"""Hand-made cases with known answers for the model and the CSV log."""

from datetime import datetime, timezone

import pandas as pd

from weather_app.models import WeatherSnapshot, comfort_index
from weather_app.storage import SnapshotStore


def make_snapshot(city="Madrid", temp=22.0, feels=21.0, humidity=40.0,
                  wind=3.0, hour=12):
    return WeatherSnapshot(
        city=city, country="ES", temperature=temp, feels_like=feels,
        humidity=humidity, wind_speed=wind, pressure=1015,
        description="clear sky",
        fetched_at=datetime(2026, 11, 1, hour, tzinfo=timezone.utc),
    )


def test_comfort_index_known_values():
    assert comfort_index(21, 45, 2) == 100.0     # ideal day
    # 1 °C off (-3), 10 % too humid (-5), 2 m/s too windy (-4)
    assert comfort_index(22, 70, 7) == 88.0
    assert comfort_index(-20, 95, 25) == 0.0     # clamped at 0


def test_properties():
    snap = make_snapshot(temp=20.0, feels=17.5)
    assert snap.feels_like_delta == -2.5
    assert snap.temperature_f == 68.0
    assert snap.label == "Madrid, ES"


def test_sorting_and_equality():
    hot = make_snapshot("Seville", temp=30)
    cold = make_snapshot("Oslo", temp=2)
    assert sorted([hot, cold]) == [cold, hot]
    assert make_snapshot() == make_snapshot()
    assert make_snapshot(hour=12) != make_snapshot(hour=13)
    assert len({make_snapshot(), make_snapshot()}) == 1


def test_store_round_trip(tmp_path):
    store = SnapshotStore(tmp_path / "log.csv")
    assert len(store) == 0
    assert store.load().empty

    store.append_many([make_snapshot(hour=9), make_snapshot(hour=15)])
    store.append(make_snapshot("Oslo", temp=2, hour=12))

    df = store.load()
    assert len(store) == 3
    assert list(df["city"]) == ["Madrid", "Oslo", "Madrid"]  # time order
    assert df["fetched_at"].dt.tz is not None
    assert df.loc[1, "location"] == "Oslo, ES"


def test_old_log_is_upgraded_without_losing_rows(tmp_path):
    path = tmp_path / "log.csv"
    path.write_text(
        "fetched_at,city,country,temperature,feels_like,humidity,"
        "wind_speed,pressure,description,icon,lat,lon\n"
        "2026-11-01T09:00:00+00:00,Paris,FR,10.0,9.0,90.0,2.0,1010.0,"
        "fog,50d,48.85,2.35\n", encoding="utf-8")
    store = SnapshotStore(path)
    assert store.load()["condition_id"].isna().all()   # old file loads

    new = make_snapshot(hour=15)
    new.condition_id, new.visibility = 800, 10000.0
    store.append(new)

    df = store.load()
    assert len(df) == 2
    assert df.loc[0, "description"] == "fog"           # old row intact
    assert pd.isna(df.loc[0, "condition_id"])
    assert df.loc[1, "condition_id"] == 800
    back = WeatherSnapshot.from_record(df.loc[1])
    assert back == new and back.condition_id == 800
    assert WeatherSnapshot.from_record(df.loc[0]).condition_id is None
