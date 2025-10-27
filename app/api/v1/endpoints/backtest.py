from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.orm import defer
from typing import Any, Dict, Optional, List
from datetime import datetime

from app.api import deps
from app.models.backtest import BacktestTask
from app.models.backtest_config import BacktestConfig as BacktestConfigModel
from app.models.project_config import ProjectConfig as ProjectConfigModel
from app.schemas.backtest import (
    BacktestTaskOut, BacktestTaskBriefOut,
    BacktestConfigCreate, BacktestConfigUpdate, BacktestConfigOut,
    EnhancedBacktestCreate
)
from app.schemas.common import PageResponse
from leek_core.utils import get_logger
from app.core.scheduler import scheduler
from app.utils.series_codec import maybe_decode_values, maybe_decode_times, downsample_series
from app.service.enhanced_backtest_service import enhanced_backtest_service
from app.core.template_manager import leek_template_manager
from app.utils.json_sanitize import sanitize_for_json

logger = get_logger(__name__)

router = APIRouter()
def _attach_derived_metrics(task: BacktestTask, avoid_windows: bool = False) -> BacktestTask:
    try:
        cfg = task.config or {}
        initial_balance = float(cfg.get('initial_balance') or 10000)
        pnl_median = task.pnl_median
        start = task.start
        end = task.end
        # 总收益率
        tr = None
        if pnl_median is not None and initial_balance:
            tr = float(pnl_median) / float(initial_balance)
        # 年化
        ar = None
        if tr is not None and start and end:
            from datetime import datetime as _dt
            try:
                d1 = _dt.fromisoformat(str(start))
                d2 = _dt.fromisoformat(str(end))
                days = max(1, (d2 - d1).days)
                ar = (1.0 + float(tr)) ** (365.0 / float(days)) - 1.0
            except Exception:
                ar = None
        # 总交易次数：列表接口可选择跳过 windows 以避免加载大 JSON
        tt = None
        if not avoid_windows:
            try:
                wins = task.windows if isinstance(task.windows, list) else None
                if wins:
                    tt = int(sum(int(w.get('test_trades') or 0) for w in wins if isinstance(w, dict)))
            except Exception:
                tt = None
        if tt is None and task.trades_median is not None:
            try:
                tt = int(round(float(task.trades_median)))
            except Exception:
                tt = None
        # 交易胜率（如未落库，则按窗口聚合）
        try:
            if getattr(task, 'trade_win_rate', None) is None:
                tw = 0
                tt2 = 0
                wins = task.windows if isinstance(task.windows, list) else None
                if wins:
                    for w in wins:
                        tw += int(w.get('win_trades') or 0)
                        tt2 += int(w.get('test_trades') or 0)
                task.trade_win_rate = (float(tw)/float(tt2)) if tt2>0 else None
        except Exception:
            pass
        # 动态附加到实例（Pydantic from_attributes 会带出）
        task.total_return = tr
        task.annual_return = ar
        task.total_trades = tt
    except Exception:
        pass
    return task




def _update_status(task_id: int, status: str, progress: Optional[float] = None, started_at: Optional[datetime] = None, finished_at: Optional[datetime] = None, error: Optional[str] = None, windows=None, summary=None):
    from app.db.session import db_connect
    with db_connect() as db:
        t = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
        if not t:
            return
        t.status = status
        if progress is not None:
            t.progress = progress
        if started_at is not None:
            t.started_at = started_at
        if finished_at is not None:
            t.finished_at = finished_at
        if error is not None:
            t.error = error
        if windows is not None:
            t.windows = windows
        if summary is not None:
            t.summary = summary
        db.commit()


