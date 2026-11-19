"""Sales submissions exercise the real Intake table with isolated synthetic data."""
import json
from uuid import uuid4
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from database import Base
from models import IntakeEmail, Project, ProjectWorkItem
from sales_intake import install_routes
from schemas import IntakeEmailOut


@pytest.fixture
def site(monkeypatch):
    monkeypatch.setenv('WEBEX_ALLOWED_DOMAIN','bullfrog.net')
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    def db_dep():
        with factory() as db: yield db
    def auth(request: Request):
        if request.headers.get('authorization')!='Bearer synthetic-service': raise HTTPException(401,'Unauthorized')
    calls=[]
    async def customer(customer_id):
        calls.append(customer_id)
        if customer_id=='404': raise HTTPException(404,'Not found')
        return {'customer_id':customer_id if customer_id!='999' else '888','customer_name':'Synthetic Customer','extra':'private upstream field'}
    def options(db): return {'project_types':['Webex Calling','Other'],'sales_owners':['Jack','Matt']}
    app=FastAPI();install_routes(app,auth,customer,options,db_dep)
    return TestClient(app),factory,calls


def payload():
    return {'submission_id':str(uuid4()),'submitter':{'name':'Synthetic Sales','email':'jack@bullfrog.net'},'details':{
        'customer_id':'1005','project_name':'Synthetic deployment','project_type':'Webex Calling','request_type':'Sold project','sales_owner':'Jack',
        'scope':'Deploy calling for the synthetic office <10 users>.','contact_name':'Synthetic Contact','contact_email':'contact@example.test',
        'requested_go_live':None,'go_live_unknown':True,'quote_reference':'Q-123','supporting_links':['https://files.example.test/statement']}}


AUTH={'Authorization':'Bearer synthetic-service'}
BASE='/api/mcp/sales-intake'


def test_auth_required_for_every_service_route(site):
    client,_,calls=site
    for path in ['/options','/customers/1005','/submissions?email=jack@bullfrog.net']:
        assert client.get(BASE+path).status_code==401
    assert client.post(BASE,json=payload()).status_code==401
    assert not calls


def test_sales_creates_one_pending_intake_and_no_project_or_work(site):
    client,factory,calls=site
    body=payload();r=client.post(BASE,headers=AUTH,json=body)
    assert r.status_code==200 and r.json()['status']=='Pending'
    assert r.json()['reference'].startswith('PCC-INTAKE-') and r.json()['project_id'] is None
    assert r.json()['submission_id']==body['submission_id']
    with factory() as db:
        item=db.scalar(select(IntakeEmail))
        assert item.source_type=='Sales Portal' and item.sender_email=='jack@bullfrog.net'
        assert item.customer_name=='Synthetic Customer' and item.quote_id=='Q-123'
        assert item.sales_details['project_type']=='Webex Calling'
        assert '&lt;10 users&gt;' in item.body
        assert IntakeEmailOut.model_validate(item).sales_details['contact_email']=='contact@example.test'
        assert db.scalar(select(func.count()).select_from(Project))==0
        assert db.scalar(select(func.count()).select_from(ProjectWorkItem))==0
    duplicate=client.post(BASE,headers=AUTH,json=body)
    assert duplicate.json()['intake_id']==r.json()['intake_id']
    assert calls==['1005']
    with factory() as db: assert db.scalar(select(func.count()).select_from(IntakeEmail))==1
    body['details']['scope']='Changed scope after a saved submission'
    assert client.post(BASE,headers=AUTH,json=body).status_code==409


def test_my_submissions_filters_submitter_and_returns_review_status(site):
    client,factory,_=site
    body=payload();first=client.post(BASE,headers=AUTH,json=body).json()
    other=payload();other['submitter']['email']='matthew@bullfrog.net';client.post(BASE,headers=AUTH,json=other)
    with factory() as db:
        item=db.get(IntakeEmail,first['intake_id']);item.status='Dismissed';db.commit()
    result=client.get(BASE+'/submissions?email=jack@bullfrog.net',headers=AUTH).json()
    assert len(result['submissions'])==1 and result['submissions'][0]['status']=='Dismissed'
    assert 'body' not in result['submissions'][0] and 'details' not in result['submissions'][0]
    # A delayed retry never creates a fresh request after review.
    assert client.post(BASE,headers=AUTH,json=body).json()['status']=='Dismissed'


@pytest.mark.parametrize('change',[
    {'scope':' '},{'sales_owner':'Unknown'},{'project_type':'Deleted type'},{'quote_reference':''},
    {'go_live_unknown':False},{'go_live_unknown':'true'},{'requested_go_live':'2026-12-01'},
    {'supporting_links':['javascript:alert(1)']},{'supporting_links':['https://user:secret@example.test']},
    {'contact_email':'bad'},{'customer_id':'x'},{'status':'Converted'}])
def test_invalid_or_incomplete_details_do_not_write_intake(site,change):
    client,factory,_=site;body=payload();body['details'].update(change)
    assert client.post(BASE,headers=AUTH,json=body).status_code==422
    with factory() as db: assert db.scalar(select(func.count()).select_from(IntakeEmail))==0


def test_trial_unknown_date_missing_customer_and_customer_identity_validation(site):
    client,factory,_=site
    trial=payload();trial['details'].update(request_type='Trial',quote_reference='')
    assert client.post(BASE,headers=AUTH,json=trial).status_code==200
    for cid,code in [('404',404),('999',502)]:
        body=payload();body['details']['customer_id']=cid
        assert client.post(BASE,headers=AUTH,json=body).status_code==code
    customer=client.get(BASE+'/customers/1005',headers=AUTH).json()
    assert customer=={'ok':True,'customer_id':'1005','customer_name':'Synthetic Customer'}
    assert client.get(BASE+'/customers/abc',headers=AUTH).status_code==400
    body=payload();body['submitter']['email']='sales@outside.test'
    assert client.post(BASE,headers=AUTH,json=body).status_code==403
    assert client.post(BASE,headers=AUTH,content='x'*40001).status_code==413


def test_existing_review_conversion_remains_the_only_project_creation_step(site):
    import main
    from schemas import IntakeConvert,ProjectCreate
    client,factory,_=site
    created=client.post(BASE,headers=AUTH,json=payload()).json()
    with factory() as db:
        request=Request({'type':'http','method':'POST','path':'/review','headers':[], 'session':{'user':{'name':'Reviewer','email':'reviewer@bullfrog.net'}}})
        result=main.convert_intake(created['intake_id'],IntakeConvert(project=ProjectCreate(customer='Synthetic Customer',customer_id='1005',project_name='Reviewed project',project_type='Other')),request,db)
        assert result.id and db.get(IntakeEmail,created['intake_id']).status=='Converted'
        assert db.scalar(select(func.count()).select_from(Project))==1
