from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_db_session
from app.models.project import Project
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User
from pydantic import BaseModel
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
    is_enabled: Optional[bool] = None

class ProjectResponse(ProjectBase):
    id: int
    created_at: datetime
    updated_at: datetime
    created_by: int
    is_enabled: bool
    
    class Config:
        from_attributes = True

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
async def update_project_status(
    project_id: int,
    project_data: ProjectUpdate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """更新项目状态"""
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
    
    # 只更新提供的字段
    if project_data.name is not None:
        project.name = project_data.name
    if project_data.description is not None:
        project.description = project_data.description
    if project_data.is_enabled is not None:
        project.is_enabled = project_data.is_enabled
    
    db.commit()
    db.refresh(project)
    return project 