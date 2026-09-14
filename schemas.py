from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field

class MilestoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    status: str = "Not Started"
    due_date: date | None = None

class MilestoneUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    due_date: date | None = None

class MilestoneOut(MilestoneCreate):
    id: int
    project_id: int
    completed_date: date | None = None
    model_config = ConfigDict(from_attributes=True)

class AttachmentOut(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    model_config = ConfigDict(from_attributes=True)

class NoteCreate(BaseModel):
    author: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1)

class NoteOut(NoteCreate):
    id: int
    project_id: int
    created_at: datetime
    attachments: list[AttachmentOut] = []
    model_config = ConfigDict(from_attributes=True)

class ContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    contact_type: str = "Technical"
    is_primary: bool = False

class ContactUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    contact_type: str | None = None
    is_primary: bool | None = None

class ContactOut(ContactCreate):
    id: int
    project_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ActivityOut(BaseModel):
    id: int
    project_id: int
    actor_name: str
    actor_email: str | None = None
    action: str
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    description: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ProjectBase(BaseModel):
    customer: str = Field(min_length=1, max_length=160)
    project_name: str = Field(min_length=1, max_length=200)
    project_type: str = "Other"
    technical_manager: str = "Chad"
    engineer: str | None = None
    sales_owner: str | None = None
    stage: str = "Intake"
    risk: str = "Green"
    priority: str = "Normal"
    target_date: date | None = None
    next_action: str | None = None
    next_action_owner: str | None = None
    next_action_due: date | None = None
    blocked: bool = False
    blocker: str | None = None
    scope: str | None = None

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(BaseModel):
    customer: str | None = None
    project_name: str | None = None
    project_type: str | None = None
    technical_manager: str | None = None
    engineer: str | None = None
    sales_owner: str | None = None
    stage: str | None = None
    risk: str | None = None
    priority: str | None = None
    target_date: date | None = None
    next_action: str | None = None
    next_action_owner: str | None = None
    next_action_due: date | None = None
    blocked: bool | None = None
    blocker: str | None = None
    scope: str | None = None

class ProjectOut(ProjectBase):
    id: int
    created_at: datetime
    updated_at: datetime
    milestones: list[MilestoneOut] = []
    notes: list[NoteOut] = []
    contacts: list[ContactOut] = []
    activities: list[ActivityOut] = []
    model_config = ConfigDict(from_attributes=True)


class IntakeEmailCreate(BaseModel):
    message_id: str = Field(min_length=1, max_length=500)
    subject: str = Field(min_length=1, max_length=500)
    sender_name: str | None = Field(default=None, max_length=200)
    sender_email: str | None = Field(default=None, max_length=320)
    body: str | None = None
    received_at: datetime | None = None

class IntakeEmailOut(IntakeEmailCreate):
    id: int
    status: str
    project_id: int | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class IntakeConvert(BaseModel):
    project: ProjectCreate
