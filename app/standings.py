"""Group standings computation with configurable tie-breakers."""
from __future__ import annotations

import json
import random
from typing import Optional

from sqlalchemy.orm import Session

from . import models

DEFAULT_TIEBREAKERS = ["points", "gd", "gf", "head_to_head", "random"]

WIN_POINTS = 3
DRAW_POINTS = 1
LOSS_POINTS = 0


def _tiebreakers(tournament: models.Tournament) -> list[str]:
    if tournament.settings_json:
        try:
            cfg = json.loads(tournament.settings_json)
            tb = cfg.get("tiebreakers")
            if isinstance(tb, list) and tb:
                return tb
        except Exception:
            pass
    return DEFAULT_TIEBREAKERS


def compute_group_standings(db: Session, tournament: models.Tournament, group: models.Group) -> list[dict]:
    team_ids = [m.team_id for m in group.members]
    stats = {
        tid: {"team_id": tid, "played": 0, "won": 0, "drawn": 0, "lost": 0,
              "points": 0, "gf": 0, "ga": 0, "gd": 0}
        for tid in team_ids
    }
    matches = (
        db.query(models.Match)
        .filter(
            models.Match.tournament_id == tournament.id,
            models.Match.group_id == group.id,
            models.Match.status == "completed",
        )
        .all()
    )
    h2h: dict[tuple[int, int], int] = {}
    for m in matches:
        a, b = m.team_a_id, m.team_b_id
        if a not in stats or b not in stats:
            continue
        stats[a]["played"] += 1
        stats[b]["played"] += 1
        stats[a]["gf"] += m.score_a
        stats[a]["ga"] += m.score_b
        stats[b]["gf"] += m.score_b
        stats[b]["ga"] += m.score_a
        if m.is_draw or m.score_a == m.score_b:
            stats[a]["drawn"] += 1
            stats[b]["drawn"] += 1
            stats[a]["points"] += DRAW_POINTS
            stats[b]["points"] += DRAW_POINTS
        elif m.score_a > m.score_b:
            stats[a]["won"] += 1
            stats[b]["lost"] += 1
            stats[a]["points"] += WIN_POINTS
            h2h[(a, b)] = 1
        else:
            stats[b]["won"] += 1
            stats[a]["lost"] += 1
            stats[b]["points"] += WIN_POINTS
            h2h[(b, a)] = 1

    for s in stats.values():
        s["gd"] = s["gf"] - s["ga"]

    order = _tiebreakers(tournament)
    rows = list(stats.values())

    def sort_key(row):
        key = []
        for crit in order:
            if crit == "points":
                key.append(-row["points"])
            elif crit == "gd":
                key.append(-row["gd"])
            elif crit == "gf":
                key.append(-row["gf"])
            elif crit == "random":
                key.append(random.random())
        return tuple(key)

    rows.sort(key=sort_key)

    # head-to-head refinement for adjacent equal rows
    if "head_to_head" in order:
        for i in range(len(rows) - 1):
            a, b = rows[i]["team_id"], rows[i + 1]["team_id"]
            if rows[i]["points"] == rows[i + 1]["points"] and rows[i]["gd"] == rows[i + 1]["gd"]:
                if h2h.get((b, a)) and not h2h.get((a, b)):
                    rows[i], rows[i + 1] = rows[i + 1], rows[i]

    team_map = {t.id: t for t in db.query(models.Team).filter(models.Team.id.in_(team_ids)).all()}
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        row["team_name"] = team_map[row["team_id"]].name if row["team_id"] in team_map else "?"
    return rows


def group_qualifiers(db: Session, tournament: models.Tournament, group: models.Group, count: int) -> list[int]:
    rows = compute_group_standings(db, tournament, group)
    return [r["team_id"] for r in rows[:count]]
