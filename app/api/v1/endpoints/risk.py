from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func
from datetime import datetime, date, timedelta

from app.api import deps
from app.core.engine import engine_manager
from app.api.deps import get_project_id
from app.models.risk_policy import RiskPolicy as RiskPolicyModel
from app.models.risk_log import RiskLog as RiskLogModel
from app.models.strategy import Strategy as StrategyModel
from app.schemas.risk import RiskPolicy, RiskPolicyCreate, RiskPolicyUpdate
from app.schemas.risk_log import (
    RiskLog, RiskLogQuery, RiskDashboardData, RiskType
)
from app.schemas.common import PageResponse


router = APIRouter()


@router.get("/risk-policies", response_model=List[RiskPolicy])
def list_risk_policies(
    db: Session = Depends(deps.get_db_session),
    skip: int = 0,
    limit: int = 100,
    project_id: int = Depends(get_project_id),
    is_enabled: bool | None = None,
):
    query = db.query(RiskPolicyModel).filter(RiskPolicyModel.project_id == project_id)
    if is_enabled is not None:
        query = query.filter(RiskPolicyModel.is_enabled == is_enabled)
    query = query.order_by(RiskPolicyModel.created_at.desc())
    if limit is not None and limit > 0:
        query = query.offset(skip).limit(limit)
    items = query.all()
    return items


@router.post("/risk-policies", response_model=RiskPolicy)
async def create_risk_policy(
    payload: RiskPolicyCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(get_project_id),
):
    model = RiskPolicyModel(**payload.model_dump())
    model.project_id = project_id
    db.add(model)
    db.commit()
    db.refresh(model)
    # 如果启用则推送到引擎
    if model.is_enabled:
        client = engine_manager.get_client(project_id=str(project_id))
        if client:
            # 添加到引擎
            await engine_manager.send_action(str(project_id), "add_position_policy", config=model.dumps_map())
    return model


@router.get("/risk-policies/{policy_id}", response_model=RiskPolicy)
def get_risk_policy(
    policy_id: int,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(deps.get_db_session),
):
    model = db.query(RiskPolicyModel).filter(
        RiskPolicyModel.id == policy_id, RiskPolicyModel.project_id == project_id
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="RiskPolicy not found")
    return model


@router.put("/risk-policies/{policy_id}", response_model=RiskPolicy)
async def update_risk_policy(
    policy_id: int,
    payload: RiskPolicyUpdate,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(deps.get_db_session),
):
    model = db.query(RiskPolicyModel).filter(
        RiskPolicyModel.id == policy_id, RiskPolicyModel.project_id == project_id
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="RiskPolicy not found")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(model, field, value)
    db.commit()
    db.refresh(model)
    # 推送更新/删除到引擎
    client = engine_manager.get_client(project_id=str(project_id))
    if client:
        if model.is_enabled:
            await engine_manager.send_action(str(project_id), "update_position_policy", config=model.dumps_map())
        else:
            await engine_manager.send_action(str(project_id), "remove_position_policy", str(model.id))
    return model


@router.delete("/risk-policies/{policy_id}")
async def delete_risk_policy(
    policy_id: int,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(deps.get_db_session),
):
    model = db.query(RiskPolicyModel).filter(
        RiskPolicyModel.id == policy_id, RiskPolicyModel.project_id == project_id
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="RiskPolicy not found")
    # 先通知引擎移除
    client = engine_manager.get_client(project_id=str(project_id))
    if client:
        await engine_manager.send_action(str(project_id), "remove_position_policy", str(model.id))
    db.delete(model)
    db.commit()
    return {"status": "success"}


@router.get("/risk-events")
def list_risk_events():
    # TODO: implement real risk events source
    return []


