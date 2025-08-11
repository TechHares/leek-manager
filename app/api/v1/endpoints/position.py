from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, cast, Boolean
from datetime import datetime
from app.api.deps import get_db_session
from app.models.project_config import ProjectConfig
from app.models.position import Position
from app.api.deps import get_project_id
from app.schemas.position import (
    PositionSettingCreate, 
    PositionSettingOut,
    PositionOut,
    PositionUpdate,
    PositionFilter
)
from app.core.template_manager import leek_template_manager
from app.schemas.template import TemplateResponse
from app.schemas.common import PageResponse
from app.core.engine import engine_manager
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/positions", response_model=PageResponse[PositionOut])
async def list_positions(
    filters: PositionFilter = Depends(),
    page: int = 1,
    size: int = 20,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db_session)
):
    """
    List positions with filters and pagination
    """
    query = db.query(Position)
    query = query.filter(Position.project_id == project_id)
    if filters.is_closed is not None:
        query = query.filter(cast(Position.is_closed, Boolean) == filters.is_closed)
    if filters.strategy_id is not None:
        query = query.filter(Position.strategy_id == filters.strategy_id)
    if filters.strategy_instance_id is not None:
        query = query.filter(Position.strategy_instance_id == filters.strategy_instance_id)
    if filters.symbol is not None:
        query = query.filter(Position.symbol == filters.symbol)
    if filters.is_fake is not None:
        query = query.filter(cast(Position.is_fake, Boolean) == filters.is_fake)
    if filters.ins_type is not None:
        query = query.filter(Position.ins_type == filters.ins_type)
    if filters.asset_type is not None:
        query = query.filter(Position.asset_type == filters.asset_type)
    
    total = query.count()
    items = query.order_by(Position.open_time.desc(), Position.id.desc()).offset((page - 1) * size).limit(size).all()
    return PageResponse(total=total, page=page, size=size, items=items)

@router.get("/positions/{position_id}", response_model=PositionOut)
async def get_position(
    position_id: int,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db_session)
):
    """
    Get position details
    """
    position = db.query(Position).filter(Position.id == position_id, Position.project_id == project_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    return position

@router.patch("/positions/{position_id}", response_model=PositionOut)
async def update_position(
    position_id: int,
    position_update: PositionUpdate,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db_session)
):
    """
    Update position information
    """
    position = db.query(Position).filter(Position.id == position_id, Position.project_id == project_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    
    update_data = position_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(position, field, value)
    
    db.commit()
    db.refresh(position)
    return position

@router.post("/positions/{position_id}/close", response_model=PositionOut)
async def close_position(
    position_id: int,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db_session)
):
    """
    Close a position
    """
    position = db.query(Position).filter(Position.id == position_id, Position.project_id == project_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    
    if position.is_closed:
        raise HTTPException(status_code=400, detail="Position is already closed")
    client = engine_manager.get_client(project_id=project_id)
    if not client or not await client.invoke("close_position", position_id=str(position.id)):
        position.is_closed = True
        position.close_time = datetime.now()
        db.commit()
        db.refresh(position)
    return position

@router.get("/position/setting", response_model=PositionSettingOut)
async def get_position_setting(
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db_session)
):
    config = db.query(ProjectConfig).filter_by(project_id=project_id).first()
    if not config:
        config = ProjectConfig(project_id=project_id)
        db.add(config)
        db.commit()
        db.refresh(config)
    if not config.position_setting:
        return PositionSettingOut(positiondata=config.position_data)
    return PositionSettingOut(**config.position_setting, positiondata=config.position_data)

@router.put("/position/setting", response_model=PositionSettingOut)
async def save_position_setting(
    data: PositionSettingCreate,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db_session)
):
    config = db.query(ProjectConfig).filter_by(project_id=project_id).first()
    if not config:
        config = ProjectConfig(project_id=project_id)
        db.add(config)
    config.position_setting = data.model_dump()
    db.commit()
    db.refresh(config)
    client = engine_manager.get_client(project_id=project_id)
    if client:
        await client.update_position_config(data.model_dump(), None)
    return PositionSettingOut(**config.position_setting, positiondata=config.position_data)

@router.get("/templates/policy", response_model=List[TemplateResponse])
async def list_policy_templates(
    project_id: int = Depends(get_project_id)
):
    return await leek_template_manager.get_policies_templates(project_id) 
