from __future__ import annotations

from app import models
from tests.conftest import make_match_with_session


def test_admin_can_open_teams(admin_client):
    r = admin_client.get("/teams")
    assert r.status_code == 200


def test_host_cannot_open_admin_teams(host_client):
    r = host_client.get("/teams")
    assert r.status_code == 403


def test_unauth_redirects_to_login(client):
    r = client.get("/my-matches", follow_redirects=False)
    assert r.status_code == 401 or r.status_code == 302


def test_host_only_assigned_match_visible(db_session, host_client):
    host = db_session.query(models.User).filter_by(username="host").first()
    m1 = make_match_with_session(db_session, host_id=host.id)
    m2 = make_match_with_session(db_session, host_id=None)

    r_ok = host_client.get(f"/game/{m1.id}")
    assert r_ok.status_code == 200
    r_forbidden = host_client.get(f"/game/{m2.id}")
    assert r_forbidden.status_code == 403
