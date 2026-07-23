"""Game engine: session state machine, transactional question locking, scoring.

Live per-question state is persisted in GameSession.state_json so a browser
refresh or server restart never loses confirmed scores (those live in
ScoreEvent + Match.score_a/score_b).
"""
from __future__ import annotations

import json
import random
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, scoring


class GameError(Exception):
    def __init__(self, key: str, **ctx):
        self.key = key
        self.ctx = ctx
        super().__init__(key)


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #
def _default_state() -> dict:
    return {"current_section": 0, "current": None, "sections": {},
            "wheel": None, "buzzer": {"locked": False, "team": None}}


def load_state(session: models.GameSession) -> dict:
    if not session.state_json:
        return _default_state()
    try:
        return json.loads(session.state_json)
    except Exception:
        return _default_state()


def save_state(db: Session, session: models.GameSession, state: dict) -> None:
    session.state_json = json.dumps(state, ensure_ascii=False)
    db.add(session)
    db.commit()


def regular_categories(db: Session) -> list[dict]:
    cats = (
        db.query(models.Category)
        .filter(models.Category.is_regular == True, models.Category.is_active == True)  # noqa: E712
        .order_by(models.Category.id)
        .all()
    )
    return [{"id": c.id, "name": c.name} for c in cats]


def category_by_name(db: Session, name: str) -> Optional[models.Category]:
    return db.query(models.Category).filter(models.Category.name == name).first()


# --------------------------------------------------------------------------- #
# Availability
# --------------------------------------------------------------------------- #
def used_question_ids(db: Session, session_id: int) -> set[int]:
    rows = db.query(models.QuestionUsage.question_id).filter(
        models.QuestionUsage.session_id == session_id
    ).all()
    return {r[0] for r in rows}


def available_count(db: Session, session_id: int, category_id: int) -> int:
    used = used_question_ids(db, session_id)
    q = db.query(func.count(models.Question.id)).filter(
        models.Question.category_id == category_id,
        models.Question.is_active == True,  # noqa: E712
    )
    if used:
        q = q.filter(~models.Question.id.in_(used))
    return q.scalar() or 0


def remaining_by_category(db: Session, session_id: int) -> list[dict]:
    out = []
    for cat in regular_categories(db):
        out.append({**cat, "remaining": available_count(db, session_id, cat["id"])})
    return out


# --------------------------------------------------------------------------- #
# Section lifecycle
# --------------------------------------------------------------------------- #
def start_section(db: Session, session: models.GameSession, section: int) -> dict:
    state = load_state(session)
    cats = regular_categories(db)
    key = str(section)

    if section == 1:
        plan = scoring.build_section1_plan(cats)
    elif section == 2:
        plan = scoring.build_section2_plan(cats)
    elif section == 3:
        plan = scoring.build_section3_plan(cats)
    elif section == 4:
        state["wheel"] = {**scoring.build_section4_plan(), "turn": "a"}
        plan = []
    elif section == 5:
        plan = [{"category_id": None, "category_name": scoring.SECTION_NAMES[5], "team": None}]
    else:
        raise GameError("invalid_transition")

    # validate availability per category (sections 1-3)
    if section in (1, 2, 3):
        need: dict[int, int] = {}
        for slot in plan:
            need[slot["category_id"]] = need.get(slot["category_id"], 0) + 1
        for cat_id, n in need.items():
            if available_count(db, session.id, cat_id) < n:
                cat = db.get(models.Category, cat_id)
                raise GameError("not_enough_questions", n=n, cat=cat.name if cat else cat_id)

    state["sections"][key] = {"plan": plan, "index": 0, "completed": False}
    state["current_section"] = section
    state["current"] = None
    state["buzzer"] = {"locked": False, "team": None}
    session.current_section = section
    session.status = "in_progress"
    save_state(db, session, state)
    return state


def finish_section(db: Session, session: models.GameSession, section: int) -> dict:
    state = load_state(session)
    key = str(section)
    if key in state["sections"]:
        state["sections"][key]["completed"] = True
    state["current"] = None
    save_state(db, session, state)
    return state


