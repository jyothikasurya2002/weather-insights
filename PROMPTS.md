# AI collaboration log

One entry per feature/class an AI agent helped with, in the order we worked
on them. Kept running as we go — not reconstructed at the end.

Agent used: Claude Code (Claude Opus 5.5).

---

## Feature: API client, data model, CSV logging, collector script

**Asked:** "Go through this group project and tell me what needs to be done
to rank highest... let me do everything with the help of you according to
the rubric." Then asked it to start with the foundation so data logging
could begin on day one.

**Got:**
- `src/weather_app/client.py`: `JSONAPIClient` (generic base: builds the
  request, maps HTTP status codes to exceptions) and `OpenWeatherClient`
  (subclass: base URL, `__api_key`, `validate_city`, `fetch_current`,
  `fetch_many`). One exception class per failure mode
  (`InvalidInputError`, `LocationNotFoundError`, `AuthenticationError`,
  `RateLimitError`, `NetworkError`).
- `src/weather_app/models.py`: `WeatherSnapshot` with `@property`
  values `comfort_index`, `feels_like_delta`, `temperature_f`, `label`, and
  `__repr__`, `__str__`, `__eq__`/`__hash__`, `__lt__`.
- `src/weather_app/storage.py`: `SnapshotStore` that appends to
  `data/weather_log.csv` and loads it back as a pandas DataFrame.
- `src/weather_app/collect.py`: `collect-weather` command to log a set of
  cities in one go.
- `config.py` changed to read the key lazily via `get_api_key()`.
- Tests in `tests/test_client.py` and `tests/test_models_storage.py`.

**Checked:**
- `uv run pytest`: 23 tests pass. They use a fake HTTP session, so they
  check every error path (404/401/429/5xx/connection error) without a
  network connection.
- Hand-computed comfort index: 22 °C, 70 % humidity, 7 m/s wind should be
  100 − 3 − 5 − 4 = 88, and the test confirms it.
- Confirmed the API key does not appear in `repr(client)` or in network
  error messages (requests' own messages include the URL with `appid=`).
- Ran `collect-weather` with no key: it printed a clear message instead of
  a traceback.

**Kept / changed / rejected:**
- Kept the overall design.
- Changed `config.py` from raising at import time to a `get_api_key()`
  function, because raising at import made the tests and the Streamlit app
  crash before they could show a friendly error.
- Rejected copying `summary.md`'s `ValueError`-for-everything pattern in
  favour of distinct exception classes, so the UI can show a different
  message for each failure.

---

## Feature: analytics views (trend, comparison, comfort index)

**Asked:** "Start analytics" — the three rubric categories (trend over
time, cross-location comparison, derived metric), leaving `daily_range` and
`feels_like_gap` for teammates.

**Got:** `src/weather_app/analytics.py`:
- Derived metric: `add_comfort_index` (adds a 0-100 comfort column using
  the same `comfort_index` formula as `WeatherSnapshot`).
- Comparison: `latest_by_location`, `rank_locations(metric)`, `extremes`
  (hottest / coldest / windiest / most humid / most and least comfortable).
- Trend: `metric_trend(locations, metric)` and `trend_summary` (first,
  last, change, min, max, mean for one location).
- `tests/test_analytics.py` with a 5-row hand-made log.
- Small fix in `storage.py`: an empty log now still has a `location`
  column, so the analytics don't crash on a fresh install.

**Checked:**
- 8 new tests, all against hand-computed answers. For example, Oslo at
  3 °C / 70 % / 7 m/s should score 100 − 54 − 5 − 4 = 37, and the test
  confirms it. Madrid going 10 → 21 °C should give `change` = 11 and
  `mean` = 15.5.
- Ran the functions on our real 20-row log. Rankings looked plausible:
  Sydney (≈20 °C) was most comfortable, Reykjavik coldest and windiest.

**Kept / changed / rejected:**
- Renamed the first draft's `temperature_trend` to `metric_trend`, because
  it works for any metric, not just temperature.
- Kept the functions pure (DataFrame in, DataFrame out) so they can be
  tested without Streamlit or the API.

---
