"""FastAPI application entry point."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import config, seed
from .config import BASE_DIR
from .database import init_db
from .deps import render, templates  # noqa: F401
from .web import router as web_router
from .api import router as api_router

config.ensure_dirs()
logging.basicConfig(
    filename=str(config.LOG_DIR / "app.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("abakra")

app = FastAPI(title="Abakra Tournament Platform")
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    session_cookie=config.SESSION_COOKIE,
    https_only=False,
    same_site="lax",
    max_age=60 * 60 * 12,
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
app.mount("/logos", StaticFiles(directory=str(config.LOGO_STORE)), name="logos")

app.include_router(web_router)
app.include_router(api_router, prefix="/api")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    seed.seed_initial_data()


@app.exception_handler(StarletteHTTPException)
async def http_exc_handler(request: Request, exc: StarletteHTTPException):
    # API requests get JSON; page requests redirect/render friendly messages.
    if request.url.path.startswith("/api"):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
    if exc.status_code == 401:
        return RedirectResponse(url="/login", status_code=302)
    if exc.status_code == 403:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    if request.url.path.startswith("/api"):
        return JSONResponse(status_code=500, content={"error": "server_error"})
    return JSONResponse(status_code=500, content={"error": "server_error"})
