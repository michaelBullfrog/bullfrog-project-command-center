from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from database import Base, SessionLocal, engine, get_db
from models import Milestone, Project, ProjectNote
from schemas import (
    MilestoneCreate, MilestoneOut, MilestoneUpdate, NoteCreate, NoteOut,
    ProjectCreate, ProjectOut, ProjectUpdate,
)

STAGES = ["Intake", "Technical Review", "Ready to Schedule", "Implementation", "Testing",
          "Customer Acceptance", "Waiting on Customer", "On Hold", "Complete"]
RISKS = ["Green", "Yellow", "Red"]
PRIORITIES = ["Normal", "High", "Critical"]
PROJECT_TYPES = ["Webex Calling", "Webex Contact Center", "Meraki", "Network", "Other"]
ENGINEERS = ["Gabriel", "Zach", "Michael"]
SALES_OWNERS = ["Jack", "Matt"]
CUSTOMER_SUCCESS_MANAGERS = ["Chad", "Ryan"]
NEXT_ACTION_OWNERS = ENGINEERS + SALES_OWNERS + CUSTOMER_SUCCESS_MANAGERS

TEMPLATES = {
    "Webex Calling": ["Discovery Complete", "Network Review Complete", "Control Hub Provisioned",
        "Users and Licenses Configured", "Number Port Submitted", "FOC Received",
        "Devices Configured", "Call Flows Tested", "Customer Training", "Go Live", "Closeout"],
    "Webex Contact Center": ["Discovery Complete", "Call Flow Design", "Queue and Team Design",
        "Agent Setup", "Integrations", "Flow Build", "Testing", "Supervisor Training", "Go Live", "Closeout"],
    "Meraki": ["Discovery Complete", "Network Design", "Hardware Received", "Configuration",
        "Staging", "Installation", "Validation", "Documentation", "Closeout"],
    "Network": ["Discovery Complete", "Network Design", "Hardware Received", "Configuration",
        "Installation", "Validation", "Documentation", "Closeout"],
    "Other": ["Discovery Complete", "Planning", "Implementation", "Testing", "Customer Acceptance", "Closeout"],
}

def project_query():
    return select(Project).options(selectinload(Project.milestones), selectinload(Project.notes))

def seed_database():
    db = SessionLocal()
    try:
        # One-time compatibility cleanup for projects created before the
        # Technical Manager field became Customer Success Manager.
        for project in db.scalars(select(Project).where(Project.technical_manager == "Mike")):
            project.technical_manager = "Chad"
        db.commit()
        if db.scalar(select(Project.id).limit(1)):
            return
        today = date.today()
        examples = [
            Project(customer="ABC Manufacturing", project_name="Webex Calling Deployment",
                project_type="Webex Calling", engineer="Chris", sales_owner="John",
                stage="Implementation", risk="Yellow", priority="High", target_date=today + timedelta(days=12),
                next_action="Resolve porting issue and confirm FOC", next_action_owner="Mike",
                next_action_due=today + timedelta(days=1), blocked=True, blocker="Waiting for carrier FOC",
                scope="Deploy Webex Calling for 62 users across two locations."),
            Project(customer="Smith Dental", project_name="Contact Center Launch",
                project_type="Webex Contact Center", engineer="Dan", sales_owner="Sarah",
                stage="Waiting on Customer", risk="Red", priority="Critical", target_date=today + timedelta(days=6),
                next_action="Receive approved call flow", next_action_owner="Customer",
                next_action_due=today - timedelta(days=1), blocked=True, blocker="Call flow approval outstanding",
                scope="New contact center with voice queues, recording, and supervisor reporting."),
            Project(customer="Acme Corporation", project_name="Meraki Network Refresh",
                project_type="Meraki", engineer="Chris", sales_owner="John",
                stage="Ready to Schedule", risk="Green", target_date=today + timedelta(days=24),
                next_action="Confirm installation date", next_action_owner="Customer",
                next_action_due=today + timedelta(days=4), scope="MX, MS, and MR refresh at headquarters."),
        ]
        for project in examples:
            db.add(project)
            db.flush()
            for name in TEMPLATES[project.project_type]:
                db.add(Milestone(project_id=project.id, name=name))
        db.commit()
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_database()
    yield

app = FastAPI(title="Bullfrog Project Command Center", version="1.0.0", lifespan=lifespan)
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/options")
def options():
    return {"stages": STAGES, "risks": RISKS, "priorities": PRIORITIES,
            "project_types": PROJECT_TYPES, "templates": TEMPLATES,
            "engineers": ENGINEERS, "sales_owners": SALES_OWNERS,
            "customer_success_managers": CUSTOMER_SUCCESS_MANAGERS,
            "next_action_owners": NEXT_ACTION_OWNERS}

@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(
    search: str | None = None, stage: str | None = None, risk: str | None = None,
    engineer: str | None = None, project_type: str | None = Query(None, alias="type"),
    db: Session = Depends(get_db),
):
    stmt = project_query().order_by(Project.target_date.asc().nullslast(), Project.updated_at.desc())
    if search:
        term = f"%{search}%"
        stmt = stmt.where(or_(Project.customer.ilike(term), Project.project_name.ilike(term)))
    if stage: stmt = stmt.where(Project.stage == stage)
    if risk: stmt = stmt.where(Project.risk == risk)
    if engineer: stmt = stmt.where(Project.engineer == engineer)
    if project_type: stmt = stmt.where(Project.project_type == project_type)
    return list(db.scalars(stmt).unique().all())

@app.post("/api/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(**payload.model_dump())
    db.add(project)
    db.flush()
    for name in TEMPLATES.get(project.project_type, TEMPLATES["Other"]):
        db.add(Milestone(project_id=project.id, name=name))
    db.commit()
    return db.scalar(project_query().where(Project.id == project.id))

@app.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.scalar(project_query().where(Project.id == project_id))
    if not project:
        raise HTTPException(404, "Project not found")
    return project

@app.put("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    db.commit()
    return db.scalar(project_query().where(Project.id == project_id))

@app.delete("/api/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.post("/api/projects/{project_id}/milestones", response_model=MilestoneOut, status_code=201)
def add_milestone(project_id: int, payload: MilestoneCreate, db: Session = Depends(get_db)):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    item = Milestone(project_id=project_id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return item

@app.patch("/api/milestones/{milestone_id}", response_model=MilestoneOut)
def update_milestone(milestone_id: int, payload: MilestoneUpdate, db: Session = Depends(get_db)):
    item = db.get(Milestone, milestone_id)
    if not item:
        raise HTTPException(404, "Milestone not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    item.completed_date = date.today() if item.status == "Complete" else None
    db.commit(); db.refresh(item)
    return item

@app.delete("/api/milestones/{milestone_id}", status_code=204)
def delete_milestone(milestone_id: int, db: Session = Depends(get_db)):
    item = db.get(Milestone, milestone_id)
    if not item:
        raise HTTPException(404, "Milestone not found")
    db.delete(item); db.commit()
    return Response(status_code=204)

@app.post("/api/projects/{project_id}/notes", response_model=NoteOut, status_code=201)
def add_note(project_id: int, payload: NoteCreate, db: Session = Depends(get_db)):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    note = ProjectNote(project_id=project_id, **payload.model_dump())
    db.add(note); db.commit(); db.refresh(note)
    return note
