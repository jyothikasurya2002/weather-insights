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
    nearest_air,
    nearest_step,
)
from weather_app.models import AirQuality, WeatherSnapshot

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


# ---- air quality ------------------------------------------------------------


def air(aqi, hours=0, pm2_5=50.0):
    return AirQuality(aqi=aqi, pm2_5=pm2_5,
                      fetched_at=START + timedelta(hours=hours))


@pytest.mark.parametrize("aqi, van, bike", [
    (1, RiskLevel.GREEN, RiskLevel.GREEN),
    (2, RiskLevel.GREEN, RiskLevel.GREEN),
    (3, RiskLevel.GREEN, RiskLevel.YELLOW),
    (4, RiskLevel.GREEN, RiskLevel.ORANGE),
    (5, RiskLevel.YELLOW, RiskLevel.RED),
])
def test_air_quality_matters_most_for_bikes(aqi, van, bike):
    assert Van().assess(reading(), air(aqi)).level == van
    assert Truck().assess(reading(), air(aqi)).level == van
    assert Bike().assess(reading(), air(aqi)).level == bike


def test_air_quality_reason_and_no_air_data():
    result = Bike().assess(reading(), air(5, pm2_5=82.7))
    assert result.reasons == ["Air quality very poor (AQI 5, PM2.5 83 µg/m³)"]
    assert result.air.aqi == 5
    without = Bike().assess(reading())          # no air data: weather only
    assert without.level == RiskLevel.GREEN and without.air is None


def test_air_and_weather_take_the_worst():
    stormy = reading(description="thunderstorm", condition_id=211)
    assert Van().assess(stormy, air(5)).level == RiskLevel.RED
    rainy = reading(description="light rain", condition_id=500)
    assert Bike().assess(rainy, air(5)).level == RiskLevel.RED


def test_aqi_must_be_1_to_5():
    with pytest.raises(ValueError):
        AirQuality(aqi=0)


def test_nearest_air_ignores_readings_too_far_away():
    readings = [air(2, hours=0), air(5, hours=1)]
    assert nearest_air(readings, START + timedelta(hours=1)).aqi == 5
    # 10 hours past the last reading: better no data than the wrong day.
    assert nearest_air(readings, START + timedelta(hours=11)) is None
    assert nearest_air(None, START) is None


def test_route_uses_air_at_each_end():
    clean = [air(1, hours=h) for h in range(48)]
    smoggy = [air(5, hours=h) for h in range(48)]
    trip = assess_route(Bike(), ORIGIN, ORIGIN, START + timedelta(hours=12),
                        6, origin_air=clean, destination_air=smoggy)
    assert trip.origin.level == RiskLevel.GREEN
    assert trip.destination.level == RiskLevel.RED
    assert trip.destination.air.fetched_at == START + timedelta(hours=18)


def test_best_departure_never_relies_on_missing_air_data():
    # Air is very poor for the whole air forecast (first 24 h), then the
    # air data ends. Departures after that must not be offered as "safe".
    smog = [air(5, hours=h) for h in range(24)]
    options = departure_options(Bike(), ORIGIN, ORIGIN, normal_hours=3,
                                origin_air=smog, destination_air=smog)
    assert options                                      # some are covered
    assert all(o.origin.air and o.destination.air for o in options)
    assert best_departure(options).level == RiskLevel.RED


# ---- checkpoints along the route ----------------------------------------------

from weather_app.logistics import (  # noqa: E402
    Checkpoint,
    distance_km,
    route_points,
    route_warnings,
)

PARIS, LONDON = (48.8534, 2.3488), (51.5085, -0.1257)


def test_distance_km_known_value():
    assert distance_km(*PARIS, *LONDON) == pytest.approx(343, abs=3)
    assert distance_km(*PARIS, *PARIS) == 0


def test_route_points_are_evenly_spaced_on_the_line():
    points = route_points(*PARIS, *LONDON)          # ~343 km -> 2 points
    assert [round(f, 2) for f, _, _ in points] == [0.33, 0.67]
    for f, lat, lon in points:
        assert distance_km(*PARIS, lat, lon) == pytest.approx(343 * f, abs=2)
    assert route_points(*PARIS, 48.9, 2.4) == []    # short trip: none


def test_long_routes_are_capped():
    assert len(route_points(19.0, 72.8, 51.5, -0.1)) == 8  # Mumbai-London


def place(city, condition_id=800, description="clear sky", country="FR"):
    return [WeatherSnapshot(
        city=city, country=country, temperature=12, feels_like=12,
        humidity=70, wind_speed=3, pressure=1010, description=description,
        fetched_at=START + timedelta(hours=h), condition_id=condition_id,
        visibility=10000)
        for h in range(0, 48, 3)]


def test_storm_in_the_middle_makes_the_route_red():
    clear_a, clear_b = place("Paris"), place("London", country="GB")
    storm = place("Amiens", condition_id=211, description="thunderstorm")
    trip = assess_route(Van(), clear_a, clear_b, START, normal_hours=6,
                        waypoints=[(0.5, storm)], distance=340)
    assert trip.origin.level == trip.destination.level == RiskLevel.GREEN
    assert trip.level == RiskLevel.RED
    worst = trip.worst
    assert worst.name == "Amiens, FR"
    assert worst.km == 170
    assert worst.passing_at == START + timedelta(hours=3)
    assert [c.km for c in trip.checkpoints] == [0, 170, 340]


def test_checkpoint_is_judged_when_the_vehicle_passes():
    # Thunderstorm at the midpoint until 06:00, clear afterwards.
    storm, clear = (place("Amiens", 211, "thunderstorm"), place("Amiens"))
    midpoint = [s if s.fetched_at < START + timedelta(hours=6) else c
                for s, c in zip(storm, clear)]
    # A 2 h trip passes the midpoint at 01:00, a 16 h trip at 08:00.
    quick = assess_route(Van(), clear, clear, START, 2,
                         waypoints=[(0.5, midpoint)], distance=100)
    slow = assess_route(Van(), clear, clear, START, 16,
                        waypoints=[(0.5, midpoint)], distance=100)
    assert quick.level == RiskLevel.RED
    assert slow.level == RiskLevel.GREEN


def test_route_warnings():
    sea = place("", country="")
    trip = assess_route(Van(), place("Mumbai"), place("Dubai"), START, 10,
                        waypoints=[(0.5, sea)], distance=1930)
    assert trip.waypoints[0].name == "Open water"
    assert trip.waypoints[0].open_water
    warnings = route_warnings(Van(), trip)
    assert len(warnings) == 3        # too far, too fast, open sea
    assert "open sea" in warnings[2]

    fine = assess_route(Truck(), place("Paris"), place("London"), START, 6,
                        distance=343)
    assert route_warnings(Truck(), fine) == []
    assert route_warnings(Bike(), fine)   # 343 km is not a bike trip


def test_checkpoint_open_water_needs_no_name_and_no_country():
    a = Van().assess(place("Eastbourne", country="GB")[0])
    assert not Checkpoint("Eastbourne", 10, START, a).open_water
