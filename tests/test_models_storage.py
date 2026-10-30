"""Hand-made cases with known answers for the model and the CSV log."""

from datetime import datetime, timezone

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
