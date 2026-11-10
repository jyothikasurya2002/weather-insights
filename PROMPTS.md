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

## Feature: Streamlit app (Live Conditions, Trends, Compare, How to use)

**Asked:** "Let's continue with the next process": build `app.py` on top of
the client, storage and analytics modules, meeting the rubric's Streamlit
requirements (2+ views, real interaction, 2+ labelled charts, usable by a
stranger, key never shown).

**Got:** `app.py` with four pages chosen from the sidebar:
- **Live Conditions:** a card per tracked city (icon, temperature, feels-like
  difference, comfort score, humidity, wind, pressure, "updated X ago"), a
  "Fetch latest for all tracked cities" button, and a "Load sample cities"
  button on first run.
- **Trends:** pick cities and a metric to get a Plotly line chart over time
  (axis labels with units) and summary cards (last, change, low/high/avg).
- **Compare:** extremes cards, a ranking bar chart by any metric, a world
  map coloured by comfort index, and a table of the latest readings.
- **How to use:** instructions, the comfort-index formula with a worked
  example, and a CSV download of the log.
- Sidebar: add a city (validated, fetched and logged immediately), remove
  tracked cities, API-key status (never the key itself), log size.

**Checked:** with Streamlit's `AppTest` (headless):
- All 4 pages render with no exceptions on our real log.
- Adding `"   "` and `"12345"` shows input warnings without calling the API.
  `"Atlantisxyzq"` shows the "city not found" error. `"Lisbon"` is fetched,
  logged and added to the tracked list.
- With no API key: a clear error in the sidebar, and the fetch buttons are
  disabled. Trends and Compare still work from the log.
- "Fetch latest" logged all 11 tracked cities.

**Kept / changed / rejected:**
- Changed the starter's two-page layout to four pages, because one
  "Analytics" page with everything on it was hard to read.
- Tracked-city additions are queued in `session_state` and applied at the
  top of the script, because Streamlit raises an error if a widget's value
  is changed after the widget is drawn.
- Rejected a °C/°F toggle for now. It would have to be threaded through
  every chart and table for little benefit.

---

## Feature: README rewrite (Ruben, Task C)

**Asked:** Claude to check my README against the finished app and give a
complete, corrected version, because my "How to use the app" section was
written before the app existed.

**Got:** a full README draft:
- "How to use the app" rewritten to cover the sidebar (add a city, tracked
  cities, key status) and all four pages: Live Conditions, Trends, Compare
  and How to use.
- Small fixes to "Project structure" (added `variables.env.example`,
  corrected the `models.py` description, described `tests/`).
- The stray ```` line at the end of my first version removed.

**Checked:**
- Ran `uv run streamlit run app.py` and clicked through every page. Every
  button and page name in the new section matches the app.
- Tried adding `Madrid` and `12345` in the sidebar: Madrid was added, and
  `12345` showed a warning instead of crashing, as the README says.
- Previewed the README on GitHub to check headings and code blocks render.

**Kept / changed / rejected:**
- Kept my own Setup, Run the tests, Run the app and Collecting data
  sections, which were already correct after my fresh-install test.
- Changed "How to use the app" to the new version, because my draft
  described only three pages and missed the sidebar, the map, the table
  and the CSV download.
- Changed the `models.py` line in Project structure, which mentioned
  "locations", a class the project doesn't have.

---

## Feature: feels-like gap analytics (Victória, Task D)

**Asked:** Followed the Task D brief and asked Claude Code to set up the
repo, add `feels_like_gap` to `analytics.py` with its tests, and run them.

**Got:**
- `feels_like_gap(df)` in `src/weather_app/analytics.py`: average of
  `feels_like - temperature` per location (rounded to 1 decimal) and the
  number of readings, sorted from most negative to most positive. Returns
  an empty table with the same 3 columns if there is no data.
- Added it to the "Derived metric" line in the module docstring.
- Two tests in `tests/test_analytics.py`: the worked example from the brief
  and the empty-input case.

