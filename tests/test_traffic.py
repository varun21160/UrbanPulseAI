"""
Unit & Integration Tests for Traffic Disruption Intelligence
Tests API failure handling, disabled credentials state, missing reference fields,
duplicate record handling, cold-start / insufficient history protection,
MAD anomaly scoring, and evidence-based weather correlation.
All external API responses are synthetic mocks.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
import requests

from src.collect_traffic import TrafficCollector
from src.config import AppConfig, CorridorInfo, TrafficConfig, get_config
from src.database import DatabaseManager
from src.detector_traffic import TrafficDisruptionDetector
from tests.fixtures import (
    SYNTHETIC_TOMTOM_ROUTE_SUCCESS_PAYLOAD,
    SYNTHETIC_TRAFFIC_OBSERVATION_RECORD,
)


@pytest.fixture
def db_manager():
    """Provides DatabaseManager connected to test database with traffic tables initialized."""
    config = get_config()
    db = DatabaseManager(config.db)
    db.init_traffic_tables()
    return db


@pytest.fixture
def test_corridor():
    """Sample corridor for unit testing."""
    return CorridorInfo(
        corridor_id="gachibowli-central",
        name="Gachibowli -> Hyderabad Central",
        origin_location_id="gachibowli",
        destination_location_id="hyderabad-central",
        origin_latitude=17.4401,
        origin_longitude=78.3489,
        destination_latitude=17.3850,
        destination_longitude=78.4867,
        via_road="Old Mumbai Highway",
        distance_km=16.5,
    )


# -----------------------------------------------------------------------------
# 1. API Failure & Disabled Credential Tests
# -----------------------------------------------------------------------------

def test_collector_disabled_state_when_no_api_key(test_corridor):
    """
    When TOMTOM_API_KEY is not configured, collector must report disabled state
    and refuse to poll without credentials (no fabricated data).
    """
    cfg = AppConfig()
    cfg.traffic.api_key = ""  # Explicitly empty
    collector = TrafficCollector(cfg)

    assert collector.is_configured is False
    status_info = collector.get_status_info()
    assert status_info["configured"] is False
    assert "missing" in status_info["instructions"].lower()

    # Attempting to fetch route directly raises ValueError
    with pytest.raises(ValueError, match="TomTom API key not configured"):
        collector.fetch_route_travel_time(test_corridor)


def test_collector_api_unauthorized_401(test_corridor):
    """HTTP 401/403 unauthorized error must raise PermissionError with clear message."""
    cfg = AppConfig()
    cfg.traffic.api_key = "invalid_dummy_key_12345"
    collector = TrafficCollector(cfg)

    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch.object(collector.session, "get", return_value=mock_resp):
        with pytest.raises(PermissionError, match="rejected credentials"):
            collector.fetch_route_travel_time(test_corridor)


def test_collector_api_rate_limit_429(test_corridor):
    """HTTP 429 rate limit exceeded must raise RuntimeError to trigger backoff."""
    cfg = AppConfig()
    cfg.traffic.api_key = "valid_format_key_12345"
    collector = TrafficCollector(cfg)

    mock_resp = MagicMock()
    mock_resp.status_code = 429

    with patch.object(collector.session, "get", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="rate limit or quota exceeded"):
            collector.fetch_route_travel_time(test_corridor)


def test_collector_api_timeout(test_corridor):
    """Network connection timeout must cleanly propagate."""
    cfg = AppConfig()
    cfg.traffic.api_key = "valid_format_key_12345"
    collector = TrafficCollector(cfg)

    with patch.object(collector.session, "get", side_effect=requests.exceptions.Timeout("Connection timed out")):
        with pytest.raises(requests.exceptions.Timeout):
            collector.fetch_route_travel_time(test_corridor)


# -----------------------------------------------------------------------------
# 2. Response Parsing & Congestion Index Tests
# -----------------------------------------------------------------------------

def test_collector_successful_parsing(test_corridor):
    """Valid TomTom payload must be correctly parsed into travel time, free flow, and congestion index."""
    cfg = AppConfig()
    cfg.traffic.api_key = "valid_format_key_12345"
    collector = TrafficCollector(cfg)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SYNTHETIC_TOMTOM_ROUTE_SUCCESS_PAYLOAD

    with patch.object(collector.session, "get", return_value=mock_resp):
        rec = collector.fetch_route_travel_time(test_corridor)

    assert rec["route_id"] == "gachibowli-central"
    assert rec["estimated_duration_seconds"] == 1860.0
    assert rec["free_flow_duration_seconds"] == 1500.0
    assert rec["delay_seconds"] == 360.0
    # Congestion Index = 1860 / 1500 = 1.24
    assert rec["congestion_index"] == 1.24
    assert rec["observed_at"].tzinfo is not None


def test_collector_missing_free_flow_reference(test_corridor):
    """
    Requirement 8: Calculate a congestion index only when the required reference value exists.
    If noTrafficTravelTimeInSeconds is missing from response, congestion_index must be None.
    """
    cfg = AppConfig()
    cfg.traffic.api_key = "valid_format_key_12345"
    collector = TrafficCollector(cfg)

    payload_no_free_flow = {
        "routes": [
            {
                "summary": {
                    "lengthInMeters": 16500,
                    "travelTimeInSeconds": 1800,
                    "trafficDelayInSeconds": 300,
                    # noTrafficTravelTimeInSeconds is absent
                }
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = payload_no_free_flow

    with patch.object(collector.session, "get", return_value=mock_resp):
        rec = collector.fetch_route_travel_time(test_corridor)

    assert rec["estimated_duration_seconds"] == 1800.0
    assert rec["free_flow_duration_seconds"] is None
    assert rec["congestion_index"] is None


# -----------------------------------------------------------------------------
# 3. Database Persistence & Deduplication Tests
# -----------------------------------------------------------------------------

def test_database_duplicate_safe_traffic_save(db_manager):
    """
    Writing a route travel time record with the exact same (route_id, provider, observed_at)
    must update in-place without creating duplicate rows.
    """
    db_manager.seed_corridors()
    test_dt = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    rec = dict(SYNTHETIC_TRAFFIC_OBSERVATION_RECORD)
    rec["route_id"] = "gachibowli-central"
    rec["observed_at"] = test_dt
    rec["estimated_duration_seconds"] = 1800.0

    # First write
    id_1 = db_manager.save_route_travel_time(rec)
    assert id_1 is not None

    # Second write with updated duration
    rec["estimated_duration_seconds"] = 1950.0
    id_2 = db_manager.save_route_travel_time(rec)

    assert id_1 == id_2

    # Verify count is 1 and value is updated
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*), max(estimated_duration_seconds)
                FROM route_travel_times
                WHERE route_id = %s AND observed_at = %s;
                """,
                ("gachibowli-central", test_dt),
            )
            row = cur.fetchone()
            assert row["count"] == 1
            assert row["max"] == 1950.0

            # Cleanup test record
            cur.execute(
                "DELETE FROM route_travel_times WHERE route_id = %s AND observed_at = %s;",
                ("gachibowli-central", test_dt),
            )
        conn.commit()


