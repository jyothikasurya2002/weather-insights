"""Weather Insights: Streamlit entry point.

Run with:  uv run streamlit run app.py
"""

from datetime import datetime, time, timedelta, timezone

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
from weather_app.logistics import (
    VEHICLES,
    RiskLevel,
    assess_route,
    best_departure,
    departure_options,
    hub_reliability,
)
from weather_app.models import (
    CALM_WIND_MS,
    HUMIDITY_RANGE,
    IDEAL_TEMP_C,
    WeatherSnapshot,
)
from weather_app.config import get_api_key
from weather_app.storage import SnapshotStore

st.set_page_config(page_title="Weather Insights", page_icon="🌤️",
                   layout="wide")

PAGES = ["🚚 Delivery Risk", "🌤️ Live Conditions", "📈 Trends",
         "📊 Compare", "ℹ️ How to use"]


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


# ---- page: delivery risk (the business use case) --------------------------

SIGNAL_COLORS = {level.name.title(): level.color for level in RiskLevel}
SIGNAL_ORDER = [level.name.title() for level in RiskLevel]


@st.cache_data(ttl=1800, show_spinner=False)
def get_forecast(query: str) -> list[WeatherSnapshot]:
    """5-day forecast, cached for 30 minutes to stay within the free
    plan's request limit. Forecasts are not added to the log."""
    return client.fetch_forecast(query)


def forecast_for(location: str) -> list[WeatherSnapshot] | None:
    """The forecast, or None after showing why it couldn't be fetched."""
    if client is None:
        st.info("🔑 Forecasts need an API key (see the sidebar).")
        return None
    try:
        with st.spinner(f"Fetching the forecast for {location}..."):
            return get_forecast(to_query(location))
    except APIError as error:
        level, text = error_message(error)
        getattr(st, level)(text)
        return None


def fmt_time(moment: datetime) -> str:
    return f"{moment:%a %d %b, %H:%M} UTC"


def signal_box(level: RiskLevel, title: str, lines: list[str]) -> None:
    """A coloured box: green -> success, yellow/orange -> warning, red ->
    error. The text always names the level, not only the colour."""
    body = f"**{level} · {title}**  \n" + "  \n".join(lines)
    if level == RiskLevel.GREEN:
        st.success(body)
    elif level == RiskLevel.RED:
        st.error(body)
    else:
        st.warning(body)


def logistics_page() -> None:
    st.header("🚚 Delivery Risk")
    st.caption("Weather turned into delivery signals for a logistics team: "
               "🟢 normal, 🟡 minor delays, 🟠 significant delays, 🔴 hold "
               "or reroute. Rules and delay estimates are explained on the "
               "How to use page.")

    choice = st.radio(
        "Vehicle", list(VEHICLES), horizontal=True,
        format_func=lambda name: f"{VEHICLES[name].emoji} {name}",
        help="Trucks are more sensitive to wind, bikes to rain, wind and "
             "heat.")
    vehicle = VEHICLES[choice]

    board, route, outlook, reliability = st.tabs(
        ["📋 Dispatch board", "🗺️ Route planner", "📅 5-day hub outlook",
         "📊 Hub reliability"])
    with board:
        dispatch_board(vehicle)
    with route:
        route_planner(vehicle)
    with outlook:
        hub_outlook(vehicle)
    with reliability:
        reliability_chart(vehicle)


def dispatch_board(vehicle) -> None:
    st.caption("The signal for each tracked hub right now, from its latest "
               "reading, worst first.")
    if st.button("🔄 Refresh live readings", key="refresh_board",
                 disabled=client is None or not tracked):
        with st.spinner(f"Fetching {len(tracked)} cities..."):
            fetch_and_log([to_query(loc) for loc in tracked])
        st.rerun()

    latest = latest_by_location(history[history["location"].isin(tracked)])
    if latest.empty:
        st.info("No hubs yet. Add a city in the sidebar.")
        return
    assessments = sorted(
        (vehicle.assess(WeatherSnapshot.from_record(row))
         for _, row in latest.iterrows()),
        key=lambda a: (-a.level, a.snapshot.label))

    counts = st.columns(len(RiskLevel))
    for column, level in zip(counts, reversed(RiskLevel)):
        column.metric(str(level),
                      sum(a.level == level for a in assessments),
                      border=True)

    for start in range(0, len(assessments), CARDS_PER_ROW):
        columns = st.columns(CARDS_PER_ROW)
        for column, a in zip(columns,
                             assessments[start:start + CARDS_PER_ROW]):
            with column:
                low, high = a.level.delay_range
                delay = ("no expected delay" if high == 0 else
                         f"+{low:.0%} to +{high:.0%} trip time")
                age = pd.Timestamp(a.snapshot.fetched_at)
                signal_box(a.level, a.snapshot.label, [
                    a.level.advice,
                    f"⏱️ {delay}",
                    "⚠️ " + ("; ".join(a.reasons) or "No weather issues"),
                    f"🕒 Reading from {time_ago(age)}",
                ])


