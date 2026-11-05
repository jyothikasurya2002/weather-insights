"""Weather Insights: Streamlit entry point.

Run with:  uv run streamlit run app.py
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from weather_app.analytics import (
    METRICS,
    daily_range,
    extremes,
    feels_like_gap,
    latest_by_location,
    metric_trend,
    rank_locations,
    trend_summary,
)
from weather_app.client import (
    APIError,
    AuthenticationError,
    InvalidInputError,
    LocationNotFoundError,
    NetworkError,
    OpenWeatherClient,
    RateLimitError,
)
from weather_app.collect import DEFAULT_CITIES
from weather_app.models import (
    CALM_WIND_MS,
    HUMIDITY_RANGE,
    IDEAL_TEMP_C,
)
from weather_app.config import get_api_key
from weather_app.storage import SnapshotStore

st.set_page_config(page_title="Weather Insights", page_icon="🌤️",
                   layout="wide")

PAGES = ["🌤️ Live Conditions", "📈 Trends", "📊 Compare", "ℹ️ How to use"]


# ---- helpers --------------------------------------------------------------


def metric_label(metric: str) -> str:
    """'temperature' -> 'Temperature (°C)', for axis titles and menus."""
    name, unit = METRICS[metric]
    return f"{name} ({unit})"


def unit_of(metric: str) -> str:
    return METRICS[metric][1]


def time_ago(timestamp: pd.Timestamp) -> str:
    seconds = (pd.Timestamp.now(tz="UTC") - timestamp).total_seconds()
    if seconds < 90:
        return "just now"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f} min ago"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.0f} h ago"
    return f"{seconds / 86400:.0f} days ago"


def to_query(location: str) -> str:
    """'Paris, FR' -> 'Paris,FR', so re-fetches hit the same city."""
    return location.replace(", ", ",")


def error_message(error: APIError) -> tuple[str, str]:
    """Pick an icon and a message level for each failure mode."""
    if isinstance(error, InvalidInputError):
        return "warning", f"✏️ {error}"
    if isinstance(error, LocationNotFoundError):
        return "error", f"📍 {error}"
    if isinstance(error, AuthenticationError):
        return "error", f"🔑 {error}"
    if isinstance(error, RateLimitError):
        return "warning", f"⏳ {error}"
    if isinstance(error, NetworkError):
        return "error", f"📡 {error}"
    return "error", f"⚠️ {error}"


def flash(level: str, text: str) -> None:
    """Queue a message to show after the next rerun."""
    st.session_state.setdefault("flash", []).append((level, text))


def show_flashes() -> None:
    for level, text in st.session_state.pop("flash", []):
        getattr(st, level)(text)


def track(locations: list[str]) -> None:
    """Queue locations to add to the tracked list on the next rerun.

    The tracked list is owned by a sidebar widget, and Streamlit only
    lets us change a widget's value *before* the widget is drawn, so
    additions are queued here and applied at the top of the script.
    """
    st.session_state.setdefault("to_track", []).extend(locations)


def fetch_and_log(queries: list[str]) -> None:
    """Fetch several cities, log the successes, and report the rest."""
    try:
        snapshots, failures = client.fetch_many(queries)
    except AuthenticationError as error:
        flash(*error_message(error))
        return
    store.append_many(snapshots)
    track([s.label for s in snapshots])
    if snapshots:
        flash("success", f"✅ Fetched and logged {len(snapshots)} "
                         f"{'city' if len(snapshots) == 1 else 'cities'}.")
    for query, reason in failures.items():
        flash("warning", f"Skipped **{query or '(blank)'}**: {reason}")


# ---- setup ----------------------------------------------------------------


@st.cache_resource
def get_client() -> OpenWeatherClient:
    return OpenWeatherClient(get_api_key())


try:
    client = get_client()
    key_problem = None
except (RuntimeError, AuthenticationError) as error:
    client = None
    key_problem = str(error)

store = SnapshotStore()

if "tracked" not in st.session_state:
    # First visit: start by tracking every location already in the log.
    st.session_state.tracked = sorted(store.load()["location"].unique())

for location in st.session_state.pop("to_track", []):
    if location not in st.session_state.tracked:
        st.session_state.tracked.append(location)


# ---- sidebar --------------------------------------------------------------

with st.sidebar:
    st.title("🌤️ Weather Insights")
    page = st.radio("View", PAGES, label_visibility="collapsed")

    st.divider()
    with st.form("add_city", clear_on_submit=True):
        new_city = st.text_input(
            "Add a city",
            placeholder="e.g. Madrid  or  Paris,FR",
            help="Add a country code after a comma if the name is "
                 "ambiguous, e.g. 'Valencia,ES' vs 'Valencia,VE'.")
        add_clicked = st.form_submit_button(
            "➕ Add & fetch", width="stretch", disabled=client is None)
    if add_clicked:
        try:
            snapshot = client.fetch_current(new_city)
        except APIError as error:
            flash(*error_message(error))
        else:
            store.append(snapshot)
            track([snapshot.label])
            flash("success", f"✅ Added **{snapshot.label}**: {snapshot}")
        st.rerun()

    history = store.load()
    options = sorted(set(history["location"]) | set(st.session_state.tracked))
    st.multiselect(
        "Tracked cities", options, key="tracked",
        help="Remove a city with its ✕. Its history stays in the log.")

    st.divider()
    if key_problem:
        st.error(f"🔑 {key_problem}")
    else:
        st.caption("🔑 API key loaded")
    if history.empty:
        st.caption("📦 No readings logged yet")
    else:
        st.caption(f"📦 {len(history)} readings from "
                   f"{history['location'].nunique()} cities · last fetch "
                   f"{time_ago(history['fetched_at'].max())}")

tracked = st.session_state.tracked
show_flashes()


# ---- page: live conditions ------------------------------------------------


def live_page() -> None:
    st.header("🌤️ Live Conditions")
    st.caption("Current weather for your tracked cities. Every fetch is "
               "saved to the log that powers the Trends and Compare pages.")

    if st.button("🔄 Fetch latest for all tracked cities", type="primary",
                 disabled=client is None or not tracked):
        with st.spinner(f"Fetching {len(tracked)} cities..."):
            fetch_and_log([to_query(loc) for loc in tracked])
        st.rerun()

    latest = latest_by_location(history[history["location"].isin(tracked)])
    if latest.empty:
        st.info("No cities yet. Add one in the sidebar, or start with a "
                "sample set.")
        if st.button(f"Load {len(DEFAULT_CITIES)} sample cities",
                     disabled=client is None):
            with st.spinner("Fetching sample cities..."):
                fetch_and_log(DEFAULT_CITIES)
            st.rerun()
        return

    rows = list(latest.sort_values("location").itertuples())
    # Build the grid one row of 3 at a time, so cards in a row line up,
    # and give every card the same fixed height.
    for start in range(0, len(rows), CARDS_PER_ROW):
        columns = st.columns(CARDS_PER_ROW)
        for column, row in zip(columns, rows[start:start + CARDS_PER_ROW]):
            with column.container(border=True, height=CARD_HEIGHT):
                city_card(row)


CARDS_PER_ROW = 3
CARD_HEIGHT = 400


def city_card(row) -> None:
    """One Live Conditions card. Every line is kept to a single line of
    text so all cards come out the same shape."""
    icon, title = st.columns([1, 4], vertical_alignment="center")
    if row.icon:
        icon.image(f"https://openweathermap.org/img/wn/{row.icon}@2x.png",
                   width=56)
    title.markdown(f"#### {row.location}")
    title.caption(row.description.capitalize())

    # One wide metric (narrow columns truncate values to "2..."), with a
    # sparkline of this city's logged temperatures. A single reading is
    # drawn as a flat line so every card has a chart of the same size.
    past = list(history.loc[history["location"] == row.location,
                            "temperature"].tail(24))
    if len(past) == 1:
        past = past * 2
    gap = row.feels_like - row.temperature
    st.metric(
        f"Temperature · {time_ago(row.fetched_at)}",
        f"{row.temperature:.1f} °C",
        delta=f"Feels like {row.feels_like:.1f} °C ({gap:+.1f})",
        delta_color="off", delta_arrow="off",
        chart_data=past, chart_type="area",
        help="The line shows this city's logged temperatures.")
    st.progress(row.comfort_index / 100,
                text=f"Comfort {row.comfort_index:.0f}/100")
    st.caption(f"💧 Humidity {row.humidity:.0f} % · 💨 Wind "
               f"{row.wind_speed:.1f} m/s · 🧭 {row.pressure:.0f} hPa")


# ---- page: trends ---------------------------------------------------------


def trends_page() -> None:
    st.header("📈 Trends")
    st.caption("How conditions have changed over time, from our own log. "
               "The free API has no history, so each point is a fetch we "
               "made.")
    if history.empty:
        st.info("No history yet. Fetch some cities on the Live Conditions "
                "page first.")
        return

    locations = sorted(history["location"].unique())
    # Start with the tracked cities that have the most history, so the
    # first chart a visitor sees has real lines, not single dots.
    by_history = history["location"].value_counts().index
    default = [loc for loc in by_history if loc in tracked][:3]
    left, right = st.columns([3, 1])
    chosen = left.multiselect("Cities", locations,
                              default=default or locations[:3])
    metric = right.selectbox("Metric", list(METRICS),
                             format_func=metric_label)
    if not chosen:
        st.info("Pick at least one city.")
        return

    trend = metric_trend(history, chosen, metric)
    fig = px.line(
        trend, x="fetched_at", y=metric, color="location", markers=True,
        labels={"fetched_at": "Time (UTC)", metric: metric_label(metric),
                "location": "City"},
        title=f"{METRICS[metric][0]} over time")
    fig.update_layout(hovermode="x unified", legend_title_text="")
    st.plotly_chart(fig, width="stretch")

    st.subheader("Summary over the logged period")
    unit = unit_of(metric)
    columns = st.columns(min(len(chosen), 4))
    for i, location in enumerate(chosen):
        summary = trend_summary(history, location, metric)
        with columns[i % len(columns)].container(border=True):
            st.metric(location, f"{summary['last']:.1f} {unit}",
                      delta=f"{summary['change']:+.1f} {unit} since first "
                            "reading",
                      delta_color="off")
            st.caption(f"Low {summary['min']:.1f} · high "
                       f"{summary['max']:.1f} · average "
                       f"{summary['mean']:.1f} {unit}\n\n"
                       f"{summary['samples']} readings since "
                       f"{summary['first_at']:%d %b %H:%M} UTC")

    if trend["fetched_at"].nunique() < 3:
        st.info("💡 Only a few readings so far. Fetch again over the next "
                "few days and these lines will fill in.")

    daily_range_chart(chosen)


def daily_range_chart(chosen: list[str]) -> None:
    """Each day's low-to-high temperature span as a floating bar."""
    st.subheader("Daily temperature range")
    st.caption("Each bar runs from the day's lowest to its highest logged "
               "temperature (UTC days). The API only reports the current "
               "temperature, so the daily high and low come from our log.")
    days = daily_range(history[history["location"].isin(chosen)])
    # A single reading gives a zero-height bar, so keep only real spans.
    days = days[days["range"] > 0]
    if days.empty:
        st.info("A city needs at least two readings on the same day to "
                "show a range. Fetch again later today.")
        return
    days["date"] = days["date"].astype(str)
    fig = px.bar(
        days, x="date", y="range", base="min_temp", color="location",
        barmode="group",
        hover_data={"min_temp": ":.1f", "max_temp": ":.1f", "range": ":.1f"},
        labels={"date": "Day (UTC)", "range": "Range (°C)",
                "min_temp": "Low (°C)", "max_temp": "High (°C)",
                "location": "City"},
        title="Daily low to high temperature")
    fig.update_yaxes(title_text="Temperature (°C)")
    fig.update_layout(legend_title_text="")
    st.plotly_chart(fig, width="stretch")
    widest = days.loc[days["range"].idxmax()]
    st.caption(f"Widest swing: **{widest['location']}** on "
               f"{widest['date']}, from {widest['min_temp']:.1f} to "
               f"{widest['max_temp']:.1f} °C ({widest['range']:.1f} °C).")


