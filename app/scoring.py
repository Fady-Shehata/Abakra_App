"""Scoring rules and section definitions for quiz sections.

CRITICAL RULES:
- Normal correct answer = 5 points.
- Rebound correct (opponent) = 10 points; original team gets 0.
- Failed rebound = 0 for both.
- فردي (individual): correct = 5, NO rebound, wrong = 0 for both.
- أبونا بيسأل: open to both teams, first correct team = 10, no rebound.
"""
from __future__ import annotations

import json

NORMAL_POINTS = 5
REBOUND_POINTS = 10
FATHER_POINTS = 10

MENTAL_CATEGORY = "قدرات ذهنية"

SECTION_NAMES = {
    1: "الجماعي بوقت",
    2: "الجماعي سرعة",
    3: "فردي",
    4: "عجلة الحظ",
    5: "أبونا بيسأل",
}

# section -> whether a rebound is permitted after a wrong original answer
SECTION_REBOUND = {1: True, 2: True, 3: False, 4: True, 5: False}
SECTION_TIMED = {1: True, 2: False, 3: False, 4: False, 5: False}
SECTION_BUZZER = {1: False, 2: True, 3: True, 4: False, 5: False}

SECTION_CONFIG_KEY = "section_config_v1"
DEFAULT_SECTION_ORDER = [1, 2, 5, 3, 4]

SECTION_TEMPLATES = {
    1: {"id": 1, "name": SECTION_NAMES[1], "label": "Timed team"},
    2: {"id": 2, "name": SECTION_NAMES[2], "label": "Speed team"},
    3: {"id": 3, "name": SECTION_NAMES[3], "label": "Individual"},
    4: {"id": 4, "name": SECTION_NAMES[4], "label": "Wheel"},
    5: {"id": 5, "name": SECTION_NAMES[5], "label": "Father asks"},
}


def default_section_config() -> list[dict]:
    return [
        {
            "id": sid,
            "name": SECTION_NAMES[sid],
            "order": i + 1,
            "template_id": sid,
            "enabled": True,
            "built_in": True,
        }
        for i, sid in enumerate(DEFAULT_SECTION_ORDER)
    ]


def _clean_section(row: dict, fallback_order: int) -> dict:
    try:
        sid = int(row.get("id"))
    except (TypeError, ValueError):
        sid = 0
    try:
        template_id = int(row.get("template_id", sid))
    except (TypeError, ValueError):
        template_id = sid
    if template_id not in SECTION_TEMPLATES:
        template_id = sid if sid in SECTION_TEMPLATES else 2
    try:
        order = int(row.get("order", fallback_order))
    except (TypeError, ValueError):
        order = fallback_order
    default_name = SECTION_NAMES.get(sid) or SECTION_TEMPLATES[template_id]["name"]
    return {
        "id": sid,
        "name": (row.get("name") or default_name).strip() or default_name,
        "order": order,
        "template_id": template_id,
        "enabled": bool(row.get("enabled", True)),
        "built_in": bool(row.get("built_in", sid in SECTION_NAMES)),
    }


def normalize_section_config(rows: list[dict] | None) -> list[dict]:
    defaults = {row["id"]: row for row in default_section_config()}
    cleaned: dict[int, dict] = {}
    for index, row in enumerate(rows or [], start=1):
        item = _clean_section(row, index)
        if item["id"] > 0:
            cleaned[item["id"]] = item
    for sid, row in defaults.items():
        cleaned.setdefault(sid, row)
    return sorted(cleaned.values(), key=lambda row: (row["order"], row["id"]))


def load_section_config(db, include_disabled: bool = True) -> list[dict]:
    from . import models
    setting = db.get(models.ApplicationSetting, SECTION_CONFIG_KEY)
    rows = None
    if setting:
        try:
            rows = json.loads(setting.value)
        except json.JSONDecodeError:
            rows = None
    config = normalize_section_config(rows)
    if include_disabled:
        return config
    return [row for row in config if row["enabled"]]


def save_section_config(db, rows: list[dict]) -> None:
    from . import models
    value = json.dumps(normalize_section_config(rows), ensure_ascii=False)
    setting = db.get(models.ApplicationSetting, SECTION_CONFIG_KEY)
    if setting:
        setting.value = value
    else:
        db.add(models.ApplicationSetting(key=SECTION_CONFIG_KEY, value=value))
    db.commit()


def section_names(db=None, include_disabled: bool = True) -> dict[int, str]:
    if db is None:
        return dict(SECTION_NAMES)
    names = {row["id"]: row["name"] for row in load_section_config(db, include_disabled=include_disabled)}
    for sid, name in SECTION_NAMES.items():
        names.setdefault(sid, name)
    return names


def section_order(db=None, include_disabled: bool = False) -> list[int]:
    if db is None:
        return list(DEFAULT_SECTION_ORDER)
    return [row["id"] for row in load_section_config(db, include_disabled=include_disabled)]


def section_types(db=None, include_disabled: bool = True) -> dict[int, int]:
    if db is None:
        return {sid: sid for sid in SECTION_NAMES}
    return {row["id"]: row["template_id"] for row in load_section_config(db, include_disabled=include_disabled)}


def section_type(db, section: int) -> int:
    if db is None:
        return section
    return section_types(db).get(int(section), int(section))


def build_section1_plan(regular_categories: list) -> list[dict]:
    """Section 1: 2 questions per team per category; قدرات ذهنية = 1 per team."""
    slots = []
    for cat in regular_categories:
        count = 1 if cat["name"] == MENTAL_CATEGORY else 2
        for team in ("a", "b"):
            for _ in range(count):
                slots.append({"category_id": cat["id"], "category_name": cat["name"], "team": team})
    return slots


def build_section2_plan(regular_categories: list) -> list[dict]:
    """Section 2: one buzzer question per regular category."""
    return [{"category_id": c["id"], "category_name": c["name"], "team": None} for c in regular_categories]


def build_section3_plan(regular_categories: list) -> list[dict]:
    """Section 3: one buzzer question per regular category (no rebound)."""
    return [{"category_id": c["id"], "category_name": c["name"], "team": None} for c in regular_categories]


def build_section4_plan() -> dict:
    """Section 4: wheel, 3 spins per team."""
    return {"spins_a": 3, "spins_b": 3}


def wheel_segments(regular_categories: list) -> list[str]:
    names = [c["name"] for c in regular_categories]
    return names + ["الجوكر"]


def points_for(kind: str) -> int:
    """kind in {original, rebound, father}."""
    return {"original": NORMAL_POINTS, "rebound": REBOUND_POINTS, "father": FATHER_POINTS}.get(kind, 0)
