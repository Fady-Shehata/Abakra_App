"""First-run seeding: roles, default admin, categories, default language."""
from __future__ import annotations

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

        _auto_import_initial_workbooks(db)
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
