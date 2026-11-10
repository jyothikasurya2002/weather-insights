# Weather Insights

## What this app does

Weather Insights fetches live weather for any cities you choose from the
OpenWeatherMap API. Every fetch is saved to a log file, so the app builds
its own weather history over time. That history shows how conditions
change, each city's daily temperature range, which cities are hottest,
coldest or windiest right now, which ones feel colder or warmer than the
thermometer says, and a 0–100 comfort score that combines temperature,
humidity and wind.

### Business use case: weather-driven delivery risk

The main use of these insights is for a **logistics team**. Each city is
a delivery hub, and weather is turned into a traffic-light signal with an
estimated delay:

| Signal | Meaning | Extra trip time |
|---|---|---|
| 🟢 Green | normal operations | none |
| 🟡 Yellow | minor delays: allow extra time | +10–20 % |
| 🟠 Orange | significant delays: reschedule time-critical deliveries | +25–50 % |
| 🔴 Red | unsafe: hold or reroute | +50–100 % |

The signal depends on rain and snow, visibility, wind, gusts and
temperature (ice and heat), and on the **vehicle**: a high-sided truck is
more sensitive to wind, and a bike courier to rain, wind and heat. The
app answers four questions:

- **Which hubs can ship right now?** (dispatch board)
- **Is this route safe, and when is the best time to leave?** (route
  planner, using the 5-day forecast)
- **What do the next 5 days look like for a hub?** (hub outlook)
- **Which hubs are most often disrupted by weather?** (hub reliability,
  from our own logged history)

The thresholds and delay ranges are our own rule-based assumptions, based
on common road-safety guidance (for example, gale force starts at
17 m/s). They have not been calibrated on real delivery data.

## Setup

