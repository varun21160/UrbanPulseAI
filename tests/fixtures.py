"""
UrbanPulseAI - Synthetic Test Fixtures
All payloads in this module are synthetic and generated strictly for automated testing.
Do not use in production.
"""

from datetime import datetime, timezone
from typing import Any, Dict

# Synthetic valid Open-Meteo API response for Hyderabad Central
SYNTHETIC_OPEN_METEO_SUCCESS_PAYLOAD: Dict[str, Any] = {
    "latitude": 17.385,
    "longitude": 78.4867,
    "generationtime_ms": 0.12,
    "utc_offset_seconds": 0,
    "timezone": "GMT",
    "timezone_abbreviation": "GMT",
    "elevation": 505.0,
    "current_units": {
        "time": "iso8601",
        "interval": "seconds",
        "temperature_2m": "°C",
        "relative_humidity_2m": "%",
        "precipitation": "mm",
        "rain": "mm",
        "showers": "mm",
        "weather_code": "wmo code",
        "wind_speed_10m": "km/h",
        "wind_gusts_10m": "km/h",
        "cloud_cover": "%",
    },
    "current": {
        "time": "2026-10-25T12:00",
        "interval": 900,
        "temperature_2m": 29.5,
        "relative_humidity_2m": 30.0,
        "precipitation": 0.0,
        "rain": 0.0,
        "showers": 0.0,
        "weather_code": 1,
        "wind_speed_10m": 12.5,
        "wind_gusts_10m": 32.0,
        "cloud_cover": 20.0,
    },
}

# Synthetic payload missing the 'current' weather block
SYNTHETIC_OPEN_METEO_MISSING_CURRENT_PAYLOAD: Dict[str, Any] = {
    "latitude": 17.385,
    "longitude": 78.4867,
    "generationtime_ms": 0.05,
    "current_units": {},
}

# Synthetic payload with missing temperature measurement
SYNTHETIC_OPEN_METEO_MISSING_TEMP_PAYLOAD: Dict[str, Any] = {
    "latitude": 17.385,
    "longitude": 78.4867,
    "current": {
        "time": "2026-10-25T12:00",
        "temperature_2m": None,  # Missing critical temperature
        "relative_humidity_2m": 35.0,
        "precipitation": 0.0,
        "rain": 0.0,
        "showers": 0.0,
        "weather_code": 1,
        "wind_speed_10m": 10.0,
        "wind_gusts_10m": 25.0,
        "cloud_cover": 15.0,
    },
}

