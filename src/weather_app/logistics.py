"""Business use case: weather-driven delivery risk for a logistics team.

Every reading (live, logged or forecast) is turned into a traffic-light
signal with an estimated delay:

    GREEN   normal operations             +0 %
    YELLOW  minor delays                  +10-20 %
    ORANGE  significant delays            +25-50 %
    RED     unsafe: hold or reroute       +50-100 %

The signal is the worst of five factors: precipitation, visibility, wind,
temperature and, when we have it, air quality. Vehicle types tolerate
conditions differently (a high-sided truck is more exposed to wind, a
bike courier to rain and polluted air), so each one is a VehicleProfile
subclass with its own limits.

The thresholds and delay ranges are our own rule-based assumptions, set
from common road-safety guidance (e.g. gale force starts at 17 m/s, fog
means visibility under 1 km). They are not calibrated on real delivery
data.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum

import pandas as pd

from .models import AirQuality, WeatherSnapshot


class RiskLevel(IntEnum):
    """Ordered, so max() of several levels gives the worst one."""

    GREEN = 0
    YELLOW = 1
    ORANGE = 2
    RED = 3

    @property
    def emoji(self) -> str:
        return ["🟢", "🟡", "🟠", "🔴"][self]

    @property
    def color(self) -> str:
        return ["#2e9e44", "#e6b800", "#f07f13", "#d62728"][self]

    @property
    def delay_range(self) -> tuple[float, float]:
        """Extra travel time as a fraction of the normal trip time."""
        return [(0.0, 0.0), (0.10, 0.20), (0.25, 0.50), (0.50, 1.00)][self]

    @property
    def advice(self) -> str:
        return [
            "Normal operations.",
            "Minor delays likely: allow extra time.",
            "Significant delays: reschedule time-critical deliveries.",
            "Unsafe conditions: hold or reroute.",
        ][self]

    def __str__(self) -> str:
        return f"{self.emoji} {self.name.title()}"


@dataclass(frozen=True)
class RiskFactor:
    """One reason a reading is risky, e.g. ORANGE because of fog."""

    kind: str  # "precipitation", "visibility", "wind", "temperature", "air"
    level: RiskLevel
    reason: str


@dataclass
class RiskAssessment:
    """The signal for one reading and one vehicle type, with its reasons."""

    snapshot: WeatherSnapshot
    vehicle: str
    factors: list[RiskFactor] = field(default_factory=list)
    air: AirQuality | None = None     # None when we have no air data

    @property
    def level(self) -> RiskLevel:
        return max((f.level for f in self.factors), default=RiskLevel.GREEN)

    @property
    def reasons(self) -> list[str]:
        """Reasons behind the signal, worst first."""
        ranked = sorted(self.factors, key=lambda f: f.level, reverse=True)
        return [f.reason for f in ranked if f.level > RiskLevel.GREEN]

    def trip_hours(self, normal_hours: float) -> tuple[float, float]:
        """(best, worst) trip time in hours under these conditions."""
        low, high = self.level.delay_range
        return normal_hours * (1 + low), normal_hours * (1 + high)

    def __str__(self) -> str:
        why = "; ".join(self.reasons) or "no weather issues"
        return f"{self.snapshot.label} [{self.vehicle}]: {self.level} ({why})"


# ---- weather rules ------------------------------------------------------

_PRECIPITATION_GROUPS = {2, 3, 5, 6}     # thunderstorm, drizzle, rain, snow

# Used for log rows saved before we stored condition codes: the first
# keyword found in the description decides. Order matters ("drizzle"
# before "heavy", so heavy drizzle isn't treated like heavy rain).
_DESCRIPTION_RULES = [
    ("thunderstorm", RiskLevel.RED), ("tornado", RiskLevel.RED),
    ("squall", RiskLevel.RED), ("freezing", RiskLevel.RED),
    ("sleet", RiskLevel.RED), ("drizzle", RiskLevel.YELLOW),
    ("heavy", RiskLevel.RED), ("extreme", RiskLevel.RED),
    ("snow", RiskLevel.ORANGE), ("fog", RiskLevel.ORANGE),
    ("moderate rain", RiskLevel.ORANGE), ("rain", RiskLevel.YELLOW),
    ("shower", RiskLevel.YELLOW), ("mist", RiskLevel.YELLOW),
    ("haze", RiskLevel.YELLOW), ("smoke", RiskLevel.YELLOW),
    ("dust", RiskLevel.YELLOW), ("sand", RiskLevel.YELLOW),
]
_PRECIPITATION_WORDS = ("thunderstorm", "drizzle", "rain", "snow", "sleet",
                        "shower")


def condition_level(condition_id: int) -> RiskLevel:
    """Risk of an OpenWeatherMap condition code on its own.

    Codes: 2xx thunderstorm, 3xx drizzle, 5xx rain, 6xx snow, 7xx fog,
    haze etc., 800 clear, 80x clouds.
    """
    group = condition_id // 100
    if group == 2:
        return RiskLevel.RED
    if group == 3:
        return RiskLevel.YELLOW
    if group == 5:
        if condition_id in (500, 520):                  # light rain
            return RiskLevel.YELLOW
        if condition_id in (501, 521):                  # moderate rain
            return RiskLevel.ORANGE
        return RiskLevel.RED                            # heavy, freezing
    if group == 6:
        if condition_id in (602, 622) or 611 <= condition_id <= 616:
            return RiskLevel.RED                        # heavy snow, sleet
        return RiskLevel.ORANGE
    if group == 7:
        if condition_id == 741:                         # fog
            return RiskLevel.ORANGE
        if condition_id in (762, 771, 781):             # ash, squall, tornado
            return RiskLevel.RED
        return RiskLevel.YELLOW                         # mist, haze, smoke
    return RiskLevel.GREEN


def description_level(description: str) -> RiskLevel:
    """Fallback for old log rows: risk from the description text."""
    text = description.lower()
    for keyword, level in _DESCRIPTION_RULES:
        if keyword in text:
            return level
    return RiskLevel.GREEN


def has_precipitation(snapshot: WeatherSnapshot) -> bool:
    if snapshot.condition_id is not None:
        if snapshot.condition_id // 100 in _PRECIPITATION_GROUPS:
            return True
    if (snapshot.rain_mm_h or 0) > 0 or (snapshot.snow_mm_h or 0) > 0:
        return True
    return any(w in snapshot.description.lower()
               for w in _PRECIPITATION_WORDS)


def _level_for(value: float, limits: tuple[float, ...]) -> RiskLevel:
    """Highest level whose limit `value` reaches; limits start at YELLOW."""
    level = RiskLevel.GREEN
    for i, limit in enumerate(limits, start=1):
        if value >= limit:
            level = RiskLevel(i)
    return level


# ---- vehicle profiles -----------------------------------------------------


class VehicleProfile:
    """How one type of vehicle copes with weather.

    Subclasses change the class-level limits and can override `_adjust`
    to make extra, vehicle-specific changes to the factors.
    """

    name = "Vehicle"
    emoji = "🚚"
    # (yellow, orange, red) limits.
    WIND_LIMITS = (8.0, 11.0, 17.0)         # sustained wind, m/s
    GUST_LIMITS = (15.0, 20.0, 25.0)        # gusts, m/s
    # Visibility in metres: below these it becomes yellow, orange, red.
    VISIBILITY_LIMITS = (5000.0, 3000.0, 1000.0)
    HEAT_LIMITS = (35.0, 40.0)              # °C: yellow, orange
    RAIN_LIMITS = (0.1, 2.5, 7.6)           # mm/h: light, moderate, heavy
    HEAVY_SNOW_MM_H = 2.5                   # any snow is at least orange
    # OpenWeatherMap AQI (1 good ... 5 very poor). Drivers sit in a closed
    # cab, so only "very poor" air matters (loading, breaks outside).
    AQI_LIMITS = (5, math.inf, math.inf)
    # Sanity limits for a single road trip, used to warn about routes
    # that don't make sense for this vehicle.
    MAX_TRIP_KM = 1500.0
    MAX_AVG_SPEED_KMH = 90.0

    def assess(self, snapshot: WeatherSnapshot,
               air: AirQuality | None = None) -> RiskAssessment:
        factors = [factor for factor in (
            self._precipitation(snapshot),
            self._visibility(snapshot),
            self._wind(snapshot),
            self._temperature(snapshot),
            self._air_quality(air),
        ) if factor is not None]
        return RiskAssessment(snapshot, self.name,
                              self._adjust(factors, snapshot), air)

    def _adjust(self, factors: list[RiskFactor],
                snapshot: WeatherSnapshot) -> list[RiskFactor]:
        """Hook for subclasses; the base profile changes nothing."""
        return factors

    def _precipitation(self, s: WeatherSnapshot) -> RiskFactor | None:
        if s.condition_id is not None:
            level = condition_level(s.condition_id)
        else:
            level = description_level(s.description)
        reason = s.description.capitalize() or "Precipitation"
        # Measured amounts can make it worse than the code suggests.
        if s.rain_mm_h:
            by_rain = _level_for(s.rain_mm_h, self.RAIN_LIMITS)
            if by_rain > level:
                level = by_rain
            reason += f" ({s.rain_mm_h:.1f} mm/h rain)"
        if s.snow_mm_h:
            by_snow = (RiskLevel.RED if s.snow_mm_h >= self.HEAVY_SNOW_MM_H
                       else RiskLevel.ORANGE)
            if by_snow > level:
                level = by_snow
            reason += f" ({s.snow_mm_h:.1f} mm/h snow)"
        if level == RiskLevel.GREEN:
            return None
        kind = "precipitation" if has_precipitation(s) else "visibility"
        return RiskFactor(kind, level, reason)

    def _visibility(self, s: WeatherSnapshot) -> RiskFactor | None:
        if s.visibility is None:
            return None
        level = RiskLevel.GREEN
        for i, limit in enumerate(self.VISIBILITY_LIMITS, start=1):
            if s.visibility < limit:
                level = RiskLevel(i)
        if level == RiskLevel.GREEN:
            return None
        return RiskFactor("visibility", level,
                          f"Visibility {s.visibility / 1000:.1f} km")

    def _wind(self, s: WeatherSnapshot) -> RiskFactor | None:
        level = _level_for(s.wind_speed, self.WIND_LIMITS)
        reason = f"Wind {s.wind_speed:.1f} m/s"
        if s.wind_gust is not None:
            by_gust = _level_for(s.wind_gust, self.GUST_LIMITS)
            if by_gust > level:
                level = by_gust
                reason = f"Gusts {s.wind_gust:.1f} m/s"
        if level == RiskLevel.GREEN:
            return None
        return RiskFactor("wind", level, reason)

    def _temperature(self, s: WeatherSnapshot) -> RiskFactor | None:
        t = s.temperature
        if t <= 0 and has_precipitation(s):
            return RiskFactor("temperature", RiskLevel.RED,
                              f"{t:.1f} °C with precipitation: ice risk")
        if t <= -10:
            return RiskFactor("temperature", RiskLevel.ORANGE,
                              f"Severe cold ({t:.1f} °C)")
        if t <= 2:
            return RiskFactor("temperature", RiskLevel.YELLOW,
                              f"Near freezing ({t:.1f} °C): possible ice")
        yellow_heat, orange_heat = self.HEAT_LIMITS
        if t >= orange_heat:
            return RiskFactor("temperature", RiskLevel.ORANGE,
                              f"Extreme heat ({t:.1f} °C)")
        if t >= yellow_heat:
            return RiskFactor("temperature", RiskLevel.YELLOW,
                              f"Heat ({t:.1f} °C): driver breaks, "
                              "perishables")
        return None

    def _air_quality(self, air: AirQuality | None) -> RiskFactor | None:
        if air is None:
            return None
        level = _level_for(air.aqi, self.AQI_LIMITS)
        if level == RiskLevel.GREEN:
            return None
        return RiskFactor("air", level,
                          f"Air quality {air.label.lower()} (AQI {air.aqi}, "
                          f"PM2.5 {air.pm2_5:.0f} µg/m³)")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class Van(VehicleProfile):
    """Delivery van: the baseline limits."""

    name = "Van"
    emoji = "🚐"


class Truck(VehicleProfile):
    """High-sided truck: blown over or off course at lower wind speeds."""

    name = "Truck"
    emoji = "🚛"
    WIND_LIMITS = (7.0, 10.0, 14.0)
    GUST_LIMITS = (12.0, 17.0, 21.0)
    MAX_TRIP_KM = 3000.0              # long-haul, with rest stops
    MAX_AVG_SPEED_KMH = 80.0


class Bike(VehicleProfile):
    """Bike or scooter courier: exposed to wind, rain, heat and polluted
    air, which riders breathe hard for their whole shift."""

    name = "Bike"
    emoji = "🛵"
    WIND_LIMITS = (6.0, 9.0, 13.0)
    GUST_LIMITS = (10.0, 14.0, 18.0)
    HEAT_LIMITS = (32.0, 38.0)
    AQI_LIMITS = (3, 4, 5)        # moderate -> yellow ... very poor -> red
    MAX_TRIP_KM = 60.0                # local, last-mile deliveries
    MAX_AVG_SPEED_KMH = 30.0

    def _adjust(self, factors: list[RiskFactor],
                snapshot: WeatherSnapshot) -> list[RiskFactor]:
        """Any rain or snow is one level worse for an open vehicle."""
        adjusted = []
        for factor in factors:
            if factor.kind == "precipitation" and factor.level < RiskLevel.RED:
                factor = RiskFactor(factor.kind, RiskLevel(factor.level + 1),
                                    factor.reason + " (rider exposed)")
            adjusted.append(factor)
        return adjusted


VEHICLES: dict[str, VehicleProfile] = {
    v.name: v for v in (Van(), Truck(), Bike())
}


# ---- geography ------------------------------------------------------------

EARTH_RADIUS_KM = 6371.0
CHECKPOINT_SPACING_KM = 150.0
MAX_CHECKPOINTS = 8          # each one costs an API call per route


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle ("as the crow flies") distance, haversine formula."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def route_points(lat1: float, lon1: float, lat2: float, lon2: float,
                 spacing_km: float = CHECKPOINT_SPACING_KM,
                 max_points: int = MAX_CHECKPOINTS
                 ) -> list[tuple[float, float, float]]:
    """Evenly spaced points strictly between two places, as
    (fraction of the way, lat, lon), along the great circle.

    About one point per `spacing_km`; long routes are capped at
    `max_points` (so the spacing grows). A straight line, not the road.
    """
    total = distance_km(lat1, lon1, lat2, lon2)
    count = min(max_points, max(0, math.ceil(total / spacing_km) - 1))
    if count == 0:
        return []
    angle = total / EARTH_RADIUS_KM

    def to_xyz(lat, lon):
        lat, lon = math.radians(lat), math.radians(lon)
        return (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon),
                math.sin(lat))

    a, b = to_xyz(lat1, lon1), to_xyz(lat2, lon2)
    points = []
    for i in range(1, count + 1):
        f = i / (count + 1)
        wa = math.sin((1 - f) * angle) / math.sin(angle)
        wb = math.sin(f * angle) / math.sin(angle)
        x, y, z = (wa * p + wb * q for p, q in zip(a, b))
        points.append((f, math.degrees(math.atan2(z, math.hypot(x, y))),
                       math.degrees(math.atan2(y, x))))
    return points


# ---- routes and forecasts -----------------------------------------------


@dataclass
class Checkpoint:
    """One point on a route, judged at the time the vehicle passes it."""

    name: str
    km: float                    # straight-line distance from the origin
    passing_at: datetime
    assessment: RiskAssessment

    @property
    def open_water(self) -> bool:
        """OpenWeatherMap names no place over open sea."""
        s = self.assessment.snapshot
        return not s.city and not s.country


@dataclass
class RouteAssessment:
    """A trip: origin at departure, any checkpoints on the way at the time
    they are passed (assuming a steady speed), destination at arrival."""

    origin: RiskAssessment
    destination: RiskAssessment
    departure: datetime
    normal_hours: float
    waypoints: list[Checkpoint] = field(default_factory=list)
    distance_km: float | None = None

    @property
    def arrival(self) -> datetime:
        return self.departure + timedelta(hours=self.normal_hours)

    @property
    def checkpoints(self) -> list[Checkpoint]:
        """Every point judged, origin to destination."""
        return [
            Checkpoint(self.origin.snapshot.label, 0.0, self.departure,
                       self.origin),
            *self.waypoints,
            Checkpoint(self.destination.snapshot.label,
                       self.distance_km or 0.0, self.arrival,
                       self.destination),
        ]

    @property
    def level(self) -> RiskLevel:
        """A route is only as safe as its worst point."""
        return max(c.assessment.level for c in self.checkpoints)

    @property
    def worst(self) -> Checkpoint:
        """The first point with the route's worst signal."""
        return next(c for c in self.checkpoints
                    if c.assessment.level == self.level)

    def trip_hours(self) -> tuple[float, float]:
        low, high = self.level.delay_range
        return self.normal_hours * (1 + low), self.normal_hours * (1 + high)


