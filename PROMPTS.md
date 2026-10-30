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