# ---- page: compare --------------------------------------------------------


def compare_page() -> None:
    st.header("📊 Compare cities")
    st.caption("Each city's most recent reading, side by side.")

    only_tracked = st.toggle("Only tracked cities", value=True)
    data = (history[history["location"].isin(tracked)] if only_tracked
            else history)
    if data.empty:
        st.info("No data to compare yet. Fetch some cities first.")
        return

    st.subheader("Extremes right now")
    picks = extremes(data)
    units = {"Hottest": "°C", "Coldest": "°C", "Windiest": "m/s",
             "Most humid": "%", "Most comfortable": "/100",
             "Least comfortable": "/100"}
    # 3 per row: six in one row truncated the city names.
    columns = st.columns(3)
    for i, (title, (location, value)) in enumerate(picks.items()):
        columns[i % 3].metric(
            title, location, delta=f"{value:.1f} {units[title]}",
            delta_color="off", delta_arrow="off", border=True)

    st.subheader("Ranking")
    left, right = st.columns([3, 1])
    metric = left.selectbox("Rank by", list(METRICS),
                            index=list(METRICS).index("comfort_index"),
                            format_func=metric_label)
    highest_first = right.radio("Order", ["Highest first", "Lowest first"],
                                horizontal=True) == "Highest first"
    ranked = rank_locations(data, metric, highest_first)
    fig = px.bar(
        ranked, x=metric, y="location", orientation="h", text=metric,
        color=metric, color_continuous_scale="RdYlBu_r"
        if metric in ("temperature", "feels_like") else "Viridis",
        labels={metric: metric_label(metric), "location": "City"},
        title=f"Cities ranked by {METRICS[metric][0].lower()}")
    fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
    fig.update_yaxes(categoryorder="array",
                     categoryarray=list(ranked["location"])[::-1])
    fig.update_layout(coloraxis_showscale=False,
                      height=max(300, 45 * len(ranked)))
    st.plotly_chart(fig, width="stretch")

    feels_like_chart(data)

    st.subheader("Where they are")
    latest = latest_by_location(data).dropna(subset=["lat", "lon"])
    fig = px.scatter_geo(
        latest, lat="lat", lon="lon", hover_name="location",
        color="comfort_index", size=[12] * len(latest),
        color_continuous_scale="RdYlGn", range_color=(0, 100),
        hover_data={"temperature": ":.1f", "humidity": True,
                    "wind_speed": ":.1f", "lat": False, "lon": False},
        labels={"comfort_index": "Comfort (/100)",
                "temperature": "Temperature (°C)",
                "humidity": "Humidity (%)",
                "wind_speed": "Wind (m/s)"},
        projection="natural earth",
        title="Tracked cities, coloured by comfort index")
    st.plotly_chart(fig, width="stretch")

    st.subheader("All latest readings")
    table = latest_by_location(data).sort_values("comfort_index",
                                                 ascending=False)
    st.dataframe(
        table[["location", "temperature", "feels_like", "humidity",
               "wind_speed", "comfort_index", "description", "fetched_at"]],
        hide_index=True, width="stretch",
        column_config={
            "location": "City",
            "temperature": st.column_config.NumberColumn(
                "Temp (°C)", format="%.1f"),
            "feels_like": st.column_config.NumberColumn(
                "Feels like (°C)", format="%.1f"),
            "humidity": st.column_config.NumberColumn(
                "Humidity (%)", format="%.0f"),
            "wind_speed": st.column_config.NumberColumn(
                "Wind (m/s)", format="%.1f"),
            "comfort_index": st.column_config.ProgressColumn(
                "Comfort", min_value=0, max_value=100, format="%.0f"),
            "description": "Conditions",
            "fetched_at": st.column_config.DatetimeColumn(
                "Fetched (UTC)", format="D MMM, HH:mm"),
        })