# The air forecast is hourly but only ~4 days long; beyond that we'd rather
# have no air reading than one from a different day.
AIR_MAX_GAP = timedelta(hours=2)


def nearest_step(forecast: list[WeatherSnapshot],
                 when: datetime) -> WeatherSnapshot:
    """The forecast step closest in time to `when`."""
    if not forecast:
        raise ValueError("The forecast is empty.")
    return min(forecast, key=lambda s: abs(s.fetched_at - when))


def nearest_air(readings: list[AirQuality] | None, when: datetime,
                max_gap: timedelta = AIR_MAX_GAP) -> AirQuality | None:
    """The air reading closest to `when`, or None if none is close enough."""
    if not readings:
        return None
    closest = min(readings, key=lambda r: abs(r.fetched_at - when))
    return closest if abs(closest.fetched_at - when) <= max_gap else None


def assess_route(vehicle: VehicleProfile,
                 origin_forecast: list[WeatherSnapshot],
                 destination_forecast: list[WeatherSnapshot],
                 departure: datetime, normal_hours: float,
                 origin_air: list[AirQuality] | None = None,
                 destination_air: list[AirQuality] | None = None,
                 waypoints: list[tuple[float, list[WeatherSnapshot]]]
                 | None = None,
                 distance: float | None = None) -> RouteAssessment:
    """Origin conditions at departure, destination at arrival.

    `waypoints` are (fraction of the way, forecast) pairs for points in
    between; each is judged at the time the vehicle would pass it. The
    air forecasts are optional; without them only weather is judged.
    """
    arrival = departure + timedelta(hours=normal_hours)
    checkpoints = []
    for fraction, forecast in waypoints or []:
        passing = departure + timedelta(hours=fraction * normal_hours)
        step = nearest_step(forecast, passing)
        checkpoints.append(Checkpoint(
            step.label or "Open water", fraction * (distance or 0.0),
            passing, vehicle.assess(step)))
    return RouteAssessment(
        vehicle.assess(nearest_step(origin_forecast, departure),
                       nearest_air(origin_air, departure)),
        vehicle.assess(nearest_step(destination_forecast, arrival),
                       nearest_air(destination_air, arrival)),
        departure, normal_hours, checkpoints, distance)


