"""Displayed responsibility follows project and custom phase ownership."""
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import Project, Milestone, CustomProjectTemplate
import main

@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:yield s
    engine.dispose()

def test_owner_display_uses_phase_assignments_and_updates_with_project(db):
    p=Project(customer='Synthetic',project_name='Test',project_type='Webex Calling',technical_manager='Chad',engineer='Zach',sales_owner='Jack')
    p.milestones=[Milestone(name='Kickoff Call',phase_name='Planning & Handoff'),Milestone(name='Call Flow',phase_name='Design & Discovery'),Milestone(name='Additional task',phase_name='Additional')]
    db.add(p);db.commit()
    result=main.get_project(p.id,db)
    assert [(m.owner_name,m.owner_role) for m in result.milestones]==[('Chad','csm'),('Zach','engineer'),(None,None)]
    p.engineer='Michael';db.commit()
    assert main.get_project(p.id,db).milestones[1].owner_name=='Michael'

def test_custom_sales_phase_and_legacy_phase_fallback(db):
    template=CustomProjectTemplate(name='Synthetic Custom',phases_json=json.dumps([{'name':'Sales Review','owner_role':'sales','milestones':['Approved']}]))
    p=Project(customer='Synthetic',project_name='Test',project_type='Synthetic Custom',technical_manager='Ryan',sales_owner='Matt')
    p.milestones=[Milestone(name='Approved',phase_name=None)]
    db.add_all([template,p]);db.commit()
    result=main.get_project(p.id,db)
    assert result.milestones[0].owner_name=='Matt' and result.milestones[0].owner_role=='sales'
    p.sales_owner=None;db.commit()
    assert main.get_project(p.id,db).milestones[0].owner_name=='Ryan'
