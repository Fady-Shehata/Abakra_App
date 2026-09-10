"""Game engine: session state machine, transactional question locking, scoring.

Live per-question state is persisted in GameSession.state_json so a browser
refresh or server restart never loses confirmed scores (those live in
ScoreEvent + Match.score_a/score_b).
"""
from __future__ import annotations

import json
import random
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import func, or_
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


def team_history_question_ids(db: Session, session: models.GameSession) -> set[int]:
    match = session.match
    if not match:
        return set()
    team_ids = [tid for tid in (match.team_a_id, match.team_b_id) if tid]
    if not team_ids:
        return set()
    rows = (
        db.query(models.QuestionUsage.question_id)
        .join(models.GameSession, models.QuestionUsage.session_id == models.GameSession.id)
        .join(models.Match, models.GameSession.match_id == models.Match.id)
        .filter(
            models.QuestionUsage.session_id != session.id,
            or_(
                models.Match.team_a_id.in_(team_ids),
                models.Match.team_b_id.in_(team_ids),
            ),
        )
        .all()
    )
    return {r[0] for r in rows}


def unavailable_question_ids(db: Session, session: models.GameSession) -> set[int]:
    return used_question_ids(db, session.id) | team_history_question_ids(db, session)


def available_count(db: Session, session_or_id: models.GameSession | int, category_id: int,
                    estimate_only: bool = False) -> int:
    if isinstance(session_or_id, models.GameSession):
        used = unavailable_question_ids(db, session_or_id)
    else:
        used = used_question_ids(db, int(session_or_id))
    q = db.query(func.count(models.Question.id)).filter(
        models.Question.category_id == category_id,
        models.Question.is_active == True,  # noqa: E712
    )
    q = q.filter(models.Question.qtype == "estimate") if estimate_only else q.filter(models.Question.qtype != "estimate")
    if used:
        q = q.filter(~models.Question.id.in_(used))
    return q.scalar() or 0


def remaining_by_category(db: Session, session_or_id: models.GameSession | int) -> list[dict]:
    out = []
    for cat in regular_categories(db):
        out.append({**cat, "remaining": available_count(db, session_or_id, cat["id"])})
    return out


def estimate_remaining_by_category(db: Session, session_or_id: models.GameSession | int) -> list[dict]:
    return [
        {**cat, "remaining": available_count(db, session_or_id, cat["id"], estimate_only=True)}
        for cat in regular_categories(db)
        if cat["name"] in scoring.ESTIMATE_CATEGORIES
    ]


# --------------------------------------------------------------------------- #
# Section lifecycle
# --------------------------------------------------------------------------- #
def start_section(db: Session, session: models.GameSession, section: int) -> dict:
    state = load_state(session)
    cats = regular_categories(db)
    key = str(section)
    if section not in scoring.section_order(db):
        raise GameError("invalid_transition")
    section_type = scoring.section_type(db, section)
    section_name = scoring.section_names(db).get(section, scoring.SECTION_NAMES.get(section_type, str(section)))

    if section_type == 1:
        plan = scoring.build_section1_plan(cats)
    elif section_type == 2:
        plan = scoring.build_section2_plan(cats)
    elif section_type == 3:
        plan = scoring.build_section3_plan(cats)
    elif section_type == 4:
        state["wheel"] = {**scoring.build_section4_plan(), "turn": "a"}
        plan = []
    elif section_type == 5:
        plan = [{"category_id": None, "category_name": section_name, "team": None}]
    elif section_type == 6:
        estimate_cats = [c for c in cats if c["name"] in scoring.ESTIMATE_CATEGORIES]
        if not estimate_cats:
            raise GameError("not_enough_questions", n=1, cat=section_name)
        plan = [{"category_id": c["id"], "category_name": c["name"], "team": None} for c in estimate_cats]
    else:
        raise GameError("invalid_transition")
    if section_type in (1, 2, 3, 6):
        random.shuffle(plan)

    # validate availability per category (sections 1-3)
    if section_type in (1, 2, 3):
        need: dict[int, int] = {}
        for slot in plan:
            need[slot["category_id"]] = need.get(slot["category_id"], 0) + 1
        for cat_id, n in need.items():
            if available_count(db, session, cat_id) < n:
                cat = db.get(models.Category, cat_id)
                raise GameError("not_enough_questions", n=n, cat=cat.name if cat else cat_id)

    state["sections"][key] = {
        "plan": plan,
        "index": 0,
        "completed": False,
        "section_type": section_type,
        "name": section_name,
    }
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

    used = unavailable_question_ids(db, session)
    section_type = scoring.section_type(db, section)
    candidates = db.query(models.Question.id).filter(
        models.Question.category_id == category_id,
        models.Question.is_active == True,  # noqa: E712
    )
    candidates = candidates.filter(models.Question.qtype == "estimate") if section_type == 6 else candidates.filter(models.Question.qtype != "estimate")
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
            "team": team, "section": section, "section_type": section_type,
            "phase": "selected",
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
               reason: str, section: Optional[int], question_id: Optional[int], host_id: Optional[int]):
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