@router.get("/risk-logs", response_model=PageResponse[RiskLog])
def list_risk_logs(
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(get_project_id),
    risk_type: RiskType | None = Query(None, description="风控类型"),
    strategy_id: int | None = Query(None, description="策略ID"),
    strategy_instance_id: str | None = Query(None, description="策略实例ID"),
    risk_policy_class_name: str | None = Query(None, description="风控策略类名"),
    start_time: datetime | None = Query(None, description="开始时间"),
    end_time: datetime | None = Query(None, description="结束时间"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    order_by: str = Query("trigger_time", description="排序字段"),
    order_desc: bool = Query(True, description="是否降序"),
):
    """查询风控日志列表"""
    # 使用左连接查询，关联策略和风控策略表
    query = db.query(
        RiskLogModel,
        StrategyModel.name.label('strategy_name'),
        RiskPolicyModel.name.label('risk_policy_name')
    ).outerjoin(
        StrategyModel, 
        RiskLogModel.strategy_id == StrategyModel.id
    ).outerjoin(
        RiskPolicyModel, 
        RiskLogModel.risk_policy_id == RiskPolicyModel.id
    ).filter(RiskLogModel.project_id == project_id)
    
    # 应用过滤条件
    if risk_type:
        query = query.filter(RiskLogModel.risk_type == risk_type)
    if strategy_id:
        query = query.filter(RiskLogModel.strategy_id == strategy_id)
    if strategy_instance_id:
        query = query.filter(RiskLogModel.strategy_instance_id == strategy_instance_id)
    if risk_policy_class_name:
        query = query.filter(RiskLogModel.risk_policy_class_name.like(f"%{risk_policy_class_name}%"))
    if start_time:
        query = query.filter(RiskLogModel.trigger_time >= start_time)
    if end_time:
        query = query.filter(RiskLogModel.trigger_time <= end_time)
    
    # 排序
    order_column = getattr(RiskLogModel, order_by, RiskLogModel.trigger_time)
    if order_desc:
        query = query.order_by(desc(order_column))
    else:
        query = query.order_by(order_column)
    
    # 分页
    total = query.count()
    results = query.offset((page - 1) * size).limit(size).all()
    
    # 处理查询结果，将关联的名称添加到风控日志对象中
    items = []
    for result in results:
        risk_log = result[0]  # RiskLogModel对象
        risk_log_dict = risk_log.dumps_map()
        risk_log_dict['strategy_name'] = result[1]  # strategy_name
        risk_log_dict['risk_policy_name'] = result[2]  # risk_policy_name
        items.append(risk_log_dict)
    
    return PageResponse(
        total=total,
        page=page,
        size=size,
        items=items
    )


@router.get("/risk-logs/{log_id}", response_model=RiskLog)
def get_risk_log(
    log_id: int,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(deps.get_db_session),
):
    """获取单个风控日志详情"""
    result = db.query(
        RiskLogModel,
        StrategyModel.name.label('strategy_name'),
        RiskPolicyModel.name.label('risk_policy_name')
    ).outerjoin(
        StrategyModel, 
        RiskLogModel.strategy_id == StrategyModel.id
    ).outerjoin(
        RiskPolicyModel, 
        RiskLogModel.risk_policy_id == RiskPolicyModel.id
    ).filter(
        RiskLogModel.id == log_id, 
        RiskLogModel.project_id == project_id
    ).first()
    
    if not result:
        raise HTTPException(status_code=404, detail="Risk log not found")
    
    # 处理查询结果，将关联的名称添加到风控日志对象中
    risk_log = result[0]  # RiskLogModel对象
    risk_log_dict = risk_log.dumps_map()
    risk_log_dict['strategy_name'] = result[1]  # strategy_name
    risk_log_dict['risk_policy_name'] = result[2]  # risk_policy_name
    
    return risk_log_dict


@router.get("/risk-dashboard", response_model=RiskDashboardData)
def get_risk_dashboard(
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(get_project_id),
):
    """获取风控仪表盘数据"""
    today = date.today()
    week_ago = today - timedelta(days=7)
    
    # 今日概况
    today_stats = db.query(
        func.count(RiskLogModel.id).label('total_signals')
    ).filter(
        RiskLogModel.project_id == project_id,
        func.date(RiskLogModel.trigger_time) == today
    ).first()
    
    today_total = today_stats.total_signals or 0
    today_blocked = 0  # 由于没有is_triggered字段，设为0
    today_block_rate = 0
    
    # 最近7天趋势
    recent_stats = db.query(
        func.date(RiskLogModel.trigger_time).label('date'),
        func.count(RiskLogModel.id).label('total_signals')
    ).filter(
        RiskLogModel.project_id == project_id,
        func.date(RiskLogModel.trigger_time) >= week_ago
    ).group_by(
        func.date(RiskLogModel.trigger_time)
    ).order_by(
        func.date(RiskLogModel.trigger_time)
    ).all()
    
    recent_7days_stats = [
        {
            'date': str(stat.date),
            'total_signals': stat.total_signals,
            'blocked_signals': 0,  # 没有is_triggered字段
            'block_rate': 0
        }
        for stat in recent_stats
    ]
    
    # 日志最多的策略
    top_strategies = db.query(
        RiskLogModel.strategy_instance_id,
        func.count(RiskLogModel.id).label('log_count')
    ).filter(
        RiskLogModel.project_id == project_id,
        func.date(RiskLogModel.trigger_time) >= week_ago,
        RiskLogModel.strategy_instance_id.isnot(None)
    ).group_by(
        RiskLogModel.strategy_instance_id
    ).order_by(
        desc(func.count(RiskLogModel.id))
    ).limit(10).all()
    
    top_triggered_strategies = [
        {
            'strategy_instance_id': strategy.strategy_instance_id,
            'trigger_count': strategy.log_count
        }
        for strategy in top_strategies
    ]
    
    # 风控策略效果
    policy_stats = db.query(
        RiskLogModel.risk_policy_class_name,
        func.count(RiskLogModel.id).label('total_evaluations')
    ).filter(
        RiskLogModel.project_id == project_id,
        func.date(RiskLogModel.trigger_time) >= week_ago
    ).group_by(
        RiskLogModel.risk_policy_class_name
    ).all()
    
    policy_effectiveness = [
        {
            'policy_class_name': policy.risk_policy_class_name,
            'total_evaluations': policy.total_evaluations,
            'triggered_count': 0,  # 没有is_triggered字段
            'trigger_rate': 0,
            'avg_duration_ms': None  # 没有evaluation_duration_ms字段
        }
        for policy in policy_stats
    ]
    
    # 平均评估耗时（已移除字段）
    avg_eval_time = None
    
    return RiskDashboardData(
        today_total_signals=today_total,
        today_blocked_signals=today_blocked,
        today_block_rate=today_block_rate,
        recent_7days_stats=recent_7days_stats,
        top_triggered_strategies=top_triggered_strategies,
        policy_effectiveness=policy_effectiveness,
        avg_evaluation_time=avg_eval_time,
        total_avoided_loss=None  # 需要后续实现回测计算
    )


