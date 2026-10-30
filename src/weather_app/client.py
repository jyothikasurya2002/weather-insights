"""API clients: a generic JSON client and an OpenWeatherMap subclass."""

import requests

from .models import WeatherSnapshot

# ---- exceptions: one per failure mode --------------------------------


class APIError(Exception):
    """Base class for every error raised by an API client."""


class InvalidInputError(APIError, ValueError):
    """The user's input was rejected before any request was sent."""


class AuthenticationError(APIError):
    """The API key is missing, invalid, or not yet activated (HTTP 401)."""


class NotFoundError(APIError):
    """The requested resource does not exist (HTTP 404)."""


class LocationNotFoundError(NotFoundError):
    """OpenWeatherMap has no city matching the given name."""


class RateLimitError(APIError):
    """Too many requests in a short time (HTTP 429)."""


class NetworkError(APIError):
    """No usable response: timeout, no connection, or a 5xx server error."""


# ---- generic client ---------------------------------------------------


class JSONAPIClient:
    """Calls any JSON-over-HTTP API and turns failures into APIError types.

    Nothing here is weather-specific: a different provider would subclass
    this, set its base URL, and override `_default_params` for its own
    authentication scheme.
    """

    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    def _default_params(self) -> dict:
        """Query parameters sent with every request (e.g. an API key)."""
        return {}

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        query = {**self._default_params(), **(params or {})}
        # requests' own error messages include the full URL — and therefore
        # the API key — so we never pass them through to the user.
        try:
            response = self._session.get(url, params=query,
                                         timeout=self.timeout)
        except requests.Timeout:
            raise NetworkError(
                f"The server took longer than {self.timeout:.0f}s to "
                "respond. Please try again.") from None
        except requests.ConnectionError:
            raise NetworkError(
                "Could not connect to the weather service. Check your "
                "internet connection.") from None

        self._raise_for_status(response)

        try:
            return response.json()
        except ValueError:
            raise APIError("The server returned a response that is not "
                           "valid JSON.") from None

    def _raise_for_status(self, response: requests.Response) -> None:
        status = response.status_code
        if status == 200:
            return
        if status == 401:
            raise AuthenticationError(
                "The API key was rejected. Check that it is correct — new "
                "OpenWeatherMap keys can take up to 2 hours to activate.")
        if status == 404:
            raise NotFoundError("The requested resource was not found.")
        if status == 429:
            raise RateLimitError(
                "Too many requests. Wait a minute and try again.")
        if status >= 500:
            raise NetworkError(
                f"The weather service is having problems (HTTP {status}). "
                "Please try again later.")
        raise APIError(f"Unexpected response from the server "
                       f"(HTTP {status}).")


# ---- OpenWeatherMap-specific client -----------------------------------

ALLOWED_PUNCTUATION = set(" ,.'-")
MAX_CITY_LENGTH = 85


class OpenWeatherClient(JSONAPIClient):
    """Fetches current conditions from OpenWeatherMap's /weather endpoint."""

    BASE_URL = "https://api.openweathermap.org/data/2.5"

    def __init__(self, api_key: str, units: str = "metric",
                 timeout: float = 10.0):
        if not api_key:
            raise AuthenticationError("No API key was provided.")
        super().__init__(self.BASE_URL, timeout=timeout)
        self.units = units
        # Name-mangled so it can't be read by accident from outside
        # (client.__api_key fails) and never shows up in __repr__.
        self.__api_key = api_key

    def _default_params(self) -> dict:
        return {"appid": self.__api_key, "units": self.units}

    @staticmethod
    def validate_city(city: str) -> str:
        """Return a cleaned city name, or raise InvalidInputError.

        Accepts names like "São Paulo", "St. John's" or "London,GB"
        (city plus optional country code).
        """
        if not isinstance(city, str):
            raise InvalidInputError("City name must be text.")
        cleaned = " ".join(city.split())
        if not cleaned:
            raise InvalidInputError("Please enter a city name.")
        if len(cleaned) > MAX_CITY_LENGTH:
            raise InvalidInputError(
                f"City name is too long (max {MAX_CITY_LENGTH} "
                "characters).")
        if not any(ch.isalpha() for ch in cleaned):
            raise InvalidInputError(
                f"'{cleaned}' doesn't look like a city name.")
        bad = sorted({ch for ch in cleaned
                      if not ch.isalpha() and ch not in ALLOWED_PUNCTUATION})
        if bad:
            raise InvalidInputError(
                f"City name contains invalid characters: {' '.join(bad)}")
        return cleaned

    def fetch_current(self, city: str) -> WeatherSnapshot:
        """Validate `city`, call the API, and return a WeatherSnapshot."""
        cleaned = self.validate_city(city)
        try:
            data = self._get("weather", {"q": cleaned})
        except NotFoundError:
            raise LocationNotFoundError(
                f"City '{cleaned}' was not found. Check the spelling, or "
                "add a country code like 'Paris,FR'.") from None
        try:
            return WeatherSnapshot.from_api(data)
        except (KeyError, IndexError, TypeError):
            raise APIError(f"Unexpected data format returned for "
                           f"'{cleaned}'.") from None

    def fetch_many(self, cities: list[str]
                   ) -> tuple[list[WeatherSnapshot], dict[str, str]]:
        """Fetch several cities, skipping any that fail.

        Returns (snapshots, failures) where failures maps each skipped
        city to the reason it was skipped. A bad key affects every city,
        so AuthenticationError is re-raised instead of being repeated.
        """
        snapshots: list[WeatherSnapshot] = []
        failures: dict[str, str] = {}
        for city in cities:
            try:
                snapshots.append(self.fetch_current(city))
            except AuthenticationError:
                raise
            except APIError as error:
                failures[city] = str(error)
        return snapshots, failures

    def __repr__(self) -> str:
        return (f"OpenWeatherClient(units={self.units!r}, "
                f"timeout={self.timeout})")
