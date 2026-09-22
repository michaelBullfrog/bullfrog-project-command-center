import asyncio
import html
import json
import httpx
import logging
import re
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote, unquote, urlencode
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect, or_, select, text
from sqlalchemy.orm import Session, selectinload

from database import Base, SessionLocal, engine, get_db
from models import CustomProjectTemplate, CustomerContact, HardwareOrderWorkflow, IntakeEmail, Milestone, NoteAttachment, Project, ProjectActivity, ProjectNote, ProjectWorkItem, PsaTicketWorkflow
from schemas import (
    ContactCreate, ContactOut, ContactUpdate, IntakeConvert, IntakeEmailCreate, IntakeEmailOut,
    MilestoneCreate, MilestoneOut, MilestoneUpdate, NoteOut, ProjectCreate, ProjectOut, ProjectUpdate,
    ProjectTemplateCreate, ProjectTemplateOut, WorkItemLink,
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
PSA_USERS = {
    "Chad": "01KKF7PVMWVPZR94AEQS16Y006",
    "Michael": "01KKF7TPZ18APSA2PF4JNX7PAS",
    "Gabriel": "01KKXX54ZETXXFPXSHNR06HA94",
    "Zach": "01KKVPJEXD1PW9D0X1VF8S8598",
    "Ryan": "01KKXT22MVQRM5R0TZV8X1922E",
    "Jack": "01KKF79JYR6K8B333BPSKCBNEP",
    "Matt": "01KPXEWW7F6CVFGFMC11QTSS3D",
}
PSA_TICKET_TYPE_ID = 3
PSA_NEW_STATUS_ID = 1
PSA_COMPLETE_STATUS_ID = 4
PSA_PRIORITY_ID = 2

def psa_ticket_automation_enabled() -> bool:
    return os.getenv("REVIO_PSA_TICKET_AUTOMATION_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_NOTE = 5
ALLOWED_ATTACHMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt"}
INLINE_ATTACHMENT_TYPES = {"image/png", "image/jpeg", "application/pdf"}
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
GRAPH_API = "https://graph.microsoft.com/v1.0"
logger = logging.getLogger("bullfrog.graph")

TEMPLATES = {
    "Webex Calling": [
        "Signed Proposal", "Internal Handoff", "Kickoff Call", "Call Flow", "User Spreadsheet",
        "LOA Document", "Port Submitted", "Hardware Payment Check", "Hardware Ordered", "FOC Received", "Port Complete",
        "Hardware Delivered", "Devices Registered", "Users Added", "Go Live Follow Up", "Go Live", "Closeout",
    ],
    "Webex Contact Center": [
        "Signed Proposal", "Internal Handoff", "Kickoff Call", "Call Flow", "User Spreadsheet",
        "Users Added", "Agent Setup", "Integrations", "Flow Build", "Testing", "Supervisor Training",
        "Go Live Follow Up", "Go Live", "Closeout",
    ],
    "Meraki": ["Signed Proposal", "Internal Handoff", "Kickoff Call", "Hardware Payment Check", "Hardware Ordered", "Hardware Delivered",
        "Devices Registered", "Network Design", "Configuration", "Staging", "Installation", "Validation",
        "Documentation", "Go Live Follow Up", "Closeout"],
    "Network": ["Signed Proposal", "Internal Handoff", "Kickoff Call", "Hardware Payment Check", "Hardware Ordered", "Hardware Delivered",
        "Devices Registered", "Network Design", "Configuration", "Installation", "Validation",
        "Documentation", "Go Live Follow Up", "Closeout"],
    "Other": ["Signed Proposal", "Internal Handoff", "Kickoff Call", "Planning", "Implementation",
        "Testing", "Customer Acceptance", "Go Live Follow Up", "Closeout"],
}

PHASE_TEMPLATES = {
    "Webex Calling": [
        {"name": "Planning & Handoff", "owner": "csm", "milestones": ["Signed Proposal", "Internal Handoff", "Kickoff Call"]},
        {"name": "Design & Discovery", "owner": "engineer", "milestones": ["Call Flow", "User Spreadsheet", "LOA Document"]},
        {"name": "Hardware & Provisioning", "owner": "engineer", "milestones": ["Hardware Payment Check", "Hardware Ordered", "Hardware Delivered", "Devices Registered", "Users Added"]},
        {"name": "Number Porting", "owner": "engineer", "milestones": ["Port Submitted", "FOC Received", "Port Complete"]},
        {"name": "Go Live & Closeout", "owner": "csm", "milestones": ["Go Live Follow Up", "Go Live", "Closeout"]},
    ],
    "Webex Contact Center": [
        {"name": "Planning & Handoff", "owner": "csm", "milestones": ["Signed Proposal", "Internal Handoff", "Kickoff Call"]},
        {"name": "Design", "owner": "engineer", "milestones": ["Call Flow", "User Spreadsheet"]},
        {"name": "Build & Integration", "owner": "engineer", "milestones": ["Users Added", "Agent Setup", "Integrations", "Flow Build"]},
        {"name": "Testing & Training", "owner": "engineer", "milestones": ["Testing", "Supervisor Training"]},
        {"name": "Go Live & Closeout", "owner": "csm", "milestones": ["Go Live Follow Up", "Go Live", "Closeout"]},
    ],
    "Meraki": [
        {"name": "Planning & Handoff", "owner": "csm", "milestones": ["Signed Proposal", "Internal Handoff", "Kickoff Call"]},
        {"name": "Hardware", "owner": "sales", "milestones": ["Hardware Payment Check", "Hardware Ordered", "Hardware Delivered"]},
        {"name": "Design & Configuration", "owner": "engineer", "milestones": ["Devices Registered", "Network Design", "Configuration", "Staging"]},
        {"name": "Deployment", "owner": "engineer", "milestones": ["Installation", "Validation", "Documentation"]},
        {"name": "Closeout", "owner": "csm", "milestones": ["Go Live Follow Up", "Closeout"]},
    ],
    "Network": [
        {"name": "Planning & Handoff", "owner": "csm", "milestones": ["Signed Proposal", "Internal Handoff", "Kickoff Call"]},
        {"name": "Hardware", "owner": "sales", "milestones": ["Hardware Payment Check", "Hardware Ordered", "Hardware Delivered"]},
        {"name": "Design & Configuration", "owner": "engineer", "milestones": ["Devices Registered", "Network Design", "Configuration"]},
        {"name": "Deployment", "owner": "engineer", "milestones": ["Installation", "Validation", "Documentation"]},
        {"name": "Closeout", "owner": "csm", "milestones": ["Go Live Follow Up", "Closeout"]},
    ],
    "Other": [
        {"name": "Planning & Handoff", "owner": "csm", "milestones": ["Signed Proposal", "Internal Handoff", "Kickoff Call", "Planning"]},
        {"name": "Delivery", "owner": "engineer", "milestones": ["Implementation", "Testing", "Customer Acceptance"]},
        {"name": "Closeout", "owner": "csm", "milestones": ["Go Live Follow Up", "Closeout"]},
    ],
}

WORK_ITEM_TEMPLATES = {
    "Webex Calling": [
        {"phase": "Planning & Handoff", "name": "Internal Handoff Meeting", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Review signed scope, ownership, dependencies, and target dates with the Bullfrog delivery team."},
        {"phase": "Planning & Handoff", "name": "Customer Kickoff Call", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Hold the customer kickoff and confirm contacts, scope, schedule, and required inputs."},
        {"phase": "Design & Discovery", "name": "Calling Design and Call Flow", "item_type": "Ticket", "owner": "engineer", "hours": 3.0, "description": "Document dial plan, calling features, auto attendants, queues, hours, caller ID, and emergency calling requirements."},
        {"phase": "Design & Discovery", "name": "Collect User and Porting Documents", "item_type": "Ticket", "owner": "csm", "hours": 1.5, "description": "Collect and validate the user spreadsheet, number inventory, LOA, CSR, and customer approvals."},
        {"phase": "Hardware & Provisioning", "name": "Order and Track Hardware", "item_type": "Ticket", "owner": "sales", "hours": 1.0, "description": "Order approved hardware after payment clearance and record shipment and tracking information."},
        {"phase": "Hardware & Provisioning", "name": "Configure Users and Devices", "item_type": "Ticket", "owner": "engineer", "hours": 4.0, "description": "Provision users, workspaces, licenses, calling features, and device assignments."},
        {"phase": "Number Porting", "name": "Submit and Manage Number Port", "item_type": "Ticket", "owner": "engineer", "hours": 2.0, "description": "Submit number ports, manage rejects, record FOC, and validate port completion."},
        {"phase": "Go Live & Closeout", "name": "Customer Training", "item_type": "Task", "owner": "engineer", "hours": 1.0, "description": "Provide administrator and end-user training before go-live."},
        {"phase": "Go Live & Closeout", "name": "Go-Live Appointment", "item_type": "Task", "owner": "engineer", "hours": 2.0, "description": "Complete the scheduled cutover, testing, and customer validation."},
        {"phase": "Go Live & Closeout", "name": "Post-Go-Live Review", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Review service after go-live and capture outstanding items."},
        {"phase": "Go Live & Closeout", "name": "Documentation and Closeout", "item_type": "Ticket", "owner": "csm", "hours": 1.0, "description": "Complete documentation, acceptance, handoff, and project closeout."},
    ],
    "Webex Contact Center": [
        {"phase": "Planning & Handoff", "name": "Internal Handoff Meeting", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Review scope, ownership, integrations, dependencies, and target dates."},
        {"phase": "Planning & Handoff", "name": "Customer Kickoff Call", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Confirm project scope, contacts, schedule, and required discovery inputs."},
        {"phase": "Design", "name": "Contact Center Discovery and Call Flow", "item_type": "Ticket", "owner": "engineer", "hours": 4.0, "description": "Document entry points, queues, teams, routing, IVR, hours, recording, and reporting requirements."},
        {"phase": "Build & Integration", "name": "Build Contact Center Configuration", "item_type": "Ticket", "owner": "engineer", "hours": 8.0, "description": "Configure users, agents, teams, queues, routing flows, desktop profiles, and required integrations."},
        {"phase": "Testing & Training", "name": "Customer Acceptance Testing", "item_type": "Ticket", "owner": "engineer", "hours": 3.0, "description": "Execute test cases and resolve issues before customer acceptance."},
        {"phase": "Testing & Training", "name": "Supervisor and Agent Training", "item_type": "Task", "owner": "engineer", "hours": 2.0, "description": "Deliver scheduled supervisor and agent training."},
        {"phase": "Go Live & Closeout", "name": "Go-Live Appointment", "item_type": "Task", "owner": "engineer", "hours": 2.0, "description": "Complete the scheduled production cutover and validation."},
        {"phase": "Go Live & Closeout", "name": "Post-Go-Live Review", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Review production results and outstanding issues."},
        {"phase": "Go Live & Closeout", "name": "Documentation and Closeout", "item_type": "Ticket", "owner": "csm", "hours": 1.0, "description": "Complete documentation, acceptance, handoff, and closeout."},
    ],
    "Meraki": [
        {"phase": "Planning & Handoff", "name": "Internal Handoff Meeting", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Review scope, hardware, dependencies, and installation targets."},
        {"phase": "Planning & Handoff", "name": "Customer Kickoff Call", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Confirm contacts, topology, schedule, access, and required inputs."},
        {"phase": "Hardware", "name": "Order and Track Hardware", "item_type": "Ticket", "owner": "sales", "hours": 1.0, "description": "Order approved hardware and record shipment and tracking details."},
        {"phase": "Design & Configuration", "name": "Network Design and Configuration", "item_type": "Ticket", "owner": "engineer", "hours": 5.0, "description": "Complete topology, VLAN, addressing, firewall, VPN, switching, and wireless configuration."},
        {"phase": "Design & Configuration", "name": "Register and Stage Devices", "item_type": "Ticket", "owner": "engineer", "hours": 3.0, "description": "Claim, register, update, configure, and stage Meraki equipment."},
        {"phase": "Deployment", "name": "Installation Appointment", "item_type": "Task", "owner": "engineer", "hours": 4.0, "description": "Perform the scheduled onsite or remote deployment."},
        {"phase": "Deployment", "name": "Validation and Documentation", "item_type": "Ticket", "owner": "engineer", "hours": 2.0, "description": "Validate connectivity and services, resolve issues, and complete documentation."},
        {"phase": "Closeout", "name": "Customer Follow-Up", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Review the completed deployment with the customer."},
        {"phase": "Closeout", "name": "Project Closeout", "item_type": "Ticket", "owner": "csm", "hours": 1.0, "description": "Complete acceptance, internal handoff, and closeout."},
    ],
    "Network": [
        {"phase": "Planning & Handoff", "name": "Internal Handoff Meeting", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Review scope, hardware, dependencies, and installation targets."},
        {"phase": "Planning & Handoff", "name": "Customer Kickoff Call", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Confirm contacts, topology, schedule, access, and required inputs."},
        {"phase": "Hardware", "name": "Order and Track Hardware", "item_type": "Ticket", "owner": "sales", "hours": 1.0, "description": "Order approved hardware and record shipment and tracking details."},
        {"phase": "Design & Configuration", "name": "Network Design and Configuration", "item_type": "Ticket", "owner": "engineer", "hours": 5.0, "description": "Complete network design, addressing, security, switching, wireless, and configuration work."},
        {"phase": "Deployment", "name": "Installation Appointment", "item_type": "Task", "owner": "engineer", "hours": 4.0, "description": "Perform the scheduled onsite or remote deployment."},
        {"phase": "Deployment", "name": "Validation and Documentation", "item_type": "Ticket", "owner": "engineer", "hours": 2.0, "description": "Validate the deployment, resolve issues, and complete documentation."},
        {"phase": "Closeout", "name": "Customer Follow-Up", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Review the completed deployment with the customer."},
        {"phase": "Closeout", "name": "Project Closeout", "item_type": "Ticket", "owner": "csm", "hours": 1.0, "description": "Complete acceptance, internal handoff, and closeout."},
    ],
    "Other": [
        {"phase": "Planning & Handoff", "name": "Internal Handoff Meeting", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Review scope, ownership, dependencies, and target dates."},
        {"phase": "Planning & Handoff", "name": "Customer Kickoff Call", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Confirm customer contacts, scope, schedule, and inputs."},
        {"phase": "Delivery", "name": "Project Delivery Work", "item_type": "Ticket", "owner": "engineer", "hours": 4.0, "description": "Complete the technical implementation and testing work."},
        {"phase": "Closeout", "name": "Customer Follow-Up", "item_type": "Task", "owner": "csm", "hours": 1.0, "description": "Review the completed work with the customer."},
        {"phase": "Closeout", "name": "Project Closeout", "item_type": "Ticket", "owner": "csm", "hours": 1.0, "description": "Complete documentation, acceptance, and closeout."},
    ],
}

def custom_template_phases(db: Session, project_type: str) -> list[dict] | None:
    template = db.scalar(
        select(CustomProjectTemplate).where(CustomProjectTemplate.name == project_type)
    )
    if not template:
        return None
    try:
        phases = json.loads(template.phases_json)
    except (TypeError, ValueError):
        return None
    return [
        {
            "name": str(phase.get("name") or "").strip(),
            "owner": str(phase.get("owner_role") or phase.get("owner") or "engineer").strip(),
            "milestones": [str(name).strip() for name in phase.get("milestones", []) if str(name).strip()],
            "work_items": [
                {
                    "name": str(work.get("name") or "").strip(),
                    "item_type": str(work.get("item_type") or "Ticket").strip().title(),
                    "owner": str(work.get("owner_role") or work.get("owner") or "engineer").strip().lower(),
                    "hours": work.get("estimated_hours"),
                    "description": str(work.get("description") or "").strip() or None,
                }
                for work in phase.get("work_items", [])
                if str(work.get("name") or "").strip()
            ],
        }
        for phase in phases
        if str(phase.get("name") or "").strip()
    ]

def project_phase_definitions(project_type: str, db: Session | None = None) -> list[dict]:
    if project_type in PHASE_TEMPLATES:
        return PHASE_TEMPLATES[project_type]
    custom = custom_template_phases(db, project_type) if db else None
    return custom or PHASE_TEMPLATES["Other"]

def project_template_milestones(project_type: str, db: Session) -> list[tuple[str, str]]:
    return [
        (milestone, phase["name"])
        for phase in project_phase_definitions(project_type, db)
        for milestone in phase["milestones"]
    ]

def project_work_definitions(project_type: str, db: Session) -> list[dict]:
    if project_type in WORK_ITEM_TEMPLATES:
        return WORK_ITEM_TEMPLATES[project_type]
    definitions = []
    for phase in project_phase_definitions(project_type, db):
        for work in phase.get("work_items", []):
            definitions.append({
                "phase": phase["name"],
                "name": work["name"],
                "item_type": work.get("item_type", "Ticket"),
                "owner": work.get("owner", phase.get("owner", "engineer")),
                "hours": work.get("hours"),
                "description": work.get("description"),
            })
    return definitions

def work_item_assignee(project: Project, owner_role: str) -> str | None:
    if owner_role == "csm":
        return project.technical_manager
    if owner_role == "sales":
        return project.sales_owner or project.technical_manager
    return project.engineer or project.technical_manager

def project_work_template_key(definition: dict) -> str:
    raw = f"{definition['phase']}::{definition['item_type']}::{definition['name']}"
    return re.sub(r"[^a-z0-9]+", "-", raw.casefold()).strip("-")[:180]

def add_project_work_items(db: Session, project: Project):
    existing = {
        item.template_key for item in db.scalars(
            select(ProjectWorkItem).where(ProjectWorkItem.project_id == project.id)
        ).all()
    }
    for definition in project_work_definitions(project.project_type, db):
        template_key = project_work_template_key(definition)
        if template_key in existing:
            continue
        db.add(ProjectWorkItem(
            project_id=project.id,
            template_key=template_key,
            phase_name=definition["phase"],
            name=definition["name"],
            item_type=definition["item_type"],
            owner_role=definition.get("owner", "engineer"),
            assignee_name=work_item_assignee(project, definition.get("owner", "engineer")),
            description=definition.get("description"),
            estimated_hours=definition.get("hours"),
        ))
        existing.add(template_key)

def ensure_project_work_items():
    db = SessionLocal()
    try:
        projects = list(db.scalars(select(Project).where(Project.stage != "Complete")).all())
        for project in projects:
            add_project_work_items(db, project)
        db.commit()
    finally:
        db.close()

def milestone_phase_info(
    project_type: str, milestone_name: str, db: Session | None = None
) -> tuple[str, str]:
    for phase in project_phase_definitions(project_type, db):
        if milestone_name in phase["milestones"]:
            return phase["name"], phase["owner"]
    return "Additional", "engineer"

def ensure_project_phase_names():
    db = SessionLocal()
    try:
        projects = list(db.scalars(project_query()).unique().all())
        changed = False
        for project in projects:
            for milestone in project.milestones:
                if not milestone.phase_name:
                    milestone.phase_name = milestone_phase_info(project.project_type, milestone.name, db)[0]
                    changed = True
        if changed:
            db.commit()
    finally:
        db.close()

WORKFLOW_MILESTONES = {
    "Webex Calling": ["Signed Proposal", "Kickoff Call", "LOA Document", "FOC Received", "Port Complete",
                      "Hardware Payment Check", "Hardware Ordered", "Hardware Delivered", "User Spreadsheet"],
    "Webex Contact Center": ["Signed Proposal", "Kickoff Call", "User Spreadsheet"],
    "Meraki": ["Signed Proposal", "Kickoff Call", "Hardware Payment Check", "Hardware Ordered", "Hardware Delivered"],
    "Network": ["Signed Proposal", "Kickoff Call", "Hardware Payment Check", "Hardware Ordered", "Hardware Delivered"],
    "Other": ["Signed Proposal", "Kickoff Call"],
}

def project_query():
    return select(Project).options(
        selectinload(Project.milestones),
        selectinload(Project.work_items),
        selectinload(Project.notes).selectinload(ProjectNote.attachments),
        selectinload(Project.contacts),
        selectinload(Project.activities),
    )

FIELD_LABELS = {
    "customer": "Customer", "customer_id": "Rev PSA Customer ID", "quote_id": "Rev.io Quote ID", "revio_project_id": "Rev PSA Project ID", "project_name": "Project name", "project_type": "Project type",
    "technical_manager": "Customer Success Manager", "engineer": "Assigned Engineer",
    "sales_owner": "Sales Owner", "stage": "Stage", "risk": "Risk", "priority": "Priority",
    "start_date": "Start date", "target_date": "Target go-live", "project_budget": "Project budget",
    "budget_hours": "Budget hours", "estimated_hours": "Estimated hours", "is_billable": "Billable",
    "project_notes": "Rev PSA notes", "revio_project_status_id": "Rev PSA status",
    "revio_project_priority_id": "Rev PSA priority", "next_action": "Next action",
    "next_action_owner": "Next action owner", "next_action_due": "Next action due",
    "blocked": "Blocked", "blocker": "Blocker", "scope": "Scope",
}

def activity_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)

def current_actor(request: Request) -> tuple[str, str | None]:
    user = request.session.get("user") or {}
    return user.get("name", "Unknown user"), user.get("email")

def record_activity(
    db: Session, project_id: int, request: Request, action: str, description: str,
    field_name: str | None = None, old_value=None, new_value=None,
):
    actor_name, actor_email = current_actor(request)
    db.add(ProjectActivity(
        project_id=project_id, actor_name=actor_name, actor_email=actor_email,
        action=action, field_name=field_name,
        old_value=activity_value(old_value) if old_value is not None else None,
        new_value=activity_value(new_value) if new_value is not None else None,
        description=description,
    ))

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
                db.add(Milestone(project_id=project.id, name=name, phase_name=milestone_phase_info(project.project_type, name)[0]))
        db.commit()
    finally:
        db.close()

def graph_configured() -> bool:
    return all(os.getenv(key) for key in ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET", "MS_INTAKE_MAILBOX"))

def graph_notification_url() -> str | None:
    base_url = (os.getenv("APP_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    return f"{base_url}/api/graph/notifications" if base_url else None

async def graph_access_token(client: httpx.AsyncClient) -> str:
    tenant = quote(os.environ["MS_TENANT_ID"], safe="")
    response = await client.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "client_id": os.environ["MS_CLIENT_ID"],
            "client_secret": os.environ["MS_CLIENT_SECRET"],
            "scope": GRAPH_SCOPE,
            "grant_type": "client_credentials",
        },
    )
    response.raise_for_status()
    return response.json()["access_token"]

def graph_received_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None

def store_graph_message(db: Session, message: dict) -> bool:
    graph_id = str(message.get("id") or "").strip()
    internet_id = str(message.get("internetMessageId") or "").strip()
    unique_id = internet_id or graph_id
    if not unique_id or db.scalar(select(IntakeEmail.id).where(IntakeEmail.message_id == unique_id)):
        return False
    sender = ((message.get("from") or {}).get("emailAddress") or {})
    body = message.get("body") or {}
    db.add(IntakeEmail(
        message_id=unique_id,
        sender_name=sender.get("name"),
        sender_email=sender.get("address"),
        subject=str(message.get("subject") or "(No subject)")[:500],
        body=body.get("content") or message.get("bodyPreview"),
        received_at=graph_received_datetime(message.get("receivedDateTime")),
    ))
    return True

async def graph_sync_recent_messages(limit: int = 50) -> int:
    if not graph_configured():
        raise RuntimeError("Microsoft Graph is not configured")
    mailbox = quote(os.environ["MS_INTAKE_MAILBOX"], safe="")
    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await graph_access_token(client)
        response = await client.get(
            f"{GRAPH_API}/users/{mailbox}/mailFolders/inbox/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "$select": "id,internetMessageId,subject,from,body,bodyPreview,receivedDateTime",
                "$orderby": "receivedDateTime desc",
                "$top": str(max(1, min(limit, 100))),
            },
        )
        response.raise_for_status()
        messages = response.json().get("value", [])
    db = SessionLocal()
    try:
        added = sum(1 for message in messages if store_graph_message(db, message))
        db.commit()
        return added
    finally:
        db.close()

async def graph_fetch_messages(message_ids: list[str]):
    if not graph_configured() or not message_ids:
        return
    mailbox = quote(os.environ["MS_INTAKE_MAILBOX"], safe="")
    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await graph_access_token(client)
        messages = []
        for message_id in dict.fromkeys(message_ids):
            response = await client.get(
                f"{GRAPH_API}/users/{mailbox}/messages/{quote(message_id, safe='')}",
                headers={"Authorization": f"Bearer {token}"},
                params={"$select": "id,internetMessageId,subject,from,body,bodyPreview,receivedDateTime"},
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            messages.append(response.json())
    db = SessionLocal()
    try:
        for message in messages:
            store_graph_message(db, message)
        db.commit()
    finally:
        db.close()

async def ensure_graph_subscription():
    notification_url = graph_notification_url()
    if not graph_configured() or not notification_url or not os.getenv("INTAKE_WEBHOOK_SECRET"):
        return
    mailbox = quote(os.environ["MS_INTAKE_MAILBOX"], safe="")
    resource = f"/users/{mailbox}/mailFolders('Inbox')/messages"
    now = datetime.now(timezone.utc)
    expiration = now + timedelta(days=3)
    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await graph_access_token(client)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        current = await client.get(f"{GRAPH_API}/subscriptions", headers=headers)
        current.raise_for_status()
        matches = [item for item in current.json().get("value", [])
                   if item.get("notificationUrl") == notification_url and item.get("resource", "").lower() == resource.lower()]
        if matches:
            item = matches[0]
            expires = datetime.fromisoformat(item["expirationDateTime"].replace("Z", "+00:00"))
            if expires > now + timedelta(hours=36):
                return
            response = await client.patch(
                f"{GRAPH_API}/subscriptions/{quote(item['id'], safe='')}",
                headers=headers, json={"expirationDateTime": expiration.isoformat().replace("+00:00", "Z")},
            )
        else:
            response = await client.post(
                f"{GRAPH_API}/subscriptions", headers=headers,
                json={
                    "changeType": "created", "notificationUrl": notification_url,
                    "resource": resource,
                    "expirationDateTime": expiration.isoformat().replace("+00:00", "Z"),
                    "clientState": os.environ["INTAKE_WEBHOOK_SECRET"],
                },
            )
        response.raise_for_status()

async def graph_subscription_maintenance():
    while True:
        try:
            await ensure_graph_subscription()
        except Exception:
            logger.exception("Unable to create or renew Microsoft Graph subscription")
        await asyncio.sleep(12 * 60 * 60)

def ensure_database_schema():
    # create_all handles fresh databases; this small compatibility migration
    # adds Customer ID to existing Render PostgreSQL databases.
    columns = {column["name"] for column in inspect(engine).get_columns("projects")}
    if "customer_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE projects ADD COLUMN customer_id VARCHAR(50)"))
    if "quote_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE projects ADD COLUMN quote_id VARCHAR(50)"))
    project_additions = {
        "revio_project_id": "VARCHAR(50)",
        "revio_project_status_id": "INTEGER",
        "revio_project_priority_id": "INTEGER",
        "revio_sync_status": "VARCHAR(40) DEFAULT 'Not Created'",
        "revio_sync_error": "TEXT",
        "revio_synced_at": "TIMESTAMP",
        "start_date": "DATE",
        "project_budget": "DOUBLE PRECISION",
        "budget_hours": "DOUBLE PRECISION",
        "estimated_hours": "DOUBLE PRECISION",
        "is_billable": "BOOLEAN DEFAULT TRUE",
        "project_notes": "TEXT",
    }
    for column_name, column_type in project_additions.items():
        if column_name not in columns:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE projects ADD COLUMN {column_name} {column_type}"))
    milestone_columns = {column["name"] for column in inspect(engine).get_columns("milestones")}
    milestone_additions = {
        "revio_milestone_id": "VARCHAR(50)",
        "revio_phase_id": "VARCHAR(50)",
        "phase_name": "VARCHAR(120)",
    }
    for column_name, column_type in milestone_additions.items():
        if column_name not in milestone_columns:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE milestones ADD COLUMN {column_name} {column_type}"))

def revio_configured() -> bool:
    return bool(os.getenv("REVIO_API_KEY", "").strip())

def revio_records(payload) -> list[dict]:
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "customers", "records", "results", "data"):
            items = data.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []

def revio_value(item: dict, *keys):
    lowered = {str(key).lower(): value for key, value in item.items()}
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None

async def revio_lookup_customer(customer_id: str) -> dict | None:
    base_url = os.getenv("REVIO_BASE_URL", "https://api.psarev.io").rstrip("/")
    host = os.getenv("REVIO_HOST", "bullfrog.psarev.io").strip()
    exchange_path = os.getenv("REVIO_TOKEN_EXCHANGE_PATH", "/api/v1/auth/api-key/exchange")
    customer_path = os.getenv("REVIO_CUSTOMER_PATH", "/billing/api/v1/customers/{customer_id}")
    api_key = os.getenv("REVIO_API_KEY", "").strip()
    async with httpx.AsyncClient(timeout=30.0) as client:
        exchange = await client.post(
            f"{base_url}/{exchange_path.lstrip('/')}",
            json={"apiKey": api_key}, headers={"Accept": "application/json"},
        )
        exchange.raise_for_status()
        token = ((exchange.json().get("data") or {}).get("token"))
        if not token:
            raise RuntimeError("Rev PSA did not return an access token")
        headers = {"Authorization": f"Bearer {token}", "X-Revio-Host": host, "Accept": "application/json"}
        path = customer_path.format(customer_id=quote(customer_id, safe=""))
        response = await client.get(f"{base_url}/{path.lstrip('/')}", headers=headers)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        customer = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(customer, dict):
            raise RuntimeError("Rev PSA returned an unexpected customer response")
        name = revio_value(customer, "name", "customerName", "companyName", "businessName", "displayName")
        if not name:
            raise RuntimeError("Rev PSA returned the customer without a name")
        resolved_id = revio_value(customer, "customerId", "customer_id", "id") or customer_id
        return {"customer_id": str(resolved_id), "customer_name": str(name), "revio_record": customer}



async def revio_psa_access_token(client: httpx.AsyncClient) -> str:
    base_url = os.getenv("REVIO_BASE_URL", "https://api.psarev.io").rstrip("/")
    exchange_path = os.getenv("REVIO_TOKEN_EXCHANGE_PATH", "/api/v1/auth/api-key/exchange")
    response = await client.post(
        f"{base_url}/{exchange_path.lstrip('/')}",
        json={"apiKey": os.getenv("REVIO_API_KEY", "").strip()},
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    token = ((response.json().get("data") or {}).get("token"))
    if not token:
        raise RuntimeError("Rev PSA did not return an access token")
    return token

async def revio_psa_api_request(method: str, path: str, *, json_body: dict | None = None, params: dict | None = None):
    if not revio_configured():
        raise RuntimeError("Rev PSA is not configured")
    base_url = os.getenv("REVIO_BASE_URL", "https://api.psarev.io").rstrip("/")
    host = os.getenv("REVIO_HOST", "bullfrog.psarev.io").strip()
    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await revio_psa_access_token(client)
        response = await client.request(
            method,
            f"{base_url}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {token}", "X-Revio-Host": host, "Accept": "application/json"},
            json=json_body,
            params=params,
        )
        response.raise_for_status()
        if not response.content:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

async def revio_project_api_request(method: str, path: str, *, json_body: dict | None = None, params: dict | None = None):
    if not revio_configured():
        raise RuntimeError("Rev PSA is not configured")
    base_url = os.getenv("REVIO_PROJECT_BASE_URL", "https://apim.psarev.io").rstrip("/")
    host = os.getenv("REVIO_HOST", "bullfrog.psarev.io").strip()
    async with httpx.AsyncClient(timeout=45.0) as client:
        token = await revio_psa_access_token(client)
        response = await client.request(
            method,
            f"{base_url}/{path.lstrip('/')}",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Revio-Host": host,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=json_body,
            params=params,
        )
        response.raise_for_status()
        if not response.content:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

def revio_datetime(value: date | None) -> str | None:
    if not value:
        return None
    return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

def revio_project_end_date(project: Project) -> date | None:
    if not project.target_date:
        return None
    start = project.start_date or project.created_at.date() or date.today()
    return project.target_date if project.target_date > start else start + timedelta(days=1)

def revio_option_list(payload: dict, *keys: str) -> list[dict]:
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return []
    lowered = {str(key).lower(): value for key, value in data.items()}
    for key in keys:
        value = data.get(key, lowered.get(key.lower()))
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []

def normalize_revio_options(payload: dict) -> dict:
    def normalize(items: list[dict], id_keys: tuple[str, ...], name_keys: tuple[str, ...]) -> list[dict]:
        result = []
        for item in items:
            option_id = revio_value(item, *id_keys)
            name = revio_value(item, *name_keys)
            if option_id not in (None, "") and name not in (None, ""):
                result.append({"id": int(option_id), "name": str(name)})
        return result

    statuses = normalize(
        revio_option_list(payload, "projectStatuses", "statuses", "projectStatusOptions"),
        ("projectStatusId", "statusId", "id"),
        ("projectStatusName", "statusName", "name", "displayName"),
    )
    priorities = normalize(
        revio_option_list(payload, "projectPriorities", "priorities", "projectPriorityOptions"),
        ("projectPriorityId", "priorityId", "id"),
        ("projectPriorityName", "priorityName", "name", "displayName"),
    )
    member_roles = normalize(
        revio_option_list(payload, "memberRoles", "roles", "projectMemberRoles"),
        ("memberRoleId", "roleId", "id"),
        ("memberRoleName", "roleName", "name", "displayName"),
    )
    return {"statuses": statuses, "priorities": priorities, "member_roles": member_roles}

def revio_role_id(roles: list[dict], *terms: str) -> int | None:
    for term in terms:
        for role in roles:
            if term in normalize_customer_name(role.get("name")):
                return int(role["id"])
    return None

async def revio_update_project_details(project: Project) -> dict:
    if not project.revio_project_id:
        raise RuntimeError("This Bullfrog project is not linked to a Rev PSA project")
    if not (project.customer_id or "").isdigit():
        raise RuntimeError("A numeric Rev PSA Customer ID is required")
    project_hours = project.estimated_hours if project.estimated_hours is not None else project.budget_hours
    payload = {
        "projectName": project.project_name,
        "projectDescription": project.scope,
        "projectStatusId": project.revio_project_status_id,
        "projectPriorityId": project.revio_project_priority_id,
        "startDate": revio_datetime(project.start_date),
        "endDate": revio_datetime(revio_project_end_date(project)),
        "budgetHours": project_hours,
        "estimatedHours": project_hours,
        "isBillable": bool(project.is_billable),
        "projectOwnerId": PSA_USERS.get(project.technical_manager),
        "customerId": int(project.customer_id),
        "isAtRisk": project.risk == "Red",
        "notes": project.project_notes,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    response = await revio_project_api_request(
        "PUT",
        f"/project-management/api/v1/projects/{quote(str(project.revio_project_id), safe='')}",
        json_body=payload,
    )
    return {
        "revio_project_id": project.revio_project_id,
        "project_hours": project_hours,
        "updated": True,
        "response": response,
    }

def revio_phase_owner(project: Project, owner_role: str) -> str | None:
    if owner_role == "csm":
        return PSA_USERS.get(project.technical_manager)
    if owner_role == "sales":
        return PSA_USERS.get(project.sales_owner) or PSA_USERS.get(project.technical_manager)
    return PSA_USERS.get(project.engineer) or PSA_USERS.get(project.technical_manager)

def revio_phase_dates(project: Project, index: int, total: int) -> tuple[date, date]:
    start = project.start_date or project.created_at.date() or date.today()
    effective_end = revio_project_end_date(project) or (start + timedelta(days=max(total, 1)))
    days = max(total, (effective_end - start).days)
    phase_start = start + timedelta(days=round(days * index / total))
    calculated_end = start + timedelta(days=round(days * (index + 1) / total))
    phase_end = max(calculated_end, phase_start + timedelta(days=1))
    return phase_start, phase_end

async def revio_sync_project_phases(project: Project, db: Session) -> dict:
    if not project.revio_project_id:
        raise RuntimeError("Create the Rev PSA project before syncing phases")
    planned_phase_status_id = int(
        (os.getenv("REVIO_PSA_PHASE_PLANNED_STATUS_ID")
         or os.getenv("REVIO_PSA_PHASE_STATUS_ID")
         or "").strip() or "1"
    )
    active_phase_status_id = int(
        (os.getenv("REVIO_PSA_PHASE_ACTIVE_STATUS_ID") or "").strip() or "2"
    )
    if not planned_phase_status_id or not active_phase_status_id:
        raise RuntimeError("Rev PSA Active and Planned phase statuses are required")

    definitions = project_phase_definitions(project.project_type, db)
    configured_names = [phase["name"] for phase in definitions]
    grouped: dict[str, list[Milestone]] = {name: [] for name in configured_names}
    for milestone in project.milestones:
        phase_name = milestone.phase_name or milestone_phase_info(project.project_type, milestone.name, db)[0]
        milestone.phase_name = phase_name
        grouped.setdefault(phase_name, []).append(milestone)
    phase_names = [name for name in configured_names if grouped.get(name)]
    phase_names += [name for name in grouped if name not in configured_names and grouped[name]]

    phases_created = 0
    milestones_created = 0
    milestones_moved = 0
    total_phases = max(1, len(phase_names))
    for index, phase_name in enumerate(phase_names):
        milestones = grouped[phase_name]
        phase_definition = next((item for item in definitions if item["name"] == phase_name), None)
        owner_role = (phase_definition or {}).get("owner", "engineer")
        owner_id = revio_phase_owner(project, owner_role)
        phase_start, phase_end = revio_phase_dates(project, index, total_phases)
        existing_phase_id = next((item.revio_phase_id for item in milestones if item.revio_phase_id), None)
        completed = sum(1 for item in milestones if item.status == "Complete")
        progress = round((completed / len(milestones)) * 100, 2) if milestones else 0

        phase_status_id = active_phase_status_id if index == 0 else planned_phase_status_id
        phase_payload = {
            "phaseName": phase_name,
            "phaseSequence": index + 1,
            "phaseStatusId": phase_status_id,
            "startDate": revio_datetime(phase_start),
            "endDate": revio_datetime(phase_end),
            "description": f"{phase_name} phase for {project.project_name}",
            "phaseOwnerId": owner_id,
            "plannedHours": (((project.estimated_hours if project.estimated_hours is not None else project.budget_hours) / total_phases) if (project.estimated_hours is not None or project.budget_hours is not None) else None),
            "isAtRisk": project.risk == "Red",
            "progressPercent": progress,
            "baselineStartDate": revio_datetime(phase_start),
            "baselineEndDate": revio_datetime(phase_end),
        }
        phase_payload = {key: value for key, value in phase_payload.items() if value is not None}

        if existing_phase_id:
            phase_id = existing_phase_id
            await revio_project_api_request(
                "PUT",
                f"/project-management/api/v1/phases/{quote(str(phase_id), safe='')}",
                json_body=phase_payload,
            )
        else:
            phase_response = await revio_project_api_request(
                "POST",
                f"/project-management/api/v1/projects/{quote(str(project.revio_project_id), safe='')}/phases",
                json_body=phase_payload,
            )
            phase_data = phase_response.get("data", phase_response)
            phase_id = revio_value(phase_data, "phaseId", "phase_id", "id") if isinstance(phase_data, dict) else None
            if phase_id in (None, ""):
                phase_id = revio_value(phase_response, "phaseId", "phase_id", "id")
            if phase_id in (None, ""):
                raise RuntimeError(f"Rev PSA created phase {phase_name} but did not return a Phase ID")
            phase_id = str(phase_id)
            phases_created += 1

        for milestone in milestones:
            milestone.revio_phase_id = str(phase_id)
            target = milestone.due_date or phase_end or project.target_date or phase_start
            milestone_payload = {
                "milestoneName": milestone.name,
                "description": f"{phase_name} milestone for {project.project_name}",
                "targetDate": revio_datetime(target),
                "ownerId": owner_id,
                "phaseId": int(phase_id),
            }
            milestone_payload = {key: value for key, value in milestone_payload.items() if value is not None}
            if milestone.revio_milestone_id:
                await revio_project_api_request(
                    "PUT",
                    f"/project-management/api/v1/milestones/{quote(str(milestone.revio_milestone_id), safe='')}",
                    json_body=milestone_payload,
                )
                milestones_moved += 1
            else:
                milestone_response = await revio_project_api_request(
                    "POST",
                    f"/project-management/api/v1/projects/{quote(str(project.revio_project_id), safe='')}/milestones",
                    json_body=milestone_payload,
                )
                milestone_data = milestone_response.get("data", milestone_response)
                milestone_id = revio_value(milestone_data, "milestoneId", "milestone_id", "id") if isinstance(milestone_data, dict) else None
                if milestone_id in (None, ""):
                    milestone_id = revio_value(milestone_response, "milestoneId", "milestone_id", "id")
                if milestone_id in (None, ""):
                    raise RuntimeError(f"Rev PSA created milestone {milestone.name} but did not return a Milestone ID")
                milestone.revio_milestone_id = str(milestone_id)
                milestones_created += 1

    project.revio_sync_status = "Synced with Phases"
    project.revio_sync_error = None
    project.revio_synced_at = datetime.utcnow()
    db.flush()
    return {
        "revio_project_id": project.revio_project_id,
        "sync_status": project.revio_sync_status,
        "phases_created": phases_created,
        "milestones_created": milestones_created,
        "milestones_moved": milestones_moved,
    }

async def revio_create_project_with_milestones(project: Project, db: Session) -> dict:
    if not (project.customer_id or "").isdigit():
        raise RuntimeError("A numeric Rev PSA Customer ID is required")
    if not project.revio_project_status_id:
        raise RuntimeError("Select a Rev PSA Project Status before creating the project")
    start_date = project.start_date or project.created_at.date() or date.today()
    if project.target_date and project.target_date < start_date:
        raise RuntimeError("Target go-live cannot be earlier than the project start date")
    if project.budget_hours is not None and project.budget_hours < 0:
        raise RuntimeError("Budget hours cannot be negative")
    if project.estimated_hours is not None and project.estimated_hours < 0:
        raise RuntimeError("Project hours cannot be negative")
    if project.technical_manager not in PSA_USERS:
        raise RuntimeError("The selected Customer Success Manager is not mapped to a Rev PSA user")

    options_payload = await revio_project_api_request(
        "GET", "/project-management/api/v1/projects/options"
    )
    options = normalize_revio_options(options_payload)
    roles = options["member_roles"]
    warnings: list[str] = []
    team_members = []
    seen_users = set()
    member_specs = [
        (project.technical_manager, True, ("projectmanager", "manager", "lead", "owner")),
        (project.engineer, False, ("engineer", "technician", "technical")),
        (project.sales_owner, False, ("sales",)),
    ]
    for name, is_lead, role_terms in member_specs:
        if not name or name not in PSA_USERS or PSA_USERS[name] in seen_users:
            continue
        role_id = revio_role_id(roles, *role_terms)
        if not role_id:
            warnings.append(f"Could not match a Rev PSA member role for {name}; the project was created without that team assignment.")
            continue
        seen_users.add(PSA_USERS[name])
        team_members.append({
            "globalUserId": PSA_USERS[name],
            "memberRoleId": role_id,
            "isLead": is_lead,
        })

    payload = {
        "projectName": project.project_name,
        "projectStatusId": int(project.revio_project_status_id),
        "startDate": revio_datetime(start_date),
        "isBillable": bool(project.is_billable),
        "projectOwnerId": PSA_USERS.get(project.technical_manager),
        "projectDescription": project.scope,
        "customerId": int(project.customer_id),
        "teamMembers": team_members or None,
        "notes": project.project_notes,
    }
    project_hours = project.estimated_hours if project.estimated_hours is not None else project.budget_hours
    optional_values = {
        "endDate": revio_datetime(revio_project_end_date(project)),
        "budgetHours": project_hours,
        "estimatedHours": project_hours,
        "projectPriorityId": project.revio_project_priority_id,
    }
    payload.update({key: value for key, value in optional_values.items() if value is not None})
    payload = {key: value for key, value in payload.items() if value is not None}

    response = await revio_project_api_request(
        "POST", "/project-management/api/v1/projects", json_body=payload
    )
    data = response.get("data", response)
    project_id = revio_value(data, "projectId", "project_id", "id") if isinstance(data, dict) else None
    if project_id in (None, ""):
        project_id = revio_value(response, "projectId", "project_id", "id")
    if project_id in (None, ""):
        raise RuntimeError("Rev PSA created the project but did not return a Project ID")

    project.revio_project_id = str(project_id)
    project.revio_sync_status = "Creating Phases"
    project.revio_sync_error = None
    project.revio_synced_at = datetime.utcnow()
    db.flush()
    result = await revio_sync_project_phases(project, db)
    result["warnings"] = warnings
    return result

def revio_http_error_detail(exc: httpx.HTTPStatusError, fallback: str) -> str:
    response = exc.response
    details: list[str] = []

    def collect(value, prefix: str = ""):
        if value in (None, "", [], {}):
            return
        if isinstance(value, dict):
            preferred = ("message", "detail", "title", "error", "description")
            for key in preferred:
                if key in value:
                    collect(value[key], prefix)
            errors = value.get("errors")
            if errors is not None:
                collect(errors, prefix)
            for key, item in value.items():
                if key in preferred or key == "errors" or item in (None, "", [], {}):
                    continue
                if isinstance(item, (dict, list)):
                    collect(item, f"{prefix}{key}: ")
        elif isinstance(value, list):
            for item in value:
                collect(item, prefix)
        else:
            text_value = str(value).strip()
            if text_value:
                details.append(f"{prefix}{text_value}")

    try:
        collect(response.json())
    except ValueError:
        if response.text and response.text.strip():
            details.append(response.text.strip())

    unique = []
    for item in details:
        if item not in unique:
            unique.append(item)
    if unique:
        return f"{fallback}: {' | '.join(unique)}"[:4000]
    return fallback

def psa_ticket_ids() -> tuple[int, int, int, int]:
    return (
        int(os.getenv("REVIO_PSA_TICKET_TYPE_ID", str(PSA_TICKET_TYPE_ID))),
        int(os.getenv("REVIO_PSA_NEW_STATUS_ID", str(PSA_NEW_STATUS_ID))),
        int(os.getenv("REVIO_PSA_COMPLETE_STATUS_ID", str(PSA_COMPLETE_STATUS_ID))),
        int(os.getenv("REVIO_PSA_PRIORITY_ID", str(PSA_PRIORITY_ID))),
    )

PSA_TICKET_RULES = {
    "schedule_internal_handoff": {
        "description": "Schedule Internal Handoff", "assignee": "sales_owner",
        "associate": "csm", "completed_milestone": "Internal Handoff", "next": "kickoff_call",
        "work": "Coordinate and schedule the internal project handoff with Sales and Customer Success.",
    },
    "kickoff_call": {
        "description": "Schedule and Hold Kickoff Call", "assignee": "csm",
        "completed_milestone": "Kickoff Call", "next": "call_flow",
        "work": "Schedule and hold the customer kickoff meeting. Complete this ticket after the meeting is held.",
    },
    "call_flow": {
        "description": "Build Customer Call Flow", "assignee": "engineer",
        "completed_milestone": "Call Flow",
        "work": "Document and configure the customer call flow based on the completed kickoff meeting.",
    },
    "submit_port": {
        "description": "Submit Number Port", "assignee": "engineer",
        "completed_milestone": "Port Submitted",
        "work": "Submit the number port using the completed LOA documentation.",
    },
    "notify_port_date": {
        "description": "Notify Customer of Port Date", "assignee": "csm",
        "work": "Notify the customer of the confirmed FOC and port date.",
    },
    "schedule_go_live_follow_up": {
        "description": "Schedule Go-Live Follow-Up", "assignee": "csm",
        "completed_milestone": "Go Live Follow Up",
        "work": "Schedule the customer go-live follow-up after the number port is complete.",
    },
    "hardware_ordered": {
        "description": "Order Customer Hardware", "assignee": "sales_owner",
        "completed_milestone": "Hardware Ordered", "next": "provide_tracking",
        "work": "Order the hardware listed in the approved Rev.io billing source. Complete this ticket when ordered.",
    },
    "provide_tracking": {
        "description": "Provide Hardware Tracking to Customer", "assignee": "csm",
        "work": "Send the hardware shipment tracking information to the customer.",
    },
    "register_devices": {
        "description": "Register Customer Devices", "assignee": "engineer",
        "completed_milestone": "Devices Registered",
        "work": "Register the delivered customer devices in Rev PSA and the applicable provisioning platform.",
    },
    "add_users": {
        "description": "Add Customer Users", "assignee": "engineer",
        "completed_milestone": "Users Added",
        "work": "Add and configure the users from the completed customer spreadsheet.",
    },
}

MILESTONE_TICKET_RULES = {
    "signedproposal": "schedule_internal_handoff",
    "quotesigned": "schedule_internal_handoff",
    "kickoffcall": "call_flow",
    "loadocument": "submit_port",
    "focreceived": "notify_port_date",
    "foc": "notify_port_date",
    "portcomplete": "schedule_go_live_follow_up",
    "hardwareordered": "provide_tracking",
    "hardwaredelivered": "register_devices",
    "hardwaredelivery": "register_devices",
    "userspreadsheet": "add_users",
}

def psa_assignee(project: Project, role: str) -> str:
    if role == "sales_owner":
        name = project.sales_owner
    elif role == "csm":
        name = project.technical_manager
    else:
        name = project.engineer
    if not name:
        raise RuntimeError(f"Project has no {role.replace('_', ' ')} assigned")
    if name not in PSA_USERS:
        raise RuntimeError(f"{name} does not have a configured Rev PSA Global User ID")
    return name

def record_psa_activity(db: Session, project_id: int, action: str, description: str):
    db.add(ProjectActivity(
        project_id=project_id, actor_name="Bullfrog Automation", actor_email=None,
        action=action, field_name="revio_psa_ticket_workflow", description=description,
    ))

def queue_psa_ticket(db: Session, project: Project, workflow_key: str) -> PsaTicketWorkflow:
    existing = db.scalar(select(PsaTicketWorkflow).where(
        PsaTicketWorkflow.project_id == project.id,
        PsaTicketWorkflow.workflow_key == workflow_key,
    ))
    if existing:
        return existing
    rule = PSA_TICKET_RULES[workflow_key]
    assignee = psa_assignee(project, rule["assignee"])
    associated = psa_assignee(project, rule["associate"]) if rule.get("associate") else None
    workflow = PsaTicketWorkflow(
        project_id=project.id,
        workflow_key=workflow_key,
        ticket_description=rule["description"],
        assignee_name=assignee,
        associated_name=associated,
        status="Pending",
    )
    db.add(workflow)
    db.flush()
    record_psa_activity(
        db, project.id, "psa_ticket_queued",
        f"Queued Rev PSA ticket: {rule['description']} — assigned to {assignee}",
    )
    return workflow

async def revio_psa_create_ticket(project: Project, workflow: PsaTicketWorkflow) -> str:
    ticket_type_id, new_status_id, _, priority_id = psa_ticket_ids()
    rule = PSA_TICKET_RULES[workflow.workflow_key]
    if not (project.customer_id or "").isdigit():
        raise RuntimeError("Project must have a numeric Rev PSA Customer ID before creating tickets")
    associated_names = [workflow.assignee_name]
    if workflow.associated_name and workflow.associated_name not in associated_names:
        associated_names.append(workflow.associated_name)
    payload = {
        "customerId": int(project.customer_id),
        "ticketDescription": f"{project.customer} — {workflow.ticket_description}",
        "ticketTypeId": ticket_type_id,
        "ticketStatusId": new_status_id,
        "ticketPriorityId": priority_id,
        "techAssigned": workflow.assignee_name,
        "techsAssociated": [
            {
                "globalUserId": PSA_USERS[name],
                "techName": "Matthew" if name == "Matt" else name,
                "workComplete": False,
                "role": "Assigned" if name == workflow.assignee_name else "Associated",
            }
            for name in associated_names
        ],
        "workRequested": (
            f"{rule['work']}\n\n"
            f"Bullfrog Project: {project.project_name}\n"
            f"Customer: {project.customer}\n"
            f"Project Type: {project.project_type}"
        ),
    }
    path = os.getenv("REVIO_PSA_TICKET_CREATE_PATH", "/psac/api/v1/ticket")
    response = await revio_psa_api_request("POST", path, json_body=payload)
    data = response.get("data", response)
    if isinstance(data, dict):
        ticket_id = revio_value(data, "ticketId", "ticket_id", "id")
    else:
        ticket_id = None
    if ticket_id in (None, ""):
        ticket_id = revio_value(response, "ticketId", "ticket_id", "id")
    if ticket_id in (None, ""):
        raise RuntimeError("Rev PSA created the ticket but did not return a ticket ID")
    return str(ticket_id)

async def revio_psa_ticket_status(ticket_id: str) -> int:
    path_template = os.getenv("REVIO_PSA_TICKET_DETAIL_PATH", "/psac/api/v1/ticket/{ticket_id}")
    try:
        response = await revio_psa_api_request(
            "GET", path_template.format(ticket_id=quote(ticket_id, safe=""))
        )
        data = response.get("data", response)
        if isinstance(data, list):
            data = data[0] if data else {}
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in (404, 405):
            raise
        # Some PSA tenants expose ticket creation but not the matching detail
        # route. Fall back to the known ticket-list endpoint and find the ID.
        data = {}
        list_path = os.getenv("REVIO_PSA_TICKET_LIST_PATH", "/psac/api/v1/ticket-list")
        for page in range(1, 11):
            payload = await revio_psa_api_request(
                "GET", list_path, params={"page": page, "perPage": 100}
            )
            records = revio_records(payload)
            match = next((
                item for item in records
                if str(revio_value(item, "ticketId", "ticket_id", "id")) == str(ticket_id)
            ), None)
            if match:
                data = match
                break
            if len(records) < 100:
                break

    if not isinstance(data, dict) or not data:
        raise RuntimeError(f"Rev PSA ticket {ticket_id} was not found")
    status_id = revio_value(data, "ticketStatusId", "ticket_status_id", "statusId", "status_id")
    nested = data.get("status") if isinstance(data.get("status"), dict) else {}
    if status_id in (None, ""):
        status_id = revio_value(nested, "ticketStatusId", "ticket_status_id", "statusId", "status_id", "id")
    if status_id not in (None, ""):
        try:
            return int(status_id)
        except (TypeError, ValueError):
            pass

    status_name = revio_value(data, "ticketStatus", "ticket_status", "status", "statusName")
    if isinstance(status_name, dict):
        status_name = revio_value(status_name, "name", "statusName")
    if normalize_customer_name(str(status_name or "")) in ("complete", "completed"):
        return psa_ticket_ids()[2]
    raise RuntimeError(f"Rev PSA ticket {ticket_id} did not include a recognizable status")


def normalize_customer_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())

def revio_billing_configured() -> bool:
    if (os.getenv("REVIO_BILLING_AUTHORIZATION") or "").strip():
        return True
    return all((os.getenv(key) or "").strip() for key in (
        "REVIO_BILLING_USERNAME", "REVIO_BILLING_CLIENT_CODE", "REVIO_BILLING_PASSWORD",
    ))

def revio_billing_customer_name(customer: dict) -> str:
    direct = revio_value(customer, "name", "customer_name", "customerName", "company_name", "companyName")
    if direct:
        return str(direct).strip()
    for address_key in ("billing_address", "service_address", "listing_address"):
        address = customer.get(address_key) or {}
        company = revio_value(address, "company_name", "companyName")
        if company:
            return str(company).strip()
        first = str(revio_value(address, "first_name", "firstName") or "").strip()
        last = str(revio_value(address, "last_name", "lastName") or "").strip()
        if first or last:
            return f"{first} {last}".strip()
    return ""

def revio_billing_http_settings() -> tuple[str, dict, httpx.BasicAuth | None]:
    base_url = os.getenv("REVIO_BILLING_BASE_URL", "https://restapi.rev.io").rstrip("/")
    authorization = (os.getenv("REVIO_BILLING_AUTHORIZATION") or "").strip()
    headers = {"Accept": "application/json"}
    auth = None
    if authorization:
        if not authorization.lower().startswith("basic "):
            authorization = f"Basic {authorization}"
        headers["Authorization"] = authorization
    else:
        username = os.environ["REVIO_BILLING_USERNAME"].strip()
        client_code = os.environ["REVIO_BILLING_CLIENT_CODE"].strip()
        password = os.environ["REVIO_BILLING_PASSWORD"]
        auth = httpx.BasicAuth(f"{username}@{client_code}", password)
    return base_url, headers, auth

async def revio_billing_get(path: str, params: dict | None = None) -> dict:
    if not revio_billing_configured():
        raise RuntimeError("Rev.io Billing is not configured")
    base_url, headers, auth = revio_billing_http_settings()
    async with httpx.AsyncClient(timeout=30.0, auth=auth) as client:
        response = await client.get(
            f"{base_url}/{path.lstrip('/')}", params=params or {}, headers=headers,
        )
        response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Rev.io Billing returned an unexpected response")
    return payload

async def revio_billing_request_statuses() -> dict[str, dict]:
    # Include inactive statuses too. Older signed quotes can retain a status
    # that an administrator later deactivated in Rev.io.
    payload = await revio_billing_get(
        "/v1/RequestStatuses",
        {"search.page_size": 100},
    )
    statuses = {}
    for item in revio_records(payload):
        status_id = revio_value(item, "request_status_id", "requestStatusId", "status_id", "statusId", "id")
        if status_id in (None, ""):
            continue
        statuses[str(status_id)] = {
            "name": str(revio_value(item, "name", "request_status", "requestStatus") or "Unknown status"),
            "type": str(revio_value(item, "status_type", "statusType", "type") or "").upper(),
        }
    return statuses

def revio_billing_quote_status(item: dict, statuses: dict[str, dict]) -> tuple[str, dict]:
    nested = item.get("status") if isinstance(item.get("status"), dict) else {}
    status_id = revio_value(
        item, "request_status_id", "requestStatusId", "status_id", "statusId"
    )
    if status_id in (None, ""):
        status_id = revio_value(nested, "request_status_id", "requestStatusId", "status_id", "statusId", "id")
    status = statuses.get(str(status_id), {}).copy()
    direct_name = revio_value(item, "request_status", "requestStatus", "status_name", "statusName")
    if not direct_name:
        direct_name = revio_value(nested, "name", "request_status", "requestStatus")
    direct_type = revio_value(item, "status_type", "statusType")
    if not direct_type:
        direct_type = revio_value(nested, "status_type", "statusType", "type")
    if direct_name:
        status["name"] = str(direct_name)
    if direct_type:
        status["type"] = str(direct_type).upper()
    status.setdefault("name", "Unknown status")
    status.setdefault("type", "")
    return str(status_id or ""), status

def revio_billing_status_is_signed(status: dict) -> bool:
    if status.get("type") == "COMPLETE":
        return True
    name = normalize_customer_name(status.get("name"))
    return any(word in name for word in ("signed", "complete", "accepted", "approved", "converted", "won"))

async def revio_billing_complete_statuses() -> dict[str, str]:
    statuses = await revio_billing_request_statuses()
    return {
        status_id: status["name"]
        for status_id, status in statuses.items()
        if revio_billing_status_is_signed(status)
    }

async def revio_billing_find_customer(customer_name: str) -> dict:
    payload = await revio_billing_get(
        "/v1/Customers",
        {"search.name": customer_name, "search.page_size": 25},
    )
    records = payload.get("records", [])
    exact = [
        item for item in records
        if isinstance(item, dict)
        and normalize_customer_name(revio_billing_customer_name(item)) == normalize_customer_name(customer_name)
    ]
    if not exact:
        raise RuntimeError(f'No exact Rev.io Billing customer match was found for "{customer_name}"')
    if len(exact) > 1:
        raise RuntimeError(f'Multiple Rev.io Billing customers matched "{customer_name}"')
    customer = exact[0]
    customer_id = revio_value(customer, "customer_id", "customerId", "id")
    finance = customer.get("finance") or {}
    balance_value = revio_value(finance, "balance")
    if customer_id in (None, ""):
        raise RuntimeError("Rev.io Billing returned the customer without an ID")
    if balance_value in (None, ""):
        raise RuntimeError("Rev.io Billing returned the customer without an account balance")
    try:
        balance = Decimal(str(balance_value))
    except InvalidOperation as exc:
        raise RuntimeError("Rev.io Billing returned an invalid account balance") from exc
    return {"customer_id": str(customer_id), "customer_name": revio_billing_customer_name(customer), "balance": balance}

async def revio_billing_signed_quotes(customer_id: str) -> list[dict]:
    statuses = await revio_billing_request_statuses()
    payload = await revio_billing_get(
        "/v1/Requests",
        {"search.customer_id": customer_id, "search.page_size": 100, "search.sort": "-status_date"},
    )
    quotes = []
    for item in revio_records(payload):
        request_id = revio_value(item, "request_id", "requestId", "id")
        if request_id in (None, ""):
            continue
        _, request_status = revio_billing_quote_status(item, statuses)
        if request_status.get("type") == "CANCELED":
            continue
        quotes.append({
            "source_id": f"request:{request_id}",
            "source_type": "Quote",
            "quote_id": str(request_id),
            "description": str(revio_value(item, "description", "name", "title") or "No quote description"),
            "status": request_status["name"],
            "status_type": request_status["type"],
            "is_signed_status": revio_billing_status_is_signed(request_status),
            "signed_at": revio_value(item, "status_date", "statusDate", "modified_date", "modifiedDate", "created_date", "createdDate"),
        })
    quotes.sort(
        key=lambda item: (item["is_signed_status"], item.get("signed_at") or ""),
        reverse=True,
    )
    return quotes

async def revio_billing_product_names(product_ids: set[str]) -> dict[str, str]:
    if not product_ids:
        return {}
    payload = await revio_billing_get(
        "/v1/Products",
        {"search.product_id": sorted(product_ids), "search.page_size": 100},
    )
    names = {}
    for item in revio_records(payload):
        product_id = revio_value(item, "product_id", "productId", "id")
        name = revio_value(item, "description", "name", "product_name", "productName")
        if product_id not in (None, "") and name:
            names[str(product_id)] = str(name)
    return names

async def revio_billing_charge_lines(charges: list[dict]) -> list[dict]:
    product_ids = {
        str(product_id)
        for item in charges
        if (product_id := revio_value(item, "product_id", "productId")) not in (None, "")
    }
    try:
        product_names = await revio_billing_product_names(product_ids)
    except httpx.HTTPStatusError:
        # Product lookup is only enrichment; charge descriptions may already
        # contain everything needed for the hardware order email.
        product_names = {}
    lines = []
    for item in charges:
        product = item.get("product") if isinstance(item.get("product"), dict) else {}
        product_id = revio_value(item, "product_id", "productId")
        description = (
            revio_value(item, "description", "name", "charge_description", "chargeDescription")
            or revio_value(product, "description", "name", "product_name", "productName")
            or product_names.get(str(product_id))
            or (f"Product {product_id}" if product_id not in (None, "") else "Rev.io charge")
        )
        lines.append({
            "description": str(description).strip(),
            "quantity": revio_value(item, "quantity", "qty") or 1,
            "rate": revio_value(item, "rate", "unit_rate", "unitRate", "price", "amount"),
        })
    return lines

async def revio_billing_bill_sources(customer_id: str) -> list[dict]:
    bills_payload, charges_payload = await asyncio.gather(
        revio_billing_get(
            "/v1/Bills",
            {"search.customer_id": customer_id, "search.page_size": 100, "search.sort": "-created_date"},
        ),
        revio_billing_get(
            "/v1/Charges",
            {"search.customer_id": customer_id, "search.page_size": 100, "search.sort": "-created_date"},
        ),
    )
    bills = revio_records(bills_payload)
    charges = revio_records(charges_payload)
    charges_by_bill: dict[str, list[dict]] = {}
    unbilled_charges = []
    for charge in charges:
        bill_id = revio_value(charge, "bill_id", "billId")
        if bill_id in (None, "", 0, "0"):
            unbilled_charges.append(charge)
        else:
            charges_by_bill.setdefault(str(bill_id), []).append(charge)

    sources = []
    for bill in bills:
        bill_id = revio_value(bill, "bill_id", "billId", "id")
        if bill_id in (None, ""):
            continue
        bill_charges = charges_by_bill.get(str(bill_id), [])
        bill_number = revio_value(bill, "bill_number", "billNumber", "invoice_number", "invoiceNumber")
        created = revio_value(bill, "cycle_date", "cycleDate", "created_date", "createdDate", "due_date", "dueDate")
        amount = revio_value(bill, "amount_due", "amountDue", "balance", "total", "amount")
        label = f"Bill #{bill_number or bill_id}"
        detail = f"{len(bill_charges)} charge{'s' if len(bill_charges) != 1 else ''}"
        if amount not in (None, ""):
            detail += f" · Total {amount}"
        sources.append({
            "source_id": f"bill:{bill_id}",
            "source_type": "Bill",
            "quote_id": str(bill_id),
            "description": f"{label} — {detail}",
            "status": "Billed",
            "status_type": "BILL",
            "is_signed_status": True,
            "signed_at": created,
        })

    if unbilled_charges:
        newest = max(
            (str(revio_value(item, "created_date", "createdDate") or "") for item in unbilled_charges),
            default="",
        )
        sources.append({
            "source_id": "charges:unbilled",
            "source_type": "Charges",
            "quote_id": "unbilled",
            "description": f"Current unbilled charges — {len(unbilled_charges)} item{'s' if len(unbilled_charges) != 1 else ''}",
            "status": "Unbilled",
            "status_type": "CHARGES",
            "is_signed_status": True,
            "signed_at": newest or None,
        })
    return sources

async def revio_billing_sources(customer_id: str) -> list[dict]:
    quotes, billing_sources = await asyncio.gather(
        revio_billing_signed_quotes(customer_id),
        revio_billing_bill_sources(customer_id),
    )
    return quotes + billing_sources

async def revio_billing_selected_source(customer_id: str, selected_id: str | None) -> dict:
    clean_id = (selected_id or "").strip()
    if not clean_id:
        raise RuntimeError("Select a Rev.io Quote, Bill, or Charges entry before completing Quote Signed")
    legacy_numeric = ":" not in clean_id and clean_id.isdigit()
    if ":" in clean_id:
        source_type, source_value = clean_id.split(":", 1)
    elif legacy_numeric:
        source_type, source_value = "request", clean_id
    else:
        raise RuntimeError("The selected Rev.io billing source is invalid")

    if source_type == "request":
        if not source_value.isdigit():
            raise RuntimeError("The selected Rev.io Quote ID is invalid")
        statuses = await revio_billing_request_statuses()
        payload = await revio_billing_get(
            "/v1/Requests",
            {"search.request_id": source_value, "search.page_size": 10},
        )
        matches = [
            item for item in revio_records(payload)
            if str(revio_value(item, "request_id", "requestId", "id")) == source_value
            and str(revio_value(item, "customer_id", "customerId")) == str(customer_id)
        ]
        if len(matches) != 1:
            if legacy_numeric:
                # Projects saved before typed source IDs were introduced only
                # contain a number. Detect whether that number is actually a
                # bill or charge before asking the user to reselect it.
                bill_payload, charge_payload = await asyncio.gather(
                    revio_billing_get("/v1/Bills", {"search.bill_id": source_value, "search.page_size": 10}),
                    revio_billing_get("/v1/Charges", {"search.charge_id": source_value, "search.page_size": 10}),
                )
                bill_match = any(
                    str(revio_value(item, "bill_id", "billId", "id")) == source_value
                    and str(revio_value(item, "customer_id", "customerId")) == str(customer_id)
                    for item in revio_records(bill_payload)
                )
                if bill_match:
                    return await revio_billing_selected_source(customer_id, f"bill:{source_value}")
                charge_match = any(
                    str(revio_value(item, "charge_id", "chargeId", "id")) == source_value
                    and str(revio_value(item, "customer_id", "customerId")) == str(customer_id)
                    for item in revio_records(charge_payload)
                )
                if charge_match:
                    return await revio_billing_selected_source(customer_id, f"charge:{source_value}")
            raise RuntimeError(
                f"Rev.io source {source_value} was not found for the matched Billing customer. "
                "Edit the project and select a Quote, Bill, or Charges entry again."
            )
        request_item = matches[0]
        _, request_status = revio_billing_quote_status(request_item, statuses)
        if request_status.get("type") == "CANCELED":
            raise RuntimeError(f"Rev.io Quote {source_value} is canceled")
        products_payload = await revio_billing_get(
            "/v1/RequestProducts",
            {"search.request_id": source_value, "search.page_size": 100},
        )
        products = [
            {
                "description": str(revio_value(item, "description", "name") or f"Product {revio_value(item, 'product_id', 'productId') or ''}").strip(),
                "quantity": revio_value(item, "quantity", "qty"),
                "rate": revio_value(item, "rate", "price", "amount"),
            }
            for item in revio_records(products_payload)
        ]
        return {
            "source_id": f"request:{source_value}",
            "source_type": "Quote",
            "source_number": source_value,
            "quote_id": source_value,
            "description": str(revio_value(request_item, "description", "name", "title") or "No quote description"),
            "status": request_status["name"],
            "signed_at": revio_value(request_item, "status_date", "statusDate", "created_date", "createdDate"),
            "products": products,
        }

    if source_type == "bill":
        if not source_value.isdigit():
            raise RuntimeError("The selected Rev.io Bill ID is invalid")
        bill_payload, charges_payload = await asyncio.gather(
            revio_billing_get("/v1/Bills", {"search.bill_id": source_value, "search.page_size": 10}),
            revio_billing_get("/v1/Charges", {"search.bill_id": source_value, "search.page_size": 100}),
        )
        matches = [
            item for item in revio_records(bill_payload)
            if str(revio_value(item, "bill_id", "billId", "id")) == source_value
            and str(revio_value(item, "customer_id", "customerId")) == str(customer_id)
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Rev.io Bill {source_value} was not found for the matched Billing customer")
        bill = matches[0]
        charges = [
            item for item in revio_records(charges_payload)
            if str(revio_value(item, "customer_id", "customerId") or customer_id) == str(customer_id)
        ]
        bill_number = revio_value(bill, "bill_number", "billNumber", "invoice_number", "invoiceNumber") or source_value
        return {
            "source_id": f"bill:{source_value}",
            "source_type": "Bill",
            "source_number": str(bill_number),
            "quote_id": source_value,
            "description": f"Rev.io Bill #{bill_number}",
            "status": "Billed",
            "signed_at": revio_value(bill, "cycle_date", "cycleDate", "created_date", "createdDate", "due_date", "dueDate"),
            "products": await revio_billing_charge_lines(charges),
        }

    if source_type == "charge":
        if not source_value.isdigit():
            raise RuntimeError("The selected Rev.io Charge ID is invalid")
        payload = await revio_billing_get(
            "/v1/Charges",
            {"search.charge_id": source_value, "search.page_size": 10},
        )
        matches = [
            item for item in revio_records(payload)
            if str(revio_value(item, "charge_id", "chargeId", "id")) == source_value
            and str(revio_value(item, "customer_id", "customerId")) == str(customer_id)
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Rev.io Charge {source_value} was not found for the matched Billing customer")
        charge = matches[0]
        return {
            "source_id": f"charge:{source_value}",
            "source_type": "Charge",
            "source_number": source_value,
            "quote_id": source_value,
            "description": str(
                revio_value(charge, "description", "name", "charge_description", "chargeDescription")
                or f"Rev.io Charge #{source_value}"
            ),
            "status": "Charged",
            "signed_at": revio_value(charge, "created_date", "createdDate"),
            "products": await revio_billing_charge_lines([charge]),
        }

    if source_type == "charges" and source_value == "unbilled":
        payload = await revio_billing_get(
            "/v1/Charges",
            {"search.customer_id": customer_id, "search.page_size": 100, "search.sort": "-created_date"},
        )
        charges = [
            item for item in revio_records(payload)
            if revio_value(item, "bill_id", "billId") in (None, "", 0, "0")
        ]
        if not charges:
            raise RuntimeError("No current unbilled Rev.io charges were found for this customer")
        return {
            "source_id": "charges:unbilled",
            "source_type": "Charges",
            "source_number": "Unbilled",
            "quote_id": "unbilled",
            "description": "Current unbilled Rev.io charges",
            "status": "Unbilled",
            "signed_at": max(
                (str(revio_value(item, "created_date", "createdDate") or "") for item in charges),
                default="",
            ) or None,
            "products": await revio_billing_charge_lines(charges),
        }

    raise RuntimeError("The selected Rev.io billing source is not supported")

def record_automation_activity(db: Session, project_id: int, action: str, description: str, old_value=None, new_value=None):
    db.add(ProjectActivity(
        project_id=project_id, actor_name="Bullfrog Automation", actor_email=None,
        action=action, field_name="hardware_order_workflow",
        old_value=activity_value(old_value) if old_value is not None else None,
        new_value=activity_value(new_value) if new_value is not None else None,
        description=description,
    ))


def ensure_project_workflow_milestones():
    db = SessionLocal()
    try:
        projects = list(db.scalars(select(Project).where(Project.stage != "Complete")).all())
        for project in projects:
            existing_items = list(db.scalars(
                select(Milestone).where(Milestone.project_id == project.id).order_by(Milestone.id)
            ).all())
            for item in existing_items:
                normalized_name = normalize_customer_name(item.name)
                if normalized_name == "quotesigned":
                    item.name = "Signed Proposal"
                elif normalized_name == "hardwarepaid":
                    item.name = "Hardware Payment Check"
            payment_checks = [
                item for item in existing_items
                if normalize_customer_name(item.name) == "hardwarepaymentcheck"
            ]
            if len(payment_checks) > 1:
                keeper = payment_checks[0]
                completed = next((item for item in payment_checks if item.status == "Complete"), None)
                dated = next((item for item in payment_checks if item.due_date), None)
                if completed:
                    keeper.status = "Complete"
                    keeper.completed_date = completed.completed_date or date.today()
                if not keeper.due_date and dated:
                    keeper.due_date = dated.due_date
                for duplicate in payment_checks[1:]:
                    db.delete(duplicate)
                existing_items = [
                    item for item in existing_items
                    if item not in payment_checks[1:]
                ]

            existing_names = {normalize_customer_name(item.name) for item in existing_items}
            for name in WORKFLOW_MILESTONES.get(project.project_type, []):
                if normalize_customer_name(name) not in existing_names:
                    db.add(Milestone(project_id=project.id, name=name))
                    existing_names.add(normalize_customer_name(name))

            # Balance checks that were previously started by Signed Proposal
            # must wait for the new, explicit Hardware Payment Check milestone.
            hardware_paid_complete = any(
                normalize_customer_name(item.name) == "hardwarepaymentcheck" and item.status == "Complete"
                for item in existing_items
            )
            hardware_workflow = db.scalar(select(HardwareOrderWorkflow).where(
                HardwareOrderWorkflow.project_id == project.id
            ))
            if hardware_workflow and hardware_workflow.status != "Sent" and not hardware_paid_complete:
                hardware_workflow.status = "Awaiting Hardware Payment Check"
                hardware_workflow.last_error = None
        db.commit()
    finally:
        db.close()

def complete_automation_milestone(db: Session, project: Project, milestone_name: str):
    milestone = db.scalar(select(Milestone).where(
        Milestone.project_id == project.id,
        Milestone.name.ilike(milestone_name),
    ))
    if milestone and milestone.status != "Complete":
        milestone.status = "Complete"
        milestone.completed_date = date.today()
        record_psa_activity(
            db, project.id, "milestone_updated",
            f"Completed milestone {milestone.name} from Rev PSA ticket completion",
        )

async def process_psa_ticket_workflow(workflow_id: int):
    db = SessionLocal()
    try:
        workflow = db.get(PsaTicketWorkflow, workflow_id)
        if not workflow or workflow.status in ("Completed", "Needs Review"):
            return
        project = db.get(Project, workflow.project_id)
        if not project:
            return

        if not workflow.ticket_id:
            workflow.status = "Creating"
            workflow.last_error = None
            db.commit()
            try:
                ticket_id = await revio_psa_create_ticket(project, workflow)
            except httpx.TimeoutException:
                workflow.status = "Needs Review"
                workflow.last_error = "Ticket creation timed out; automatic retry paused to prevent a duplicate ticket."
                record_psa_activity(
                    db, project.id, "psa_ticket_review",
                    f"Rev PSA ticket creation timed out for {workflow.ticket_description}; verify PSA before retrying.",
                )
                db.commit()
                return
            workflow.ticket_id = ticket_id
            workflow.status = "Open"
            workflow.last_checked_at = datetime.utcnow()
            workflow.last_error = None
            record_psa_activity(
                db, project.id, "psa_ticket_created",
                f"Created Rev PSA ticket {ticket_id}: {workflow.ticket_description} — assigned to {workflow.assignee_name}",
            )
            db.commit()
            return

        _, _, completed_status_id, _ = psa_ticket_ids()
        current_status = await revio_psa_ticket_status(workflow.ticket_id)
        workflow.last_checked_at = datetime.utcnow()
        workflow.last_error = None
        if current_status != completed_status_id:
            workflow.status = "Open"
            db.commit()
            return

        workflow.status = "Completed"
        workflow.completed_at = datetime.utcnow()
        rule = PSA_TICKET_RULES[workflow.workflow_key]
        completed_milestone = rule.get("completed_milestone")
        if completed_milestone:
            complete_automation_milestone(db, project, completed_milestone)
        record_psa_activity(
            db, project.id, "psa_ticket_completed",
            f"Rev PSA ticket {workflow.ticket_id} completed: {workflow.ticket_description}",
        )
        next_key = rule.get("next")
        next_workflow = queue_psa_ticket(db, project, next_key) if next_key else None
        db.commit()
        if next_workflow and next_workflow.status in ("Pending", "Retry"):
            await process_psa_ticket_workflow(next_workflow.id)
    except Exception as exc:
        logger.exception("Rev PSA ticket workflow failed for workflow %s", workflow_id)
        db.rollback()
        workflow = db.get(PsaTicketWorkflow, workflow_id)
        if workflow and workflow.status not in ("Completed", "Needs Review"):
            workflow.status = "Needs Review" if (
                isinstance(exc, httpx.HTTPStatusError) and 400 <= exc.response.status_code < 500
            ) else "Retry"
            workflow.last_error = str(exc)[:2000]
            workflow.last_checked_at = datetime.utcnow()
            project = db.get(Project, workflow.project_id)
            if project:
                record_psa_activity(
                    db, project.id, "psa_ticket_retry" if workflow.status == "Retry" else "psa_ticket_review",
                    f"Rev PSA automation could not process {workflow.ticket_description}: {workflow.last_error}",
                )
            db.commit()
    finally:
        db.close()

async def psa_ticket_maintenance():
    interval = max(300, int(os.getenv("REVIO_PSA_TICKET_CHECK_SECONDS", "3600")))
    while True:
        await asyncio.sleep(interval)
        db = SessionLocal()
        try:
            workflow_ids = list(db.scalars(
                select(PsaTicketWorkflow.id).where(
                    PsaTicketWorkflow.status.in_(("Pending", "Retry", "Open"))
                )
            ).all())
        finally:
            db.close()
        for workflow_id in workflow_ids:
            await process_psa_ticket_workflow(workflow_id)


async def graph_send_hardware_order_email(project: dict, billing_customer: dict, signed_quote: dict):
    if not graph_configured():
        raise RuntimeError("Microsoft Graph is not configured")
    sender = quote(os.environ["MS_INTAKE_MAILBOX"], safe="")
    recipient = os.getenv("HARDWARE_ORDER_EMAIL", "sales@bullfrog.net").strip()
    app_url = (os.getenv("APP_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    customer = html.escape(project["customer"])
    project_name = html.escape(project["project_name"])
    project_type = html.escape(project["project_type"])
    sales_owner = html.escape(project.get("sales_owner") or "Not assigned")
    billing_id = html.escape(billing_customer["customer_id"])
    source_type = html.escape(signed_quote.get("source_type") or "Quote")
    source_number = html.escape(str(signed_quote.get("source_number") or signed_quote.get("quote_id") or ""))
    source_description = html.escape(signed_quote["description"])
    product_rows = "".join(
        "<tr><td>" + html.escape(str(product.get("quantity") or "")) + "</td><td>"
        + html.escape(product.get("description") or "") + "</td><td>"
        + html.escape(str(product.get("rate") if product.get("rate") is not None else "")) + "</td></tr>"
        for product in signed_quote["products"]
    )
    if not product_rows:
        product_rows = '<tr><td colspan="3">No product or charge lines were returned for this selection.</td></tr>'
    project_link = f'<p><a href="{html.escape(app_url)}">Open Bullfrog Projects</a></p>' if app_url else ""
    body = f"""
        <p>The approved billing selection for <strong>{customer}</strong> has cleared the Rev.io Billing balance check.</p>
        <table>
          <tr><td><strong>Rev.io Billing Customer ID</strong></td><td>{billing_id}</td></tr>
          <tr><td><strong>Project</strong></td><td>{project_name}</td></tr>
          <tr><td><strong>Project Type</strong></td><td>{project_type}</td></tr>
          <tr><td><strong>Sales Owner</strong></td><td>{sales_owner}</td></tr>
          <tr><td><strong>Rev.io Source</strong></td><td>{source_type} #{source_number}</td></tr>
          <tr><td><strong>Verified Balance</strong></td><td>$0.00</td></tr>
        </table>
        <h3>{source_type} Description</h3>
        <p style="white-space: pre-wrap;">{source_description}</p>
        <h3>Products and Charges</h3>
        <table>
          <thead><tr><th>Quantity</th><th>Description</th><th>Rate</th></tr></thead>
          <tbody>{product_rows}</tbody>
        </table>
        <p><strong>Please order the hardware for this customer.</strong></p>
        {project_link}
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await graph_access_token(client)
        response = await client.post(
            f"{GRAPH_API}/users/{sender}/sendMail",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "message": {
                    "subject": f"Hardware order ready — {project['customer']}",
                    "body": {"contentType": "HTML", "content": body},
                    "toRecipients": [{"emailAddress": {"address": recipient}}],
                },
                "saveToSentItems": True,
            },
        )
        response.raise_for_status()

async def process_hardware_order_workflow(project_id: int):
    db = SessionLocal()
    workflow = None
    try:
        workflow = db.scalar(select(HardwareOrderWorkflow).where(HardwareOrderWorkflow.project_id == project_id))
        project = db.get(Project, project_id)
        if not workflow or not project or workflow.status in ("Sent", "Sending", "Needs Review"):
            return
        previous_status = workflow.status
        previous_balance = workflow.last_balance
        billing_customer = await revio_billing_find_customer(project.customer)
        signed_quote = await revio_billing_selected_source(billing_customer["customer_id"], project.quote_id)
        balance = billing_customer["balance"]
        workflow.revio_customer_id = billing_customer["customer_id"]
        workflow.revio_customer_name = billing_customer["customer_name"]
        workflow.last_balance = str(balance)
        workflow.last_checked_at = datetime.utcnow()
        workflow.last_error = None

        if balance != Decimal("0"):
            workflow.status = "Waiting for zero balance"
            if previous_status != workflow.status or previous_balance != workflow.last_balance:
                record_automation_activity(
                    db, project.id, "hardware_order_waiting",
                    f"Rev.io Billing verified {billing_customer['customer_name']}; "
                    f"hardware order is waiting for the account balance to reach $0.00 "
                    f"(current balance: $" f"{balance:,.2f})",
                    old_value=previous_balance, new_value=workflow.last_balance,
                )
            db.commit()
            return

        project_snapshot = {
            "customer": project.customer, "project_name": project.project_name,
            "project_type": project.project_type, "sales_owner": project.sales_owner,
        }
        workflow.status = "Sending"
        db.commit()
        try:
            await graph_send_hardware_order_email(project_snapshot, billing_customer, signed_quote)
        except httpx.TimeoutException:
            workflow.status = "Needs Review"
            workflow.last_error = "The email request timed out. Delivery is uncertain, so automatic retries are paused."
            record_automation_activity(
                db, project.id, "hardware_order_review",
                "Rev.io Billing balance is $0.00, but the Sales email timed out. "
                "Automatic retry is paused to prevent a duplicate email.",
            )
            db.commit()
            logger.exception("Hardware order email timed out for project %s", project_id)
            return

        workflow.status = "Sent"
        workflow.email_sent_at = datetime.utcnow()
        record_automation_activity(
            db, project.id, "hardware_order_sent",
            f"Rev.io Billing verified {signed_quote.get('source_type', 'Quote')} "
            f"{signed_quote.get('source_number') or signed_quote.get('quote_id')} and a $0.00 balance, then notified "
            f"{os.getenv('HARDWARE_ORDER_EMAIL', 'sales@bullfrog.net')} to order hardware",
            old_value=previous_status, new_value="Sent",
        )
        hardware_ticket = None
        if psa_ticket_automation_enabled():
            try:
                hardware_ticket = queue_psa_ticket(db, project, "hardware_ordered")
            except RuntimeError as exc:
                record_psa_activity(
                    db, project.id, "psa_ticket_review",
                    f"Hardware email was sent, but the Rev PSA hardware ticket could not be queued: {exc}",
                )
        db.commit()
        if hardware_ticket and hardware_ticket.status in ("Pending", "Retry"):
            await process_psa_ticket_workflow(hardware_ticket.id)
    except Exception as exc:
        logger.exception("Hardware order workflow failed for project %s", project_id)
        db.rollback()
        workflow = db.scalar(select(HardwareOrderWorkflow).where(HardwareOrderWorkflow.project_id == project_id))
        project = db.get(Project, project_id)
        if workflow and project and workflow.status != "Sent":
            old_error = workflow.last_error
            workflow.status = "Retry"
            workflow.last_error = str(exc)[:2000]
            workflow.last_checked_at = datetime.utcnow()
            if old_error != workflow.last_error:
                record_automation_activity(
                    db, project.id, "hardware_order_retry",
                    f"Hardware order check could not complete: {workflow.last_error}. It will retry automatically.",
                )
            db.commit()
    finally:
        db.close()

async def hardware_order_maintenance():
    interval = max(300, int(os.getenv("HARDWARE_ORDER_CHECK_SECONDS", "3600")))
    while True:
        await asyncio.sleep(interval)
        db = SessionLocal()
        try:
            project_ids = list(db.scalars(
                select(HardwareOrderWorkflow.project_id).where(
                    HardwareOrderWorkflow.status.in_(("Pending", "Waiting for zero balance", "Retry"))
                )
            ).all())
        finally:
            db.close()
        for project_id in project_ids:
            await process_hardware_order_workflow(project_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_database_schema()
    seed_database()
    ensure_project_workflow_milestones()
    ensure_project_phase_names()
    ensure_project_work_items()
    graph_task = asyncio.create_task(graph_subscription_maintenance())
    hardware_task = asyncio.create_task(hardware_order_maintenance())
    psa_ticket_task = asyncio.create_task(psa_ticket_maintenance()) if psa_ticket_automation_enabled() else None
    try:
        yield
    finally:
        graph_task.cancel()
        hardware_task.cancel()
        if psa_ticket_task:
            psa_ticket_task.cancel()

app = FastAPI(title="Bullfrog Project Command Center", version="1.6.0", lifespan=lifespan)
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
        or path == "/api/intake/email"
        or path == "/api/graph/notifications"
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

@app.get("/api/me")
def get_current_user(request: Request):
    return request.session["user"]

@app.post("/api/graph/notifications")
async def graph_notifications(
    request: Request, background_tasks: BackgroundTasks,
    validation_token: str | None = Query(None, alias="validationToken"),
):
    if validation_token is not None:
        return PlainTextResponse(validation_token)
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Invalid Microsoft Graph notification")
    expected_state = os.getenv("INTAKE_WEBHOOK_SECRET", "")
    message_ids = []
    for notification in payload.get("value", []):
        supplied_state = str(notification.get("clientState") or "")
        if not expected_state or not secrets.compare_digest(supplied_state, expected_state):
            continue
        resource_data = notification.get("resourceData") or {}
        message_id = resource_data.get("id")
        if not message_id:
            resource = unquote(str(notification.get("resource") or ""))
            marker = "/messages/"
            if marker in resource:
                message_id = resource.split(marker, 1)[1]
        if message_id:
            message_ids.append(str(message_id))
    if message_ids:
        background_tasks.add_task(graph_fetch_messages, message_ids)
    return Response(status_code=status.HTTP_202_ACCEPTED)

@app.post("/api/graph/sync")
async def sync_graph_mailbox():
    try:
        added = await graph_sync_recent_messages()
        await ensure_graph_subscription()
        return {"status": "ok", "imported": added}
    except httpx.HTTPStatusError as exc:
        detail = "Microsoft Graph rejected the mailbox request"
        try:
            graph_error = exc.response.json().get("error", {})
            detail = graph_error.get("message") or detail
        except ValueError:
            pass
        raise HTTPException(502, detail)
    except (httpx.HTTPError, KeyError, RuntimeError) as exc:
        raise HTTPException(502, str(exc))

@app.post("/api/intake/email", response_model=IntakeEmailOut, status_code=status.HTTP_201_CREATED)
def receive_intake_email(
    payload: IntakeEmailCreate, request: Request, response: Response,
    db: Session = Depends(get_db),
):
    configured_secret = os.getenv("INTAKE_WEBHOOK_SECRET", "")
    supplied_secret = request.headers.get("X-Intake-Secret", "")
    if not configured_secret:
        raise HTTPException(503, "Email intake is not configured")
    if not supplied_secret or not secrets.compare_digest(supplied_secret, configured_secret):
        raise HTTPException(401, "Invalid intake secret")

    existing = db.scalar(select(IntakeEmail).where(IntakeEmail.message_id == payload.message_id))
    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    item = IntakeEmail(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@app.get("/api/intake", response_model=list[IntakeEmailOut])
def list_intake(status_filter: str = Query("Pending", alias="status"), db: Session = Depends(get_db)):
    stmt = select(IntakeEmail).order_by(IntakeEmail.received_at.desc().nullslast(), IntakeEmail.created_at.desc())
    if status_filter:
        stmt = stmt.where(IntakeEmail.status == status_filter)
    return list(db.scalars(stmt).all())

@app.patch("/api/intake/{intake_id}/dismiss", response_model=IntakeEmailOut)
def dismiss_intake(intake_id: int, db: Session = Depends(get_db)):
    item = db.get(IntakeEmail, intake_id)
    if not item:
        raise HTTPException(404, "Intake email not found")
    if item.status == "Converted":
        raise HTTPException(409, "Converted intake cannot be dismissed")
    item.status = "Dismissed"
    db.commit()
    db.refresh(item)
    return item

@app.post("/api/intake/{intake_id}/convert", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def convert_intake(intake_id: int, payload: IntakeConvert, request: Request, db: Session = Depends(get_db)):
    item = db.get(IntakeEmail, intake_id)
    if not item:
        raise HTTPException(404, "Intake email not found")
    if item.status != "Pending":
        raise HTTPException(409, "This intake email has already been handled")

    project = Project(**payload.project.model_dump())
    db.add(project)
    db.flush()
    for name, phase_name in project_template_milestones(project.project_type, db):
        db.add(Milestone(project_id=project.id, name=name, phase_name=phase_name))
    add_project_work_items(db, project)
    record_activity(
        db, project.id, request, "project_created",
        f"Created project from email intake: {item.subject}",
    )
    item.status = "Converted"
    item.project_id = project.id
    db.commit()
    return db.scalar(project_query().where(Project.id == project.id))

@app.get("/api/revio/customers/{customer_id}")
async def lookup_revio_customer(customer_id: str):
    clean_id = customer_id.strip()
    if not clean_id.isdigit():
        raise HTTPException(400, "Customer ID must contain numbers only")
    if not revio_configured():
        raise HTTPException(503, "Rev PSA is not configured")
    try:
        customer = await revio_lookup_customer(clean_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise HTTPException(502, "Rev PSA rejected the API key or its permissions")
        raise HTTPException(502, f"Rev PSA lookup failed with status {exc.response.status_code}")
    except (httpx.HTTPError, KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(502, str(exc))
    if not customer:
        raise HTTPException(404, f"No Rev PSA customer was found for ID {clean_id}")
    return {"customer_id": customer["customer_id"], "customer_name": customer["customer_name"]}

@app.get("/api/revio/billing/quotes")
async def list_revio_billing_quotes(customer_name: str = Query(..., min_length=1)):
    try:
        customer = await revio_billing_find_customer(customer_name.strip())
        sources = await revio_billing_sources(customer["customer_id"])
        return {
            "billing_customer_id": customer["customer_id"],
            "billing_customer_name": customer["customer_name"],
            "quotes": sources,
            "sources": sources,
        }
    except httpx.HTTPStatusError as exc:
        detail = f"Rev.io Billing quote lookup failed with status {exc.response.status_code}"
        try:
            payload = exc.response.json()
            detail = payload.get("message") or payload.get("error") or detail
        except ValueError:
            pass
        raise HTTPException(502, detail)
    except (httpx.HTTPError, KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(502, str(exc))

@app.get("/api/revio/projects/options")
async def revio_project_options():
    try:
        payload = await revio_project_api_request(
            "GET", "/project-management/api/v1/projects/options"
        )
        return normalize_revio_options(payload)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Rev PSA project options failed with status {exc.response.status_code}")
    except (httpx.HTTPError, KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(502, str(exc))

@app.post("/api/projects/{project_id}/revio/create", status_code=status.HTTP_201_CREATED)
async def create_revio_project(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.scalar(project_query().where(Project.id == project_id))
    if not project:
        raise HTTPException(404, "Project not found")
    if project.revio_project_id:
        raise HTTPException(409, f"Already linked to Rev PSA Project {project.revio_project_id}")
    project.revio_sync_status = "Creating"
    project.revio_sync_error = None
    db.commit()
    try:
        result = await revio_create_project_with_milestones(project, db)
        record_activity(
            db, project.id, request, "revio_project_created",
            f"Created Rev PSA Project {result['revio_project_id']} with {result['milestones_created']} milestone(s)",
        )
        db.commit()
        return result
    except httpx.HTTPStatusError as exc:
        fallback = (
            f"Rev PSA Project {project.revio_project_id} was created, but phase sync failed with status {exc.response.status_code}"
            if project.revio_project_id
            else f"Rev PSA project creation failed with status {exc.response.status_code}"
        )
        detail = revio_http_error_detail(exc, fallback)
        project.revio_sync_status = "Phase Sync Failed" if project.revio_project_id else "Failed"
        project.revio_sync_error = str(detail)[:4000]
        db.commit()
        raise HTTPException(502, detail)
    except (httpx.HTTPError, KeyError, ValueError, RuntimeError) as exc:
        project.revio_sync_status = "Failed"
        project.revio_sync_error = str(exc)[:4000]
        db.commit()
        raise HTTPException(502, str(exc))

@app.put("/api/projects/{project_id}/revio/sync")
async def sync_revio_project(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.scalar(project_query().where(Project.id == project_id))
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.revio_project_id:
        raise HTTPException(409, "This project has not been created in Rev PSA")
    try:
        result = await revio_update_project_details(project)
        project.revio_sync_status = "Synced with Phases" if all(item.revio_phase_id for item in project.milestones) else "Synced"
        project.revio_sync_error = None
        project.revio_synced_at = datetime.utcnow()
        record_activity(
            db, project.id, request, "revio_project_updated",
            f"Updated Rev PSA Project {project.revio_project_id}"
            + (f" with {result['project_hours']} project hours" if result["project_hours"] is not None else ""),
        )
        db.commit()
        return result
    except httpx.HTTPStatusError as exc:
        detail = revio_http_error_detail(
            exc, f"Rev PSA project update failed with status {exc.response.status_code}"
        )
        project.revio_sync_error = str(detail)[:4000]
        db.commit()
        raise HTTPException(502, detail)
    except (httpx.HTTPError, KeyError, ValueError, RuntimeError) as exc:
        project.revio_sync_error = str(exc)[:4000]
        db.commit()
        raise HTTPException(502, str(exc))

@app.post("/api/projects/{project_id}/revio/sync-phases")
async def sync_revio_project_phases(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.scalar(project_query().where(Project.id == project_id))
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.revio_project_id:
        raise HTTPException(409, "Create the Rev PSA project before syncing phases")
    project.revio_sync_status = "Syncing Phases"
    project.revio_sync_error = None
    db.commit()
    try:
        result = await revio_sync_project_phases(project, db)
        record_activity(
            db, project.id, request, "revio_phases_synced",
            f"Synced {result['phases_created']} Rev PSA phase(s), created {result['milestones_created']} milestone(s), and organized {result['milestones_moved']} existing milestone(s)",
        )
        db.commit()
        return result
    except httpx.HTTPStatusError as exc:
        detail = revio_http_error_detail(
            exc, f"Rev PSA phase sync failed with status {exc.response.status_code}"
        )
        project.revio_sync_status = "Phase Sync Failed"
        project.revio_sync_error = str(detail)[:4000]
        db.commit()
        raise HTTPException(502, detail)
    except (httpx.HTTPError, KeyError, ValueError, RuntimeError) as exc:
        project.revio_sync_status = "Phase Sync Failed"
        project.revio_sync_error = str(exc)[:4000]
        db.commit()
        raise HTTPException(502, str(exc))

def serialize_project_template(template: CustomProjectTemplate) -> dict:
    try:
        phases = json.loads(template.phases_json)
    except (TypeError, ValueError):
        phases = []
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "phases": phases,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }

def normalized_project_template(payload: ProjectTemplateCreate) -> tuple[str, str | None, list[dict]]:
    name = payload.name.strip()
    description = payload.description.strip() if payload.description and payload.description.strip() else None
    phases: list[dict] = []
    phase_names: set[str] = set()
    milestone_names: set[str] = set()
    for item in payload.phases:
        phase_name = item.name.strip()
        phase_key = phase_name.casefold()
        if phase_key in phase_names:
            raise HTTPException(400, f"Phase name {phase_name} is duplicated")
        phase_names.add(phase_key)
        owner_role = item.owner_role.strip().lower()
        if owner_role not in {"csm", "engineer", "sales"}:
            raise HTTPException(400, f"Invalid owner role for phase {phase_name}")
        milestones = []
        for raw_name in item.milestones:
            milestone_name = raw_name.strip()
            if not milestone_name:
                continue
            milestone_key = milestone_name.casefold()
            if milestone_key in milestone_names:
                raise HTTPException(400, f"Milestone name {milestone_name} is duplicated")
            milestone_names.add(milestone_key)
            milestones.append(milestone_name)
        if not milestones:
            raise HTTPException(400, f"Phase {phase_name} needs at least one milestone")
        work_items = []
        for work in item.work_items:
            work_name = work.name.strip()
            work_type = work.item_type.strip().title()
            work_owner = work.owner_role.strip().lower()
            if work_type not in {"Ticket", "Task"}:
                raise HTTPException(400, f"Work item {work_name} must be a Ticket or Task")
            if work_owner not in {"csm", "engineer", "sales"}:
                raise HTTPException(400, f"Invalid owner role for work item {work_name}")
            work_items.append({
                "name": work_name,
                "item_type": work_type,
                "owner_role": work_owner,
                "estimated_hours": work.estimated_hours,
                "description": work.description.strip() if work.description and work.description.strip() else None,
            })
        phases.append({"name": phase_name, "owner_role": owner_role, "milestones": milestones, "work_items": work_items})
    return name, description, phases

def ensure_template_name_available(
    db: Session, name: str, exclude_id: int | None = None
):
    if name.casefold() in {item.casefold() for item in PROJECT_TYPES}:
        raise HTTPException(409, "That name is already used by a built-in project type")
    for item in db.scalars(select(CustomProjectTemplate)).all():
        if item.id != exclude_id and item.name.casefold() == name.casefold():
            raise HTTPException(409, "A custom project type with that name already exists")

@app.get("/api/project-templates", response_model=list[ProjectTemplateOut])
def list_project_templates(db: Session = Depends(get_db)):
    items = db.scalars(select(CustomProjectTemplate).order_by(CustomProjectTemplate.name)).all()
    return [serialize_project_template(item) for item in items]

@app.post("/api/project-templates", response_model=ProjectTemplateOut, status_code=status.HTTP_201_CREATED)
def create_project_template(payload: ProjectTemplateCreate, db: Session = Depends(get_db)):
    name, description, phases = normalized_project_template(payload)
    ensure_template_name_available(db, name)
    item = CustomProjectTemplate(
        name=name, description=description, phases_json=json.dumps(phases)
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return serialize_project_template(item)

@app.put("/api/project-templates/{template_id}", response_model=ProjectTemplateOut)
def update_project_template(
    template_id: int, payload: ProjectTemplateCreate, db: Session = Depends(get_db)
):
    item = db.get(CustomProjectTemplate, template_id)
    if not item:
        raise HTTPException(404, "Custom project type not found")
    name, description, phases = normalized_project_template(payload)
    ensure_template_name_available(db, name, exclude_id=template_id)
    if name != item.name and db.scalar(select(Project.id).where(Project.project_type == item.name).limit(1)):
        raise HTTPException(409, "This project type is already in use and cannot be renamed")
    item.name = name
    item.description = description
    item.phases_json = json.dumps(phases)
    db.commit()
    db.refresh(item)
    return serialize_project_template(item)

@app.delete("/api/project-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_template(template_id: int, db: Session = Depends(get_db)):
    item = db.get(CustomProjectTemplate, template_id)
    if not item:
        raise HTTPException(404, "Custom project type not found")
    if db.scalar(select(Project.id).where(Project.project_type == item.name).limit(1)):
        raise HTTPException(409, "This project type is in use and cannot be deleted")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/api/options")
def options(db: Session = Depends(get_db)):
    custom_items = db.scalars(select(CustomProjectTemplate).order_by(CustomProjectTemplate.name)).all()
    custom_types = [item.name for item in custom_items]
    templates = dict(TEMPLATES)
    for item in custom_items:
        phases = custom_template_phases(db, item.name) or []
        templates[item.name] = [name for phase in phases for name in phase["milestones"]]
    return {"stages": STAGES, "risks": RISKS, "priorities": PRIORITIES,
            "project_types": PROJECT_TYPES + custom_types, "templates": templates,
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
def create_project(payload: ProjectCreate, request: Request, db: Session = Depends(get_db)):
    project = Project(**payload.model_dump())
    db.add(project)
    db.flush()
    for name, phase_name in project_template_milestones(project.project_type, db):
        db.add(Milestone(project_id=project.id, name=name, phase_name=phase_name))
    add_project_work_items(db, project)
    record_activity(db, project.id, request, "project_created", f"Created project {project.project_name}")
    db.commit()
    return db.scalar(project_query().where(Project.id == project.id))

@app.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.scalar(project_query().where(Project.id == project_id))
    if not project:
        raise HTTPException(404, "Project not found")
    return project

@app.put("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, request: Request, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        old_value = getattr(project, key)
        if old_value != value:
            setattr(project, key, value)
            label = FIELD_LABELS.get(key, key.replace("_", " ").title())
            record_activity(
                db, project.id, request, "project_updated",
                f"Changed {label} from {activity_value(old_value) or 'Not set'} to {activity_value(value) or 'Not set'}",
                field_name=key, old_value=old_value, new_value=value,
            )
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
def add_milestone(project_id: int, payload: MilestoneCreate, request: Request, db: Session = Depends(get_db)):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    item = Milestone(project_id=project_id, **payload.model_dump())
    db.add(item)
    db.flush()
    record_activity(db, project_id, request, "milestone_added", f"Added milestone {item.name}")
    db.commit(); db.refresh(item)
    return item

@app.patch("/api/milestones/{milestone_id}", response_model=MilestoneOut)
def update_milestone(
    milestone_id: int, payload: MilestoneUpdate, request: Request,
    background_tasks: BackgroundTasks, db: Session = Depends(get_db),
):
    item = db.get(Milestone, milestone_id)
    if not item:
        raise HTTPException(404, "Milestone not found")
    old_status = item.status
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    item.completed_date = date.today() if item.status == "Complete" else None
    if old_status != item.status:
        verb = "Completed" if item.status == "Complete" else "Changed status of"
        description = f"{verb} milestone {item.name}"
        record_activity(db, item.project_id, request, "milestone_updated", description,
                        field_name="milestone_status", old_value=old_status, new_value=item.status)

        # Keep the project summary aligned with the milestone checklist. The
        # first incomplete milestone becomes the next action automatically.
        db.flush()
        project = db.get(Project, item.project_id)
        next_milestone = db.scalar(
            select(Milestone)
            .where(Milestone.project_id == item.project_id, Milestone.status != "Complete")
            .order_by(Milestone.id.asc())
            .limit(1)
        )
        next_action = next_milestone.name if next_milestone else "Review project for completion"
        next_due = next_milestone.due_date if next_milestone else None
        if project and (project.next_action != next_action or project.next_action_due != next_due):
            old_action = project.next_action
            project.next_action = next_action
            project.next_action_due = next_due
            record_activity(
                db, project.id, request, "project_updated",
                f"Advanced Next Action to {next_action}", field_name="next_action",
                old_value=old_action, new_value=next_action,
            )
    normalized_milestone = normalize_customer_name(item.name)
    should_check_hardware_order = (
        old_status != "Complete"
        and item.status == "Complete"
        and normalized_milestone == "hardwarepaymentcheck"
    )
    psa_workflow_id = None
    if should_check_hardware_order:
        workflow = db.scalar(
            select(HardwareOrderWorkflow).where(HardwareOrderWorkflow.project_id == item.project_id)
        )
        if not workflow:
            workflow = HardwareOrderWorkflow(project_id=item.project_id, status="Pending")
            db.add(workflow)
        elif workflow.status != "Sent":
            workflow.status = "Pending"
            workflow.last_error = None
        if workflow.status != "Sent":
            record_automation_activity(
                db, item.project_id, "hardware_order_queued",
                "Hardware Payment Check is complete; queued the Rev.io Billing balance check",
            )

    if psa_ticket_automation_enabled() and old_status != "Complete" and item.status == "Complete":
        workflow_key = MILESTONE_TICKET_RULES.get(normalized_milestone)
        if workflow_key:
            project = db.get(Project, item.project_id)
            try:
                psa_workflow = queue_psa_ticket(db, project, workflow_key)
                if psa_workflow.status in ("Pending", "Retry"):
                    psa_workflow_id = psa_workflow.id
            except RuntimeError as exc:
                record_psa_activity(
                    db, item.project_id, "psa_ticket_review",
                    f"Could not queue Rev PSA ticket for {item.name}: {exc}",
                )

    db.commit(); db.refresh(item)
    if should_check_hardware_order and workflow.status != "Sent":
        background_tasks.add_task(process_hardware_order_workflow, item.project_id)
    if psa_workflow_id:
        background_tasks.add_task(process_psa_ticket_workflow, psa_workflow_id)
    return item

@app.delete("/api/milestones/{milestone_id}", status_code=204)
def delete_milestone(milestone_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(Milestone, milestone_id)
    if not item:
        raise HTTPException(404, "Milestone not found")
    record_activity(db, item.project_id, request, "milestone_deleted", f"Deleted milestone {item.name}")
    db.delete(item); db.commit()
    return Response(status_code=204)

@app.post("/api/projects/{project_id}/contacts", response_model=ContactOut, status_code=201)
def add_contact(project_id: int, payload: ContactCreate, request: Request, db: Session = Depends(get_db)):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    if payload.is_primary:
        for existing in db.scalars(select(CustomerContact).where(CustomerContact.project_id == project_id)):
            existing.is_primary = False
    contact = CustomerContact(project_id=project_id, **payload.model_dump())
    db.add(contact)
    db.flush()
    record_activity(db, project_id, request, "contact_added", f"Added customer contact {contact.name}")
    db.commit(); db.refresh(contact)
    return contact

@app.put("/api/contacts/{contact_id}", response_model=ContactOut)
def update_contact(contact_id: int, payload: ContactUpdate, request: Request, db: Session = Depends(get_db)):
    contact = db.get(CustomerContact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_primary"):
        for existing in db.scalars(select(CustomerContact).where(
            CustomerContact.project_id == contact.project_id,
            CustomerContact.id != contact.id,
        )):
            existing.is_primary = False
    for key, value in data.items():
        setattr(contact, key, value)
    record_activity(db, contact.project_id, request, "contact_updated", f"Updated customer contact {contact.name}")
    db.commit(); db.refresh(contact)
    return contact

@app.delete("/api/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: int, request: Request, db: Session = Depends(get_db)):
    contact = db.get(CustomerContact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    record_activity(db, contact.project_id, request, "contact_deleted", f"Deleted customer contact {contact.name}")
    db.delete(contact); db.commit()
    return Response(status_code=204)

@app.post("/api/projects/{project_id}/notes", response_model=NoteOut, status_code=201)
def add_note(
    project_id: int,
    request: Request,
    note: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    if not note.strip():
        raise HTTPException(422, "Note is required")
    if len(files) > MAX_ATTACHMENTS_PER_NOTE:
        raise HTTPException(413, f"Maximum {MAX_ATTACHMENTS_PER_NOTE} attachments per note")
    actor_name, _ = current_actor(request)
    item = ProjectNote(project_id=project_id, author=actor_name, note=note.strip())
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
    attachment_count = len([upload for upload in files if upload.filename])
    detail = f"Added a project note with {attachment_count} attachment{'s' if attachment_count != 1 else ''}" if attachment_count else "Added a project note"
    record_activity(db, project_id, request, "note_added", detail)
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
