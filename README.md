# Bullfrog Project Command Center

A lightweight internal project-management application for Bullfrog technical operations. It provides a manager-first dashboard, standardized project intake, milestones, notes, risk tracking, next actions, and engineer workload visibility.

## Included in V1

- Dashboard with active, at-risk, overdue, and upcoming go-live counts
- Needs Attention and Upcoming Go-Lives queues
- Searchable/filterable project list
- New and edit project forms
- Project detail view with scope, next action, milestones, notes, and persistent attachments
- Engineer workload view
- Automatic milestone templates for Webex Calling, Webex Contact Center, Meraki, Network, and Other
- FastAPI REST API
- PostgreSQL production support and SQLite local fallback
- Sample data on a new empty database
- Shared-login protection for the dashboard, APIs, and attachments
- Single-service Render Blueprint configuration

## Run locally

1. Install Python 3.11 or newer.
2. Clone the repository.
3. Create a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Install and start:

   ```powershell
   pip install -r requirements.txt
   uvicorn main:app --reload
   ```

5. Open [http://localhost:8000](http://localhost:8000).

No environment variable is required locally; the app creates `bullfrog_projects.db`.

## Deploy a test version to Render

1. In Render, select **New + → Blueprint**.
2. Connect this GitHub repository.
3. Approve the single web service from `render.yaml`.
4. Select **Apply**.

This V1 Blueprint uses SQLite so it creates only one Render resource. It is suitable for interface and workflow testing, but a free Render web service has an ephemeral filesystem. Data can be lost during a restart or redeployment.

## Before production use

Connect a durable PostgreSQL database by setting the web service's `DATABASE_URL` environment variable. The database can be an existing Render Postgres database or an external PostgreSQL provider. Do not enter real customer project information until durable storage and authentication are configured.

## Required Webex SSO configuration

Create a Webex OAuth integration with this callback:

`https://bullfrog-project-command-center.onrender.com/auth/callback`

Select only the `spark:people_read` scope. Add these environment variables to the Render web service:

- `WEBEX_CLIENT_ID`
- `WEBEX_CLIENT_SECRET`
- `WEBEX_REDIRECT_URI`
- `WEBEX_ALLOWED_DOMAIN=bullfrog.net`
- `SESSION_SECRET`: a long random value
- Optional `WEBEX_ALLOWED_ORG_ID`: further restrict access to one Webex organization

The integration verifies the user through `/v1/people/me` and then discards the Webex access and refresh tokens. The signed application session contains only the user's name, email, and organization ID. The public health-check endpoint remains available at `/api/health`.

Note attachments support PNG, JPG, PDF, Word, Excel, and TXT files. Each file is limited to 10 MB, with up to five files per note. Attachments are stored in PostgreSQL and require Webex SSO.

## Hardware Payment Check order automation

New project templates separate **Signed Proposal** from **Hardware Payment Check**. Signed Proposal creates the internal-handoff PSA ticket. When Hardware Payment Check is marked complete, the app:

1. searches Rev.io Billing for an exact normalized customer-name match;
2. reads the customer's account-wide `finance.balance` (including unbilled transactions);
3. waits and rechecks hourly while the balance is not zero; and
4. sends one hardware-order email to `sales@bullfrog.net` after a confirmed $0.00 balance.

The workflow is persisted in PostgreSQL and will not send a second email if the milestone is toggled or the app restarts. Its checks and outcomes are written to Project Activity History.

Configure this Render secret:

- `REVIO_BILLING_AUTHORIZATION`: the complete `Basic …` authorization value from Rev.io Billing

The app also supports `REVIO_BILLING_USERNAME`, `REVIO_BILLING_CLIENT_CODE`, and `REVIO_BILLING_PASSWORD` as an optional fallback.

- Optional `REVIO_BILLING_BASE_URL` (defaults to `https://restapi.rev.io`)
- Optional `HARDWARE_ORDER_EMAIL` (defaults to `sales@bullfrog.net`)
- Optional `HARDWARE_ORDER_CHECK_SECONDS` (defaults to 3600; minimum 300)

These settings are separate from the Rev.io PSA API. Store the authorization value only as a secret environment variable; never commit it to GitHub.

The Microsoft Entra application used by `MS_INTAKE_MAILBOX` must also have the Microsoft Graph **Mail.Send application permission** with admin consent. The existing Exchange application access policy should keep send-as access limited to the approved mailbox.

## API

Interactive API documentation is available at `/docs`. Health check: `/api/health`.

Primary endpoints:

- `GET/POST /api/projects`
- `GET/PUT/DELETE /api/projects/{id}`
- `POST /api/projects/{id}/milestones`
- `PATCH/DELETE /api/milestones/{id}`
- `POST /api/projects/{id}/notes`
- `GET /api/options`

## V1 security note

Webex OAuth protects the application and limits access to the configured Bullfrog email domain. For stronger enforcement, configure WEBEX_ALLOWED_ORG_ID in addition to the domain restriction.


## Rev PSA project creation

The project form can create a complete Rev PSA project from the Bullfrog dashboard. It uses the existing `REVIO_API_KEY` token exchange and the project-management API at `REVIO_PROJECT_BASE_URL` (default: `https://apim.psarev.io`).

The form loads Rev PSA project statuses and priorities dynamically, sends the customer, dates, budget, hours, billable flag, owner, description, notes, and matching team members, then creates each Bullfrog checklist item as a Rev PSA project milestone. The returned Rev PSA Project ID and milestone IDs are saved locally. Project creation can be retried safely when the Rev PSA Project ID has not yet been returned.

Project work-item endpoints only link existing Rev PSA tickets or calendar tasks. Milestone ticket automation remains disabled unless `REVIO_PSA_TICKET_AUTOMATION_ENABLED=true`.
