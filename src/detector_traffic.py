"""
UrbanPulse AI - Traffic Disruption Detection Engine
Statistical travel-time anomaly detection using Median Absolute Deviation (MAD)
and Congestion Index ratio analysis.
Correlates travel-time slowdowns with local meteorological observations
ONLY when physical weather evidence exists.
"""

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import AppConfig, TrafficConfig, get_config
from src.database import DatabaseManager

logger = logging.getLogger("UrbanPulseAI.detector_traffic")


class TrafficDisruptionDetector:
    """
    Evaluates road corridor travel times against historical rolling baselines.
    Prevents false alerts on cold start (< min_history_observations).
    Calculates congestion index strictly when free-flow references exist.
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self.app_config = config or get_config()
        self.config: TrafficConfig = self.app_config.traffic

    def evaluate_observation(
        self,
        obs: Dict[str, Any],
        history: List[Dict[str, Any]],
        weather_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate a single corridor travel-time observation against strictly prior history.
        Returns a disruption alert dictionary if an anomalous increase is confirmed,
        or None if travel time is within normal baseline variations.
        
        Guarantees NO DATA LEAKAGE: history must only contain observations prior to obs['observed_at'].
        """
        route_id = obs["route_id"]
        obs_duration = float(obs.get("estimated_duration_seconds") or 0.0)
        if obs_duration <= 0:
            return None

        # 1. Cold-start Protection: filter valid historical durations
        valid_durations = [
            float(h["estimated_duration_seconds"])
            for h in history
            if h.get("estimated_duration_seconds") is not None
            and float(h["estimated_duration_seconds"]) > 0
        ]

        if len(valid_durations) < self.config.min_history_observations:
            logger.debug(
                "Corridor %s has insufficient history (%d < %d). Skipping alert.",
                route_id,
                len(valid_durations),
                self.config.min_history_observations,
            )
            return None

        # 2. Historical Baseline: Median & MAD
        durations_arr = np.array(valid_durations, dtype=float)
        baseline_median = float(np.median(durations_arr))
        abs_deviations = np.abs(durations_arr - baseline_median)
        mad = float(np.median(abs_deviations))
        deviation = obs_duration - baseline_median

        # If travel time is faster or equal to median, no disruption exists
        if deviation <= 0:
            return None

        # If deviation is below the minimum significant threshold (e.g. 180s = 3 minutes), ignore micro-jitter
        if deviation < self.config.min_deviation_seconds:
            return None

        # 3. Modified Z-score calculation
        if mad > 0:
            modified_z = float(0.6745 * deviation / mad)
        else:
            std = float(np.std(durations_arr))
            if std > 0:
                modified_z = float(deviation / std)
            else:
                # All historical samples had identical values
                modified_z = float((deviation / baseline_median) * 5.0)

        # 4. Congestion Index (only when reference free-flow exists & > 0)
        free_flow = obs.get("free_flow_duration_seconds")
        congestion_index: Optional[float] = None
        if free_flow is not None and float(free_flow) > 0:
            congestion_index = round(obs_duration / float(free_flow), 2)

        # 5. Anomaly Decision & Threshold Check
        qualifies_by_mad = modified_z >= self.config.mad_threshold_moderate
        qualifies_by_congestion = (
            congestion_index is not None and congestion_index >= self.config.congestion_ratio_moderate
        )

        if not (qualifies_by_mad or qualifies_by_congestion):
            return None

        # 6. Severity Classification
        if modified_z >= self.config.mad_threshold_critical or (
            congestion_index is not None and congestion_index >= self.config.congestion_ratio_critical
        ):
            severity = "CRITICAL"
        elif modified_z >= self.config.mad_threshold_severe or (
            congestion_index is not None and congestion_index >= self.config.congestion_ratio_severe
        ):
            severity = "SEVERE"
        else:
            severity = "MODERATE"

        # 7. Weather Correlation Engine
        weather_analysis = self._correlate_weather(weather_context)

        observed_at = obs["observed_at"]
        if isinstance(observed_at, str):
            observed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))

        evidence = {
            "route_id": route_id,
            "provider": obs.get("provider", "tomtom"),
            "data_type": obs.get("data_type", "live_api"),
            "observed_duration_seconds": round(obs_duration, 1),
            "observed_duration_minutes": round(obs_duration / 60.0, 1),
            "baseline_median_seconds": round(baseline_median, 1),
            "baseline_median_minutes": round(baseline_median / 60.0, 1),
            "deviation_seconds": round(deviation, 1),
            "delay_minutes": round(deviation / 60.0, 1),
            "mad": round(mad, 1),
            "modified_z_score": round(modified_z, 2),
            "free_flow_duration_seconds": round(float(free_flow), 1) if free_flow else None,
            "congestion_index": congestion_index,
            "history_sample_count": len(valid_durations),
            "explanation": (
                f"Travel time {round(obs_duration / 60.0, 1)}m is {round(deviation / 60.0, 1)}m "
                f"({round((deviation / baseline_median) * 100, 1)}%) above historical median "
                f"({round(baseline_median / 60.0, 1)}m, Z={modified_z:.2f})."
            ),
        }

        return {
            "route_id": route_id,
            "observed_at": observed_at,
            "severity": severity,
            "observed_duration_seconds": round(obs_duration, 1),
            "baseline_duration_seconds": round(baseline_median, 1),
            "deviation_seconds": round(deviation, 1),
            "congestion_index": congestion_index,
            "model_name": "statistical_mad",
            "model_version": self.config.model_version,
            "evidence": evidence,
            "weather_context": weather_analysis,
            "status": "active",
        }

    def _correlate_weather(
        self, weather_context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Assess whether local adverse weather directly contributed to corridor slowdown.
        Strictly requires verified physical meteorological evidence.
        Does NOT label a slowdown as weather-caused without supporting measurements.
        """
        if not weather_context:
            return {
                "weather_correlated": False,
                "evidence": "No synchronous meteorological data available for adjacent station.",
                "station_id": None,
                "precipitation_mm": None,
                "wind_speed_kmh": None,
            }

        rain = float(weather_context.get("precipitation_mm") or weather_context.get("rain_mm") or 0.0)
        wind = float(weather_context.get("wind_speed_kmh") or 0.0)
        gusts = float(weather_context.get("wind_gusts_kmh") or 0.0)
        station_name = weather_context.get("location_name") or weather_context.get("location_id") or "Adjacent Station"
        has_weather_anomaly = bool(weather_context.get("has_anomaly", False))

        # Adverse weather thresholds: rain >= 2.0mm, or severe gusts >= 45km/h, or detected anomaly
        is_rain_event = rain >= 2.0
        is_wind_event = gusts >= 45.0 or wind >= 35.0

        if is_rain_event or is_wind_event or has_weather_anomaly:
            factors = []
            if is_rain_event:
                factors.append(f"precipitation {rain:.1f} mm")
            if is_wind_event:
                factors.append(f"wind velocity {wind:.1f} km/h (gusts {gusts:.1f} km/h)")
            if has_weather_anomaly:
                factors.append("active atmospheric anomaly")

            factor_str = ", ".join(factors)
            return {
                "weather_correlated": True,
                "station_id": weather_context.get("location_id"),
                "station_name": station_name,
                "precipitation_mm": rain,
                "wind_speed_kmh": wind,
                "wind_gusts_kmh": gusts,
                "evidence": (
                    f"Adverse weather verified at {station_name} ({factor_str}). "
                    f"Physical meteorological factors likely contributed to reduced roadway speeds."
                ),
            }
        else:
            return {
                "weather_correlated": False,
                "station_id": weather_context.get("location_id"),
                "station_name": station_name,
                "precipitation_mm": rain,
                "wind_speed_kmh": wind,
                "wind_gusts_kmh": gusts,
                "evidence": (
                    f"Normal meteorological conditions at {station_name} (Rain: {rain:.1f} mm, Wind: {wind:.1f} km/h). "
                    f"Slowdown is NOT weather-caused; attributed to conventional congestion, bottlenecks, or traffic incidents."
                ),
            }

    def analyze_db_observations(
        self,
        db: DatabaseManager,
        route_id: Optional[str] = None,
        limit_recent: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Analyze recent un-evaluated corridor observations stored in database.
        Saves generated alerts to traffic_disruptions table.
        """
        db.init_traffic_tables()
        recent_obs = db.get_corridor_travel_time_history(route_id=route_id, limit=limit_recent)
        if not recent_obs:
            logger.info("No corridor observations in database to evaluate.")
            return []

        corridors = {c["corridor_id"]: c for c in db.get_all_corridors()}
        latest_weather = {w["location_id"]: w for w in db.get_latest_observations()}

        alerts_created = []

        for obs in recent_obs:
            rid = obs["route_id"]
            obs_time = obs["observed_at"]
            corridor_meta = corridors.get(rid, {})

            # Fetch strictly prior history
            history = db.get_prior_route_travel_times(
                route_id=rid,
                before_time=obs_time,
                limit=100,
            )

            # Nearest weather context (using origin station)
            origin_loc_id = corridor_meta.get("origin_location_id")
            weather_ctx = latest_weather.get(origin_loc_id) if origin_loc_id else None

            alert = self.evaluate_observation(obs, history, weather_context=weather_ctx)
            if alert:
                alert_id = db.save_traffic_disruption(alert)
                alert["disruption_id"] = alert_id
                alerts_created.append(alert)
                logger.info(
                    "Detected %s traffic disruption on corridor %s (ID #%d): %s",
                    alert["severity"],
                    rid,
                    alert_id,
                    alert["evidence"]["explanation"],
                )

        return alerts_created
