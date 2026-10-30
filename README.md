# Weather Insights

<!-- Replace this with a real description of what your app does once it exists. -->

## Setup

```bash
uv sync
cp variables.env.example variables.env   # then fill in your own OpenWeatherMap key
```

## Run the app

```bash
uv run streamlit run app.py
```

## Run the tests

```bash
uv run pytest
```

## Project structure

```
.
├── pyproject.toml
├── variables.env               # not committed — your API key
├── src/
│   └── weather_app/
│       ├── client.py           # API client classes
│       ├── models.py           # data classes (snapshots, locations...)
│       ├── storage.py          # logging/loading fetched history
│       └── analytics.py        # analytical views
├── app.py                      # Streamlit entry point
├── tests/
└── PROMPTS.md                  # AI collaboration log
```

## Team

<!-- Names and a one-line summary of who worked on what. -->