**Checked:**
- Worked example by hand: Toronto gaps −3 and −4 → −3.5; Mumbai +5 and +3
  → +4.0; London 0.0. The test confirms the order and the values, and that
  the input DataFrame is not modified.
- `uv run pytest`: 33 tests pass.
- Ran it on our real log (Oct 30 – Nov 4): Reykjavik −3.6 and Paris −1.8 at
  the top (wind makes them feel colder), Dubai +3.5 and Mumbai +4.8 at the
  bottom (humidity makes them feel warmer), which matches what we expected.

**Kept / changed / rejected:**
- Kept the function pure (DataFrame in, DataFrame out) like the other
  analytics, using `df.assign` so the input is not changed.
- Expanded the one-line docstring to say what a negative or positive gap
  means, since that is the part a reader needs to interpret the numbers.

---
## Feature: daily temperature range analytics (Enrique, Task B)

*Asked:* Followed the Task B brief and used Claude to help write
daily_range in analytics.py and its tests, and to fix my setup when
the tests could not find the weather_app module.

*Got:*
- daily_range(df) in src/weather_app/analytics.py: the lowest and
  highest temperature, and the range (max − min), for each location on
  each UTC day, sorted by location then date. Returns an empty table with
  the same 5 columns if there is no data.
- Added it to the "Derived metric" line in the module docstring, after
  Victoria's feels_like_gap.
- Two tests in tests/test_analytics.py: the worked example from the
  brief and the empty-input case.

*Checked:*
- Worked example by hand: Madrid on Nov 1 (10, 18, 14 °C) → min 10,
  max 18, range 8. Madrid on Nov 2 (one reading) → range 0. Oslo on Nov 1
  (2, −1 °C) → range 3. The test confirms these values and the order.
- uv run pytest: 35 tests pass.
- Ran it on our real log: New York had the biggest daily range, on Nov 3
  (11.3 → 19.1 °C, a range of 7.8 °C).

*Kept / changed / rejected:*
- Kept the function pure (DataFrame in, DataFrame out) like the other
  analytics, using df.assign so the input is not changed.
- Changed the comment above my test, which wrongly said the function also
  calculates an average temperature.

---

## Feature: client error tests for timeout and HTTP 403 (Juan, Task A)

**Asked:** Followed the Task A brief, whose reference solution was written
with Claude, to add two tests to `tests/test_client.py`: one for a request
timeout and one for an HTTP 403 response.

**Got:**
- `test_timeout_raises_network_error`: the fake session raises
  `requests.Timeout`, and the test checks that `fetch_current` raises our
  `NetworkError`.
- `test_403_raises_generic_api_error`: the fake session returns
  `FakeResponse(403, {})`, and the test checks that the error is exactly
  `APIError`, not one of its subclasses.
- `APIError` added to the import list at the top of the file.

**Checked:**
- Read `JSONAPIClient._get`: it catches `requests.Timeout` and raises
  `NetworkError` instead, so the first test matches the code.
- Read `_raise_for_status`: it handles 200, 401, 404, 429 and 5xx. 403
  matches none of them, so it reaches the last line and raises a plain
  `APIError("Unexpected response from the server (HTTP 403).")`.
- `uv run pytest`: 37 tests pass (35 existing + my 2).

**Kept / changed / rejected:**
- Kept `info.type is APIError` in the 403 test, because
  `pytest.raises(APIError)` alone would also pass if a subclass such as
  `AuthenticationError` were raised.
- Kept both tests on the fake session instead of the real API, so they run
  without a network connection or API key, like the other client tests.

---

## Feature: teammates' analytics in the app, and a rubric review

**Asked:** "Build the teammates' functions into the app, and check the app
against the rubric and change whatever needs changing to get the highest
score."

**Got:**
- Trends page: a **Daily temperature range** chart using Enrique's
  `daily_range`, with a floating bar per day from the low to the high,
  plus a caption naming the widest swing.
- Compare page: a **"Does it feel colder or warmer than it is?"** chart
  using Victoria's `feels_like_gap`, coloured blue (feels colder) to red
  (feels warmer).
- Trends now starts with the tracked cities that have the most history.
  Before, it picked the first three alphabetically, which included a city
  with a single reading, so the first chart showed one dot.
