"""Analytics checked against small hand-made tables with known answers."""

import pandas as pd
import pytest

from weather_app.analytics import (
    add_comfort_index,
    daily_range,
    extremes,
    feels_like_gap,
    latest_by_location,
    metric_trend,
    rank_locations,
    trend_summary,
)


def make_log(rows):
    """rows: (iso time, location, temperature, humidity, wind_speed)."""
    df = pd.DataFrame(rows, columns=["fetched_at", "location", "temperature",
                                     "humidity", "wind_speed"])
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    df["feels_like"] = df["temperature"]
    df["pressure"] = 1013.0
    return df


LOG = make_log([
    ("2026-11-01T06:00", "Madrid, ES", 10.0, 50, 2.0),
    ("2026-11-01T12:00", "Madrid, ES", 21.0, 45, 2.0),   # latest Madrid
    ("2026-11-01T06:00", "Oslo, NO", 1.0, 80, 9.0),
    ("2026-11-01T12:00", "Oslo, NO", 3.0, 70, 7.0),      # latest Oslo
    ("2026-11-01T12:00", "Dubai, AE", 33.0, 20, 4.0),    # only Dubai
])
EMPTY = LOG.iloc[0:0]


def test_comfort_index_column():
    df = add_comfort_index(LOG)
    # Madrid 12:00 is the ideal day (21 °C, 45 %, 2 m/s) -> 100.
    assert df.loc[1, "comfort_index"] == 100.0
    # Oslo 12:00: 18 °C off (-54), 10 % too humid (-5), 2 m/s (-4) -> 37.
    assert df.loc[3, "comfort_index"] == 37.0
    assert "comfort_index" not in LOG.columns    # input not modified


def test_latest_by_location_keeps_newest_row():
    latest = latest_by_location(LOG).set_index("location")
    assert latest.loc["Madrid, ES", "temperature"] == 21.0
    assert latest.loc["Oslo, NO", "temperature"] == 3.0
    assert len(latest) == 3


def test_rank_locations():
    ranked = rank_locations(LOG, "temperature")
    assert list(ranked["location"]) == ["Dubai, AE", "Madrid, ES",
                                        "Oslo, NO"]
    assert list(ranked["rank"]) == [1, 2, 3]
    coldest_first = rank_locations(LOG, "temperature", highest_first=False)
    assert coldest_first.iloc[0]["location"] == "Oslo, NO"


def test_rank_by_unknown_metric_raises():
    with pytest.raises(ValueError):
        rank_locations(LOG, "rainfall")


def test_extremes():
    result = extremes(LOG)
    assert result["Hottest"] == ("Dubai, AE", 33.0)
    assert result["Coldest"] == ("Oslo, NO", 3.0)
    assert result["Windiest"] == ("Oslo, NO", 7.0)
    assert result["Most comfortable"] == ("Madrid, ES", 100.0)


def test_metric_trend_filters_and_sorts():
    trend = metric_trend(LOG, ["Madrid, ES", "Oslo, NO"])
    assert len(trend) == 4
    assert trend["fetched_at"].is_monotonic_increasing
    assert set(trend["location"]) == {"Madrid, ES", "Oslo, NO"}


def test_trend_summary():
    summary = trend_summary(LOG, "Madrid, ES")
    assert summary["samples"] == 2
    assert summary["change"] == 11.0      # 10 -> 21 °C
    assert summary["min"] == 10.0 and summary["max"] == 21.0
    assert summary["mean"] == 15.5


def test_empty_log_is_handled():
    assert latest_by_location(EMPTY).empty
    assert rank_locations(EMPTY).empty
    assert extremes(EMPTY) == {}
    assert metric_trend(EMPTY, ["Madrid, ES"]).empty
    assert trend_summary(EMPTY, "Madrid, ES") is None


def test_feels_like_gap():
    df = pd.DataFrame([
        ("Toronto, CA", 10.0, 7.0),
        ("Toronto, CA", 8.0, 4.0),
        ("Mumbai, IN", 30.0, 35.0),
        ("Mumbai, IN", 28.0, 31.0),
        ("London, GB", 15.0, 15.0),
    ], columns=["location", "temperature", "feels_like"])

    result = feels_like_gap(df)

    assert list(result.columns) == ["location", "avg_gap", "samples"]
    # Toronto: gaps -3 and -4 -> -3.5; Mumbai: +5 and +3 -> +4.0.
    assert list(result["location"]) == ["Toronto, CA", "London, GB",
                                        "Mumbai, IN"]
    assert list(result["avg_gap"]) == [-3.5, 0.0, 4.0]
    assert list(result["samples"]) == [2, 1, 2]
    assert "gap" not in df.columns       # input not modified


def test_feels_like_gap_empty():
    result = feels_like_gap(EMPTY)
    assert result.empty
    assert list(result.columns) == ["location", "avg_gap", "samples"]

# Testing daily temperature range and temperature for each location

def test_daily_range():
    df = pd.DataFrame([
        ("2026-11-01T06:00", "Madrid, ES", 10.0),
        ("2026-11-01T12:00", "Madrid, ES", 18.0),
        ("2026-11-01T18:00", "Madrid, ES", 14.0),
        ("2026-11-02T12:00", "Madrid, ES", 16.0),
        ("2026-11-01T12:00", "Oslo, NO", 2.0),
        ("2026-11-01T18:00", "Oslo, NO", -1.0),
    ], columns=["fetched_at", "location", "temperature"])
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)

    result = daily_range(df)

    assert list(result.columns) == ["location", "date", "min_temp",
                                    "max_temp", "range"]
    assert len(result) == 3
    assert list(result["location"]) == ["Madrid, ES", "Madrid, ES",
                                        "Oslo, NO"]
    assert list(result["range"]) == [8.0, 0.0, 3.0]
    assert result.loc[0, "min_temp"] == 10.0
    assert result.loc[0, "max_temp"] == 18.0
    assert result.loc[2, "min_temp"] == -1.0    # Oslo
    assert result.loc[2, "max_temp"] == 2.0


def test_daily_range_empty():
    result = daily_range(EMPTY)
    assert result.empty
    assert list(result.columns) == ["location", "date", "min_temp",
                                    "max_temp", "range"]
