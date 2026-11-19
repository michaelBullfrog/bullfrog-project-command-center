# Sales submissions to Project Intake

The Bullfrog portal's **Submit a Project** card opens `/submit-project`. Verified Webex staff can submit requests to the existing Project Command Center **Project Intake** tab. Sales submissions are marked `Sales Portal` and `Pending`; submitting creates no project, work item, ticket, hardware order, or email. Reviewers use the existing Review & Create action to create a project and choose resource assignments.

## Form

Requires a numeric **Rev PSA** Customer ID verified against Command Center's customer lookup, project name/type, request type (Sold project or Trial), sales owner, scope/customer expectations, and customer contact name/email. Phone and up to five HTTPS shared-document links are optional. Sold projects require a sales-supplied quote reference; trials do not. A requested go-live date or an explicit Unknown choice is required. The quote reference is not proof of quote approval, payment, or customer association; the reviewer verifies it. Documents remain in the existing shared-file system; this release stores links rather than uploaded file bytes.

Project types (including custom types) and sales owners come from Command Center. Customer identity is checked again by Command Center on submission; its verified name overrides browser input. Contact and scope details remain in the intake review context; resource assignments remain the reviewer's responsibility. Structured project name, type, quote reference and requested date prefill Review & Create. Staff can refresh My recent submissions to see their latest 25 request statuses. It is not a complete project portfolio report.

## Connection and security

Uses the existing server-side `PROJECT_COMMAND_CENTER_BASE_URL` (HTTPS origin only) and `PROJECT_COMMAND_CENTER_API_TOKEN`. That token must match Command Center's existing `BULLFROG_MCP_SERVICE_TOKEN`. No new credentials or scopes are needed. The existing read-only MCP project tool remains read-only; these are staff browser routes, not Claude tools.

The browser never receives the token. Staff-only `/submit-project/api/*` routes verify the authenticated identity and exact configured Origin on POST. A machine bearer token without a staff session is insufficient. A caller cannot supply or override submitter identity. The service calls only the fixed `/api/mcp/sales-intake` route family; redirects are not followed. Upstream errors are sanitized. Shared-document URLs are stored as references, not fetched by either server.

Submission UUIDs and a normalized payload hash make retries idempotent. The intake table's unique message ID is the database guard against concurrent duplicate inserts. Reusing a UUID with changed details returns a conflict. A network timeout does not report success; the browser retains the immutable request and retries using the same UUID/body. Automatic POST retries are not performed. Starting a new request intentionally creates a new UUID; it is not business-level duplicate detection across different submissions or browsers. Unsaved form data remains in tab memory and warns before leaving.

Deployment order: deploy the Command Center receiver/schema change first, then the portal. Command Center adds nullable `sales_details_json` and `submission_hash` columns to the existing intake table during normal startup migration. No existing intake is converted or dismissed by deployment. The JSON wire contract is kept identical in both repositories (`sales_intake_contract.py`). No new Render resources or environment variables are required when the existing project service connection is already configured.

## Validation

Isolated database tests verify one Pending intake, no project/work creation on submit, identity matching, required fields, exact retry receipts, changed-payload conflicts, submitter filtering and existing review conversion. Portal tests verify staff/origin gates, server-assigned identity, sanitized failures, private service credentials, bounded requests and customer identity. DOM tests verify form conditions, safe text and immutable retry behavior. Production submissions are not created as test data.
