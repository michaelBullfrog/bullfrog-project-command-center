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
2. reads the selected Rev.io Bill and its payment applications;
3. waits for Rev.io payment webhooks and runs a daily 7:00 a.m. Eastern reconciliation until payments applied to that exact Bill cover its full amount; and
4. sends one hardware-order email to `sales@bullfrog.net` after the selected Bill is fully paid.

The workflow is persisted in PostgreSQL and will not send a second email if the milestone is toggled or the app restarts. Its checks and outcomes are written to Project Activity History.

Configure this Render secret:

- `REVIO_BILLING_AUTHORIZATION`: the complete `Basic …` authorization value from Rev.io Billing

The app also supports `REVIO_BILLING_USERNAME`, `REVIO_BILLING_CLIENT_CODE`, and `REVIO_BILLING_PASSWORD` as an optional fallback.

- Optional `REVIO_BILLING_BASE_URL` (defaults to `https://restapi.rev.io`)
- Optional `HARDWARE_ORDER_EMAIL` (defaults to `sales@bullfrog.net`)
- Optional `HARDWARE_ORDER_RECONCILIATION_HOUR` (defaults to `7`)
- Optional `HARDWARE_ORDER_RECONCILIATION_TIMEZONE` (defaults to `America/New_York`)

## Rev.io Billing webhooks and Automation Center

The **Automations** screen shows Hardware Payment workflows, remaining selected-Bill balances, last and next checks, email delivery time, errors, and the latest Rev.io Billing webhook events. A manager can run a payment check immediately or retry a failed webhook event. A daily 7:00 a.m. Eastern reconciliation remains enabled as a fallback.

To enable immediate payment-event processing:

1. Add a long random `REVIO_WEBHOOK_TOKEN` secret to the Render web service and redeploy.
2. In Rev.io Billing, register this receiver URL, replacing `<token>` with the exact secret:
   `https://bullfrog-project-command-center.onrender.com/api/webhooks/revio-billing/<token>`
3. Enable `PAYMENT_CREATED`, `PAYMENT_REAPPLIED`, `PAYMENT_REVERSED`, `PAYMENT_VOID`, and `PAYMENT_BOUNCED`.
4. Require receiver confirmation. The endpoint echoes Rev.io's `X-Hook-Secret` header and activates the receiver.

Webhook events are saved before processing and deduplicated by Rev.io event ID. Positive payment events immediately recheck projects linked to the affected Bill. A reversal, void, or bounced payment after the hardware-order email was sent changes the workflow to **Needs Review** but never sends a duplicate order email.

## Rev PSA approved quote intake

The app checks Rev PSA for quote approvals every five minutes and adds newly approved quotes to **Project Intake**. The first successful check records the current quote statuses as a baseline, so historical approvals do not flood the intake queue. Later transitions to Approved are deduplicated by Rev PSA Quote ID and include the customer, Customer ID, quote description, sales owner, approval time, and available total. Clicking **Sync Inbox** also runs the quote check immediately.

Optional settings:

- `REVIO_QUOTE_PATH` defaults to `/billing/api/v1/quotes`.
- `REVIO_QUOTE_SYNC_SECONDS` defaults to `300` and cannot run more frequently than once per minute.

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

Project work items create and link Rev PSA tickets or calendar tasks to their matching phases. The Go-Live milestone always creates a CSM ticket to update the Rev PSA Overview with final license counts. The broader legacy milestone ticket chain remains disabled unless `REVIO_PSA_TICKET_AUTOMATION_ENABLED=true`.

## Sales portal intake

Sales requests from the Bullfrog portal appear in **Project Intake** as **Sales Portal / Pending Review**. Submission does not create a project. Existing Review & Create converts the request after review. See [sales intake](docs/sales-intake.md).


### Services inbox subject filter
Email intake from the configured `MS_INTAKE_MAILBOX` (services@bullfrog.net) accepts only the complete subject **New Project**, ignoring capitalization and surrounding whitespace. Replies, forwards, empty subjects and longer subjects are skipped. The filter applies to Graph notifications, Sync Inbox imports, and the authenticated email-intake webhook; skipped webhook requests receive HTTP 200 with `status: ignored`. Existing intake entries remain unchanged. Sales Portal submissions, quote intake, and Orders-folder monitoring use their own ingestion paths.


