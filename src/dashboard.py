"""
UrbanPulse AI - Enterprise Weather Intelligence Dashboard
Production-grade meteorological analytics and anomaly monitoring for urban Hyderabad.
Built with Streamlit, Plotly, and OpenStreetMap (Folium).
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Ensure project root and .venv site-packages are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

venv_site_packages = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"
if venv_site_packages.exists() and str(venv_site_packages) not in sys.path:
    sys.path.insert(0, str(venv_site_packages))

import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from src.config import HYDERABAD_LOCATIONS, get_config
from src.database import DatabaseManager
from src.collect_weather import get_weather_description, run_pipeline
from src.detector import WeatherAnomalyDetector
from src.collect_traffic import TrafficCollector
from src.detector_traffic import TrafficDisruptionDetector

# -----------------------------------------------------------------------------
# 1. Page Configuration & Theme
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="UrbanPulse AI | Hyderabad Weather Intelligence",
    page_icon="🏙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Clean, production-style enterprise dark theme styling (refined slate palette, not AI neon)
ENTERPRISE_DARK_CSS = """
<style>
    /* Professional typography */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: #F8FAFC;
        background-color: #0A0E17;
    }

    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2.5rem;
        padding-left: 2rem;
        padding-right: 2rem;
        max-width: 1440px;
    }

    /* Enterprise Dark Header */
    .app-header {
        background-color: #111827;
        border: 1px solid #1E293B;
        border-top: 3px solid #3B82F6;
        border-radius: 8px;
        padding: 18px 24px;
        margin-bottom: 16px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.4), 0 2px 4px -2px rgba(0, 0, 0, 0.3);
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 12px;
    }

    .app-title {
        font-size: 1.5rem;
        font-weight: 700;
        color: #F8FAFC;
        letter-spacing: -0.02em;
        margin: 0;
        line-height: 1.2;
    }

    .app-subtitle {
        font-size: 0.88rem;
        color: #94A3B8;
        margin-top: 4px;
        margin-bottom: 0;
    }

    /* Source Health Bar */
    .health-bar {
        background-color: #111827;
        border: 1px solid #1E293B;
        border-radius: 8px;
        padding: 12px 20px;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 16px;
        font-size: 0.82rem;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.3);
    }

    .health-item {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .health-item-label {
        font-size: 0.72rem;
        font-weight: 600;
        color: #94A3B8;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .health-item-val {
        font-size: 0.88rem;
        font-weight: 600;
        color: #F8FAFC;
    }

    /* Enterprise Dark KPI Cards */
    .metric-card {
        background-color: #111827;
        border: 1px solid #1E293B;
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 2px 4px 0 rgba(0, 0, 0, 0.3);
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        transition: border-color 0.2s ease, transform 0.2s ease;
    }

    .metric-card:hover {
        border-color: #334155;
    }

    .metric-title {
        font-size: 0.75rem;
        font-weight: 600;
        color: #94A3B8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 6px;
    }

    .metric-value {
        font-size: 1.75rem;
        font-weight: 700;
        color: #F8FAFC;
        letter-spacing: -0.02em;
        line-height: 1.1;
    }

    .metric-unit {
        font-size: 0.95rem;
        font-weight: 500;
        color: #64748B;
        margin-left: 2px;
    }

    .metric-subtext {
        font-size: 0.78rem;
        color: #94A3B8;
        margin-top: 6px;
        display: flex;
        align-items: center;
        gap: 4px;
    }

    /* Status Badges - Deep Dark Enterprise */
    .badge {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.02em;
    }

    .badge-success {
        background-color: #064E3B;
        color: #34D399;
        border: 1px solid #059669;
    }

    .badge-warning {
        background-color: #451A03;
        color: #FBBF24;
        border: 1px solid #B45309;
    }

    .badge-danger {
        background-color: #450A0A;
        color: #F87171;
        border: 1px solid #B91C1C;
    }

    .badge-info {
        background-color: #172554;
        color: #93C5FD;
        border: 1px solid #1D4ED8;
    }

    /* Station Details Card */
    .station-panel {
        background-color: #111827;
        border: 1px solid #1E293B;
        border-radius: 8px;
        padding: 16px 18px;
        margin-bottom: 10px;
        transition: background-color 0.15s ease, border-color 0.15s ease;
    }

    .station-panel-active {
        border-left: 3px solid #3B82F6;
        background-color: #1E293B;
        border-color: #3B82F6;
    }

    /* Technical Notice Banner */
    .tech-notice {
        background-color: #111827;
        border: 1px solid #1E293B;
        border-left: 3px solid #3B82F6;
        border-radius: 6px;
        padding: 10px 14px;
        font-size: 0.8rem;
        color: #94A3B8;
        margin-bottom: 16px;
        line-height: 1.45;
    }

    /* Leaflet OpenStreetMap Dark Frame & Popup Overrides */
    .leaflet-popup-content-wrapper, .leaflet-popup-tip {
        background: #111827 !important;
        color: #F8FAFC !important;
        border: 1px solid #334155 !important;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.7) !important;
    }

    .leaflet-container {
        border-radius: 8px !important;
        border: 1px solid #1E293B !important;
        background: #0B0F19 !important;
    }

    /* Streamlit component dark overrides */
    div[data-testid="stMetricValue"] {
        color: #F8FAFC !important;
        font-family: 'Inter', sans-serif !important;
    }

    div[data-testid="stMetricLabel"] {
        color: #94A3B8 !important;
    }

    /* Tabs styling */
    div[data-testid="stTabs"] button {
        color: #94A3B8 !important;
        font-weight: 500 !important;
    }

    div[data-testid="stTabs"] button[aria-selected="true"] {
        color: #60A5FA !important;
        border-bottom-color: #3B82F6 !important;
        font-weight: 600 !important;
    }

    /* Dataframe styling */
    .stDataFrame {
        border: 1px solid #1E293B;
        border-radius: 6px;
        background: #111827;
    }
</style>
"""
st.markdown(ENTERPRISE_DARK_CSS, unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 2. Cached Database Data Access Layer
# -----------------------------------------------------------------------------
@st.cache_resource
def get_db_manager() -> DatabaseManager:
    """Retrieve shared DatabaseManager instance."""
    config = get_config()
    return DatabaseManager(config.db)


@st.cache_data(ttl=25, show_spinner=False)
def load_all_locations() -> List[Dict[str, Any]]:
    """Fetch all monitored urban locations."""
    try:
        db = get_db_manager()
        return db.get_all_locations()
    except Exception as e:
        return [loc.to_dict() for loc in HYDERABAD_LOCATIONS]


@st.cache_data(ttl=20, show_spinner=False)
def load_latest_observations() -> List[Dict[str, Any]]:
    """Fetch the latest observation for each location."""
    try:
        db = get_db_manager()
        return db.get_latest_observations()
    except Exception:
        return []


@st.cache_data(ttl=25, show_spinner=False)
def load_historical_series(
    location_id: Optional[str] = None,
    limit: int = 500,
) -> pd.DataFrame:
    """
    Fetch chronological time-series observations from PostgreSQL.
    Returns clean pandas DataFrame with parsed UTC and IST datetimes.
    """
    try:
        db = get_db_manager()
        records = db.get_location_history_series(location_id=location_id, limit=limit)
    except Exception:
        records = []
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if "observed_at" in df.columns:
        df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
        # Indian Standard Time (UTC+5:30)
        df["observed_at_ist"] = df["observed_at"].dt.tz_convert("Asia/Kolkata")
        df["observed_at_utc_str"] = df["observed_at"].dt.strftime("%Y-%m-%d %H:%M UTC")
        df["observed_at_ist_str"] = df["observed_at_ist"].dt.strftime("%Y-%m-%d %H:%M IST")
    return df


@st.cache_data(ttl=20, show_spinner=False)
def load_anomalies(
    location_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Fetch recorded weather anomalies from database."""
    try:
        db = get_db_manager()
        return db.get_recent_anomalies(limit=limit, location_id=location_id)
    except Exception:
        return []


@st.cache_data(ttl=25, show_spinner=False)
def load_system_health() -> Dict[str, Any]:
    """Fetch overall ingestion and system health metrics."""
    try:
        db = get_db_manager()
        return db.get_health_metrics()
    except Exception:
        return {}


@st.cache_data(ttl=25, show_spinner=False)
def load_recent_runs(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch recent ingestion run audit records."""
    try:
        db = get_db_manager()
        return db.get_recent_ingestion_runs(limit=limit)
    except Exception:
        return []


@st.cache_data(ttl=25, show_spinner=False)
def load_all_corridors() -> List[Dict[str, Any]]:
    """Fetch all monitored Hyderabad road corridors."""
    try:
        db = get_db_manager()
        db.init_traffic_tables()
        return db.get_all_corridors()
    except Exception:
        return [c.to_dict() for c in get_config().corridors]


@st.cache_data(ttl=20, show_spinner=False)
def load_latest_traffic() -> List[Dict[str, Any]]:
    """Fetch latest travel time estimates for each corridor."""
    try:
        db = get_db_manager()
        db.init_traffic_tables()
        return db.get_latest_corridor_travel_times()
    except Exception:
        return []


@st.cache_data(ttl=25, show_spinner=False)
def load_traffic_history(route_id: Optional[str] = None, limit: int = 500) -> pd.DataFrame:
    """Fetch historical corridor travel time observations."""
    try:
        db = get_db_manager()
        db.init_traffic_tables()
        records = db.get_corridor_travel_time_history(route_id=route_id, limit=limit)
    except Exception:
        records = []
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if "observed_at" in df.columns:
        df["observed_at"] = pd.to_datetime(df["observed_at"], utc=True)
        df["observed_at_ist"] = df["observed_at"].dt.tz_convert("Asia/Kolkata")
        df["observed_at_utc_str"] = df["observed_at"].dt.strftime("%Y-%m-%d %H:%M UTC")
        df["observed_at_ist_str"] = df["observed_at_ist"].dt.strftime("%Y-%m-%d %H:%M IST")
    return df


@st.cache_data(ttl=20, show_spinner=False)
def load_traffic_disruptions(route_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch recorded traffic disruptions from database."""
    try:
        db = get_db_manager()
        db.init_traffic_tables()
        return db.get_recent_traffic_disruptions(limit=limit, route_id=route_id)
    except Exception:
        return []


# -----------------------------------------------------------------------------
# 3. Sidebar Controls & Real-Time Actions
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Controls & Filters")

    # Location Filter
    locations_list = load_all_locations()
    location_options = {"all": "All Monitored Locations (5)"}
    for loc in locations_list:
        location_options[loc["location_id"]] = loc["name"]

    selected_loc_id = st.selectbox(
        "Station Filter",
        options=list(location_options.keys()),
        format_func=lambda k: location_options[k],
        index=0,
        help="Select a specific station to filter time-series charts and observations.",
    )

    # Time Horizon Filter
    time_horizon_options = {
        "6h": "Last 6 Hours",
        "12h": "Last 12 Hours",
        "24h": "Last 24 Hours",
        "3d": "Last 3 Days",
        "all": "All Recorded History",
    }
    selected_horizon = st.selectbox(
        "Time Range",
        options=list(time_horizon_options.keys()),
        format_func=lambda k: time_horizon_options[k],
        index=2,
    )

    st.markdown("---")
    st.markdown("#### Refresh Settings")

    col_btn, col_spin = st.columns([1, 1])
    with col_btn:
        if st.button("Refresh", width="stretch"):
            st.cache_data.clear()
            st.rerun()

    auto_refresh = st.checkbox("Auto-refresh", value=False)
    refresh_seconds = 30
    if auto_refresh:
        refresh_seconds = st.slider("Interval (seconds)", 15, 300, 30, step=15)
        st.caption(f"Polling interval: {refresh_seconds}s")

    st.markdown("---")
    st.markdown("#### Ingestion & Anomaly Actions")

    if st.button("Run Live Ingestion Cycle", width="stretch", help="Fetch latest Open-Meteo readings"):
        with st.spinner("Ingesting observations..."):
            try:
                success = run_pipeline()
                st.cache_data.clear()
                if success:
                    st.success("Ingestion cycle complete.")
                else:
                    st.warning("Ingestion finished with warnings.")
                st.rerun()
            except Exception as e:
                st.error(f"Ingestion failed: {e}")

    if st.button("Evaluate Anomaly Baselines", width="stretch", help="Run MAD & Isolation Forest detection"):
        with st.spinner("Analyzing observations..."):
            try:
                detector = WeatherAnomalyDetector()
                summary = detector.analyze_recent_observations(
                    location_id=None if selected_loc_id == "all" else selected_loc_id,
                    limit=50,
                )
                st.cache_data.clear()
                if summary.alerts:
                    st.warning(f"Detected {len(summary.alerts)} anomaly alert(s).")
                else:
                    st.info("No anomalies detected across recent observations.")
                st.rerun()
            except Exception as e:
                st.error(f"Detection failed: {e}")

    st.markdown("---")
    st.markdown("#### Traffic Disruption Intelligence")
    _sidebar_config = get_config()
    traffic_collector = TrafficCollector(_sidebar_config)
    traffic_status_info = traffic_collector.get_status_info()
    if traffic_status_info["configured"]:
        st.markdown('<span class="badge badge-success">TomTom API: Active</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge badge-warning">TomTom API: Disabled (No Key)</span>', unsafe_allow_html=True)

    if st.button("Poll TomTom Traffic", width="stretch", help="Query TomTom routing for Hyderabad corridors"):
        with st.spinner("Polling corridor travel times..."):
            try:
                res = traffic_collector.run_collection_cycle(get_db_manager())
                st.cache_data.clear()
                if res["status"] == "success":
                    st.success(f"Traffic polled: {res['saved']} corridors saved.")
                elif res["status"] == "disabled":
                    st.warning("Traffic API key missing. Polling paused (no data fabricated).")
                else:
                    st.warning(f"Traffic polling status: {res['status']}.")
                st.rerun()
            except Exception as e:
                st.error(f"Traffic collection failed: {e}")

    if st.button("Evaluate Traffic Baselines", width="stretch", help="Run MAD anomaly detection on corridor history"):
        with st.spinner("Evaluating corridor travel times..."):
            try:
                detector = TrafficDisruptionDetector(_sidebar_config)
                alerts = detector.analyze_db_observations(get_db_manager())
                st.cache_data.clear()
                if alerts:
                    st.warning(f"Detected {len(alerts)} traffic disruption(s).")
                else:
                    st.info("No traffic disruptions detected across corridor observations.")
                st.rerun()
            except Exception as e:
                st.error(f"Traffic evaluation failed: {e}")

    st.markdown("---")
    st.markdown(
        "<div style='font-size:0.75rem; color:#64748B;'>"
        "<b>UrbanPulse AI</b> v1.0.0<br>"
        "PostgreSQL • Open-Meteo & TomTom<br>"
        "Hyderabad Urban Analytics"
        "</div>",
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# 4. Header & Source Health Section (Requirement 3 & 4)
# -----------------------------------------------------------------------------
# Fetch database state
health_metrics = load_system_health()
latest_run = health_metrics.get("latest_run") or {}
historical_stats = health_metrics.get("historical_stats") or {}
latest_obs_list = load_latest_observations()
active_records = [r for r in latest_obs_list if r.get("observation_id") is not None]
if not active_records:
    # Fallback to configured locations when DB has no observations or is connecting
    active_records = [
        {
            "location_id": loc["location_id"],
            "location_name": loc["name"],
            "latitude": loc["latitude"],
            "longitude": loc["longitude"],
            "temperature_c": "--",
            "relative_humidity_pct": "--",
            "wind_speed_kmh": "--",
            "precipitation_mm": 0.0,
            "weather_code": 0,
        }
        for loc in load_all_locations()
    ]

# Determine timestamps
now_utc = datetime.now(timezone.utc)
ui_render_time_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

# 1. Ingestion finished / started time
run_status = latest_run.get("status", "READY").upper()
run_time_utc_str = "None"
run_time_ist_str = "None"
if latest_run.get("finished_at") or latest_run.get("started_at"):
    r_time = latest_run.get("finished_at") or latest_run.get("started_at")
    if isinstance(r_time, datetime):
        r_utc = r_time if r_time.tzinfo else r_time.replace(tzinfo=timezone.utc)
        run_time_utc_str = r_utc.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        run_time_ist_str = r_utc.astimezone(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%H:%M IST")

# 2. Latest observation timestamp across active records
latest_obs_time: Optional[datetime] = None
for r in active_records:
    if r.get("observed_at"):
        t = r["observed_at"] if isinstance(r["observed_at"], datetime) else datetime.fromisoformat(str(r["observed_at"]))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        else:
            t = t.astimezone(timezone.utc)
        if latest_obs_time is None or t > latest_obs_time:
            latest_obs_time = t

obs_time_utc_str = latest_obs_time.strftime("%Y-%m-%d %H:%M UTC") if latest_obs_time else "No records"
obs_time_ist_str = (
    latest_obs_time.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%H:%M IST")
    if latest_obs_time else "N/A"
)

# 3. Data Freshness calculation
age_minutes = round((now_utc - latest_obs_time).total_seconds() / 60, 1) if latest_obs_time else None
staleness_threshold = get_config().data_quality.max_staleness_minutes
is_stale = (age_minutes is not None and age_minutes > staleness_threshold)

# Render Application Header
st.markdown(
    """
    <div class="app-header">
        <div>
            <h1 class="app-title">UrbanPulse AI</h1>
            <p class="app-subtitle">Hyderabad Urban Environmental Intelligence & Meteorological Analytics</p>
        </div>
        <div style="text-align:right;">
            <span class="badge badge-info" style="font-size:0.78rem;">5 Monitored Urban Hubs</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Compact Source-Health Section
run_badge_class = "badge-success" if run_status in ("SUCCESS", "COMPLETED") else ("badge-warning" if run_status == "PARTIAL" else "badge-danger")
freshness_badge_class = "badge-danger" if is_stale else ("badge-success" if age_minutes is not None else "badge-warning")
freshness_label = f"Stale ({age_minutes:.0f}m ago)" if is_stale else (f"Fresh ({age_minutes:.0f}m ago)" if age_minutes is not None else "No data")

st.markdown(
    f"""
    <div class="health-bar">
        <div class="health-item">
            <span class="health-item-label">Ingestion Run Status</span>
            <span class="health-item-val">
                <span class="badge {run_badge_class}">{run_status}</span>
                <span style="font-size:0.8rem; color:#64748B; margin-left:4px;">Run #{latest_run.get('run_id', 'N/A')}</span>
            </span>
        </div>
        <div class="health-item">
            <span class="health-item-label">Last Ingestion Time</span>
            <span class="health-item-val">{run_time_utc_str} <span style="font-size:0.78rem; color:#64748B;">({run_time_ist_str})</span></span>
        </div>
        <div class="health-item">
            <span class="health-item-label">Latest Observation</span>
            <span class="health-item-val">{obs_time_utc_str} <span style="font-size:0.78rem; color:#64748B;">({obs_time_ist_str})</span></span>
        </div>
        <div class="health-item">
            <span class="health-item-label">Source Freshness</span>
            <span class="health-item-val"><span class="badge {freshness_badge_class}">{freshness_label}</span></span>
        </div>
        <div class="health-item">
            <span class="health-item-label">Dashboard Rendered</span>
            <span class="health-item-val" style="font-family:'JetBrains Mono', monospace; font-size:0.8rem; color:#64748B;">{ui_render_time_str}</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Context Notice (Requirement 4 & 8)
st.markdown(
    """
    <div class="tech-notice">
        <b>Data Credibility Notice:</b> Meteorological variables are ingested directly from Open-Meteo.
        Anomaly alerts are computed relative to historical rolling baselines (Median Absolute Deviation and Isolation Forest).
        <i>Weather anomalies identify statistical departures in atmospheric measurements and do NOT constitute confirmed traffic accidents or street disruptions.</i>
    </div>
    """,
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# 5. Compact KPI Cards Row (Requirement 3 & 4)
# -----------------------------------------------------------------------------
# Filter latest observations by selected location if applicable
filtered_latest = active_records
if selected_loc_id != "all":
    filtered_latest = [r for r in active_records if r.get("location_id") == selected_loc_id]

# Query real anomalies
anomalies_list = load_anomalies(location_id=None if selected_loc_id == "all" else selected_loc_id, limit=100)
active_anomalies_count = len([a for a in anomalies_list if a.get("status") == "active"])

# Compute actual statistics
if filtered_latest:
    temps = [float(r["temperature_c"]) for r in filtered_latest if r.get("temperature_c") is not None]
    rains = [
        float(r["precipitation_mm"] if r.get("precipitation_mm") is not None else r["rain_mm"])
        for r in filtered_latest
        if r.get("precipitation_mm") is not None or r.get("rain_mm") is not None
    ]
    winds = [float(r["wind_speed_kmh"]) for r in filtered_latest if r.get("wind_speed_kmh") is not None]
    gusts = [float(r["wind_gusts_kmh"]) for r in filtered_latest if r.get("wind_gusts_kmh") is not None]

    mean_temp = sum(temps) / len(temps) if temps else 0.0
    min_temp, max_temp = (min(temps), max(temps)) if temps else (0.0, 0.0)
    current_rain = max(rains) if rains else None
    mean_wind = sum(winds) / len(winds) if winds else 0.0
    max_gust = max(gusts) if gusts else 0.0
else:
    mean_temp, min_temp, max_temp = (0.0, 0.0, 0.0)
    current_rain = None
    mean_wind, max_gust = (0.0, 0.0)

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)

with kpi1:
    loc_count = len(filtered_latest)
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">Monitored Locations</div>
            <div class="metric-value">{loc_count}<span class="metric-unit">stations</span></div>
            <div class="metric-subtext">{'All 5 Hyderabad stations' if selected_loc_id == 'all' else 'Filtered station'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with kpi2:
    range_text = f"Range: {min_temp:.1f}° - {max_temp:.1f}°C" if selected_loc_id == "all" else f"Recorded at {obs_time_ist_str}"
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">Latest Temperature</div>
            <div class="metric-value">{mean_temp:.1f}<span class="metric-unit">°C</span></div>
            <div class="metric-subtext">{range_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with kpi3:
    if current_rain is None:
        rain_val_str = "N/A"
        rain_unit_str = ""
        rain_desc = "No rainfall data"
    elif current_rain == 0.0:
        rain_val_str = "0.0"
        rain_unit_str = "mm"
        rain_desc = "Dry (0.0 mm)"
    else:
        rain_val_str = f"{current_rain:.1f}"
        rain_unit_str = "mm"
        rain_desc = f"Peak rate: {current_rain:.1f} mm"
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">Rainfall Rate</div>
            <div class="metric-value">{rain_val_str}<span class="metric-unit">{rain_unit_str}</span></div>
            <div class="metric-subtext">{rain_desc}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with kpi4:
    gust_desc = f"Gusts to {max_gust:.1f} km/h" if max_gust > 0 else "Calm gusts"
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">Wind Velocity</div>
            <div class="metric-value">{mean_wind:.1f}<span class="metric-unit">km/h</span></div>
            <div class="metric-subtext">{gust_desc}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with kpi5:
    alert_badge = '<span class="badge badge-success">Normal (0)</span>' if active_anomalies_count == 0 else f'<span class="badge badge-danger">{active_anomalies_count} Active</span>'
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">Weather Anomalies</div>
            <div class="metric-value">{active_anomalies_count}<span class="metric-unit">events</span></div>
            <div class="metric-subtext">{alert_badge}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.write("")  # Margin spacing


# -----------------------------------------------------------------------------
# 6. Interactive Geospatial Map with OpenStreetMap (Requirement 2 & HIGHEST PRIORITY)
# -----------------------------------------------------------------------------
st.markdown("### Spatial Overview & Station Network")

map_left_col, map_right_col = st.columns([3, 1.3])

with map_left_col:
    try:
        # Standard OpenStreetMap tile configuration with attribution
        # Completely avoids CARTO and any endpoints requiring API keys
        osm_tile_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        osm_attr = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

        # Center initially around central Hyderabad coordinates
        m = folium.Map(
            location=[17.4150, 78.4600],
            zoom_start=11,
            tiles=osm_tile_url,
            attr=osm_attr,
            control_scale=True,
        )

        lats: List[float] = []
        lons: List[float] = []

        for loc_rec in active_records:
            lid = loc_rec["location_id"]
            lname = loc_rec.get("location_name") or lid
            lat = float(loc_rec["latitude"])
            lon = float(loc_rec["longitude"])
            lats.append(lat)
            lons.append(lon)

            temp = loc_rec.get("temperature_c")
            humidity = loc_rec.get("relative_humidity_pct")
            wind = loc_rec.get("wind_speed_kmh")
            rain = loc_rec.get("precipitation_mm") or 0.0
            wcode = loc_rec.get("weather_code")
            condition = get_weather_description(wcode)

            # Check if this station is currently selected in dropdown
            is_active_selection = (selected_loc_id != "all" and selected_loc_id == lid)
            has_anomaly = any(a.get("location_id") == lid and a.get("status") == "active" for a in anomalies_list)

            # Enterprise marker color: Primary Blue (#2563EB), Warning Amber (#D97706), Alert Red (#DC2626)
            marker_color = "#DC2626" if has_anomaly else ("#D97706" if is_stale else "#2563EB")
            radius = 12 if is_active_selection else 9
            weight = 3 if is_active_selection else 2

            popup_content = f"""
            <div style="font-family:'Inter', sans-serif; font-size:12px; color:#F8FAFC; background-color:#111827; padding:8px 10px; border-radius:6px; min-width:180px;">
                <div style="font-weight:700; font-size:13px; color:#60A5FA; margin-bottom:4px;">{lname}</div>
                <div style="font-size:11px; color:#94A3B8; margin-bottom:6px;">Station: {lid}</div>
                <table style="width:100%; border-collapse:collapse; font-size:11px;">
                    <tr><td style="color:#94A3B8; padding:2px 0;">Temperature:</td><td style="color:#F8FAFC; text-align:right;"><b>{temp}°C</b></td></tr>
                    <tr><td style="color:#94A3B8; padding:2px 0;">Humidity:</td><td style="color:#F8FAFC; text-align:right;"><b>{humidity}%</b></td></tr>
                    <tr><td style="color:#94A3B8; padding:2px 0;">Wind:</td><td style="color:#F8FAFC; text-align:right;"><b>{wind} km/h</b></td></tr>
                    <tr><td style="color:#94A3B8; padding:2px 0;">Precipitation:</td><td style="color:#F8FAFC; text-align:right;"><b>{rain} mm</b></td></tr>
                    <tr><td style="color:#94A3B8; padding:2px 0;">Condition:</td><td style="color:#F8FAFC; text-align:right;"><b>{condition}</b></td></tr>
                </table>
            </div>
            """

            folium.CircleMarker(
                location=[lat, lon],
                radius=radius,
                color=marker_color,
                weight=weight,
                fill=True,
                fill_color=marker_color,
                fill_opacity=0.75,
                tooltip=f"{lname}: {temp}°C, {condition}",
                popup=folium.Popup(popup_content, max_width=250),
            ).add_to(m)

        # Fit map bounds to encompass all Hyderabad locations cleanly
        if lats and lons:
            m.fit_bounds([
                [min(lats) - 0.02, min(lons) - 0.02],
                [max(lats) + 0.02, max(lons) + 0.02],
            ])

        st_folium(m, height=420, use_container_width=True, returned_objects=[])

    except Exception as e:
        st.error(f"Basemap rendering error: {e}. Please ensure network access to OpenStreetMap tiles.")

with map_right_col:
    st.markdown("#### Station Details Panel")
    for r in active_records:
        lid = r["location_id"]
        lname = r.get("location_name") or lid
        temp = r.get("temperature_c")
        wcode = r.get("weather_code")
        condition = get_weather_description(wcode)
        is_selected = (selected_loc_id == "all" or selected_loc_id == lid)
        active_class = "station-panel-active" if is_selected else ""

        st.markdown(
            f"""
            <div class="station-panel {active_class}">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-weight:600; font-size:0.88rem; color:#F8FAFC;">{lname}</span>
                    <span style="font-weight:700; font-size:0.88rem; color:#60A5FA;">{temp}°C</span>
                </div>
                <div style="font-size:0.75rem; color:#94A3B8; margin-top:2px;">
                    {condition} • Coord: {r.get('latitude', 0):.4f}, {r.get('longitude', 0):.4f}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# -----------------------------------------------------------------------------
# 7. Analytical Views: Charts, Anomaly Log, Audit & Raw Observations
# -----------------------------------------------------------------------------
st.write("")
st.markdown("### Historical Analytics & Data Quality")

# Load historical time-series observations
df_history = load_historical_series(
    location_id=None if selected_loc_id == "all" else selected_loc_id,
    limit=500,
)

# Apply Time Window filtering
if not df_history.empty and selected_horizon != "all":
    cutoff_hours = {"6h": 6, "12h": 12, "24h": 24, "3d": 72}.get(selected_horizon, 24)
    cutoff_dt = now_utc - timedelta(hours=cutoff_hours)
    df_history = df_history[df_history["observed_at"] >= cutoff_dt]

tab_charts, tab_traffic, tab_anomalies, tab_table, tab_audit = st.tabs([
    "Time-Series Trends",
    "Traffic Disruption Intelligence",
    "Weather Anomalies Log",
    "Observations Archive",
    "Ingestion Audit",
])

# Enterprise Plotly clean dark layout configuration
PLOTLY_DARK_LAYOUT = dict(
    paper_bgcolor="#111827",
    plot_bgcolor="#111827",
    font=dict(family="Inter, -apple-system, sans-serif", size=12, color="#94A3B8"),
    xaxis=dict(
        showgrid=True,
        gridcolor="#1E293B",
        linecolor="#334155",
        zeroline=False,
        tickfont=dict(size=11, color="#94A3B8"),
    ),
    yaxis=dict(
        showgrid=True,
        gridcolor="#1E293B",
        linecolor="#334155",
        zeroline=False,
        tickfont=dict(size=11, color="#94A3B8"),
    ),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
        font=dict(size=11, color="#94A3B8"),
    ),
    margin=dict(l=45, r=20, t=30, b=40),
)

# Tab 1: Time-Series Trends
with tab_charts:
    if df_history.empty:
        st.info("No historical observations found for the selected station and time window.")
    else:
        col_c1, col_c2 = st.columns(2)

        with col_c1:
            st.markdown("##### Temperature Trend (°C)")
            temp_valid = df_history["temperature_c"].dropna() if "temperature_c" in df_history.columns else pd.Series(dtype=float)
            if temp_valid.empty:
                st.info("No temperature records available for the selected station and time window.")
            else:
                fig_temp = px.line(
                    df_history,
                    x="observed_at",
                    y="temperature_c",
                    color="location_name" if selected_loc_id == "all" else None,
                    markers=True,
                    labels={"observed_at": "Timestamp (UTC)", "temperature_c": "Temperature (°C)", "location_name": "Station"},
                    color_discrete_sequence=["#3B82F6", "#06B6D4", "#8B5CF6", "#F59E0B", "#10B981"],
                )
                fig_temp.update_traces(line=dict(width=2))
                fig_temp.update_layout(**PLOTLY_DARK_LAYOUT, height=300)
                st.plotly_chart(fig_temp, width="stretch")

        with col_c2:
            st.markdown("##### Precipitation (mm)")
            precip_col = "precipitation_mm" if "precipitation_mm" in df_history.columns else None
            valid_precip = df_history[precip_col].dropna() if precip_col else pd.Series(dtype=float)

            if valid_precip.empty:
                st.info("No precipitation data recorded for the selected station and time window.")
            elif (valid_precip == 0.0).all():
                st.caption("Measured 0.0 mm across all intervals (Dry weather / Zero precipitation).")
                fig_rain = px.bar(
                    df_history,
                    x="observed_at",
                    y="precipitation_mm",
                    color="location_name" if selected_loc_id == "all" else None,
                    labels={"observed_at": "Timestamp (UTC)", "precipitation_mm": "Rainfall (mm)", "location_name": "Station"},
                    barmode="group",
                    color_discrete_sequence=["#0284C7", "#06B6D4", "#3B82F6", "#64748B", "#475569"],
                )
                rain_layout = PLOTLY_DARK_LAYOUT.copy()
                rain_layout.pop("yaxis", None)
                fig_rain.update_layout(
                    **rain_layout,
                    height=300,
                    yaxis=dict(
                        range=[0, 1],
                        showgrid=True,
                        gridcolor="#1E293B",
                        linecolor="#334155",
                        zeroline=True,
                        zerolinecolor="#3B82F6",
                        tickvals=[0, 0.5, 1.0],
                        ticktext=["0.0 mm (Dry)", "0.5 mm", "1.0 mm"],
                        tickfont=dict(size=11, color="#94A3B8"),
                    ),
                    annotations=[
                        dict(
                            text="All stations recorded 0.0 mm (No precipitation)",
                            xref="paper",
                            yref="paper",
                            x=0.5,
                            y=0.5,
                            showarrow=False,
                            font=dict(size=12, color="#64748B"),
                        )
                    ]
                )
                st.plotly_chart(fig_rain, width="stretch")
            else:
                fig_rain = px.bar(
                    df_history,
                    x="observed_at",
                    y="precipitation_mm",
                    color="location_name" if selected_loc_id == "all" else None,
                    labels={"observed_at": "Timestamp (UTC)", "precipitation_mm": "Rainfall (mm)", "location_name": "Station"},
                    barmode="group",
                    color_discrete_sequence=["#0284C7", "#06B6D4", "#3B82F6", "#64748B", "#475569"],
                )
                fig_rain.update_layout(**PLOTLY_DARK_LAYOUT, height=300)
                st.plotly_chart(fig_rain, width="stretch")

        col_c3, col_c4 = st.columns(2)

        with col_c3:
            st.markdown("##### Wind Velocity & Gusts (km/h)")
            wind_valid = df_history["wind_speed_kmh"].dropna() if "wind_speed_kmh" in df_history.columns else pd.Series(dtype=float)
            if wind_valid.empty:
                st.info("No wind records available for the selected station and time window.")
            else:
                fig_wind = go.Figure()
                if selected_loc_id != "all":
                    fig_wind.add_trace(go.Scatter(
                        x=df_history["observed_at"],
                        y=df_history["wind_speed_kmh"],
                        mode="lines+markers",
                        name="Sustained Wind",
                        line=dict(color="#3B82F6", width=2),
                    ))
                    if "wind_gusts_kmh" in df_history.columns and not df_history["wind_gusts_kmh"].dropna().empty:
                        fig_wind.add_trace(go.Scatter(
                            x=df_history["observed_at"],
                            y=df_history["wind_gusts_kmh"],
                            mode="lines",
                            name="Peak Gusts",
                            line=dict(color="#EF4444", width=1.5, dash="dash"),
                        ))
                else:
                    for loc_name, grp in df_history.groupby("location_name"):
                        fig_wind.add_trace(go.Scatter(
                            x=grp["observed_at"],
                            y=grp["wind_speed_kmh"],
                            mode="lines+markers",
                            name=str(loc_name),
                        ))
                fig_wind.update_layout(**PLOTLY_DARK_LAYOUT, height=300)
                st.plotly_chart(fig_wind, width="stretch")

        with col_c4:
            st.markdown("##### Relative Humidity (%)")
            hum_valid = df_history["relative_humidity_pct"].dropna() if "relative_humidity_pct" in df_history.columns else pd.Series(dtype=float)
            if hum_valid.empty:
                st.info("No humidity records available for the selected station and time window.")
            else:
                fig_hum = px.line(
                    df_history,
                    x="observed_at",
                    y="relative_humidity_pct",
                    color="location_name" if selected_loc_id == "all" else None,
                    markers=True,
                    labels={"observed_at": "Timestamp (UTC)", "relative_humidity_pct": "Humidity (%)", "location_name": "Station"},
                    color_discrete_sequence=["#10B981", "#06B6D4", "#3B82F6", "#8B5CF6", "#64748B"],
                )
                fig_hum.update_traces(line=dict(width=2))
                fig_hum.update_layout(**PLOTLY_DARK_LAYOUT, height=300)
                st.plotly_chart(fig_hum, width="stretch")


# Tab 2: Traffic Disruption Intelligence
with tab_traffic:
    st.markdown("#### Road Corridor Travel Times & Disruption Intelligence")

    # 1. API Status and Setup Guide
    t_status = TrafficCollector(get_config()).get_status_info()
    if not t_status["configured"]:
        st.markdown(
            """
            <div style="background-color:#1E293B; border-left:4px solid #F59E0B; border-radius:6px; padding:16px 20px; margin-bottom:18px;">
                <div style="font-weight:700; color:#F8FAFC; font-size:0.95rem; margin-bottom:4px;">
                    ⚠️ TomTom Traffic Provider Disabled (No API Key Configured)
                </div>
                <div style="font-size:0.84rem; color:#CBD5E1; line-height:1.5;">
                    Live traffic polling across Hyderabad road corridors is currently paused. No simulated or synthetic data has been injected into production tables.<br>
                    <b>Setup Instructions to Enable Live Traffic:</b>
                    <ol style="margin-top:6px; margin-bottom:6px; padding-left:20px;">
                        <li>Create a free account on the <a href="https://developer.tomtom.com" target="_blank" style="color:#60A5FA;">TomTom Developer Portal</a>.</li>
                        <li>Generate an API Key with access to the Routing & Traffic Flow APIs.</li>
                        <li>Add <code>TOMTOM_API_KEY=your_key_here</code> to your <code>.env</code> file.</li>
                        <li>Click <b>Poll TomTom Traffic</b> in the sidebar or run <code>python src/collect_traffic.py --run-once</code>.</li>
                    </ol>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div style="background-color:#064E3B; border-left:4px solid #10B981; border-radius:6px; padding:12px 18px; margin-bottom:18px;">
                <span style="font-weight:600; color:#ECFDF5;">TomTom Traffic & Routing API Active</span> • 
                <span style="font-size:0.85rem; color:#A7F3D0;">Live travel-time querying enabled for monitored Hyderabad arterial corridors.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # 2. Monitored Corridors Overview
    st.markdown("##### Monitored Road Corridors & Current Conditions")
    latest_traffic_records = load_latest_traffic()
    if not latest_traffic_records:
        st.info("No corridor records found in database.")
    else:
        corridor_cols = st.columns(min(len(latest_traffic_records), 5))
        now_utc = datetime.now(timezone.utc)
        for i, c in enumerate(latest_traffic_records):
            with corridor_cols[i % len(corridor_cols)]:
                c_dur = c.get("estimated_duration_seconds")
                c_ff = c.get("free_flow_duration_seconds")
                c_ci = c.get("congestion_index")
                c_type = c.get("data_type")
                obs_dt = c.get("observed_at")

                if obs_dt is not None:
                    if isinstance(obs_dt, datetime):
                        obs_utc = obs_dt.astimezone(timezone.utc) if obs_dt.tzinfo else obs_dt.replace(tzinfo=timezone.utc)
                    else:
                        obs_utc = datetime.fromisoformat(str(obs_dt).replace("Z", "+00:00")).astimezone(timezone.utc)
                    age_min = max(0.0, (now_utc - obs_utc).total_seconds() / 60.0)
                    obs_str = obs_utc.strftime("%Y-%m-%d %H:%M UTC")
                    if age_min <= 60.0:
                        freshness_label = f"Live ({int(age_min)}m ago)"
                        freshness_badge = "badge-success"
                    elif age_min <= 180.0:
                        freshness_label = f"Stale ({int(age_min)}m ago)"
                        freshness_badge = "badge-warning"
                    else:
                        freshness_label = f"Stale ({int(age_min / 60.0)}h ago)"
                        freshness_badge = "badge-danger"
                else:
                    obs_str = "No observations recorded"
                    freshness_label = "Unavailable"
                    freshness_badge = "badge-info"

                dur_str = f"{c_dur / 60.0:.1f}m" if c_dur else "Unavailable"
                ff_str = f"{c_ff / 60.0:.1f}m" if c_ff else "N/A"
                ci_str = f"{c_ci:.2f}x" if c_ci else "N/A"

                if c_ci and c_ci >= 1.6:
                    ci_badge = "badge-danger"
                elif c_ci and c_ci >= 1.3:
                    ci_badge = "badge-warning"
                elif c_ci:
                    ci_badge = "badge-success"
                else:
                    ci_badge = "badge-info"

                if not c.get("travel_time_id"):
                    tag_label = "Unavailable (Unpolled)"
                    tag_class = "badge-info"
                elif c_type == "live_api":
                    tag_label = "Live API Ingestion"
                    tag_class = "badge-success" if freshness_badge == "badge-success" else "badge-warning"
                elif c_type == "test_fixture":
                    tag_label = "Synthetic Test Fixture"
                    tag_class = "badge-warning"
                else:
                    tag_label = f"Archive ({c_type or 'historical'})"
                    tag_class = "badge-info"

                st.markdown(
                    f"""
                    <div style="background-color:#111827; border:1px solid #1E293B; border-radius:6px; padding:12px; margin-bottom:12px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                            <span style="font-weight:600; font-size:0.85rem; color:#F8FAFC;">{c.get('corridor_name')}</span>
                        </div>
                        <div style="font-size:0.75rem; color:#94A3B8; margin-bottom:8px;">{c.get('via_road')} ({c.get('distance_km', 0):.1f} km)</div>
                        <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:4px;">
                            <span style="font-size:0.78rem; color:#94A3B8;">Est. Travel Time:</span>
                            <span style="font-weight:700; font-size:1.0rem; color:#60A5FA;">{dur_str}</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.75rem; color:#94A3B8; margin-bottom:6px;">
                            <span>Free-flow: {ff_str}</span>
                            <span class="badge {ci_badge}">Congestion: {ci_str}</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
                            <span class="badge {freshness_badge}" style="font-size:0.7rem;">{freshness_label}</span>
                            <span class="badge {tag_class}" style="font-size:0.7rem;">{tag_label}</span>
                        </div>
                        <div style="font-size:0.68rem; color:#64748B; margin-top:4px; text-align:right;">
                            {obs_str}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # 3. Traffic Disruption Alerts & Explainable Evidence
    st.markdown("##### Traffic Disruption Alerts & Weather Correlation")
    disruptions_list = load_traffic_disruptions(
        route_id=None if selected_loc_id == "all" else selected_loc_id,
        limit=50,
    )
    if not disruptions_list:
        st.markdown(
            """
            <div style="background-color:#111827; border:1px solid #1E293B; border-radius:6px; padding:18px 22px; margin-bottom:14px;">
                <div style="font-weight:600; color:#F8FAFC; font-size:0.92rem; margin-bottom:4px;">
                    No Active Traffic Disruptions
                </div>
                <div style="font-size:0.83rem; color:#94A3B8; line-height:1.5;">
                    Monitored road corridors are flowing within expected baseline travel-time variations.
                    Statistical baselines require at least <b>5 prior historical observations</b> per route
                    to establish reliable Median Absolute Deviation (MAD) bounds.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.caption(f"Showing {len(disruptions_list)} recorded corridor disruption(s)")
        for d in disruptions_list:
            sev = d.get("severity", "LOW")
            sev_badge = "badge-danger" if sev in ("HIGH", "CRITICAL", "SEVERE") else ("badge-warning" if sev == "MODERATE" else "badge-info")
            evidence = d.get("evidence") or {}
            weather_ctx = d.get("weather_context") or {}
            is_weather_corr = weather_ctx.get("weather_correlated", False)
            weather_badge = "badge-warning" if is_weather_corr else "badge-info"
            weather_title = "Weather-Correlated Delay" if is_weather_corr else "Independent Non-Weather Congestion"

            d_type = evidence.get("data_type", "live_api")
            type_tag = "Provider Estimate" if d_type == "live_api" else ("Synthetic Fixture" if d_type == "test_fixture" else "Estimate")

            obs_dt = d.get("observed_at")
            if isinstance(obs_dt, datetime):
                obs_dt = obs_dt.astimezone(timezone.utc) if obs_dt.tzinfo else obs_dt.replace(tzinfo=timezone.utc)
                obs_str = obs_dt.strftime("%Y-%m-%d %H:%M UTC")
            else:
                obs_str = str(obs_dt) if obs_dt else "N/A"

            st.markdown(
                f"""
                <div style="background-color:#111827; border:1px solid #1E293B; border-radius:6px; padding:14px; margin-bottom:12px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <span style="font-weight:600; font-size:0.92rem; color:#F8FAFC;">
                            #{d.get('disruption_id')} • {d.get('corridor_name')}
                        </span>
                        <div>
                            <span class="badge {sev_badge}">{sev}</span>
                            <span class="badge badge-info" style="margin-left:4px;">{type_tag}</span>
                            <span class="badge {weather_badge}" style="margin-left:4px;">{weather_title}</span>
                        </div>
                    </div>
                    <div style="font-size:0.82rem; color:#CBD5E1; margin-bottom:6px;">
                        <b>Traffic Disruption:</b> {evidence.get('explanation', 'None recorded.')}
                    </div>
                    <div style="font-size:0.80rem; color:#94A3B8; background-color:#0F172A; padding:8px 10px; border-radius:4px; margin-bottom:6px;">
                        <b>Weather Analysis:</b> {weather_ctx.get('evidence', 'No meteorological data.')}
                    </div>
                    <div style="font-size:0.75rem; color:#64748B;">
                        Observed: {obs_str} | Model: {d.get('model_name')} (v{d.get('model_version')}) | Congestion Index: {d.get('congestion_index') or 'N/A'}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.expander(f"View Traffic Evidence JSON (#{d.get('disruption_id')})"):
                st.json(evidence)

    # 4. Historical Travel Time Trends
    st.markdown("##### Corridor Travel Time Time-Series")
    df_traffic = load_traffic_history(
        route_id=None if selected_loc_id == "all" else selected_loc_id,
        limit=300,
    )
    if df_traffic.empty:
        st.info("No historical travel-time observations recorded yet in database.")
    else:
        df_traffic_view = df_traffic.copy()
        df_traffic_view["travel_time_minutes"] = df_traffic_view["estimated_duration_seconds"] / 60.0
        fig_traffic = px.line(
            df_traffic_view,
            x="observed_at",
            y="travel_time_minutes",
            color="corridor_name",
            markers=True,
            labels={"observed_at": "Timestamp (UTC)", "travel_time_minutes": "Travel Time (minutes)", "corridor_name": "Corridor"},
            color_discrete_sequence=["#3B82F6", "#F59E0B", "#10B981", "#EF4444", "#8B5CF6"],
        )
        fig_traffic.update_traces(line=dict(width=2))
        fig_traffic.update_layout(**PLOTLY_DARK_LAYOUT, height=320)
        st.plotly_chart(fig_traffic, width="stretch")


# Tab 3: Weather Anomalies Log
with tab_anomalies:
    st.markdown("#### Weather Anomalies & Model Evidence")

    if not anomalies_list:
        st.markdown(
            """
            <div style="background-color:#111827; border:1px solid #1E293B; border-radius:6px; padding:18px 22px;">
                <div style="font-weight:600; color:#F8FAFC; font-size:0.92rem; margin-bottom:4px;">
                    No Anomalies Recorded in Database
                </div>
                <div style="font-size:0.83rem; color:#94A3B8; line-height:1.5;">
                    All ingested observations fall within normal baseline boundaries.
                    Note: The statistical anomaly engine requires at least <b>5 prior historical observations</b> per station
                    to establish reliable Median Absolute Deviation (MAD) baselines. Observations with insufficient history
                    are safely skipped to avoid false alarms during initial startup.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.caption(f"Showing {len(anomalies_list)} recorded anomaly alert(s)")
        for a in anomalies_list:
            sev = a.get("severity", "LOW")
            sev_badge = "badge-danger" if sev in ("HIGH", "CRITICAL") else ("badge-warning" if sev == "MEDIUM" else "badge-info")
            evidence = a.get("evidence") or {}
            obs_dt = a.get("observed_at")
            if isinstance(obs_dt, datetime):
                obs_dt = obs_dt.astimezone(timezone.utc) if obs_dt.tzinfo else obs_dt.replace(tzinfo=timezone.utc)
                obs_str = obs_dt.strftime("%Y-%m-%d %H:%M UTC")
            else:
                obs_str = str(obs_dt) if obs_dt else "N/A"

            det_dt = a.get("detected_at")
            if isinstance(det_dt, datetime):
                det_dt = det_dt.astimezone(timezone.utc) if det_dt.tzinfo else det_dt.replace(tzinfo=timezone.utc)
                det_str = det_dt.strftime("%Y-%m-%d %H:%M UTC")
            else:
                det_str = str(det_dt) if det_dt else "N/A"

            st.markdown(
                f"""
                <div style="background-color:#111827; border:1px solid #1E293B; border-radius:6px; padding:14px; margin-bottom:10px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <span style="font-weight:600; font-size:0.92rem; color:#F8FAFC;">
                            #{a.get('anomaly_id')} • {a.get('location_name')} ({a.get('location_id')})
                        </span>
                        <div>
                            <span class="badge {sev_badge}">{sev}</span>
                            <span class="badge badge-info" style="margin-left:4px;">Risk: {float(a.get('risk_score', 0)):.2f}</span>
                        </div>
                    </div>
                    <div style="font-size:0.82rem; color:#CBD5E1; margin-bottom:6px;">
                        <b>Explanation:</b> {evidence.get('explanation', 'None recorded.')}
                    </div>
                    <div style="font-size:0.75rem; color:#94A3B8;">
                        Observed: {obs_str} | Detected: {det_str} | Model: {a.get('model_name')} (v{a.get('model_version')})
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.expander(f"View Evidence JSON (#{a.get('anomaly_id')})"):
                st.json(evidence)


# Tab 3: Observations Archive
with tab_table:
    st.markdown("#### Recorded Observations Archive")
    if df_history.empty:
        st.info("No records to display.")
    else:
        disp_cols = [
            "observation_id",
            "location_name",
            "observed_at_utc_str",
            "observed_at_ist_str",
            "temperature_c",
            "relative_humidity_pct",
            "precipitation_mm",
            "wind_speed_kmh",
            "wind_gusts_kmh",
            "cloud_cover_pct",
            "weather_code",
            "data_type",
        ]
        valid_cols = [c for c in disp_cols if c in df_history.columns]
        view_df = df_history[valid_cols].rename(columns={
            "observation_id": "ID",
            "location_name": "Location",
            "observed_at_utc_str": "Observed (UTC)",
            "observed_at_ist_str": "Observed (IST)",
            "temperature_c": "Temp (°C)",
            "relative_humidity_pct": "Humidity (%)",
            "precipitation_mm": "Rain (mm)",
            "wind_speed_kmh": "Wind (km/h)",
            "wind_gusts_kmh": "Gusts (km/h)",
            "cloud_cover_pct": "Cloud (%)",
            "weather_code": "WMO Code",
            "data_type": "Data Type",
        })

        st.dataframe(view_df, width="stretch", height=360)

        csv_bytes = view_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Observations as CSV",
            data=csv_bytes,
            file_name=f"urbanpulse_weather_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )


# Tab 4: Ingestion Pipeline Audit
with tab_audit:
    st.markdown("#### Ingestion Runs Audit Log")
    runs_list = load_recent_runs(limit=15)
    if not runs_list:
        st.info("No ingestion runs recorded in database.")
    else:
        df_runs = pd.DataFrame(runs_list)
        if "started_at" in df_runs.columns:
            df_runs["started_at"] = pd.to_datetime(df_runs["started_at"], utc=True).dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        if "finished_at" in df_runs.columns:
            df_runs["finished_at"] = pd.to_datetime(df_runs["finished_at"], utc=True).dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        st.dataframe(
            df_runs[[
                "run_id",
                "started_at",
                "status",
                "locations_requested",
                "locations_succeeded",
                "observations_saved",
                "duration_seconds",
                "error_message",
            ]].rename(columns={
                "run_id": "Run ID",
                "started_at": "Started (UTC)",
                "status": "Status",
                "locations_requested": "Requested",
                "locations_succeeded": "Succeeded",
                "observations_saved": "Saved",
                "duration_seconds": "Duration (s)",
                "error_message": "Errors",
            }),
            width="stretch",
            height=280,
        )

    # Database summary counts
    st.markdown("##### Total Database Records")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Observations", historical_stats.get("total_observations", 0))
    with c2:
        st.metric("Total Ingestion Runs", historical_stats.get("total_runs", 0))
    with c3:
        succ = historical_stats.get("successful_runs", 0)
        tot = historical_stats.get("total_runs", 1) or 1
        pct = (succ / tot) * 100
        st.metric("Pipeline Success Rate", f"{pct:.1f}%")
    with c4:
        st.metric("Persisted Anomalies", historical_stats.get("total_anomalies", 0))


# -----------------------------------------------------------------------------
# 8. Auto-Refresh Loop (Page End)
# -----------------------------------------------------------------------------
if auto_refresh:
    import time
    time.sleep(refresh_seconds)
    st.rerun()
