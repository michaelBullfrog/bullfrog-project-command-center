from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

def utcnow() -> datetime:
    return datetime.utcnow()

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer: Mapped[str] = mapped_column(String(160), index=True)
    project_name: Mapped[str] = mapped_column(String(200))
    project_type: Mapped[str] = mapped_column(String(60), index=True)
    technical_manager: Mapped[str] = mapped_column(String(100), default="Chad")
    engineer: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    sales_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stage: Mapped[str] = mapped_column(String(60), default="Intake", index=True)
    risk: Mapped[str] = mapped_column(String(20), default="Green", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="Normal")
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
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

class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="Not Started")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
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
