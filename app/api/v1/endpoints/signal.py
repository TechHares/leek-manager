from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from sqlalchemy import and_

from app.api import deps
from app.models.strategy import Strategy
from app.models import signal as models
from app.schemas.signal import Signal, Asset, AssetType, TradeInsType, PositionSide
from app.core.template_manager import leek_template_manager

router = APIRouter()

@router.get("/signals", response_model=List[Signal])
async def get_signals(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    strategy_instance_id: Optional[int] = None,
    data_source_instance_id: Optional[int] = None,
    strategy_class_name: Optional[str] = None,
    data_source_class_name: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    project_id: int = Depends(deps.get_project_id)
) -> List[Signal]:
    """
    获取信号列表
    
    参数:
    - skip: 跳过记录数
    - limit: 返回记录数
    - strategy_instance_id: 策略实例ID
    - data_source_instance_id: 数据源实例ID
    - strategy_class_name: 策略类名
    - data_source_class_name: 数据源类名
    - start_time: 开始时间
    - end_time: 结束时间
    - project_id: 项目ID (自动从上下文获取)
    """
    # 获取所有策略实例的ID
    strategies = db.query(Strategy.id, Strategy.name).distinct().all()
    strategies = {s.id: s for s in strategies}
    
    # 获取策略模板信息
    strategy_templates = {
        t.cls: t.name for t in await leek_template_manager.get_strategy_by_project(project_id)
    }
    
    query = db.query(models.Signal).filter(models.Signal.project_id == project_id)
    
    if strategy_instance_id:
        query = query.filter(models.Signal.strategy_id == strategy_instance_id)
    if data_source_instance_id:
        query = query.filter(models.Signal.data_source_instance_id == data_source_instance_id)
    if strategy_class_name:
        query = query.filter(models.Signal.strategy_class_name == strategy_class_name)
    if data_source_class_name:
        query = query.filter(models.Signal.data_source_class_name == data_source_class_name)
    if start_time:
        query = query.filter(models.Signal.signal_time >= start_time)
    if end_time:
        query = query.filter(models.Signal.signal_time <= end_time)
        
    signals = query.order_by(models.Signal.signal_time.desc()).offset(skip).limit(limit).all()
    
    # 补充策略名称和模板名称
    for signal in signals:
        strategy = strategies.get(signal.strategy_id)
        if strategy:
            signal.strategy_name = strategy.name
            signal.strategy_template_name = strategy_templates.get(signal.strategy_class_name, signal.strategy_class_name)
    
    return signals

@router.get("/signals/{signal_id}", response_model=Signal)
async def get_signal(
    signal_id: int,
    db: Session = Depends(deps.get_db),
    project_id: int = Depends(deps.get_project_id)
) -> Signal:
    """
    获取单个信号详情
    
    参数:
    - signal_id: 信号ID
    - project_id: 项目ID (自动从上下文获取)
    """
    signal = db.query(models.Signal).filter(
        and_(
            models.Signal.id == signal_id,
            models.Signal.project_id == project_id
        )
    ).first()
    
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
        
    # 获取并补充策略信息
    strategy = db.query(models.Strategy).filter(
        models.Strategy.id == signal.strategy_instance_id
    ).first()
    
    if strategy:
        signal.strategy_name = strategy.name
        # 获取策略模板名称
        strategy_templates = {
            t.cls: t.name for t in leek_template_manager.get_strategy_by_project(project_id)
        }
        signal.strategy_template_name = strategy_templates.get(signal.strategy_class_name, signal.strategy_class_name)
    
    return signal 