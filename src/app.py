"""
UrbanPulse AI - src/app.py redirect proxy
Allows running: streamlit run src/app.py
"""

from pathlib import Path
import sys

# Ensure project root and .venv site-packages are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

venv_site_packages = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"
if venv_site_packages.exists() and str(venv_site_packages) not in sys.path:
    sys.path.insert(0, str(venv_site_packages))

# Import and execute dashboard
from src import dashboard