def route_planner(vehicle) -> None:
    st.caption("Plan a trip between two hubs. The origin is judged on its "
               "forecast at departure, the destination at arrival, and the "
               "route takes the worse of the two.")
    hubs = sorted(set(tracked) | set(history["location"]))
    if len(hubs) < 2:
        st.info("Add at least two cities in the sidebar to plan a route.")
        return

    c1, c2, c3 = st.columns(3)
    origin = c1.selectbox("From", hubs, index=0)
    destination = c2.selectbox("To", hubs, index=1)
    normal_hours = c3.number_input(
        "Normal trip time (hours)", min_value=1.0, max_value=72.0,
        value=8.0, step=1.0,
        help="How long the trip takes in good weather.")
    now = datetime.now(timezone.utc)
    c4, c5, _ = st.columns(3)
    day = c4.date_input("Departure day (UTC)", value=now.date(),
                        min_value=now.date(),
                        max_value=now.date() + timedelta(days=4))
    hour = c5.slider("Departure hour (UTC)", 0, 23,
                     value=min(now.hour + 1, 23))
    departure = datetime.combine(day, time(hour), tzinfo=timezone.utc)
    if origin == destination:
        st.warning("Pick two different hubs.")
        return

    origin_fc = forecast_for(origin)
    destination_fc = forecast_for(destination)
    if not origin_fc or not destination_fc:
        return

    trip = assess_route(vehicle, origin_fc, destination_fc, departure,
                        normal_hours)
    if trip.arrival > destination_fc[-1].fetched_at:
        st.caption("ℹ️ Arrival is after the end of the 5-day forecast, so "
                   "the destination uses the last forecast step.")
    low, high = trip.trip_hours()
    signal_box(trip.level, f"{origin} → {destination} ({vehicle.name})", [
        trip.level.advice,
        f"⏱️ Normal {normal_hours:.0f} h → expect "
        + (f"{low:.1f} h" if low == high else f"{low:.1f}–{high:.1f} h"),
        f"🛫 Depart {fmt_time(trip.departure)}, arrive about "
        f"{fmt_time(trip.arrival)}",
    ])
    left, right = st.columns(2)
    for column, title, a in ((left, "At the origin, on departure",
                              trip.origin),
                             (right, "At the destination, on arrival",
                              trip.destination)):
        with column.container(border=True):
            st.markdown(f"**{title}**  \n{a.level} · {a.snapshot.label}")
            st.caption(f"Forecast for {fmt_time(a.snapshot.fetched_at)}: "
                       f"{a.snapshot.description}, "
                       f"{a.snapshot.temperature:.1f} °C, wind "
                       f"{a.snapshot.wind_speed:.1f} m/s")
            st.write("; ".join(a.reasons) or "No weather issues.")

    st.subheader("When is the best time to leave?")
    options = departure_options(vehicle, origin_fc, destination_fc,
                                normal_hours, earliest=now)
    best = best_departure(options)
    if best is None:
        st.info("The trip is too long to check against the 5-day forecast.")
        return
    if best.level < trip.level:
        st.info(f"💡 Leaving **{fmt_time(best.departure)}** instead lowers "
                f"the risk from {trip.level} to {best.level}.")
    else:
        st.caption(f"Your departure is already as safe as any in the "
                   f"forecast ({best.level}).")
    table = pd.DataFrame({
        "departure": [o.departure for o in options],
        "signal": [o.level.name.title() for o in options],
        "height": [int(o.level) + 1 for o in options],
        "origin": [f"{o.origin.level.name.title()}: "
                   + ("; ".join(o.origin.reasons) or "clear")
                   for o in options],
        "destination": [f"{o.destination.level.name.title()}: "
                        + ("; ".join(o.destination.reasons) or "clear")
                        for o in options],
    })
    fig = px.bar(
        table, x="departure", y="height", color="signal",
        color_discrete_map=SIGNAL_COLORS,
        category_orders={"signal": SIGNAL_ORDER},
        hover_data={"height": False, "origin": True, "destination": True},
        labels={"departure": "Departure (UTC)", "signal": "Route signal"},
        title="Route signal for each possible departure (3-hour steps)")
    fig.update_yaxes(title_text="Risk", tickvals=[1, 2, 3, 4],
                     ticktext=SIGNAL_ORDER, range=[0, 4.3])
    fig.update_layout(bargap=0.1, legend_title_text="")
    fig.add_vline(x=departure, line_dash="dash", line_color="gray")
    st.plotly_chart(fig, width="stretch")


