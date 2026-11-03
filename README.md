# Weather Insights

## What this app does

Weather Insights fetches live weather for any cities you choose from the
OpenWeatherMap API. Every fetch is saved to a log file, so the app builds
its own weather history over time. That history shows how conditions
change, which cities are hottest, coldest or windiest right now, and a
0–100 comfort score that combines temperature, humidity and wind.

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

Pick a page in the sidebar:

- **Live Conditions:** add or choose cities to see their current
  temperature, feels-like temperature, humidity, wind and comfort score.
  Each fetch is also saved to the log.
- **Trends:** choose one or more cities and a metric (temperature,
  humidity, wind, comfort...) to see how it changed over the logged
  history, with a summary of the first, last, lowest and highest values.
- **Compare:** rank all logged cities by a metric using their latest
  reading, and see headline extremes such as the hottest, coldest,
  windiest and most comfortable city.

## Project structure

```
.
├── pyproject.toml
├── variables.env               # not committed — your API key
├── data/
│   └── weather_log.csv         # every fetch, appended by the app/collector
├── src/
│   └── weather_app/
│       ├── client.py           # API client classes
│       ├── models.py           # data classes (snapshots, locations...)
│       ├── storage.py          # logging/loading fetched history
│       ├── analytics.py        # analytical views
│       ├── collect.py          # `uv run collect-weather`
│       └── config.py           # reads the API key, project paths
├── app.py                      # Streamlit entry point
├── tests/
└── PROMPTS.md                  # AI collaboration log
```

## Team

- **Jyothika:** API client, data model, analytics, Streamlit app
- **Juan:** client error tests (timeout, 403)
- **Enrique:** daily temperature range analytics
- **Victoria:** feels-like gap analytics
- **Ruben:** README and fresh-install testing
````
