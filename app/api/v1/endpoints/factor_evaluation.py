from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.orm import defer
from typing import Any, Dict, Optional, List
from datetime import datetime

from app.api import deps
from app.models.factor_evaluation import FactorEvaluationTask
from app.schemas.factor_evaluation import (
    FactorEvaluationCreate,
    FactorEvaluationTaskOut,
    FactorEvaluationTaskBriefOut
)
from app.schemas.common import PageResponse
from leek_core.utils import get_logger
from app.service.factor_evaluation_service import factor_evaluation_service
from app.utils.json_sanitize import sanitize_for_json, finite_or_none
from app.utils.series_codec import decode_time_series, decode_values

logger = get_logger(__name__)

router = APIRouter()


@router.post("/factor_evaluation", response_model=FactorEvaluationTaskOut)
async def create_factor_evaluation(
    req: FactorEvaluationCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
):
    """创建因子评价任务"""
    try:
        # 创建数据库记录
        task = FactorEvaluationTask(
            project_id=project_id,
            name=req.name,
            config=req.model_dump(),
            status="pending",
            progress=0.0,
            data_config_id=req.data_config_id,
            start=req.start_time,
            end=req.end_time,
            symbols=req.symbols,
            timeframes=req.timeframes,
            factor_ids=req.factor_ids,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        
        # 异步执行评价
        await factor_evaluation_service.create_evaluation_task(task, req)
        
        return task
    except Exception as e:
        logger.error(f"Failed to create factor evaluation: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/factor_evaluation/{task_id}", response_model=FactorEvaluationTaskOut)
async def get_factor_evaluation_task(
    task_id: int,
    db: Session = Depends(deps.get_db_session),
    expand_charts: bool = Query(False, description="是否展开图表数据"),
    include_metrics: bool = Query(True, description="是否包含详细指标数据（大数据字段）"),
):
    """获取因子评价任务详情"""
    # 优化：先查询基本字段，大字段按需单独查询
    # metrics 字段可能非常大（数百MB），单独查询可以更好地控制
    task = db.query(FactorEvaluationTask).options(
        defer(FactorEvaluationTask.summary),
        defer(FactorEvaluationTask.metrics),
        defer(FactorEvaluationTask.charts)
    ).filter(FactorEvaluationTask.id == task_id).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 按需加载大字段（使用单独的查询，避免一次性加载所有数据）
    if include_metrics and task.metrics is None:
        # 显式加载 metrics（SQLAlchemy 会在访问时自动加载，但我们可以控制时机）
        db.refresh(task, ['metrics'])
    elif not include_metrics:
        # 如果不需要 metrics，保持为 None，避免加载
        pass
    
    # 总是加载 summary 和 charts（它们相对较小）
    if task.summary is None:
        db.refresh(task, ['summary'])
    if task.charts is None:
        db.refresh(task, ['charts'])
    
    # 如果任务未完成，从 running_tasks 获取详细状态
    if task.status in ['pending', 'running']:
        task_status = factor_evaluation_service.get_task_status(task_id)
        if task_status:
            # 将状态信息添加到 task 对象中（通过 config 字段传递）
            if not task.config:
                task.config = {}
            task.config['task_status'] = task_status
    
    # JSON合规清洗（优化：减少对大型数据的递归处理）
    try:
        if isinstance(task.summary, dict):
            task.summary = sanitize_for_json(task.summary)
        if isinstance(task.metrics, list) and task.metrics:
            # 优化：对于大数据，只清洗顶层结构，避免深度递归
            # metrics 列表可能包含大量数据，如果数据已经是 JSON 安全的，可以跳过深度处理
            # 只处理列表中的每个元素的第一层，避免递归处理嵌套的大数据结构
            sanitized_metrics = []
            for m in task.metrics:
                if isinstance(m, dict):
                    # 只清洗顶层字段，避免深度递归处理大字段（如 ic_series）
                    sanitized_m = {}
                    for k, v in m.items():
                        # 对于可能很大的字段（如 ic_series），如果已经是列表/字典，只做浅层处理
                        if k in ['ic_series'] and isinstance(v, list):
                            # ic_series 是列表，只处理列表中的数值，不做深度递归
                            sanitized_m[k] = [finite_or_none(x) if isinstance(x, (int, float)) else x for x in v]
                        else:
                            sanitized_m[k] = sanitize_for_json(v)
                    sanitized_metrics.append(sanitized_m)
                else:
                    sanitized_metrics.append(sanitize_for_json(m))
            task.metrics = sanitized_metrics
        # charts 字段优化：如果不需要展开，只清洗非压缩部分
        # charts 结构：{'ic_series': {factor_name: {codec, data}}, 'quantile_returns': {...}, 'correlation_matrix': {...}}
        if isinstance(task.charts, dict):
            if expand_charts:
                # 需要展开时才进行完整递归清洗
                task.charts = sanitize_for_json(task.charts)
            else:
                # 不需要展开时，只清洗非压缩部分（quantile_returns 和 correlation_matrix）
                # ic_series 已经是压缩格式，不需要递归清洗
                if 'quantile_returns' in task.charts and isinstance(task.charts['quantile_returns'], dict):
                    task.charts['quantile_returns'] = sanitize_for_json(task.charts['quantile_returns'])
                if 'correlation_matrix' in task.charts and isinstance(task.charts['correlation_matrix'], dict):
                    task.charts['correlation_matrix'] = sanitize_for_json(task.charts['correlation_matrix'])
        if isinstance(task.config, dict):
            task.config = sanitize_for_json(task.config)
    except Exception:
        pass
    
    return task


@router.get("/factor_evaluation", response_model=PageResponse[FactorEvaluationTaskBriefOut])
async def list_factor_evaluation_tasks(
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """获取因子评价任务列表"""
    # defer大字段
    query = db.query(FactorEvaluationTask).options(
        defer(FactorEvaluationTask.summary),
        defer(FactorEvaluationTask.metrics),
        defer(FactorEvaluationTask.charts)
    ).filter(FactorEvaluationTask.project_id == project_id)
    
    if name:
        query = query.filter(FactorEvaluationTask.name.like(f"%{name}%"))
    
    if status:
        query = query.filter(FactorEvaluationTask.status == status)
    
    # 时间范围过滤（按创建时间）
    if start_date:
        start_dt = datetime.fromisoformat(start_date)
        query = query.filter(FactorEvaluationTask.created_at >= start_dt)
    if end_date:
        end_dt = datetime.fromisoformat(end_date)
        end_dt = end_dt.replace(hour=23, minute=59, second=59)
        query = query.filter(FactorEvaluationTask.created_at <= end_dt)
    
    total = query.count()
    items = (
        query.order_by(
            FactorEvaluationTask.created_at.desc(), 
            FactorEvaluationTask.id.desc()
        )
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    
    return PageResponse(total=total, page=page, size=size, items=items)


@router.get("/factor_evaluation/{task_id}/factor/{factor_id}/charts")
async def get_factor_charts(
    task_id: int,
    factor_id: int,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
    symbol: Optional[str] = Query(None, description="筛选特定symbol"),
    timeframe: Optional[str] = Query(None, description="筛选特定timeframe"),
    merged: bool = Query(False, description="是否返回合并后的IC序列"),
):
    """获取单个因子的图表数据（解压后的IC序列和时间戳）"""
    # 查询任务
    task = db.query(FactorEvaluationTask).filter(
        FactorEvaluationTask.id == task_id,
        FactorEvaluationTask.project_id == project_id
    ).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 加载charts数据
    if task.charts is None:
        db.refresh(task, ['charts'])
    
    if not task.charts:
        raise HTTPException(status_code=404, detail="Charts data not found")
    
    # 从metrics中找到对应的因子
    if task.metrics is None:
        db.refresh(task, ['metrics'])
    
    if not task.metrics:
        raise HTTPException(status_code=404, detail="Metrics data not found")
    
    # 查找对应的因子
    factor_metric = None
    for metric in task.metrics:
        if metric.get('factor_id') == factor_id:
            factor_metric = metric
            break
    
    if not factor_metric:
        raise HTTPException(status_code=404, detail=f"Factor {factor_id} not found in task")
    
    factor_name = factor_metric.get('factor_name', '')
    
    # 从charts中获取该因子的数据
    ic_series_data = task.charts.get('ic_series', {})
    factor_charts = ic_series_data.get(factor_name, {})
    
    if not factor_charts:
        raise HTTPException(status_code=404, detail=f"Charts data for factor {factor_name} not found")
    
    # 解压数据
    ic_data = []
    
    # 如果merged=true，返回合并后的IC序列
    if merged:
        merged_data = factor_charts.get('merged', {})
        if merged_data:
            times_encoded = merged_data.get('times', {})
            values_encoded = merged_data.get('values', {})
            
            ic_times = decode_time_series(times_encoded) if times_encoded else []
            ic_values = decode_values(values_encoded) if values_encoded else []
            
            return {
                'factor_id': factor_id,
                'factor_name': factor_name,
                'ic_data_merged': {
                    'ic_times': ic_times,
                    'ic_values': ic_values,
                },
                'quantile_returns': factor_metric.get('quantile_returns', {}),
                'long_short_return': factor_metric.get('long_short_return', 0.0),
            }
    
    # 返回按symbol×timeframe保存的数据
    for st_key, st_data in factor_charts.items():
        if st_key == 'merged':
            continue
        
        st_symbol = st_data.get('symbol', '')
        st_timeframe = st_data.get('timeframe', '')
        
        # 如果指定了symbol或timeframe筛选，进行过滤
        if symbol and st_symbol != symbol:
            continue
        if timeframe and st_timeframe != timeframe:
            continue
        
        times_encoded = st_data.get('times', {})
        values_encoded = st_data.get('values', {})
        
        ic_times = decode_time_series(times_encoded) if times_encoded else []
        ic_values = decode_values(values_encoded) if values_encoded else []
        
        ic_data.append({
            'symbol': st_symbol,
            'timeframe': st_timeframe,
            'ic_times': ic_times,
            'ic_values': ic_values,
        })
    
    return {
        'factor_id': factor_id,
        'factor_name': factor_name,
        'ic_data': ic_data,
        'quantile_returns': factor_metric.get('quantile_returns', {}),
        'long_short_return': factor_metric.get('long_short_return', 0.0),
    }


@router.delete("/factor_evaluation/{task_id}")
async def delete_factor_evaluation_task(
    task_id: int,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
):
    """删除因子评价任务"""
    task = db.query(FactorEvaluationTask).filter(
        FactorEvaluationTask.id == task_id,
        FactorEvaluationTask.project_id == project_id
    ).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    db.delete(task)
    db.commit()
    return {"status": "success"}

