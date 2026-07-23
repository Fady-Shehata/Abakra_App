"""Internationalization: JSON-file based translations with runtime default."""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from . import config, models


# Simple mtime-based cache so edits to locale JSON take effect without
# restarting the server. Keyed by language code; value is (mtime, data).
_LOCALE_CACHE: dict[str, tuple[float, dict]] = {}


def _load(lang: str) -> dict:
    path = config.LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        path = config.LOCALES_DIR / f"{config.DEFAULT_LANGUAGE}.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    cached = _LOCALE_CACHE.get(lang)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    _LOCALE_CACHE[lang] = (mtime, data)
    return data


def available_languages() -> list[str]:
    return list(config.SUPPORTED_LANGUAGES)


def clear_cache() -> None:
    _LOCALE_CACHE.clear()


def get_default_language(db: Session) -> str:
    row = db.get(models.ApplicationSetting, "default_language")
    if row and row.value in config.SUPPORTED_LANGUAGES:
        return row.value
    return config.DEFAULT_LANGUAGE


def set_default_language(db: Session, lang: str) -> None:
    if lang not in config.SUPPORTED_LANGUAGES:
        raise ValueError("unsupported language")
    row = db.get(models.ApplicationSetting, "default_language")
    if row:
        row.value = lang
    else:
        db.add(models.ApplicationSetting(key="default_language", value=lang))
    db.commit()


def resolve_language(request, db: Session) -> str:
    """Per-request language: user override cookie/session, else global default."""
    lang: Optional[str] = None
    try:
        lang = request.session.get("lang")
    except Exception:
        lang = None
    if lang not in config.SUPPORTED_LANGUAGES:
        lang = get_default_language(db)
    return lang


class Translator:
    def __init__(self, lang: str):
        self.lang = lang
        self.dir = "rtl" if lang.startswith("ar") else "ltr"
        self._data = _load(lang)
        self._fallback = _load(config.DEFAULT_LANGUAGE)

    def t(self, key: str, **kwargs) -> str:
        val = self._data.get(key) or self._fallback.get(key) or key
        if kwargs:
            try:
                return val.format(**kwargs)
            except (KeyError, IndexError):
                return val
        return val
