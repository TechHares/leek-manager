from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import and_
from pydantic import BaseModel

from app.api import deps
from app.schemas.executor import Executor, ExecutorCreate, ExecutorUpdate
from app.schemas.template import TemplateResponse
from app.models.execution import Executor as ExecutorModel
from app.core.template_manager import leek_template_manager
from app.core.engine import engine_manager
from app.api.deps import get_project_id

class ExecutorBase(BaseModel):
    name: str
    description: Optional[str]
    class_name: str
    params: Optional[Dict[str, Any]]

router = APIRouter()

@router.get("/executor/traders", response_model=List[Executor])
def list_executors(
    db: Session = Depends(deps.get_db_session),
    skip: Optional[int] = 0,
    limit: Optional[int] = 100,
    enable: Optional[bool] = Query(None),
    project_id: int = Depends(get_project_id)
):
    """
    获取执行器列表，可选是否只查启用的，可选不分页
    """
    query = db.query(ExecutorModel)
    query = query.filter(ExecutorModel.project_id == project_id)
    if enable is not None:
        query = query.filter(ExecutorModel.is_enabled == enable)
    query = query.order_by(ExecutorModel.created_at.desc())
    # limit为0或负数时，返回全部
    if limit is not None and limit > 0:
        query = query.offset(skip).limit(limit)
    executors = query.all()
    return executors

@router.post("/executor/traders", response_model=Executor)
async def create_executor(
    executor: ExecutorBase,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(get_project_id)
):
    """
    创建新的执行器
    """
    executor_model = ExecutorModel(**executor.model_dump())
    executor_model.project_id = project_id
    db.add(executor_model)
    db.commit()
    db.refresh(executor_model)
    client = engine_manager.get_client(project_id=project_id)
    if client:
            await client.add_executor(executor_model.dumps_map())
    return executor_model

@router.get("/executor/traders/{executor_id}", response_model=Executor)
async def get_executor(
    *,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(get_project_id),
    executor_id: int
):
    """
    获取指定执行器详情
    """
    executor = db.query(ExecutorModel).filter(ExecutorModel.id == executor_id, ExecutorModel.project_id == project_id).first()
    if not executor:
        raise HTTPException(status_code=404, detail="Executor not found")
    return executor

@router.put("/executor/traders/{executor_id}", response_model=Executor)
async def update_executor(
    *,
    db: Session = Depends(deps.get_db_session),
    executor_id: int,
    project_id: int = Depends(get_project_id),
    executor_in: ExecutorUpdate
):
    """
    更新执行器信息
    """
    executor = db.query(ExecutorModel).filter(ExecutorModel.id == executor_id, ExecutorModel.project_id == project_id).first()
    if not executor:
        raise HTTPException(status_code=404, detail="Executor not found")
    
    update_data = executor_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(executor, field, value)
    
    db.commit()
    db.refresh(executor)
    client = engine_manager.get_client(project_id=project_id)
    if client:
        if executor.is_enabled:
            await client.update_executor(executor.dumps_map())
        else:
            await client.remove_executor(executor.id)
    return executor

@router.delete("/executor/traders/{executor_id}")
async def delete_executor(
    *,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(get_project_id),
    executor_id: int
):
    """
    删除执行器
    """
    executor = db.query(ExecutorModel).filter(ExecutorModel.id == executor_id, ExecutorModel.project_id == project_id).first()
    if not executor:
        raise HTTPException(status_code=404, detail="Executor not found")
    
    db.delete(executor)
    db.commit()
    client = engine_manager.get_client(project_id=project_id)
    if client:
        await client.remove_executor(executor.id)
    return {"status": "success"}

@router.get("/templates/executor", response_model=List[TemplateResponse])
async def list_executor_templates(
    project_id: int = Depends(get_project_id),
    just_backtest: bool | None = Query(None)
):
    """
    获取执行器模板列表
    - just_backtest 未传：仅返回非回测专用（正式）
    - just_backtest=true：仅返回回测专用
    - just_backtest=false：仅返回非回测专用
    """
    items = await leek_template_manager.get_executors_by_project(project_id)
    if just_backtest is None:
        return [x for x in items if not getattr(x, 'just_backtest', False)]
    return [x for x in items if (getattr(x, 'just_backtest', False) is True) == (just_backtest is True)]