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


def _optional_float(value) -> float | None:
    """float(value), or None for a missing value (None, "" or NaN)."""
    if value is None or value == "":
        return None
    value = float(value)
    return None if value != value else value  # NaN != NaN


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
    """Conditions for one city at `fetched_at` (UTC).

    Usually an observation we fetched; for a forecast, `fetched_at` is the
    time the forecast is for. The last five arguments are the details the
    logistics risk rules need; older log rows don't have them, so they are
    optional and None when unknown.
    """

    def __init__(self, city: str, country: str, temperature: float,
                 feels_like: float, humidity: float, wind_speed: float,
                 pressure: float, description: str, icon: str = "",
                 lat: float | None = None, lon: float | None = None,
                 fetched_at: datetime | None = None,
                 condition_id: int | None = None,
                 visibility: float | None = None,
                 wind_gust: float | None = None,
                 rain_mm_h: float | None = None,
                 snow_mm_h: float | None = None):
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
        # OpenWeatherMap condition code, e.g. 500 = light rain, 211 =
        # thunderstorm: https://openweathermap.org/weather-conditions
        condition_id = _optional_float(condition_id)
        self.condition_id = None if condition_id is None else int(condition_id)
        self.visibility = _optional_float(visibility)    # metres, max 10000
        self.wind_gust = _optional_float(wind_gust)      # m/s
        self.rain_mm_h = _optional_float(rain_mm_h)      # mm per hour
        self.snow_mm_h = _optional_float(snow_mm_h)      # mm per hour

    @classmethod
    def _from_owm(cls, item: dict, city: str, country: str, coord: dict,
                  precip_key: str, precip_hours: float,
                  fetched_at: datetime | None = None) -> "WeatherSnapshot":
        """Shared parsing for /weather responses and /forecast list items.

        Rain and snow come as mm over the last hour ("1h") for current
        weather and over 3 hours ("3h") for a forecast step, so both are
        converted to mm per hour.
        """
        main = item["main"]
        weather = item["weather"][0] if item.get("weather") else {}
        wind = item.get("wind", {})

        def per_hour(kind: str) -> float | None:
            amount = (item.get(kind) or {}).get(precip_key)
            return None if amount is None else amount / precip_hours

        return cls(
            city=city,
            country=country,
            temperature=main["temp"],
            feels_like=main["feels_like"],
            humidity=main["humidity"],
            wind_speed=wind.get("speed", 0.0),
            pressure=main["pressure"],
            description=weather.get("description", ""),
            icon=weather.get("icon", ""),
            lat=coord.get("lat"),
            lon=coord.get("lon"),
            fetched_at=fetched_at,
            condition_id=weather.get("id"),
            visibility=item.get("visibility"),
            wind_gust=wind.get("gust"),
            rain_mm_h=per_hour("rain"),
            snow_mm_h=per_hour("snow"),
        )

    @classmethod
    def from_api(cls, data: dict) -> "WeatherSnapshot":
        """Build a snapshot from an OpenWeatherMap /weather JSON response."""
        return cls._from_owm(data, data["name"],
                             data.get("sys", {}).get("country", ""),
                             data.get("coord", {}), "1h", 1.0)

    @classmethod
    def from_forecast(cls, item: dict, city: dict) -> "WeatherSnapshot":
        """Build a snapshot from one 3-hour step of a /forecast response.

        `item` is an element of the response's "list"; `city` is its
        "city" object. `fetched_at` is set to the time the step is for.
        """
        return cls._from_owm(
            item, city["name"], city.get("country", ""),
            city.get("coord", {}), "3h", 3.0,
            fetched_at=datetime.fromtimestamp(item["dt"], timezone.utc))

    @classmethod
    def from_record(cls, record) -> "WeatherSnapshot":
        """Rebuild a snapshot from a log row (a dict or a pandas row)."""
        fetched_at = record["fetched_at"]
        if isinstance(fetched_at, str):
            fetched_at = datetime.fromisoformat(fetched_at)
        elif hasattr(fetched_at, "to_pydatetime"):
            fetched_at = fetched_at.to_pydatetime()
        return cls(
            city=record["city"],
            country=record.get("country", "") or "",
            temperature=record["temperature"],
            feels_like=record["feels_like"],
            humidity=record["humidity"],
            wind_speed=record["wind_speed"],
            pressure=record["pressure"],
            description=record.get("description", "") or "",
            icon=record.get("icon", "") or "",
            lat=_optional_float(record.get("lat")),
            lon=_optional_float(record.get("lon")),
            fetched_at=fetched_at,
            condition_id=record.get("condition_id"),
            visibility=record.get("visibility"),
            wind_gust=record.get("wind_gust"),
            rain_mm_h=record.get("rain_mm_h"),
            snow_mm_h=record.get("snow_mm_h"),
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
            "condition_id": self.condition_id,
            "visibility": self.visibility,
            "wind_gust": self.wind_gust,
            "rain_mm_h": self.rain_mm_h,
            "snow_mm_h": self.snow_mm_h,
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
