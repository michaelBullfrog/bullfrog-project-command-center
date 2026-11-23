"""Approval transitions and durable email claims use synthetic records and a fake sender."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
import pytest
import httpx
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from database import Base
from models import QuoteHandoffNotice, Project, IntakeEmail
from quote_handoff import observe_quotes, dispatch_pending, recipient_for, message_for, summary

NOW=datetime(2026,11,23,15)

@pytest.fixture
def factory():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def record(ident='2000',approved=False,owner='Jack Harris',date=None):
    return dict(quote_id=ident,is_approved=approved,status_name='Approved' if approved else 'Open',
        approved_at=date,customer_id='1005',customer_name='<Synthetic Customer>',quote_name='Calling',sales_owner='Jack',
        amount='5500.00',raw={'salesOwnerName':owner})

async def enrich(value):return value

@pytest.mark.asyncio
async def test_baselines_history_then_sends_one_prompt_per_quote(factory):
    old=record('1999',True)
    current=record()
    await observe_quotes(factory,[old,current],enrich,now=NOW)
    send=AsyncMock()
    await dispatch_pending(factory,send,now=NOW)
    send.assert_not_awaited()
    current['is_approved']=True
    await observe_quotes(factory,[old,current],enrich,now=NOW+timedelta(minutes=5))
    await dispatch_pending(factory,send,now=NOW+timedelta(minutes=5))
    assert send.await_count==1 and send.await_args.args[0]=='jack@bullfrog.net'
    subject,body=send.await_args.args[1:]
    assert '2000' in subject and 'https://mcp.bullfrog.net/submit-project' in body
    assert '&lt;Synthetic Customer&gt;' in body and '<Synthetic Customer>' not in body
    for approved in [True,False,True]:
        current['is_approved']=approved
        await observe_quotes(factory,[current],enrich,now=NOW+timedelta(minutes=10))
        await dispatch_pending(factory,send,now=NOW+timedelta(minutes=10))
    assert send.await_count==1
    with factory() as db:
        assert db.get(QuoteHandoffNotice,'2000').status=='Sent'
        assert db.scalar(select(func.count(Project.id)))==0
        assert db.scalar(select(func.count(IntakeEmail.id)))==0

@pytest.mark.asyncio
async def test_new_approved_quote_after_baseline_but_historical_pages_do_not_send(factory):
    await observe_quotes(factory,[record()],enrich,now=NOW)
    await observe_quotes(factory,[record('2001',True),record('1990',True),record('1991',True,date=NOW-timedelta(days=2))],enrich,now=NOW+timedelta(minutes=5))
    send=AsyncMock();await dispatch_pending(factory,send)
    assert send.await_count==1 and '2001' in send.await_args.args[1]

@pytest.mark.parametrize('owner,expected',[('Jack Harris','jack@bullfrog.net'),('Matthew Petrusha','matthew@bullfrog.net'),('Matt','matthew@bullfrog.net'),('Jamie Jackson',None),('Jack Someone Else',None),('',None)])
def test_recipient_mapping_is_exact(owner,expected):
    r=record(owner=owner)
    if not owner:r['sales_owner']=None
    assert recipient_for(r)==expected


def test_unknown_email_or_conflicting_owner_is_not_guessed():
    r=record();r['raw']['salesOwnerEmail']='someone@example.test'
    assert recipient_for(r) is None
    r=record();r['raw']['assignee']={'displayName':'Matthew Petrusha'}
    assert recipient_for(r) is None

@pytest.mark.asyncio
async def test_missing_owner_is_blocked_then_recovers_when_owner_is_known(factory):
    r=record();r['sales_owner']=None;r['raw']={}
    await observe_quotes(factory,[r],enrich,now=NOW)
    r['is_approved']=True
    await observe_quotes(factory,[r],enrich,now=NOW)
    send=AsyncMock();await dispatch_pending(factory,send)
    send.assert_not_awaited()
    with factory() as db:assert summary(db)['notices'][0]['status']=='Blocked'
    r['raw']={'salesRep':{'displayName':'Matthew Petrusha'}}
    await observe_quotes(factory,[r],enrich,now=NOW)
    await dispatch_pending(factory,send)
    assert send.await_args.args[0]=='matthew@bullfrog.net'

@pytest.mark.asyncio
async def test_timeout_does_not_automatically_resend(factory):
    await observe_quotes(factory,[record()],enrich,now=NOW)
    await observe_quotes(factory,[record(approved=True)],enrich,now=NOW)
    send=AsyncMock(side_effect=httpx.ReadTimeout('sensitive details'))
    await dispatch_pending(factory,send)
    await dispatch_pending(factory,send)
    assert send.await_count==1
    with factory() as db:
        item=db.get(QuoteHandoffNotice,'2000')
        assert item.status=='Needs review' and 'sensitive' not in item.error

@pytest.mark.asyncio
async def test_sender_config_and_interrupted_claim_prevent_blind_send(factory):
    await observe_quotes(factory,[record()],enrich,now=NOW)
    await observe_quotes(factory,[record(approved=True)],enrich,now=NOW)
    send=AsyncMock()
    await dispatch_pending(factory,send,configured=False)
    send.assert_not_awaited()
    with factory() as db:
        item=db.get(QuoteHandoffNotice,'2000');item.status='Sending';item.attempted_at=NOW;db.commit()
    await dispatch_pending(factory,send,now=NOW+timedelta(minutes=16))
    send.assert_not_awaited()
    with factory() as db:assert db.get(QuoteHandoffNotice,'2000').status=='Needs review'

@pytest.mark.asyncio
async def test_4xx_rejection_is_visible_and_not_automatically_retried(factory):
    await observe_quotes(factory,[record()],enrich,now=NOW)
    await observe_quotes(factory,[record(approved=True)],enrich,now=NOW)
    response=httpx.Response(403,request=httpx.Request('POST','https://graph.example/sendMail'))
    send=AsyncMock(side_effect=httpx.HTTPStatusError('secret',request=response.request,response=response))
    await dispatch_pending(factory,send)
    await dispatch_pending(factory,send)
    with factory() as db:assert db.get(QuoteHandoffNotice,'2000').status=='Failed'
    assert send.await_count==1

@pytest.mark.asyncio
async def test_exact_quote_check_cannot_accidentally_establish_baseline(factory):
    await observe_quotes(factory,[record(approved=True)],enrich,allow_baseline=False,now=NOW)
    with factory() as db:assert not summary(db)['monitoring'] and db.get(QuoteHandoffNotice,'2000') is None

@pytest.mark.asyncio
async def test_concurrent_dispatchers_only_claim_one_email(factory):
    import asyncio
    await observe_quotes(factory,[record()],enrich,now=NOW)
    await observe_quotes(factory,[record(approved=True)],enrich,now=NOW)
    async def send(*args):await asyncio.sleep(0)
    sender=AsyncMock(side_effect=send)
    await asyncio.gather(dispatch_pending(factory,sender),dispatch_pending(factory,sender))
    assert sender.await_count==1

@pytest.mark.asyncio
async def test_actual_quote_sync_queues_approval_without_creating_complete_intake(factory,monkeypatch):
    import main
    status={'name':'Open'}
    async def fetch():
        return [{'quoteId':'2500','status':status.copy(),'customerId':'1005','customerName':'Synthetic',
            'description':'Calling','salesOwnerName':'Jack Harris'}],1,1
    sender=AsyncMock()
    monkeypatch.setattr(main,'SessionLocal',factory)
    monkeypatch.setattr(main,'fetch_revio_quotes',fetch)
    monkeypatch.setattr(main,'revio_configured',lambda:True)
    monkeypatch.setattr(main,'graph_configured',lambda:True)
    monkeypatch.setattr(main,'graph_send_project_notification',sender)
    await main.sync_revio_quote_approvals()
    sender.assert_not_awaited()
    status['name']='Approved'
    result=await main.sync_revio_quote_approvals()
    assert result['imported']==0 and sender.await_count==1
    await main.sync_revio_quote_approvals()
    assert sender.await_count==1
    with factory() as db:assert db.scalar(select(func.count(IntakeEmail.id)))==0

def test_mail_status_and_retry_routes_require_staff_sign_in(monkeypatch):
    import main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main,'webex_oauth_configured',lambda:True)
    client=TestClient(main.app)
    assert client.get('/api/revio/quote-handoffs').status_code==401
    assert client.post('/api/revio/quote-handoffs/2500/retry').status_code==401

@pytest.mark.asyncio
async def test_staff_retry_cannot_resend_ambiguous_or_sent_email(factory,monkeypatch):
    import main
    from fastapi import HTTPException
    monkeypatch.setattr(main,'SessionLocal',factory)
    monkeypatch.setattr(main,'graph_configured',lambda:True)
    sender=AsyncMock();monkeypatch.setattr(main,'graph_send_project_notification',sender)
    with factory() as db:
        for idx,status in enumerate(['Sent','Needs review','Blocked','Failed']):
            db.add(QuoteHandoffNotice(quote_id=str(idx),status=status,recipient='jack@bullfrog.net',subject='Synthetic',body='Synthetic'))
        db.commit()
        for ident in ['0','1','2']:
            with pytest.raises(HTTPException) as exc:await main.retry_quote_handoff(ident,db)
            assert exc.value.status_code==409
        await main.retry_quote_handoff('3',db)
        assert sender.await_count==1 and db.get(QuoteHandoffNotice,'3').status=='Sent'


def test_normalized_owner_without_source_evidence_does_not_select_mailbox():
    r=record();r['raw']={}
    assert recipient_for(r) is None

@pytest.mark.asyncio
async def test_enrichment_cannot_turn_unknown_source_owner_into_guessed_recipient(factory):
    await observe_quotes(factory,[record(owner='Jack Unknown')],enrich,now=NOW)
    async def detail_without_owner(r):return {**r,'raw':{'quoteId':r['quote_id']}}
    await observe_quotes(factory,[record(approved=True,owner='Jack Unknown')],detail_without_owner,now=NOW)
    send=AsyncMock();await dispatch_pending(factory,send)
    send.assert_not_awaited()
    with factory() as db:assert db.get(QuoteHandoffNotice,'2000').status=='Blocked'
