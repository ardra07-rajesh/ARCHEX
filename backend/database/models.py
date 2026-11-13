from sqlalchemy import Float, Integer, String, Text, ForeignKey, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Phase 12 account identity. Passwords are stored as PBKDF2 hashes only."""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(20), default="researcher", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class SecurityAuditEvent(Base):
    __tablename__ = "security_audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(50), default="")
    resource_id: Mapped[str] = mapped_column(String(80), default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40), index=True)


class AnalysisRecord(Base):
    """One stored AI analysis (Phase 5). Full experiment records arrive in Phase 8."""

    __tablename__ = "analysis_records"
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String(40))
    scenario: Mapped[str] = mapped_column(String(40))
    seed: Mapped[int] = mapped_column(Integer)
    classification: Mapped[str] = mapped_column(String(20))
    anomaly_score: Mapped[float] = mapped_column(Float)
    result_json: Mapped[str] = mapped_column(Text)


class Experiment(Base):
    """Persistent research experiment definition and latest result snapshot."""
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(40), index=True)
    simulation: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    updated_at: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    config_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    version: Mapped[int] = mapped_column(Integer, default=1)


class ExperimentExecution(Base):
    __tablename__ = "experiment_executions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    config_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    software_version: Mapped[str] = mapped_column(String(32), default="0.7.0")
    replay_of: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(String(500))
    experiment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    data_json: Mapped[str] = mapped_column(Text, default="{}")



class AssistantConversation(Base):
    """Persisted Phase 7 assistant conversation metadata."""
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    __tablename__ = "assistant_conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(180), default="New research conversation")
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40), index=True)


class AssistantMessage(Base):
    """Persisted user/assistant messages and the evidence snapshot used."""
    __tablename__ = "assistant_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    usage_json: Mapped[str] = mapped_column(Text, default="{}")


class ResearchReport(Base):
    """Generated report metadata; report bytes live in the managed reports directory."""
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    __tablename__ = "research_reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200))
    report_type: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(24), default="completed", index=True)
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    filename: Mapped[str] = mapped_column(String(80), unique=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    sections_json: Mapped[str] = mapped_column(Text, default="[]")
    detail_level: Mapped[str] = mapped_column(String(24), default="technical")
    experiment_version: Mapped[int] = mapped_column(Integer, default=1)


class ValidationRun(Base):
    """Immutable provenance record for a reproducible research benchmark run."""
    __tablename__ = "validation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    suite: Mapped[str] = mapped_column(String(64), index=True)
    seed: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    duration_ms: Mapped[float] = mapped_column(Float)
    result_sha256: Mapped[str] = mapped_column(String(64), index=True)
    manifest_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
