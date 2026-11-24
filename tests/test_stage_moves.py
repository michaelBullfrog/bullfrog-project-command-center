from datetime import date
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from database import Base
from models import Project, ProjectActivity, Milestone
from stage_moves import StageMove
import main

@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        p=Project(customer='Synthetic',project_name='Timeline test',project_type='Other',stage='Intake',start_date=date(2026,11,1),target_date=date(2026,12,1),risk='Yellow')
        p.milestones=[Milestone(name='Testing',status='Not Started')]
        s.add(p);s.commit();yield s,p.id
    engine.dispose()

def req():return Request({'type':'http','method':'PATCH','path':'/test','headers':[], 'session':{'user':{'name':'Synthetic Staff','email':'staff@bullfrog.net'}}})

def test_move_saves_stage_and_actor_without_altering_dates_or_milestones(db):
    s,ident=db
    result=main.change_project_stage(ident,StageMove(stage='Implementation',expected_stage='Intake'),req(),s)
    assert result.stage=='Implementation'
    assert result.start_date==date(2026,11,1) and result.target_date==date(2026,12,1) and result.risk=='Yellow'
    assert result.milestones[0].status=='Not Started'
    activity=s.scalar(select(ProjectActivity))
    assert activity.field_name=='stage' and activity.old_value=='Intake' and activity.new_value=='Implementation'
    assert activity.actor_email=='staff@bullfrog.net'
    main.change_project_stage(ident,StageMove(stage='Implementation',expected_stage='Intake'),req(),s)
    assert s.scalar(select(func.count(ProjectActivity.id)))==1


def test_stale_board_move_is_rejected(db):
    s,ident=db
    main.change_project_stage(ident,StageMove(stage='Testing',expected_stage='Intake'),req(),s)
    with pytest.raises(HTTPException) as exc:
        main.change_project_stage(ident,StageMove(stage='Complete',expected_stage='Intake'),req(),s)
    assert exc.value.status_code==409 and s.get(Project,ident).stage=='Testing'
    assert s.scalar(select(func.count(ProjectActivity.id)))==1


def test_invalid_stage_unknown_project_and_date_overwrite_rejected(db):
    s,ident=db
    with pytest.raises(HTTPException) as exc:main.change_project_stage(ident,StageMove(stage='Fake',expected_stage='Intake'),req(),s)
    assert exc.value.status_code==422
    with pytest.raises(HTTPException) as exc:main.change_project_stage(99999,StageMove(stage='Testing',expected_stage='Intake'),req(),s)
    assert exc.value.status_code==404
    with pytest.raises(ValidationError):StageMove(stage='Testing',expected_stage='Intake',target_date='2027-01-01')
    assert s.get(Project,ident).stage=='Intake'


def test_completed_project_can_be_reopened(db):
    s,ident=db
    main.change_project_stage(ident,StageMove(stage='Complete',expected_stage='Intake'),req(),s)
    result=main.change_project_stage(ident,StageMove(stage='Testing',expected_stage='Complete'),req(),s)
    assert result.stage=='Testing' and len(result.activities)==2


def test_stage_route_requires_staff_sign_in(monkeypatch):
    monkeypatch.setattr(main,'webex_oauth_configured',lambda:True)
    client=TestClient(main.app)
    assert client.patch('/api/projects/1/stage',json={'stage':'Testing','expected_stage':'Intake'}).status_code==401
