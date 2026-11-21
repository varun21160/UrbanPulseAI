"""
UrbanPulseAI - Configuration Module
Loads environment variables and provides structured application configuration.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dotenv import load_dotenv

# Resolve project base directory and load .env file
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)


@dataclass(frozen=True)
class LocationInfo:
    """Metadata for a monitored urban geographic location."""
    location_id: str
    name: str
    latitude: float
    longitude: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "location_id": self.location_id,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


# Monitored locations in Hyderabad as specified in project requirements
HYDERABAD_LOCATIONS: List[LocationInfo] = [
    LocationInfo(
        location_id="hyderabad-central",
        name="Hyderabad Central",
        latitude=17.3850,
        longitude=78.4867,
    ),
    LocationInfo(
        location_id="gachibowli",
        name="Gachibowli",
        latitude=17.4401,
        longitude=78.3489,
    ),
    LocationInfo(
        location_id="secunderabad",
        name="Secunderabad",
        latitude=17.4399,
        longitude=78.4983,
    ),
    LocationInfo(
        location_id="kukatpally",
        name="Kukatpally",
        latitude=17.4849,
        longitude=78.4138,
    ),
    LocationInfo(
        location_id="lb-nagar",
        name="LB Nagar",
        latitude=17.3457,
        longitude=78.5522,
    ),
]


@dataclass(frozen=True)
class CorridorInfo:
    """Metadata for a monitored urban road corridor."""
    corridor_id: str
    name: str
    origin_location_id: str
    destination_location_id: str
    origin_latitude: float
    origin_longitude: float
    destination_latitude: float
    destination_longitude: float
    via_road: str
    distance_km: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "corridor_id": self.corridor_id,
            "name": self.name,
            "origin_location_id": self.origin_location_id,
            "destination_location_id": self.destination_location_id,
            "origin_latitude": self.origin_latitude,
            "origin_longitude": self.origin_longitude,
            "destination_latitude": self.destination_latitude,
            "destination_longitude": self.destination_longitude,
            "via_road": self.via_road,
            "distance_km": self.distance_km,
        }


# Monitored key traffic arterial corridors connecting Hyderabad urban hubs
HYDERABAD_CORRIDORS: List[CorridorInfo] = [
    CorridorInfo(
        corridor_id="gachibowli-central",
        name="Gachibowli -> Hyderabad Central",
        origin_location_id="gachibowli",
        destination_location_id="hyderabad-central",
        origin_latitude=17.4401,
        origin_longitude=78.3489,
        destination_latitude=17.3850,
        destination_longitude=78.4867,
        via_road="Old Mumbai Highway / Mehdipatnam",
        distance_km=16.5,
    ),
    CorridorInfo(
        corridor_id="kukatpally-gachibowli",
        name="Kukatpally -> Gachibowli",
        origin_location_id="kukatpally",
        destination_location_id="gachibowli",
        origin_latitude=17.4849,
        origin_longitude=78.4138,
        destination_latitude=17.4401,
        destination_longitude=78.3489,
        via_road="HITEC City Main Road",
        distance_km=11.8,
    ),
    CorridorInfo(
        corridor_id="secunderabad-central",
        name="Secunderabad -> Hyderabad Central",
        origin_location_id="secunderabad",
        destination_location_id="hyderabad-central",
        origin_latitude=17.4399,
        origin_longitude=78.4983,
        destination_latitude=17.3850,
        destination_longitude=78.4867,
        via_road="Tank Bund Road / Lower Tank Bund",
        distance_km=7.9,
    ),
    CorridorInfo(
        corridor_id="lbnagar-central",
        name="LB Nagar -> Hyderabad Central",
        origin_location_id="lb-nagar",
        destination_location_id="hyderabad-central",
        origin_latitude=17.3457,
        origin_longitude=78.5522,
        destination_latitude=17.3850,
        destination_longitude=78.4867,
        via_road="NH 65 / Dilsukhnagar Main Road",
        distance_km=12.3,
    ),
    CorridorInfo(
        corridor_id="secunderabad-kukatpally",
        name="Secunderabad -> Kukatpally",
        origin_location_id="secunderabad",
        destination_location_id="kukatpally",
        origin_latitude=17.4399,
        origin_longitude=78.4983,
        destination_latitude=17.4849,
        destination_longitude=78.4138,
        via_road="Balanagar Main Road / Sanath Nagar",
        distance_km=13.5,
    ),
]


@dataclass
class DatabaseConfig:
    """PostgreSQL database connection settings."""
    host: str = field(default_factory=lambda: os.getenv("DB_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("DB_PORT", "5432")))
    name: str = field(default_factory=lambda: os.getenv("DB_NAME", "urbanpulse_db"))
    user: str = field(default_factory=lambda: os.getenv("DB_USER", "postgres"))
    password: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", ""))
    database_url: Optional[str] = field(default_factory=lambda: os.getenv("DATABASE_URL"))

    @property
    def connection_params(self) -> Dict[str, Any]:
        """Return parameters dictionary for psycopg.connect."""
        if self.host and self.user:
            return {
                "host": self.host,
                "port": self.port,
                "dbname": self.name,
                "user": self.user,
                "password": self.password,
            }
        if self.database_url:
            return {"conninfo": self.database_url}
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.name,
            "user": self.user,
            "password": self.password,
        }

    @property
    def connection_uri(self) -> str:
        """Return the PostgreSQL connection string."""
        if self.database_url:
            return self.database_url
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


@dataclass
class WeatherConfig:
    """Weather API configuration settings."""
    api_url: str = field(
        default_factory=lambda: os.getenv(
            "OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast"
        )
    )
    provider: str = field(
        default_factory=lambda: os.getenv("WEATHER_PROVIDER", "open-meteo").lower()
    )
    timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
    )
    # Required current variables per Day 1 specifications
    current_variables: List[str] = field(
        default_factory=lambda: [
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "rain",
            "showers",
            "weather_code",
            "wind_speed_10m",
            "wind_gusts_10m",
            "cloud_cover",
        ]
    )


@dataclass
class SchedulerConfig:
    """Scheduler and API rate-limiting configuration."""
    interval_minutes: int = field(
        default_factory=lambda: int(os.getenv("COLLECTION_INTERVAL_MINUTES", "15"))
    )
    rate_limit_delay_seconds: float = field(
        default_factory=lambda: float(os.getenv("API_RATE_LIMIT_DELAY_SECONDS", "0.5"))
    )
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("API_MAX_RETRIES", "3"))
    )
    backoff_factor: float = field(
        default_factory=lambda: float(os.getenv("API_BACKOFF_FACTOR", "1.0"))
    )


@dataclass
class DataQualityConfig:
    """Thresholds and rules for automated observation data quality checks."""
    temp_min_c: float = field(
        default_factory=lambda: float(os.getenv("DQ_TEMP_MIN_C", "-10.0"))
    )
    temp_max_c: float = field(
        default_factory=lambda: float(os.getenv("DQ_TEMP_MAX_C", "60.0"))
    )
    humidity_min_pct: float = field(
        default_factory=lambda: float(os.getenv("DQ_HUMIDITY_MIN_PCT", "0.0"))
    )
    humidity_max_pct: float = field(
        default_factory=lambda: float(os.getenv("DQ_HUMIDITY_MAX_PCT", "100.0"))
    )
    wind_max_kmh: float = field(
        default_factory=lambda: float(os.getenv("DQ_WIND_MAX_KMH", "300.0"))
    )
    precip_max_mm: float = field(
        default_factory=lambda: float(os.getenv("DQ_PRECIP_MAX_MM", "500.0"))
    )
    max_staleness_minutes: int = field(
        default_factory=lambda: int(os.getenv("MAX_OBSERVATION_STALENESS_MINUTES", "180"))
    )
    max_future_skew_seconds: int = field(
        default_factory=lambda: int(os.getenv("MAX_FUTURE_SKEW_SECONDS", "600"))
    )


@dataclass
class AnomalyDetectionConfig:
    """Settings and thresholds for statistical and machine-learning anomaly detection."""
    min_history_observations: int = field(
        default_factory=lambda: int(os.getenv("AD_MIN_HISTORY_OBSERVATIONS", "5"))
    )
    mad_threshold_moderate: float = field(
        default_factory=lambda: float(os.getenv("AD_MAD_THRESHOLD_MODERATE", "2.5"))
    )
    mad_threshold_severe: float = field(
        default_factory=lambda: float(os.getenv("AD_MAD_THRESHOLD_SEVERE", "3.5"))
    )
    mad_threshold_critical: float = field(
        default_factory=lambda: float(os.getenv("AD_MAD_THRESHOLD_CRITICAL", "5.0"))
    )
    temp_deviation_floor_c: float = field(
        default_factory=lambda: float(os.getenv("AD_TEMP_DEVIATION_FLOOR_C", "3.0"))
    )
    rain_threshold_mm: float = field(
        default_factory=lambda: float(os.getenv("AD_RAIN_THRESHOLD_MM", "5.0"))
    )
    wind_deviation_floor_kmh: float = field(
        default_factory=lambda: float(os.getenv("AD_WIND_DEVIATION_FLOOR_KMH", "15.0"))
    )
    wind_gust_threshold_kmh: float = field(
        default_factory=lambda: float(os.getenv("AD_WIND_GUST_THRESHOLD_KMH", "40.0"))
    )
    isolation_forest_min_samples: int = field(
        default_factory=lambda: int(os.getenv("AD_IFOREST_MIN_SAMPLES", "15"))
    )
    isolation_forest_contamination: Union[str, float] = field(
        default_factory=lambda: (
            float(os.getenv("AD_IFOREST_CONTAMINATION"))
            if os.getenv("AD_IFOREST_CONTAMINATION", "auto") != "auto"
            and os.getenv("AD_IFOREST_CONTAMINATION", "auto").replace(".", "", 1).isdigit()
            else "auto"
        )
    )
    model_version: str = field(
        default_factory=lambda: os.getenv("AD_MODEL_VERSION", "1.0.0")
    )


@dataclass
class LogConfig:
    """Logging configuration settings."""
    level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    file_path: Path = field(
        default_factory=lambda: BASE_DIR / os.getenv("LOG_FILE", "logs/weather_collector.log")
    )


@dataclass
class TrafficConfig:
    """Traffic API & disruption detection configuration."""
    provider: str = field(
        default_factory=lambda: os.getenv("TRAFFIC_PROVIDER", "tomtom").lower()
    )
    api_key: str = field(
        default_factory=lambda: os.getenv("TOMTOM_API_KEY", "").strip()
    )
    routing_url: str = field(
        default_factory=lambda: os.getenv(
            "TOMTOM_ROUTING_URL", "https://api.tomtom.com/routing/1/calculateRoute"
        )
    )
    traffic_flow_url: str = field(
        default_factory=lambda: os.getenv(
            "TOMTOM_FLOW_URL", "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
        )
    )
    timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("TRAFFIC_REQUEST_TIMEOUT_SECONDS", "15"))
    )
    rate_limit_delay_seconds: float = field(
        default_factory=lambda: float(os.getenv("TRAFFIC_RATE_LIMIT_DELAY_SECONDS", "0.5"))
    )
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("TRAFFIC_MAX_RETRIES", "3"))
    )
    backoff_factor: float = field(
        default_factory=lambda: float(os.getenv("TRAFFIC_BACKOFF_FACTOR", "1.0"))
    )
    # Anomaly baseline settings for traffic corridors
    min_history_observations: int = field(
        default_factory=lambda: int(os.getenv("TRAFFIC_MIN_HISTORY_OBSERVATIONS", "5"))
    )
    mad_threshold_moderate: float = field(
        default_factory=lambda: float(os.getenv("TRAFFIC_MAD_THRESHOLD_MODERATE", "2.0"))
    )
    mad_threshold_severe: float = field(
        default_factory=lambda: float(os.getenv("TRAFFIC_MAD_THRESHOLD_SEVERE", "3.0"))
    )
    mad_threshold_critical: float = field(
        default_factory=lambda: float(os.getenv("TRAFFIC_MAD_THRESHOLD_CRITICAL", "4.5"))
    )
    min_deviation_seconds: float = field(
        default_factory=lambda: float(os.getenv("TRAFFIC_MIN_DEVIATION_SECONDS", "180.0"))
    )
    congestion_ratio_moderate: float = field(
        default_factory=lambda: float(os.getenv("TRAFFIC_CONGESTION_RATIO_MODERATE", "1.3"))
    )
    congestion_ratio_severe: float = field(
        default_factory=lambda: float(os.getenv("TRAFFIC_CONGESTION_RATIO_SEVERE", "1.6"))
    )
    congestion_ratio_critical: float = field(
        default_factory=lambda: float(os.getenv("TRAFFIC_CONGESTION_RATIO_CRITICAL", "2.0"))
    )
    model_version: str = field(
        default_factory=lambda: os.getenv("TRAFFIC_MODEL_VERSION", "1.0.0")
    )

    @property
    def is_configured(self) -> bool:
        """Check if an actual API key is present."""
        return bool(self.api_key and len(self.api_key) > 5)


@dataclass
class AppConfig:
    """Root configuration holding database, weather, traffic, locations, corridors, scheduler, DQ, AD and logging settings."""
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    weather: WeatherConfig = field(default_factory=WeatherConfig)
    traffic: TrafficConfig = field(default_factory=TrafficConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    data_quality: DataQualityConfig = field(default_factory=DataQualityConfig)
    anomaly_detection: AnomalyDetectionConfig = field(default_factory=AnomalyDetectionConfig)
    logging: LogConfig = field(default_factory=LogConfig)
    locations: List[LocationInfo] = field(default_factory=lambda: list(HYDERABAD_LOCATIONS))
    corridors: List[CorridorInfo] = field(default_factory=lambda: list(HYDERABAD_CORRIDORS))
    base_dir: Path = BASE_DIR


def get_config() -> AppConfig:
    """Get initialized application configuration."""
    return AppConfig()



