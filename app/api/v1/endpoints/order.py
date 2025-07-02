from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, cast, Boolean
from app.db.session import get_db
from app.models.order import Order, ExecutionOrder
from app.models.strategy import Strategy
from app.models.execution import Executor
from app.schemas.order import OrderOut, OrderFilter, ExecutionInfo as ExecutionInfoSchema
from app.schemas.common import PageResponse
from app.api.deps import get_project_id

router = APIRouter()

@router.get("/executor/orders", response_model=PageResponse[OrderOut])
async def list_orders(
    position_id: str = Query(None),
    strategy_id: int = Query(None),
    order_status: str = Query(None),
    is_open: bool = Query(None),
    is_fake: bool = Query(None),
    market_order_id: str = Query(None),
    executor_id: str = Query(None),
    page: int = 1,
    size: int = 20,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db)
):
    query = db.query(Order)
    query = query.filter(Order.project_id == project_id)
    if position_id:
        query = query.filter(Order.position_id == position_id)
    if strategy_id:
        query = query.filter(Order.strategy_id == strategy_id)
    if order_status:
        query = query.filter(Order.order_status == order_status)
    if is_open is not None:
        query = query.filter(Order.is_open == is_open)
    if is_fake is not None:
        query = query.filter(Order.is_fake == is_fake)
    if market_order_id:
        query = query.filter(Order.market_order_id == market_order_id)
    if executor_id:
        query = query.filter(Order.executor_id == executor_id)
    total = query.count()
    items = query.order_by(Order.order_time.desc()).offset((page - 1) * size).limit(size).all()
    # 获取所有策略ID和执行器ID
    strategy_ids = {item.strategy_id for item in items if item.strategy_id}
    executor_ids = {item.executor_id for item in items if item.executor_id}

    # 一次性查询所有策略和执行器
    strategy_map = {strategy.id: strategy.name for strategy in db.query(Strategy).filter(Strategy.id.in_(strategy_ids)).all()}
    executor_map = {executor.id: executor.name for executor in db.query(Executor).filter(Executor.id.in_(executor_ids)).all()}
    # 填充名称
    for item in items:
        item.strategy_name = strategy_map.get(item.strategy_id)
        item.exec_name = executor_map.get(int(item.executor_id))
    return PageResponse(total=total, page=page, size=size, items=items)

@router.get("/executor/orders/{order_id}", response_model=OrderOut)
async def get_order_detail(order_id: int, project_id: int = Depends(get_project_id), db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id, Order.project_id == project_id).first()
    if not order:
        raise HTTPException(status_code=403, detail="Order not found")
    
    # 获取策略和执行器名称
    if order.strategy_id:
        strategy = db.query(Strategy).filter(Strategy.id == order.strategy_id).first()
        if strategy:
            order.strategy_name = strategy.name
    
    if order.executor_id:
        executor = db.query(Executor).filter(Executor.id == order.executor_id).first()
        if executor:
            order.exec_name = executor.name
    
    return order

@router.get("/executor/execution_orders", response_model=PageResponse[ExecutionInfoSchema])
async def list_execution_infos(
    signal_id: str = Query(None),
    strategy_id: int = Query(None),
    strategy_instant_id: str = Query(None),
    page: int = 1,
    size: int = 20,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db)
):
    query = db.query(ExecutionOrder).filter(ExecutionOrder.project_id == project_id)
    if signal_id:
        query = query.filter(ExecutionOrder.signal_id == signal_id)
    if strategy_id:
        query = query.filter(ExecutionOrder.strategy_id == strategy_id)
    if strategy_instant_id:
        query = query.filter(ExecutionOrder.strategy_instant_id == strategy_instant_id)
    total = query.count()
    items = query.order_by(ExecutionOrder.created_time.desc()).offset((page - 1) * size).limit(size).all()
    strategy_ids = {item.strategy_id for item in items if item.strategy_id}
    # 一次性查询所有策略和执行器
    strategy_map = {strategy.id: strategy.name for strategy in db.query(Strategy).filter(Strategy.id.in_(strategy_ids)).all()}
    # 填充名称
    for item in items:
        item.strategy_name = strategy_map.get(item.strategy_id)
    return PageResponse(total=total, page=page, size=size, items=items) 