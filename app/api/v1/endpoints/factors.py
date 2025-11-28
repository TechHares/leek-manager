from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict, List
from app.api import deps
from app.models.factor import Factor as FactorModel
from app.schemas.factor import (
    FactorConfigOut, FactorConfigCreate, FactorConfigUpdate
)
from app.schemas.template import TemplateResponse
from app.core.template_manager import leek_template_manager
from leek_core.base import load_class_from_str
from leek_core.base.util import create_component
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/factors", response_model=List[FactorConfigOut])
async def list_factors(
    db: Session = Depends(deps.get_db_session),
    page: int = 1,
    size: int = 100,
    project_id: int = Depends(deps.get_project_id),
    is_enabled: int = None,
    name: str = None,
    categories: str = None
):
    query = db.query(FactorModel)
    query = query.filter(FactorModel.project_id == project_id)
    query = query.filter(FactorModel.is_deleted == False)
    if is_enabled is not None:
        query = query.filter(FactorModel.is_enabled == is_enabled)
    if name:
        query = query.filter(FactorModel.name.like(f"%{name}%"))
    if categories:
        # categories 参数格式：逗号分隔的分类列表，如 "momentum,reversal"
        category_list = [c.strip() for c in categories.split(',') if c.strip()]
        if category_list:
            # JSON 字段查询：categories 数组中包含任一指定分类
            # 使用跨数据库兼容的方法
            from sqlalchemy import func, or_, cast, String
            
            # 检查数据库类型
            db_dialect = db.bind.dialect.name if hasattr(db, 'bind') else None
            
            conditions = []
            for cat in category_list:
                if db_dialect == 'mysql':
                    # MySQL: 使用 JSON_CONTAINS
                    conditions.append(func.json_contains(FactorModel.categories, f'"{cat}"'))
                else:
                    conditions.append(cast(FactorModel.categories, String).like(f'%"{cat}"%'))
            
            if conditions:
                query = query.filter(or_(*conditions))
    skip = (page - 1) * size
    factors = query.order_by(FactorModel.created_at.desc()).offset(skip).limit(size).all()
    return factors

@router.post("/factors", response_model=FactorConfigOut)
async def create_factor(
    factor: FactorConfigCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id)
):
    # 验证因子类并获取因子信息
    try:
        factor_cls = load_class_from_str(factor.class_name)
        # 获取因子元信息
        factor_count = getattr(factor_cls, 'factor_count', 1)
        
        # 创建因子实例以获取输出名称
        try:
            factor_instance = create_component(factor_cls, **(factor.params or {}))
            output_names = factor_instance.get_output_names()
        except Exception as e:
            logger.warning(f"Failed to create factor instance to get output names: {e}")
            output_names = None
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid factor class: {e}")
    
    data = factor.model_dump()
    data["project_id"] = project_id
    # 使用output_names的长度作为factor_count
    if output_names:
        data["factor_count"] = len(output_names)
    else:
        data["factor_count"] = factor_count
    data["output_names"] = output_names
    # 保留前端传来的categories，如果没有提供（None）则设置为空数组
    if data.get("categories") is None:
        data["categories"] = []
    factor_model = FactorModel(**data)
    factor_model.is_enabled = True
    db.add(factor_model)
    db.commit()
    db.refresh(factor_model)
    return factor_model

@router.get("/factors/{factor_id}", response_model=FactorConfigOut)
async def get_factor(
    factor_id: int,
    db: Session = Depends(deps.get_db_session)
):
    factor = db.query(FactorModel).filter(FactorModel.id == factor_id).first()
    if not factor:
        raise HTTPException(status_code=404, detail="Factor not found")
    return factor

@router.put("/factors/{factor_id}", response_model=FactorConfigOut)
async def update_factor(
    factor_id: int,
    factor_in: FactorConfigUpdate,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    factor = db.query(FactorModel).filter(
        FactorModel.id == factor_id, 
        FactorModel.project_id == project_id
    ).first()
    if not factor:
        raise HTTPException(status_code=404, detail="Factor not found")
    
    update_data = factor_in.model_dump(exclude_unset=True)
    
    # 如果更新了 class_name 或 params，需要重新验证
    if 'class_name' in update_data or 'params' in update_data:
        class_name = update_data.get('class_name', factor.class_name)
        params = update_data.get('params', factor.params)
        
        try:
            factor_cls = load_class_from_str(class_name)
            factor_instance = create_component(factor_cls, **(params or {}))
            output_names = factor_instance.get_output_names()
            # 使用output_names的长度作为factor_count
            if output_names:
                factor_count = len(output_names)
            else:
                factor_count = getattr(factor_cls, 'factor_count', 1)
            
            update_data['output_names'] = output_names
            update_data['factor_count'] = factor_count
            
            # 如果更新了 class_name 且没有指定 categories，重新推断分类
            if 'class_name' in update_data and 'categories' not in update_data:
                module_name = factor_cls.__module__
                inferred_class_name = factor_cls.__name__.lower()
                inferred_categories = []
                
                if 'time' in module_name or 'time' in inferred_class_name:
                    inferred_categories.append('time')
                if 'technical' in module_name or any(x in inferred_class_name for x in ['ma', 'rsi', 'atr', 'macd', 'boll']):
                    inferred_categories.append('technical')
                
                # 如果推断出分类，则更新；否则保持原有分类
                if inferred_categories:
                    update_data['categories'] = inferred_categories
        except Exception as e:
            logger.error(f"Failed to validate factor: {e}")
    
    for field, value in update_data.items():
        setattr(factor, field, value)
    
    db.commit()
    db.refresh(factor)
    return factor

@router.delete("/factors/{factor_id}")
async def delete_factor(
    factor_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    factor = db.query(FactorModel).filter(
        FactorModel.id == factor_id,
        FactorModel.project_id == project_id
    ).first()
    if not factor:
        raise HTTPException(status_code=404, detail="Factor not found")
    
    factor.is_deleted = True
    db.commit()
    return {"status": "success"}

@router.put("/factors/{factor_id}/enable", response_model=FactorConfigOut)
async def enable_factor(
    factor_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    factor = db.query(FactorModel).filter(
        FactorModel.id == factor_id,
        FactorModel.project_id == project_id
    ).first()
    if not factor:
        raise HTTPException(status_code=404, detail="Factor not found")
    
    factor.is_enabled = True
    db.commit()
    db.refresh(factor)
    return factor

@router.put("/factors/{factor_id}/disable", response_model=FactorConfigOut)
async def disable_factor(
    factor_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    factor = db.query(FactorModel).filter(
        FactorModel.id == factor_id,
        FactorModel.project_id == project_id
    ).first()
    if not factor:
        raise HTTPException(status_code=404, detail="Factor not found")
    
    factor.is_enabled = False
    db.commit()
    db.refresh(factor)
    return factor

@router.get("/templates/factor", response_model=List[TemplateResponse])
async def list_factor_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取因子模板列表
    """
    return await leek_template_manager.get_factor_by_project(project_id)

