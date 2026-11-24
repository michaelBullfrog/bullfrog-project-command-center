"""Small, concurrent-safe stage changes for the timeline and stage board."""
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from fastapi import HTTPException
from models import Project

class StageMove(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    stage: str=Field(min_length=1,max_length=60)
    expected_stage: str=Field(min_length=1,max_length=60)


def move_project_stage(db,project_id,payload,request,allowed_stages,record_activity):
    if payload.stage not in allowed_stages:
        raise HTTPException(422,'Choose a valid project stage.')
    project=db.scalar(select(Project).where(Project.id==project_id).with_for_update())
    if not project:raise HTTPException(404,'Project not found')
    if project.stage==payload.stage:return project
    if project.stage!=payload.expected_stage:
        raise HTTPException(409,'Another update changed this project stage. Refresh the board and try again.')
    old=project.stage
    project.stage=payload.stage
    record_activity(db,project.id,request,'project_updated',f'Changed Stage from {old} to {payload.stage}',
        field_name='stage',old_value=old,new_value=payload.stage)
    db.commit()
    return project
