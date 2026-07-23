from __future__ import annotations

import random

from app import game as ge, models
from tests.conftest import make_category, make_match_with_session, make_question, make_source


def _clear_categories(db):
    db.query(models.Category).delete()
    db.commit()


def test_original_correct_is_5(db_session):
    _clear_categories(db_session)
    cat = make_category(db_session, "كتاب لاهوت", True, True)
    src = make_source(db_session, "s1.xlsx")
    make_question(db_session, cat.id, src.id, "Q1", "h1")
    m = make_match_with_session(db_session)

    ge.start_section(db_session, m.session, 2)
    ge.select_question(db_session, m.session, 2, cat.id, None, None)
    ge.reveal(db_session, m.session)
    ge.mark_correct(db_session, m.session, "a", None)

    m2 = db_session.get(models.Match, m.id)
    assert m2.score_a == 5
    assert m2.score_b == 0


def test_rebound_correct_is_10_for_opponent(db_session):
    _clear_categories(db_session)
    cat = make_category(db_session, "كتاب لاهوت", True, True)
    src = make_source(db_session, "s2.xlsx")
    make_question(db_session, cat.id, src.id, "Q1", "h2")
    m = make_match_with_session(db_session)

    ge.start_section(db_session, m.session, 2)
    ge.select_question(db_session, m.session, 2, cat.id, None, None)
    ge.reveal(db_session, m.session)
    ge.mark_wrong(db_session, m.session, None)
    ge.rebound_correct(db_session, m.session, None)

    m2 = db_session.get(models.Match, m.id)
    assert m2.score_a + m2.score_b == 10


def test_failed_rebound_is_zero(db_session):
    _clear_categories(db_session)
    cat = make_category(db_session, "كتاب لاهوت", True, True)
    src = make_source(db_session, "s3.xlsx")
    make_question(db_session, cat.id, src.id, "Q1", "h3")
    m = make_match_with_session(db_session)

    ge.start_section(db_session, m.session, 2)
    ge.select_question(db_session, m.session, 2, cat.id, None, None)
    ge.reveal(db_session, m.session)
    ge.mark_wrong(db_session, m.session, None)
    ge.rebound_wrong(db_session, m.session, None)

    m2 = db_session.get(models.Match, m.id)
    assert m2.score_a == 0
    assert m2.score_b == 0


def test_individual_no_rebound(db_session):
    _clear_categories(db_session)
    cat = make_category(db_session, "كتاب لاهوت", True, True)
    src = make_source(db_session, "s4.xlsx")
    make_question(db_session, cat.id, src.id, "Q1", "h4")
    m = make_match_with_session(db_session)

    ge.start_section(db_session, m.session, 3)
    ge.select_question(db_session, m.session, 3, cat.id, None, None)
    ge.reveal(db_session, m.session)
    ge.mark_wrong(db_session, m.session, None)

    st = ge.load_state(m.session)
    assert st["current"]["phase"] == "done"
    assert m.score_a == 0 and m.score_b == 0


def test_father_asks_awards_10(db_session):
    _clear_categories(db_session)
    special = make_category(db_session, "أبونا بيسأل", False, False)
    src = make_source(db_session, "s5.xlsx")
    make_question(db_session, special.id, src.id, "Q1", "h5")
    m = make_match_with_session(db_session)

    ge.start_section(db_session, m.session, 5)
    ge.select_question(db_session, m.session, 5, special.id, None, None)
    ge.reveal(db_session, m.session)
    ge.father_award(db_session, m.session, "b", None)

    m2 = db_session.get(models.Match, m.id)
    assert m2.score_b == 10


def test_section1_mental_ability_exception(db_session):
    _clear_categories(db_session)
    cat1 = make_category(db_session, "كتاب لاهوت", True, True)
    cat2 = make_category(db_session, "قدرات ذهنية", True, True)
    src = make_source(db_session, "s6.xlsx")
    # Section 1 needs 4 questions for normal categories and 2 for قدرات ذهنية.
    for i in range(1, 5):
        make_question(db_session, cat1.id, src.id, f"C1_{i}", f"h_c1_{i}")
    for i in range(1, 3):
        make_question(db_session, cat2.id, src.id, f"C2_{i}", f"h_c2_{i}")
    m = make_match_with_session(db_session)

    st = ge.start_section(db_session, m.session, 1)
    slots = st["sections"]["1"]["plan"]
    per_cat_team = {}
    for s in slots:
        key = (s["category_name"], s["team"])
        per_cat_team[key] = per_cat_team.get(key, 0) + 1

    assert per_cat_team[("كتاب لاهوت", "a")] == 2
    assert per_cat_team[("كتاب لاهوت", "b")] == 2
    assert per_cat_team[("قدرات ذهنية", "a")] == 1
    assert per_cat_team[("قدرات ذهنية", "b")] == 1


def test_speed_buzzer_lock(db_session):
    _clear_categories(db_session)
    cat = make_category(db_session, "كتاب لاهوت", True, True)
    src = make_source(db_session, "s7.xlsx")
    make_question(db_session, cat.id, src.id, "Q_lock", "h_lock")
    m = make_match_with_session(db_session)
    ge.start_section(db_session, m.session, 2)
    ge.set_buzz(db_session, m.session, "a")
    ge.set_buzz(db_session, m.session, "b")
    st = ge.load_state(m.session)
    assert st["buzzer"]["team"] == "a"


def test_wheel_three_spins_each_and_joker(db_session, monkeypatch):
    _clear_categories(db_session)
    make_category(db_session, "كتاب لاهوت", True, True)
    make_category(db_session, "قدرات ذهنية", True, True)
    m = make_match_with_session(db_session)
    ge.start_section(db_session, m.session, 4)

    monkeypatch.setattr(random, "choice", lambda seq: "الجوكر")
    for _ in range(3):
        ge.spin_wheel(db_session, m.session, "a")
    for _ in range(3):
        ge.spin_wheel(db_session, m.session, "b")

    st = ge.load_state(m.session)
    assert st["wheel"]["spins_a"] == 0
    assert st["wheel"]["spins_b"] == 0
    assert st["last_spin"]["result"] == "الجوكر"
