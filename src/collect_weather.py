"""
UrbanPulseAI - Weather Data Collection Pipeline (Day 2)
Fetches real weather observations from Open-Meteo API for Hyderabad locations,
performs automated data-quality checks, and persists historical time-series
into PostgreSQL (locations, weather_observations, ingestion_runs).
Includes rate-limiting, scheduler, and health-reporting capabilities.
"""

import argparse
from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
import urllib3
from urllib3.util import Retry

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output in Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.config import AppConfig, LocationInfo, get_config
from src.database import DatabaseManager
from src.data_quality import DataQualityChecker, QualityReport

# Standard WMO Weather interpretation codes
WMO_CODE_MAP = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}
# Alias for backwards/cross-module compatibility
WEATHER_CODE_DESCRIPTIONS = WMO_CODE_MAP


def get_weather_description(code: Optional[int]) -> str:
    """Return human-readable description for WMO weather code."""
    if code is None:
        return "Unknown"
    return WMO_CODE_MAP.get(code, f"Code {code}")


def setup_logger(config: AppConfig) -> logging.Logger:
    """Configure dual-destination logging: console stdout and rotating log file."""
    logger = logging.getLogger("UrbanPulseAI")
    logger.setLevel(getattr(logging, config.logging.level, logging.INFO))

    if logger.handlers:
        return logger

    # Ensure log directory exists
    config.logging.file_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler (5 MB per file, max 3 backups)
    file_handler = RotatingFileHandler(
        config.logging.file_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


class WeatherCollector:
    """Fetches and standardizes live weather observations from the Open-Meteo API."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = logging.getLogger("UrbanPulseAI.collector")
        self.session = requests.Session()

        # Resilient HTTP retries on transient errors (429, 500, 502, 503, 504)
        retries = Retry(
            total=config.scheduler.max_retries,
            backoff_factor=config.scheduler.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update(
            {"User-Agent": "UrbanPulseAI-DataPipeline/1.0.0"}
        )

    def fetch_weather(
        self, location_id: str, latitude: float, longitude: float
    ) -> Dict[str, Any]:
        """
        Call Open-Meteo forecast API for current weather variables.
        Normalizes timestamp to UTC and formats for database insertion.
        Includes rate-limit (HTTP 429) backoff handling.
        """
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(self.config.weather.current_variables),
            "timezone": "UTC",
        }

        self.logger.debug(
            "Requesting Open-Meteo API for '%s' (lat=%.4f, lon=%.4f)",
            location_id,
            latitude,
            longitude,
        )

        try:
            response = self.session.get(
                self.config.weather.api_url,
                params=params,
                timeout=self.config.weather.timeout_seconds,
            )
        except requests.exceptions.Timeout as e:
            self.logger.error("Request timeout for location [%s]: %s", location_id, e)
            raise
        except requests.exceptions.RequestException as e:
            self.logger.error("Network request failed for location [%s]: %s", location_id, e)
            raise

        # Check for rate-limiting response (HTTP 429)
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            wait_time = float(retry_after) if retry_after and retry_after.isdigit() else 5.0
            self.logger.warning(
                "Rate limit (429) encountered for [%s]. Backing off for %.1f seconds...",
                location_id,
                wait_time,
            )
            time.sleep(wait_time)
            # Retry request once after backoff
            response = self.session.get(
                self.config.weather.api_url,
                params=params,
                timeout=self.config.weather.timeout_seconds,
            )

        response.raise_for_status()
        payload = response.json()

        curr = payload.get("current", {})
        if not curr:
            raise ValueError(f"No current weather data returned for location {location_id}")

        # Parse and normalize observed_at to UTC
        time_str = curr.get("time")
        if time_str:
            dt = datetime.fromisoformat(time_str)
            if dt.tzinfo is None:
                observed_at = dt.replace(tzinfo=timezone.utc)
            else:
                observed_at = dt.astimezone(timezone.utc)
        else:
            observed_at = datetime.now(timezone.utc)

        weather_code = curr.get("weather_code")

        return {
            "location_id": location_id,
            "source": "open-meteo",
            "observed_at": observed_at,
            "temperature_c": curr.get("temperature_2m"),
            "relative_humidity_pct": curr.get("relative_humidity_2m"),
            "precipitation_mm": curr.get("precipitation"),
            "rain_mm": curr.get("rain"),
            "showers_mm": curr.get("showers"),
            "weather_code": weather_code,
            "weather_description": get_weather_description(weather_code),
            "wind_speed_kmh": curr.get("wind_speed_10m"),
            "wind_gusts_kmh": curr.get("wind_gusts_10m"),
            "cloud_cover_pct": curr.get("cloud_cover"),
            "data_type": "live_api",
            "raw_payload": payload,
        }


def run_pipeline(
    dry_run: bool = False,
    target_location: Optional[str] = None,
) -> bool:
    """
    Execute weather data ingestion across monitored locations.
    Applies data quality checks, enforces rate-limiting delays between calls,
    preserves historical time-series observations, and logs run execution metrics.
    """
    start_time = datetime.now(timezone.utc)
    config = get_config()
    logger = setup_logger(config)
    collector = WeatherCollector(config)
    dq_checker = DataQualityChecker(config.data_quality)
    db = DatabaseManager(config.db)

    logger.info("=" * 75)
    logger.info("UrbanPulseAI Weather Ingestion Pipeline Started")
    logger.info(
        "Started At: %s UTC | Mode: %s | Provider: %s",
        start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "DRY-RUN (No DB write)" if dry_run else "DATABASE",
        config.weather.provider,
    )
    logger.info("=" * 75)

    # 1. Verify database connectivity & schema if not in dry-run
    locations_to_process: List[Dict[str, Any]] = []

    if not dry_run:
        try:
            db_info = db.verify_database()
            logger.info("Connected to PostgreSQL database: %s", db_info["database"])
        except Exception as e:
            logger.error("Database verification failed: %s", e)
            logger.error("Aborting ingestion run. Please check your database settings.")
            return False

        # Ensure locations are seeded in the database
        try:
            db.seed_locations()
            db_locations = db.get_locations()
            locations_to_process = db_locations
        except Exception as e:
            logger.error("Failed to seed/fetch locations from database: %s", e)
            return False
    else:
        # Dry-run fallback using in-memory configured locations
        locations_to_process = [loc.to_dict() for loc in config.locations]

    # 2. Filter for a specific location if requested
    if target_location:
        query_str = target_location.strip().lower()
        matched = [
            loc
            for loc in locations_to_process
            if loc["location_id"].lower() == query_str
            or loc["name"].lower() == query_str
            or query_str in loc["name"].lower()
        ]
        if not matched:
            logger.error("Target location '%s' not found among monitored locations.", target_location)
            logger.info("Available locations: %s", [loc["name"] for loc in locations_to_process])
            return False
        locations_to_process = matched

    # 3. Initialize ingestion run record in DB
    run_id: Optional[int] = None
    if not dry_run:
        try:
            run_id = db.start_ingestion_run(len(locations_to_process))
        except Exception as e:
            logger.error("Failed to initialize ingestion run record: %s", e)
            return False

    # 4. Ingestion loop with rate-limiting & data quality checks
    success_count = 0
    saved_count = 0
    failure_count = 0
    summary_rows: List[Dict[str, Any]] = []
    error_details: List[str] = []

    num_locations = len(locations_to_process)
    for idx, loc in enumerate(locations_to_process):
        loc_id = loc["location_id"]
        loc_name = loc["name"]
        lat = float(loc["latitude"])
        lon = float(loc["longitude"])

        logger.info(
            "--> [%d/%d] Collecting weather for [%s] (%s | lat=%.4f, lon=%.4f)...",
            idx + 1,
            num_locations,
            loc_name,
            loc_id,
            lat,
            lon,
        )

        try:
            # Fetch live weather reading
            observation = collector.fetch_weather(loc_id, lat, lon)

            # Perform automated Data Quality Validation
            dq_report = dq_checker.validate_observation(observation)

            if not dq_report.is_valid:
                # Fatal data quality violation: REJECT and do not save!
                failure_count += 1
                rejection_reasons = dq_report.error_messages()
                err_msg = f"{loc_name} ({loc_id}) REJECTED by DQ: {'; '.join(rejection_reasons)}"
                error_details.append(err_msg)
                logger.error("Data Quality Check REJECTED for [%s]: %s", loc_name, "; ".join(rejection_reasons))

                summary_rows.append({
                    "location_id": loc_id,
                    "name": loc_name,
                    "lat_lon": f"{lat:.4f}, {lon:.4f}",
                    "observed_at": observation["observed_at"].strftime("%Y-%m-%d %H:%M UTC"),
                    "temp_c": observation.get("temperature_c", "N/A"),
                    "humidity": observation.get("relative_humidity_pct", "N/A"),
                    "precip_mm": observation.get("precipitation_mm", "N/A"),
                    "rain_mm": observation.get("rain_mm", "N/A"),
                    "showers_mm": observation.get("showers_mm", "N/A"),
                    "wind_kmh": observation.get("wind_speed_kmh", "N/A"),
                    "gusts_kmh": observation.get("wind_gusts_kmh", "N/A"),
                    "cloud_pct": observation.get("cloud_cover_pct", "N/A"),
                    "weather": observation.get("weather_description", "REJECTED"),
                    "dq_status": "REJECTED",
                    "status": "REJECTED (DQ Violations)",
                })
            else:
                # Valid observation (passed or warning)
                success_count += 1
                status_label = "DRY-RUN"
                obs_id = None

                if dq_report.has_warnings:
                    for warn in dq_report.warning_messages():
                        logger.warning("Data Quality Warning [%s]: %s", loc_name, warn)

                if not dry_run:
                    obs_id = db.save_observation(observation)
                    saved_count += 1
                    status_label = f"SAVED (ID #{obs_id})"
                    if dq_report.has_warnings:
                        status_label += " [DQ: WARN]"

                logger.info(
                    "[%s] %s | Temp: %.1f°C | Humidity: %s%% | Rain: %s mm | Wind: %s km/h (Gusts: %s km/h) | Cloud: %s%% | DQ: %s | Status: %s",
                    loc_name,
                    observation["weather_description"],
                    observation["temperature_c"],
                    observation["relative_humidity_pct"],
                    observation["rain_mm"],
                    observation["wind_speed_kmh"],
                    observation["wind_gusts_kmh"],
                    observation["cloud_cover_pct"],
                    dq_report.status,
                    status_label,
                )

                summary_rows.append({
                    "location_id": loc_id,
                    "name": loc_name,
                    "lat_lon": f"{lat:.4f}, {lon:.4f}",
                    "observed_at": observation["observed_at"].strftime("%Y-%m-%d %H:%M UTC"),
                    "temp_c": observation["temperature_c"],
                    "humidity": observation["relative_humidity_pct"],
                    "precip_mm": observation["precipitation_mm"],
                    "rain_mm": observation["rain_mm"],
                    "showers_mm": observation["showers_mm"],
                    "wind_kmh": observation["wind_speed_kmh"],
                    "gusts_kmh": observation["wind_gusts_kmh"],
                    "cloud_pct": observation["cloud_cover_pct"],
                    "weather": observation["weather_description"],
                    "dq_status": dq_report.status,
                    "status": status_label,
                })

        except Exception as e:
            failure_count += 1
            err_msg = f"{loc_name} ({loc_id}): {e}"
            error_details.append(err_msg)
            logger.error("Failed to collect weather for [%s]: %s", loc_name, e)
            summary_rows.append({
                "location_id": loc_id,
                "name": loc_name,
                "lat_lon": f"{lat:.4f}, {lon:.4f}",
                "observed_at": "N/A",
                "temp_c": "N/A",
                "humidity": "N/A",
                "precip_mm": "N/A",
                "rain_mm": "N/A",
                "showers_mm": "N/A",
                "wind_kmh": "N/A",
                "gusts_kmh": "N/A",
                "cloud_pct": "N/A",
                "weather": "ERROR",
                "dq_status": "FAILED",
                "status": f"FAILED ({e})",
            })

        # Rate-limiting pause between consecutive location calls
        if idx < num_locations - 1 and config.scheduler.rate_limit_delay_seconds > 0:
            time.sleep(config.scheduler.rate_limit_delay_seconds)

    finish_time = datetime.now(timezone.utc)
    duration_sec = (finish_time - start_time).total_seconds()

    # 5. Complete ingestion run record in DB
    if not dry_run and run_id is not None:
        if failure_count == 0:
            final_status = "success"
        elif success_count > 0:
            final_status = "partial"
        else:
            final_status = "failed"

        err_summary = "; ".join(error_details) if error_details else None
        try:
            db.complete_ingestion_run(
                run_id=run_id,
                status=final_status,
                locations_succeeded=success_count,
                observations_saved=saved_count,
                error_message=err_summary,
            )
        except Exception as e:
            logger.error("Failed to update final ingestion run status: %s", e)

    # 6. Log detailed run summary
    logger.info("=" * 75)
    logger.info(
        "Ingestion Run Finished at: %s UTC (Elapsed: %.2fs)",
        finish_time.strftime("%Y-%m-%d %H:%M:%S"),
        duration_sec,
    )
    logger.info(
        "Run Status: %s | Locations Requested: %d | Succeeded: %d | Saved: %d | Failed: %d",
        "SUCCESS" if failure_count == 0 else ("PARTIAL" if success_count > 0 else "FAILED"),
        num_locations,
        success_count,
        saved_count,
        failure_count,
    )
    if error_details:
        logger.warning("Errors encountered during run: %s", "; ".join(error_details))
    logger.info("=" * 75)

    # 7. Print formatted console summary table
    print("\n" + "=" * 95)
    print("                    URBANPULSE AI - WEATHER INGESTION SUMMARY")
    print("=" * 95)
    header = f"{'Location':<20} {'Coordinates':<18} {'Observed (UTC)':<18} {'Temp':<8} {'Humidity':<10} {'DQ':<9} {'Status'}"
    print(header)
    print("-" * 95)
    for row in summary_rows:
        temp_str = f"{row['temp_c']}°C" if isinstance(row['temp_c'], (int, float)) else "N/A"
        hum_str = f"{row['humidity']}%" if isinstance(row['humidity'], (int, float)) else "N/A"
        print(
            f"{row['name']:<20} {row['lat_lon']:<18} {row['observed_at']:<18} {temp_str:<8} {hum_str:<10} {row['dq_status']:<9} {row['status']}"
        )
    print("=" * 95)
    print(
        f"Execution Summary: {success_count} succeeded, {saved_count} saved to DB, {failure_count} failed. Elapsed: {duration_sec:.2f}s."
    )
    print("=" * 95 + "\n")

    return success_count > 0 and failure_count == 0


def print_health_report(db: DatabaseManager) -> None:
    """Display comprehensive system health report across pipeline and database."""
    try:
        metrics = db.get_health_metrics()
    except Exception as e:
        print(f"\n[FAIL] Unable to query health metrics from database: {e}\n")
        return

    latest_run = metrics.get("latest_run")
    locations_status = metrics.get("locations_status", [])
    stats = metrics.get("historical_stats", {})
    location_counts = metrics.get("location_counts", [])

    print("\n" + "=" * 85)
    print("                      URBANPULSE AI - SYSTEM HEALTH REPORT")
    print("=" * 85)

    # 1. Latest Ingestion Run
    print("\n[1] LATEST INGESTION RUN")
    print("-" * 85)
    if not latest_run:
        print("  No ingestion runs recorded in database.")
    else:
        started_utc = (
            latest_run["started_at"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if latest_run.get("started_at")
            else "N/A"
        )
        finished_utc = (
            latest_run["finished_at"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if latest_run.get("finished_at")
            else "Running / Incomplete"
        )
        duration_s = f"{float(latest_run['duration_seconds']):.2f}s" if latest_run.get("duration_seconds") is not None else "N/A"
        status_flag = latest_run["status"].upper()

        print(f"  Run ID              : #{latest_run['run_id']}")
        print(f"  Status              : {status_flag}")
        print(f"  Started             : {started_utc}")
        print(f"  Finished            : {finished_utc} (Duration: {duration_s})")
        print(
            f"  Locations Requested : {latest_run['locations_requested']} | "
            f"Succeeded: {latest_run['locations_succeeded']} | "
            f"Saved: {latest_run['observations_saved']}"
        )
        if latest_run.get("error_message"):
            print(f"  Errors Logged       : {latest_run['error_message']}")
        else:
            print("  Errors Logged       : None (Clean Run)")

    # 2. Location-by-Location Health
    print("\n[2] LOCATION OBSERVATION FRESHNESS & HEALTH")
    print("-" * 85)
    loc_header = f"  {'Location Name':<22} {'Observed (UTC)':<20} {'Age (Min)':<11} {'Temp':<8} {'Humidity':<10} {'Health Status'}"
    print(loc_header)
    print("  " + "-" * 81)

    for loc in locations_status:
        loc_name = loc["location_name"]
        if loc.get("observation_id") is None:
            print(f"  {loc_name:<22} {'No Observations':<20} {'N/A':<11} {'N/A':<8} {'N/A':<10} NO DATA")
            continue

        obs_utc = (
            loc["observed_at"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if loc.get("observed_at")
            else "N/A"
        )
        age = loc.get("age_minutes")
        age_str = f"{age:.1f}m" if age is not None else "N/A"
        temp_str = f"{loc['temperature_c']}°C" if loc.get("temperature_c") is not None else "N/A"
        hum_str = f"{loc['relative_humidity_pct']}%" if loc.get("relative_humidity_pct") is not None else "N/A"

        # Staleness heuristic: fresh (< 60m), warning (60-180m), stale (> 180m)
        if age is not None and age <= 60.0:
            health = "HEALTHY (Fresh)"
        elif age is not None and age <= 180.0:
            health = "ACTIVE"
        elif age is not None:
            health = "STALE (>3 hrs)"
        else:
            health = "UNKNOWN"

        print(f"  {loc_name:<22} {obs_utc:<20} {age_str:<11} {temp_str:<8} {hum_str:<10} {health}")

    # 3. Historical Database Stats
    print("\n[3] HISTORICAL DATA ARCHIVE & INTEGRITY")
    print("-" * 85)
    total_obs = stats.get("total_observations", 0)
    total_runs = stats.get("total_runs", 0)
    succ_runs = stats.get("successful_runs", 0)
    success_rate = (succ_runs / total_runs * 100.0) if total_runs > 0 else 0.0

    earliest = (
        stats["earliest_observation"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if stats.get("earliest_observation")
        else "N/A"
    )
    latest = (
        stats["latest_observation"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if stats.get("latest_observation")
        else "N/A"
    )

    print(f"  Total Observations Stored : {total_obs}")
    print(f"  Monitored Locations Count : {stats.get('total_locations', 0)}")
    print(f"  Historical Timeline Span  : {earliest}  --->  {latest}")
    print(f"  Total Ingestion Runs      : {total_runs} (Success Rate: {success_rate:.1f}%)")

    # Historical count per location
    if location_counts:
        counts_str = ", ".join([f"{r['name']}: {r['observation_count']}" for r in location_counts])
        print(f"  Records per Location      : {counts_str}")

    print("=" * 85 + "\n")


def run_scheduler(interval_minutes: int, single_location: Optional[str] = None) -> None:
    """
    Run the ingestion pipeline on a reliable recurring schedule.
    Safely catches exceptions so transient network/database hiccups do not crash the service.
    """
    config = get_config()
    logger = setup_logger(config)

    logger.info("=" * 75)
    logger.info(
        "Starting UrbanPulseAI Ingestion Scheduler (Interval: %d minutes)",
        interval_minutes,
    )
    logger.info("Target: %s", single_location if single_location else "All Monitored Locations")
    logger.info("Press Ctrl+C to gracefully stop the scheduler.")
    logger.info("=" * 75)

    cycle_count = 0
    try:
        while True:
            cycle_count += 1
            cycle_start = datetime.now(timezone.utc)
            logger.info(">>> Beginning Ingestion Cycle #%d at %s UTC", cycle_count, cycle_start.strftime("%Y-%m-%d %H:%M:%S"))

            try:
                run_pipeline(dry_run=False, target_location=single_location)
            except Exception as e:
                logger.error("Unexpected error in weather cycle #%d: %s", cycle_count, e, exc_info=True)

            try:
                from src.collect_traffic import TrafficCollector
                traffic_collector = TrafficCollector(config)
                db_traffic = DatabaseManager(config.db)
                db_traffic.init_traffic_tables()
                traffic_res = traffic_collector.run_collection_cycle(db_traffic)
                if traffic_res.get("status") != "disabled":
                    logger.info(
                        "Traffic cycle #%d completed: status=%s, succeeded=%d/%d, saved=%d",
                        cycle_count,
                        traffic_res.get("status"),
                        traffic_res.get("succeeded", 0),
                        traffic_res.get("requested", 0),
                        traffic_res.get("saved", 0),
                    )
            except Exception as e:
                logger.error("Traffic collection failed in cycle #%d (weather collection unaffected): %s", cycle_count, e)

            # Calculate sleep duration to hit next interval boundary
            sleep_duration = interval_minutes * 60
            logger.info("Cycle #%d completed. Sleeping for %d minute(s)...", cycle_count, interval_minutes)

            # Sleep in 1-second slices for immediate response to Ctrl+C
            sleep_remaining = sleep_duration
            while sleep_remaining > 0:
                time.sleep(min(1.0, sleep_remaining))
                sleep_remaining -= 1.0

    except KeyboardInterrupt:
        logger.info("\nScheduled collection stopped by user (Ctrl+C). Exiting cleanly.")


def main():
    """Command line entrypoint for UrbanPulseAI weather collector."""
    parser = argparse.ArgumentParser(
        description="UrbanPulseAI - Weather Data Ingestion Pipeline (Day 2)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate weather from API without saving to PostgreSQL",
    )
    parser.add_argument(
        "--location",
        type=str,
        help="Collect weather for a single specific location (e.g. 'gachibowli' or 'Secunderabad')",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Display comprehensive system health report across pipeline and database",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Display the latest recorded weather observations from the database",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Display recent ingestion run records from the database",
    )
    parser.add_argument(
        "--verify-db",
        action="store_true",
        help="Verify PostgreSQL connection and required schema tables",
    )
    parser.add_argument(
        "--interval",
        type=int,
        help="Run continuously on a recurring interval of N minutes",
    )
    parser.add_argument(
        "--detect-anomalies",
        action="store_true",
        help="Analyze recent weather observations for anomalies using statistical & ML models",
    )
    parser.add_argument(
        "--list-anomalies",
        action="store_true",
        help="Display recorded weather anomaly alerts from the database",
    )
    parser.add_argument(
        "--scheduler",
        action="store_true",
        help="Run continuously using configured interval from .env (COLLECTION_INTERVAL_MINUTES)",
    )

    args = parser.parse_args()
    config = get_config()
    logger = setup_logger(config)

    # Anomaly Detection Analysis
    if args.detect_anomalies:
        from src.detector import WeatherAnomalyDetector, print_detection_summary
        detector = WeatherAnomalyDetector(config.anomaly_detection, db_manager=DatabaseManager(config.db))
        summary = detector.analyze_recent_observations(location_id=args.location, limit=50)
        print_detection_summary(summary)
        sys.stdout.flush()
        sys.exit(0)

    # Anomaly Alert Listing
    if args.list_anomalies:
        from src.detector import print_anomalies_list
        db = DatabaseManager(config.db)
        anomalies = db.get_recent_anomalies(limit=20, location_id=args.location)
        print_anomalies_list(anomalies)
        sys.stdout.flush()
        sys.exit(0)

    # Health Report
    if args.health:
        db = DatabaseManager(config.db)
        print_health_report(db)
        sys.exit(0)

    # Verify DB
    if args.verify_db:
        db = DatabaseManager(config.db)
        try:
            info = db.verify_database()
            print("\n[OK] Database verification successful!")
            print(f"  Database : {info['database']}")
            print(f"  User     : {info['user']}")
            print(f"  Tables   : {info['tables']}")
            sys.exit(0)
        except Exception as e:
            print(f"\n[FAIL] Database verification failed: {e}")
            sys.exit(1)

    # Summary View
    if args.summary:
        db = DatabaseManager(config.db)
        try:
            rows = db.get_latest_observations()
            if not rows or all(r.get("observation_id") is None for r in rows):
                print("No weather observations recorded in database yet.")
            else:
                print("\n" + "=" * 80)
                print("               URBANPULSE AI - LATEST RECORDED WEATHER")
                print("=" * 80)
                print(f"{'Location':<22} {'Observed (UTC)':<22} {'Temp':<9} {'Humidity':<10} {'Weather':<18}")
                print("-" * 80)
                for r in rows:
                    if r.get("observation_id") is None:
                        continue
                    obs_time = (
                        r["observed_at"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                        if r.get("observed_at")
                        else "N/A"
                    )
                    desc = get_weather_description(r.get("weather_code"))
                    print(
                        f"{r['location_name']:<22} {obs_time:<22} {r['temperature_c']}°C    {r['relative_humidity_pct']}%       {desc}"
                    )
                print("=" * 80 + "\n")
            sys.exit(0)
        except Exception as e:
            logger.error("Failed to query latest summary: %s", e)
            sys.exit(1)

    # Ingestion History View
    if args.history:
        db = DatabaseManager(config.db)
        try:
            runs = db.get_recent_ingestion_runs(limit=10)
            if not runs:
                print("No ingestion runs recorded in database yet.")
            else:
                print("\n" + "=" * 85)
                print("                     URBANPULSE AI - RECENT INGESTION RUNS")
                print("=" * 85)
                print(f"{'Run ID':<8} {'Started (UTC)':<24} {'Status':<10} {'Req':<5} {'Succ':<6} {'Saved':<6} {'Duration':<10}")
                print("-" * 85)
                for r in runs:
                    start_str = (
                        r["started_at"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                        if r.get("started_at")
                        else "N/A"
                    )
                    dur_str = f"{float(r['duration_seconds']):.2f}s" if r.get("duration_seconds") is not None else "-"
                    print(
                        f"{r['run_id']:<8} {start_str:<24} {r['status']:<10} {r['locations_requested']:<5} {r['locations_succeeded']:<6} {r['observations_saved']:<6} {dur_str:<10}"
                    )
                print("=" * 85 + "\n")
            sys.exit(0)
        except Exception as e:
            logger.error("Failed to query ingestion runs: %s", e)
            sys.exit(1)

    # Scheduled Continuous Ingestion
    if args.scheduler or args.interval is not None:
        interval = args.interval if args.interval is not None else config.scheduler.interval_minutes
        run_scheduler(interval_minutes=interval, single_location=args.location)
    else:
        # Single cycle run
        success = run_pipeline(dry_run=args.dry_run, target_location=args.location)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
