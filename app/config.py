"""Application configuration and managed storage paths."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Managed storage directory. Imported workbooks are copied here so the app does
# not depend on the original external file location.
DATA_STORE = Path(os.environ.get("ABAKRA_DATA_STORE", BASE_DIR / "data_store"))
WORKBOOK_STORE = DATA_STORE / "workbooks"
MANUAL_STORE = DATA_STORE / "manual"
UPLOAD_TMP = DATA_STORE / "uploads_tmp"
LOGO_STORE = DATA_STORE / "logos"
LOG_DIR = DATA_STORE / "logs"

DB_PATH = Path(os.environ.get("ABAKRA_DB", DATA_STORE / "abakra.db"))
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

LOCALES_DIR = BASE_DIR / "app" / "locales"

DEFAULT_LANGUAGE = "ar-EG"
SUPPORTED_LANGUAGES = ("ar-EG", "en")

# Upload limits / security
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXCEL_EXT = {".xlsx", ".xlsm"}  # macros are never executed
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".svg"}

# Session secret. In production set ABAKRA_SECRET.
SECRET_KEY = os.environ.get("ABAKRA_SECRET") or secrets.token_hex(32)
SESSION_COOKIE = "abakra_session"

# Login throttling
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 300

ROLE_ADMIN = "مسؤول"
ROLE_HOST = "خادم"


def ensure_dirs() -> None:
    for d in (DATA_STORE, WORKBOOK_STORE, MANUAL_STORE, UPLOAD_TMP, LOGO_STORE, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
