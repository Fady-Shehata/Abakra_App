"""Higher-level tournament services: groups, fixtures, knockout."""
from __future__ import annotations

import itertools
import random

from sqlalchemy.orm import Session

from . import models, brackets, standings


def generate_groups(db: Session, tournament_id: int, num_groups: int) -> None:
    t = db.get(models.Tournament, tournament_id)
    if not t:
        return
    # clear existing groups & group matches
    db.query(models.Match).filter_by(tournament_id=t.id, stage="group").delete(synchronize_session=False)
    for g in list(t.groups):
        db.delete(g)
    db.commit()

    team_ids = [tt.team_id for tt in t.teams]
    random.shuffle(team_ids)
    num_groups = max(1, min(num_groups, len(team_ids) or 1))
    groups = []
    for i in range(num_groups):
        g = models.Group(tournament_id=t.id, name=f"المجموعة {chr(65 + i)}")
        db.add(g)
        groups.append(g)
    db.flush()
    for idx, team_id in enumerate(team_ids):
        g = groups[idx % num_groups]
        db.add(models.GroupTeam(group_id=g.id, team_id=team_id))
    db.commit()


def generate_group_matches(db: Session, tournament_id: int) -> None:
    t = db.get(models.Tournament, tournament_id)
    if not t:
        return
    db.query(models.Match).filter_by(tournament_id=t.id, stage="group").delete(synchronize_session=False)
    db.commit()
    for g in t.groups:
        team_ids = [m.team_id for m in g.members]
        for a, b in itertools.combinations(team_ids, 2):
            db.add(models.Match(tournament_id=t.id, stage="group", group_id=g.id,
                                round_name=g.name, team_a_id=a, team_b_id=b, status="scheduled"))
    db.commit()


def generate_groups_sequential(db: Session, tournament_id: int,
                               teams_per_group: int,
                               shuffle: bool = False) -> None:
    """Distribute teams sequentially: first N teams -> group A, next N -> B, etc.

    Existing groups + group matches are wiped first. If shuffle is True the
    team list is shuffled once before slicing (still keeping the "fill each
    group fully before moving to the next" behaviour).
    """
    t = db.get(models.Tournament, tournament_id)
    if not t:
        return
    db.query(models.Match).filter_by(tournament_id=t.id, stage="group").delete(synchronize_session=False)
    for g in list(t.groups):
        db.delete(g)
    db.commit()

    team_ids = [tt.team_id for tt in t.teams]
    if not team_ids:
        return
    if shuffle:
        random.shuffle(team_ids)
    per = max(1, teams_per_group)
    chunks = [team_ids[i:i + per] for i in range(0, len(team_ids), per)]
    groups: list[models.Group] = []
    for i in range(len(chunks)):
        g = models.Group(tournament_id=t.id, name=f"المجموعة {chr(65 + i)}")
        db.add(g)
        groups.append(g)
    db.flush()
    for g, chunk in zip(groups, chunks):
        for team_id in chunk:
            db.add(models.GroupTeam(group_id=g.id, team_id=team_id))
    db.commit()


def assign_teams_to_groups(db: Session, tournament_id: int,
                           assignments: dict[int, int]) -> None:
    """Manually distribute participating teams into specific groups.

    assignments maps team_id -> 0-based group index. Any teams whose id is not
    present in the mapping are left unassigned. Existing groups and their group
    matches are wiped and rebuilt from scratch.
    """
    t = db.get(models.Tournament, tournament_id)
    if not t:
        return
    # wipe existing groups & group matches
    db.query(models.Match).filter_by(tournament_id=t.id, stage="group").delete(synchronize_session=False)
    for g in list(t.groups):
        db.delete(g)
    db.commit()
    if not assignments:
        return
    max_index = max(assignments.values())
    groups: list[models.Group] = []
    for i in range(max_index + 1):
        g = models.Group(tournament_id=t.id, name=f"المجموعة {chr(65 + i)}")
        db.add(g)
        groups.append(g)
    db.flush()
    for team_id, idx in assignments.items():
        if 0 <= idx < len(groups):
            db.add(models.GroupTeam(group_id=groups[idx].id, team_id=team_id))
    db.commit()


def generate_knockout(db: Session, tournament_id: int, qualifiers_per_group: int) -> None:
    t = db.get(models.Tournament, tournament_id)
    if not t:
        return
    qualified: list[int] = []
    if t.groups:
        # interleave qualifiers by rank for fair seeding
        per_group = []
        for g in t.groups:
            per_group.append(standings.group_qualifiers(db, t, g, qualifiers_per_group))
        for rank in range(qualifiers_per_group):
            for grp in per_group:
                if rank < len(grp):
                    qualified.append(grp[rank])
    else:
        # no groups: use tournament team order (2-team direct final etc.)
        qualified = [tt.team_id for tt in t.teams]
    if len(qualified) >= 2:
        brackets.generate_bracket(db, t, qualified)