- `collect-weather` prints cities hottest-first with
  `sorted(snapshots, reverse=True)`, so `WeatherSnapshot.__lt__` is used
  by the program itself, not only by the tests.
- README "How to use the app" and the in-app How to use page updated to
  describe the two new charts.

**Checked:**
- Rendered all four pages headlessly with Streamlit's `AppTest`: no
  exceptions, and both new sections appear. Took screenshots to check the
  charts look right.
- The widest daily swing caption says New York on Nov 3, 11.3 → 19.1 °C,
  which matches running `daily_range` on the log directly.
- Clean-clone test: cloned the repo from GitHub into an empty folder and
  followed only the README. `uv sync` and `uv run pytest` (37 passed)
  worked. With the placeholder key the app and collector showed a clear
  "key is not set" message instead of crashing, and with a real key all
  four pages loaded.

**Kept / changed / rejected:**
- Hid zero-height bars (days with a single reading) in the daily range
  chart and explained why in the caption, instead of drawing empty bars.
- Rejected adding a separate page for the teammates' metrics: they fit
  next to the related views (trend and comparison), which is easier to
  follow.

---

## Feature: delivery-risk business use case (logistics)

**Asked:** After our review, the professor asked us to use the insights to
solve a business use case. We chose logistics: "green, yellow, orange and
red signals based on the time delay the weather causes, with weather as
the main role." We asked for the full version, including the 5-day
forecast.

**Got:**
- `logistics.py`:
  - `RiskLevel` (an ordered `IntEnum`: green → red, each with an emoji,
    colour, advice and delay range).
  - `RiskFactor` and `RiskAssessment` dataclasses.
  - A `VehicleProfile` base class with `Van`, `Truck` and `Bike`
    subclasses that override the wind, gust and heat limits. `Bike` also
    overrides `_adjust` to make rain one level worse.
  - Route functions (`assess_route`, `departure_options`,
    `best_departure`) and `hub_reliability` over the log.
- `client.py`: `fetch_forecast()` for the free 5-day / 3-hour forecast,
  sharing validation and 404 handling with `fetch_current` through a new
  `_get_city` helper.
- `models.py`: `WeatherSnapshot` now also keeps the condition code,
  visibility, wind gust and rain/snow in mm per hour, which the API was
  already sending. It also has `from_forecast` and `from_record`
  constructors.
- `storage.py`: the log has 5 new columns. An old log file is upgraded in
  place the first time it is written to, without losing rows.
- A new first page in the app, **🚚 Delivery Risk**, with a dispatch
  board, route planner, 5-day hub outlook and hub reliability chart. The
  How to use page explains the rules, and the README has a new section.
- 42 new tests (79 in total).

**Checked:**
- Called the real `/forecast` endpoint first to confirm the response
  shape (40 steps, `rain.3h`, `wind.gust`, `visibility`, `weather[0].id`)
  before writing the parser.
- Ran the rules on our real 176-row log. Paris fog → 🟠, Mumbai smoke →
  🟡, New York "heavy intensity rain" → 🔴, and a bike is stricter than a
  van, as intended.
- Found and fixed a rounding issue: "disrupted" showed 12.4 % instead of
  12.5 % because it was summed after rounding.
- Rendered every page with Streamlit's `AppTest` and the real API key: no
  exceptions. Paris → London by truck came out 🟡 (light rain at both
  ends), and the planner suggested leaving at 06:00 the next day for 🟢.
- Checked that rendering the app does not change `weather_log.csv`.
- `uv run pytest`: 79 passed.

**Kept / changed / rejected:**
- Kept the thresholds as clearly labelled assumptions (in the module
  docstring, How to use page and README) instead of presenting them as
  real delay data, which we don't have.
- Kept forecasts out of the log, because the log is for observations
  only, and mixing in predictions would distort the trends.
- Rejected a machine-learning delay model: we have no real delivery
  times to train on, so rules we can explain are more honest.
- Old log rows have no condition code, so they are judged from their
  description text. This is a documented fallback rather than dropping
  history.

---
