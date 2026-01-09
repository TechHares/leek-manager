from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.api.deps import get_db_session
from app.models.project_config import ProjectConfig
from pydantic import BaseModel, Field
from typing import Any, Optional, List, Dict
from app.core.config_manager import config_manager, DatabaseConfig
from app.db.session import reset_connection
from app.core.template_manager import leek_template_manager
from app.schemas.template import TemplateResponse
from app.core.engine import engine_manager
from app.api import deps

router = APIRouter()

class AlarmConfig(BaseModel):
    class_name: str
    enabled: bool = True
    config: Dict[str, Any]

class ConfigResponse(BaseModel):
    business_db: Optional[dict]
    data_db: Optional[dict]
    is_configured: bool

class SaveConfigRequest(BaseModel):
    business_db: Optional[DatabaseConfig]
    data_db: DatabaseConfig
    admin: Optional[dict] = None

class ProjectConfigSchema(BaseModel):
    project_id: int

class ProjectConfigIn(BaseModel):
    log_level: str = "INFO"
    log_format: str = "json"
    log_alarm: bool = False
    alert_config: List[AlarmConfig] = Field(default_factory=list)
    mount_dirs: list = Field(default_factory=list)
    project_id: Optional[int] = None

class ProjectConfigOut(ProjectConfigIn):
    id: int

@router.get("/system/configurations", response_model=ConfigResponse)
async def get_config():
    """Get current database configuration."""
    return config_manager.get_config()

@router.put("/system/configurations", status_code=204)
async def update_config(config: SaveConfigRequest):
    """Update database configuration."""
    if not config.data_db:
        raise HTTPException(status_code=400, detail="Data database configuration is required")
    
    config_dict = {
        "is_configured": True,
        "business_db": config.business_db.model_dump() if config.business_db else None,
        "data_db": config.data_db.model_dump(),
        "admin": config.admin
    }
    
    try:
        config_manager.update_config(config_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save configuration: {str(e)}")
    
    # 重置数据库连接
    reset_connection()

@router.get("/config", response_model=ProjectConfigOut)
async def get_project_config(
    project_id: int = Header(..., description="项目ID"),
    db: Session = Depends(get_db_session)
):
    config = db.query(ProjectConfig).filter_by(project_id=project_id).first()
    if not config:
        # 没有则插入一条默认配置
        config = ProjectConfig(project_id=project_id)
        config.alert_config = []
        config.mount_dirs = ["default"]
        db.add(config)
        db.commit()
        db.refresh(config)
    return config

@router.put("/config", response_model=ProjectConfigOut)
async def save_project_config(
    data: ProjectConfigIn,
    project_id: int = Header(..., description="项目ID"),
    db: Session = Depends(get_db_session)
):
    # 用 project_id 覆盖 data.project_id
    data.project_id = project_id
    config = db.query(ProjectConfig).filter_by(project_id=data.project_id).first()
    if config:
        config.log_level = data.log_level
        config.log_format = data.log_format
        config.log_alarm = data.log_alarm
        config.alert_config = [item.model_dump() for item in data.alert_config]
        config.mount_dirs = data.mount_dirs
    else:
        config = ProjectConfig(**data.model_dump())
    db.commit()
    db.refresh(config)
    return config

@router.get("/templates/alarm", response_model=List[TemplateResponse])
async def list_alarm_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取告警模板列表
    """
    return await leek_template_manager.get_alarm_templates(project_id)

@router.patch("/config/mount_dirs")
async def refresh_mount_dirs(
    project_id: int = Header(..., description="项目ID"),
    db: Session = Depends(get_db_session)
):
    config = db.query(ProjectConfig).filter_by(project_id=project_id).first()
    await leek_template_manager.update_dirs(project_id, config.mount_dirs)

@router.post("/config/reset_position_state")
async def reset_position_state(
    project_id: int = Header(..., description="项目ID"),
    db: Session = Depends(get_db_session)
):
    client = engine_manager.get_client(project_id)
    if client:
        state = await client.invoke("reset_position_state")
        project_config = db.query(ProjectConfig).filter(ProjectConfig.project_id == int(project_id)).first()
        project_config.position_data = state
        db.commit()
    else:
        project_config = db.query(ProjectConfig).filter(ProjectConfig.project_id == int(project_id)).first()
        project_config.position_data = {}
        db.commit()
