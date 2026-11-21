"""
UrbanPulse AI - Traffic Intelligence & Travel-Time Collection Module
Integrates with TomTom Routing & Traffic Flow APIs for monitored Hyderabad road corridors.
Handles timeouts, exponential backoff retries, rate limiting, and deduplication.
Provides a clear disabled state and setup guidance when no API key is configured.
Does NOT fabricate live traffic data.
"""

import argparse
from datetime import datetime, timezone
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import AppConfig, CorridorInfo, get_config
from src.database import DatabaseManager

logger = logging.getLogger("UrbanPulseAI.traffic")


class TrafficCollector:
    """
    Manages communication with the TomTom Traffic & Routing API.
    Enforces safe networking practices, rate limiting, retries, and clean disabled states.
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or get_config()
        self.traffic_config = self.config.traffic
        self.session = self._init_session()

    def _init_session(self) -> requests.Session:
        """Initialize requests.Session with resilient retry policies."""
        session = requests.Session()
        retries = Retry(
            total=self.traffic_config.max_retries,
            backoff_factor=self.traffic_config.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=5, pool_maxsize=10)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({
            "User-Agent": "UrbanPulseAI-TrafficCollector/1.0.0",
            "Accept": "application/json",
        })
        return session

    @property
    def is_configured(self) -> bool:
        """Check whether a valid TomTom API key is present in configuration."""
        return self.traffic_config.is_configured

    def get_status_info(self) -> Dict[str, Any]:
        """Return diagnostic provider configuration and credential status."""
        return {
            "provider": self.traffic_config.provider,
            "configured": self.is_configured,
            "api_key_masked": (
                f"{self.traffic_config.api_key[:4]}...{self.traffic_config.api_key[-4:]}"
                if self.is_configured
                else "NOT_SET"
            ),
            "routing_url": self.traffic_config.routing_url,
            "corridors_count": len(self.config.corridors),
            "timeout_seconds": self.traffic_config.timeout_seconds,
            "rate_limit_delay_seconds": self.traffic_config.rate_limit_delay_seconds,
            "instructions": (
                "TomTom Traffic API is ready."
                if self.is_configured
                else (
                    "TomTom API key is missing. To enable live traffic polling:\n"
                    "1. Register at https://developer.tomtom.com\n"
                    "2. Generate an API Key (Routing & Traffic Flow APIs)\n"
                    "3. Add 'TOMTOM_API_KEY=your_key_here' to e:/UrbanPulseAI/.env\n"
                    "4. Re-run traffic collection.\n"
                    "Note: In the absence of an API key, live traffic remains disabled; "
                    "no simulated data is injected into production tables."
                )
            ),
        }

    def fetch_route_travel_time(
        self, corridor: CorridorInfo
    ) -> Dict[str, Any]:
        """
        Request current travel time and free-flow duration for a given road corridor
        from TomTom Calculate Route API.
        
        Endpoint specification:
            https://api.tomtom.com/routing/1/calculateRoute/{locations}/json
            locations format: {origin_lat},{origin_lon}:{dest_lat},{dest_lon}
        """
        if not self.is_configured:
            raise ValueError(
                "TomTom API key not configured. Cannot request live traffic without credentials. "
                "Set TOMTOM_API_KEY in .env."
            )

        locations_param = (
            f"{corridor.origin_latitude:.6f},{corridor.origin_longitude:.6f}:"
            f"{corridor.destination_latitude:.6f},{corridor.destination_longitude:.6f}"
        )
        url = f"{self.traffic_config.routing_url.rstrip('/')}/{locations_param}/json"

        params = {
            "key": self.traffic_config.api_key,
            "traffic": "true",
            "travelMode": "car",
            "routeType": "fastest",
        }

        logger.debug("Requesting TomTom route calculation for corridor %s (%s)...", corridor.corridor_id, corridor.name)

        try:
            resp = self.session.get(
                url,
                params=params,
                timeout=self.traffic_config.timeout_seconds,
            )
        except requests.exceptions.Timeout as e:
            logger.error("TomTom API timed out for corridor %s: %s", corridor.corridor_id, e)
            raise
        except requests.exceptions.RequestException as e:
            logger.error("TomTom API connection error for corridor %s: %s", corridor.corridor_id, e)
            raise

        if resp.status_code == 401 or resp.status_code == 403:
            raise PermissionError(
                f"TomTom API rejected credentials (HTTP {resp.status_code}): Invalid or unentitled API key."
            )
        elif resp.status_code == 429:
            raise RuntimeError(
                f"TomTom API rate limit or quota exceeded (HTTP 429). Retry after backoff."
            )
        elif resp.status_code != 200:
            resp.raise_for_status()

        payload = resp.json()
        routes = payload.get("routes")
        if not routes or not isinstance(routes, list) or len(routes) == 0:
            raise ValueError(
                f"TomTom API returned no routes in payload for corridor {corridor.corridor_id}."
            )

        summary = routes[0].get("summary", {})
        travel_time_sec = summary.get("travelTimeInSeconds")
        if travel_time_sec is None:
            raise ValueError(
                f"TomTom route summary missing 'travelTimeInSeconds' for corridor {corridor.corridor_id}."
            )

        # Free-flow reference duration (noTrafficTravelTimeInSeconds)
        free_flow_sec = summary.get("noTrafficTravelTimeInSeconds")
        traffic_delay_sec = summary.get("trafficDelayInSeconds", 0.0)
        length_meters = summary.get("lengthInMeters")

        # Congestion Index: estimated_duration / free_flow_duration (only when free-flow exists & > 0)
        congestion_index = None
        if free_flow_sec and float(free_flow_sec) > 0:
            congestion_index = round(float(travel_time_sec) / float(free_flow_sec), 2)

        # Departure timestamp normalized to UTC
        dep_time_str = summary.get("departureTime")
        if dep_time_str:
            try:
                obs_dt = datetime.fromisoformat(dep_time_str.replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                obs_dt = datetime.now(timezone.utc)
        else:
            obs_dt = datetime.now(timezone.utc)

        return {
            "route_id": corridor.corridor_id,
            "provider": self.traffic_config.provider,
            "observed_at": obs_dt,
            "estimated_duration_seconds": float(travel_time_sec),
            "free_flow_duration_seconds": float(free_flow_sec) if free_flow_sec is not None else None,
            "delay_seconds": float(traffic_delay_sec) if traffic_delay_sec is not None else 0.0,
            "distance_meters": float(length_meters) if length_meters is not None else None,
            "congestion_index": congestion_index,
            "data_type": "live_api",
            "raw_payload": payload,
        }

    def run_collection_cycle(
        self,
        db: DatabaseManager,
        corridor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute an ingestion cycle across registered road corridors.
        If credentials are not configured, logs a clean disabled message and returns diagnostic status.
        """
        if not self.is_configured:
            msg = (
                "TomTom Traffic API key is not configured. Live traffic collection is paused. "
                "Set TOMTOM_API_KEY in .env to activate."
            )
            logger.warning(msg)
            return {
                "status": "disabled",
                "message": msg,
                "requested": 0,
                "succeeded": 0,
                "saved": 0,
                "errors": [],
            }

        target_corridors = self.config.corridors
        if corridor_id:
            target_corridors = [c for c in target_corridors if c.corridor_id == corridor_id]
            if not target_corridors:
                raise ValueError(f"Corridor '{corridor_id}' not found in configuration.")

        # Ensure corridors are seeded in DB
        db.seed_corridors(self.config.corridors)

        succeeded = 0
        saved = 0
        errors = []

        import time

        for idx, corridor in enumerate(target_corridors):
            try:
                record = self.fetch_route_travel_time(corridor)
                travel_time_id = db.save_route_travel_time(record)
                saved += 1
                succeeded += 1
                logger.info(
                    "[%s] Saved travel time: %ds (Free-flow: %s, Delay: %ss, Congestion Index: %s, ID #%d)",
                    corridor.name,
                    record["estimated_duration_seconds"],
                    f"{record['free_flow_duration_seconds']}s" if record.get("free_flow_duration_seconds") else "N/A",
                    record["delay_seconds"],
                    record["congestion_index"] or "N/A",
                    travel_time_id,
                )
            except Exception as e:
                logger.error("Failed to collect traffic for corridor %s: %s", corridor.corridor_id, e)
                errors.append(f"{corridor.corridor_id}: {str(e)}")

            if idx < len(target_corridors) - 1 and self.traffic_config.rate_limit_delay_seconds > 0:
                time.sleep(self.traffic_config.rate_limit_delay_seconds)

        return {
            "status": "success" if succeeded == len(target_corridors) else ("partial" if succeeded > 0 else "failed"),
            "requested": len(target_corridors),
            "succeeded": succeeded,
            "saved": saved,
            "errors": errors,
        }