# NOTE: 为避免路径匹配到 /backtest/{task_id}，需要先声明更具体的 /backtest/config 路由
@router.get("/backtest/config", response_model=PageResponse[BacktestConfigOut])
async def list_backtest_configs(
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    type: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
):
    query = db.query(BacktestConfigModel).filter(BacktestConfigModel.project_id == project_id)
    if type:
        query = query.filter(BacktestConfigModel.type == type)
    if name:
        query = query.filter(BacktestConfigModel.name.like(f"%{name}%"))
    total = query.count()
    items = (
        query.order_by(BacktestConfigModel.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return PageResponse(total=total, page=page, size=size, items=items)


@router.post("/backtest/config", response_model=BacktestConfigOut)
async def create_backtest_config(
    req: BacktestConfigCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
):
    model = BacktestConfigModel(**req.model_dump())
    model.project_id = project_id
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


@router.put("/backtest/config/{config_id}", response_model=BacktestConfigOut)
async def update_backtest_config(
    config_id: int,
    req: BacktestConfigUpdate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
):
    model = db.query(BacktestConfigModel).filter(
        BacktestConfigModel.id == config_id,
        BacktestConfigModel.project_id == project_id,
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="Config not found")
    for k, v in req.model_dump(exclude_unset=True).items():
        setattr(model, k, v)
    db.commit()
    db.refresh(model)
    return model


@router.delete("/backtest/config/{config_id}")
async def delete_backtest_config(
    config_id: int,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
):
    model = db.query(BacktestConfigModel).filter(
        BacktestConfigModel.id == config_id,
        BacktestConfigModel.project_id == project_id,
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="Config not found")
    db.delete(model)
    db.commit()
    return {"status": "success"}


@router.get("/backtest/{task_id}", response_model=BacktestTaskOut)
async def get_backtest_task(
    task_id: int,
    db: Session = Depends(deps.get_db_session),
    expand_series: bool = Query(False),
):
    task = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # 按需展开压缩的时间/数值序列（仅详情接口，避免默认返回大 JSON）
    if expand_series and isinstance(task.windows, list):
        try:
            decoded_windows = []
            for w in task.windows:
                if not isinstance(w, dict):
                    decoded_windows.append(w)
                    continue
                obj = dict(w)
                if "equity_values" in obj:
                    obj["equity_values"] = maybe_decode_values(obj.get("equity_values"))
                if "equity_times" in obj:
                    obj["equity_times"] = maybe_decode_times(obj.get("equity_times"))
                # JSON 合规清洗
                decoded_windows.append(sanitize_for_json(obj))
            task.windows = decoded_windows
        except Exception:
            ...
    # 冗余字段已在任务完成时落库，直接返回（模型会由 Pydantic 导出）。
    # 但为避免 NaN/Inf 导致 JSONResponse 失败，这里对可疑字段做轻量清洗。
    try:
        if isinstance(task.summary, dict):
            task.summary = sanitize_for_json(task.summary)
        if isinstance(task.artifacts, dict):
            task.artifacts = sanitize_for_json(task.artifacts)
    except Exception:
        ...
    # 附加展示名称
    try:
        # 需要 project_id 获取模板；从任务所属项目冗余字段读取
        project_id = task.project_id
        templates = await leek_template_manager.get_strategy_by_project(project_id)
        cls_to_name = {t.cls: t.name for t in templates}
        setattr(task, "strategy_display_name", cls_to_name.get(getattr(task, "strategy_class", None)))
    except Exception:
        ...
    return task


@router.get("/backtest", response_model=PageResponse[BacktestTaskBriefOut])
async def list_backtest_tasks(
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    statuses: Optional[List[str]] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    # 只defer大字段windows和summary，保留config用于复制功能
    query = db.query(BacktestTask).options(
        defer(BacktestTask.windows),
        defer(BacktestTask.summary)
    ).filter(BacktestTask.project_id == project_id)
    if name:
        query = query.filter(BacktestTask.name.like(f"%{name}%"))
    # 支持单选（status）与多选（statuses）两种形式
    if statuses and len(statuses) > 0:
        query = query.filter(BacktestTask.status.in_(statuses))
    elif status:
        query = query.filter(BacktestTask.status == status)
    # 时间范围过滤（按创建时间）
    if start_date:
        start_dt = datetime.fromisoformat(start_date)
        query = query.filter(BacktestTask.created_at >= start_dt)
    if end_date:
        # 包含当天：将结束时间设置为当天 23:59:59
        end_dt = datetime.fromisoformat(end_date)
        end_dt = end_dt.replace(hour=23, minute=59, second=59)
        query = query.filter(BacktestTask.created_at <= end_dt)

    total = query.count()
    items = (
        query.order_by(BacktestTask.created_at.desc(), BacktestTask.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    # 附加展示名称
    templates = await leek_template_manager.get_strategy_by_project(project_id)
    cls_to_name = {t.cls: t.name for t in templates}
    for it in items:
        setattr(it, "strategy_display_name", cls_to_name.get(getattr(it, "strategy_class", None)))
    return PageResponse(total=total, page=page, size=size, items=items)


@router.delete("/backtest/{task_id}")
async def delete_backtest_task(
    task_id: int,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
):
    task = (
        db.query(BacktestTask)
        .filter(BacktestTask.id == task_id, BacktestTask.project_id == project_id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"status": "success"}


# ==================== Enhanced Backtest APIs ====================

@router.post("/backtest/enhanced", response_model=BacktestTaskOut)
async def create_enhanced_backtest(
    req: EnhancedBacktestCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
):
    """创建增强型回测任务"""
    try:
        project_config = db.query(ProjectConfigModel).filter(ProjectConfigModel.project_id == project_id).first()
        data_config = db.query(BacktestConfigModel).filter(BacktestConfigModel.id == req.data_config_id).first()
        req.data_source_config = data_config.params
        req.data_source = data_config.class_name
        # 创建数据库记录
        task = BacktestTask(
            project_id=project_id,
            name=req.name,
            type=req.mode,
            config=req.model_dump(),
            status="pending",
            progress=0.0,
            
            # 冗余字段
            strategy_class=req.strategy_class,
            data_config_id=req.data_config_id,
            cost_config_id=req.cost_config_id,
            start=str(req.start_time) if req.start_time else None,
            end=str(req.end_time) if req.end_time else None,
            symbols=req.symbols,
            timeframes=[tf.value if hasattr(tf, 'value') else str(tf) for tf in (req.timeframes or [])],
            max_workers=req.max_workers,
            train_days=req.train_days,
            test_days=req.test_days,
            embargo_days=req.embargo_days,
            mode=req.mode,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        await enhanced_backtest_service.create_backtest_task(task=task, req=req, mount_dirs=project_config.mount_dirs)
        return task
    except Exception as e:
        logger.error(f"Failed to create enhanced backtest: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/backtest/enhanced/{task_id}/results")
async def get_enhanced_backtest_results(
    task_id: int,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
    format: str = Query("json", description="返回格式：json, csv"),
):
    """获取增强型回测结果"""
    # 验证任务属于当前项目
    task = db.query(BacktestTask).filter(
        BacktestTask.id == task_id, 
        BacktestTask.project_id == project_id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="Task not completed")
    
    # 获取详细结果数据
    task_with_data = await enhanced_backtest_service.get_backtest_task_with_decompressed_data(
        db, task_id, expand_series=True
    )
    
    if format.lower() == "csv":
        # TODO: 实现CSV格式导出
        raise HTTPException(status_code=501, detail="CSV export not implemented yet")
    
    # 获取完整的性能指标
    windows = task_with_data.windows if task_with_data else task.windows
    
    # 下采样：当单条曲线长度过长时，降低采样率（阈值 2100）
    try:
        DS_MAX = 2100
        ds_windows = []
        if isinstance(windows, list):
            for w in windows:
                if not isinstance(w, dict):
                    ds_windows.append(w)
                    continue
                obj = dict(w)
                times = obj.get("equity_times")
                values = obj.get("equity_values")
                if isinstance(values, list) and len(values) > DS_MAX:
                    n = len(values)
                    # 统一索引，保证多条曲线对齐
                    stride = (n + DS_MAX - 1) // DS_MAX
                    idxs = list(range(0, n, stride))
                    if idxs[-1] != n - 1:
                        idxs.append(n - 1)
                    # 应用到 equity
                    obj["equity_values"] = [values[i] for i in idxs]
                    if isinstance(times, list) and len(times) >= n:
                        obj["equity_times"] = [times[i] for i in idxs]
                    # 对齐回撤与基准
                    dd = obj.get("drawdown_curve")
                    if isinstance(dd, list) and len(dd) >= n:
                        obj["drawdown_curve"] = [dd[i] for i in idxs]
                    bm = obj.get("benchmark_curve")
                    if isinstance(bm, list) and len(bm) >= n:
                        obj["benchmark_curve"] = [bm[i] for i in idxs]
                ds_windows.append(obj)
            windows = ds_windows
    except Exception:
        # 下采样失败时，保持原样
        ...
    detailed_metrics = {}
    combined = None
    # normal 模式：使用汇总指标，并解压组合曲线
    if isinstance(task.summary, dict) and 'normal' in task.summary:
        normal = task.summary.get('normal') or {}
        detailed_metrics = normal.get('aggregated_metrics') or {}
        try:
            c = normal.get('combined') or {}
            if isinstance(c, dict):
                times = c.get('equity_times')
                values = c.get('equity_values')
                # 解压
                if times:
                    times = maybe_decode_times(times)
                if values:
                    values = maybe_decode_values(values)
                # 对组合曲线做下采样
                if isinstance(values, list) and len(values) > DS_MAX:
                    times, values = downsample_series(times, values, DS_MAX)
                combined = { 'equity_times': times, 'equity_values': values }
        except Exception:
            combined = None
    else:
        # 取首个窗口的详细指标
        if windows and len(windows) > 0:
            first_window = windows[0]
            if isinstance(first_window, dict):
                detailed_metrics = first_window.get('test_metrics') or first_window.get('metrics') or {}
    
    # 构建结果数据
    results = {
        "task_id": task_id,
        "name": task.name,
        "status": task.status,
        "config": task.config,
        "summary": (lambda s, t: (lambda merged: merged)(
            (lambda _s: ( _s.update({"times": getattr(t, 'times_metrics', None)}) or _s ) if isinstance(_s, dict) else _s)(dict(s or {}))
        ))(task.summary, task),
        "windows": windows,
        "metrics": detailed_metrics,  # normal: 聚合指标；其它：首窗口指标
        "combined": combined,  # normal 模式下的组合净值
        "artifacts": task.artifacts,
        "created_at": task.created_at,
        "finished_at": task.finished_at,
        "execution_time": (task.finished_at - task.started_at).total_seconds() if task.finished_at and task.started_at else None
    }
    
    # 确保 JSON 合规
    return sanitize_for_json(results)


