"""Durable quote approval prompts; Microsoft Graph sendMail is not idempotent."""
import html
import json
import re
from datetime import datetime, timedelta
import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from models import IntegrationSyncState, QuoteHandoffNotice
from quote_assignees import billing_id, staff_email

BASELINE_KEY = 'quote_sales_handoff_baseline_v1'
SUBMIT_URL = 'https://mcp.bullfrog.net/submit-project'
SALES_MAILBOXES = {'jack':'jack@bullfrog.net', 'jackharris':'jack@bullfrog.net',
    'matt':'matthew@bullfrog.net', 'matthew':'matthew@bullfrog.net', 'matthewpetrusha':'matthew@bullfrog.net',
    'mattpetrusha':'matthew@bullfrog.net'}


def owner_values(raw):
    names = [raw[k] for k in ('salesOwnerName','sales_owner_name','salesRepName','sales_rep_name','assigneeName','assignee_name','ownerName','owner_name') if raw.get(k)]
    emails = [raw[k] for k in ('salesOwnerEmail','sales_owner_email','salesRepEmail','sales_rep_email') if raw.get(k)]
    for key in ('salesRep','sales_rep','assignee','owner'):
        owner = raw.get(key)
        if isinstance(owner,dict):
            names.extend(owner[k] for k in ('name','displayName','fullName') if owner.get(k))
            emails.extend(owner[k] for k in ('email','emailAddress') if isinstance(owner.get(k),str) and owner.get(k))
    return names,emails


def recipient_for(record):
    assigned_value = record.get('assigned_to') or (record.get('raw') or {}).get('assignedTo')
    assigned_to = billing_id(assigned_value)
    if assigned_value not in (None,'',0,'0'):
        if not assigned_to:return None
        user = record.get('assigned_user') or {}
        return staff_email(user.get('email')) if billing_id(user.get('billing_user_id')) == assigned_to else None
    names,emails=owner_values(record.get('raw') or {})
    matches = {SALES_MAILBOXES.get(re.sub(r'[^a-z0-9]','',str(name).lower())) for name in names}
    known_emails=set(SALES_MAILBOXES.values())
    for email in emails:
        value=str(email).strip().lower()
        matches.add(value if value in known_emails else None)
    return next(iter(matches)) if len(matches)==1 and None not in matches else None


def message_for(record):
    quote_id=str(record['quote_id'])
    customer=str(record.get('customer_name') or 'Customer not returned')
    details=[('Customer',customer),('Rev PSA Customer ID',record.get('customer_id') or 'Not returned'),
        ('Quote ID',quote_id),('Quote',record.get('quote_name') or 'Not returned'),
        ('Quote status',record.get('status_name') or 'Approved'),('Sales owner',record.get('sales_owner') or 'Not returned')]
    if record.get('assigned_to'):
        user=record.get('assigned_user') or {}
        details.extend([('Assigned to',user.get('name') or 'Unresolved'),('Billing User ID',record['assigned_to'])])
    if record.get('amount') not in (None,''):
        details.append(('Source quote total',str(record['amount'])))
    rows=''.join('<tr><th align="left">'+html.escape(k)+'</th><td>'+html.escape(str(v))+'</td></tr>' for k,v in details)
    subject=('Quote #'+quote_id+' approved — start internal handoff — '+customer)[:500]
    body=('<h2>Start the internal project handoff</h2><p>A quote is approved in Rev PSA. '
        'Please complete the sales submission so the team can review the project handoff.</p><table>'+rows+'</table>'
        '<p><a href="'+SUBMIT_URL+'">Submit a Project</a></p>'
        '<p>Sign in with your Bullfrog Webex account. Use the customer ID and quote reference above, '
        'then add the scope, customer contacts, requested go-live date, and supporting attachments.</p>'
        '<p>If this quote has already been submitted, do not submit it again. '
        'Submitting sends the request to Project Intake for review; it does not create a project immediately.</p>')
    return subject,body


def number(value):
    try:return int(value)
    except (TypeError,ValueError):return -1


