"""
Unit Tests for Data Quality & Validation (src/data_quality.py)
Uses synthetic fixtures to test boundary conditions, missing fields, and staleness.
"""

from datetime import datetime, timedelta, timezone
from src.config import DataQualityConfig
from src.data_quality import DataQualityChecker
from tests.fixtures import SYNTHETIC_OBSERVATION_RECORD


def test_valid_observation_passes():
    """A valid synthetic observation must pass quality checks with no errors or warnings."""
    checker = DataQualityChecker()
    obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs["observed_at"] = datetime.now(timezone.utc) - timedelta(minutes=5)

    report = checker.validate_observation(obs)
    assert report.is_valid is True
    assert report.status == "PASSED"
    assert not report.has_errors
    assert not report.has_warnings


def test_missing_critical_temperature_rejected():
    """Missing temperature_c is a critical error and must reject the observation."""
    checker = DataQualityChecker()
    obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs["temperature_c"] = None
    obs["observed_at"] = datetime.now(timezone.utc)

    report = checker.validate_observation(obs)
    assert report.is_valid is False
    assert report.status == "REJECTED"
    assert report.has_errors
    assert any("temperature_c" in msg for msg in report.error_messages())


def test_missing_humidity_warning():
    """Missing relative_humidity_pct is non-fatal and must produce a warning while remaining valid."""
    checker = DataQualityChecker()
    obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs["relative_humidity_pct"] = None
    obs["observed_at"] = datetime.now(timezone.utc)

    report = checker.validate_observation(obs)
    assert report.is_valid is True
    assert report.status == "WARNING"
    assert report.has_warnings
    assert not report.has_errors


def test_temperature_out_of_bounds_high():
    """Extreme high temperature exceeding physical bounds must be rejected."""
    checker = DataQualityChecker(DataQualityConfig(temp_max_c=60.0))
    obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs["temperature_c"] = 85.0
    obs["observed_at"] = datetime.now(timezone.utc)

    report = checker.validate_observation(obs)
    assert report.is_valid is False
    assert report.status == "REJECTED"
    assert report.has_errors


def test_temperature_out_of_bounds_low():
    """Extreme low temperature below physical bounds must be rejected."""
    checker = DataQualityChecker(DataQualityConfig(temp_min_c=-10.0))
    obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs["temperature_c"] = -25.0
    obs["observed_at"] = datetime.now(timezone.utc)

    report = checker.validate_observation(obs)
    assert report.is_valid is False
    assert report.status == "REJECTED"
    assert report.has_errors


def test_negative_humidity_rejected():
    """Negative humidity values must be rejected."""
    checker = DataQualityChecker()
    obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs["relative_humidity_pct"] = -5.0
    obs["observed_at"] = datetime.now(timezone.utc)

    report = checker.validate_observation(obs)
    assert report.is_valid is False
    assert report.status == "REJECTED"
    assert report.has_errors


def test_negative_precipitation_rejected():
    """Negative precipitation values must be rejected."""
    checker = DataQualityChecker()
    obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs["precipitation_mm"] = -1.5
    obs["observed_at"] = datetime.now(timezone.utc)

    report = checker.validate_observation(obs)
    assert report.is_valid is False
    assert report.status == "REJECTED"
    assert report.has_errors


def test_negative_wind_speed_rejected():
    """Negative wind speed values must be rejected."""
    checker = DataQualityChecker()
    obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs["wind_speed_kmh"] = -10.0
    obs["observed_at"] = datetime.now(timezone.utc)

    report = checker.validate_observation(obs)
    assert report.is_valid is False
    assert report.status == "REJECTED"
    assert report.has_errors


def test_stale_observation_warning():
    """Observation older than configured max staleness (180 min) must trigger a warning."""
    checker = DataQualityChecker(DataQualityConfig(max_staleness_minutes=180))
    obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    # Set observed_at to 240 minutes ago
    obs["observed_at"] = datetime.now(timezone.utc) - timedelta(minutes=240)

    report = checker.validate_observation(obs)
    assert report.is_valid is True
    assert report.status == "WARNING"
    assert any("stale" in msg.lower() for msg in report.warning_messages())


def test_future_timestamp_skew_warning():
    """Observation timestamp in the future (> 10 min) must trigger a warning."""
    checker = DataQualityChecker(DataQualityConfig(max_future_skew_seconds=600))
    obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    # Set observed_at to 30 minutes in the future
    obs["observed_at"] = datetime.now(timezone.utc) + timedelta(minutes=30)

    report = checker.validate_observation(obs)
    assert report.is_valid is True
    assert report.status == "WARNING"
    assert any("future" in msg.lower() for msg in report.warning_messages())
