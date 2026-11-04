"""Analytical views over the logged history (see storage.SnapshotStore).

Every function takes the DataFrame returned by `SnapshotStore().load()` and
returns a new table or value; nothing here calls the API or changes the
input. Three categories from the brief are covered:

- Trend over time:         `metric_trend`, `trend_summary`
- Cross-location compare:  `latest_by_location`, `rank_locations`,
                           `extremes`
- Derived metric:          `add_comfort_index` (the API has no comfort score),
                           `feels_like_gap` (feels-like minus actual temp),
                           `daily_range` (the API has no daily high/low)
"""
import pandas as pd

from .models import comfort_index

# Metrics a user can rank or chart by, with a display label and unit.
METRICS = {
    "temperature": ("Temperature", "°C"),
    "feels_like": ("Feels like", "°C"),
    "humidity": ("Humidity", "%"),
    "wind_speed": ("Wind speed", "m/s"),
    "pressure": ("Pressure", "hPa"),
    "comfort_index": ("Comfort index", "/100"),
}


def _check_metric(metric: str) -> None:
    if metric not in METRICS:
        raise ValueError(f"Unknown metric {metric!r}; choose one of "
                         f"{', '.join(METRICS)}.")


# ---- derived metric ---------------------------------------------------


def add_comfort_index(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `df` with a `comfort_index` column (0-100).

    Uses the same formula as `WeatherSnapshot.comfort_index`, so a value
    on the Live page always matches the same reading in the history.
    """
    out = df.copy()
    out["comfort_index"] = [
        comfort_index(t, h, w)
        for t, h, w in zip(out["temperature"], out["humidity"],
                           out["wind_speed"])
    ]
    return out


# ---- cross-location comparison ----------------------------------------


def latest_by_location(df: pd.DataFrame) -> pd.DataFrame:
    """The most recent reading for each location, with its comfort index."""
    if df.empty:
        return add_comfort_index(df)
    latest = (df.sort_values("fetched_at")
                .groupby("location", as_index=False)
                .tail(1))
    return add_comfort_index(latest).reset_index(drop=True)


def rank_locations(df: pd.DataFrame, metric: str = "temperature",
                   highest_first: bool = True) -> pd.DataFrame:
    """Rank locations by their latest value of `metric`.

    Returns columns `rank`, `location`, `<metric>`, `fetched_at`; rank 1 is
    the highest value (or the lowest, if `highest_first` is False).
    """
    _check_metric(metric)
    latest = latest_by_location(df)
    ranked = (latest.sort_values(metric, ascending=not highest_first)
                    .reset_index(drop=True))
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return ranked[["rank", "location", metric, "fetched_at"]]


def extremes(df: pd.DataFrame) -> dict[str, tuple[str, float]]:
    """Headline extremes across locations, using each one's latest reading.

    Returns e.g. {"Hottest": ("Dubai, AE", 32.0), ...}; empty if no data.
    """
    latest = latest_by_location(df)
    if latest.empty:
        return {}
    picks = {
        "Hottest": ("temperature", "idxmax"),
        "Coldest": ("temperature", "idxmin"),
        "Windiest": ("wind_speed", "idxmax"),
        "Most humid": ("humidity", "idxmax"),
        "Most comfortable": ("comfort_index", "idxmax"),
        "Least comfortable": ("comfort_index", "idxmin"),
    }
    result = {}
    for title, (column, how) in picks.items():
        row = latest.loc[getattr(latest[column], how)()]
        result[title] = (row["location"], float(row[column]))
    return result


# ---- trend over time ---------------------------------------------------


def metric_trend(df: pd.DataFrame, locations: list[str],
                 metric: str = "temperature") -> pd.DataFrame:
    """Time series of `metric` for the chosen locations, oldest first.

    Returns columns `fetched_at`, `location`, `<metric>` — the long format
    Plotly expects for one line per location.
    """
    _check_metric(metric)
    data = add_comfort_index(df) if metric == "comfort_index" else df
    subset = data[data["location"].isin(locations)]
    return (subset.sort_values("fetched_at")
                  [["fetched_at", "location", metric]]
                  .reset_index(drop=True))


def trend_summary(df: pd.DataFrame, location: str,
                  metric: str = "temperature") -> dict | None:
    """First/last/min/max/mean of `metric` for one location.

    `change` is last minus first, so a positive number means it got warmer
    (or windier, etc.) over the logged period. Returns None if the location
    has no history.
    """
    series = metric_trend(df, [location], metric)
    if series.empty:
        return None
    values = series[metric]
    return {
        "location": location,
        "metric": metric,
        "samples": len(series),
        "first_at": series["fetched_at"].iloc[0],
        "last_at": series["fetched_at"].iloc[-1],
        "first": float(values.iloc[0]),
        "last": float(values.iloc[-1]),
        "change": round(float(values.iloc[-1] - values.iloc[0]), 1),
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": round(float(values.mean()), 1),
    }


def feels_like_gap(df: pd.DataFrame) -> pd.DataFrame:
    """Average feels-like minus actual temperature per location (°C).

    Negative means wind makes a place feel colder than the thermometer
    says; positive means humidity makes it feel warmer. Sorted from most
    negative to most positive, with the number of readings behind each.
    """
    columns = ["location", "avg_gap", "samples"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    data = df.assign(gap=df["feels_like"] - df["temperature"])
    out = (data.groupby("location")["gap"]
               .agg(["mean", "count"])
               .reset_index()
               .rename(columns={"mean": "avg_gap", "count": "samples"}))
    out["avg_gap"] = out["avg_gap"].round(1)
    return out.sort_values("avg_gap").reset_index(drop=True)[columns]

# Daily temperature range per location, for charting or table display.

def daily_range(df: pd.DataFrame) -> pd.DataFrame:
    """Min, max and range of temperature per location per UTC day."""
    columns = ["location", "date", "min_temp", "max_temp", "range"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    data = df.assign(date=df["fetched_at"].dt.tz_convert("UTC").dt.date)
    out = (data.groupby(["location", "date"])["temperature"]
               .agg(["min", "max"])
               .reset_index()
               .rename(columns={"min": "min_temp", "max": "max_temp"}))
    out["range"] = out["max_temp"] - out["min_temp"]
    return out.sort_values(["location", "date"]).reset_index(drop=True)[columns]
