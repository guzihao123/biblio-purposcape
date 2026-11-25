from typing import Optional
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, synonym


class Base(DeclarativeBase):
    pass


def _utcnow():
    return datetime.now(timezone.utc)


def _session_expiry():
    from app.config import get_settings

    return _utcnow() + timedelta(seconds=get_settings().session_ttl_seconds)


class InviteSession(Base):
    __tablename__ = 'invite_sessions'

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_ip: Mapped[str] = mapped_column(String(64), default='', nullable=False)
    user_agent: Mapped[str] = mapped_column(String(300), default='', nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_session_expiry,
        nullable=False,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Task(Base):
    __tablename__ = 'tasks'
    __table_args__ = (
        UniqueConstraint(
            'session_id',
            'idempotency_key',
            name='uq_tasks_session_idempotency_key',
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey('invite_sessions.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(String(32), default='collecting_mode', nullable=False)
    next_card: Mapped[Optional[str]] = mapped_column(String(32), default='direction', nullable=True)
    skill_version_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey('skill_versions.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=True)
    updated_at: Mapped[Optional[object]] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=True,
    )
    events: Mapped[list['TaskEvent']] = relationship(
        back_populates='task',
        cascade='all, delete-orphan',
        order_by='TaskEvent.id',
    )
    progress: Mapped[Optional['TaskProgress']] = relationship(
        back_populates='task',
        cascade='all, delete-orphan',
        uselist=False,
    )


class TaskAnswer(Base):
    __tablename__ = 'task_answers'
    __table_args__ = (
        UniqueConstraint('task_id', 'card_id', name='uq_task_answers_task_card'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey('tasks.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    card_id: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_state: Mapped[str] = mapped_column(String(32), nullable=False)
    next_card: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class TaskJob(Base):
    __tablename__ = 'task_jobs'

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey('tasks.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    answer_id: Mapped[int] = mapped_column(
        ForeignKey('task_answers.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default='pending', nullable=False)


class SkillVersion(Base):
    __tablename__ = 'skill_versions'
    __table_args__ = (
        Index(
            'uq_skill_one_published',
            'state',
            unique=True,
            sqlite_where=text("state = 'published'"),
            postgresql_where=text("state = 'published'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int] = mapped_column(nullable=False, unique=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    state: Mapped[str] = mapped_column(String(16), default='draft', nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    regression_report: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)


class SkillVersionEvent(Base):
    __tablename__ = 'skill_version_events'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey('skill_versions.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    diff: Mapped[dict] = mapped_column(JSON, nullable=False)
    regression_report: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class TaskEvent(Base):
    __tablename__ = 'task_events'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey('tasks.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    kind = synonym('event_type')
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    task: Mapped[Task] = relationship(back_populates='events')


class TaskProgress(Base):
    __tablename__ = 'task_progress'

    task_id: Mapped[str] = mapped_column(
        ForeignKey('tasks.id', ondelete='CASCADE'),
        primary_key=True,
    )
    stage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(String(500), default='', nullable=False)
    percent: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False)
    input_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    checkpoint: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    traceback: Mapped[Optional[str]] = mapped_column('protected_traceback', Text, nullable=True)
    updated_at: Mapped[Optional[object]] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=True,
    )
    task: Mapped[Task] = relationship(back_populates='progress')