def hub_outlook(vehicle) -> None:
    st.caption("The signal for one hub over the next 5 days, from the "
               "forecast in 3-hour steps.")
    hubs = sorted(set(tracked) | set(history["location"]))
    if not hubs:
        st.info("Add a city in the sidebar first.")
        return
    hub = st.selectbox("Hub", hubs, key="outlook_hub")
    forecast = forecast_for(hub)
    if not forecast:
        return
    steps = [vehicle.assess(step) for step in forecast]
    table = pd.DataFrame({
        "time": [a.snapshot.fetched_at for a in steps],
        "signal": [a.level.name.title() for a in steps],
        "height": [int(a.level) + 1 for a in steps],
        "conditions": [a.snapshot.description for a in steps],
        "temperature": [a.snapshot.temperature for a in steps],
        "reasons": ["; ".join(a.reasons) or "none" for a in steps],
    })

    next_day = [a for a in steps
                if a.snapshot.fetched_at <= steps[0].snapshot.fetched_at
                + timedelta(hours=24)]
    worst = max(next_day, key=lambda a: a.level)
    disrupted = sum(a.level >= RiskLevel.ORANGE for a in steps)
    c1, c2 = st.columns(2)
    c1.metric("Worst in the next 24 h", str(worst.level),
              delta=(fmt_time(worst.snapshot.fetched_at)
                     if worst.level > RiskLevel.GREEN else None),
              delta_color="off", delta_arrow="off", border=True)
    c2.metric("Orange or red steps in 5 days",
              f"{disrupted} of {len(steps)}",
              delta=f"about {disrupted * 3} h of disruption",
              delta_color="off", delta_arrow="off", border=True)

    fig = px.bar(
        table, x="time", y="height", color="signal",
        color_discrete_map=SIGNAL_COLORS,
        category_orders={"signal": SIGNAL_ORDER},
        hover_data={"height": False, "conditions": True,
                    "temperature": ":.1f", "reasons": True},
        labels={"time": "Time (UTC)", "signal": "Signal",
                "temperature": "Temperature (°C)"},
        title=f"{hub}: {vehicle.name} signal, next 5 days")
    fig.update_yaxes(title_text="Risk", tickvals=[1, 2, 3, 4],
                     ticktext=SIGNAL_ORDER, range=[0, 4.3])
    fig.update_layout(bargap=0.1, legend_title_text="")
    st.plotly_chart(fig, width="stretch")


MIN_READINGS = 5


def reliability_chart(vehicle) -> None:
    st.caption("How often each hub's logged weather would have meant each "
               "signal. Uses every reading in our log, not the forecast.")
    data = history[history["location"].isin(tracked)]
    table = hub_reliability(data, vehicle)
    if table.empty:
        st.info("No logged readings for the tracked hubs yet.")
        return
    enough = table[table["readings"] >= MIN_READINGS]
    if enough.empty:
        st.info(f"Each hub needs at least {MIN_READINGS} readings.")
        return

    long = enough.melt(id_vars=["location", "readings"],
                       value_vars=SIGNAL_ORDER, var_name="signal",
                       value_name="share")
    fig = px.bar(
        long, x="share", y="location", color="signal", orientation="h",
        color_discrete_map=SIGNAL_COLORS,
        category_orders={"signal": SIGNAL_ORDER,
                         "location": list(enough["location"])},
        hover_data={"readings": True, "share": ":.1f"},
        labels={"share": "Share of readings (%)", "location": "Hub",
                "signal": "Signal", "readings": "Readings"},
        title=f"Share of time at each signal ({vehicle.name})")
    fig.update_layout(legend_title_text="",
                      height=max(300, 45 * len(enough)))
    st.plotly_chart(fig, width="stretch")

    top = enough.iloc[0]
    if top["disrupted"] > 0:
        st.caption(f"Most disrupted hub: **{top['location']}**, orange or "
                   f"red in {top['disrupted']:.0f} % of its "
                   f"{top['readings']} readings.")
    skipped = len(table) - len(enough)
    st.caption(f"Hubs with fewer than {MIN_READINGS} readings are left out"
               + (f" ({skipped} hidden)." if skipped else ".")
               + " Readings logged before 10 Nov have no condition code or "
               "visibility, so they are judged from their description.")


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
builds its own history, so you can see trends and compare places. Its main
use case is **delivery risk**: turning weather into go / slow down / stop
signals for a logistics team.