## Quote approval emails to Sales
The scheduled Rev PSA quote poll (default five minutes) now observes approval independently of the existing **Complete** quote intake import. A newly approved/accepted quote, or a quote first seen as Complete, prompts its verified sales owner to begin the internal handoff at https://mcp.bullfrog.net/submit-project. The message includes the quote ID, customer and Rev PSA customer ID, source status, description and source total. It uses the existing `PSA_NOTIFICATION_SENDER` (default projectintake@bullfrog.net) and Microsoft Graph mail connection.

The first nonempty scheduled poll establishes a baseline: existing approvals do not send historical email. Exact-quote checks cannot establish this baseline. Previously unseen older approvals are also suppressed using approval timestamps and the baseline quote ID boundary. Open quotes observed after activation send on an approval transition. One notice is kept per quote, including across restarts and repeated polls. Approved/accepted/complete statuses use the existing Rev PSA approval classifier; pending approval is excluded.

For quotes without an assignedTo ID, fallback recipients are Jack Harris → jack@bullfrog.net and Matthew/Matt Petrusha → matthew@bullfrog.net. Matching uses exact source owner names or the known mailbox, rather than substring matching. Missing, unknown or conflicting owner information creates a Blocked notice and sends no email; subsequent polls can resolve it when the source owner is corrected.

**Project Intake → Quote approval emails to Sales** shows queued, sent, blocked and failed notices. Sent means Microsoft Graph accepted the request, not confirmed inbox delivery. A definitive mail-service rejection can be retried using **Retry rejected email**. A timeout, server error or interrupted send is **Needs review** and is never automatically resent: check the sender's Sent Items first. The staff-only `/api/revio/quote-handoffs` endpoint exposes the same metadata; mail bodies are not returned. Queueing does not create a project or submit the sales form, and does not change Rev PSA.

Approval monitoring uses the existing recent-quote page window (`REVIO_QUOTE_RECENT_PAGES`, default 5 pages). Quotes outside the fetched window are not observed by this poll. No historical approval emails are backfilled automatically.


### Quote assignee resolution
Quote `assignedTo` is resolved against `GET /billing/api/v1/users` using **billingUserId**, not globalUserId. The verified active user's name and email are shown with recent quotes, and the handoff prompt goes to that assigned Bullfrog user (including a CSM if the quote is assigned to them). One user-directory read serves each quote poll. Missing, inactive, ambiguous or external-email assignees remain blocked; an unresolved assignedTo never falls back to a guessed sales owner. Name-based Jack/Matt mapping is retained only for quotes without an assignedTo ID. The existing approval baseline and sent-notice history are retained; this upgrade does not backfill old approvals or resend sent notices.


## Timeline & Stages
Open **Timeline & Stages** in the sidebar for a Gantt timeline grouped by the current project stage, or switch to **Stage board** for cards in stage columns. Drag a project bar/card into a different stage section, or use its **Move to…** menu (keyboard and touch supported). Moves save the shared Command Center stage immediately and record the signed-in staff member in Activity History. A stage-only write with an expected prior stage rejects conflicting concurrent changes.

Gantt bars use the saved project start and target go-live dates. Expand a project with **+** to see milestone phases using their saved start, end and due dates. Missing schedules remain visibly unscheduled; one-sided dates are markers, and reversed dates are flagged for correction. The chart groups by **current** stage and shows planned schedules; it does not fabricate stage history or dates. Dragging between stages does not reschedule projects, complete milestones, or change Rev PSA statuses.

Search customer/project/engineer/CSM, include completed projects, choose 4 weeks / 3 months / 6 months, use Today and the navigation arrows, or Fit projects (up to two years). Board moves and Gantt moves update the same projects used everywhere else in the dashboard. Open a project name/bar for its full details.

Validation: `python -m pytest -q tests/test_stage_moves.py` and `NODE_PATH=<jsdom modules> node tests/test_project_planner_ui.cjs`.
