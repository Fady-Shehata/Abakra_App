"""SQLAlchemy ORM models.

Question *content* lives in managed workbook sources; SQLite stores only
metadata and references (workbook id, worksheet name, original row).
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now() -> dt.datetime:
    return dt.datetime.utcnow()


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)

    role: Mapped[Role] = relationship(back_populates="users")

    @property
    def role_name(self) -> str:
        return self.role.name if self.role else ""


class ApplicationSetting(Base):
    __tablename__ = "application_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)


# --------------------------------------------------------------------------- #
# Teams
# --------------------------------------------------------------------------- #
class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    level: Mapped[Optional[str]] = mapped_column(String(80))  # المرحلة (e.g., ابتدائي/إعدادي/ثانوي/جامعي)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    logo_path: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)

    members: Mapped[list["TeamMember"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class TeamMember(Base):
    __tablename__ = "team_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    team: Mapped[Team] = relationship(back_populates="members")


# --------------------------------------------------------------------------- #
# Tournaments
# --------------------------------------------------------------------------- #
class Tournament(Base):
    __tablename__ = "tournaments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    start_date: Mapped[Optional[dt.date]] = mapped_column(DateTime)
    end_date: Mapped[Optional[dt.date]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft/active/completed/archived
    format: Mapped[str] = mapped_column(String(20), default="groups_knockout")
    settings_json: Mapped[Optional[str]] = mapped_column(Text)  # tie-breakers etc.
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)

    teams: Mapped[list["TournamentTeam"]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan"
    )
    groups: Mapped[list["Group"]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan"
    )
    matches: Mapped[list["Match"]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan"
    )


class TournamentTeam(Base):
    __tablename__ = "tournament_teams"
    __table_args__ = (UniqueConstraint("tournament_id", "team_id", name="uq_tt"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    seed: Mapped[Optional[int]] = mapped_column(Integer)
    tournament: Mapped[Tournament] = relationship(back_populates="teams")
    team: Mapped[Team] = relationship()


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    tournament: Mapped[Tournament] = relationship(back_populates="groups")
    members: Mapped[list["GroupTeam"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupTeam(Base):
    __tablename__ = "group_teams"
    __table_args__ = (UniqueConstraint("group_id", "team_id", name="uq_gt"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    group: Mapped[Group] = relationship(back_populates="members")
    team: Mapped[Team] = relationship()


# --------------------------------------------------------------------------- #
# Matches & sessions
# --------------------------------------------------------------------------- #
class Match(Base):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(30), default="group")  # group / knockout
    round_name: Mapped[Optional[str]] = mapped_column(String(80))
    group_id: Mapped[Optional[int]] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    team_a_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    team_b_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    host_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    scheduled_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    score_a: Mapped[int] = mapped_column(Integer, default=0)
    score_b: Mapped[int] = mapped_column(Integer, default=0)
    winner_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    is_draw: Mapped[bool] = mapped_column(Boolean, default=False)
    points_a: Mapped[int] = mapped_column(Integer, default=0)
    points_b: Mapped[int] = mapped_column(Integer, default=0)
    bracket_slot_id: Mapped[Optional[int]] = mapped_column(Integer)
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)

    tournament: Mapped[Tournament] = relationship(back_populates="matches")
    team_a: Mapped[Optional[Team]] = relationship(foreign_keys=[team_a_id])
    team_b: Mapped[Optional[Team]] = relationship(foreign_keys=[team_b_id])
    host: Mapped[Optional[User]] = relationship()
    session: Mapped[Optional["GameSession"]] = relationship(
        back_populates="match", uselist=False, cascade="all, delete-orphan"
    )


class GameSession(Base):
    __tablename__ = "game_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), unique=True)
    current_section: Mapped[int] = mapped_column(Integer, default=0)  # 0=not started..5
    state_json: Mapped[Optional[str]] = mapped_column(Text)  # live section state machine
    status: Mapped[str] = mapped_column(String(20), default="ready")  # ready/in_progress/paused/completed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)

    match: Mapped[Match] = relationship(back_populates="session")


# --------------------------------------------------------------------------- #
# Categories & questions
# --------------------------------------------------------------------------- #
class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    is_regular: Mapped[bool] = mapped_column(Boolean, default=True)  # False for أبونا بيسأل
    on_wheel: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class QuestionSource(Base):
    __tablename__ = "question_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20), default="import")  # import / manual
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("question_code", name="uq_qcode"),
        UniqueConstraint("content_hash", name="uq_qhash"),
        Index("ix_q_cat", "category_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("question_sources.id"))
    worksheet: Mapped[str] = mapped_column(String(120))
    row_number: Mapped[int] = mapped_column(Integer)
    question_code: Mapped[str] = mapped_column(String(80))
    content_hash: Mapped[str] = mapped_column(String(64))
    qtype: Mapped[str] = mapped_column(String(20), default="mc")  # mc/tf/open
    difficulty: Mapped[Optional[str]] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)

    category: Mapped[Category] = relationship()
    source: Mapped[QuestionSource] = relationship()


class QuestionImport(Base):
    __tablename__ = "question_imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("question_sources.id"))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    summary_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class QuestionUsage(Base):
    __tablename__ = "question_usage"
    __table_args__ = (
        UniqueConstraint("session_id", "question_id", name="uq_session_question"),
        Index("ix_usage_session", "session_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    section: Mapped[int] = mapped_column(Integer)
    assigned_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    state: Mapped[str] = mapped_column(String(20), default="selected")
    selected_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, default=now)
    revealed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    answer_result: Mapped[Optional[str]] = mapped_column(String(20))
    rebound_result: Mapped[Optional[str]] = mapped_column(String(20))
    points_awarded: Mapped[int] = mapped_column(Integer, default=0)
    host_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    via_joker: Mapped[bool] = mapped_column(Boolean, default=False)


class ScoreEvent(Base):
    __tablename__ = "score_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"))
    section: Mapped[Optional[int]] = mapped_column(Integer)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    question_id: Mapped[Optional[int]] = mapped_column(ForeignKey("questions.id"))
    delta: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(120))
    host_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class MatchResult(Base):
    __tablename__ = "match_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), unique=True)
    score_a: Mapped[int] = mapped_column(Integer)
    score_b: Mapped[int] = mapped_column(Integer)
    winner_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    is_draw: Mapped[bool] = mapped_column(Boolean, default=False)
    points_a: Mapped[int] = mapped_column(Integer, default=0)
    points_b: Mapped[int] = mapped_column(Integer, default=0)
    host_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


# --------------------------------------------------------------------------- #
# Brackets
# --------------------------------------------------------------------------- #
class BracketRound(Base):
    __tablename__ = "bracket_rounds"
    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class BracketSlot(Base):
    __tablename__ = "bracket_slots"
    __table_args__ = (
        UniqueConstraint("round_id", "position", name="uq_slot_pos"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("bracket_rounds.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    team_a_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    team_b_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    match_id: Mapped[Optional[int]] = mapped_column(ForeignKey("matches.id", ondelete="SET NULL"))
    winner_to_slot: Mapped[Optional[int]] = mapped_column(Integer)
    winner_to_side: Mapped[Optional[str]] = mapped_column(String(1))  # 'a' or 'b'
    loser_to_slot: Mapped[Optional[int]] = mapped_column(Integer)
    loser_to_side: Mapped[Optional[str]] = mapped_column(String(1))
    is_third_place: Mapped[bool] = mapped_column(Boolean, default=False)


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(120))
    detail: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
