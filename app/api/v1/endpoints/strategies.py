from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict, List
from app.api import deps
from app.models.strategy import Strategy as StrategyModel
from app.schemas.strategy import (
    StrategyConfigOut, StrategyConfigCreate, StrategyConfigUpdate
)
from app.schemas.template import TemplateResponse
from app.core.template_manager import leek_template_manager
from app.core.engine import engine_manager
router = APIRouter()
@router.get("/strategies", response_model=List[StrategyConfigOut])
async def list_strategies(
    db: Session = Depends(deps.get_db),
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

@router.post("/strategies", response_model=StrategyConfigOut)
async def create_strategy(
    strategy: StrategyConfigCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id)
):
    data = strategy.model_dump()
    data["enter_strategy_config"] = data.pop("enter_strategy_params", None)
    data["exit_strategy_config"] = data.pop("exit_strategy_params", None)
    data["enter_strategy_class_name"] = data.pop("enter_strategy_class_name", None)
    data["exit_strategy_class_name"] = data.pop("exit_strategy_class_name", None)
    data["info_fabricator_configs"] = data.pop("info_fabricator_configs", None)
    data["params"] = data.pop("params", None)
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
    db: Session = Depends(deps.get_db)
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
    db: Session = Depends(deps.get_db)
):
    strategy = db.query(StrategyModel).filter(StrategyModel.id == strategy_id, StrategyModel.project_id == project_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    update_data = strategy_in.model_dump(exclude_unset=True)
    if "enter_strategy" in update_data:
        update_data["enter_strategy_class_name"] = update_data.pop("enter_strategy")
    if "enter_strategy_params" in update_data:
        update_data["enter_strategy_config"] = update_data.pop("enter_strategy_params")
    if "exit_strategy" in update_data:
        update_data["exit_strategy_class_name"] = update_data.pop("exit_strategy")
    if "exit_strategy_params" in update_data:
        update_data["exit_strategy_config"] = update_data.pop("exit_strategy_params")
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
    db: Session = Depends(deps.get_db)
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
    db: Session = Depends(deps.get_db)
):
    strategy = db.query(StrategyModel).filter(StrategyModel.id == strategy_id, StrategyModel.project_id == project_id).first()
    if not strategy or not strategy.is_enabled:
        raise HTTPException(status_code=404, detail="Strategy not found")
    client = engine_manager.get_client(project_id=project_id)
    if client:
        await client.remove_strategy(strategy.id)
        await client.add_strategy(strategy.dumps_map())
    return strategy


@router.delete("/strategies/{strategy_id}")
async def delete_strategy(
    strategy_id: int,
    project_id: int = Depends(deps.get_project_id),
    db: Session = Depends(deps.get_db)
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
async def list_executor_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取模板列表
    """
    return await leek_template_manager.get_strategy_by_project(project_id)

@router.get("/templates/strategy/exit", response_model=List[TemplateResponse])
async def list_executor_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取模板列表
    """
    return await leek_template_manager.get_exit_strategy_by_project(project_id)

@router.get("/templates/strategy/enter", response_model=List[TemplateResponse])
async def list_executor_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取模板列表
    """
    return await leek_template_manager.get_enter_strategy_by_project(project_id)

@router.get("/templates/strategy/policy", response_model=List[TemplateResponse])
async def list_executor_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取模板列表
    """
    return await leek_template_manager.get_strategy_policy_by_project(project_id)

@router.get("/templates/strategy/fabricator", response_model=List[TemplateResponse])
async def list_executor_templates(
    project_id: int = Depends(deps.get_project_id)
):
    """
    获取模板列表
    """
    return await leek_template_manager.get_strategy_fabricator_by_project(project_id) 