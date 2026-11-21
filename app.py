"""
UrbanPulse AI - Dashboard Root Entrypoint
Launches the Streamlit real-time weather intelligence dashboard.
Usage:
    streamlit run app.py
"""

from pathlib import Path
import sys

# Ensure project root and .venv site-packages are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

venv_site_packages = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"
if venv_site_packages.exists() and str(venv_site_packages) not in sys.path:
    sys.path.insert(0, str(venv_site_packages))

# Run dashboard module
from src import dashboard
