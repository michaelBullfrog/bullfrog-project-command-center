"""Service-authenticated sales requests into Pending Intake; never create projects."""
import hashlib
import json
import os
from datetime import datetime
from uuid import UUID
from fastapi import Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from models import IntakeEmail
from sales_intake_contract import SalesSubmission

VERSION = '2026-11-19-sales-intake-v1'


def allowed_email(value):
    domain = os.getenv('WEBEX_ALLOWED_DOMAIN', 'bullfrog.net').strip().lower()
    return isinstance(value, str) and bool(domain) and value.lower().endswith('@' + domain)


def receipt(item):
    return {'ok': True, 'intake_id': item.id, 'reference': 'PCC-INTAKE-' + str(item.id),
        'status': item.status, 'project_id': item.project_id, 'subject': item.subject,
        'received_at': (item.received_at or item.created_at).isoformat(),
        'submission_id': item.message_id.rsplit(':', 1)[-1]}


def content_hash(payload):
    content = {'submitter_email': payload.submitter.email.lower(), 'details': payload.details.model_dump(mode='json')}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def install_routes(app, require_token, lookup_customer, get_options, get_db):
    async def checked_customer(customer_id):
        try:
            customer = await lookup_customer(customer_id)
        except HTTPException as exc:
            raise HTTPException(404 if exc.status_code == 404 else 503 if exc.status_code == 503 else 502,
                'Customer not found.' if exc.status_code == 404 else 'Customer verification is unavailable.') from None
        except Exception:
            raise HTTPException(502, 'Customer verification is unavailable.') from None
        if not isinstance(customer, dict) or str(customer.get('customer_id')) != customer_id:
            raise HTTPException(502, 'The customer lookup returned a different customer ID.')
        return {'customer_id': customer_id, 'customer_name': str(customer['customer_name'])[:255]}

    @app.get('/api/mcp/sales-intake/options', dependencies=[Depends(require_token)])
    def sales_options(db=Depends(get_db)):
        values = get_options(db)
        return {'ok': True, 'project_types': values['project_types'], 'sales_owners': values['sales_owners']}

    @app.get('/api/mcp/sales-intake/customers/{customer_id}', dependencies=[Depends(require_token)])
    async def sales_customer(customer_id: str):
        if not customer_id.isascii() or not customer_id.isdigit() or len(customer_id) > 50:
            raise HTTPException(400, 'A numeric Rev PSA Customer ID is required.')
        return {'ok': True, **await checked_customer(customer_id)}

    @app.get('/api/mcp/sales-intake/submissions', dependencies=[Depends(require_token)])
    def sales_submissions(email: str, db=Depends(get_db)):
        if not allowed_email(email):
            raise HTTPException(400, 'A staff submitter is required.')
        rows = db.scalars(select(IntakeEmail).where(IntakeEmail.sender_email == email.lower(),
            IntakeEmail.source_type == 'Sales Portal').order_by(IntakeEmail.id.desc()).limit(25)).all()
        return {'ok': True, 'submissions': [receipt(item) for item in rows]}

    @app.post('/api/mcp/sales-intake', dependencies=[Depends(require_token)])
    async def sales_submit(request: Request, db=Depends(get_db)):
        raw, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 40000:
                raise HTTPException(413, 'Submission is too large.')
            raw.append(chunk)
        try:
            payload = SalesSubmission.model_validate_json(b''.join(raw))
        except ValidationError as exc:
            raise HTTPException(422, detail=[{'loc': e['loc'], 'msg': e['msg']} for e in exc.errors()])
        if not allowed_email(payload.submitter.email):
            raise HTTPException(403, 'A Bullfrog staff submitter is required.')
        email = payload.submitter.email.lower()
        key = 'sales-portal:' + email + ':' + str(payload.submission_id)
        fingerprint = content_hash(payload)

        def previous():
            item = db.scalar(select(IntakeEmail).where(IntakeEmail.message_id == key))
            if item:
                if item.submission_hash != fingerprint:
                    raise HTTPException(409, 'This submission reference was already used with different details.')
                return receipt(item)
            return None

        existing = previous()
        if existing:
            return existing
        details = payload.details
        choices = get_options(db)
        if details.project_type not in choices['project_types'] or details.sales_owner not in choices['sales_owners']:
            raise HTTPException(422, 'Choose a current project type and sales owner.')
        customer = await checked_customer(details.customer_id)
        lines = [
            'Sales submission — pending review. No project has been created.',
            'Submitted by: ' + payload.submitter.name + ' <' + email + '>',
            'Customer: ' + customer['customer_name'], 'Rev PSA Customer ID: ' + details.customer_id,
            'Project: ' + details.project_name, 'Project type: ' + details.project_type,
            'Request type: ' + details.request_type, 'Sales owner: ' + details.sales_owner,
            'Quote reference (sales supplied; reviewer must verify): ' + (details.quote_reference or 'Not supplied — trial'),
            'Requested go-live: ' + (details.requested_go_live.isoformat() if details.requested_go_live else 'Unknown'),
            'Customer contact: ' + details.contact_name, 'Contact email: ' + details.contact_email,
            'Contact phone: ' + (details.contact_phone or 'Not supplied'), '', 'Scope and customer expectations:', details.scope,
        ]
        if details.supporting_links:
            lines.extend(['', 'Supporting documents (review access and contents):', *details.supporting_links])
        # The existing intake body renderer strips email HTML. Escape literal
        # angle brackets so customer scope is preserved as text through review.
        import html
        body = '<pre>' + html.escape('\n'.join(lines)) + '</pre>'
        item = IntakeEmail(message_id=key, sender_name=payload.submitter.name, sender_email=email,
            source_type='Sales Portal', customer_id=details.customer_id, customer_name=customer['customer_name'],
            quote_id=details.quote_reference or None, sales_owner=details.sales_owner,
            subject=('Sales request: ' + details.project_name)[:500], body=body,
            sales_details_json=details.model_dump_json(), submission_hash=fingerprint,
            received_at=datetime.utcnow(), status='Pending', project_id=None)
        db.add(item)
        try:
            db.commit()
            db.refresh(item)
        except IntegrityError:
            db.rollback()
            existing = previous()
            if existing:
                return existing
            raise HTTPException(409, 'The submission could not be saved; retry with the same reference.')
        return receipt(item)
