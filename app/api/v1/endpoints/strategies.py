from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict, List
from app.api import deps
from app.models.strategy import Strategy as StrategyModel
from app.models.model import Model as ModelModel
from app.schemas.strategy import (
    StrategyConfigOut, StrategyConfigCreate, StrategyConfigUpdate
)
from app.schemas.template import TemplateResponse
from app.core.template_manager import leek_template_manager
from app.core.engine import engine_manager
from leek_core.utils import get_logger

logger = get_logger(__name__)
router = APIRouter()
@router.get("/strategies", response_model=List[StrategyConfigOut])
async def list_strategies(
    db: Session = Depends(deps.get_db_session),
    skip: int = 0,
    limit: int = 100,
    project_id: int = Depends(deps.get_project_id),
    is_enabled: int = None
):
    query = db.query(StrategyModel)
    query = query.filter(StrategyModel.project_id == project_id)
    if is_enabled is not None:
        query = query.filter(StrategyModel.is_enabled == is_enabled)
    strategies = query.order_by(StrategyModel.created_at.desc()).offset(skip).limit(limit).all()
    return strategies

@router.get("/strategies/instances")
async def list_strategy_instances(
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    """
    返回项目下各策略的实例列表（基于引擎上报的 runtime data）。
    结构: [{ strategy_id, strategy_name, instances: [instance_id,...] }]
    """
    rows = db.query(StrategyModel).filter(StrategyModel.project_id == project_id).all()
    result = []
    for s in rows:
        result.append({
            "strategy_id": s.id,
            "strategy_name": s.name,
        })
    return result

def _validate_model_config(params: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """验证 model_config，如果缺少 model_path 则补充（兼容旧数据）"""
    if not params or not isinstance(params, dict):
        return params
    
    model_config = params.get('model_config')
    if not model_config or not isinstance(model_config, dict):
        return params
    
    # 如果已经有 model_path，验证其有效性
    if 'model_path' in model_config and model_config['model_path']:
        # 验证文件是否存在（可选，如果文件不存在会在运行时报错）
        return params
    
    # 如果缺少 model_path，尝试从 model_id 补充（兼容旧数据或手动创建的情况）
    model_id = model_config.get('model_id')
    if model_id:
        model = db.query(ModelModel).filter(
            ModelModel.id == model_id,
            ModelModel.is_deleted == False
        ).first()
        if model:
            params['model_config']['model_path'] = model.file_path
            # 如果缺少 feature_config，从模型记录中补充
            if 'feature_config' not in params['model_config'] or not params['model_config']['feature_config']:
                if model.feature_config:
                    params['model_config']['feature_config'] = model.feature_config
                    logger.info(f"Model config missing feature_config, supplemented from model_id {model_id}")
            logger.warning(f"Model config missing model_path, supplemented from model_id {model_id}")
        else:
            raise HTTPException(status_code=404, detail=f"Model with id {model_id} not found")
    else:
        raise HTTPException(status_code=400, detail="model_config must contain either model_path or model_id")
    
    return params

@router.post("/strategies", response_model=StrategyConfigOut)
async def create_strategy(
    strategy: StrategyConfigCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id)
):
    data = strategy.model_dump()
    # 进出场子策略已移除
    data["info_fabricator_configs"] = data.pop("info_fabricator_configs", None)
    params = data.pop("params", None)
    
    # 验证并补充 model_path（如果缺失）
    if params:
        params = _validate_model_config(params, db)
    
    data["params"] = params
    data["project_id"] = project_id
    strategy_model = StrategyModel(**data)
    db.add(strategy_model)
    db.commit()
    db.refresh(strategy_model)
    if strategy_model.is_enabled:
        client = engine_manager.get_client(project_id=project_id)
        if client:
            await client.add_strategy(strategy_model.dumps_map())
    return strategy_model

@router.get("/strategies/{strategy_id}", response_model=StrategyConfigOut)
async def get_strategy(
    strategy_id: int,
    db: Session = Depends(deps.get_db_session)
):
    strategy = db.query(StrategyModel).filter(StrategyModel.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy

@router.put("/strategies/{strategy_id}", response_model=StrategyConfigOut)
async def update_strategy(
    strategy_id: int,
    strategy_in: StrategyConfigUpdate,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    strategy = db.query(StrategyModel).filter(StrategyModel.id == strategy_id, StrategyModel.project_id == project_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    update_data = strategy_in.model_dump(exclude_unset=True)
    
    # 如果更新了 params，验证并补充 model_path（如果缺失）
    if 'params' in update_data and update_data['params']:
        update_data['params'] = _validate_model_config(update_data['params'], db)
    
    # 进出场子策略已移除
    for field, value in update_data.items():
        setattr(strategy, field, value)
    db.commit()
    db.refresh(strategy)
    client = engine_manager.get_client(project_id=project_id)
    if client:
        if strategy.is_enabled:
            await client.update_strategy(strategy.dumps_map())
        else:
            await client.remove_strategy(strategy.id)
    return strategy


@router.put("/strategies/{strategy_id}/state", response_model=StrategyConfigOut)
async   def update_strategy_state(
    strategy_id: int,
    strategy_in: Dict[str, Any],
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    strategy = db.query(StrategyModel).filter(StrategyModel.id == strategy_id, StrategyModel.project_id == project_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategy.data = strategy_in
    db.commit()
    db.refresh(strategy)
    client = engine_manager.get_client(project_id=project_id)
    if client:
        await client.invoke("update_strategy_state", instance_id=str(strategy_id), state=strategy_in)
    return strategy

@router.put("/strategies/{strategy_id}/restart", response_model=StrategyConfigOut)
async def restart_strategy(
    strategy_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    strategy = db.query(StrategyModel).filter(StrategyModel.id == strategy_id, StrategyModel.project_id == project_id).first()
    if not strategy or not strategy.is_enabled:
        raise HTTPException(status_code=404, detail="Strategy not found")
    client = engine_manager.get_client(project_id=project_id)
    if client:
        await client.remove_strategy(strategy.id)
        await client.add_strategy(strategy.dumps_map())
    return strategy

@router.delete("/strategies/{strategy_id}/instance/{instance_id}")
async def delete_strategy_instance(
    strategy_id: str,
    instance_id: str,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    strategy = db.query(StrategyModel).filter(StrategyModel.id == strategy_id, StrategyModel.project_id == project_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    client = engine_manager.get_client(project_id=project_id)
    if client:
        data = await client.invoke("clear_strategy_state", strategy_id=strategy_id, instance_id=instance_id)
        if str(strategy_id) in data:
            strategy.data = data[str(strategy_id)]
            db.commit()
    return {"status": "success"}

@router.delete("/strategies/{strategy_id}")
async def delete_strategy(
    strategy_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db_session)
):
    strategy = db.query(StrategyModel).filter(StrategyModel.id == strategy_id, StrategyModel.project_id == project_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    db.delete(strategy)
    db.commit()
    client = engine_manager.get_client(project_id=project_id)
    if client:
        await client.remove_strategy(strategy.id)
    return {"status": "success"}

@router.get("/templates/strategy", response_model=List[TemplateResponse])
async def list_strategy_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取模板列表
    """
    return await leek_template_manager.get_strategy_by_project(project_id)


@router.get("/templates/strategy/policy", response_model=List[TemplateResponse])
async def list_strategy_policy_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取模板列表
    """
    return await leek_template_manager.get_strategy_policy_by_project(project_id)

@router.get("/templates/strategy/fabricator", response_model=List[TemplateResponse])
async def list_strategy_fabricator_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取模板列表
    """
    return await leek_template_manager.get_strategy_fabricator_by_project(project_id) 