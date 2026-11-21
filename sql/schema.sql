-- UrbanPulseAI Schema Definition
-- Urban Environmental & Weather Intelligence Database

-- 1. Locations Table (Monitored urban stations & coordinates)
CREATE TABLE IF NOT EXISTS locations (
    location_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Weather Observations Table (Time-series weather measurements)
CREATE TABLE IF NOT EXISTS weather_observations (
    observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id TEXT NOT NULL REFERENCES locations(location_id),
    source TEXT NOT NULL DEFAULT 'open-meteo',
    observed_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    temperature_c DOUBLE PRECISION,
    relative_humidity_pct DOUBLE PRECISION,
    precipitation_mm DOUBLE PRECISION,
    rain_mm DOUBLE PRECISION,
    showers_mm DOUBLE PRECISION,
    weather_code INTEGER,
    wind_speed_kmh DOUBLE PRECISION,
    wind_gusts_kmh DOUBLE PRECISION,
    cloud_cover_pct DOUBLE PRECISION,
    data_type TEXT NOT NULL DEFAULT 'live_api',
    raw_payload JSONB NOT NULL,
    CONSTRAINT weather_observations_location_id_source_observed_at_key UNIQUE (location_id, source, observed_at)
);

-- Indexes for efficient querying & time-series retrieval
CREATE INDEX IF NOT EXISTS idx_weather_observations_time ON weather_observations (observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_weather_observations_location_time ON weather_observations (location_id, observed_at DESC);

-- 3. Ingestion Runs Table (Pipeline execution auditing & metrics)
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    locations_requested INTEGER NOT NULL DEFAULT 0,
    locations_succeeded INTEGER NOT NULL DEFAULT 0,
    observations_saved INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

-- 4. Weather Anomalies Table (AI & Statistical Anomaly Alerts)
CREATE TABLE IF NOT EXISTS weather_anomalies (
    anomaly_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id TEXT NOT NULL REFERENCES locations(location_id),
    observed_at TIMESTAMPTZ NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    anomaly_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    risk_score DOUBLE PRECISION NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL DEFAULT '1.0.0',
    observed_value DOUBLE PRECISION,
    baseline_value DOUBLE PRECISION,
    evidence JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    CONSTRAINT uq_weather_anomalies_loc_obs_type_model UNIQUE (location_id, observed_at, anomaly_type, model_name)
);

CREATE INDEX IF NOT EXISTS idx_weather_anomalies_location ON weather_anomalies (location_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_weather_anomalies_detected ON weather_anomalies (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_weather_anomalies_severity ON weather_anomalies (severity, risk_score DESC);

-- 5. Initial Seed for Monitored Hyderabad Locations
INSERT INTO locations (location_id, name, latitude, longitude)
VALUES
    ('hyderabad-central', 'Hyderabad Central', 17.3850, 78.4867),
    ('gachibowli', 'Gachibowli', 17.4401, 78.3489),
    ('secunderabad', 'Secunderabad', 17.4399, 78.4983),
    ('kukatpally', 'Kukatpally', 17.4849, 78.4138),
    ('lb-nagar', 'LB Nagar', 17.3457, 78.5522)
ON CONFLICT (location_id) DO UPDATE
SET name = EXCLUDED.name,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude;

-- 6. Traffic Corridors Table (Monitored urban arterial corridors)
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

-- 7. Route Travel Times Table (Timestamped route travel-time estimates & free-flow)
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

-- 8. Traffic Disruptions Table (Statistical travel-time anomaly alerts)
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

-- 9. Initial Seed for Key Hyderabad Road Corridors
INSERT INTO traffic_corridors (corridor_id, name, origin_location_id, destination_location_id, origin_latitude, origin_longitude, destination_latitude, destination_longitude, via_road, distance_km)
VALUES
    ('gachibowli-central', 'Gachibowli -> Hyderabad Central', 'gachibowli', 'hyderabad-central', 17.4401, 78.3489, 17.3850, 78.4867, 'Old Mumbai Highway / Mehdipatnam', 16.5),
    ('kukatpally-gachibowli', 'Kukatpally -> Gachibowli', 'kukatpally', 'gachibowli', 17.4849, 78.4138, 17.4401, 78.3489, 'HITEC City Main Road', 11.8),
    ('secunderabad-central', 'Secunderabad -> Hyderabad Central', 'secunderabad', 'hyderabad-central', 17.4399, 78.4983, 17.3850, 78.4867, 'Tank Bund Road / Lower Tank Bund', 7.9),
    ('lbnagar-central', 'LB Nagar -> Hyderabad Central', 'lb-nagar', 'hyderabad-central', 17.3457, 78.5522, 17.3850, 78.4867, 'NH 65 / Dilsukhnagar Main Road', 12.3),
    ('secunderabad-kukatpally', 'Secunderabad -> Kukatpally', 'secunderabad', 'kukatpally', 17.4399, 78.4983, 17.4849, 78.4138, 'Balanagar Main Road / Sanath Nagar', 13.5)
ON CONFLICT (corridor_id) DO UPDATE
SET name = EXCLUDED.name,
    origin_latitude = EXCLUDED.origin_latitude,
    origin_longitude = EXCLUDED.origin_longitude,
    destination_latitude = EXCLUDED.destination_latitude,
    destination_longitude = EXCLUDED.destination_longitude,
    via_road = EXCLUDED.via_road,
    distance_km = EXCLUDED.distance_km;

