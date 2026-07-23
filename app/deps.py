"""Shared template/rendering helpers."""
from __future__ import annotations

import os

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import config, i18n
from .config import BASE_DIR

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _asset(path: str) -> str:
    """Return a static URL with an mtime-based cache-busting query string.

    Usage in templates: ``{{ asset('js/game.js') }}`` →
    ``/static/js/game.js?v=1729450123``. If the file is missing we fall back
    to the plain URL so template rendering never crashes on a typo.
    """
    rel = path.lstrip("/")
    fs_path = BASE_DIR / "app" / "static" / rel
    try:
        v = int(os.path.getmtime(fs_path))
    except OSError:
        return f"/static/{rel}"
    return f"/static/{rel}?v={v}"


templates.env.globals["asset"] = _asset


def render(request: Request, db: Session, name: str, user=None, **context):
    lang = i18n.resolve_language(request, db)
    tr = i18n.Translator(lang)
    base = {
        "request": request,
        "t": tr.t,
        "lang": lang,
        "dir": tr.dir,
        "user": user,
        "config": config,
        "languages": i18n.available_languages(),
        "ROLE_ADMIN": config.ROLE_ADMIN,
        "ROLE_HOST": config.ROLE_HOST,
    }
    base.update(context)
    return templates.TemplateResponse(request=request, name=name, context=base)