def feels_like_chart(data: pd.DataFrame) -> None:
    """Average feels-like minus actual temperature, per city."""
    st.subheader("Does it feel colder or warmer than it is?")
    st.caption("Average of *feels like − actual temperature* over every "
               "logged reading. Below zero, wind makes a city feel colder; "
               "above zero, humidity makes it feel warmer.")
    gaps = feels_like_gap(data)
    limit = max(1.0, gaps["avg_gap"].abs().max())
    fig = px.bar(
        gaps, x="avg_gap", y="location", orientation="h", text="avg_gap",
        color="avg_gap", color_continuous_scale="RdBu_r",
        range_color=(-limit, limit),
        hover_data={"samples": True},
        labels={"avg_gap": "Feels-like minus actual (°C)",
                "location": "City", "samples": "Readings"},
        title="Average feels-like gap")
    fig.update_traces(texttemplate="%{text:+.1f}", textposition="outside")
    fig.update_yaxes(categoryorder="array",
                     categoryarray=list(gaps["location"])[::-1])
    fig.update_layout(coloraxis_showscale=False,
                      height=max(300, 45 * len(gaps)))
    st.plotly_chart(fig, width="stretch")


# ---- page: how to use -----------------------------------------------------


def help_page() -> None:
    st.header("ℹ️ How to use Weather Insights")
    low, high = HUMIDITY_RANGE
    st.markdown(f"""
**Weather Insights** tracks live weather for the cities you choose and
builds its own history, so you can see trends and compare places.

1. **Add cities** in the sidebar: type a name (e.g. `Madrid`) and press
   *Add & fetch*. For ambiguous names add a country code: `Paris,FR`.
2. **Live Conditions** shows the latest reading per city. Press
   *Fetch latest* any time to record a new reading for every tracked city.
3. **Trends** charts how a metric changed over time for the cities you pick,
   and each day's low-to-high temperature range.
4. **Compare** ranks cities by any metric, highlights the extremes, shows
   which cities feel colder or warmer than the thermometer says, and maps
   them.

#### Why the history matters
OpenWeatherMap's free tier only returns *current* conditions. Every fetch
is saved with a timestamp to `data/weather_log.csv`. That log is the time
series behind the Trends page, and it grows each time anyone fetches.

#### The comfort index (0-100)
A score the API doesn't provide, computed by us from three readings:

| Starts at 100, then loses... | for every... |
|---|---|
| 3 points | °C away from an ideal {IDEAL_TEMP_C:.0f} °C |
| 0.5 points | % of humidity outside {low:.0f}-{high:.0f} % |
| 2 points | m/s of wind above {CALM_WIND_MS:.0f} m/s |

Example: 22 °C, 70 % humidity and 7 m/s wind gives
100 − 3 − 5 − 4 = **88**.
""")
    if not history.empty:
        st.download_button(
            "⬇️ Download the full log (CSV)",
            history.drop(columns="location").to_csv(index=False),
            file_name="weather_log.csv", mime="text/csv")


{
    PAGES[0]: live_page,
    PAGES[1]: trends_page,
    PAGES[2]: compare_page,
    PAGES[3]: help_page,
}[page]()
