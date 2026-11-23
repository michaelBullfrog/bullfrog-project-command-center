"""Resolve quote assignedTo (billing ID) through Rev PSA's user directory."""
import re
import httpx


def billing_id(value):
    if isinstance(value,bool):return None
    value=str(value or '').strip()
    return value if value.isascii() and value.isdigit() and int(value)>0 else None


def staff_email(value):
    value=str(value or '').strip().lower()
    return value if len(value)<=254 and re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@bullfrog\.net",value) else None


def user_rows(payload):
    if isinstance(payload,dict):payload=payload.get('data',payload)
    if isinstance(payload,dict):
        payload=next((payload[k] for k in ('items','records','users','results') if isinstance(payload.get(k),list)),None)
    return payload if isinstance(payload,list) else []


async def resolve_quote_assignees(records,request):
    wanted={billing_id(r.get('assigned_to')) for r in records}-{None}
    if not wanted:return records
    directory={}
    error=None
    try:
        payload=await request('GET','/billing/api/v1/users')
        for row in user_rows(payload):
            if not isinstance(row,dict):continue
            ident=billing_id(row.get('billingUserId'))
            if ident not in wanted:continue
            # Duplicate directory IDs are ambiguous, even if one row is active.
            if ident in directory:
                directory[ident]=None
                continue
            email=staff_email(row.get('emailAddress'))
            name=' '.join(str(row.get(k) or '').strip() for k in ('firstName','lastName')).strip()
            active=str(row.get('status') or '').strip().upper()=='ACTIVE'
            directory[ident]={'billing_user_id':ident,'name':name[:200], 'email':email,
                'job_title':str(row.get('jobTitle') or '')[:200]} if email and name and active else None
    except (httpx.HTTPError,RuntimeError,ValueError,TypeError):
        error='Rev PSA user directory lookup is unavailable.'
    for record in records:
        ident=billing_id(record.get('assigned_to'))
        if not ident:continue
        record['assigned_user']=directory.get(ident)
        record['assignee_error']=error or (None if directory.get(ident) else 'Assigned billing user could not be verified as an active Bullfrog staff member.')
    return records
