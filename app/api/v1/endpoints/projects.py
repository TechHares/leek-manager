from typing import List, Optional
from enum import Enum
import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from app.api.deps import get_db_session, get_project_id
from app.db.session import db_connect
from app.models.project import Project
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User
from pydantic import BaseModel
from app.core.engine import engine_manager
from datetime import datetime

router = APIRouter()

# Schemas
class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class ProjectResponse(ProjectBase):
    id: int
    created_at: datetime
    updated_at: datetime
    created_by: int
    is_enabled: bool
    
    class Config:
        from_attributes = True

class EngineAction(str, Enum):
    START = "start"
    STOP = "stop"
    RESTART = "restart"

class EngineActionRequest(BaseModel):
    action: EngineAction

# Endpoints
@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """获取所有项目列表，按创建时间倒序"""
    return db.query(Project).filter(Project.is_deleted == False).order_by(Project.created_at.desc()).all()

@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_data: ProjectCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """创建新项目"""
    project = Project(
        name=project_data.name,
        description=project_data.description,
        created_by=current_user.id
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project



@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """删除项目"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在"
        )
    
    if project.created_by != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有项目创建者或管理员可以删除项目"
        )
    
    project.is_deleted = True
    db.commit()

@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    project_data: ProjectUpdate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """更新项目信息"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在"
        )
    
    if project.created_by != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有项目创建者或管理员可以修改项目"
        )
    
    # 只更新 name 和 description
    if project_data.name is not None:
        project.name = project_data.name
    if project_data.description is not None:
        project.description = project_data.description
    
    db.commit()
    db.refresh(project)
    return project


@router.post("/engines")
async def control_engine(
    request: EngineActionRequest,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """引擎控制接口，返回 SSE 流"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 提前获取需要的数据，避免生成器内 session 已关闭
    project_name = project.name
    
    def update_project_status(enabled: bool):
        """在新的 session 中更新项目状态"""
        with db_connect() as session:
            proj = session.query(Project).filter(Project.id == project_id).first()
            if proj:
                proj.is_enabled = enabled
                session.commit()
    
    async def event_stream():
        try:
            if request.action == EngineAction.START:
                yield {"data": json.dumps({"status": "running", "message": "正在启动引擎..."})}
                await engine_manager.add_client(str(project_id), project_name)
                update_project_status(True)
                yield {"data": json.dumps({"status": "completed", "message": "引擎启动成功"})}
                
            elif request.action == EngineAction.STOP:
                yield {"data": json.dumps({"status": "running", "message": "正在停止引擎..."})}
                await engine_manager.remove_client(str(project_id))
                update_project_status(False)
                yield {"data": json.dumps({"status": "completed", "message": "引擎停止成功"})}
                
            elif request.action == EngineAction.RESTART:
                yield {"data": json.dumps({"status": "running", "message": "正在停止引擎..."})}
                await engine_manager.remove_client(str(project_id))
                yield {"data": json.dumps({"status": "running", "message": "正在启动引擎..."})}
                await engine_manager.add_client(str(project_id), project_name)
                update_project_status(True)
                yield {"data": json.dumps({"status": "completed", "message": "引擎重启成功"})}
                
        except Exception as e:
            yield {"data": json.dumps({"status": "failed", "message": str(e)})}
    
    return EventSourceResponse(event_stream())