"""
Unit Tests for Explainable Anomaly Detection Engine (src/detector.py)
Tests statistical baselines (MAD), zero-variance safety, data leakage prevention,
missing data handling, Isolation Forest integration, and duplicate alert constraints.
All test fixtures are synthetic and labeled accordingly.
"""

from datetime import datetime, timedelta, timezone
import pytest
from src.config import AnomalyDetectionConfig, get_config
from src.database import DatabaseManager
from src.detector import WeatherAnomalyDetector
from tests.fixtures import (
    SYNTHETIC_ANOMALY_RECORD,
    SYNTHETIC_OBSERVATION_RECORD,
    generate_synthetic_history,
)


@pytest.fixture
def detector():
    """Provides a WeatherAnomalyDetector initialized with test configuration."""
    cfg = AnomalyDetectionConfig(
        min_history_observations=5,
        mad_threshold_moderate=2.5,
        mad_threshold_severe=3.5,
        mad_threshold_critical=5.0,
        temp_deviation_floor_c=3.0,
        rain_threshold_mm=5.0,
        wind_deviation_floor_kmh=15.0,
        isolation_forest_min_samples=15,
    )
    return WeatherAnomalyDetector(config=cfg)


def test_insufficient_history_returns_no_anomalies(detector):
    """
    When prior observations are fewer than min_history_observations (e.g. 2 < 5),
    no anomalies should be generated. Prevents false positive alerts on cold start.
    """
    history = generate_synthetic_history(count=2)
    target_obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    target_obs["temperature_c"] = 45.0  # Even an extreme value must not trigger alert

    alerts = detector.evaluate_observation(target_obs, history)
    assert len(alerts) == 0, "Must not flag an observation as anomalous when history is insufficient."


def test_normal_observation_no_anomalies(detector):
    """A normal reading within the historical baseline range must produce zero alerts."""
    history = generate_synthetic_history(count=10, base_temp=28.5)
    target_obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    target_obs["temperature_c"] = 28.7
    target_obs["precipitation_mm"] = 0.0
    target_obs["wind_speed_kmh"] = 12.0
    target_obs["wind_gusts_kmh"] = 24.0

    alerts = detector.evaluate_observation(target_obs, history)
    assert len(alerts) == 0, f"Expected 0 alerts for normal reading, got: {alerts}"


def test_temperature_spike_detected(detector):
    """An extreme temperature spike must trigger a temperature_spike alert with explainable evidence."""
    history = generate_synthetic_history(count=10, base_temp=28.5, temp_noise=0.3)
    target_obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    target_obs["temperature_c"] = 42.5  # +14°C above baseline

    alerts = detector.evaluate_observation(target_obs, history)
    temp_alerts = [a for a in alerts if a.anomaly_type == "temperature_spike"]

    assert len(temp_alerts) == 1
    alert = temp_alerts[0]
    assert alert.severity in ("HIGH", "CRITICAL")
    assert alert.risk_score >= 0.5
    assert alert.model_name == "statistical_mad"
    assert "explanation" in alert.evidence
    assert alert.evidence["deviation"] > 10.0


def test_temperature_drop_detected(detector):
    """An abrupt unseasonal temperature plunge must trigger a temperature_drop alert."""
    history = generate_synthetic_history(count=10, base_temp=28.5, temp_noise=0.3)
    target_obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    target_obs["temperature_c"] = 14.0  # -14.5°C plunge

    alerts = detector.evaluate_observation(target_obs, history)
    drop_alerts = [a for a in alerts if a.anomaly_type == "temperature_drop"]

    assert len(drop_alerts) == 1
    alert = drop_alerts[0]
    assert alert.observed_value == 14.0
    assert alert.evidence["deviation"] < 0


def test_extreme_precipitation_detected(detector):
    """Heavy sudden rainfall against dry baseline must trigger an extreme_precipitation alert."""
    history = generate_synthetic_history(count=10, base_rain=0.0)
    target_obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    target_obs["precipitation_mm"] = 45.0  # Torrential downpour

    alerts = detector.evaluate_observation(target_obs, history)
    rain_alerts = [a for a in alerts if a.anomaly_type == "extreme_precipitation"]

    assert len(rain_alerts) == 1
    alert = rain_alerts[0]
    assert alert.observed_value == 45.0
    assert "precipitation" in alert.evidence["explanation"].lower()


def test_high_wind_detected(detector):
    """Gale force winds exceeding sustained baseline must trigger high_wind_sustained alert."""
    history = generate_synthetic_history(count=10, base_wind=10.0)
    target_obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    target_obs["wind_speed_kmh"] = 65.0

    alerts = detector.evaluate_observation(target_obs, history)
    wind_alerts = [a for a in alerts if a.anomaly_type == "high_wind_sustained"]

    assert len(wind_alerts) == 1
    alert = wind_alerts[0]
    assert alert.observed_value == 65.0


