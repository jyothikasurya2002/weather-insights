"""Client tests with a fake HTTP session — no network or API key needed."""

import pytest
import requests

from weather_app.client import (
    AuthenticationError,
    InvalidInputError,
    LocationNotFoundError,
    NetworkError,
    OpenWeatherClient,
    RateLimitError,
)

LONDON_JSON = {
    "name": "London",
    "sys": {"country": "GB"},
    "coord": {"lat": 51.51, "lon": -0.13},
    "main": {"temp": 12.0, "feels_like": 10.5, "humidity": 80,
             "pressure": 1012},
    "wind": {"speed": 4.1},
    "weather": [{"description": "light rain", "icon": "10d"}],
}


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    """Returns a canned response per city, or raises a canned exception."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        result = self.responses[params["q"]]
        if isinstance(result, Exception):
            raise result
        return result


def make_client(responses):
    client = OpenWeatherClient("test-key")
    client._session = FakeSession(responses)
    return client


def test_fetch_current_builds_snapshot():
    client = make_client({"London": FakeResponse(200, LONDON_JSON)})
    snap = client.fetch_current("  London ")
    assert snap.label == "London, GB"
    assert snap.temperature == 12.0
    assert snap.feels_like_delta == -1.5


def test_api_key_and_units_are_sent():
    client = make_client({"London": FakeResponse(200, LONDON_JSON)})
    client.fetch_current("London")
    params = client._session.calls[0]
    assert params["appid"] == "test-key"
    assert params["units"] == "metric"


@pytest.mark.parametrize("status, error", [
    (404, LocationNotFoundError),
    (401, AuthenticationError),
    (429, RateLimitError),
    (503, NetworkError),
])
def test_status_codes_map_to_specific_errors(status, error):
    client = make_client({"X": FakeResponse(status, {})})
    with pytest.raises(error):
        client.fetch_current("X")


def test_connection_error_hides_url_with_key():
    boom = requests.ConnectionError("failed: https://...?appid=test-key")
    client = make_client({"London": boom})
    with pytest.raises(NetworkError) as info:
        client.fetch_current("London")
    assert "test-key" not in str(info.value)


@pytest.mark.parametrize("bad", ["", "   ", "12345", "London<script>",
                                 "a" * 200])
def test_invalid_input_rejected_before_request(bad):
    client = make_client({})
    with pytest.raises(InvalidInputError):
        client.fetch_current(bad)
    assert client._session.calls == []


@pytest.mark.parametrize("good", ["São Paulo", "St. John's", "London,GB",
                                  "Winston-Salem"])
def test_valid_city_names_accepted(good):
    assert OpenWeatherClient.validate_city(good) == good


def test_fetch_many_skips_failures():
    client = make_client({
        "London": FakeResponse(200, LONDON_JSON),
        "Atlantis": FakeResponse(404, {}),
    })
    snapshots, failures = client.fetch_many(["London", "Atlantis", ""])
    assert [s.city for s in snapshots] == ["London"]
    assert set(failures) == {"Atlantis", ""}


def test_fetch_many_stops_on_bad_key():
    client = make_client({"London": FakeResponse(401, {})})
    with pytest.raises(AuthenticationError):
        client.fetch_many(["London", "Paris"])


def test_api_key_is_private_and_not_in_repr():
    client = OpenWeatherClient("secret-123")
    assert not hasattr(client, "__api_key")
    assert "secret-123" not in repr(client)
