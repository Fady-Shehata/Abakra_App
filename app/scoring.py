"""Pure scoring rules and section definitions for the five quiz sections.

CRITICAL RULES:
- Normal correct answer = 5 points.
- Rebound correct (opponent) = 10 points; original team gets 0.
- Failed rebound = 0 for both.
- فردي (individual): correct = 5, NO rebound, wrong = 0 for both.
- أبونا بيسأل: open to both teams, first correct team = 10, no rebound.
"""
from __future__ import annotations

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
