"""Fetch a list of cities once and append the results to the log.

Run it a few times a day to build up history for the trend views:

    uv run collect-weather                    # default cities
    uv run collect-weather Tokyo "New York"   # specific cities
"""

import sys

from .client import APIError, OpenWeatherClient
from .config import get_api_key
from .storage import SnapshotStore

DEFAULT_CITIES = ["London", "New York", "Tokyo", "Sydney", "Dubai",
                  "Mumbai", "Paris", "Toronto", "Cairo", "Reykjavik"]


def main(argv: list[str] | None = None) -> int:
    cities = (sys.argv[1:] if argv is None else argv) or DEFAULT_CITIES
    try:
        client = OpenWeatherClient(get_api_key())
        snapshots, failures = client.fetch_many(cities)
    except (RuntimeError, APIError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    store = SnapshotStore()
    store.append_many(snapshots)

    for snapshot in snapshots:
        print(f"  logged  {snapshot}")
    for city, reason in failures.items():
        print(f"  skipped {city}: {reason}", file=sys.stderr)
    print(f"{len(snapshots)} logged, {len(failures)} skipped -> "
          f"{store.path} ({len(store)} rows total)")
    return 0 if snapshots else 1


if __name__ == "__main__":
    sys.exit(main())
