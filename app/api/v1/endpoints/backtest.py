from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.orm import defer
from typing import Any, Dict, Optional, List
from datetime import datetime

from app.api import deps
from app.models.backtest import BacktestTask
from app.models.backtest_config import BacktestConfig as BacktestConfigModel
from app.schemas.backtest import (
    WalkForwardCreate, BacktestTaskOut, BacktestTaskBriefOut,
    BacktestConfigCreate, BacktestConfigUpdate, BacktestConfigOut
)
from app.schemas.common import PageResponse
from leek_core.utils import get_logger
from app.core.scheduler import scheduler

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


@router.post("/backtest/walk-forward", response_model=BacktestTaskOut)
async def create_walk_forward(
    req: WalkForwardCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
):
    task = BacktestTask(
        project_id=project_id,
        name=req.name,
        type="walk_forward",
        config=req.model_dump(),
        status="pending",
    )
    # 冗余关键字段，便于列表展示/过滤
    try:
        cfg = task.config
        task.strategy_class = cfg.get("strategy_class")
        task.data_config_id = cfg.get("data_config_id")
        task.cost_config_id = cfg.get("cost_config_id")
        task.start = cfg.get("start")
        task.end = cfg.get("end")
        task.train_days = int(cfg.get("train_days")) if cfg.get("train_days") is not None else None
        task.test_days = int(cfg.get("test_days")) if cfg.get("test_days") is not None else None
        task.embargo_days = int(cfg.get("embargo_days")) if cfg.get("embargo_days") is not None else None
        task.mode = cfg.get("mode")
        task.cv_splits = int(cfg.get("cv_splits")) if cfg.get("cv_splits") is not None else None
        task.max_workers = int(cfg.get("max_workers")) if cfg.get("max_workers") is not None else None
        task.symbols = cfg.get("symbols")
        task.timeframes = cfg.get("timeframes")
    except Exception:
        pass
    db.add(task)
    db.commit()
    db.refresh(task)

    # 调度后台执行
    # 使用进程池执行，避免与主进程GIL竞争，适合CPU密集的回测
    scheduler.add_date_job(
        func='app.service.walk_forward_service:run_walk_forward_task_job',
        run_date=datetime.now(),
        args=(task.id,),
        id=f"wf_{task.id}",
        name=f"walk_forward_{task.id}",
        executor="processpool",
    )

    return _attach_derived_metrics(task)


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
async def get_backtest_task(task_id: int, db: Session = Depends(deps.get_db_session)):
    task = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # 冗余字段已在任务完成时落库，直接返回
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
    query = db.query(BacktestTask).options(
        defer(BacktestTask.windows),
        defer(BacktestTask.summary),
    ).filter(BacktestTask.project_id == project_id)
    if name:
        query = query.filter(BacktestTask.name.like(f"%{name}%"))
    # 支持单选（status）与多选（statuses）两种形式
    if statuses and len(statuses) > 0:
        query = query.filter(BacktestTask.status.in_(statuses))
    elif status:
        query = query.filter(BacktestTask.status == status)
    # 时间范围过滤（按创建时间）
    try:
        if start_date:
            start_dt = datetime.fromisoformat(start_date)
            query = query.filter(BacktestTask.created_at >= start_dt)
        if end_date:
            # 包含当天：将结束时间设置为当天 23:59:59
            end_dt = datetime.fromisoformat(end_date)
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            query = query.filter(BacktestTask.created_at <= end_dt)
    except Exception:
        # 忽略非法时间格式
        pass

    total = query.count()
    items = (
        query.order_by(BacktestTask.created_at.desc(), BacktestTask.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    # 关键指标已冗余在表结构，直接返回
    items = items
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


# （已向上移动 config 路由，避免与 /backtest/{task_id} 冲突）