def apply_yellow_card(db: Session, session: models.GameSession, team: str, host_id: Optional[int]) -> dict:
    """Yellow card penalty: subtract 3 points from the selected team."""
    if team not in ("a", "b"):
        raise GameError("invalid_transition")
    match = session.match
    if not match or match.status not in ("in_progress", "paused"):
        raise GameError("invalid_transition")
    _add_score(db, match, team, -3, "yellow_card", None, None, host_id)
    db.commit()
    return load_state(session)


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
    section_type = cur.get("section_type") or scoring.section_type(db, cur["section"])
    if scoring.SECTION_REBOUND.get(section_type):
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
    section_type = cur.get("section_type") or scoring.section_type(db, cur["section"])
    if not scoring.SECTION_REBOUND.get(section_type):
        raise GameError("invalid_transition")
    cur["phase"] = "rebound_open"
    save_state(db, session, state)
    return state


def rebound_correct(db: Session, session: models.GameSession, host_id: Optional[int],
                    team: Optional[str] = None) -> dict:
    """Rebound answered correctly -> 10 points.

    If ``team`` is provided ("a" or "b"), award the rebound points directly to
    that team. This is used by quick sections (2 and 3) where the host chooses
    which team receives the rebound. Otherwise, fall back to the automatic
    opponent-of-original-team behaviour used by sections 1 and 4.
    """
    state = load_state(session)
    cur = state.get("current")
    if not cur or cur["phase"] != "rebound_open":
        raise GameError("invalid_transition")
    if team in ("a", "b"):
        target = team
    else:
        orig = _original_team(cur)
        target = "b" if orig == "a" else "a"
    match = session.match
    pts = scoring.REBOUND_POINTS
    _add_score(db, match, target, pts, "rebound_correct", cur["section"], cur["question_id"], host_id)
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
        _add_score(db, match, team, pts, "father_correct", cur["section"], cur["question_id"], host_id)
        _finish_current(db, session, state, "correct", None, pts)
    else:
        _finish_current(db, session, state, "none", None, 0)
    save_state(db, session, state)
    return state


def _number(value) -> Decimal:
    text = str(value).strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,"))
    text = re.sub(r"[^0-9+,.\-]", "", text).replace(",", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        raise GameError("invalid_number")


def submit_estimates(db: Session, session: models.GameSession, guess_a, guess_b,
                     host_id: Optional[int]) -> dict:
    """Award five points to the team closest to the workbook's numeric answer.

    An exact distance tie awards both teams, since both estimates are equally closest.
    """
    state = load_state(session)
    cur = state.get("current")
    if not cur or cur.get("phase") != "revealed" or cur.get("section_type") != 6:
        raise GameError("invalid_transition")
    from . import question_store as qs
    question = db.get(models.Question, cur["question_id"])
    content = qs.render_question(db, question, include_answer=True) if question else {}
    correct = _number(content.get("answer", ""))
    a = _number(guess_a)
    b = _number(guess_b)
    distance_a, distance_b = abs(a - correct), abs(b - correct)
    winners = ["a"] if distance_a < distance_b else ["b"] if distance_b < distance_a else ["a", "b"]
    for team in winners:
        _add_score(db, session.match, team, scoring.ESTIMATE_POINTS, "estimate_closest",
                   cur["section"], cur["question_id"], host_id)
    cur["estimate_result"] = {
        "guess_a": str(a), "guess_b": str(b), "correct": str(correct),
        "distance_a": str(distance_a), "distance_b": str(distance_b),
        "winner": "tie" if len(winners) == 2 else winners[0],
    }
    _finish_current(db, session, state, f"estimate_{cur['estimate_result']['winner']}", None,
                    scoring.ESTIMATE_POINTS * len(winners))
    save_state(db, session, state)
    return state


def skip_question(db: Session, session: models.GameSession, host_id: Optional[int]) -> dict:
    state = load_state(session)
    cur = state.get("current")
    if not cur:
        raise GameError("invalid_transition")
    section = cur["section"]
    category_id = cur["category_id"]
    team = cur.get("team")
    via_joker = bool(cur.get("via_joker"))
    usage = db.get(models.QuestionUsage, cur["usage_id"])
    if usage:
        usage.state = "skipped"
        usage.answer_result = "skipped"
        usage.points_awarded = 0
    state["current"] = None
    reset_buzzer_inline(state)
    save_state(db, session, state)
    try:
        return select_question(db, session, section, category_id, team, host_id, via_joker=via_joker)
    except GameError as e:
        if e.key == "not_enough_questions":
            return load_state(session)
        raise


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
