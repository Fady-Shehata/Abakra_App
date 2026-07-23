"""Knockout bracket generation, byes, seeding and winner advancement."""
from __future__ import annotations

import math
from typing import Optional

from sqlalchemy.orm import Session

from . import models


def _round_name(size: int) -> str:
    return {
        2: "النهائي",
        4: "نصف النهائي",
        8: "ربع النهائي",
        16: "دور الـ16",
        32: "دور الـ32",
    }.get(size, f"دور الـ{size}")


def next_power_of_two(n: int) -> int:
    return 1 if n <= 1 else 2 ** math.ceil(math.log2(n))


def seed_positions(size: int) -> list[int]:
    """Standard bracket seeding for a bracket of `size` slots (1-indexed seeds)."""
    seeds = [1, 2]
    while len(seeds) < size:
        n = len(seeds) * 2
        new = []
        for s in seeds:
            new.append(s)
            new.append(n + 1 - s)
        seeds = new
    return seeds


def generate_bracket(db: Session, tournament: models.Tournament, qualified_team_ids: list[int]) -> None:
    """Create bracket rounds/slots and the first-round matches.

    Supports byes when qualifiers are not a power of two. Seeds by given order.
    """
    # clear existing bracket
    db.query(models.BracketSlot).filter(
        models.BracketSlot.round_id.in_(
            db.query(models.BracketRound.id).filter(
                models.BracketRound.tournament_id == tournament.id
            )
        )
    ).delete(synchronize_session=False)
    db.query(models.BracketRound).filter(
        models.BracketRound.tournament_id == tournament.id
    ).delete(synchronize_session=False)
    db.query(models.Match).filter(
        models.Match.tournament_id == tournament.id,
        models.Match.stage == "knockout",
    ).delete(synchronize_session=False)
    db.commit()

    n = len(qualified_team_ids)
    if n < 2:
        raise ValueError("need at least 2 qualified teams")
    size = next_power_of_two(n)

    # seed order -> place teams into positions, byes = None
    positions = seed_positions(size)  # seed number per slot position
    seeded = [None] * size
    for slot_index, seed in enumerate(positions):
        if seed <= n:
            seeded[slot_index] = qualified_team_ids[seed - 1]

    # Build rounds from `size` down to 2
    rounds: list[models.BracketRound] = []
    order = 0
    s = size
    while s >= 2:
        r = models.BracketRound(tournament_id=tournament.id, name=_round_name(s), order_index=order)
        db.add(r)
        rounds.append(r)
        order += 1
        s //= 2
    db.flush()

    # First round slots (pairs)
    first = rounds[0]
    slots: list[models.BracketSlot] = []
    num_first_slots = size // 2
    for pos in range(num_first_slots):
        a = seeded[pos * 2]
        b = seeded[pos * 2 + 1]
        slot = models.BracketSlot(round_id=first.id, position=pos, team_a_id=a, team_b_id=b)
        db.add(slot)
        slots.append(slot)
    db.flush()

    # subsequent round slots
    prev_slots = slots
    for r in rounds[1:]:
        count = len(prev_slots) // 2
        new_slots = []
        for pos in range(count):
            slot = models.BracketSlot(round_id=r.id, position=pos)
            db.add(slot)
            new_slots.append(slot)
        db.flush()
        # link winners
        for i, ps in enumerate(prev_slots):
            target = new_slots[i // 2]
            ps.winner_to_slot = target.id
            ps.winner_to_side = "a" if i % 2 == 0 else "b"
        prev_slots = new_slots

    # third-place slot (fed by semi-final losers) when >=4 teams
    if size >= 4 and len(rounds) >= 2:
        semis = _round_slots(db, rounds[-2].id)
        third_round = models.BracketRound(
            tournament_id=tournament.id, name="مباراة المركز الثالث", order_index=order
        )
        db.add(third_round)
        db.flush()
        third_slot = models.BracketSlot(round_id=third_round.id, position=0, is_third_place=True)
        db.add(third_slot)
        db.flush()
        for i, ss in enumerate(semis):
            ss.loser_to_slot = third_slot.id
            ss.loser_to_side = "a" if i == 0 else "b"

    db.commit()

    # Auto-advance byes in the first round, then create matches for ready slots
    _advance_byes(db, tournament, first)
    _create_matches_for_ready_slots(db, tournament)
    db.add(models.AuditLog(user_id=None, action="generate_bracket",
                           detail=f"tournament={tournament.id} teams={n} size={size}"))
    db.commit()


def _round_slots(db: Session, round_id: int) -> list[models.BracketSlot]:
    return (
        db.query(models.BracketSlot)
        .filter(models.BracketSlot.round_id == round_id)
        .order_by(models.BracketSlot.position)
        .all()
    )


def _advance_byes(db: Session, tournament: models.Tournament, first_round: models.BracketRound) -> None:
    for slot in _round_slots(db, first_round.id):
        a, b = slot.team_a_id, slot.team_b_id
        if (a is None) ^ (b is None):
            winner = a if a is not None else b
            _place_winner(db, slot, winner)
    db.commit()


def _place_winner(db: Session, slot: models.BracketSlot, team_id: Optional[int]) -> None:
    if slot.winner_to_slot and team_id:
        target = db.get(models.BracketSlot, slot.winner_to_slot)
        if target:
            if slot.winner_to_side == "a":
                target.team_a_id = team_id
            else:
                target.team_b_id = team_id


def _create_matches_for_ready_slots(db: Session, tournament: models.Tournament) -> None:
    slots = (
        db.query(models.BracketSlot)
        .join(models.BracketRound)
        .filter(models.BracketRound.tournament_id == tournament.id)
        .all()
    )
    for slot in slots:
        if slot.match_id is None and slot.team_a_id and slot.team_b_id:
            rnd = db.get(models.BracketRound, slot.round_id)
            match = models.Match(
                tournament_id=tournament.id, stage="knockout",
                round_name=rnd.name, team_a_id=slot.team_a_id, team_b_id=slot.team_b_id,
                status="scheduled", bracket_slot_id=slot.id,
            )
            db.add(match)
            db.flush()
            slot.match_id = match.id
    db.commit()


def advance_after_match(db: Session, match: models.Match) -> None:
    """Advance winner (and loser to third-place slot) after a knockout match."""
    if match.stage != "knockout" or not match.bracket_slot_id:
        return
    slot = db.get(models.BracketSlot, match.bracket_slot_id)
    if not slot or not match.winner_team_id:
        return
    loser_id = match.team_a_id if match.winner_team_id == match.team_b_id else match.team_b_id
    _place_winner(db, slot, match.winner_team_id)
    if slot.loser_to_slot and loser_id:
        target = db.get(models.BracketSlot, slot.loser_to_slot)
        if target:
            if slot.loser_to_side == "a":
                target.team_a_id = loser_id
            else:
                target.team_b_id = loser_id
    db.add(models.AuditLog(user_id=None, action="bracket_advance",
                           detail=f"match={match.id} winner={match.winner_team_id}"))
    db.commit()
    _create_matches_for_ready_slots(db, match.tournament)
