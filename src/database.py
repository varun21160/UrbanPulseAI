"""
UrbanPulseAI - Database Management Module
Manages PostgreSQL connections, verification, and data persistence for
locations, weather_observations, and ingestion_runs tables.
"""

from contextlib import contextmanager
import logging
from typing import Any, Dict, Generator, List, Optional
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.config import CorridorInfo, DatabaseConfig, LocationInfo, get_config

logger = logging.getLogger("UrbanPulseAI.database")


class DatabaseManager:
    """Handles PostgreSQL operations using psycopg v3."""

    def __init__(self, db_config: Optional[DatabaseConfig] = None):
        self.config = db_config or get_config().db

    @contextmanager
    def get_connection(self) -> Generator[psycopg.Connection, None, None]:
        """Context manager yielding an active database connection with transaction handling."""
        conn = None
        try:
            conn = psycopg.connect(**self.config.connection_params, row_factory=dict_row)
            yield conn
        except psycopg.Error as e:
            logger.error("Database connection error: %s", e)
            if conn and not conn.closed:
                conn.rollback()
            raise
        finally:
            if conn and not conn.closed:
                conn.close()

    def verify_database(self) -> Dict[str, Any]:
        """
        Verify connection to the PostgreSQL database, confirm database name,
        and verify that the required tables exist.
        """
        required_tables = {
            "locations",
            "weather_observations",
            "ingestion_runs",
            "weather_anomalies",
        }
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT current_database() AS db_name, current_user AS db_user, version() AS version;"
                )
                db_info = cur.fetchone()
                if not db_info:
                    raise RuntimeError("Unable to query database information.")

                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = ANY(%s);
                    """,
                    (list(required_tables),),
                )
                existing_tables = {row["table_name"] for row in cur.fetchall()}
                missing = required_tables - existing_tables
                if missing:
                    raise RuntimeError(
                        f"Database verification failed: missing required tables: {missing}"
                    )

                logger.info(
                    "Verified database connection to '%s' as user '%s'. All required tables present: %s",
                    db_info["db_name"],
                    db_info["db_user"],
                    list(required_tables),
                )
                return {
                    "database": db_info["db_name"],
                    "user": db_info["db_user"],
                    "tables": list(existing_tables),
                    "version": db_info["version"],
                }

    def seed_locations(
        self, locations: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Insert or update monitored locations into the locations table using
        parameterized, duplicate-safe upsert.
        """
        if locations is None:
            locations = get_config().locations

        upsert_query = """
            INSERT INTO locations (location_id, name, latitude, longitude)
            VALUES (%(location_id)s, %(name)s, %(latitude)s, %(longitude)s)
            ON CONFLICT (location_id) DO UPDATE
            SET name = EXCLUDED.name,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude
            RETURNING location_id, name, latitude, longitude, created_at;
        """

        seeded: List[Dict[str, Any]] = []
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                for loc in locations:
                    if isinstance(loc, LocationInfo):
                        data = loc.to_dict()
                    elif isinstance(loc, dict):
                        data = loc
                    else:
                        continue

                    cur.execute(upsert_query, data)
                    row = cur.fetchone()
                    if row:
                        seeded.append(dict(row))
            conn.commit()

        logger.info("Successfully seeded/synced %d locations in database.", len(seeded))
        return seeded

    def get_locations(self) -> List[Dict[str, Any]]:
        """Fetch all registered monitoring locations from the database."""
        query = """
            SELECT location_id, name, latitude, longitude, created_at
            FROM locations
            ORDER BY name ASC;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return [dict(row) for row in cur.fetchall()]

    def start_ingestion_run(self, locations_requested: int) -> int:
        """
        Record the start of an ingestion run in the ingestion_runs table.
        Returns the generated run_id.
        """
        query = """
            INSERT INTO ingestion_runs (
                started_at,
                status,
                locations_requested,
                locations_succeeded,
                observations_saved
            ) VALUES (
                CURRENT_TIMESTAMP,
                'running',
                %(locations_requested)s,
                0,
                0
            ) RETURNING run_id;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, {"locations_requested": locations_requested})
                row = cur.fetchone()
                conn.commit()
                run_id = row["run_id"]
                logger.info(
                    "Started ingestion run #%d for %d locations.",
                    run_id,
                    locations_requested,
                )
                return run_id

    def complete_ingestion_run(
        self,
        run_id: int,
        status: str,
        locations_succeeded: int,
        observations_saved: int,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Update an ingestion run with final status, metrics, and error info.
        """
        query = """
            UPDATE ingestion_runs
            SET finished_at = CURRENT_TIMESTAMP,
                status = %(status)s,
                locations_succeeded = %(locations_succeeded)s,
                observations_saved = %(observations_saved)s,
                error_message = %(error_message)s
            WHERE run_id = %(run_id)s;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    {
                        "run_id": run_id,
                        "status": status,
                        "locations_succeeded": locations_succeeded,
                        "observations_saved": observations_saved,
                        "error_message": error_message,
                    },
                )
            conn.commit()
        logger.info(
            "Completed ingestion run #%d: status=%s, succeeded=%d, saved=%d",
            run_id,
            status,
            locations_succeeded,
            observations_saved,
        )

    def save_observation(self, observation: Dict[str, Any]) -> int:
        """
        Save a standardized weather observation into the weather_observations table.
        Duplicate-safe via ON CONFLICT (location_id, source, observed_at).
        Returns the observation_id.
        """
        query = """
            INSERT INTO weather_observations (
                location_id,
                source,
                observed_at,
                temperature_c,
                relative_humidity_pct,
                precipitation_mm,
                rain_mm,
                showers_mm,
                weather_code,
                wind_speed_kmh,
                wind_gusts_kmh,
                cloud_cover_pct,
                data_type,
                raw_payload
            ) VALUES (
                %(location_id)s,
                %(source)s,
                %(observed_at)s,
                %(temperature_c)s,
                %(relative_humidity_pct)s,
                %(precipitation_mm)s,
                %(rain_mm)s,
                %(showers_mm)s,
                %(weather_code)s,
                %(wind_speed_kmh)s,
                %(wind_gusts_kmh)s,
                %(cloud_cover_pct)s,
                %(data_type)s,
                %(raw_payload)s
            )
            ON CONFLICT (location_id, source, observed_at) DO UPDATE
            SET temperature_c = EXCLUDED.temperature_c,
                relative_humidity_pct = EXCLUDED.relative_humidity_pct,
                precipitation_mm = EXCLUDED.precipitation_mm,
                rain_mm = EXCLUDED.rain_mm,
                showers_mm = EXCLUDED.showers_mm,
                weather_code = EXCLUDED.weather_code,
                wind_speed_kmh = EXCLUDED.wind_speed_kmh,
                wind_gusts_kmh = EXCLUDED.wind_gusts_kmh,
                cloud_cover_pct = EXCLUDED.cloud_cover_pct,
                data_type = EXCLUDED.data_type,
                raw_payload = EXCLUDED.raw_payload,
                ingested_at = CURRENT_TIMESTAMP
            RETURNING observation_id;
        """

        record = observation.copy()
        # Wrap raw_payload in Jsonb adapter for PostgreSQL jsonb column
        raw_payload = record.get("raw_payload", {})
        if not isinstance(raw_payload, Jsonb):
            record["raw_payload"] = Jsonb(raw_payload)

        # Defaults for source and data_type
        record.setdefault("source", "open-meteo")
        record.setdefault("data_type", "live_api")

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, record)
                row = cur.fetchone()
                conn.commit()
                observation_id = row["observation_id"]
                return observation_id

    def get_latest_observations(self) -> List[Dict[str, Any]]:
        """
        Query the most recent weather observation recorded for each location.
        """
        query = """
            SELECT DISTINCT ON (l.location_id)
                l.location_id,
                l.name AS location_name,
                l.latitude,
                l.longitude,
                w.observation_id,
                w.source,
                w.observed_at,
                w.ingested_at,
                w.temperature_c,
                w.relative_humidity_pct,
                w.precipitation_mm,
                w.rain_mm,
                w.showers_mm,
                w.weather_code,
                w.wind_speed_kmh,
                w.wind_gusts_kmh,
                w.cloud_cover_pct,
                w.data_type
            FROM locations l
            LEFT JOIN weather_observations w ON l.location_id = w.location_id
            ORDER BY l.location_id, w.observed_at DESC NULLS LAST;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return [dict(row) for row in cur.fetchall()]

    def get_recent_ingestion_runs(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetch the most recent ingestion runs for audit and verification."""
        query = """
            SELECT run_id, started_at, finished_at, status,
                   locations_requested, locations_succeeded, observations_saved,
                   error_message,
                   EXTRACT(EPOCH FROM (COALESCE(finished_at, NOW()) - started_at)) AS duration_seconds
            FROM ingestion_runs
            ORDER BY run_id DESC
            LIMIT %s;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (limit,))
                return [dict(row) for row in cur.fetchall()]

    def get_health_metrics(self) -> Dict[str, Any]:
        """
        Aggregate comprehensive system health metrics:
        1. Latest ingestion run details & execution status
        2. Location-level observation freshness, age, and latest metrics
        3. Total historical records, time span, and pipeline reliability stats
        4. Count of historical observations per location
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Latest Ingestion Run
                cur.execute("""
                    SELECT run_id, started_at, finished_at, status,
                           locations_requested, locations_succeeded, observations_saved,
                           error_message,
                           EXTRACT(EPOCH FROM (COALESCE(finished_at, NOW()) - started_at)) AS duration_seconds
                    FROM ingestion_runs
                    ORDER BY run_id DESC
                    LIMIT 1;
                """)
                latest_run_row = cur.fetchone()
                latest_run = dict(latest_run_row) if latest_run_row else None

                # 2. Location Status & Last Observation
                cur.execute("""
                    SELECT DISTINCT ON (l.location_id)
                        l.location_id,
                        l.name AS location_name,
                        l.latitude,
                        l.longitude,
                        w.observation_id,
                        w.source,
                        w.observed_at,
                        w.ingested_at,
                        w.temperature_c,
                        w.relative_humidity_pct,
                        w.wind_speed_kmh,
                        w.weather_code,
                        w.data_type,
                        EXTRACT(EPOCH FROM (NOW() - w.observed_at)) / 60.0 AS age_minutes
                    FROM locations l
                    LEFT JOIN weather_observations w ON l.location_id = w.location_id
                    ORDER BY l.location_id, w.observed_at DESC NULLS LAST;
                """)
                locations_status = [dict(r) for r in cur.fetchall()]

                # 3. Overall Historical Summary
                cur.execute("""
                    SELECT
                        (SELECT count(*) FROM weather_observations) AS total_observations,
                        (SELECT count(*) FROM locations) AS total_locations,
                        (SELECT count(*) FROM ingestion_runs) AS total_runs,
                        (SELECT count(*) FROM ingestion_runs WHERE status = 'success') AS successful_runs,
                        (SELECT min(observed_at) FROM weather_observations) AS earliest_observation,
                        (SELECT max(observed_at) FROM weather_observations) AS latest_observation,
                        (SELECT count(*) FROM weather_anomalies) AS total_anomalies,
                        (SELECT count(*) FROM weather_anomalies WHERE status = 'active') AS active_anomalies;
                """)
                stats_row = cur.fetchone()
                historical_stats = dict(stats_row) if stats_row else {}

                # 4. Count of observations per location
                cur.execute("""
                    SELECT l.location_id, l.name, count(w.observation_id) AS observation_count
                    FROM locations l
                    LEFT JOIN weather_observations w ON l.location_id = w.location_id
                    GROUP BY l.location_id, l.name
                    ORDER BY l.name;
                """)
                location_counts = [dict(r) for r in cur.fetchall()]

                return {
                    "latest_run": latest_run,
                    "locations_status": locations_status,
                    "historical_stats": historical_stats,
                    "location_counts": location_counts,
                }

    def get_historical_observations_before(
        self,
        location_id: str,
        before_time: Any,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query prior historical observations strictly BEFORE before_time (chronological order).
        Guarantees NO DATA LEAKAGE: an observation is only evaluated against past data.
        """
        query = """
            SELECT observation_id, location_id, source, observed_at,
                   temperature_c, relative_humidity_pct, precipitation_mm, rain_mm,
                   showers_mm, weather_code, wind_speed_kmh, wind_gusts_kmh,
                   cloud_cover_pct, data_type
            FROM weather_observations
            WHERE location_id = %(location_id)s
              AND observed_at < %(before_time)s
            ORDER BY observed_at ASC
            LIMIT %(limit)s;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, {
                    "location_id": location_id,
                    "before_time": before_time,
                    "limit": limit,
                })
                return [dict(row) for row in cur.fetchall()]

    def get_observations_for_analysis(
        self,
        location_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent observations to evaluate for anomalies.
        """
        base_query = """
            SELECT observation_id, location_id, source, observed_at,
                   temperature_c, relative_humidity_pct, precipitation_mm, rain_mm,
                   showers_mm, weather_code, wind_speed_kmh, wind_gusts_kmh,
                   cloud_cover_pct, data_type
            FROM weather_observations
        """
        params: List[Any] = []
        if location_id:
            base_query += " WHERE location_id = %s"
            params.append(location_id)
        base_query += " ORDER BY observed_at DESC LIMIT %s;"
        params.append(limit)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(base_query, params)
                return [dict(row) for row in cur.fetchall()]

    def save_anomaly(self, anomaly: Dict[str, Any]) -> int:
        """
        Persist a detected anomaly alert into the weather_anomalies table.
        Duplicate-safe via UNIQUE (location_id, observed_at, anomaly_type, model_name).
        Returns the anomaly_id.
        """
        query = """
            INSERT INTO weather_anomalies (
                location_id,
                observed_at,
                detected_at,
                anomaly_type,
                severity,
                risk_score,
                model_name,
                model_version,
                observed_value,
                baseline_value,
                evidence,
                status
            ) VALUES (
                %(location_id)s,
                %(observed_at)s,
                COALESCE(%(detected_at)s, CURRENT_TIMESTAMP),
                %(anomaly_type)s,
                %(severity)s,
                %(risk_score)s,
                %(model_name)s,
                %(model_version)s,
                %(observed_value)s,
                %(baseline_value)s,
                %(evidence)s,
                COALESCE(%(status)s, 'active')
            )
            ON CONFLICT (location_id, observed_at, anomaly_type, model_name) DO UPDATE
            SET severity = EXCLUDED.severity,
                risk_score = EXCLUDED.risk_score,
                observed_value = EXCLUDED.observed_value,
                baseline_value = EXCLUDED.baseline_value,
                evidence = EXCLUDED.evidence,
                detected_at = CURRENT_TIMESTAMP
            RETURNING anomaly_id;
        """

        record = anomaly.copy()
        raw_evidence = record.get("evidence", {})
        if not isinstance(raw_evidence, Jsonb):
            record["evidence"] = Jsonb(raw_evidence)

        record.setdefault("detected_at", None)
        record.setdefault("model_version", "1.0.0")
        record.setdefault("status", "active")

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, record)
                row = cur.fetchone()
                conn.commit()
                return row["anomaly_id"]

    def get_recent_anomalies(
        self,
        limit: int = 20,
        location_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent anomaly detections with location details.
        """
        base_query = """
            SELECT a.anomaly_id, a.location_id, l.name AS location_name,
                   a.observed_at, a.detected_at, a.anomaly_type, a.severity,
                   a.risk_score, a.model_name, a.model_version, a.observed_value,
                   a.baseline_value, a.evidence, a.status
            FROM weather_anomalies a
            JOIN locations l ON a.location_id = l.location_id
        """
        params: List[Any] = []
        if location_id:
            base_query += " WHERE a.location_id = %s"
            params.append(location_id)
        base_query += " ORDER BY a.detected_at DESC, a.observed_at DESC LIMIT %s;"
        params.append(limit)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(base_query, params)
                return [dict(row) for row in cur.fetchall()]

    def get_all_locations(self) -> List[Dict[str, Any]]:
        """Retrieve all monitored locations with coordinates."""
        query = "SELECT location_id, name, latitude, longitude, created_at FROM locations ORDER BY name ASC;"
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return [dict(row) for row in cur.fetchall()]

    def get_location_history_series(
        self,
        location_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve chronological historical weather time-series observations
        for dashboard visualization and analytical trends.
        Queries the most recent observations up to limit, ordered chronologically.
        """
        where_clause = ""
        params: List[Any] = []
        if location_id and location_id != "all":
            where_clause = " WHERE w.location_id = %s"
            params.append(location_id)

        query = f"""
            SELECT * FROM (
                SELECT w.observation_id, w.location_id, l.name AS location_name,
                       l.latitude, l.longitude, w.source, w.observed_at, w.ingested_at,
                       w.temperature_c, w.relative_humidity_pct, w.precipitation_mm,
                       w.rain_mm, w.showers_mm, w.weather_code, w.wind_speed_kmh,
                       w.wind_gusts_kmh, w.cloud_cover_pct, w.data_type
                FROM weather_observations w
                JOIN locations l ON w.location_id = l.location_id
                {where_clause}
                ORDER BY w.observed_at DESC
                LIMIT %s
            ) sub
            ORDER BY observed_at ASC;
        """
        params.append(limit)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    def init_traffic_tables(self) -> None:
        """Ensure traffic corridors, route travel times, and disruptions tables exist."""
        ddl = """
            CREATE TABLE IF NOT EXISTS traffic_corridors (
                corridor_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                origin_location_id TEXT REFERENCES locations(location_id),
                destination_location_id TEXT REFERENCES locations(location_id),
                origin_latitude DOUBLE PRECISION NOT NULL,
                origin_longitude DOUBLE PRECISION NOT NULL,
                destination_latitude DOUBLE PRECISION NOT NULL,
                destination_longitude DOUBLE PRECISION NOT NULL,
                via_road TEXT,
                distance_km DOUBLE PRECISION,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS route_travel_times (
                travel_time_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                route_id TEXT NOT NULL REFERENCES traffic_corridors(corridor_id),
                provider TEXT NOT NULL DEFAULT 'tomtom',
                observed_at TIMESTAMPTZ NOT NULL,
                ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                estimated_duration_seconds DOUBLE PRECISION NOT NULL,
                free_flow_duration_seconds DOUBLE PRECISION,
                delay_seconds DOUBLE PRECISION,
                distance_meters DOUBLE PRECISION,
                congestion_index DOUBLE PRECISION,
                data_type TEXT NOT NULL DEFAULT 'live_api',
                raw_payload JSONB NOT NULL,
                CONSTRAINT uq_route_travel_times_route_provider_obs UNIQUE (route_id, provider, observed_at)
            );

            CREATE INDEX IF NOT EXISTS idx_route_travel_times_time ON route_travel_times (observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_route_travel_times_route_time ON route_travel_times (route_id, observed_at DESC);

            CREATE TABLE IF NOT EXISTS traffic_disruptions (
                disruption_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                route_id TEXT NOT NULL REFERENCES traffic_corridors(corridor_id),
                observed_at TIMESTAMPTZ NOT NULL,
                detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                severity TEXT NOT NULL,
                observed_duration_seconds DOUBLE PRECISION NOT NULL,
                baseline_duration_seconds DOUBLE PRECISION NOT NULL,
                deviation_seconds DOUBLE PRECISION NOT NULL,
                congestion_index DOUBLE PRECISION,
                model_name TEXT NOT NULL DEFAULT 'statistical_mad',
                model_version TEXT NOT NULL DEFAULT '1.0.0',
                evidence JSONB NOT NULL,
                weather_context JSONB,
                status TEXT NOT NULL DEFAULT 'active',
                CONSTRAINT uq_traffic_disruptions_route_obs_model UNIQUE (route_id, observed_at, model_name)
            );

            CREATE INDEX IF NOT EXISTS idx_traffic_disruptions_route ON traffic_disruptions (route_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_traffic_disruptions_detected ON traffic_disruptions (detected_at DESC);
            CREATE INDEX IF NOT EXISTS idx_traffic_disruptions_severity ON traffic_disruptions (severity);
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()

    def seed_corridors(
        self, corridors: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Insert or update monitored traffic corridors into traffic_corridors table.
        Duplicate-safe via ON CONFLICT (corridor_id).
        """
        if corridors is None:
            corridors = get_config().corridors

        upsert_query = """
            INSERT INTO traffic_corridors (
                corridor_id, name, origin_location_id, destination_location_id,
                origin_latitude, origin_longitude, destination_latitude, destination_longitude,
                via_road, distance_km
            ) VALUES (
                %(corridor_id)s, %(name)s, %(origin_location_id)s, %(destination_location_id)s,
                %(origin_latitude)s, %(origin_longitude)s, %(destination_latitude)s, %(destination_longitude)s,
                %(via_road)s, %(distance_km)s
            )
            ON CONFLICT (corridor_id) DO UPDATE
            SET name = EXCLUDED.name,
                origin_latitude = EXCLUDED.origin_latitude,
                origin_longitude = EXCLUDED.origin_longitude,
                destination_latitude = EXCLUDED.destination_latitude,
                destination_longitude = EXCLUDED.destination_longitude,
                via_road = EXCLUDED.via_road,
                distance_km = EXCLUDED.distance_km
            RETURNING corridor_id, name, distance_km;
        """

        seeded: List[Dict[str, Any]] = []
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                for c in corridors:
                    if isinstance(c, CorridorInfo):
                        data = c.to_dict()
                    elif isinstance(c, dict):
                        data = c
                    else:
                        continue
                    cur.execute(upsert_query, data)
                    row = cur.fetchone()
                    if row:
                        seeded.append(dict(row))
            conn.commit()
        logger.info("Successfully seeded %d traffic corridors in database.", len(seeded))
        return seeded

    def get_all_corridors(self) -> List[Dict[str, Any]]:
        """Fetch all registered road corridors with endpoints and metadata."""
        query = """
            SELECT corridor_id, name, origin_location_id, destination_location_id,
                   origin_latitude, origin_longitude, destination_latitude, destination_longitude,
                   via_road, distance_km, created_at
            FROM traffic_corridors
            ORDER BY name ASC;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return [dict(row) for row in cur.fetchall()]

    def save_route_travel_time(self, record: Dict[str, Any]) -> int:
        """
        Persist a route travel time observation into route_travel_times.
        Duplicate-safe via UNIQUE (route_id, provider, observed_at).
        Returns travel_time_id.
        """
        query = """
            INSERT INTO route_travel_times (
                route_id, provider, observed_at, estimated_duration_seconds,
                free_flow_duration_seconds, delay_seconds, distance_meters,
                congestion_index, data_type, raw_payload
            ) VALUES (
                %(route_id)s, %(provider)s, %(observed_at)s, %(estimated_duration_seconds)s,
                %(free_flow_duration_seconds)s, %(delay_seconds)s, %(distance_meters)s,
                %(congestion_index)s, %(data_type)s, %(raw_payload)s
            )
            ON CONFLICT (route_id, provider, observed_at) DO UPDATE
            SET estimated_duration_seconds = EXCLUDED.estimated_duration_seconds,
                free_flow_duration_seconds = EXCLUDED.free_flow_duration_seconds,
                delay_seconds = EXCLUDED.delay_seconds,
                distance_meters = EXCLUDED.distance_meters,
                congestion_index = EXCLUDED.congestion_index,
                data_type = EXCLUDED.data_type,
                raw_payload = EXCLUDED.raw_payload,
                ingested_at = CURRENT_TIMESTAMP
            RETURNING travel_time_id;
        """
        rec = record.copy()
        raw = rec.get("raw_payload", {})
        if not isinstance(raw, Jsonb):
            rec["raw_payload"] = Jsonb(raw)
        rec.setdefault("provider", "tomtom")
        rec.setdefault("data_type", "live_api")

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, rec)
                row = cur.fetchone()
                conn.commit()
                return row["travel_time_id"]

    def get_latest_corridor_travel_times(self) -> List[Dict[str, Any]]:
        """Query the most recent travel time record for each corridor."""
        query = """
            SELECT DISTINCT ON (c.corridor_id)
                c.corridor_id,
                c.name AS corridor_name,
                c.origin_location_id,
                c.destination_location_id,
                c.via_road,
                c.distance_km,
                r.travel_time_id,
                r.provider,
                r.observed_at,
                r.ingested_at,
                r.estimated_duration_seconds,
                r.free_flow_duration_seconds,
                r.delay_seconds,
                r.distance_meters,
                r.congestion_index,
                r.data_type
            FROM traffic_corridors c
            LEFT JOIN route_travel_times r ON c.corridor_id = r.route_id
            ORDER BY c.corridor_id, r.observed_at DESC NULLS LAST;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return [dict(row) for row in cur.fetchall()]

    def get_corridor_travel_time_history(
        self,
        route_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve chronological historical travel-time observations for a corridor.
        Queries the most recent observations up to limit, returned chronologically.
        """
        where_clause = ""
        params: List[Any] = []
        if route_id and route_id != "all":
            where_clause = " WHERE r.route_id = %s"
            params.append(route_id)

        query = f"""
            SELECT * FROM (
                SELECT r.travel_time_id, r.route_id, c.name AS corridor_name,
                       c.via_road, c.distance_km, r.provider, r.observed_at, r.ingested_at,
                       r.estimated_duration_seconds, r.free_flow_duration_seconds,
                       r.delay_seconds, r.distance_meters, r.congestion_index, r.data_type
                FROM route_travel_times r
                JOIN traffic_corridors c ON r.route_id = c.corridor_id
                {where_clause}
                ORDER BY r.observed_at DESC
                LIMIT %s
            ) sub
            ORDER BY observed_at ASC;
        """
        params.append(limit)
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    def get_prior_route_travel_times(
        self,
        route_id: str,
        before_time: Any,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve observations strictly prior to before_time for cold-start & baseline computation.
        Guarantees NO DATA LEAKAGE.
        """
        query = """
            SELECT travel_time_id, route_id, provider, observed_at,
                   estimated_duration_seconds, free_flow_duration_seconds,
                   delay_seconds, congestion_index, data_type
            FROM route_travel_times
            WHERE route_id = %(route_id)s
              AND observed_at < %(before_time)s
            ORDER BY observed_at ASC
            LIMIT %(limit)s;
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, {
                    "route_id": route_id,
                    "before_time": before_time,
                    "limit": limit,
                })
                return [dict(row) for row in cur.fetchall()]

    def save_traffic_disruption(self, disruption: Dict[str, Any]) -> int:
        """
        Persist a detected traffic disruption into traffic_disruptions table.
        Duplicate-safe via UNIQUE (route_id, observed_at, model_name).
        Returns disruption_id.
        """
        query = """
            INSERT INTO traffic_disruptions (
                route_id, observed_at, severity, observed_duration_seconds,
                baseline_duration_seconds, deviation_seconds, congestion_index,
                model_name, model_version, evidence, weather_context, status
            ) VALUES (
                %(route_id)s, %(observed_at)s, %(severity)s, %(observed_duration_seconds)s,
                %(baseline_duration_seconds)s, %(deviation_seconds)s, %(congestion_index)s,
                %(model_name)s, %(model_version)s, %(evidence)s, %(weather_context)s, %(status)s
            )
            ON CONFLICT (route_id, observed_at, model_name) DO UPDATE
            SET severity = EXCLUDED.severity,
                observed_duration_seconds = EXCLUDED.observed_duration_seconds,
                baseline_duration_seconds = EXCLUDED.baseline_duration_seconds,
                deviation_seconds = EXCLUDED.deviation_seconds,
                congestion_index = EXCLUDED.congestion_index,
                evidence = EXCLUDED.evidence,
                weather_context = EXCLUDED.weather_context,
                status = EXCLUDED.status,
                detected_at = CURRENT_TIMESTAMP
            RETURNING disruption_id;
        """
        rec = disruption.copy()
        evidence = rec.get("evidence", {})
        if not isinstance(evidence, Jsonb):
            rec["evidence"] = Jsonb(evidence)
        weather_ctx = rec.get("weather_context", {})
        if not isinstance(weather_ctx, Jsonb):
            rec["weather_context"] = Jsonb(weather_ctx)
        rec.setdefault("model_name", "statistical_mad")
        rec.setdefault("model_version", "1.0.0")
        rec.setdefault("status", "active")

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, rec)
                row = cur.fetchone()
                conn.commit()
                return row["disruption_id"]

    def get_recent_traffic_disruptions(
        self,
        limit: int = 50,
        route_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent traffic disruption alerts."""
        where_clause = ""
        params: List[Any] = []
        if route_id and route_id != "all":
            where_clause = " WHERE d.route_id = %s"
            params.append(route_id)

        query = f"""
            SELECT d.disruption_id, d.route_id, c.name AS corridor_name,
                   c.via_road, d.observed_at, d.detected_at, d.severity,
                   d.observed_duration_seconds, d.baseline_duration_seconds,
                   d.deviation_seconds, d.congestion_index, d.model_name,
                   d.model_version, d.evidence, d.weather_context, d.status
            FROM traffic_disruptions d
            JOIN traffic_corridors c ON d.route_id = c.corridor_id
            {where_clause}
            ORDER BY d.detected_at DESC, d.observed_at DESC
            LIMIT %s;
        """
        params.append(limit)
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]



