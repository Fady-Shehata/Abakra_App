"""Database engine/session setup with SQLite WAL mode."""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.engine import Engine

from . import config

config.ensure_dirs()

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    future=True,
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (lightweight migration for SQLite)."""
    from . import models  # noqa: F401  (ensure models imported)

    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def _run_lightweight_migrations() -> None:
    """Add columns that were introduced after the initial schema.

    SQLite doesn't support most ALTER operations, but ADD COLUMN is safe and
    idempotent when guarded by a PRAGMA check.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(teams)").fetchall()}
        if "level" not in cols:
            conn.exec_driver_sql("ALTER TABLE teams ADD COLUMN level VARCHAR(80)")
