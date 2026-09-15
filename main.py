import asyncio
import html
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
from models import CustomerContact, HardwareOrderWorkflow, IntakeEmail, Milestone, NoteAttachment, Project, ProjectActivity, ProjectNote
from schemas import (
    ContactCreate, ContactOut, ContactUpdate, IntakeConvert, IntakeEmailCreate, IntakeEmailOut,
    MilestoneCreate, MilestoneOut, MilestoneUpdate, NoteOut, ProjectCreate, ProjectOut, ProjectUpdate,
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
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
GRAPH_API = "https://graph.microsoft.com/v1.0"
logger = logging.getLogger("bullfrog.graph")

TEMPLATES = {
    "Webex Calling": ["Quote Signed", "Discovery Complete", "Network Review Complete", "Control Hub Provisioned",
        "Users and Licenses Configured", "Number Port Submitted", "FOC Received",
        "Devices Configured", "Call Flows Tested", "Customer Training", "Go Live", "Closeout"],
    "Webex Contact Center": ["Quote Signed", "Discovery Complete", "Call Flow Design", "Queue and Team Design",
        "Agent Setup", "Integrations", "Flow Build", "Testing", "Supervisor Training", "Go Live", "Closeout"],
    "Meraki": ["Quote Signed", "Discovery Complete", "Network Design", "Hardware Received", "Configuration",
        "Staging", "Installation", "Validation", "Documentation", "Closeout"],
    "Network": ["Quote Signed", "Discovery Complete", "Network Design", "Hardware Received", "Configuration",
        "Installation", "Validation", "Documentation", "Closeout"],
    "Other": ["Quote Signed", "Discovery Complete", "Planning", "Implementation", "Testing", "Customer Acceptance", "Closeout"],
}

def project_query():
    return select(Project).options(
        selectinload(Project.milestones),
        selectinload(Project.notes).selectinload(ProjectNote.attachments),
        selectinload(Project.contacts),
        selectinload(Project.activities),
    )

FIELD_LABELS = {
    "customer": "Customer", "customer_id": "Rev PSA Customer ID", "project_name": "Project name", "project_type": "Project type",
    "technical_manager": "Customer Success Manager", "engineer": "Assigned Engineer",
    "sales_owner": "Sales Owner", "stage": "Stage", "risk": "Risk", "priority": "Priority",
    "target_date": "Target go-live", "next_action": "Next action",
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
                db.add(Milestone(project_id=project.id, name=name))
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


def normalize_customer_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())

def revio_billing_configured() -> bool:
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

async def revio_billing_find_customer(customer_name: str) -> dict:
    if not revio_billing_configured():
        raise RuntimeError("Rev.io Billing is not configured")
    base_url = os.getenv("REVIO_BILLING_BASE_URL", "https://restapi.rev.io").rstrip("/")
    username = os.environ["REVIO_BILLING_USERNAME"].strip()
    client_code = os.environ["REVIO_BILLING_CLIENT_CODE"].strip()
    password = os.environ["REVIO_BILLING_PASSWORD"]
    auth = httpx.BasicAuth(f"{username}@{client_code}", password)
    async with httpx.AsyncClient(timeout=30.0, auth=auth) as client:
        response = await client.get(
            f"{base_url}/v1/Customers",
            params={"search.name": customer_name, "search.page_size": 25},
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
    payload = response.json()
    records = payload.get("records", []) if isinstance(payload, dict) else []
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

def record_automation_activity(db: Session, project_id: int, action: str, description: str, old_value=None, new_value=None):
    db.add(ProjectActivity(
        project_id=project_id, actor_name="Bullfrog Automation", actor_email=None,
        action=action, field_name="hardware_order_workflow",
        old_value=activity_value(old_value) if old_value is not None else None,
        new_value=activity_value(new_value) if new_value is not None else None,
        description=description,
    ))

async def graph_send_hardware_order_email(project: dict, billing_customer: dict):
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
    project_link = f'<p><a href="{html.escape(app_url)}">Open Bullfrog Projects</a></p>' if app_url else ""
    body = f"""
        <p>The signed quote for <strong>{customer}</strong> has cleared the Rev.io Billing balance check.</p>
        <table>
          <tr><td><strong>Rev.io Billing Customer ID</strong></td><td>{billing_id}</td></tr>
          <tr><td><strong>Project</strong></td><td>{project_name}</td></tr>
          <tr><td><strong>Project Type</strong></td><td>{project_type}</td></tr>
          <tr><td><strong>Sales Owner</strong></td><td>{sales_owner}</td></tr>
          <tr><td><strong>Verified Balance</strong></td><td>$0.00</td></tr>
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
            await graph_send_hardware_order_email(project_snapshot, billing_customer)
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
            f"Rev.io Billing verified a $0.00 balance and notified "
            f"{os.getenv('HARDWARE_ORDER_EMAIL', 'sales@bullfrog.net')} to order hardware",
            old_value=previous_status, new_value="Sent",
        )
        db.commit()
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
    graph_task = asyncio.create_task(graph_subscription_maintenance())
    hardware_task = asyncio.create_task(hardware_order_maintenance())
    try:
        yield
    finally:
        graph_task.cancel()
        hardware_task.cancel()

app = FastAPI(title="Bullfrog Project Command Center", version="1.5.0", lifespan=lifespan)
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
    for name in TEMPLATES.get(project.project_type, TEMPLATES["Other"]):
        db.add(Milestone(project_id=project.id, name=name))
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
def create_project(payload: ProjectCreate, request: Request, db: Session = Depends(get_db)):
    project = Project(**payload.model_dump())
    db.add(project)
    db.flush()
    for name in TEMPLATES.get(project.project_type, TEMPLATES["Other"]):
        db.add(Milestone(project_id=project.id, name=name))
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
    should_check_hardware_order = (
        old_status != "Complete"
        and item.status == "Complete"
        and item.name.strip().casefold() == "quote signed"
    )
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
                "Quote Signed is complete; queued the Rev.io Billing balance check",
            )
    db.commit(); db.refresh(item)
    if should_check_hardware_order and workflow.status != "Sent":
        background_tasks.add_task(process_hardware_order_workflow, item.project_id)
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