def main():
    """CLI entrypoint for traffic intelligence module."""
    parser = argparse.ArgumentParser(description="UrbanPulse AI Traffic Intelligence Collector")
    parser.add_argument("--status", action="store_true", help="Display provider status and setup guidance")
    parser.add_argument("--corridors", action="store_true", help="List registered Hyderabad arterial corridors")
    parser.add_argument("--run-once", action="store_true", help="Run a single traffic collection cycle")
    parser.add_argument("--corridor", type=str, help="Filter collection to a single corridor ID")

    args = parser.parse_args()
    config = get_config()
    db = DatabaseManager(config.db)
    collector = TrafficCollector(config)

    if args.status:
        info = collector.get_status_info()
        print("\n=======================================================")
        print("          URBANPULSE AI - TRAFFIC PROVIDER STATUS")
        print("=======================================================")
        print(f"  Provider       : {info['provider'].upper()}")
        print(f"  Configured     : {'YES (Ready)' if info['configured'] else 'NO (Disabled)'}")
        print(f"  API Key        : {info['api_key_masked']}")
        print(f"  Routing URL    : {info['routing_url']}")
        print(f"  Corridors      : {info['corridors_count']} monitored")
        print("-------------------------------------------------------")
        print(info["instructions"])
        print("=======================================================\n")
        return

    if args.corridors:
        print("\n=========================================================================================")
        print("                        REGISTERED HYDERABAD ROAD CORRIDORS")
        print("=========================================================================================")
        header = f"  {'ID':<24} {'Name':<34} {'Distance':<10} {'Via Road'}"
        print(header)
        print("  " + "-" * 87)
        for c in config.corridors:
            print(f"  {c.corridor_id:<24} {c.name:<34} {c.distance_km:<10.1f}km {c.via_road}")
        print("=========================================================================================\n")
        return

    if args.run_once:
        print("\nStarting Traffic Collection Cycle...")
        db.init_traffic_tables()
        result = collector.run_collection_cycle(db, corridor_id=args.corridor)
        print(f"Result: {result['status'].upper()}")
        print(f"Requested: {result['requested']} | Succeeded: {result['succeeded']} | Saved: {result['saved']}")
        if result.get("message"):
            print(f"Message: {result['message']}")
        if result.get("errors"):
            print("Errors:")
            for err in result["errors"]:
                print(f"  - {err}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
