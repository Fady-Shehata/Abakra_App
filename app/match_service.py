"""Match lifecycle services: completion, points, bracket advancement."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy.orm import Session

from . import models, brackets, standings


def compute_result(score_a: int, score_b: int) -> tuple[Optional[str], bool]:
    """Return (winner_side, is_draw)."""
    if score_a > score_b:
        return "a", False
    if score_b > score_a:
        return "b", False
    return None, True


def complete_match(
    db: Session,
    match: models.Match,
    host_id: Optional[int],
    forced_winner_side: Optional[str] = None,
) -> models.Match:
    """Finalize a match. Knockout matches must not end as a draw."""
    winner_side, is_draw = compute_result(match.score_a, match.score_b)

    if match.stage == "knockout" and is_draw:
        if forced_winner_side not in ("a", "b"):
            from .game import GameError
            raise GameError("knockout_no_draw")
        winner_side = forced_winner_side
        is_draw = False

    match.is_draw = is_draw
    if winner_side == "a":
        match.winner_team_id = match.team_a_id
        match.points_a, match.points_b = (standings.WIN_POINTS, standings.LOSS_POINTS)
    elif winner_side == "b":
        match.winner_team_id = match.team_b_id
        match.points_a, match.points_b = (standings.LOSS_POINTS, standings.WIN_POINTS)
    else:
        match.winner_team_id = None
        match.points_a = match.points_b = standings.DRAW_POINTS

    match.status = "completed"
    match.completed_at = dt.datetime.utcnow()
    if match.session:
        match.session.status = "completed"

    result = db.get(models.MatchResult, match.id) if False else (
        db.query(models.MatchResult).filter(models.MatchResult.match_id == match.id).first()
    )
    if result is None:
        result = models.MatchResult(match_id=match.id)
        db.add(result)
    result.score_a = match.score_a
    result.score_b = match.score_b
    result.winner_team_id = match.winner_team_id
    result.is_draw = match.is_draw
    result.points_a = match.points_a
    result.points_b = match.points_b
    result.host_id = host_id
    result.completed_at = match.completed_at

    db.add(models.AuditLog(user_id=host_id, action="complete_match",
                           detail=f"match={match.id} {match.score_a}-{match.score_b}"))
    db.commit()

    if match.stage == "knockout":
        brackets.advance_after_match(db, match)
    return match


def update_match_result(
    db: Session,
    match: models.Match,
    score_a: int,
    score_b: int,
    admin_id: Optional[int],
    forced_winner_side: Optional[str] = None,
) -> models.Match:
    """Admin correction for a completed match result."""
    if score_a < 0 or score_b < 0:
        from .game import GameError
        raise GameError("invalid_transition")

    old_score_a = match.score_a
    old_score_b = match.score_b
    winner_side, is_draw = compute_result(score_a, score_b)
    if match.stage == "knockout" and is_draw:
        if forced_winner_side not in ("a", "b"):
            from .game import GameError
            raise GameError("knockout_no_draw")
        winner_side = forced_winner_side
        is_draw = False

    match.score_a = score_a
    match.score_b = score_b
    match.is_draw = is_draw
    if winner_side == "a":
        match.winner_team_id = match.team_a_id
        match.points_a, match.points_b = (standings.WIN_POINTS, standings.LOSS_POINTS)
    elif winner_side == "b":
        match.winner_team_id = match.team_b_id
        match.points_a, match.points_b = (standings.LOSS_POINTS, standings.WIN_POINTS)
    else:
        match.winner_team_id = None
        match.points_a = match.points_b = standings.DRAW_POINTS

    match.status = "completed"
    if not match.completed_at:
        match.completed_at = dt.datetime.utcnow()
    if match.session:
        match.session.status = "completed"

    result = db.query(models.MatchResult).filter(models.MatchResult.match_id == match.id).first()
    if result is None:
        result = models.MatchResult(match_id=match.id)
        db.add(result)
    result.score_a = match.score_a
    result.score_b = match.score_b
    result.winner_team_id = match.winner_team_id
    result.is_draw = match.is_draw
    result.points_a = match.points_a
    result.points_b = match.points_b
    result.host_id = admin_id
    result.completed_at = match.completed_at

    delta_a = score_a - old_score_a
    delta_b = score_b - old_score_b
    if delta_a:
        db.add(models.ScoreEvent(
            match_id=match.id,
            session_id=match.session.id if match.session else None,
            section=None,
            team_id=match.team_a_id,
            question_id=None,
            delta=delta_a,
            reason="admin_result_adjustment",
            host_id=admin_id,
        ))
    if delta_b:
        db.add(models.ScoreEvent(
            match_id=match.id,
            session_id=match.session.id if match.session else None,
            section=None,
            team_id=match.team_b_id,
            question_id=None,
            delta=delta_b,
            reason="admin_result_adjustment",
            host_id=admin_id,
        ))

    db.add(models.AuditLog(
        user_id=admin_id,
        action="edit_match_result",
        detail=f"match={match.id} {old_score_a}-{old_score_b} -> {score_a}-{score_b}",
    ))
    db.commit()
    return match