1. **Add cities** in the sidebar: type a name (e.g. `Madrid`) and press
   *Add & fetch*. Each city is a delivery hub. For ambiguous names add a
   country code: `Paris,FR`.
2. **Delivery Risk** gives each hub a signal for the chosen vehicle, plans
   a route between two hubs with the 5-day forecast (and suggests a safer
   departure time), shows a hub's next 5 days, and ranks hubs by how often
   our logged weather disrupted them.
3. **Live Conditions** shows the latest reading per city. Press
   *Fetch latest* any time to record a new reading for every tracked city.
4. **Trends** charts how a metric changed over time for the cities you pick,
   and each day's low-to-high temperature range.
5. **Compare** ranks cities by any metric, highlights the extremes, shows
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
    delivery_rules()
    if not history.empty:
        st.download_button(
            "⬇️ Download the full log (CSV)",
            history.drop(columns="location").to_csv(index=False),
            file_name="weather_log.csv", mime="text/csv")


def delivery_rules() -> None:
    """The delivery-risk rules, built from the vehicle classes themselves
    so the explanation can't drift from the code."""
    st.markdown("""
#### Delivery risk signals
Each reading gets the **worst** signal of four factors: precipitation,
visibility, wind and temperature.

| Signal | Means | Extra trip time |
|---|---|---|
""" + "\n".join(
        f"| {level} | {level.advice} | "
        + ("none" if level.delay_range[1] == 0 else
           f"+{level.delay_range[0]:.0%} to +{level.delay_range[1]:.0%}")
        + " |" for level in RiskLevel) + """

**Conditions** (from OpenWeatherMap's condition code): 🟡 drizzle, light
rain, mist, haze, smoke or dust · 🟠 moderate rain, snow, fog · 🔴
thunderstorm, heavy rain, freezing rain, heavy snow, sleet, squalls.
Measured rain (≥ 2.5 mm/h 🟠, ≥ 7.6 mm/h 🔴) and visibility (under 5 km 🟡,
3 km 🟠, 1 km 🔴) can raise it further.
**Temperature:** ≤ 2 °C 🟡 (possible ice), ≤ −10 °C 🟠, at or below 0 °C
with precipitation 🔴 (ice).

**Limits by vehicle** (yellow / orange / red):
""")
    st.dataframe(pd.DataFrame([{
        "Vehicle": f"{v.emoji} {v.name}",
        "Wind (m/s)": " / ".join(f"{x:g}" for x in v.WIND_LIMITS),
        "Gusts (m/s)": " / ".join(f"{x:g}" for x in v.GUST_LIMITS),
        "Heat (°C, yellow / orange)":
            " / ".join(f"{x:g}" for x in v.HEAT_LIMITS),
        "Rain or snow": ("one level worse (rider exposed)"
                         if v.name == "Bike" else "as above"),
    } for v in VEHICLES.values()]), hide_index=True)
    st.caption("A route takes the worse of the origin (at departure) and "
               "the destination (at arrival). These thresholds and delay "
               "ranges are our own assumptions based on common road-safety "
               "guidance (e.g. gale force starts at 17 m/s), not "
               "calibrated on real delivery data.")


{
    PAGES[0]: logistics_page,
    PAGES[1]: live_page,
    PAGES[2]: trends_page,
    PAGES[3]: compare_page,
    PAGES[4]: help_page,
}[page]()
