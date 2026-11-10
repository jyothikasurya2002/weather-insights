"""Delivery-risk rules checked with hand-made readings and known answers."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from weather_app.logistics import (
    VEHICLES,
    Bike,
    RiskLevel,
    Truck,
    Van,
    assess_route,
    best_departure,
    condition_level,
    departure_options,
    description_level,
    hub_reliability,
    nearest_step,
)
from weather_app.models import WeatherSnapshot

START = datetime(2026, 11, 10, 0, tzinfo=timezone.utc)


def reading(city="Madrid", temp=15.0, wind=2.0, description="clear sky",
            condition_id=800, visibility=10000.0, gust=None, rain=None,
            snow=None, hours=0):
    return WeatherSnapshot(
        city=city, country="ES", temperature=temp, feels_like=temp,
        humidity=60, wind_speed=wind, pressure=1013,
        description=description,
        fetched_at=START + timedelta(hours=hours),
        condition_id=condition_id, visibility=visibility, wind_gust=gust,
        rain_mm_h=rain, snow_mm_h=snow)


@pytest.mark.parametrize("code, level", [
    (800, RiskLevel.GREEN),     # clear
    (804, RiskLevel.GREEN),     # overcast
    (300, RiskLevel.YELLOW),    # drizzle
    (500, RiskLevel.YELLOW),    # light rain
    (501, RiskLevel.ORANGE),    # moderate rain
    (502, RiskLevel.RED),       # heavy rain
    (511, RiskLevel.RED),       # freezing rain
    (600, RiskLevel.ORANGE),    # light snow
    (602, RiskLevel.RED),       # heavy snow
    (611, RiskLevel.RED),       # sleet
    (711, RiskLevel.YELLOW),    # smoke
    (741, RiskLevel.ORANGE),    # fog
    (211, RiskLevel.RED),       # thunderstorm
])
def test_condition_codes(code, level):
    assert condition_level(code) == level


@pytest.mark.parametrize("text, level", [
    ("clear sky", RiskLevel.GREEN),
    ("light rain", RiskLevel.YELLOW),
    ("moderate rain", RiskLevel.ORANGE),
    ("heavy intensity rain", RiskLevel.RED),
    ("heavy intensity drizzle", RiskLevel.YELLOW),
    ("fog", RiskLevel.ORANGE),
    ("smoke", RiskLevel.YELLOW),
    ("thunderstorm with rain", RiskLevel.RED),
])
def test_description_fallback_for_old_rows(text, level):
    assert description_level(text) == level


def test_clear_calm_day_is_green():
    result = Van().assess(reading())
    assert result.level == RiskLevel.GREEN
    assert result.reasons == []
    assert result.trip_hours(10) == (10, 10)


def test_worst_factor_wins_and_reasons_are_worst_first():
    result = Van().assess(reading(description="light rain",
                                  condition_id=500, visibility=800))
    assert result.level == RiskLevel.RED            # visibility < 1 km
    assert result.reasons[0] == "Visibility 0.8 km"
    assert "Light rain" in result.reasons


def test_old_row_without_code_uses_description():
    result = Van().assess(reading(description="fog", condition_id=None,
                                  visibility=None))
    assert result.level == RiskLevel.ORANGE


def test_measured_rain_raises_the_level():
    light = reading(description="light rain", condition_id=500)
    assert Van().assess(light).level == RiskLevel.YELLOW
    downpour = reading(description="light rain", condition_id=500, rain=8.0)
    assert Van().assess(downpour).level == RiskLevel.RED


def test_freezing_with_precipitation_is_red():
    icy = reading(temp=-1.0, description="light snow", condition_id=600)
    assert Van().assess(icy).level == RiskLevel.RED
    cold_dry = reading(temp=-1.0)
    assert Van().assess(cold_dry).level == RiskLevel.YELLOW


def test_heat():
    assert Van().assess(reading(temp=36)).level == RiskLevel.YELLOW
    assert Van().assess(reading(temp=41)).level == RiskLevel.ORANGE


def test_truck_is_more_sensitive_to_wind():
    windy = reading(wind=10.5)
    assert Van().assess(windy).level == RiskLevel.YELLOW
    assert Truck().assess(windy).level == RiskLevel.ORANGE


def test_gusts_count_too():
    gusty = reading(wind=4.0, gust=22.0)
    result = Van().assess(gusty)
    assert result.level == RiskLevel.ORANGE
    assert result.reasons == ["Gusts 22.0 m/s"]


def test_bike_gets_rain_one_level_worse_but_not_fog():
    rain = reading(description="light rain", condition_id=500)
    assert Van().assess(rain).level == RiskLevel.YELLOW
    assert Bike().assess(rain).level == RiskLevel.ORANGE
    fog = reading(description="fog", condition_id=741)
    assert Bike().assess(fog).level == Van().assess(fog).level


def test_vehicles_are_profiles():
    assert set(VEHICLES) == {"Van", "Truck", "Bike"}
    assert repr(VEHICLES["Truck"]) == "Truck()"


def test_delay_ranges_grow_with_level():
    highs = [level.delay_range[1] for level in RiskLevel]
    assert highs == sorted(highs)
    assert max(RiskLevel.YELLOW, RiskLevel.RED) == RiskLevel.RED


# ---- routes ---------------------------------------------------------------

# Origin: clear all day. Destination: thunderstorm for the first 9 hours.
ORIGIN = [reading("Madrid", hours=h) for h in range(0, 48, 3)]
DESTINATION = [
    reading("Lisbon", hours=h,
            description="thunderstorm" if h < 9 else "clear sky",
            condition_id=211 if h < 9 else 800)
    for h in range(0, 48, 3)
]


def test_nearest_step():
    assert nearest_step(ORIGIN, START + timedelta(hours=4)).fetched_at == \
        START + timedelta(hours=3)


def test_route_uses_destination_at_arrival():
    trip = assess_route(Van(), ORIGIN, DESTINATION, START, normal_hours=6)
    assert trip.origin.level == RiskLevel.GREEN
    assert trip.destination.level == RiskLevel.RED   # arrives at 06:00
    assert trip.level == RiskLevel.RED
    assert trip.arrival == START + timedelta(hours=6)
    assert trip.trip_hours() == (9.0, 12.0)


def test_best_departure_avoids_the_storm():
    options = departure_options(Van(), ORIGIN, DESTINATION, normal_hours=6)
    best = best_departure(options)
    assert best.level == RiskLevel.GREEN
    assert best.departure == START + timedelta(hours=3)  # arrives 09:00
    # Every departure's arrival is inside the destination forecast.
    assert all(o.arrival <= DESTINATION[-1].fetched_at for o in options)


def test_best_departure_with_no_options():
    assert best_departure([]) is None


# ---- reliability over the log ---------------------------------------------


def test_hub_reliability():
    rows = [r.to_record() | {"location": r.label} for r in [
        reading("Paris", description="fog", condition_id=741),
        reading("Paris"),
        reading("Paris"),
        reading("Paris", description="thunderstorm", condition_id=211),
        reading("Cairo"),
    ]]
    df = pd.DataFrame(rows)
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    table = hub_reliability(df, Van()).set_index("location")
    assert table.loc["Paris, ES", "readings"] == 4
    assert table.loc["Paris, ES", "Green"] == 50.0
    assert table.loc["Paris, ES", "disrupted"] == 50.0
    assert table.loc["Cairo, ES", "disrupted"] == 0.0
    assert list(table.index) == ["Paris, ES", "Cairo, ES"]  # worst first


def test_hub_reliability_empty():
    empty = pd.DataFrame(columns=["location", "fetched_at"])
    assert hub_reliability(empty, Van()).empty