# -----------------------------------------------------------------------------
# 4. Anomaly Detection & Baseline Cold-Start Tests
# -----------------------------------------------------------------------------

def test_detector_insufficient_history():
    """
    When historical observations are fewer than min_history_observations (e.g. 3 < 5),
    detector must return None to avoid false positives during cold start.
    """
    detector = TrafficDisruptionDetector()
    history = [
        {"estimated_duration_seconds": 1500.0},
        {"estimated_duration_seconds": 1520.0},
        {"estimated_duration_seconds": 1490.0},
    ]  # 3 observations < 5 threshold
    obs = {
        "route_id": "gachibowli-central",
        "observed_at": datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc),
        "estimated_duration_seconds": 3600.0,  # Extreme duration
        "free_flow_duration_seconds": 1400.0,
    }
    alert = detector.evaluate_observation(obs, history)
    assert alert is None, "Must not flag disruption when history is insufficient."


def test_detector_normal_travel_time():
    """A travel time close to the historical baseline median must produce no alert."""
    detector = TrafficDisruptionDetector()
    history = [{"estimated_duration_seconds": 1500.0 + (i * 10)} for i in range(10)]
    obs = {
        "route_id": "gachibowli-central",
        "observed_at": datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc),
        "estimated_duration_seconds": 1550.0,
        "free_flow_duration_seconds": 1450.0,
    }
    alert = detector.evaluate_observation(obs, history)
    assert alert is None


