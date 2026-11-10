"""Business use case: weather-driven delivery risk for a logistics team.

Every reading (live, logged or forecast) is turned into a traffic-light
signal with an estimated delay:

    GREEN   normal operations             +0 %
    YELLOW  minor delays                  +10-20 %
    ORANGE  significant delays            +25-50 %
    RED     unsafe: hold or reroute       +50-100 %

The signal is the worst of four factors: precipitation, visibility, wind
and temperature. Vehicle types tolerate weather differently (a high-sided
truck is more exposed to wind, a bike courier to rain), so each one is a
VehicleProfile subclass with its own limits.

The thresholds and delay ranges are our own rule-based assumptions, set
from common road-safety guidance (e.g. gale force starts at 17 m/s, fog
means visibility under 1 km). They are not calibrated on real delivery
data.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum

import pandas as pd

from .models import WeatherSnapshot


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

    kind: str          # "precipitation", "visibility", "wind", "temperature"
    level: RiskLevel
    reason: str


@dataclass
class RiskAssessment:
    """The signal for one reading and one vehicle type, with its reasons."""

    snapshot: WeatherSnapshot
    vehicle: str
    factors: list[RiskFactor] = field(default_factory=list)

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

    def assess(self, snapshot: WeatherSnapshot) -> RiskAssessment:
        factors = [factor for factor in (
            self._precipitation(snapshot),
            self._visibility(snapshot),
            self._wind(snapshot),
            self._temperature(snapshot),
        ) if factor is not None]
        return RiskAssessment(snapshot, self.name,
                              self._adjust(factors, snapshot))

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


class Bike(VehicleProfile):
    """Bike or scooter courier: exposed to wind, rain and heat."""

    name = "Bike"
    emoji = "🛵"
    WIND_LIMITS = (6.0, 9.0, 13.0)
    GUST_LIMITS = (10.0, 14.0, 18.0)
    HEAT_LIMITS = (32.0, 38.0)

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


# ---- routes and forecasts -----------------------------------------------


@dataclass
class RouteAssessment:
    """A trip: origin weather at departure, destination at arrival."""

    origin: RiskAssessment
    destination: RiskAssessment
    departure: datetime
    normal_hours: float

    @property
    def arrival(self) -> datetime:
        return self.departure + timedelta(hours=self.normal_hours)

    @property
    def level(self) -> RiskLevel:
        """A route is only as safe as its worst end."""
        return max(self.origin.level, self.destination.level)

    def trip_hours(self) -> tuple[float, float]:
        low, high = self.level.delay_range
        return self.normal_hours * (1 + low), self.normal_hours * (1 + high)


def nearest_step(forecast: list[WeatherSnapshot],
                 when: datetime) -> WeatherSnapshot:
    """The forecast step closest in time to `when`."""
    if not forecast:
        raise ValueError("The forecast is empty.")
    return min(forecast, key=lambda s: abs(s.fetched_at - when))


def assess_route(vehicle: VehicleProfile,
                 origin_forecast: list[WeatherSnapshot],
                 destination_forecast: list[WeatherSnapshot],
                 departure: datetime, normal_hours: float
                 ) -> RouteAssessment:
    arrival = departure + timedelta(hours=normal_hours)
    return RouteAssessment(
        vehicle.assess(nearest_step(origin_forecast, departure)),
        vehicle.assess(nearest_step(destination_forecast, arrival)),
        departure, normal_hours)


def departure_options(vehicle: VehicleProfile,
                      origin_forecast: list[WeatherSnapshot],
                      destination_forecast: list[WeatherSnapshot],
                      normal_hours: float,
                      earliest: datetime | None = None
                      ) -> list[RouteAssessment]:
    """The route assessed for every forecast step as a departure time.

    Only departures whose arrival is still inside the destination's
    forecast are included, so each one is backed by real forecast data.
    """
    if not origin_forecast or not destination_forecast:
        return []
    last = destination_forecast[-1].fetched_at
    return [
        assess_route(vehicle, origin_forecast, destination_forecast,
                     step.fetched_at, normal_hours)
        for step in origin_forecast
        if (earliest is None or step.fetched_at >= earliest)
        and step.fetched_at + timedelta(hours=normal_hours) <= last
    ]


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
