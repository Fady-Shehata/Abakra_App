"""HTML page routes."""
from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from . import config, models, security, i18n, standings as standings_mod, game as game_engine, scoring
from .database import get_db
from .deps import render
from .security import get_current_user, require_login, require_admin

router = APIRouter()


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/", 302)
    return render(request, db, "login.html", error=None)


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...),
                 db: Session = Depends(get_db)):
    user = db.query(models.User).filter_by(username=username.strip()).first()
    lang = i18n.resolve_language(request, db)
    tr = i18n.Translator(lang)
    if not user or not user.is_active:
        return render(request, db, "login.html", error=tr.t("invalid_credentials"))
    if security.is_locked(user):
        return render(request, db, "login.html", error=tr.t("account_locked"))
    if not security.verify_password(user.password_hash, password):
        security.register_failed_attempt(db, user)
        return render(request, db, "login.html", error=tr.t("invalid_credentials"))
    security.reset_attempts(db, user)
    request.session["user_id"] = user.id
    security.audit(db, user.id, "login", user.username)
    return RedirectResponse("/", 302)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 302)


@router.post("/lang")
def set_lang(request: Request, lang: str = Form(...)):
    if lang in config.SUPPORTED_LANGUAGES:
        request.session["lang"] = lang
    ref = request.headers.get("referer", "/")
    return RedirectResponse(ref, 302)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", 302)
    if user.role_name == config.ROLE_HOST:
        return RedirectResponse("/my-matches", 302)
    return dashboard(request, db, user)


def dashboard(request: Request, db: Session, user: models.User):
    total_teams = db.query(models.Team).count()
    active_tournaments = db.query(models.Tournament).filter_by(status="active").count()
    completed = db.query(models.Match).filter_by(status="completed").count()
    scheduled = db.query(models.Match).filter(models.Match.status.in_(["scheduled", "ready"])).count()
    remaining = db.query(models.Match).filter(models.Match.status != "completed").count()
    hosts = db.query(models.User).join(models.Role).filter(models.Role.name == config.ROLE_HOST,
                                                           models.User.is_active == True).count()  # noqa: E712
    # stats
    top_match = db.query(models.Match).filter_by(status="completed").order_by(
        (models.Match.score_a + models.Match.score_b).desc()).first()
    cat_counts = []
    for c in db.query(models.Category).filter_by(is_regular=True).all():
        cnt = db.query(models.Question).filter_by(category_id=c.id, is_active=True).count()
        cat_counts.append({"name": c.name, "count": cnt})
    warnings = [c for c in cat_counts if c["count"] < 10]
    stats = {
        "total_teams": total_teams,
        "active_tournaments": active_tournaments,
        "completed_matches": completed,
        "scheduled_matches": scheduled,
        "remaining_matches": remaining,
        "active_hosts": hosts,
        "cat_counts": cat_counts,
        "warnings": warnings,
        "top_match": top_match,
    }
    tournaments = db.query(models.Tournament).order_by(models.Tournament.created_at.desc()).all()
    group_results = []
    for tr in tournaments:
        groups = []
        for g in tr.groups:
            rows = standings_mod.compute_group_standings(db, tr, g)
            completed_matches = db.query(models.Match).filter_by(
                tournament_id=tr.id,
                group_id=g.id,
                status="completed",
            ).count()
            groups.append({"group": g, "rows": rows, "completed_matches": completed_matches})
        if groups:
            group_results.append({"tournament": tr, "groups": groups})
    return render(request, db, "dashboard.html", user=user, stats=stats,
                  tournaments=tournaments, group_results=group_results)


# --------------------------------------------------------------------------- #
# Teams
# --------------------------------------------------------------------------- #
@router.get("/teams", response_class=HTMLResponse)
def teams_page(request: Request, db: Session = Depends(get_db),
               user: models.User = Depends(require_admin)):
    teams = db.query(models.Team).order_by(models.Team.name).all()
    return render(request, db, "teams.html", user=user, teams=teams, summary=None)