1. **Install uv** (it installs Python and the project's packages):
   - Mac/Linux:
     ```bash
     curl -LsSf https://astral.sh/uv/install.sh | sh
     ```
   - Windows (PowerShell):
     ```powershell
     powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
     ```
2. **Download the project and install its packages:**
   ```bash
   git clone https://github.com/jyothikasurya2002/weather-insights.git
   cd weather-insights
   uv sync
   ```
3. **Get a free OpenWeatherMap API key:** sign up at
   https://openweathermap.org, confirm your email, then click your name
   (top right) → *My API keys*. A new key can take **up to 2 hours** to
   start working. Until then, requests fail with "The API key was rejected".
4. **Add your key:**
   ```bash
   cp variables.env.example variables.env
   ```
   Open `variables.env` and replace `your_key_here` with your key.
   `variables.env` is listed in `.gitignore`. **Never commit it**, because
   anyone who sees the key can use it.

## Run the tests

```bash
uv run pytest
```

The tests use fake responses, so they need no API key or internet
connection.

## Run the app

```bash
uv run streamlit run app.py
```

This opens the app in your browser (usually at http://localhost:8501).

## Collecting data

The trend and comparison views need history. To fetch the current weather
for 10 default cities (London, New York, Tokyo, Sydney, Dubai, Mumbai,
Paris, Toronto, Cairo, Reykjavik) and add it to the log, run:

```bash
uv run collect-weather
```

To fetch specific cities instead, put their names after the command. Use
quotes for names with spaces:

```bash
uv run collect-weather Tokyo "New York"
```

Each run adds one row per city to `data/weather_log.csv`. Run it a few
times a day to build up a useful history. Cities that can't be found are
skipped and listed with the reason.

## How to use the app

Start the app with `uv run streamlit run app.py`. Use the **sidebar** to
switch between the five pages and to manage your cities.

### Sidebar

- **Add a city:** type a name (e.g. `Madrid`) and press **➕ Add & fetch**.
  The city's current weather is fetched, saved to the log, and the city is
  added to your tracked list. If a name exists in several countries, add a
  country code after a comma, e.g. `Valencia,ES` or `Paris,FR`.
- **Tracked cities:** the cities shown on the Live Conditions page. When
  you open the app, every city in the log is tracked. Click the ✕ next to
  a city to stop tracking it. Its history stays in the log.
- **Status:** shows whether your API key loaded (the key itself is never
  shown) and how many readings are in the log.

If the name is invalid (e.g. `12345`), the city can't be found, or the
key or network fails, the app shows a clear message explaining what went
wrong instead of crashing.

### 🚚 Delivery Risk

The first page. Choose a **vehicle** (🚐 Van, 🚛 Truck or 🛵 Bike) at the
top, then use the four tabs:

- **📋 Dispatch board:** one coloured box per tracked hub with its signal,
  what to do, the expected extra trip time and the reasons (for example
  "Fog" or "Wind 8.2 m/s"), worst first. Counts of each signal are shown
  above. Press **🔄 Refresh live readings** to fetch and log new readings.
- **🗺️ Route planner:** pick **From** and **To** hubs, the normal trip time
  and a departure day and hour (UTC, up to 4 days ahead). The origin is
  judged on its forecast at departure and the destination at arrival,
  and the route takes the worse of the two. You see the expected trip
  time, both ends' conditions, and a chart of the route signal for every
  possible departure. If another time is safer, the app suggests it, e.g.
  "Leaving Wed 11 Nov, 06:00 UTC instead lowers the risk from 🟡 Yellow
  to 🟢 Green."
- **📅 5-day hub outlook:** the signal for one hub in 3-hour steps over the
  next 5 days, the worst signal in the next 24 hours, and how many hours
  are orange or red.
- **📊 Hub reliability:** for each tracked hub with at least 5 readings,
  the share of logged readings at each signal, most disrupted first.

Forecasts are cached for 30 minutes and are **not** added to the log,
because they are predictions, not observations. The full rules and the
limits for each vehicle are on the **How to use** page.

### 🌤️ Live Conditions

One card per tracked city with its latest reading: temperature, how warm
or cold it *feels* compared to the actual temperature, a small chart of
its past temperatures, a **comfort score** (0–100), and humidity, wind
and pressure. Press **🔄 Fetch latest for all tracked cities** to record a
new reading for every city. If no cities are tracked (for example with
an empty log), a **Load 10 sample cities** button appears to start with a
ready-made set.

### 📈 Trends

Choose one or more **cities** and a **metric** (temperature, feels like,
humidity, wind speed, pressure or comfort index) to see a line chart of
how it changed over time. Below the chart, a summary card for each city
shows its latest value, the change since the first reading, and its low,
high and average. The free API has no history, so every point on the
chart is a reading we logged ourselves.

**Daily temperature range:** for the same cities, a bar for each day
running from that day's lowest to its highest logged temperature, and the
widest swing in the period. A city needs at least two readings on the
same day to show a bar.

### 📊 Compare

Compares the cities side by side:

- **Extremes right now:** the hottest, coldest, windiest, most humid, most
  comfortable and least comfortable city, from each city's latest reading.
- **Ranking:** a bar chart of all cities ranked by the metric you choose,
  highest or lowest first.
- **Does it feel colder or warmer than it is?** Each city's average
  *feels like − actual temperature* over all its readings. Below zero,
  wind makes it feel colder; above zero, humidity makes it feel warmer.
- **Where they are:** a world map with each city coloured by its comfort
  score.
- **All latest readings:** a table with every city's latest values.

Turn off **Only tracked cities** to include every city in the log, not
just the ones you're tracking.

### ℹ️ How to use

Short instructions inside the app, an explanation of how the comfort
index is calculated (it starts at 100 and loses points for temperature
away from 21 °C, humidity outside 30–60 %, and wind above 5 m/s), the
delivery-risk rules with each vehicle's limits, and a button to
**download the full log as a CSV**.

## Project structure

```
.
├── pyproject.toml
├── variables.env.example       # template for your API key file
├── variables.env               # not committed — your API key
├── data/
│   └── weather_log.csv         # every fetch, appended by the app/collector
├── src/
│   └── weather_app/
│       ├── client.py           # API client classes and error types
│       ├── models.py           # WeatherSnapshot and the comfort index
│       ├── storage.py          # logging/loading fetched history
│       ├── analytics.py        # trend, comparison and derived-metric views
│       ├── logistics.py        # delivery risk: signals, vehicles, routes
│       ├── collect.py          # `uv run collect-weather`
│       └── config.py           # reads the API key, project paths
├── app.py                      # Streamlit entry point
├── tests/                      # pytest tests (no API key needed)
└── PROMPTS.md                  # AI collaboration log
```

## Team

- **Jyothika:** API client, data model, analytics, Streamlit app,
  delivery-risk use case
- **Juan:** client error tests (timeout, 403)
- **Enrique:** daily temperature range analytics
- **Victoria:** feels-like gap analytics
- **Ruben:** README and fresh-install testing
