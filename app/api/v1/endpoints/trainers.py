from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict, List
from app.api import deps
from app.models.trainer import Trainer as TrainerModel
from app.schemas.trainer import (
    TrainerConfigOut, TrainerConfigCreate, TrainerConfigUpdate
)
from app.schemas.template import TemplateResponse
from app.core.template_manager import leek_template_manager
from leek_core.base import load_class_from_str
from leek_core.base.util import create_component
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/trainers", response_model=List[TrainerConfigOut])
async def list_trainers(
    db: Session = Depends(deps.get_db_session),
    page: int = 1,
    size: int = 100,
    project_id: int = Depends(deps.get_project_id),
    is_enabled: int = None,
    name: str = None
):
    query = db.query(TrainerModel)
    query = query.filter(TrainerModel.project_id == project_id)
    query = query.filter(TrainerModel.is_deleted == False)
    if is_enabled is not None:
        query = query.filter(TrainerModel.is_enabled == is_enabled)
    if name:
        query = query.filter(TrainerModel.name.like(f"%{name}%"))
    skip = (page - 1) * size
    trainers = query.order_by(TrainerModel.created_at.desc()).offset(skip).limit(size).all()
    return trainers

@router.post("/trainers", response_model=TrainerConfigOut)
async def create_trainer(
    trainer: TrainerConfigCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id)
):
    # 验证训练器类
    try:
        trainer_cls = load_class_from_str(trainer.class_name)
        # 尝试创建实例以验证参数
        try:
            create_component(trainer_cls, **(trainer.params or {}))
        except Exception as e:
            logger.warning(f"Failed to create trainer instance: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid trainer class: {e}")
    
    data = trainer.model_dump()
    data["project_id"] = project_id
    trainer_model = TrainerModel(**data)
    trainer_model.is_enabled = True
    db.add(trainer_model)
    db.commit()
    db.refresh(trainer_model)
    return trainer_model

@router.get("/trainers/{trainer_id}", response_model=TrainerConfigOut)
async def get_trainer(
    trainer_id: int,
    db: Session = Depends(deps.get_db_session)
):
    trainer = db.query(TrainerModel).filter(TrainerModel.id == trainer_id).first()
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    return trainer

@router.put("/trainers/{trainer_id}", response_model=TrainerConfigOut)
async def update_trainer(
    trainer_id: int,
    trainer_in: TrainerConfigUpdate,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    trainer = db.query(TrainerModel).filter(
        TrainerModel.id == trainer_id, 
        TrainerModel.project_id == project_id
    ).first()
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    
    update_data = trainer_in.model_dump(exclude_unset=True)
    
    # 如果更新了 class_name 或 params，需要重新验证
    if 'class_name' in update_data or 'params' in update_data:
        class_name = update_data.get('class_name', trainer.class_name)
        params = update_data.get('params', trainer.params)
        
        try:
            trainer_cls = load_class_from_str(class_name)
            create_component(trainer_cls, **(params or {}))
        except Exception as e:
            logger.error(f"Failed to validate trainer: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid trainer configuration: {e}")
    
    for field, value in update_data.items():
        setattr(trainer, field, value)
    
    db.commit()
    db.refresh(trainer)
    return trainer

@router.delete("/trainers/{trainer_id}")
async def delete_trainer(
    trainer_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    trainer = db.query(TrainerModel).filter(
        TrainerModel.id == trainer_id,
        TrainerModel.project_id == project_id
    ).first()
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    
    trainer.is_deleted = True
    db.commit()
    return {"status": "success"}

@router.put("/trainers/{trainer_id}/enable", response_model=TrainerConfigOut)
async def enable_trainer(
    trainer_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    trainer = db.query(TrainerModel).filter(
        TrainerModel.id == trainer_id,
        TrainerModel.project_id == project_id
    ).first()
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    
    trainer.is_enabled = True
    db.commit()
    db.refresh(trainer)
    return trainer

@router.put("/trainers/{trainer_id}/disable", response_model=TrainerConfigOut)
async def disable_trainer(
    trainer_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    trainer = db.query(TrainerModel).filter(
        TrainerModel.id == trainer_id,
        TrainerModel.project_id == project_id
    ).first()
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    
    trainer.is_enabled = False
    db.commit()
    db.refresh(trainer)
    return trainer

@router.get("/templates/trainer", response_model=List[TemplateResponse])
async def list_trainer_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取训练器模板列表
    """
    return await leek_template_manager.get_trainer_by_project(project_id)