@router.post("/teams/create")
def team_create(request: Request, name: str = Form(...), level: str = Form(""),
                member_count: int = Form(0),
                members: str = Form(""), member_names: list[str] = Form(default=[]), status: str = Form("active"),
                db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    names = [m.strip() for m in member_names if m and m.strip()]
    if not names and members.strip():
        names = [m.strip() for m in members.replace("\r", "").split("\n") if m.strip()]
    # keep manual entry clean and prevent accidental duplicates
    unique_names: list[str] = []
    seen = set()
    for n in names:
        key = n.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique_names.append(n)
    team = models.Team(name=name.strip(), level=(level.strip() or None),
                       member_count=len(names) or member_count,
                       is_active=(status == "active"))
    for n in unique_names:
        team.members.append(models.TeamMember(name=n))
    team.member_count = len(unique_names) if unique_names else member_count
    db.add(team)
    db.commit()
    security.audit(db, user.id, "create_team", team.name)
    return RedirectResponse("/teams", 302)


@router.post("/teams/{team_id}/update")
def team_update(team_id: int, name: str = Form(...), level: str = Form(""),
                status: str = Form("active"),
                db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    team = db.get(models.Team, team_id)
    if not team:
        return RedirectResponse("/teams", 302)
    new_name = (name or "").strip()
    if new_name and new_name != team.name:
        # avoid unique-constraint collisions
        clash = db.query(models.Team).filter(models.Team.name == new_name,
                                             models.Team.id != team.id).first()
        if not clash:
            team.name = new_name
    team.level = (level or "").strip() or None
    team.is_active = (status == "active")
    db.commit()
    security.audit(db, user.id, "update_team", f"team={team_id}")
    return RedirectResponse("/teams", 302)


@router.post("/teams/{team_id}/members")
def team_members_update(team_id: int, member_names: list[str] = Form(default=[]),
                        db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    team = db.get(models.Team, team_id)
    if not team:
        return RedirectResponse("/teams", 302)

    cleaned: list[str] = []
    seen = set()
    for raw in member_names:
        n = (raw or "").strip()
        if not n:
            continue
        key = n.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(n)

    team.members.clear()
    for n in cleaned:
        team.members.append(models.TeamMember(name=n))
    team.member_count = len(cleaned)
    db.commit()
    security.audit(db, user.id, "update_team_members", f"team={team_id} count={len(cleaned)}")
    return RedirectResponse("/teams", 302)


@router.post("/teams/{team_id}/delete")
def team_delete(team_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    team = db.get(models.Team, team_id)
    if team:
        db.delete(team)
        db.commit()
        security.audit(db, user.id, "delete_team", str(team_id))
    return RedirectResponse("/teams", 302)


@router.post("/teams/import")
async def teams_import(request: Request, file: UploadFile = File(...),
                       db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    from . import excel_import
    summary = await _save_and_run(file, lambda p, n: excel_import.import_teams_workbook(db, p, n))
    teams = db.query(models.Team).order_by(models.Team.name).all()
    return render(request, db, "teams.html", user=user, teams=teams, summary=summary)


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #
@router.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request, db: Session = Depends(get_db),
                    user: models.User = Depends(require_admin)):
    cats = db.query(models.Category).order_by(models.Category.id).all()
    counts = {c.id: db.query(models.Question).filter_by(category_id=c.id, is_active=True).count()
              for c in cats}
    return render(request, db, "categories.html", user=user, categories=cats, counts=counts)


@router.post("/categories/create")
def category_create(name: str = Form(...), is_regular: str = Form("on"),
                    on_wheel: str = Form("on"), db: Session = Depends(get_db),
                    user: models.User = Depends(require_admin)):
    if not db.query(models.Category).filter_by(name=name.strip()).first():
        db.add(models.Category(name=name.strip(), is_regular=(is_regular == "on"),
                               on_wheel=(on_wheel == "on")))
        db.commit()
        security.audit(db, user.id, "create_category", name)
    return RedirectResponse("/categories", 302)


@router.post("/categories/bulk-create")
def category_bulk_create(names: list[str] = Form(default=[]),
                         is_regular: str = Form("on"), on_wheel: str = Form("on"),
                         db: Session = Depends(get_db),
                         user: models.User = Depends(require_admin)):
    seen: set[str] = set()
    created = 0
    for raw in names:
        name = (raw or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        if db.query(models.Category).filter_by(name=name).first():
            continue
        db.add(models.Category(name=name,
                               is_regular=(is_regular == "on"),
                               on_wheel=(on_wheel == "on")))
        created += 1
    if created:
        db.commit()
        security.audit(db, user.id, "bulk_create_categories", f"n={created}")
    return RedirectResponse("/categories", 302)


@router.post("/categories/{cid}/toggle-regular")
def category_toggle_regular(cid: int, db: Session = Depends(get_db),
                            user: models.User = Depends(require_admin)):
    cat = db.get(models.Category, cid)
    if cat:
        cat.is_regular = not cat.is_regular
        db.commit()
    return RedirectResponse("/categories", 302)


@router.post("/categories/{cid}/toggle-wheel")
def category_toggle_wheel(cid: int, db: Session = Depends(get_db),
                          user: models.User = Depends(require_admin)):
    cat = db.get(models.Category, cid)
    if cat:
        cat.on_wheel = not cat.on_wheel
        db.commit()
    return RedirectResponse("/categories", 302)


@router.post("/categories/{cid}/rename")
def category_rename(cid: int, name: str = Form(...),
                    db: Session = Depends(get_db),
                    user: models.User = Depends(require_admin)):
    cat = db.get(models.Category, cid)
    new_name = (name or "").strip()
    if cat and new_name:
        existing = db.query(models.Category).filter(
            models.Category.name == new_name,
            models.Category.id != cid,
        ).first()
        if not existing:
            cat.name = new_name
            db.commit()
            security.audit(db, user.id, "rename_category", f"id={cid} name={new_name}")
    return RedirectResponse("/categories", 302)


@router.post("/categories/{cid}/delete")
def category_delete(cid: int, db: Session = Depends(get_db),
                    user: models.User = Depends(require_admin)):
    cat = db.get(models.Category, cid)
    if cat:
        # Safe delete: only when the category is empty. Otherwise the admin
        # must first reassign or delete its questions.
        used = db.query(models.Question).filter_by(category_id=cid).count()
        if used == 0:
            name = cat.name
            db.delete(cat)
            db.commit()
            security.audit(db, user.id, "delete_category", f"id={cid} name={name}")
    return RedirectResponse("/categories", 302)


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #
@router.get("/questions", response_class=HTMLResponse)
def questions_page(request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_admin)):
    cats = db.query(models.Category).order_by(models.Category.id).all()
    counts = {c.id: db.query(models.Question).filter_by(category_id=c.id, is_active=True).count()
              for c in cats}
    imports = db.query(models.QuestionImport).order_by(models.QuestionImport.created_at.desc()).limit(10).all()
    from . import question_store as qs
    questions = (
        db.query(models.Question)
        .order_by(models.Question.category_id, models.Question.id.desc())
        .limit(500)
        .all()
    )
    q_rows = []
    for q in questions:
        content = qs.render_question(db, q, include_answer=True) or {}
        src = q.source
        q_rows.append({
            "id": q.id,
            "category_id": q.category_id,
            "code": q.question_code,
            "qtype": q.qtype,
            "text": (content.get("text") or "").strip(),
            "answer": (content.get("answer") or "").strip(),
            "choices": content.get("choices") or [],
            "explanation": (content.get("explanation") or "").strip(),
            "difficulty": q.difficulty or "",
            "is_active": q.is_active,
            "source_kind": src.kind if src else "import",
        })
    return render(request, db, "questions.html", user=user, categories=cats, counts=counts,
                  imports=imports, summary=None, questions=q_rows)


@router.post("/questions/manual")
def question_manual(request: Request, category_id: int = Form(...), text: str = Form(...),
                    qtype: str = Form("mc"), a: str = Form(""), b: str = Form(""),
                    c: str = Form(""), d: str = Form(""), answer: str = Form(...),
                    explanation: str = Form(""), difficulty: str = Form(""),
                    db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    from . import manual_questions
    cat = db.get(models.Category, category_id)
    if cat:
        manual_questions.add_manual_question(db, cat, text.strip(), qtype,
                                             [a, b, c, d], answer.strip(), explanation, difficulty)
        security.audit(db, user.id, "manual_question", cat.name)
    return RedirectResponse("/questions", 302)


@router.post("/questions/import")
async def questions_import(request: Request, category_id: int = Form(...),
                           file: UploadFile = File(...), db: Session = Depends(get_db),
                           user: models.User = Depends(require_admin)):
    from . import excel_import
    cat = db.get(models.Category, category_id)
    summary = await _save_and_run(
        file, lambda p, n: excel_import.import_questions_workbook(db, p, n, cat, user.id))
    # Re-render the full questions page (with the manage table) instead of a
    # thin summary-only shell so the admin can immediately review results.
    cats = db.query(models.Category).order_by(models.Category.id).all()
    counts = {c.id: db.query(models.Question).filter_by(category_id=c.id, is_active=True).count()
              for c in cats}
    imports = db.query(models.QuestionImport).order_by(models.QuestionImport.created_at.desc()).limit(10).all()
    from . import question_store as qs
    questions = (
        db.query(models.Question)
        .order_by(models.Question.category_id, models.Question.id.desc())
        .limit(500)
        .all()
    )
    q_rows = []
    for q in questions:
        content = qs.render_question(db, q, include_answer=True) or {}
        src = q.source
        q_rows.append({
            "id": q.id,
            "category_id": q.category_id,
            "code": q.question_code,
            "qtype": q.qtype,
            "text": (content.get("text") or "").strip(),
            "answer": (content.get("answer") or "").strip(),
            "choices": content.get("choices") or [],
            "explanation": (content.get("explanation") or "").strip(),
            "difficulty": q.difficulty or "",
            "is_active": q.is_active,
            "source_kind": src.kind if src else "import",
        })
    return render(request, db, "questions.html", user=user, categories=cats, counts=counts,
                  imports=imports, summary=summary, questions=q_rows)


@router.post("/questions/{qid}/toggle-active")
def question_toggle_active(qid: int, db: Session = Depends(get_db),
                           user: models.User = Depends(require_admin)):
    q = db.get(models.Question, qid)
    if q:
        q.is_active = not q.is_active
        db.commit()
        security.audit(db, user.id, "toggle_question_active", f"q={qid} active={q.is_active}")
    return RedirectResponse("/questions", 302)


@router.post("/questions/{qid}/move")
def question_move(qid: int, category_id: int = Form(...),
                  db: Session = Depends(get_db),
                  user: models.User = Depends(require_admin)):
    q = db.get(models.Question, qid)
    cat = db.get(models.Category, category_id)
    if q and cat:
        q.category_id = cat.id
        db.commit()
        security.audit(db, user.id, "move_question", f"q={qid} to={cat.name}")
    return RedirectResponse("/questions", 302)


@router.post("/questions/{qid}/delete")
def question_delete(qid: int, db: Session = Depends(get_db),
                    user: models.User = Depends(require_admin)):
    q = db.get(models.Question, qid)
    if q:
        code = q.question_code
        # Referenced by QuestionUsage rows — soft delete (deactivate) if the
        # question has ever been used so historical reports remain intact.
        used = db.query(models.QuestionUsage).filter_by(question_id=qid).first()
        if used:
            q.is_active = False
        else:
            db.delete(q)
        db.commit()
        security.audit(db, user.id, "delete_question", f"q={qid} code={code} soft={bool(used)}")
    return RedirectResponse("/questions", 302)


@router.post("/questions/{qid}/edit")
def question_edit(qid: int, text: str = Form(...), qtype: str = Form("mc"),
                  a: str = Form(""), b: str = Form(""),
                  c: str = Form(""), d: str = Form(""),
                  answer: str = Form(...), explanation: str = Form(""),
                  difficulty: str = Form(""),
                  db: Session = Depends(get_db),
                  user: models.User = Depends(require_admin)):
    from . import manual_questions
    q = db.get(models.Question, qid)
    if not q:
        return RedirectResponse("/questions", 302)
    src = q.source
    if not src or src.kind != "manual":
        # Imported workbooks are immutable — refuse to rewrite them.
        return RedirectResponse("/questions", 302)
    manual_questions.edit_manual_question(
        db, q, text.strip(), qtype, [a, b, c, d], answer.strip(), explanation, difficulty,
    )
    security.audit(db, user.id, "edit_question", f"q={qid} code={q.question_code}")
    return RedirectResponse("/questions", 302)


# --------------------------------------------------------------------------- #
# Tournaments
# --------------------------------------------------------------------------- #
@router.get("/tournaments", response_class=HTMLResponse)
def tournaments_page(request: Request, db: Session = Depends(get_db),
                     user: models.User = Depends(require_admin)):
    tournaments = db.query(models.Tournament).order_by(models.Tournament.created_at.desc()).all()
    return render(request, db, "tournaments.html", user=user, tournaments=tournaments)


@router.post("/tournaments/create")
def tournament_create(name: str = Form(...), description: str = Form(""),
                      start_date: str = Form(""), end_date: str = Form(""),
                      db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    def parse(d):
        try:
            return dt.datetime.strptime(d, "%Y-%m-%d")
        except Exception:
            return None
    t = models.Tournament(name=name.strip(), description=description,
                          start_date=parse(start_date), end_date=parse(end_date), status="draft")
    db.add(t)
    db.commit()
    security.audit(db, user.id, "create_tournament", t.name)
    return RedirectResponse(f"/tournaments/{t.id}", 302)


@router.get("/tournaments/{tid}", response_class=HTMLResponse)
def tournament_detail(tid: int, request: Request, db: Session = Depends(get_db),
                      user: models.User = Depends(require_admin)):
    t = db.get(models.Tournament, tid)
    if not t:
        return RedirectResponse("/tournaments", 302)
    all_teams = db.query(models.Team).filter_by(is_active=True).order_by(models.Team.name).all()
    part_ids = {tt.team_id for tt in t.teams}
    group_tables = []
    for g in t.groups:
        group_tables.append({"group": g, "rows": standings_mod.compute_group_standings(db, t, g)})
    # team_id -> 0-based group index (for the manual assignment form)
    group_index_by_team: dict[int, int] = {}
    for i, g in enumerate(t.groups):
        for gm in g.members:
            group_index_by_team[gm.team_id] = i
    hosts = db.query(models.User).join(models.Role).filter(models.Role.name == config.ROLE_HOST).all()
    bracket = _bracket_view(db, t)
    return render(request, db, "tournament_detail.html", user=user, tour=t, all_teams=all_teams,
                  part_ids=part_ids, group_tables=group_tables, hosts=hosts, bracket=bracket,
                  matches=t.matches, group_index_by_team=group_index_by_team)


def _bracket_view(db: Session, t: models.Tournament):
    rounds = db.query(models.BracketRound).filter_by(tournament_id=t.id).order_by(
        models.BracketRound.order_index).all()
    view = []
    for r in rounds:
        slots = db.query(models.BracketSlot).filter_by(round_id=r.id).order_by(
            models.BracketSlot.position).all()
        srows = []
        for s in slots:
            ta = db.get(models.Team, s.team_a_id) if s.team_a_id else None
            tb = db.get(models.Team, s.team_b_id) if s.team_b_id else None
            match = db.get(models.Match, s.match_id) if s.match_id else None
            srows.append({"slot": s, "team_a": ta, "team_b": tb, "match": match})
        view.append({"round": r, "slots": srows})
    return view


@router.post("/tournaments/{tid}/add-team")
def tournament_add_team(tid: int, team_id: int = Form(...), db: Session = Depends(get_db),
                        user: models.User = Depends(require_admin)):
    if not db.query(models.TournamentTeam).filter_by(tournament_id=tid, team_id=team_id).first():
        db.add(models.TournamentTeam(tournament_id=tid, team_id=team_id))
        db.commit()
    return RedirectResponse(f"/tournaments/{tid}", 302)


@router.post("/tournaments/{tid}/add-teams")
def tournament_add_teams(tid: int, team_ids: list[int] = Form(default=[]),
                         db: Session = Depends(get_db),
                         user: models.User = Depends(require_admin)):
    added = 0
    for team_id in team_ids:
        if not team_id:
            continue
        exists = db.query(models.TournamentTeam).filter_by(
            tournament_id=tid, team_id=team_id).first()
        if exists:
            continue
        db.add(models.TournamentTeam(tournament_id=tid, team_id=team_id))
        added += 1
    if added:
        db.commit()
        security.audit(db, user.id, "bulk_add_teams", f"t={tid} n={added}")
    return RedirectResponse(f"/tournaments/{tid}", 302)


@router.post("/tournaments/{tid}/remove-team/{team_id}")
def tournament_remove_team(tid: int, team_id: int,
                           db: Session = Depends(get_db),
                           user: models.User = Depends(require_admin)):
    row = db.query(models.TournamentTeam).filter_by(
        tournament_id=tid, team_id=team_id).first()
    if row:
        db.delete(row)
        db.commit()
        security.audit(db, user.id, "remove_team", f"t={tid} team={team_id}")
    return RedirectResponse(f"/tournaments/{tid}", 302)


@router.post("/tournaments/{tid}/activate")
def tournament_activate(tid: int, db: Session = Depends(get_db),
                        user: models.User = Depends(require_admin)):
    t = db.get(models.Tournament, tid)
    if t:
        t.status = "active"
        db.commit()
    return RedirectResponse(f"/tournaments/{tid}", 302)


@router.post("/tournaments/{tid}/generate-groups")
def tournament_generate_groups(tid: int, num_groups: int = Form(1),
                               db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    from .services import generate_groups
    generate_groups(db, tid, num_groups)
    security.audit(db, user.id, "generate_groups", f"t={tid} n={num_groups}")
    return RedirectResponse(f"/tournaments/{tid}", 302)


@router.post("/tournaments/{tid}/generate-groups-sequential")
def tournament_generate_groups_sequential(
        tid: int, teams_per_group: int = Form(4),
        also_matches: str = Form(""),
        redirect_to: str = Form(""),
        db: Session = Depends(get_db),
        user: models.User = Depends(require_admin)):
    """Sequential fill: first N teams -> group A, next N -> group B, etc."""
    from .services import generate_groups_sequential, generate_group_matches
    generate_groups_sequential(db, tid, teams_per_group)
    if also_matches:
        generate_group_matches(db, tid)
    security.audit(db, user.id, "generate_groups_seq",
                   f"t={tid} per={teams_per_group} matches={bool(also_matches)}")
    return RedirectResponse(redirect_to or f"/tournaments/{tid}", 302)


@router.post("/tournaments/{tid}/generate-group-matches")
def tournament_group_matches(tid: int, db: Session = Depends(get_db),
                             user: models.User = Depends(require_admin)):
    from .services import generate_group_matches
    generate_group_matches(db, tid)
    return RedirectResponse(f"/tournaments/{tid}", 302)


@router.post("/tournaments/{tid}/generate-bracket")
def tournament_generate_bracket(tid: int, qualifiers: int = Form(2),
                                db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    from .services import generate_knockout
    generate_knockout(db, tid, qualifiers)
    return RedirectResponse(f"/tournaments/{tid}", 302)


@router.post("/tournaments/{tid}/auto-build")
def tournament_auto_build(tid: int, num_groups: int = Form(1), qualifiers: int = Form(2),
                          include_bracket: str = Form(""),
                          redirect_to: str = Form("/matches"),
                          db: Session = Depends(get_db),
                          user: models.User = Depends(require_admin)):
    """One-shot random build: groups + all pair matches + optional bracket."""
    from .services import generate_groups, generate_group_matches, generate_knockout
    generate_groups(db, tid, max(1, num_groups))
    generate_group_matches(db, tid)
    if include_bracket:
        generate_knockout(db, tid, max(1, qualifiers))
    security.audit(db, user.id, "auto_build",
                   f"t={tid} groups={num_groups} q={qualifiers} bracket={bool(include_bracket)}")
    return RedirectResponse(redirect_to, 302)


@router.post("/tournaments/{tid}/groups/assign")
async def tournament_groups_assign(tid: int, request: Request,
                                   db: Session = Depends(get_db),
                                   user: models.User = Depends(require_admin)):
    """Assign teams to specific groups. Form fields: team_group_<team_id> = <0-based idx>."""
    form = await request.form()
    assignments: dict[int, int] = {}
    for key, value in form.multi_items():
        if not key.startswith("team_group_"):
            continue
        try:
            team_id = int(key.split("_")[-1])
            idx = int(value)
        except (ValueError, TypeError):
            continue
        if idx < 0:
            continue
        assignments[team_id] = idx
    from .services import assign_teams_to_groups
    assign_teams_to_groups(db, tid, assignments)
    security.audit(db, user.id, "manual_groups",
                   f"t={tid} teams={len(assignments)}")
    redirect_to = str(form.get("redirect_to") or "/matches")
    return RedirectResponse(redirect_to, 302)


@router.post("/matches/create")
def match_manual_create(request: Request,
                        tournament_id: int = Form(...),
                        team_a_id: int = Form(...),
                        team_b_id: int = Form(...),
                        stage: str = Form("group"),
                        group_id: int = Form(0),
                        round_name: str = Form(""),
                        scheduled_at: str = Form(""),
                        host_id: int = Form(0),
                        db: Session = Depends(get_db),
                        user: models.User = Depends(require_admin)):
    if team_a_id == team_b_id:
        return RedirectResponse("/matches?err=same_team", 302)
    m = models.Match(
        tournament_id=tournament_id,
        stage=stage or "group",
        group_id=group_id or None,
        round_name=round_name or None,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        host_id=host_id or None,
        status="scheduled",
    )
    if scheduled_at:
        try:
            m.scheduled_at = dt.datetime.strptime(scheduled_at, "%Y-%m-%dT%H:%M")
        except Exception:
            pass
    if m.host_id and m.team_a_id and m.team_b_id:
        m.status = "ready"
    db.add(m)
    db.commit()
    security.audit(db, user.id, "manual_match",
                   f"t={tournament_id} a={team_a_id} b={team_b_id}")
    return RedirectResponse("/matches", 302)


@router.post("/matches/{mid}/delete")
def match_delete(mid: int, db: Session = Depends(get_db),
                 user: models.User = Depends(require_admin)):
    m = db.get(models.Match, mid)
    if m and m.status in ("scheduled", "ready"):
        db.delete(m)
        db.commit()
        security.audit(db, user.id, "delete_match", f"m={mid}")
    return RedirectResponse("/matches", 302)


@router.post("/matches/{mid}/restart-ready")
def match_restart_ready(mid: int, db: Session = Depends(get_db),
                        user: models.User = Depends(require_admin)):
    m = db.get(models.Match, mid)
    if not m:
        return RedirectResponse("/matches", 302)

    if m.session:
        db.query(models.QuestionUsage).filter_by(session_id=m.session.id).delete(synchronize_session=False)
        m.session.current_section = 0
        m.session.state_json = None
        m.session.status = "ready"
    else:
        m.session = models.GameSession(status="ready")

    db.query(models.ScoreEvent).filter_by(match_id=m.id).delete(synchronize_session=False)
    db.query(models.MatchResult).filter_by(match_id=m.id).delete(synchronize_session=False)

    m.status = "ready"
    m.score_a = 0
    m.score_b = 0
    m.winner_team_id = None
    m.is_draw = False
    m.points_a = 0
    m.points_b = 0
    m.started_at = None
    m.completed_at = None
    db.add(m)
    db.commit()
    security.audit(db, user.id, "restart_match_ready", f"m={mid}")
    return RedirectResponse("/matches", 302)


@router.post("/matches/{mid}/edit")
def match_edit(mid: int,
               team_a_id: int = Form(...),
               team_b_id: int = Form(...),
               stage: str = Form("group"),
               group_id: int = Form(0),
               round_name: str = Form(""),
               scheduled_at: str = Form(""),
               host_id: int = Form(0),
               db: Session = Depends(get_db),
               user: models.User = Depends(require_admin)):
    m = db.get(models.Match, mid)
    if not m:
        return RedirectResponse("/matches", 302)
    if m.status not in ("scheduled", "ready"):
        return RedirectResponse("/matches?err=locked", 302)
    if team_a_id == team_b_id:
        return RedirectResponse("/matches?err=same_team", 302)
    m.team_a_id = team_a_id
    m.team_b_id = team_b_id
    m.stage = stage or "group"
    m.group_id = group_id or None
    m.round_name = round_name or None
    m.host_id = host_id or None
    if scheduled_at:
        try:
            m.scheduled_at = dt.datetime.strptime(scheduled_at, "%Y-%m-%dT%H:%M")
        except Exception:
            pass
    else:
        m.scheduled_at = None
    m.status = "ready" if (m.host_id and m.team_a_id and m.team_b_id) else "scheduled"
    db.commit()
    security.audit(db, user.id, "edit_match", f"m={mid}")
    return RedirectResponse("/matches", 302)


@router.post("/groups/{gid}/rename")
def group_rename(gid: int, name: str = Form(...),
                 db: Session = Depends(get_db),
                 user: models.User = Depends(require_admin)):
    g = db.get(models.Group, gid)
    if g and name.strip():
        old = g.name
        g.name = name.strip()
        # also update round_name on group matches that referenced the old name
        db.query(models.Match).filter_by(group_id=g.id, round_name=old).update(
            {"round_name": g.name}, synchronize_session=False)
        db.commit()
        security.audit(db, user.id, "rename_group", f"g={gid}")
    tid = g.tournament_id if g else 0
    return RedirectResponse(f"/tournaments/{tid}", 302)


@router.post("/groups/{gid}/delete")
def group_delete(gid: int, db: Session = Depends(get_db),
                 user: models.User = Depends(require_admin)):
    g = db.get(models.Group, gid)
    if not g:
        return RedirectResponse("/tournaments", 302)
    tid = g.tournament_id
    # Cascade: delete matches referencing this group, then the group (GroupTeam
    # rows cascade via the FK definition).
    db.query(models.Match).filter_by(group_id=g.id).delete(synchronize_session=False)
    db.delete(g)
    db.commit()
    security.audit(db, user.id, "delete_group", f"g={gid}")
    return RedirectResponse(f"/tournaments/{tid}", 302)


# --------------------------------------------------------------------------- #
# Matches
# --------------------------------------------------------------------------- #
@router.get("/matches", response_class=HTMLResponse)
def matches_page(request: Request, db: Session = Depends(get_db),
                 user: models.User = Depends(require_admin)):
    # Order matches by their scheduled time (nulls last), then by creation
    # time as a stable tiebreaker so unscheduled matches stay grouped.
    matches = db.query(models.Match).order_by(
        models.Match.scheduled_at.is_(None),
        models.Match.scheduled_at.asc(),
        models.Match.created_at.asc(),
    ).all()
    hosts = db.query(models.User).join(models.Role).filter(models.Role.name == config.ROLE_HOST).all()
    tournaments = db.query(models.Tournament).order_by(models.Tournament.created_at.desc()).all()
    tour_data: dict[int, dict] = {}
    for t in tournaments:
        teams = [
            {"id": tt.team.id, "name": tt.team.name, "level": tt.team.level or ""}
            for tt in t.teams if tt.team
        ]
        groups = [{"id": g.id, "name": g.name,
                   "team_ids": [gm.team_id for gm in g.members]} for g in t.groups]
        tour_data[t.id] = {
            "id": t.id, "name": t.name, "teams": teams, "groups": groups,
        }
    return render(request, db, "matches.html", user=user, matches=matches,
                  hosts=hosts, tournaments=tournaments,
                  tour_data_json=json.dumps(tour_data, ensure_ascii=False))


@router.post("/matches/{mid}/assign")
def match_assign(mid: int, host_id: int = Form(...), scheduled_at: str = Form(""),
                 db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    m = db.get(models.Match, mid)
    if m:
        m.host_id = host_id or None
        try:
            m.scheduled_at = dt.datetime.strptime(scheduled_at, "%Y-%m-%dT%H:%M") if scheduled_at else None
        except Exception:
            pass
        if m.status == "scheduled" and m.host_id and m.team_a_id and m.team_b_id:
            m.status = "ready"
        db.commit()
        security.audit(db, user.id, "assign_match", f"m={mid} host={host_id}")
    return RedirectResponse("/matches", 302)


@router.get("/my-matches", response_class=HTMLResponse)
def my_matches(request: Request, db: Session = Depends(get_db),
               user: models.User = Depends(require_login)):
    matches = db.query(models.Match).filter(models.Match.host_id == user.id).order_by(
        models.Match.scheduled_at.is_(None), models.Match.scheduled_at).all()
    return render(request, db, "my_matches.html", user=user, matches=matches)


@router.get("/matches/{mid}/score", response_class=HTMLResponse)
def match_score_page(mid: int, request: Request, db: Session = Depends(get_db),
                     user: models.User = Depends(require_login)):
    m = db.get(models.Match, mid)
    if not m:
        return RedirectResponse("/", 302)
    if not security.can_access_match(user, m):
        return HTMLResponse("<h1>403</h1>", status_code=403)
    if m.status != "completed":
        return RedirectResponse(f"/game/{m.id}", 302)

    events = (
        db.query(models.ScoreEvent)
        .filter(models.ScoreEvent.match_id == m.id)
        .order_by(models.ScoreEvent.created_at.asc(), models.ScoreEvent.id.asc())
        .all()
    )
    section_order = sorted(scoring.SECTION_NAMES)
    section_totals: dict[int, dict] = {}
    team_breakdowns = {
        "a": {
            "name": m.team_a.name if m.team_a else "—",
            "score": m.score_a,
            "sections": {
                sec: {"section": sec, "name": scoring.SECTION_NAMES[sec], "total": 0, "events": []}
                for sec in section_order
            },
        },
        "b": {
            "name": m.team_b.name if m.team_b else "—",
            "score": m.score_b,
            "sections": {
                sec: {"section": sec, "name": scoring.SECTION_NAMES[sec], "total": 0, "events": []}
                for sec in section_order
            },
        },
    }
    rows = []
    for e in events:
        q = db.get(models.Question, e.question_id) if e.question_id else None
        cat = db.get(models.Category, q.category_id) if q else None
        team_side = "a" if e.team_id == m.team_a_id else "b" if e.team_id == m.team_b_id else ""
        team_name = m.team_a.name if team_side == "a" and m.team_a else (
            m.team_b.name if team_side == "b" and m.team_b else "—"
        )
        sec = e.section or 0
        if sec not in section_totals:
            section_totals[sec] = {
                "section": sec,
                "name": scoring.SECTION_NAMES.get(sec, "—"),
                "a": 0,
                "b": 0,
        }
        if team_side in ("a", "b"):
            section_totals[sec][team_side] += e.delta
        row = {
            "event": e,
            "team_side": team_side,
            "team_name": team_name,
            "question_code": q.question_code if q else "—",
            "category": cat.name if cat else "—",
            "section_name": scoring.SECTION_NAMES.get(sec, "—"),
        }
        rows.append(row)
        if team_side in ("a", "b") and sec in team_breakdowns[team_side]["sections"]:
            team_breakdowns[team_side]["sections"][sec]["total"] += e.delta
            team_breakdowns[team_side]["sections"][sec]["events"].append(row)

    winner_name = ""
    if m.winner_team_id == m.team_a_id and m.team_a:
        winner_name = m.team_a.name
    elif m.winner_team_id == m.team_b_id and m.team_b:
        winner_name = m.team_b.name

    return render(
        request, db, "match_score.html",
        user=user, match=m, rows=rows,
        section_totals=sorted(section_totals.values(), key=lambda x: x["section"]),
        team_breakdowns=team_breakdowns,
        section_order=section_order,
        winner_name=winner_name,
    )


@router.get("/game/{mid}", response_class=HTMLResponse)
def game_screen(mid: int, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(require_login)):
    m = db.get(models.Match, mid)
    if not m:
        return RedirectResponse("/", 302)
    if not security.can_access_match(user, m):
        return HTMLResponse("<h1>403</h1>", status_code=403)
    # Ensure a game session exists but do NOT auto-start the match here — the
    # host must click the explicit "Start Match" button so opening the page
    # is non-destructive and can be reversed to ready state.
    if not m.session:
        m.session = models.GameSession(status="ready")
        db.commit()
    return render(request, db, "game.html", user=user, match=m)


# --------------------------------------------------------------------------- #
# Users / settings / reports
# --------------------------------------------------------------------------- #
@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db),
               user: models.User = Depends(require_admin)):
    users = db.query(models.User).order_by(models.User.id).all()
    roles = db.query(models.Role).all()
    return render(request, db, "users.html", user=user, users=users, roles=roles)


@router.post("/users/create")
def user_create(username: str = Form(...), display_name: str = Form(...),
                password: str = Form(...), role_id: int = Form(...),
                db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    if not db.query(models.User).filter_by(username=username.strip()).first():
        db.add(models.User(username=username.strip(), display_name=display_name.strip(),
                           password_hash=security.hash_password(password), role_id=role_id))
        db.commit()
        security.audit(db, user.id, "create_user", username)
    return RedirectResponse("/users", 302)


@router.post("/users/{uid}/toggle")
def user_toggle(uid: int, db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    u = db.get(models.User, uid)
    if u and u.id != user.id:
        u.is_active = not u.is_active
        db.commit()
    return RedirectResponse("/users", 302)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db),
                  user: models.User = Depends(require_admin)):
    default_lang = i18n.get_default_language(db)
    return render(request, db, "settings.html", user=user, default_lang=default_lang)


@router.post("/settings/language")
def settings_language(lang: str = Form(...), db: Session = Depends(get_db),
                      user: models.User = Depends(require_admin)):
    try:
        i18n.set_default_language(db, lang)
        security.audit(db, user.id, "set_default_language", lang)
    except ValueError:
        pass
    return RedirectResponse("/settings", 302)


@router.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, db: Session = Depends(get_db),
                 user: models.User = Depends(require_admin)):
    tournaments = db.query(models.Tournament).all()
    score_matches = db.query(models.Match).filter(
        models.Match.status == "completed"
    ).order_by(
        models.Match.completed_at.is_(None),
        models.Match.completed_at.desc(),
        models.Match.created_at.desc(),
    ).all()
    return render(request, db, "reports.html", user=user, tournaments=tournaments,
                  score_matches=score_matches)


# --------------------------------------------------------------------------- #
# Upload helper
# --------------------------------------------------------------------------- #
async def _save_and_run(file: UploadFile, fn):
    import uuid
    from pathlib import Path
    ext = Path(file.filename or "").suffix.lower()
    tmp = config.UPLOAD_TMP / f"{uuid.uuid4().hex}{ext}"
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_BYTES:
        return {"errors": ["file_too_large"]}
    with open(tmp, "wb") as fh:
        fh.write(data)
    try:
        return fn(tmp, file.filename or "upload.xlsx")
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass
