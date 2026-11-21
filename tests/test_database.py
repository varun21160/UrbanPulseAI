"""
Unit & Integration Tests for Database Persistence (src/database.py)
Tests duplicate handling, historical timeline preservation, and health metrics querying.
"""

from datetime import datetime, timezone
import pytest
from src.config import get_config
from src.database import DatabaseManager
from tests.fixtures import SYNTHETIC_OBSERVATION_RECORD


@pytest.fixture
def db_manager():
    """Provides a DatabaseManager connected to the test database."""
    config = get_config()
    db = DatabaseManager(config.db)
    # Ensure database is accessible
    db.verify_database()
    return db


def test_duplicate_safe_observation_save(db_manager):
    """
    Inserting an observation with the exact same (location_id, source, observed_at)
    must update the existing record rather than creating a duplicate or raising an error.
    """
    test_dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    obs = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs["location_id"] = "hyderabad-central"
    obs["source"] = "open-meteo"
    obs["observed_at"] = test_dt
    obs["temperature_c"] = 28.0

    # First write
    obs_id_1 = db_manager.save_observation(obs)
    assert obs_id_1 is not None

    # Second write with same unique keys but updated temperature
    obs["temperature_c"] = 28.5
    obs_id_2 = db_manager.save_observation(obs)

    # Must return the same primary key (record updated in-place)
    assert obs_id_1 == obs_id_2

    # Verify updated temperature was saved without creating duplicates
    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*), max(temperature_c)
                FROM weather_observations
                WHERE location_id = %s AND source = %s AND observed_at = %s;
                """,
                ("hyderabad-central", "open-meteo", test_dt),
            )
            row = cur.fetchone()
            count, temp = row["count"], row["max"]
            assert count == 1
            assert temp == 28.5

            # Cleanup test record
            cur.execute(
                "DELETE FROM weather_observations WHERE location_id = %s AND observed_at = %s;",
                ("hyderabad-central", test_dt),
            )
        conn.commit()


def test_historical_timeline_preservation(db_manager):
    """
    Observations at different timestamps for the same location must create distinct rows,
    preserving the historical time-series timeline.
    """
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 10, 15, 0, tzinfo=timezone.utc)

    obs1 = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs1["location_id"] = "gachibowli"
    obs1["observed_at"] = t1
    obs1["temperature_c"] = 27.0

    obs2 = dict(SYNTHETIC_OBSERVATION_RECORD)
    obs2["location_id"] = "gachibowli"
    obs2["observed_at"] = t2
    obs2["temperature_c"] = 27.5

    id1 = db_manager.save_observation(obs1)
    id2 = db_manager.save_observation(obs2)

    assert id1 != id2

    with db_manager.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM weather_observations
                WHERE location_id = 'gachibowli' AND observed_at IN (%s, %s);
                """,
                (t1, t2),
            )
            count = cur.fetchone()["count"]
            assert count == 2

            # Cleanup
            cur.execute(
                "DELETE FROM weather_observations WHERE location_id = 'gachibowli' AND observed_at IN (%s, %s);",
                (t1, t2),
            )
        conn.commit()


def test_health_metrics_structure(db_manager):
    """Verify that get_health_metrics returns well-formed sections and data types."""
    metrics = db_manager.get_health_metrics()

    assert "latest_run" in metrics
    assert "locations_status" in metrics
    assert "historical_stats" in metrics
    assert "location_counts" in metrics

    assert isinstance(metrics["locations_status"], list)
    assert len(metrics["locations_status"]) >= 5

    stats = metrics["historical_stats"]
    assert stats["total_observations"] >= 0
    assert stats["total_runs"] >= 0


def test_location_history_series_ordering(db_manager):
    """
    Verify get_location_history_series retrieves observations in chronological order
    (ascending by observed_at), while respecting limits on the most recent entries.
    """
    series = db_manager.get_location_history_series(location_id="all", limit=10)
    assert isinstance(series, list)
    if len(series) >= 2:
        for i in range(len(series) - 1):
            assert series[i]["observed_at"] <= series[i + 1]["observed_at"]

