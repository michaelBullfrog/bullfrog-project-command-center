"""Inbox filtering applies before database writes on notification/sync and webhook paths."""
import pytest
from fastapi import Response
from starlette.requests import Request
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from database import Base
from models import IntakeEmail
from schemas import IntakeEmailCreate
import main

@pytest.fixture
def db():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:yield session
    engine.dispose()

@pytest.mark.parametrize('subject,accepted',[
    ('New Project',True),('new project',True),(' NEW PROJECT ',True),
    ('RE: New Project',False),('FW: New Project',False),('New Project - Customer',False),
    ('Invoice',False),('',False),(None,False),('New  Project',False),
])
def test_graph_message_filter_and_deduplication(db,subject,accepted):
    message={'id':'synthetic-message','subject':subject,'from':{'emailAddress':{'address':'test@example.test'}}}
    assert main.store_graph_message(db,message) is accepted
    db.commit()
    assert db.scalar(select(func.count(IntakeEmail.id)))==int(accepted)
    if accepted:
        assert not main.store_graph_message(db,message)
        assert db.scalar(select(IntakeEmail)).subject==subject

@pytest.mark.parametrize('subject,accepted',[('New Project',True),(' new PROJECT ',True),('Invoice',False),('RE: New Project',False)])
def test_webhook_filter_after_authentication(db,monkeypatch,subject,accepted):
    monkeypatch.setenv('INTAKE_WEBHOOK_SECRET','synthetic-secret')
    payload=IntakeEmailCreate(message_id='synthetic-hook',subject=subject)
    def request(secret):return Request({'type':'http','headers':[(b'x-intake-secret',secret.encode())]})
    with pytest.raises(main.HTTPException) as denied:
        main.receive_intake_email(payload,request('wrong'),Response(),db)
    assert denied.value.status_code==401
    result=main.receive_intake_email(payload,request('synthetic-secret'),Response(),db)
    if accepted:assert result.status=='Pending'
    else:assert result.status_code==200 and b'subject_not_new_project' in result.body
    assert db.scalar(select(func.count(IntakeEmail.id)))==int(accepted)