def departure_options(vehicle: VehicleProfile,
                      origin_forecast: list[WeatherSnapshot],
                      destination_forecast: list[WeatherSnapshot],
                      normal_hours: float,
                      earliest: datetime | None = None,
                      origin_air: list[AirQuality] | None = None,
                      destination_air: list[AirQuality] | None = None,
                      waypoints: list[tuple[float, list[WeatherSnapshot]]]
                      | None = None,
                      distance: float | None = None
                      ) -> list[RouteAssessment]:
    """The route assessed for every forecast step as a departure time.

    Only departures whose arrival is still inside the destination's
    forecast are included, so each one is backed by real forecast data.
    The same goes for air quality when it is given: its forecast is
    shorter than the weather one, and a departure past its end would look
    safer only because the bad air had dropped out of the data.
    """
    if not origin_forecast or not destination_forecast:
        return []
    trip = timedelta(hours=normal_hours)

    def covered(departure: datetime) -> bool:
        arrival = departure + trip
        if arrival > destination_forecast[-1].fetched_at:
            return False
        if origin_air and nearest_air(origin_air, departure) is None:
            return False
        if destination_air and nearest_air(destination_air, arrival) is None:
            return False
        return True

    return [
        assess_route(vehicle, origin_forecast, destination_forecast,
                     step.fetched_at, normal_hours, origin_air,
                     destination_air, waypoints, distance)
        for step in origin_forecast
        if (earliest is None or step.fetched_at >= earliest)
        and covered(step.fetched_at)
    ]