# --------------------------------------------------------------------------- #
# Question selection with transactional locking
# --------------------------------------------------------------------------- #
def select_question(
    db: Session,
    session: models.GameSession,
    section: int,
    category_id: int,
    team: Optional[str],
    host_id: Optional[int],
    via_joker: bool = False,
) -> dict:
    state = load_state(session)
    if state.get("current") and state["current"].get("phase") not in (None, "done"):
        raise GameError("invalid_transition")

    used = used_question_ids(db, session.id)
    candidates = db.query(models.Question.id).filter(
        models.Question.category_id == category_id,
        models.Question.is_active == True,  # noqa: E712
    )
    if used:
        candidates = candidates.filter(~models.Question.id.in_(used))
    ids = [r[0] for r in candidates.all()]
    if not ids:
        raise GameError("not_enough_questions", n=1,
                        cat=(db.get(models.Category, category_id).name if db.get(models.Category, category_id) else ""))

    random.shuffle(ids)
    assigned_team_id = None
    match = session.match
    if team == "a":
        assigned_team_id = match.team_a_id
    elif team == "b":
        assigned_team_id = match.team_b_id

    # Try to reserve transactionally; unique constraint prevents double use.
    for qid in ids:
        usage = models.QuestionUsage(
            session_id=session.id, question_id=qid, category_id=category_id,
            section=section, assigned_team_id=assigned_team_id, state="selected",
            host_id=host_id, via_joker=via_joker,
        )
        db.add(usage)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(usage)
        state["current"] = {
            "usage_id": usage.id, "question_id": qid, "category_id": category_id,
            "category_name": db.get(models.Category, category_id).name,
            "team": team, "section": section, "phase": "selected",
            "buzz_team": None, "via_joker": via_joker,
        }
        save_state(db, session, state)
        return state
    raise GameError("question_already_used")


def reveal(db: Session, session: models.GameSession) -> dict:
    state = load_state(session)
    cur = state.get("current")
    if not cur or cur["phase"] != "selected":
        raise GameError("invalid_transition")
    cur["phase"] = "revealed"
    usage = db.get(models.QuestionUsage, cur["usage_id"])
    if usage:
        usage.state = "revealed"
        from .models import now as _now
        usage.revealed_at = _now()
        db.commit()
    save_state(db, session, state)
    return state


def set_buzz(db: Session, session: models.GameSession, team: str) -> dict:
    state = load_state(session)
    if state["buzzer"]["locked"]:
        return state
    state["buzzer"] = {"locked": True, "team": team}
    if state.get("current"):
        state["current"]["buzz_team"] = team
    save_state(db, session, state)
    return state


def reset_buzzer(db: Session, session: models.GameSession) -> dict:
    state = load_state(session)
    state["buzzer"] = {"locked": False, "team": None}
    if state.get("current"):
        state["current"]["buzz_team"] = None
    save_state(db, session, state)
    return state


# --------------------------------------------------------------------------- #
# Scoring actions
# --------------------------------------------------------------------------- #
def _add_score(db: Session, match: models.Match, team: str, delta: int,
               reason: str, section: int, question_id: Optional[int], host_id: Optional[int]):
    team_id = match.team_a_id if team == "a" else match.team_b_id
    if team == "a":
        match.score_a += delta
    else:
        match.score_b += delta
    db.add(models.ScoreEvent(
        match_id=match.id, session_id=match.session.id, section=section,
        team_id=team_id, question_id=question_id, delta=delta,
        reason=reason, host_id=host_id,
    ))


def _finish_current(db: Session, session: models.GameSession, state: dict, result: str,
                    rebound_result: Optional[str], points: int):
    cur = state["current"]
    usage = db.get(models.QuestionUsage, cur["usage_id"])
    if usage:
        usage.state = "used"
        usage.answer_result = result
        usage.rebound_result = rebound_result
        usage.points_awarded = points
    cur["phase"] = "done"
    # advance plan index
    sec = str(cur["section"])
    if sec in state["sections"]:
        state["sections"][sec]["index"] += 1


def mark_correct(db: Session, session: models.GameSession, team: str, host_id: Optional[int]) -> dict:
    """Original team answered correctly -> 5 points. Ends the question."""
    state = load_state(session)
    cur = state.get("current")
    if not cur or cur["phase"] != "revealed":
        raise GameError("reveal_first")
    match = session.match
    pts = scoring.NORMAL_POINTS
    _add_score(db, match, team, pts, "original_correct", cur["section"], cur["question_id"], host_id)
    _finish_current(db, session, state, "correct", None, pts)
    reset_buzzer_inline(state)
    save_state(db, session, state)
    return state


def mark_wrong(db: Session, session: models.GameSession, host_id: Optional[int]) -> dict:
    """Original attempt wrong. If section allows rebound -> open rebound phase,
    else the question ends with no points (فردي / individual)."""
    state = load_state(session)
    cur = state.get("current")
    if not cur or cur["phase"] not in ("revealed",):
        raise GameError("reveal_first")
    section = cur["section"]
    if scoring.SECTION_REBOUND.get(section):
        cur["phase"] = "rebound_open"
        save_state(db, session, state)
        return state
    # no rebound (section 3) -> 0 for both
    _finish_current(db, session, state, "wrong", None, 0)
    reset_buzzer_inline(state)
    save_state(db, session, state)
    return state


