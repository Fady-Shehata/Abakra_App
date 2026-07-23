from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Use isolated test storage/database before importing app modules.
TEST_ROOT = Path(__file__).resolve().parent / "_testdata"
if TEST_ROOT.exists():
    shutil.rmtree(TEST_ROOT)
TEST_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["ABAKRA_DATA_STORE"] = str(TEST_ROOT)
os.environ["ABAKRA_DB"] = str(TEST_ROOT / "test.db")
os.environ["ABAKRA_SKIP_AUTOIMPORT"] = "1"
os.environ["ABAKRA_ADMIN_PASSWORD"] = "admin123"
os.environ["ABAKRA_HOST_PASSWORD"] = "host123"

from app.main import app  # noqa: E402
from app.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app import models, seed  # noqa: E402


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed.seed_initial_data()
    yield


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login(client: TestClient, username: str, password: str):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


@pytest.fixture
def admin_client(client):
    r = login(client, "admin", "admin123")
    assert r.status_code in (302, 303)
    return client


@pytest.fixture
def host_client(client):
    r = login(client, "host", "host123")
    assert r.status_code in (302, 303)
    return client


def make_team(db, name: str):
    existing = db.query(models.Team).filter_by(name=name).first()
    if existing:
        return existing
    t = models.Team(name=name, member_count=0, is_active=True)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def make_category(db, name: str, is_regular=True, on_wheel=True):
    existing = db.query(models.Category).filter_by(name=name).first()
    if existing:
        return existing
    c = models.Category(name=name, is_regular=is_regular, on_wheel=on_wheel, is_active=True)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def make_source(db, name="src.xlsx"):
    s = models.QuestionSource(original_name=name, stored_filename=name, file_hash="h", kind="import")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def make_question(db, category_id: int, source_id: int, code: str, chash: str):
    q = models.Question(
        category_id=category_id,
        source_id=source_id,
        worksheet="S",
        row_number=2,
        question_code=code,
        content_hash=chash,
        qtype="mc",
        is_active=True,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def make_match_with_session(db, host_id=None, stage="group"):
    t = models.Tournament(name="T", status="active")
    db.add(t)
    db.commit()
    db.refresh(t)
    ta = make_team(db, "A")
    tb = make_team(db, "B")
    m = models.Match(
        tournament_id=t.id,
        stage=stage,
        round_name="R",
        team_a_id=ta.id,
        team_b_id=tb.id,
        host_id=host_id,
        status="ready",
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    m.session = models.GameSession(status="ready")
    db.commit()
    db.refresh(m)
    return m
