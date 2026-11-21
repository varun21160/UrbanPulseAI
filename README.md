# UrbanPulseAI

Real-time urban environmental and weather intelligence data pipeline for Hyderabad, India.

---

## Architecture Overview

UrbanPulseAI collects, validates, and archives meteorological observations across key urban hubs in Hyderabad:
- **Hyderabad Central** (`17.3850, 78.4867`)
- **Gachibowli** (`17.4401, 78.3489`)
- **Secunderabad** (`17.4399, 78.4983`)
- **Kukatpally** (`17.4849, 78.4138`)
- **LB Nagar** (`17.3457, 78.5522`)

---

## Project Structure

```text
UrbanPulseAI/
├── .venv/                  # Python virtual environment
├── .env                    # Environment variables (DB credentials, API keys)
├── .env.example            # Environment configuration template
├── .gitignore              # Git ignore rules
├── requirements.txt        # Python package dependencies
├── README.md               # Project documentation
├── test_db.py              # Quick DB connection test script
├── sql/
│   └── schema.sql          # PostgreSQL DDL for locations, weather_observations, ingestion_runs
├── src/
│   ├── __init__.py         # Package initialization
│   ├── config.py           # Configuration loader, scheduler settings, DQ & AD thresholds
│   ├── data_quality.py     # Automated data-quality checks, physical bounds & staleness detection
│   ├── database.py         # PostgreSQL connection management, CRUD, health & anomaly handlers
│   ├── detector.py         # Explainable anomaly detection engine (MAD + Isolation Forest)
│   └── collect_weather.py  # Weather data collection, rate-limited scheduler & unified CLI
├── tests/                  # Automated unit and integration test suite (31 tests)
│   ├── __init__.py
│   ├── fixtures.py         # Explicitly labeled synthetic test fixtures
│   ├── test_collector.py   # Normalization, missing fields & API error tests
│   ├── test_data_quality.py# Data quality boundary and anomaly tests
│   ├── test_database.py    # Duplicate handling & health metrics tests
│   └── test_detector.py    # Insufficient history, MAD, Isolation Forest, leakage & deduplication
└── logs/                   # Rotating collection logs
    └── weather_collector.log
```

---

## Day 3 Features: Explainable Weather Anomaly Detection

1. **Robust Statistical Baselines (Rolling Median + MAD)**:
   - Uses Median Absolute Deviation (MAD) scaled by `1.4826` to obtain robust modified Z-scores resistant to outliers.
   - **Zero/Low Variance Handling**: Applies feature-specific deviation floors (`temp_deviation_floor_c=3.0°C`, `rain_threshold_mm=5.0mm`, `wind_deviation_floor_kmh=15.0km/h`) to prevent division-by-zero or false alarms when readings are identical over a period.
   - **Cold-Start Protection**: Enforces `AD_MIN_HISTORY_OBSERVATIONS=5`. Observations with fewer historical records are safely skipped with transparent reporting; never falsely labeled anomalous due to missing history.

2. **Multivariate Isolation Forest (Unsupervised ML)**:
   - Evaluated as an optional secondary model when sufficient historical records exist (`history >= AD_IFOREST_MIN_SAMPLES=15`).
   - Evaluates multivariate meteorological feature vectors `[temperature, humidity, wind, precipitation]`.
   - Compares ML output against the statistical baseline: records model agreement (`"consensus"` vs `"statistical_only"` vs `"isolation_forest_only"`).
   - Honestly models anomaly likelihood without inventing ground-truth incident labels or fabricated accuracy scores.

3. **Strict Data Leakage Prevention**:
   - Queries historical records strictly with `observed_at < target_observed_at ORDER BY observed_at ASC`.
   - Guaranteed at database query and detector levels: observations are never compared against contemporaneous or future data points.

4. **Auditable Evidence & Deduplication (`weather_anomalies`)**:
   - PostgreSQL table `weather_anomalies` records location, observation timestamp, detection timestamp, anomaly type, severity (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), risk score `[0.0, 1.0]`, model name/version, observed/baseline values, and evidence in JSONB.
   - Deduplication constraint: `UNIQUE (location_id, observed_at, anomaly_type, model_name)` ensures repeat detection runs update in-place without generating duplicate alerts.

---

## Quick Start & CLI Usage

### 1. Activate Environment
```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Launch Streamlit Weather Intelligence Dashboard
```powershell
streamlit run app.py
# Or directly:
streamlit run src/dashboard.py
```

### 3. Verify Database Connection & Tables
```powershell
python src/collect_weather.py --verify-db
```

### 3. Run System Health Report
```powershell
python src/collect_weather.py --health
```

### 4. Detect Weather Anomalies (Day 3)
```powershell
# Via unified collector CLI:
python src/collect_weather.py --detect-anomalies

# Or via dedicated detector module:
python src/detector.py --analyze --limit 50
python src/detector.py --analyze --location Gachibowli
```

### 5. List Recorded Anomalies (Day 3)
```powershell
# Via unified collector CLI:
python src/collect_weather.py --list-anomalies

# Or via dedicated detector module:
python src/detector.py --list --limit 20
```

### 6. Live Ingestion Cycle
```powershell
python src/collect_weather.py
```

### 7. Run Ingestion Scheduler (Every 15 Minutes)
```powershell
python src/collect_weather.py --scheduler
# Or with a custom interval:
python src/collect_weather.py --interval 30
```

---

## Running Automated Tests

Run the complete test suite (31 automated unit and integration tests across 4 test modules):

```powershell
pytest -v
```

All test fixtures are isolated and explicitly labeled as synthetic (`tests/fixtures.py`). Tests cover:
- UTC timestamp normalization (naive ISO, UTC Z, timezone offsets)
- Missing field handling and invalid API payloads
- HTTP 500, HTTP 429 rate limit backoff, and timeout handling
- Physical boundary checks (temperature, humidity, wind, precipitation)
- Staleness and future timestamp skew detection
- Duplicate-safe database writes and historical preservation
- Health metrics data aggregation
- Insufficient history safe handling (0 false alarms)
- Normal observation baseline verification
- Temperature spikes and sudden temperature drops
- Extreme precipitation and high wind / gust detection
- Zero-variance safety and missing feature robustness
- Strict prevention of future-data leakage
- Isolation Forest multivariate integration and model agreement
- Database deduplication on `weather_anomalies`