def test_detector_anomalous_slowdown_scoring():
    """A major corridor slowdown must be detected with explainable MAD score and severity."""
    detector = TrafficDisruptionDetector()
    # Baseline median ~1500s (25 minutes)
    history = [{"estimated_duration_seconds": 1500.0 + (i % 3) * 15} for i in range(10)]
    obs = {
        "route_id": "gachibowli-central",
        "observed_at": datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc),
        "estimated_duration_seconds": 3200.0,  # 53.3 minutes (+28.3m above baseline)
        "free_flow_duration_seconds": 1450.0,
    }
    alert = detector.evaluate_observation(obs, history)
    assert alert is not None
    assert alert["severity"] in ("SEVERE", "CRITICAL")
    assert alert["deviation_seconds"] > 1000.0
    assert alert["evidence"]["modified_z_score"] >= 2.0
    assert "explanation" in alert["evidence"]


def test_detector_zero_variance_history():
    """When all historical observations are identical (MAD=0), detector must handle safely without division by zero."""
    detector = TrafficDisruptionDetector()
    history = [{"estimated_duration_seconds": 1500.0} for _ in range(8)]
    obs = {
        "route_id": "gachibowli-central",
        "observed_at": datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc),
        "estimated_duration_seconds": 2400.0,  # +900s
        "free_flow_duration_seconds": 1400.0,
    }
    alert = detector.evaluate_observation(obs, history)
    assert alert is not None
    assert alert["evidence"]["mad"] == 0.0
    assert alert["evidence"]["modified_z_score"] > 0


# -----------------------------------------------------------------------------
# 5. Weather Correlation Tests (Requirement 11)
# -----------------------------------------------------------------------------

def test_detector_weather_correlation_with_physical_evidence():
    """
    When severe rain or wind is verified at an adjacent weather station,
    disruption must be marked weather_correlated=True with specific physical evidence.
    """
    detector = TrafficDisruptionDetector()
    history = [{"estimated_duration_seconds": 1500.0} for _ in range(8)]
    obs = {
        "route_id": "gachibowli-central",
        "observed_at": datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc),
        "estimated_duration_seconds": 2800.0,
        "free_flow_duration_seconds": 1400.0,
    }
    weather_ctx = {
        "location_id": "gachibowli",
        "location_name": "Gachibowli",
        "precipitation_mm": 18.5,  # Torrential downpour
        "wind_speed_kmh": 28.0,
        "wind_gusts_kmh": 48.0,
    }
    alert = detector.evaluate_observation(obs, history, weather_context=weather_ctx)
    assert alert is not None
    assert alert["weather_context"]["weather_correlated"] is True
    assert "precipitation 18.5 mm" in alert["weather_context"]["evidence"]


def test_detector_weather_correlation_without_weather_evidence():
    """
    Requirement 11: Do not label a slowdown as weather-caused without supporting evidence.
    Under clear/dry conditions, slowdown must be marked weather_correlated=False.
    """
    detector = TrafficDisruptionDetector()
    history = [{"estimated_duration_seconds": 1500.0} for _ in range(8)]
    obs = {
        "route_id": "gachibowli-central",
        "observed_at": datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc),
        "estimated_duration_seconds": 2800.0,
        "free_flow_duration_seconds": 1400.0,
    }
    weather_ctx = {
        "location_id": "gachibowli",
        "location_name": "Gachibowli",
        "precipitation_mm": 0.0,  # Completely dry
        "wind_speed_kmh": 11.0,
        "wind_gusts_kmh": 22.0,
    }
    alert = detector.evaluate_observation(obs, history, weather_context=weather_ctx)
    assert alert is not None
    assert alert["weather_context"]["weather_correlated"] is False
    assert "NOT weather-caused" in alert["weather_context"]["evidence"]