def _original_team(cur: dict) -> Optional[str]:
    """Which team had the original attempt."""
    if cur.get("team") in ("a", "b"):
        return cur["team"]
    return cur.get("buzz_team")


def open_rebound(db: Session, session: models.GameSession, host_id: Optional[int]) -> dict:
    state = load_state(session)
    cur = state.get("current")
    if not cur or cur["phase"] != "revealed":
        raise GameError("invalid_transition")
    if not scoring.SECTION_REBOUND.get(cur["section"]):
        raise GameError("invalid_transition")
    cur["phase"] = "rebound_open"
    save_state(db, session, state)
    return state


def rebound_correct(db: Session, session: models.GameSession, host_id: Optional[int]) -> dict:
    """Opponent answers rebound correctly -> 10 points to opponent, 0 original."""
    state = load_state(session)
    cur = state.get("current")
    if not cur or cur["phase"] != "rebound_open":
        raise GameError("invalid_transition")
    orig = _original_team(cur)
    opponent = "b" if orig == "a" else "a"
    match = session.match
    pts = scoring.REBOUND_POINTS
    _add_score(db, match, opponent, pts, "rebound_correct", cur["section"], cur["question_id"], host_id)
    _finish_current(db, session, state, "wrong", "correct", pts)
    reset_buzzer_inline(state)
    save_state(db, session, state)
    return state


def rebound_wrong(db: Session, session: models.GameSession, host_id: Optional[int]) -> dict:
    """Failed rebound -> 0 for both."""
    state = load_state(session)
    cur = state.get("current")
    if not cur or cur["phase"] != "rebound_open":
        raise GameError("invalid_transition")
    _finish_current(db, session, state, "wrong", "wrong", 0)
    reset_buzzer_inline(state)
    save_state(db, session, state)
    return state


def father_award(db: Session, session: models.GameSession, team: Optional[str], host_id: Optional[int]) -> dict:
    """Section 5: first correct team gets 10; or no team answered."""
    state = load_state(session)
    cur = state.get("current")
    if not cur or cur["phase"] != "revealed":
        raise GameError("reveal_first")
    match = session.match
    if team in ("a", "b"):
        pts = scoring.FATHER_POINTS
        _add_score(db, match, team, pts, "father_correct", 5, cur["question_id"], host_id)
        _finish_current(db, session, state, "correct", None, pts)
    else:
        _finish_current(db, session, state, "none", None, 0)
    save_state(db, session, state)
    return state


def skip_question(db: Session, session: models.GameSession, host_id: Optional[int]) -> dict:
    state = load_state(session)
    cur = state.get("current")
    if not cur:
        raise GameError("invalid_transition")
    usage = db.get(models.QuestionUsage, cur["usage_id"])
    if usage:
        usage.state = "skipped"
    _finish_current(db, session, state, "skipped", None, 0)
    reset_buzzer_inline(state)
    save_state(db, session, state)
    return state


def invalidate_question(db: Session, session: models.GameSession, reason: str, host_id: Optional[int]) -> dict:
    state = load_state(session)
    cur = state.get("current")
    if not cur:
        raise GameError("invalid_transition")
    usage = db.get(models.QuestionUsage, cur["usage_id"])
    if usage:
        usage.state = "invalidated"
    db.add(models.ScoreEvent(
        match_id=session.match.id, session_id=session.id, section=cur["section"],
        team_id=None, question_id=cur["question_id"], delta=0,
        reason=f"invalidated:{reason}", host_id=host_id,
    ))
    _finish_current(db, session, state, "invalidated", None, 0)
    reset_buzzer_inline(state)
    save_state(db, session, state)
    return state


def reset_buzzer_inline(state: dict) -> None:
    state["buzzer"] = {"locked": False, "team": None}
    if state.get("current"):
        state["current"]["buzz_team"] = None


# --------------------------------------------------------------------------- #
# Wheel
# --------------------------------------------------------------------------- #
def spin_wheel(db: Session, session: models.GameSession, team: str) -> dict:
    """Server-side fair random spin. Returns segment result."""
    state = load_state(session)
    wheel = state.get("wheel")
    if not wheel:
        raise GameError("invalid_transition")
    spins_key = f"spins_{team}"
    if wheel.get(spins_key, 0) <= 0:
        raise GameError("invalid_transition")
    cats = regular_categories(db)
    segments = scoring.wheel_segments(cats)
    result = random.choice(segments)
    wheel[spins_key] -= 1
    wheel["turn"] = "b" if team == "a" else "a"
    state["wheel"] = wheel
    state["last_spin"] = {"team": team, "result": result}
    save_state(db, session, state)
    return state
