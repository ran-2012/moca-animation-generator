"""Global paths & configuration for MocaDiff backend.

This module is maintained by the Lead.  It makes the vendored psd-tools
importable and defines every filesystem root used by the API.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
VENDOR_DIR = BACKEND_DIR / "vendor"

# psd-tools 1.25.0 + attrs are normally installed via requirements.txt; the
# original sandbox also kept a local copy in vendor/ (git-ignored) as fallback.
if VENDOR_DIR.is_dir() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

DATA_DIR = PROJECT_ROOT / "data"
ASSETS_DIR = DATA_DIR / "assets"
PROJECTS_DIR = DATA_DIR / "projects"
SETTINGS_FILE = DATA_DIR / "settings.json"

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

HOST = "127.0.0.1"
PORT = 8787
APP_VERSION = "0.1.0"

ALLOWED_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8787",
    "http://localhost:8787",
]

MAX_UPLOAD_BYTES = 200 * 1024 * 1024

# Asset kinds and their sub-directories under data/assets.
ASSET_KINDS = ("psd", "svp", "audio")


def ensure_dirs() -> None:
    for path in (DATA_DIR, ASSETS_DIR, PROJECTS_DIR):
        path.mkdir(parents=True, exist_ok=True)
    for kind in ASSET_KINDS:
        (ASSETS_DIR / kind).mkdir(parents=True, exist_ok=True)
