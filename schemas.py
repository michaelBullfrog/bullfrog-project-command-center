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

class NoteCreate(BaseModel):
    author: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1)

class NoteOut(NoteCreate):
    id: int
    project_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ProjectBase(BaseModel):
    customer: str = Field(min_length=1, max_length=160)
    project_name: str = Field(min_length=1, max_length=200)
    project_type: str = "Other"
    technical_manager: str = "Mike"
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
    model_config = ConfigDict(from_attributes=True)