# Synthetic payload with physically impossible temperature (out-of-bounds)
SYNTHETIC_OPEN_METEO_OUT_OF_BOUNDS_TEMP_PAYLOAD: Dict[str, Any] = {
    "latitude": 17.385,
    "longitude": 78.4867,
    "current": {
        "time": "2026-10-25T12:00",
        "temperature_2m": 85.0,  # Invalid: 85°C exceeds maximum threshold (60°C)
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

# Synthetic payload with negative relative humidity
SYNTHETIC_OPEN_METEO_NEGATIVE_HUMIDITY_PAYLOAD: Dict[str, Any] = {
    "latitude": 17.385,
    "longitude": 78.4867,
    "current": {
        "time": "2026-10-25T12:00",
        "temperature_2m": 28.0,
        "relative_humidity_2m": -15.0,  # Invalid: Negative humidity
        "precipitation": 0.0,
        "rain": 0.0,
        "showers": 0.0,
        "weather_code": 1,
        "wind_speed_10m": 12.0,
        "wind_gusts_10m": 30.0,
        "cloud_cover": 20.0,
    },
}

# Synthetic standardized observation record for database unit testing
SYNTHETIC_OBSERVATION_RECORD: Dict[str, Any] = {
    "location_id": "hyderabad-central",
    "source": "open-meteo",
    "observed_at": datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc),
    "temperature_c": 29.5,
    "relative_humidity_pct": 30.0,
    "precipitation_mm": 0.0,
    "rain_mm": 0.0,
    "showers_mm": 0.0,
    "weather_code": 1,
    "weather_description": "Mainly clear",
    "wind_speed_kmh": 12.5,
    "wind_gusts_kmh": 32.0,
    "cloud_cover_pct": 20.0,
    "data_type": "live_api",
    "raw_payload": {"synthetic": True, "location": "hyderabad-central"},
}


def generate_synthetic_history(
    count: int = 10,
    location_id: str = "hyderabad-central",
    base_temp: float = 28.5,
    base_hum: float = 30.0,
    base_wind: float = 12.0,
    base_rain: float = 0.0,
    temp_noise: float = 0.5,
) -> list[Dict[str, Any]]:
    """
    Generate synthetic chronological historical observation records for testing baselines.
    Labeled explicitly as synthetic test fixtures.
    """
    from datetime import timedelta
    records: list[Dict[str, Any]] = []
    base_time = datetime(2026, 10, 25, 6, 0, 0, tzinfo=timezone.utc)

    for i in range(count):
        t = base_time + timedelta(minutes=15 * i)
        noise = (i % 3 - 1) * temp_noise
        records.append({
            "observation_id": 1000 + i,
            "location_id": location_id,
            "source": "open-meteo",
            "observed_at": t,
            "temperature_c": round(base_temp + noise, 2),
            "relative_humidity_pct": round(base_hum + (i % 2), 1),
            "precipitation_mm": base_rain,
            "rain_mm": base_rain,
            "showers_mm": 0.0,
            "weather_code": 0,
            "wind_speed_kmh": round(base_wind + (i % 3), 1),
            "wind_gusts_kmh": round(base_wind * 2.0, 1),
            "cloud_cover_pct": 10.0,
            "data_type": "synthetic_test",
        })
    return records


SYNTHETIC_ANOMALY_RECORD: Dict[str, Any] = {
    "location_id": "hyderabad-central",
    "observed_at": datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc),
    "detected_at": datetime(2026, 10, 25, 12, 5, 0, tzinfo=timezone.utc),
    "anomaly_type": "temperature_spike",
    "severity": "HIGH",
    "risk_score": 0.85,
    "model_name": "statistical_mad",
    "model_version": "1.0.0",
    "observed_value": 42.5,
    "baseline_value": 28.5,
    "evidence": {
        "synthetic": True,
        "feature": "temperature_c",
        "observed_value": 42.5,
        "baseline_median": 28.5,
        "baseline_mad": 0.5,
        "modified_z_score": 18.88,
        "deviation": 14.0,
        "explanation": "Synthetic test temperature spike",
    },
    "status": "active",
}


# Synthetic TomTom Routing API response
SYNTHETIC_TOMTOM_ROUTE_SUCCESS_PAYLOAD: Dict[str, Any] = {
    "formatVersion": "0.0.12",
    "routes": [
        {
            "summary": {
                "lengthInMeters": 16500,
                "travelTimeInSeconds": 1860,
                "trafficDelayInSeconds": 360,
                "trafficLengthInMeters": 2400,
                "departureTime": "2026-10-26T09:15:00Z",
                "arrivalTime": "2026-10-26T09:46:00Z",
                "noTrafficTravelTimeInSeconds": 1500,
            },
            "legs": [
                {
                    "summary": {
                        "lengthInMeters": 16500,
                        "travelTimeInSeconds": 1860,
                        "trafficDelayInSeconds": 360,
                        "trafficLengthInMeters": 2400,
                        "departureTime": "2026-10-26T09:15:00Z",
                        "arrivalTime": "2026-10-26T09:46:00Z",
                        "noTrafficTravelTimeInSeconds": 1500,
                    }
                }
            ],
        }
    ],
}

# Synthetic corridor travel time record for database testing
SYNTHETIC_TRAFFIC_OBSERVATION_RECORD: Dict[str, Any] = {
    "route_id": "gachibowli-central",
    "provider": "tomtom",
    "observed_at": datetime(2026, 10, 26, 9, 15, 0, tzinfo=timezone.utc),
    "estimated_duration_seconds": 1860.0,
    "free_flow_duration_seconds": 1500.0,
    "delay_seconds": 360.0,
    "distance_meters": 16500.0,
    "congestion_index": 1.24,
    "data_type": "test_fixture",
    "raw_payload": {"synthetic": True, "provider": "tomtom_mock"},
}


