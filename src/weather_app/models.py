"""Data classes: one WeatherSnapshot = one location at one point in time."""

from datetime import datetime, timezone

# Comfort index tuning: an "ideal" day is ~21 °C, 30-60 % humidity and a
# light breeze. Each step away from that costs points on a 0-100 scale.
IDEAL_TEMP_C = 21.0
TEMP_PENALTY_PER_DEGREE = 3.0
HUMIDITY_RANGE = (30.0, 60.0)
HUMIDITY_PENALTY_PER_PERCENT = 0.5
CALM_WIND_MS = 5.0
WIND_PENALTY_PER_MS = 2.0


def comfort_index(temperature: float, humidity: float,
                  wind_speed: float) -> float:
    """Score how pleasant conditions feel, from 0 (awful) to 100 (ideal).

    A plain function (not only a property) so analytics can apply the
    exact same formula to rows of logged history.
    """
    score = 100.0
    score -= abs(temperature - IDEAL_TEMP_C) * TEMP_PENALTY_PER_DEGREE

    low, high = HUMIDITY_RANGE
    if humidity < low:
        score -= (low - humidity) * HUMIDITY_PENALTY_PER_PERCENT
    elif humidity > high:
        score -= (humidity - high) * HUMIDITY_PENALTY_PER_PERCENT

    if wind_speed > CALM_WIND_MS:
        score -= (wind_speed - CALM_WIND_MS) * WIND_PENALTY_PER_MS

    return round(max(0.0, min(100.0, score)), 1)


class WeatherSnapshot:
    """Current conditions for one city, as fetched at `fetched_at` (UTC)."""

    def __init__(self, city: str, country: str, temperature: float,
                 feels_like: float, humidity: float, wind_speed: float,
                 pressure: float, description: str, icon: str = "",
                 lat: float | None = None, lon: float | None = None,
                 fetched_at: datetime | None = None):
        self.city = city
        self.country = country
        self.temperature = float(temperature)
        self.feels_like = float(feels_like)
        self.humidity = float(humidity)
        self.wind_speed = float(wind_speed)
        self.pressure = float(pressure)
        self.description = description
        self.icon = icon
        self.lat = lat
        self.lon = lon
        self.fetched_at = fetched_at or datetime.now(timezone.utc)

    @classmethod
    def from_api(cls, data: dict) -> "WeatherSnapshot":
        """Build a snapshot from an OpenWeatherMap /weather JSON response."""
        main = data["main"]
        weather = data["weather"][0] if data.get("weather") else {}
        coord = data.get("coord", {})
        return cls(
            city=data["name"],
            country=data.get("sys", {}).get("country", ""),
            temperature=main["temp"],
            feels_like=main["feels_like"],
            humidity=main["humidity"],
            wind_speed=data.get("wind", {}).get("speed", 0.0),
            pressure=main["pressure"],
            description=weather.get("description", ""),
            icon=weather.get("icon", ""),
            lat=coord.get("lat"),
            lon=coord.get("lon"),
        )

    # ---- computed values (not returned by the API) -------------------

    @property
    def feels_like_delta(self) -> float:
        """How much warmer (+) or colder (-) it feels than it measures."""
        return round(self.feels_like - self.temperature, 1)

    @property
    def comfort_index(self) -> float:
        return comfort_index(self.temperature, self.humidity,
                             self.wind_speed)

    @property
    def temperature_f(self) -> float:
        return round(self.temperature * 9 / 5 + 32, 1)

    @property
    def label(self) -> str:
        """'London, GB' — the display name used across the app."""
        return f"{self.city}, {self.country}" if self.country else self.city

    @property
    def icon_url(self) -> str:
        if not self.icon:
            return ""
        return f"https://openweathermap.org/img/wn/{self.icon}@2x.png"

    # ---- conversion to/from a storage row ----------------------------

    def to_record(self) -> dict:
        return {
            "fetched_at": self.fetched_at.isoformat(),
            "city": self.city,
            "country": self.country,
            "temperature": self.temperature,
            "feels_like": self.feels_like,
            "humidity": self.humidity,
            "wind_speed": self.wind_speed,
            "pressure": self.pressure,
            "description": self.description,
            "icon": self.icon,
            "lat": self.lat,
            "lon": self.lon,
        }

    # ---- special methods ---------------------------------------------

    def __repr__(self) -> str:
        return (f"WeatherSnapshot({self.label!r}, {self.temperature}°C, "
                f"fetched_at={self.fetched_at.isoformat()!r})")

    def __str__(self) -> str:
        return (f"{self.label}: {self.temperature:.1f}°C "
                f"(feels {self.feels_like:.1f}°C), {self.description}, "
                f"humidity {self.humidity:.0f}%, "
                f"wind {self.wind_speed:.1f} m/s")

    def __eq__(self, other) -> bool:
        # Two snapshots are the same observation if they're for the same
        # place at the same moment.
        if not isinstance(other, WeatherSnapshot):
            return NotImplemented
        return (self.label == other.label
                and self.fetched_at == other.fetched_at)

    def __hash__(self) -> int:
        # Defining __eq__ removes the default hash; restore one that agrees
        # with __eq__ so snapshots still work in sets and as dict keys.
        return hash((self.label, self.fetched_at))

    def __lt__(self, other) -> bool:
        # Lets sorted(snapshots) order them coldest -> warmest.
        if not isinstance(other, WeatherSnapshot):
            return NotImplemented
        return self.temperature < other.temperature