async def observe_quotes(factory,records,enrich,*,allow_baseline=True,now=None):
    now=now or datetime.utcnow()
    with factory() as db:
        baseline=db.get(IntegrationSyncState,BASELINE_KEY)
        if baseline is None and (not allow_baseline or not records):
            return
        first=baseline is None
        context=json.loads(baseline.value) if baseline else {'max_id':max([number(r['quote_id']) for r in records]+[-1]),'activated_at':now.isoformat()}
        activated=datetime.fromisoformat(context['activated_at'])
        for record in records:
            key=str(record['quote_id'])
            notice=db.get(QuoteHandoffNotice,key)
            if notice is None:
                notice=QuoteHandoffNotice(quote_id=key,status='Watching')
                db.add(notice)
                old_approval=(record.get('approved_at') is not None and record['approved_at']<activated)
                historical=(old_approval or (record.get('approved_at') is None and number(key)<=context['max_id']))
                if record.get('is_approved') and (first or historical):
                    notice.status='Baselined'
            if not record.get('is_approved') or notice.status not in ('Watching','Blocked'):
                continue
            source_assigned_to=record.get("assigned_to") or (record.get("raw") or {}).get("assignedTo")
            source_recipient=recipient_for(record)
            record=await enrich(record)
            notice.customer_name=str(record.get('customer_name') or '')[:255] or None
            notice.quote_name=str(record.get('quote_name') or '')[:500] or None
            notice.recipient=recipient_for(record)
            if not source_assigned_to and not record.get('assigned_to') and not (record.get('raw') or {}).get('assignedTo') and not any(owner_values(record.get('raw') or {})):
                notice.recipient=source_recipient
            notice.subject,notice.body=message_for(record)
            notice.queued_at=notice.queued_at or now
            notice.status='Pending' if notice.recipient else 'Blocked'
            notice.error=None if notice.recipient else record.get('assignee_error') or 'Quote assignee or sales owner is missing, unrecognized, or conflicting; no email sent.'
        if first:
            db.add(IntegrationSyncState(key=BASELINE_KEY,value=json.dumps(context)))
        try:db.commit()
        except IntegrityError:
            # Another poll won the unique-key race. Reconcile at the next poll.
            db.rollback()


async def dispatch_pending(factory,send,*,configured=True,now=None):
    now=now or datetime.utcnow()
    with factory() as db:
        db.execute(update(QuoteHandoffNotice).where(QuoteHandoffNotice.status=='Sending',
            QuoteHandoffNotice.attempted_at<now-timedelta(minutes=15)).values(status='Needs review',error='Delivery was interrupted. Check Sent Items before retrying.'))
        db.commit()
        keys=list(db.scalars(select(QuoteHandoffNotice.quote_id).where(QuoteHandoffNotice.status=='Pending').order_by(QuoteHandoffNotice.queued_at).limit(10))) if configured else []
    for key in keys:
        with factory() as db:
            claimed=db.execute(update(QuoteHandoffNotice).where(QuoteHandoffNotice.quote_id==key,
                QuoteHandoffNotice.status=='Pending').values(status='Sending',attempted_at=now))
            db.commit()
            if claimed.rowcount!=1:continue
            notice=db.get(QuoteHandoffNotice,key)
            recipient,subject,body=notice.recipient,notice.subject,notice.body
        try:
            await send(recipient,subject,body)
        except httpx.HTTPStatusError as exc:
            code=exc.response.status_code
            # A definitive 4xx rejection can be safely retried by staff. Other
            # outcomes might already have accepted mail: never retry blindly.
            status='Failed' if 400<=code<500 and code!=408 else 'Needs review'
            error=f'Mail service returned HTTP {code}. '+('Fix the mail connection, then retry.' if status=='Failed' else 'Check Sent Items before retrying.')
        except Exception:
            status,error='Needs review','Delivery is unconfirmed. Check Sent Items before retrying.'
        else:
            status,error='Sent',None
        with factory() as db:
            db.execute(update(QuoteHandoffNotice).where(QuoteHandoffNotice.quote_id==key,
                QuoteHandoffNotice.status=='Sending').values(status=status,error=error,sent_at=now if status=='Sent' else None))
            db.commit()


def summary(db):
    rows=db.scalars(select(QuoteHandoffNotice).where(QuoteHandoffNotice.status.not_in(['Watching','Baselined'])).order_by(QuoteHandoffNotice.queued_at.desc()).limit(20)).all()
    return {'monitoring':db.get(IntegrationSyncState,BASELINE_KEY) is not None,'submit_url':SUBMIT_URL,
        'notices':[{'quote_id':r.quote_id,'status':r.status,'recipient':r.recipient,'customer_name':r.customer_name,
            'quote_name':r.quote_name,'error':r.error,'sent_at':r.sent_at.isoformat()+'Z' if r.sent_at else None} for r in rows]}
