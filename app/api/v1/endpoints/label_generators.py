from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict, List
from app.api import deps
from app.models.label_generator import LabelGenerator as LabelGeneratorModel
from app.schemas.label_generator import (
    LabelGeneratorConfigOut, LabelGeneratorConfigCreate, LabelGeneratorConfigUpdate
)
from app.schemas.template import TemplateResponse
from app.core.template_manager import leek_template_manager
from leek_core.base import load_class_from_str
from leek_core.base.util import create_component
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/label_generators", response_model=List[LabelGeneratorConfigOut])
async def list_label_generators(
    db: Session = Depends(deps.get_db_session),
    page: int = 1,
    size: int = 100,
    project_id: int = Depends(deps.get_project_id),
    is_enabled: int = None,
    name: str = None
):
    query = db.query(LabelGeneratorModel)
    query = query.filter(LabelGeneratorModel.project_id == project_id)
    query = query.filter(LabelGeneratorModel.is_deleted == False)
    if is_enabled is not None:
        query = query.filter(LabelGeneratorModel.is_enabled == is_enabled)
    if name:
        query = query.filter(LabelGeneratorModel.name.like(f"%{name}%"))
    skip = (page - 1) * size
    label_generators = query.order_by(LabelGeneratorModel.created_at.desc()).offset(skip).limit(size).all()
    return label_generators

@router.post("/label_generators", response_model=LabelGeneratorConfigOut)
async def create_label_generator(
    label_generator: LabelGeneratorConfigCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id)
):
    # 验证标签生成器类
    try:
        label_generator_cls = load_class_from_str(label_generator.class_name)
        # 尝试创建实例以验证参数
        try:
            create_component(label_generator_cls, **(label_generator.params or {}))
        except Exception as e:
            logger.warning(f"Failed to create label generator instance: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid label generator class: {e}")
    
    data = label_generator.model_dump()
    data["project_id"] = project_id
    label_generator_model = LabelGeneratorModel(**data)
    label_generator_model.is_enabled = True
    db.add(label_generator_model)
    db.commit()
    db.refresh(label_generator_model)
    return label_generator_model

@router.get("/label_generators/{label_generator_id}", response_model=LabelGeneratorConfigOut)
async def get_label_generator(
    label_generator_id: int,
    db: Session = Depends(deps.get_db_session)
):
    label_generator = db.query(LabelGeneratorModel).filter(LabelGeneratorModel.id == label_generator_id).first()
    if not label_generator:
        raise HTTPException(status_code=404, detail="Label generator not found")
    return label_generator

@router.put("/label_generators/{label_generator_id}", response_model=LabelGeneratorConfigOut)
async def update_label_generator(
    label_generator_id: int,
    label_generator_in: LabelGeneratorConfigUpdate,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    label_generator = db.query(LabelGeneratorModel).filter(
        LabelGeneratorModel.id == label_generator_id, 
        LabelGeneratorModel.project_id == project_id
    ).first()
    if not label_generator:
        raise HTTPException(status_code=404, detail="Label generator not found")
    
    update_data = label_generator_in.model_dump(exclude_unset=True)
    
    # 如果更新了 class_name 或 params，需要重新验证
    if 'class_name' in update_data or 'params' in update_data:
        class_name = update_data.get('class_name', label_generator.class_name)
        params = update_data.get('params', label_generator.params)
        
        try:
            label_generator_cls = load_class_from_str(class_name)
            create_component(label_generator_cls, **(params or {}))
        except Exception as e:
            logger.error(f"Failed to validate label generator: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid label generator configuration: {e}")
    
    for field, value in update_data.items():
        setattr(label_generator, field, value)
    
    db.commit()
    db.refresh(label_generator)
    return label_generator

@router.delete("/label_generators/{label_generator_id}")
async def delete_label_generator(
    label_generator_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    label_generator = db.query(LabelGeneratorModel).filter(
        LabelGeneratorModel.id == label_generator_id,
        LabelGeneratorModel.project_id == project_id
    ).first()
    if not label_generator:
        raise HTTPException(status_code=404, detail="Label generator not found")
    
    label_generator.is_deleted = True
    db.commit()
    return {"status": "success"}

@router.put("/label_generators/{label_generator_id}/enable", response_model=LabelGeneratorConfigOut)
async def enable_label_generator(
    label_generator_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    label_generator = db.query(LabelGeneratorModel).filter(
        LabelGeneratorModel.id == label_generator_id,
        LabelGeneratorModel.project_id == project_id
    ).first()
    if not label_generator:
        raise HTTPException(status_code=404, detail="Label generator not found")
    
    label_generator.is_enabled = True
    db.commit()
    db.refresh(label_generator)
    return label_generator

@router.put("/label_generators/{label_generator_id}/disable", response_model=LabelGeneratorConfigOut)
async def disable_label_generator(
    label_generator_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    label_generator = db.query(LabelGeneratorModel).filter(
        LabelGeneratorModel.id == label_generator_id,
        LabelGeneratorModel.project_id == project_id
    ).first()
    if not label_generator:
        raise HTTPException(status_code=404, detail="Label generator not found")
    
    label_generator.is_enabled = False
    db.commit()
    db.refresh(label_generator)
    return label_generator

@router.get("/templates/label_generator", response_model=List[TemplateResponse])
async def list_label_generator_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取标签生成器模板列表
    """
    return await leek_template_manager.get_label_generator_by_project(project_id)

