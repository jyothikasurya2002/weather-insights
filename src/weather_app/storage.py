"""Append fetched snapshots to a CSV log and load them back as a table.

The free OpenWeatherMap tier has no history, so this log *is* our time
series: every successful fetch adds one timestamped row.
"""

import csv
from pathlib import Path

import pandas as pd

from .config import LOG_FILE
from .models import WeatherSnapshot

COLUMNS = ["fetched_at", "city", "country", "temperature", "feels_like",
           "humidity", "wind_speed", "pressure", "description", "icon",
           "lat", "lon"]


class SnapshotStore:
    """A CSV file of WeatherSnapshot rows, one per successful fetch."""

    def __init__(self, path: Path | str = LOG_FILE):
        self.path = Path(path)

    def _ensure_file(self) -> None:
        """Create the folder and the header row the first time we write."""
        if self.path.exists() and self.path.stat().st_size > 0:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=COLUMNS).writeheader()

    def append(self, snapshot: WeatherSnapshot) -> None:
        self.append_many([snapshot])

    def append_many(self, snapshots: list[WeatherSnapshot]) -> int:
        """Append snapshots to the log and return how many were written."""
        if not snapshots:
            return 0
        self._ensure_file()
        with self.path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            for snapshot in snapshots:
                writer.writerow(snapshot.to_record())
        return len(snapshots)

    def load(self) -> pd.DataFrame:
        """Return the whole log, with `fetched_at` parsed as UTC datetimes.

        Returns an empty table (with the right columns) if nothing has been
        logged yet, so callers never need a special case for a new install.
        """
        if not self.path.exists() or self.path.stat().st_size == 0:
            return pd.DataFrame(columns=COLUMNS + ["location"])
        df = pd.read_csv(self.path, keep_default_na=False,
                         na_values={"lat": [""], "lon": [""]})
        df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True,
                                          format="ISO8601")
        df["location"] = df["city"].where(
            df["country"] == "", df["city"] + ", " + df["country"])
        return df.sort_values("fetched_at").reset_index(drop=True)

    def __len__(self) -> int:
        """Number of logged snapshots (rows, not counting the header)."""
        if not self.path.exists():
            return 0
        with self.path.open(encoding="utf-8") as f:
            return max(0, sum(1 for _ in f) - 1)

    def __repr__(self) -> str:
        return f"SnapshotStore({str(self.path)!r}, rows={len(self)})"