def test_zero_variance_handled_safely(detector):
    """
    When all historical values are identical (e.g. constant 28.0°C, MAD=0.0),
    the detector must not crash with ZeroDivisionError and must not falsely alarm on 28.0°C.
    """
    # 10 identical values
    history = generate_synthetic_history(count=10, base_temp=28.0, temp_noise=0.0)
    target_normal = dict(SYNTHETIC_OBSERVATION_RECORD)
    target_normal["temperature_c"] = 28.0

    alerts_normal = detector.evaluate_observation(target_normal, history)
    assert len(alerts_normal) == 0, "Normal reading matching zero-variance baseline must not alarm."

    # A genuine large deviation (36.0°C) should trigger safely via deviation floor
    target_extreme = dict(SYNTHETIC_OBSERVATION_RECORD)
    target_extreme["temperature_c"] = 36.0
    alerts_extreme = detector.evaluate_observation(target_extreme, history)
    assert len([a for a in alerts_extreme if a.anomaly_type == "temperature_spike"]) == 1


def test_missing_features_handled_safely(detector):
    """When an observation has missing (None) features, other available features are still scored."""
    history = generate_synthetic_history(count=10, base_temp=28.0, base_wind=10.0)
    target_obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    target_obs["temperature_c"] = None  # Missing temperature
    target_obs["wind_speed_kmh"] = 70.0  # Extreme wind present

    alerts = detector.evaluate_observation(target_obs, history)
    assert len([a for a in alerts if a.anomaly_type == "high_wind_sustained"]) == 1
    assert len([a for a in alerts if "temperature" in a.anomaly_type]) == 0


def test_prevention_of_future_data_leakage():
    """
    Verify that an observation scored at timestamp T is evaluated ONLY against past data (t < T).
    Future observations (t > T) containing extreme values must NOT leak into the baseline.
    """
    config = get_config()
    db = DatabaseManager(config.db)

    t_past = datetime(2026, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    t_target = datetime(2026, 2, 1, 11, 0, 0, tzinfo=timezone.utc)
    t_future = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Insert a synthetic historical baseline record
    obs_past = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs_past["location_id"] = "kukatpally"
    obs_past["observed_at"] = t_past
    obs_past["temperature_c"] = 28.0

    # Insert a synthetic future record with extreme temperature
    obs_future = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs_future["location_id"] = "kukatpally"
    obs_future["observed_at"] = t_future
    obs_future["temperature_c"] = 55.0  # Future heatwave

    db.save_observation(obs_past)
    db.save_observation(obs_future)

    try:
        # Query past records before t_target
        past_records = db.get_historical_observations_before(
            location_id="kukatpally", before_time=t_target
        )

        # Confirm future record (t_future) is strictly EXCLUDED
        for rec in past_records:
            assert rec["observed_at"] < t_target, "Data leakage detected: future record was returned!"
            assert rec["observed_at"] != t_future, "Future record leaked into historical baseline!"

    finally:
        # Cleanup test records
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM weather_observations WHERE location_id = 'kukatpally' AND observed_at IN (%s, %s);",
                    (t_past, t_future),
                )
            conn.commit()


def test_isolation_forest_integration(detector):
    """
    When history count >= isolation_forest_min_samples (e.g. 16 >= 15),
    Isolation Forest is evaluated and multivariate outlier results are integrated.
    """
    history = generate_synthetic_history(count=16, base_temp=28.0, base_wind=10.0, base_rain=0.0)
    target_obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    # Multivariate outlier combination (very high temp + extreme humidity + gale wind)
    target_obs["temperature_c"] = 43.0
    target_obs["relative_humidity_pct"] = 95.0
    target_obs["wind_speed_kmh"] = 65.0
    target_obs["precipitation_mm"] = 30.0

    alerts = detector.evaluate_observation(target_obs, history)
    assert len(alerts) > 0

    # Check evidence includes Isolation Forest assessment
    has_iforest_evidence = any("isolation_forest" in a.evidence for a in alerts)
    assert has_iforest_evidence, "Isolation Forest evidence should be attached when history >= 15."


def test_duplicate_anomaly_alerts_saved_safely():
    """
    Saving the same anomaly alert twice to PostgreSQL must update the record in-place
    via the deduplication constraint (location_id, observed_at, anomaly_type, model_name).
    """
    config = get_config()
    db = DatabaseManager(config.db)

    test_alert = dict(SYNTHETIC_ANOMALY_RECORD)
    test_alert["location_id"] = "secunderabad"
    test_alert["observed_at"] = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    test_alert["risk_score"] = 0.80

    try:
        # First write
        id1 = db.save_anomaly(test_alert)
        assert id1 is not None

        # Second write with same deduplication keys but updated risk_score
        test_alert["risk_score"] = 0.95
        id2 = db.save_anomaly(test_alert)

        # Must update in place (same ID)
        assert id1 == id2

        # Verify only 1 record exists in table
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*), max(risk_score)
                    FROM weather_anomalies
                    WHERE location_id = %s AND observed_at = %s AND anomaly_type = %s AND model_name = %s;
                    """,
                    (
                        test_alert["location_id"],
                        test_alert["observed_at"],
                        test_alert["anomaly_type"],
                        test_alert["model_name"],
                    ),
                )
                row = cur.fetchone()
                count, max_risk = row["count"], row["max"]
                assert count == 1
                assert max_risk == 0.95

    finally:
        # Cleanup
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM weather_anomalies WHERE location_id = 'secunderabad' AND observed_at = %s;",
                    (test_alert["observed_at"],),
                )
            conn.commit()