def route_warnings(vehicle: VehicleProfile, route: RouteAssessment
                   ) -> list[str]:
    """Reasons a route doesn't make sense as one road trip."""
    warnings = []
    distance = route.distance_km
    if distance:
        if distance > vehicle.MAX_TRIP_KM:
            warnings.append(
                f"{distance:,.0f} km in a straight line is beyond a normal "
                f"{vehicle.name.lower()} trip (up to "
                f"{vehicle.MAX_TRIP_KM:,.0f} km).")
        speed = distance / route.normal_hours
        if speed > vehicle.MAX_AVG_SPEED_KMH:
            warnings.append(
                f"Covering {distance:,.0f} km in {route.normal_hours:g} h "
                f"needs an average of {speed:.0f} km/h, faster than a "
                f"{vehicle.name.lower()} can manage "
                f"({vehicle.MAX_AVG_SPEED_KMH:.0f} km/h): the normal trip "
                "time looks too short.")
    at_sea = sum(c.open_water for c in route.waypoints)
    if at_sea:
        warnings.append(
            f"{at_sea} of {len(route.waypoints)} checkpoints are over open "
            "sea, so this is not a road route (it needs a ferry or air "
            "freight).")
    return warnings


def best_departure(options: list[RouteAssessment]
                   ) -> RouteAssessment | None:
    """The earliest departure with the lowest risk level."""
    if not options:
        return None
    return min(options, key=lambda r: (r.level, r.departure))


