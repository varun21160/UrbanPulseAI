"""
Unit Tests for Weather Collector (src/collect_weather.py)
Tests timestamp normalization, missing API fields, and HTTP error handling with synthetic mocks.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
import requests

from src.collect_weather import WeatherCollector, get_weather_description
from src.config import get_config
from tests.fixtures import (
    SYNTHETIC_OPEN_METEO_MISSING_CURRENT_PAYLOAD,
    SYNTHETIC_OPEN_METEO_SUCCESS_PAYLOAD,
)


def test_timestamp_normalization_naive_iso():
    """Verify naive ISO timestamp (e.g. '2026-10-25T12:00') is normalized to timezone-aware UTC."""
    config = get_config()
    collector = WeatherCollector(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "latitude": 17.385,
        "longitude": 78.4867,
        "current": {
            "time": "2026-10-25T12:00",
            "temperature_2m": 29.5,
            "relative_humidity_2m": 30.0,
            "precipitation": 0.0,
            "rain": 0.0,
            "showers": 0.0,
            "weather_code": 1,
            "wind_speed_10m": 12.0,
            "wind_gusts_10m": 30.0,
            "cloud_cover": 20.0,
        },
    }

    with patch.object(collector.session, "get", return_value=mock_resp):
        obs = collector.fetch_weather("hyderabad-central", 17.385, 78.4867)

    assert isinstance(obs["observed_at"], datetime)
    assert obs["observed_at"].tzinfo is not None
    assert obs["observed_at"].tzinfo == timezone.utc
    assert obs["observed_at"].hour == 12
    assert obs["observed_at"].minute == 0


def test_timestamp_normalization_with_offset():
    """Verify timestamp with timezone offset is normalized correctly to UTC."""
    config = get_config()
    collector = WeatherCollector(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # 17:30 IST (+05:30) is 12:00 UTC
    mock_resp.json.return_value = {
        "current": {
            "time": "2026-10-25T17:30:00+05:30",
            "temperature_2m": 29.5,
            "weather_code": 0,
        }
    }

    with patch.object(collector.session, "get", return_value=mock_resp):
        obs = collector.fetch_weather("hyderabad-central", 17.385, 78.4867)

    assert obs["observed_at"].tzinfo == timezone.utc
    assert obs["observed_at"].hour == 12
    assert obs["observed_at"].minute == 0


def test_missing_current_block_raises_value_error():
    """Verify that an API response missing the 'current' dictionary raises ValueError."""
    config = get_config()
    collector = WeatherCollector(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SYNTHETIC_OPEN_METEO_MISSING_CURRENT_PAYLOAD

    with patch.object(collector.session, "get", return_value=mock_resp):
        with pytest.raises(ValueError, match="No current weather data returned"):
            collector.fetch_weather("gachibowli", 17.4401, 78.3489)


def test_api_server_error_propagates():
    """Verify that HTTP 500 server error raises an HTTPError and does not fabricate readings."""
    config = get_config()
    collector = WeatherCollector(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")

    with patch.object(collector.session, "get", return_value=mock_resp):
        with pytest.raises(requests.exceptions.HTTPError):
            collector.fetch_weather("secunderabad", 17.4399, 78.4983)


def test_api_timeout_raises_exception():
    """Verify request timeout raises Timeout exception without generating data."""
    config = get_config()
    collector = WeatherCollector(config)

    with patch.object(collector.session, "get", side_effect=requests.exceptions.Timeout("Connection timed out")):
        with pytest.raises(requests.exceptions.Timeout):
            collector.fetch_weather("kukatpally", 17.4849, 78.4138)


def test_api_rate_limit_backoff():
    """Verify that HTTP 429 rate limit triggers backoff sleep and retries request."""
    config = get_config()
    collector = WeatherCollector(config)

    # First response: 429 Too Many Requests with Retry-After header
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "1"}

    # Second response: 200 OK with valid synthetic payload
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = SYNTHETIC_OPEN_METEO_SUCCESS_PAYLOAD

    with patch.object(collector.session, "get", side_effect=[resp_429, resp_200]):
        with patch("time.sleep") as mock_sleep:
            obs = collector.fetch_weather("lb-nagar", 17.3457, 78.5522)
            mock_sleep.assert_called_with(1.0)

    assert obs["location_id"] == "lb-nagar"
    assert obs["temperature_c"] == 29.5


def test_weather_code_descriptions():
    """Verify that WMO codes map to recognizable human-readable weather descriptions."""
    assert get_weather_description(0) == "Clear sky"
    assert get_weather_description(1) == "Mainly clear"
    assert get_weather_description(3) == "Overcast"
    assert get_weather_description(61) == "Slight rain"
    assert get_weather_description(95) == "Thunderstorm"
    assert get_weather_description(None) == "Unknown"
