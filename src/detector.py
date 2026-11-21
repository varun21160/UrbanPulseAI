"""
UrbanPulseAI - Explainable Anomaly Detection Engine (Day 3)
Combines robust statistical baselines (Rolling Median + MAD) and Machine Learning
(Isolation Forest) to detect meteorological anomalies across urban stations.
Prevents data leakage, handles zero-variance safely, and provides auditable evidence.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from sklearn.ensemble import IsolationForest

# Ensure project root is in sys.path when executed directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output in Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.config import AnomalyDetectionConfig, get_config
from src.database import DatabaseManager

logger = logging.getLogger("UrbanPulseAI.detector")


@dataclass
class AnomalyAlert:
    """Represents an explainable anomaly alert with evidentiary metadata."""
    location_id: str
    observed_at: datetime
    detected_at: datetime
    anomaly_type: str
    severity: str         # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    risk_score: float     # Normalized 0.0 - 1.0
    model_name: str       # "statistical_mad", "isolation_forest", "ensemble_consensus"
    model_version: str
    observed_value: Optional[float]
    baseline_value: Optional[float]
    evidence: Dict[str, Any]
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DetectionSummary:
    """Summary of an anomaly detection evaluation run."""
    observations_evaluated: int = 0
    observations_with_sufficient_history: int = 0
    observations_skipped_insufficient_history: int = 0
    alerts: List[AnomalyAlert] = field(default_factory=list)


class WeatherAnomalyDetector:
    """
    Explainable weather anomaly detector.
    Evaluates meteorological time-series observations against past baselines
    using Median Absolute Deviation (MAD) and optional Isolation Forest.
    """

    def __init__(
        self,
        config: Optional[Union[AnomalyDetectionConfig, Any]] = None,
        db_manager: Optional[DatabaseManager] = None,
    ):
        if hasattr(config, "anomaly_detection"):
            self.config = config.anomaly_detection
        else:
            self.config = config or get_config().anomaly_detection
        self.db = db_manager or DatabaseManager()

    # ------------------------------------------------------------------
    # 1. Statistical Baseline & MAD
    # ------------------------------------------------------------------
    def compute_feature_mad(
        self,
        values: List[float],
        deviation_floor: float,
    ) -> Optional[Dict[str, float]]:
        """
        Compute robust median and Median Absolute Deviation (MAD) for a feature.
        Handles zero/low variance safely using deviation_floor.
        Returns None if history length is below min_history_observations.
        """
        clean_vals = [v for v in values if v is not None and not np.isnan(v)]
        if len(clean_vals) < self.config.min_history_observations:
            return None

        arr = np.array(clean_vals, dtype=float)
        median_val = float(np.median(arr))
        abs_deviations = np.abs(arr - median_val)
        mad_val = float(np.median(abs_deviations))

        # Effective scale: 1.4826 * MAD approximates standard deviation for normal data
        effective_scale = max(mad_val * 1.4826, deviation_floor)

        return {
            "median": median_val,
            "mad": mad_val,
            "effective_scale": effective_scale,
            "sample_size": len(clean_vals),
        }

    def score_statistical_mad(
        self,
        observed_value: float,
        baseline: Dict[str, float],
        deviation_floor: float,
    ) -> Tuple[float, float]:
        """
        Calculate the modified Z-score and absolute deviation.
        Uses deviation_floor to avoid inflated scores when baseline MAD is zero.
        """
        deviation = observed_value - baseline["median"]
        abs_dev = abs(deviation)

        # If absolute deviation is smaller than the floor, not anomalous
        if abs_dev < deviation_floor:
            return 0.0, deviation

        mad = baseline["mad"]
        if mad > 0.0:
            # Boris Iglewicz and David Hoaglin modified Z-score: 0.6745 * (x - median) / MAD
            z_score = 0.6745 * abs_dev / mad
        else:
            # Zero-variance baseline (e.g. all prior readings identical)
            z_score = abs_dev / deviation_floor

        return z_score, deviation

    # ------------------------------------------------------------------
    # 2. Machine Learning: Isolation Forest
    # ------------------------------------------------------------------
    def score_isolation_forest(
        self,
        target_features: List[float],
        historical_records: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Fit Isolation Forest on historical feature vectors and score target observation.
        Returns None if historical samples are insufficient (< isolation_forest_min_samples).
        """
        if len(historical_records) < self.config.isolation_forest_min_samples:
            return None

        feature_keys = [
            "temperature_c",
            "relative_humidity_pct",
            "wind_speed_kmh",
            "precipitation_mm",
        ]

        # Build feature matrix from past observations
        rows: List[List[float]] = []
        for rec in historical_records:
            row: List[float] = []
            for k in feature_keys:
                v = rec.get(k)
                row.append(float(v) if v is not None and not np.isnan(v) else 0.0)
            rows.append(row)

        X_train = np.array(rows, dtype=float)
        X_target = np.array([target_features], dtype=float)

        try:
            model = IsolationForest(
                n_estimators=100,
                contamination=self.config.isolation_forest_contamination,
                random_state=42,
            )
            model.fit(X_train)
            pred = model.predict(X_target)[0]  # -1 for anomaly, 1 for inlier
            # score_samples returns opposite of anomaly score; more negative = more anomalous
            score = -float(model.score_samples(X_target)[0])

            is_outlier = bool(pred == -1 or score >= 0.55)
            # Normalize risk score into [0.0, 1.0]
            norm_risk = float(np.clip((score - 0.5) / 0.5, 0.0, 1.0))

            return {
                "is_outlier": is_outlier,
                "raw_score": round(score, 4),
                "risk_score": round(norm_risk, 3),
                "features_used": feature_keys,
            }
        except Exception as e:
            logger.warning("Isolation Forest execution failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # 3. Observation Evaluation Engine
    # ------------------------------------------------------------------
    def evaluate_observation(
        self,
        observation: Dict[str, Any],
        historical_observations: List[Dict[str, Any]],
        detected_at: Optional[datetime] = None,
    ) -> List[AnomalyAlert]:
        """
        Evaluate a single observation against its historical past observations.
        Guarantees NO DATA LEAKAGE: historical_observations must precede observation.
        Returns list of AnomalyAlert objects (empty if normal or insufficient history).
        """
        location_id = observation["location_id"]
        observed_at = observation["observed_at"]
        detection_time = detected_at or datetime.now(timezone.utc)
        alerts: List[AnomalyAlert] = []

        # Validate sufficient history
        num_past = len(historical_observations)
        if num_past < self.config.min_history_observations:
            logger.debug(
                "Insufficient history for location [%s] at %s (have %d, need >= %d). Skipping.",
                location_id,
                observed_at,
                num_past,
                self.config.min_history_observations,
            )
            return alerts

        # Extract historical series for features
        hist_temps = [r.get("temperature_c") for r in historical_observations]
        hist_rains = [r.get("precipitation_mm") or r.get("rain_mm") for r in historical_observations]
        hist_winds = [r.get("wind_speed_kmh") for r in historical_observations]
        hist_gusts = [r.get("wind_gusts_kmh") for r in historical_observations]
        hist_humids = [r.get("relative_humidity_pct") for r in historical_observations]

        # ----------------------------------------------------------------
        # Check A: Temperature Spike / Drop
        # ----------------------------------------------------------------
        obs_temp = observation.get("temperature_c")
        if obs_temp is not None:
            temp_baseline = self.compute_feature_mad(
                hist_temps, self.config.temp_deviation_floor_c
            )
            if temp_baseline:
                z_score, dev = self.score_statistical_mad(
                    obs_temp, temp_baseline, self.config.temp_deviation_floor_c
                )
                if z_score >= self.config.mad_threshold_moderate:
                    is_spike = dev > 0
                    anomaly_type = "temperature_spike" if is_spike else "temperature_drop"
                    severity, risk = self._determine_severity_and_risk(z_score)

                    direction = "above" if is_spike else "below"
                    explanation = (
                        f"Observed temperature of {obs_temp:.1f}°C is {abs(dev):.1f}°C {direction} "
                        f"historical median ({temp_baseline['median']:.1f}°C, MAD={temp_baseline['mad']:.1f}°C), "
                        f"producing a modified Z-score of {z_score:.2f} (threshold: {self.config.mad_threshold_moderate:.1f})."
                    )

                    evidence = {
                        "feature": "temperature_c",
                        "observed_value": obs_temp,
                        "baseline_median": temp_baseline["median"],
                        "baseline_mad": temp_baseline["mad"],
                        "modified_z_score": round(z_score, 2),
                        "deviation": round(dev, 2),
                        "deviation_floor": self.config.temp_deviation_floor_c,
                        "sample_size": temp_baseline["sample_size"],
                        "explanation": explanation,
                    }

                    alerts.append(
                        AnomalyAlert(
                            location_id=location_id,
                            observed_at=observed_at,
                            detected_at=detection_time,
                            anomaly_type=anomaly_type,
                            severity=severity,
                            risk_score=risk,
                            model_name="statistical_mad",
                            model_version=self.config.model_version,
                            observed_value=obs_temp,
                            baseline_value=temp_baseline["median"],
                            evidence=evidence,
                        )
                    )

        # ----------------------------------------------------------------
        # Check B: Extreme Precipitation
        # ----------------------------------------------------------------
        obs_rain = observation.get("precipitation_mm") or observation.get("rain_mm")
        if obs_rain is not None and obs_rain >= self.config.rain_threshold_mm:
            rain_baseline = self.compute_feature_mad(
                hist_rains, self.config.rain_threshold_mm
            )
            if rain_baseline:
                z_score, dev = self.score_statistical_mad(
                    obs_rain, rain_baseline, self.config.rain_threshold_mm
                )
                if z_score >= self.config.mad_threshold_moderate:
                    severity, risk = self._determine_severity_and_risk(z_score)
                    explanation = (
                        f"Observed precipitation of {obs_rain:.1f} mm exceeds historical median "
                        f"({rain_baseline['median']:.1f} mm) with a modified Z-score of {z_score:.2f}."
                    )
                    evidence = {
                        "feature": "precipitation_mm",
                        "observed_value": obs_rain,
                        "baseline_median": rain_baseline["median"],
                        "baseline_mad": rain_baseline["mad"],
                        "modified_z_score": round(z_score, 2),
                        "deviation": round(dev, 2),
                        "sample_size": rain_baseline["sample_size"],
                        "explanation": explanation,
                    }
                    alerts.append(
                        AnomalyAlert(
                            location_id=location_id,
                            observed_at=observed_at,
                            detected_at=detection_time,
                            anomaly_type="extreme_precipitation",
                            severity=severity,
                            risk_score=risk,
                            model_name="statistical_mad",
                            model_version=self.config.model_version,
                            observed_value=obs_rain,
                            baseline_value=rain_baseline["median"],
                            evidence=evidence,
                        )
                    )

        # ----------------------------------------------------------------
        # Check C: Severe Wind / Gusts
        # ----------------------------------------------------------------
        obs_wind = observation.get("wind_speed_kmh")
        if obs_wind is not None and obs_wind >= self.config.wind_deviation_floor_kmh:
            wind_baseline = self.compute_feature_mad(
                hist_winds, self.config.wind_deviation_floor_kmh
            )
            if wind_baseline:
                z_score, dev = self.score_statistical_mad(
                    obs_wind, wind_baseline, self.config.wind_deviation_floor_kmh
                )
                if z_score >= self.config.mad_threshold_moderate:
                    severity, risk = self._determine_severity_and_risk(z_score)
                    explanation = (
                        f"Observed wind speed of {obs_wind:.1f} km/h exceeds historical median "
                        f"({wind_baseline['median']:.1f} km/h) with a modified Z-score of {z_score:.2f}."
                    )
                    evidence = {
                        "feature": "wind_speed_kmh",
                        "observed_value": obs_wind,
                        "baseline_median": wind_baseline["median"],
                        "baseline_mad": wind_baseline["mad"],
                        "modified_z_score": round(z_score, 2),
                        "deviation": round(dev, 2),
                        "sample_size": wind_baseline["sample_size"],
                        "explanation": explanation,
                    }
                    alerts.append(
                        AnomalyAlert(
                            location_id=location_id,
                            observed_at=observed_at,
                            detected_at=detection_time,
                            anomaly_type="high_wind_sustained",
                            severity=severity,
                            risk_score=risk,
                            model_name="statistical_mad",
                            model_version=self.config.model_version,
                            observed_value=obs_wind,
                            baseline_value=wind_baseline["median"],
                            evidence=evidence,
                        )
                    )

        # Wind Gusts Check
        obs_gusts = observation.get("wind_gusts_kmh")
        if obs_gusts is not None and obs_gusts >= self.config.wind_gust_threshold_kmh:
            gust_baseline = self.compute_feature_mad(
                hist_gusts, self.config.wind_deviation_floor_kmh
            )
            if gust_baseline:
                z_score, dev = self.score_statistical_mad(
                    obs_gusts, gust_baseline, self.config.wind_deviation_floor_kmh
                )
                if z_score >= self.config.mad_threshold_moderate:
                    severity, risk = self._determine_severity_and_risk(z_score)
                    explanation = (
                        f"Observed wind gusts of {obs_gusts:.1f} km/h exceed historical median "
                        f"({gust_baseline['median']:.1f} km/h) with a modified Z-score of {z_score:.2f}."
                    )
                    evidence = {
                        "feature": "wind_gusts_kmh",
                        "observed_value": obs_gusts,
                        "baseline_median": gust_baseline["median"],
                        "baseline_mad": gust_baseline["mad"],
                        "modified_z_score": round(z_score, 2),
                        "deviation": round(dev, 2),
                        "sample_size": gust_baseline["sample_size"],
                        "explanation": explanation,
                    }
                    alerts.append(
                        AnomalyAlert(
                            location_id=location_id,
                            observed_at=observed_at,
                            detected_at=detection_time,
                            anomaly_type="high_wind_gusts",
                            severity=severity,
                            risk_score=risk,
                            model_name="statistical_mad",
                            model_version=self.config.model_version,
                            observed_value=obs_gusts,
                            baseline_value=gust_baseline["median"],
                            evidence=evidence,
                        )
                    )

        # ----------------------------------------------------------------
        # Check D: Isolation Forest (Multivariate)
        # ----------------------------------------------------------------
        target_features = [
            float(obs_temp) if obs_temp is not None else 25.0,
            float(observation.get("relative_humidity_pct") or 50.0),
            float(obs_wind or 0.0),
            float(obs_rain or 0.0),
        ]

        iforest_result = self.score_isolation_forest(
            target_features=target_features,
            historical_records=historical_observations,
        )

        if iforest_result and iforest_result["is_outlier"]:
            # If we already have statistical alerts, upgrade severity or record agreement
            if alerts:
                for alert in alerts:
                    alert.evidence["isolation_forest"] = iforest_result
                    alert.evidence["model_agreement"] = "consensus"
                    # Elevate severity when both models independently agree
                    if alert.severity == "LOW":
                        alert.severity = "MEDIUM"
                    elif alert.severity == "MEDIUM":
                        alert.severity = "HIGH"
                    alert.risk_score = min(1.0, round(alert.risk_score + 0.15, 3))
            else:
                # Multivariate anomaly detected by Isolation Forest alone
                explanation = (
                    f"Multivariate weather vector {target_features} was identified as an outlier "
                    f"by Isolation Forest (anomaly score: {iforest_result['raw_score']:.3f})."
                )
                evidence = {
                    "feature": "multivariate",
                    "features_used": iforest_result["features_used"],
                    "target_vector": target_features,
                    "isolation_forest": iforest_result,
                    "model_agreement": "isolation_forest_only",
                    "explanation": explanation,
                }
                alerts.append(
                    AnomalyAlert(
                        location_id=location_id,
                        observed_at=observed_at,
                        detected_at=detection_time,
                        anomaly_type="multivariate_anomaly",
                        severity="LOW",
                        risk_score=iforest_result["risk_score"],
                        model_name="isolation_forest",
                        model_version=self.config.model_version,
                        observed_value=None,
                        baseline_value=None,
                        evidence=evidence,
                    )
                )

        return alerts

    def _determine_severity_and_risk(self, z_score: float) -> Tuple[str, float]:
        """Convert a modified Z-score into severity category and normalized risk score."""
        if z_score >= self.config.mad_threshold_critical:
            severity = "CRITICAL"
            risk = min(1.0, round(0.75 + (z_score - self.config.mad_threshold_critical) * 0.05, 3))
        elif z_score >= self.config.mad_threshold_severe:
            severity = "HIGH"
            risk = round(0.50 + (z_score - self.config.mad_threshold_severe) * 0.15, 3)
        else:
            severity = "MEDIUM"
            risk = round(0.30 + (z_score - self.config.mad_threshold_moderate) * 0.20, 3)

        return severity, min(1.0, max(0.0, risk))

    # ------------------------------------------------------------------
    # 4. Pipeline Execution (Batch / Real-Time Analysis)
    # ------------------------------------------------------------------
    def analyze_recent_observations(
        self,
        location_id: Optional[str] = None,
        limit: int = 50,
        save_to_db: bool = True,
    ) -> DetectionSummary:
        """
        Evaluate recent observations for anomalies.
        For each observation, queries prior historical data strictly before observed_at
        (guaranteeing no data leakage) and records any detected alerts in weather_anomalies.
        """
        observations = self.db.get_observations_for_analysis(
            location_id=location_id, limit=limit
        )

        summary = DetectionSummary()
        summary.observations_evaluated = len(observations)

        logger.info(
            "Analyzing %d recent observation(s) for anomalies (location: %s)...",
            len(observations),
            location_id or "ALL",
        )

        detection_time = datetime.now(timezone.utc)

        for obs in observations:
            loc_id = obs["location_id"]
            obs_time = obs["observed_at"]

            # Query historical records strictly prior to this observation (LEAKAGE PREVENTION)
            past_records = self.db.get_historical_observations_before(
                location_id=loc_id,
                before_time=obs_time,
                limit=100,
            )

            if len(past_records) < self.config.min_history_observations:
                summary.observations_skipped_insufficient_history += 1
                continue

            summary.observations_with_sufficient_history += 1
            alerts = self.evaluate_observation(
                observation=obs,
                historical_observations=past_records,
                detected_at=detection_time,
            )

            for alert in alerts:
                summary.alerts.append(alert)
                if save_to_db:
                    try:
                        self.db.save_anomaly(alert.to_dict())
                        logger.info(
                            "Saved %s anomaly [%s] for location %s at %s (Risk: %.2f)",
                            alert.severity,
                            alert.anomaly_type,
                            alert.location_id,
                            alert.observed_at.strftime("%Y-%m-%d %H:%M UTC"),
                            alert.risk_score,
                        )
                    except Exception as e:
                        logger.error("Failed to persist anomaly alert to database: %s", e)

        logger.info(
            "Anomaly Analysis Complete: %d evaluated, %d with sufficient history, %d alerts generated.",
            summary.observations_evaluated,
            summary.observations_with_sufficient_history,
            len(summary.alerts),
        )

        return summary


def print_detection_summary(summary: DetectionSummary) -> None:
    """Format and display summary of anomaly detection analysis."""
    print("\n" + "=" * 95)
    print("                 URBANPULSE AI - ANOMALY DETECTION ANALYSIS REPORT")
    print("=" * 95)
    print(f"Observations Evaluated             : {summary.observations_evaluated}")
    print(f"With Sufficient History (>= threshold): {summary.observations_with_sufficient_history}")
    print(f"Skipped (Insufficient History)     : {summary.observations_skipped_insufficient_history}")
    print(f"Anomalies Detected                 : {len(summary.alerts)}")
    print("-" * 95)

    if not summary.alerts:
        if summary.observations_with_sufficient_history == 0:
            print("  [INFO] Insufficient historical data exists to compute reliable statistical baselines.")
            print("         Observations require at least the configured minimum past observations threshold.")
            print("         No anomalies were generated to avoid false positives.")
        else:
            print("  [OK] No anomalies detected. All observations fall within normal baseline limits.")
    else:
        header = f"{'Location':<18} {'Observed (UTC)':<18} {'Type':<22} {'Severity':<10} {'Risk':<6} {'Model':<16}"
        print(header)
        print("-" * 95)
        for a in summary.alerts:
            obs_utc = a.observed_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            print(
                f"{a.location_id:<18} {obs_utc:<18} {a.anomaly_type:<22} {a.severity:<10} {a.risk_score:<6.2f} {a.model_name:<16}"
            )
            # Print explainable evidence
            exp = a.evidence.get("explanation", "")
            if exp:
                print(f"  -> Evidence: {exp}")
    print("=" * 95 + "\n")
    sys.stdout.flush()


def print_anomalies_list(anomalies: List[Dict[str, Any]]) -> None:
    """Format and display historical anomaly alerts from database."""
    print("\n" + "=" * 100)
    print("                    URBANPULSE AI - RECORDED WEATHER ANOMALIES")
    print("=" * 100)
    if not anomalies:
        print("No weather anomalies currently recorded in the database.")
        print("=" * 100 + "\n")
        sys.stdout.flush()
        return

    header = f"{'ID':<6} {'Location':<20} {'Observed (UTC)':<18} {'Type':<22} {'Severity':<10} {'Risk':<6} {'Status'}"
    print(header)
    print("-" * 100)
    for a in anomalies:
        obs_utc = (
            a["observed_at"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if a.get("observed_at")
            else "N/A"
        )
        print(
            f"#{a['anomaly_id']:<5} {a['location_name']:<20} {obs_utc:<18} {a['anomaly_type']:<22} {a['severity']:<10} {a['risk_score']:<6.2f} {a['status']}"
        )
        # Explainable evidence narrative
        evidence = a.get("evidence", {})
        if isinstance(evidence, dict) and evidence.get("explanation"):
            print(f"   -> {evidence['explanation']}")
    print("=" * 100 + "\n")
    sys.stdout.flush()


def main():
    """CLI entrypoint for UrbanPulseAI Anomaly Detection Engine."""
    import argparse
    import sys

    # Ensure UTF-8 console output
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="UrbanPulseAI - Weather Anomaly Detection Engine (Day 3)"
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze recent observations against historical baselines and record alerts",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List recent detected weather anomalies from the database",
    )
    parser.add_argument(
        "--location",
        type=str,
        help="Filter analysis or listing to a specific location (e.g. 'hyderabad-central')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of observations or anomalies to process/display (default: 50)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Run analysis without saving alerts into weather_anomalies table",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    detector = WeatherAnomalyDetector()

    if args.list:
        anomalies = detector.db.get_recent_anomalies(
            limit=args.limit, location_id=args.location
        )
        print_anomalies_list(anomalies)
        sys.exit(0)

    if args.analyze or not sys.argv[1:]:
        summary = detector.analyze_recent_observations(
            location_id=args.location,
            limit=args.limit,
            save_to_db=not args.no_save,
        )
        print_detection_summary(summary)
        sys.exit(0)


if __name__ == "__main__":
    main()

