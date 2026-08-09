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


def test_admin_can_edit_completed_match_result(db_session, admin_client):
    m = make_match_with_session(db_session)
    m.status = "completed"
    m.score_a = 5
    m.score_b = 10
    m.winner_team_id = m.team_b_id
    db_session.commit()

    r = admin_client.post(
        f"/matches/{m.id}/result",
        data={"score_a": "20", "score_b": "15", "winner_side": "a", "redirect_to": "/matches"},
        follow_redirects=False,
    )

    assert r.status_code in (302, 303)
    db_session.expire_all()
    updated = db_session.get(models.Match, m.id)
    result = db_session.query(models.MatchResult).filter_by(match_id=m.id).one()
    assert updated.score_a == 20
    assert updated.score_b == 15
    assert updated.winner_team_id == updated.team_a_id
    assert result.score_a == 20
    assert result.score_b == 15
    assert db_session.query(models.ScoreEvent).filter_by(
        match_id=m.id,
        reason="admin_result_adjustment",
    ).count() == 2


def test_host_cannot_edit_match_result(db_session, host_client):
    host = db_session.query(models.User).filter_by(username="host").first()
    m = make_match_with_session(db_session, host_id=host.id)
    m.status = "completed"
    db_session.commit()

    r = host_client.post(
        f"/matches/{m.id}/result",
        data={"score_a": "1", "score_b": "0", "winner_side": "a", "redirect_to": "/matches"},
        follow_redirects=False,
    )

    assert r.status_code == 403
