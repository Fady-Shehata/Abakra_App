"""First-run seeding: roles, default admin, categories, default language."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import config, models, security
from .database import SessionLocal

REGULAR_CATEGORIES = [
    "كتاب لاهوت",
    "رسالة العبرانيين",
    "كتاب المجامع",
    "طقس",
    "قدرات ذهنية",
    "معلومات عامة",
]
SPECIAL_CATEGORY = "أبونا بيسأل"
EHED_CLEANUP_KEY = "data_cleanup_ehbed_sah_v1"

# Category name -> initial workbook (best-effort auto-import on first run)
INITIAL_WORKBOOKS = {
    "كتاب لاهوت": "output/final/Divinity_of_Christ_300_Questions.xlsx",
    "رسالة العبرانيين": "output/final/رسالة_العبرانين1_اختر_الاجابة_الصحيحة.xlsx",
    "كتاب المجامع": "output/final/بنك_الأسئلة_المجامع_الكنسية.xlsx",
    "قدرات ذهنية": "output/final/قدرات_ذهنية.xlsx",
    "معلومات عامة": "output/final/معلومات_عامة.xlsx",
}


def seed_initial_data() -> None:
    db = SessionLocal()
    try:
        # Roles
        for rname, desc in [(config.ROLE_ADMIN, "Administrator"), (config.ROLE_HOST, "Game Host")]:
            if not db.query(models.Role).filter_by(name=rname).first():
                db.add(models.Role(name=rname, description=desc))
        db.commit()

        admin_role = db.query(models.Role).filter_by(name=config.ROLE_ADMIN).first()
        host_role = db.query(models.Role).filter_by(name=config.ROLE_HOST).first()

        # Default admin (password from env or default; must be changed)
        if not db.query(models.User).filter_by(username="admin").first():
            pwd = os.environ.get("ABAKRA_ADMIN_PASSWORD", "admin123")
            db.add(models.User(
                username="admin", display_name="المسؤول",
                password_hash=security.hash_password(pwd), role_id=admin_role.id,
            ))
        # Sample host
        if not db.query(models.User).filter_by(username="host").first():
            pwd = os.environ.get("ABAKRA_HOST_PASSWORD", "host123")
            db.add(models.User(
                username="host", display_name="خادم",
                password_hash=security.hash_password(pwd), role_id=host_role.id,
            ))
        db.commit()

        # Default language setting
        if not db.get(models.ApplicationSetting, "default_language"):
            db.add(models.ApplicationSetting(key="default_language", value=config.DEFAULT_LANGUAGE))
            db.commit()

        # Categories
        for name in REGULAR_CATEGORIES:
            if not db.query(models.Category).filter_by(name=name).first():
                db.add(models.Category(name=name, is_regular=True, on_wheel=True))
        if not db.query(models.Category).filter_by(name=SPECIAL_CATEGORY).first():
            db.add(models.Category(name=SPECIAL_CATEGORY, is_regular=False, on_wheel=False))
        db.commit()

        _remove_ehbed_questions(db)
        _auto_import_initial_workbooks(db)
        _sync_updated_theology_workbook(db)
        _verify_deployment_question_data(db)
    finally:
        db.close()


def _auto_import_initial_workbooks(db) -> None:
    """Import bundled workbooks once, if their category has no questions yet."""
    if os.environ.get("ABAKRA_SKIP_AUTOIMPORT"):
        return
    from . import excel_import
    for cat_name, rel in INITIAL_WORKBOOKS.items():
        cat = db.query(models.Category).filter_by(name=cat_name).first()
        if not cat:
            continue
        has_q = db.query(models.Question).filter_by(category_id=cat.id).first()
        if has_q:
            continue
        path = config.BASE_DIR / rel
        if not path.exists():
            continue
        try:
            excel_import.import_questions_workbook(db, path, path.name, cat, user_id=None)
        except Exception:
            # never break startup on import issues
            db.rollback()


def _remove_ehbed_questions(db) -> int:
    """One-time cleanup for estimate questions imported by the retired section."""
    if os.environ.get("ABAKRA_SKIP_AUTOIMPORT") or db.get(models.ApplicationSetting, EHED_CLEANUP_KEY):
        return 0
    questions = db.query(models.Question).filter_by(qtype="estimate").all()
    question_ids = [q.id for q in questions]
    source_ids = {q.source_id for q in questions}
    stored_paths: list[Path] = []

    if question_ids:
        db.query(models.ScoreEvent).filter(
            models.ScoreEvent.question_id.in_(question_ids)
        ).update({"question_id": None}, synchronize_session=False)
        db.query(models.QuestionUsage).filter(
            models.QuestionUsage.question_id.in_(question_ids)
        ).delete(synchronize_session=False)
        for session in db.query(models.GameSession).filter(models.GameSession.state_json.isnot(None)).all():
            try:
                state = json.loads(session.state_json)
            except (TypeError, json.JSONDecodeError):
                continue
            changed = False
            if state.get("current_section") == 6:
                state["current_section"] = 0
                session.current_section = 0
                changed = True
            if (state.get("current") or {}).get("question_id") in question_ids:
                state["current"] = None
                state["buzzer"] = {"locked": False, "team": None}
                changed = True
            if state.get("sections", {}).pop("6", None) is not None:
                changed = True
            if changed:
                session.state_json = json.dumps(state, ensure_ascii=False)
        db.query(models.Question).filter(models.Question.id.in_(question_ids)).delete(synchronize_session=False)

    for source_id in source_ids:
        if db.query(models.Question).filter_by(source_id=source_id).first():
            continue
        source = db.get(models.QuestionSource, source_id)
        if source:
            stored_paths.append(config.WORKBOOK_STORE / source.stored_filename)
        db.query(models.QuestionImport).filter_by(source_id=source_id).delete(synchronize_session=False)
        if source:
            db.delete(source)

    db.add(models.ApplicationSetting(key=EHED_CLEANUP_KEY, value=str(len(question_ids))))
    db.commit()
    for path in stored_paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return len(question_ids)


def _sync_updated_theology_workbook(db) -> dict | None:
    """Import only workbook rows not already in the production question bank."""
    if os.environ.get("ABAKRA_SKIP_AUTOIMPORT"):
        return None
    from . import excel_import, question_store as qs
    path = config.BASE_DIR / INITIAL_WORKBOOKS["كتاب لاهوت"]
    category = db.query(models.Category).filter_by(name="كتاب لاهوت").first()
    if not category or not path.exists():
        return None
    current_hash = qs.file_hash(path)
    already_synced = db.query(models.QuestionSource).filter_by(
        original_name=path.name, file_hash=current_hash
    ).first()
    if already_synced:
        return None
    try:
        return excel_import.import_questions_workbook(db, path, path.name, category, user_id=None)
    except Exception:
        db.rollback()
        return None


def _verify_deployment_question_data(db) -> None:
    """Fail startup if the requested production question state was not reached."""
    if os.environ.get("ABAKRA_SKIP_AUTOIMPORT"):
        return
    from . import question_store as qs
    estimate_count = db.query(models.Question).filter_by(qtype="estimate").count()
    category = db.query(models.Category).filter_by(name="كتاب لاهوت").first()
    theology_count = (
        db.query(models.Question).filter_by(category_id=category.id).count() if category else 0
    )
    path = config.BASE_DIR / INITIAL_WORKBOOKS["كتاب لاهوت"]
    current_source = None
    if path.exists():
        current_source = db.query(models.QuestionSource).filter_by(
            original_name=path.name, file_hash=qs.file_hash(path)
        ).first()
    if estimate_count or theology_count < 81 or not current_source:
        raise RuntimeError(
            f"question data verification failed: estimate={estimate_count}, theology={theology_count}, "
            f"current_theology_source={bool(current_source)}"
        )
