from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

def utcnow() -> datetime:
    return datetime.utcnow()

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer: Mapped[str] = mapped_column(String(160), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    quote_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    revio_project_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    revio_project_status_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revio_project_priority_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revio_sync_status: Mapped[str] = mapped_column(String(40), default="Not Created")
    revio_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    revio_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    project_name: Mapped[str] = mapped_column(String(200))
    project_type: Mapped[str] = mapped_column(String(60), index=True)
    technical_manager: Mapped[str] = mapped_column(String(100), default="Chad")
    engineer: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    sales_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stage: Mapped[str] = mapped_column(String(60), default="Intake", index=True)
    risk: Mapped[str] = mapped_column(String(20), default="Green", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="Normal")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    project_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_billable: Mapped[bool] = mapped_column(Boolean, default=True)
    project_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(300), nullable=True)
    next_action_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    next_action_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    blocker: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Milestone.id"
    )
    notes: Mapped[list["ProjectNote"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectNote.created_at.desc()"
    )
    contacts: Mapped[list["CustomerContact"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="CustomerContact.is_primary.desc(), CustomerContact.name"
    )
    activities: Mapped[list["ProjectActivity"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectActivity.created_at.desc()"
    )

class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="Not Started")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    revio_milestone_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    project: Mapped[Project] = relationship(back_populates="milestones")

class ProjectNote(Base):
    __tablename__ = "project_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(100))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    project: Mapped[Project] = relationship(back_populates="notes")
    attachments: Mapped[list["NoteAttachment"]] = relationship(
        back_populates="note", cascade="all, delete-orphan", order_by="NoteAttachment.id"
    )

class NoteAttachment(Base):
    __tablename__ = "note_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("project_notes.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int]
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    note: Mapped[ProjectNote] = relationship(back_populates="attachments")

class CustomerContact(Base):
    __tablename__ = "customer_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contact_type: Mapped[str] = mapped_column(String(40), default="Technical")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    project: Mapped[Project] = relationship(back_populates="contacts")

class ProjectActivity(Base):
    __tablename__ = "project_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    actor_name: Mapped[str] = mapped_column(String(160))
    actor_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    field_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    project: Mapped[Project] = relationship(back_populates="activities")


class HardwareOrderWorkflow(Base):
    __tablename__ = "hardware_order_workflows"
    __table_args__ = (UniqueConstraint("project_id", name="uq_hardware_order_workflow_project"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="Pending", index=True)
    revio_customer_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    revio_customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_balance: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

class PsaTicketWorkflow(Base):
    __tablename__ = "psa_ticket_workflows"
    __table_args__ = (UniqueConstraint("project_id", "workflow_key", name="uq_psa_ticket_workflow_step"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    workflow_key: Mapped[str] = mapped_column(String(80))
    ticket_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    ticket_description: Mapped[str] = mapped_column(String(300))
    assignee_name: Mapped[str] = mapped_column(String(100))
    associated_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="Pending", index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

class IntakeEmail(Base):
    __tablename__ = "intake_emails"
    __table_args__ = (UniqueConstraint("message_id", name="uq_intake_email_message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(500), index=True)
    sender_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="Pending", index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