# ---- analytics over the logged history ----------------------------------


def assess_log(df: pd.DataFrame, vehicle: VehicleProfile) -> pd.DataFrame:
    """The log with `risk` (0-3), `signal` and `reasons` columns added."""
    out = df.copy()
    assessments = [vehicle.assess(WeatherSnapshot.from_record(row))
                   for _, row in df.iterrows()]
    out["risk"] = [int(a.level) for a in assessments]
    out["signal"] = [a.level.name.title() for a in assessments]
    out["reasons"] = ["; ".join(a.reasons) for a in assessments]
    return out


def hub_reliability(df: pd.DataFrame,
                    vehicle: VehicleProfile) -> pd.DataFrame:
    """Share of each city's logged readings at each signal level (%).

    `disrupted` is orange + red: how often deliveries from that hub would
    have faced significant delays or a hold. Sorted most disrupted first.
    """
    levels = [level.name.title() for level in RiskLevel]
    columns = ["location", "readings", *levels, "disrupted"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    assessed = assess_log(df, vehicle)
    shares = (pd.crosstab(assessed["location"], assessed["signal"],
                          normalize="index")
                .reindex(columns=levels, fill_value=0.0) * 100)
    shares["disrupted"] = shares["Orange"] + shares["Red"]
    shares = shares.round(1)
    shares["readings"] = assessed.groupby("location").size()
    out = shares.reset_index()
    return (out.sort_values(["disrupted", "location"],
                            ascending=[False, True])
               .reset_index(drop=True)[columns])
