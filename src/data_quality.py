"""
UrbanPulseAI - Data Quality & Validation Module
Enforces schema conformance, realistic physical meteorological boundaries,
staleness thresholds, and integrity checks for weather observations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from src.config import DataQualityConfig, get_config

logger = logging.getLogger("UrbanPulseAI.data_quality")


@dataclass
class ValidationIssue:
    """Represents a specific data quality anomaly or violation."""
    field: str
    issue_type: str  # "missing", "out_of_bounds", "stale", "future_skew", "type_error"
    message: str
    severity: str    # "error" (rejects record) or "warning" (flags advisory)


@dataclass
class QualityReport:
    """Summary of data quality evaluation for a single observation record."""
    location_id: str
    is_valid: bool
    status: str      # "PASSED", "WARNING", "REJECTED"
    issues: List[ValidationIssue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        """True if any error-level severity issue was detected."""
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        """True if any warning-level severity issue was detected."""
        return any(i.severity == "warning" for i in self.issues)

    def error_messages(self) -> List[str]:
        """Return list of error descriptions."""
        return [f"{i.field}: {i.message}" for i in self.issues if i.severity == "error"]

    def warning_messages(self) -> List[str]:
        """Return list of warning descriptions."""
        return [f"{i.field}: {i.message}" for i in self.issues if i.severity == "warning"]


class DataQualityChecker:
    """Validates weather observations against physical rules and temporal freshness."""

    def __init__(self, config: Optional[DataQualityConfig] = None):
        self.config = config or get_config().data_quality

    def validate_observation(
        self,
        observation: Dict[str, Any],
        reference_time: Optional[datetime] = None,
    ) -> QualityReport:
        """
        Evaluate an observation dictionary against all data quality rules.
        Returns a QualityReport containing validation status and any identified issues.
        """
        location_id = observation.get("location_id", "unknown")
        issues: List[ValidationIssue] = []
        metrics: Dict[str, Any] = {}

        now_utc = reference_time or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        # -------------------------------------------------------------
        # 1. Critical Required Fields
        # -------------------------------------------------------------
        if not observation.get("location_id"):
            issues.append(
                ValidationIssue(
                    field="location_id",
                    issue_type="missing",
                    message="Location identifier is missing or empty.",
                    severity="error",
                )
            )

        temp_c = observation.get("temperature_c")
        if temp_c is None:
            issues.append(
                ValidationIssue(
                    field="temperature_c",
                    issue_type="missing",
                    message="Temperature measurement is missing (None).",
                    severity="error",
                )
            )

        observed_at = observation.get("observed_at")
        if observed_at is None:
            issues.append(
                ValidationIssue(
                    field="observed_at",
                    issue_type="missing",
                    message="Observation timestamp is missing (None).",
                    severity="error",
                )
            )

        # -------------------------------------------------------------
        # 2. Non-critical Expected Fields
        # -------------------------------------------------------------
        if observation.get("relative_humidity_pct") is None:
            issues.append(
                ValidationIssue(
                    field="relative_humidity_pct",
                    issue_type="missing",
                    message="Relative humidity measurement is missing.",
                    severity="warning",
                )
            )

        if observation.get("wind_speed_kmh") is None:
            issues.append(
                ValidationIssue(
                    field="wind_speed_kmh",
                    issue_type="missing",
                    message="Wind speed measurement is missing.",
                    severity="warning",
                )
            )

        if observation.get("weather_code") is None:
            issues.append(
                ValidationIssue(
                    field="weather_code",
                    issue_type="missing",
                    message="WMO weather code is missing.",
                    severity="warning",
                )
            )

        # -------------------------------------------------------------
        # 3. Physical Boundaries & Sensor Limits
        # -------------------------------------------------------------
        # Temperature Range
        if temp_c is not None:
            try:
                temp_val = float(temp_c)
                metrics["temperature_c"] = temp_val
                if temp_val < self.config.temp_min_c or temp_val > self.config.temp_max_c:
                    issues.append(
                        ValidationIssue(
                            field="temperature_c",
                            issue_type="out_of_bounds",
                            message=(
                                f"Temperature {temp_val:.1f}°C is outside valid physical range "
                                f"[{self.config.temp_min_c}°C, {self.config.temp_max_c}°C]."
                            ),
                            severity="error",
                        )
                    )
            except (ValueError, TypeError):
                issues.append(
                    ValidationIssue(
                        field="temperature_c",
                        issue_type="type_error",
                        message=f"Temperature value '{temp_c}' cannot be parsed as numeric.",
                        severity="error",
                    )
                )

        # Relative Humidity Range
        humidity = observation.get("relative_humidity_pct")
        if humidity is not None:
            try:
                hum_val = float(humidity)
                metrics["relative_humidity_pct"] = hum_val
                if hum_val < self.config.humidity_min_pct or hum_val > self.config.humidity_max_pct:
                    issues.append(
                        ValidationIssue(
                            field="relative_humidity_pct",
                            issue_type="out_of_bounds",
                            message=(
                                f"Relative humidity {hum_val}% is outside valid range [0%, 100%]."
                            ),
                            severity="error",
                        )
                    )
            except (ValueError, TypeError):
                issues.append(
                    ValidationIssue(
                        field="relative_humidity_pct",
                        issue_type="type_error",
                        message=f"Humidity value '{humidity}' cannot be parsed as numeric.",
                        severity="error",
                    )
                )

        # Precipitation / Rain / Showers
        for p_field in ["precipitation_mm", "rain_mm", "showers_mm"]:
            p_val = observation.get(p_field)
            if p_val is not None:
                try:
                    val = float(p_val)
                    metrics[p_field] = val
                    if val < 0.0:
                        issues.append(
                            ValidationIssue(
                                field=p_field,
                                issue_type="out_of_bounds",
                                message=f"{p_field} cannot be negative ({val} mm).",
                                severity="error",
                            )
                        )
                    elif val > self.config.precip_max_mm:
                        issues.append(
                            ValidationIssue(
                                field=p_field,
                                issue_type="out_of_bounds",
                                message=(
                                    f"{p_field} value of {val} mm exceeds extreme threshold "
                                    f"({self.config.precip_max_mm} mm)."
                                ),
                                severity="warning",
                            )
                        )
                except (ValueError, TypeError):
                    issues.append(
                        ValidationIssue(
                            field=p_field,
                            issue_type="type_error",
                            message=f"{p_field} '{p_val}' cannot be parsed as numeric.",
                            severity="error",
                        )
                    )

        # Wind Speed & Gusts
        wind_speed = observation.get("wind_speed_kmh")
        if wind_speed is not None:
            try:
                ws_val = float(wind_speed)
                metrics["wind_speed_kmh"] = ws_val
                if ws_val < 0.0:
                    issues.append(
                        ValidationIssue(
                            field="wind_speed_kmh",
                            issue_type="out_of_bounds",
                            message=f"Wind speed cannot be negative ({ws_val} km/h).",
                            severity="error",
                        )
                    )
                elif ws_val > self.config.wind_max_kmh:
                    issues.append(
                        ValidationIssue(
                            field="wind_speed_kmh",
                            issue_type="out_of_bounds",
                            message=(
                                f"Wind speed {ws_val} km/h exceeds maximum threshold "
                                f"({self.config.wind_max_kmh} km/h)."
                            ),
                            severity="warning",
                        )
                    )
            except (ValueError, TypeError):
                issues.append(
                    ValidationIssue(
                        field="wind_speed_kmh",
                        issue_type="type_error",
                        message=f"Wind speed '{wind_speed}' cannot be parsed as numeric.",
                        severity="error",
                    )
                )

        wind_gusts = observation.get("wind_gusts_kmh")
        if wind_gusts is not None:
            try:
                wg_val = float(wind_gusts)
                metrics["wind_gusts_kmh"] = wg_val
                if wg_val < 0.0:
                    issues.append(
                        ValidationIssue(
                            field="wind_gusts_kmh",
                            issue_type="out_of_bounds",
                            message=f"Wind gusts cannot be negative ({wg_val} km/h).",
                            severity="error",
                        )
                    )
            except (ValueError, TypeError):
                issues.append(
                    ValidationIssue(
                        field="wind_gusts_kmh",
                        issue_type="type_error",
                        message=f"Wind gusts '{wind_gusts}' cannot be parsed as numeric.",
                        severity="error",
                    )
                )

        # Cloud Cover Range
        cloud_cover = observation.get("cloud_cover_pct")
        if cloud_cover is not None:
            try:
                cc_val = float(cloud_cover)
                metrics["cloud_cover_pct"] = cc_val
                if cc_val < 0.0 or cc_val > 100.0:
                    issues.append(
                        ValidationIssue(
                            field="cloud_cover_pct",
                            issue_type="out_of_bounds",
                            message=f"Cloud cover {cc_val}% is outside valid range [0%, 100%].",
                            severity="error",
                        )
                    )
            except (ValueError, TypeError):
                issues.append(
                    ValidationIssue(
                        field="cloud_cover_pct",
                        issue_type="type_error",
                        message=f"Cloud cover '{cloud_cover}' cannot be parsed as numeric.",
                        severity="error",
                    )
                )

        # Weather Code
        w_code = observation.get("weather_code")
        if w_code is not None:
            try:
                code_val = int(w_code)
                metrics["weather_code"] = code_val
                if code_val < 0:
                    issues.append(
                        ValidationIssue(
                            field="weather_code",
                            issue_type="out_of_bounds",
                            message=f"Weather code cannot be negative ({code_val}).",
                            severity="error",
                        )
                    )
            except (ValueError, TypeError):
                issues.append(
                    ValidationIssue(
                        field="weather_code",
                        issue_type="type_error",
                        message=f"Weather code '{w_code}' cannot be parsed as integer.",
                        severity="error",
                    )
                )

        # -------------------------------------------------------------
        # 4. Temporal Staleness & Future Skew
        # -------------------------------------------------------------
        if isinstance(observed_at, datetime):
            # Ensure timezone-aware comparison in UTC
            obs_utc = observed_at.astimezone(timezone.utc) if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
            age_seconds = (now_utc - obs_utc).total_seconds()
            metrics["age_minutes"] = round(age_seconds / 60.0, 1)

            # Check for stale data (e.g., > 180 minutes old)
            max_staleness_sec = self.config.max_staleness_minutes * 60
            if age_seconds > max_staleness_sec:
                issues.append(
                    ValidationIssue(
                        field="observed_at",
                        issue_type="stale",
                        message=(
                            f"Observation is stale ({metrics['age_minutes']} minutes old, "
                            f"threshold is {self.config.max_staleness_minutes} minutes)."
                        ),
                        severity="warning",
                    )
                )

            # Check for timestamps far in the future (> 10 minutes)
            if age_seconds < -self.config.max_future_skew_seconds:
                skew_sec = abs(age_seconds)
                issues.append(
                    ValidationIssue(
                        field="observed_at",
                        issue_type="future_skew",
                        message=(
                            f"Observation timestamp is {skew_sec:.0f} seconds in the future."
                        ),
                        severity="warning",
                    )
                )

        # -------------------------------------------------------------
        # 5. Final Evaluation Decision
        # -------------------------------------------------------------
        has_errors = any(i.severity == "error" for i in issues)
        has_warnings = any(i.severity == "warning" for i in issues)

        if has_errors:
            status = "REJECTED"
            is_valid = False
            logger.warning(
                "Data quality REJECTED for [%s]: %s",
                location_id,
                "; ".join([f"{i.field}: {i.message}" for i in issues if i.severity == "error"]),
            )
        elif has_warnings:
            status = "WARNING"
            is_valid = True
            logger.info(
                "Data quality WARNING for [%s]: %s",
                location_id,
                "; ".join([f"{i.field}: {i.message}" for i in issues if i.severity == "warning"]),
            )
        else:
            status = "PASSED"
            is_valid = True

        return QualityReport(
            location_id=location_id,
            is_valid=is_valid,
            status=status,
            issues=issues,
            metrics=metrics,
        )
