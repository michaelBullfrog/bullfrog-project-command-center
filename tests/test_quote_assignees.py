from unittest.mock import AsyncMock
import httpx
import pytest
import main
from quote_assignees import resolve_quote_assignees
from quote_handoff import recipient_for, message_for

USER={'billingUserId':2136,'firstName':'Chad','lastName':'Pifer','emailAddress':'chad@bullfrog.net',
      'loginName':'chad@bullfrog.net','jobTitle':'Customer Success Manager','globalUserId':'01KKF7PVMWVPZR94AEQS16Y006','status':'ACTIVE'}
QUOTE={'quoteId':1421,'assignedTo':2136,'customerId':1996,'description':'','status':'Complete','approvalMethod':'Self','statusDate':'2026-11-23T18:37:46.05'}

@pytest.mark.asyncio
@pytest.mark.parametrize('wrap',[lambda x:x,lambda x:{'data':x},lambda x:{'data':{'items':x}}])
async def test_billing_id_is_resolved_to_chad_without_guessing_sales_role(wrap):
    r=main.normalize_revio_quote(QUOTE)
    request=AsyncMock(return_value=wrap([USER]))
    await resolve_quote_assignees([r],request)
    request.assert_awaited_once_with('GET','/billing/api/v1/users')
    assert r['assigned_user']['name']=='Chad Pifer' and r['assigned_to']=='2136'
    assert recipient_for(r)=='chad@bullfrog.net'
    assert r['sales_owner'] is None
    assert 'Chad Pifer' in message_for(r)[1]
    summary=main.revio_recent_quote_summaries([r])[0]
    assert summary['assignee_name']=='Chad Pifer'

@pytest.mark.asyncio
async def test_one_lookup_for_multiple_quotes():
    records=[main.normalize_revio_quote({**QUOTE,'quoteId':n}) for n in [1421,1422,1423]]
    request=AsyncMock(return_value=[USER])
    await resolve_quote_assignees(records,request)
    assert request.await_count==1
    assert all(recipient_for(r)=='chad@bullfrog.net' for r in records)

@pytest.mark.asyncio
@pytest.mark.parametrize('rows',[[{**USER,'status':'INACTIVE'}],[{**USER,'emailAddress':'chad@example.test'}],[{**USER,'billingUserId':9999}],[USER,USER],[]])
async def test_unverified_assignee_blocks_even_when_sales_owner_name_exists(rows):
    r=main.normalize_revio_quote({**QUOTE,'salesOwnerName':'Jack Harris'})
    await resolve_quote_assignees([r],AsyncMock(return_value=rows))
    assert recipient_for(r) is None and r['assignee_error']

@pytest.mark.asyncio
async def test_directory_failure_is_blocked_without_exposing_error():
    r=main.normalize_revio_quote(QUOTE)
    await resolve_quote_assignees([r],AsyncMock(side_effect=httpx.ReadTimeout('secret')))
    assert recipient_for(r) is None and 'secret' not in r['assignee_error']

@pytest.mark.asyncio
async def test_enrichment_uses_existing_lookup_and_keeps_assigned_to_when_detail_omits_it(monkeypatch):
    r=main.normalize_revio_quote(QUOTE)
    await resolve_quote_assignees([r],AsyncMock(return_value=[USER]))
    request=AsyncMock(return_value={'data':{'quoteId':1421,'status':'Complete','description':'Calling','customerId':1996,'customerName':'Synthetic'}})
    monkeypatch.setattr(main,'revio_psa_api_request',request)
    result=await main.enrich_revio_quote(r)
    assert recipient_for(result)=='chad@bullfrog.net'
    assert request.await_count==1

@pytest.mark.asyncio
async def test_enrichment_does_not_reuse_old_assignee_when_assignment_is_removed(monkeypatch):
    r=main.normalize_revio_quote(QUOTE)
    await resolve_quote_assignees([r],AsyncMock(return_value=[USER]))
    request=AsyncMock(return_value={'data':{'quoteId':1421,'assignedTo':0,'status':'Complete','description':'Calling','customerId':1996,'customerName':'Synthetic'}})
    monkeypatch.setattr(main,'revio_psa_api_request',request)
    result=await main.enrich_revio_quote(r)
    assert recipient_for(result) is None
