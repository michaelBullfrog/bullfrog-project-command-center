import httpx
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from database import Base, SessionLocal, engine, get_db
from models import Milestone, NoteAttachment, Project, ProjectNote
from schemas import (
    MilestoneCreate, MilestoneOut, MilestoneUpdate, NoteOut,
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
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_NOTE = 5
ALLOWED_ATTACHMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt"}
INLINE_ATTACHMENT_TYPES = {"image/png", "image/jpeg", "application/pdf"}

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
    return select(Project).options(
        selectinload(Project.milestones),
        selectinload(Project.notes).selectinload(ProjectNote.attachments),
    )

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

app = FastAPI(title="Bullfrog Project Command Center", version="1.2.0", lifespan=lifespan)
def webex_oauth_configured() -> bool:
    return all(os.getenv(key) for key in (
        "WEBEX_CLIENT_ID", "WEBEX_CLIENT_SECRET", "WEBEX_REDIRECT_URI",
        "WEBEX_ALLOWED_DOMAIN", "SESSION_SECRET",
    ))

@app.middleware("http")
async def require_webex_login(request: Request, call_next):
    path = request.url.path
    public_path = (
        path == "/api/health"
        or path == "/login"
        or path == "/auth/webex"
        or path == "/auth/callback"
        or path.startswith("/static/")
    )
    if public_path:
        return await call_next(request)
    if not webex_oauth_configured():
        return JSONResponse(
            {"detail": "Webex SSO is not configured. Check the required environment variables."},
            status_code=503,
        )
    if not request.session.get("user"):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)

# Add SessionMiddleware after the auth middleware so it wraps authentication
# and makes request.session available before the access check runs.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET") or secrets.token_urlsafe(48),
    same_site="lax",
    https_only=True,
    max_age=8 * 60 * 60,
)

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"configured": webex_oauth_configured(), "error": None},
    )

@app.get("/auth/webex")
def webex_login(request: Request):
    if not webex_oauth_configured():
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"configured": False, "error": "Webex SSO is not configured."},
            status_code=503,
        )
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    params = urlencode({
        "response_type": "code",
        "client_id": os.environ["WEBEX_CLIENT_ID"],
        "redirect_uri": os.environ["WEBEX_REDIRECT_URI"],
        "scope": "spark:people_read",
        "state": state,
    })
    return RedirectResponse(f"https://webexapis.com/v1/authorize?{params}", status_code=303)

@app.get("/auth/callback")
async def webex_callback(request: Request, code: str | None = None, state: str | None = None):
    expected_state = request.session.pop("oauth_state", None)
    if not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"configured": True, "error": "The Webex sign-in could not be verified. Please try again."},
            status_code=400,
        )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_response = await client.post(
                "https://webexapis.com/v1/access_token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": os.environ["WEBEX_CLIENT_ID"],
                    "client_secret": os.environ["WEBEX_CLIENT_SECRET"],
                    "code": code,
                    "redirect_uri": os.environ["WEBEX_REDIRECT_URI"],
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]
            person_response = await client.get(
                "https://webexapis.com/v1/people/me",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            person_response.raise_for_status()
            person = person_response.json()
    except (httpx.HTTPError, KeyError, ValueError):
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"configured": True, "error": "Webex could not complete the sign-in. Please try again."},
            status_code=502,
        )

    emails = person.get("emails") or []
    email = str(emails[0]).lower().strip() if emails else ""
    allowed_domain = os.environ["WEBEX_ALLOWED_DOMAIN"].lower().lstrip("@").strip()
    allowed_org = os.getenv("WEBEX_ALLOWED_ORG_ID", "").strip()
    valid_domain = email.endswith(f"@{allowed_domain}")
    valid_org = not allowed_org or person.get("orgId") == allowed_org
    if not valid_domain or not valid_org:
        request.session.clear()
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"configured": True, "error": "This Webex account is not authorized for Bullfrog Projects."},
            status_code=403,
        )

    request.session.clear()
    request.session["user"] = {
        "name": person.get("displayName") or email,
        "email": email,
        "org_id": person.get("orgId"),
    }
    return RedirectResponse("/", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"user": request.session.get("user")},
    )

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
def add_note(
    project_id: int,
    author: str = Form(...),
    note: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    if not author.strip() or not note.strip():
        raise HTTPException(422, "Author and note are required")
    if len(files) > MAX_ATTACHMENTS_PER_NOTE:
        raise HTTPException(413, f"Maximum {MAX_ATTACHMENTS_PER_NOTE} attachments per note")
    item = ProjectNote(project_id=project_id, author=author.strip(), note=note.strip())
    db.add(item)
    db.flush()
    for upload in files:
        filename = Path(upload.filename or "").name
        if not filename:
            continue
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
            raise HTTPException(415, f"Unsupported attachment type: {extension or 'unknown'}")
        content = upload.file.read(MAX_ATTACHMENT_BYTES + 1)
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(413, f"{filename} exceeds the 10 MB limit")
        db.add(NoteAttachment(
            note_id=item.id,
            filename=filename,
            content_type=upload.content_type or "application/octet-stream",
            size_bytes=len(content),
            data=content,
        ))
    db.commit()
    return db.scalar(
        select(ProjectNote)
        .options(selectinload(ProjectNote.attachments))
        .where(ProjectNote.id == item.id)
    )

@app.get("/api/attachments/{attachment_id}")
def download_attachment(attachment_id: int, db: Session = Depends(get_db)):
    attachment = db.get(NoteAttachment, attachment_id)
    if not attachment:
        raise HTTPException(404, "Attachment not found")
    disposition = "inline" if attachment.content_type in INLINE_ATTACHMENT_TYPES else "attachment"
    encoded_name = quote(attachment.filename)
    return Response(
        content=attachment.data,
        media_type=attachment.content_type,
        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_name}"},
    )
