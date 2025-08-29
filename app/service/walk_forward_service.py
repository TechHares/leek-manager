from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple
from datetime import datetime
import os, sys

from sqlalchemy.orm import Session
from app.db.session import db_connect
from leek_core.engine.backtest import (
    WalkForwardOptimizer,
    StrategySearchConfig,
    EvaluationConfig,
    ExecutorConfig,
    generate_windows,
)
from leek_core.models import TimeFrame, TradeInsType
from app.models.backtest import BacktestTask
from app.models.backtest_config import BacktestConfig
from leek_core.utils import get_logger
from leek_core.base import load_class_from_str, create_component
from leek_core.data import DataSource
from app.utils.series_codec import encode_time_series, encode_values

logger = get_logger(__name__)


def _ensure_timeframe(tf: str) -> TimeFrame:
    try:
        # 支持传值如 "M5" 或具体值 "5m"
        return TimeFrame[tf] if tf in TimeFrame.__members__ else TimeFrame(tf)
    except Exception:
        raise ValueError(f"Invalid timeframe: {tf}")


def _import_strategy_class(class_path: str):
    """Load strategy class supporting both 'module|Class' and 'module.submodule.Class'."""
    # Preferred format used across leek-core
    try:
        return load_class_from_str(class_path)
    except Exception:
        # Fallback: dotted path import
        module_name, _, class_name = class_path.rpartition(".")
        if not module_name:
            raise ValueError(
                "strategy_class must be a full path, like 'module|ClassName' or 'module.submodule.ClassName'"
            )
        mod = __import__(module_name, fromlist=[class_name])
        return getattr(mod, class_name)


def _merge_effective_config(db: Session, cfg_in: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[DataSource], Optional[type]]:
    """Merge front-end payload with reusable configs (data/cost) to produce an effective config.

    Priority: explicit payload > cost/data config > defaults.
    Returns (effective_cfg, data_source_instance, executor_class)
    """
    cfg: Dict[str, Any] = dict(cfg_in or {})

    # Load reusable configs
    data_cfg: Optional[BacktestConfig] = None
    cost_cfg: Optional[BacktestConfig] = None
    if cfg.get("data_config_id"):
        data_cfg = db.query(BacktestConfig).filter(BacktestConfig.id == int(cfg["data_config_id"])) .first()
    if cfg.get("cost_config_id"):
        cost_cfg = db.query(BacktestConfig).filter(BacktestConfig.id == int(cfg["cost_config_id"])) .first()

    # From data config.extra
    ds_instance: Optional[DataSource] = None
    if data_cfg:
        extra = data_cfg.extra or {}
        cfg.setdefault("symbols", extra.get("symbols") or [])
        cfg.setdefault("timeframes", extra.get("timeframes") or [])
        cfg.setdefault("market", extra.get("market"))
        cfg.setdefault("quote_currency", extra.get("quote_currency"))
        if extra.get("ins_type") is not None:
            cfg.setdefault("ins_type", extra.get("ins_type"))
        # Pass data source class & params for per-worker instantiation (avoid sharing across threads)
        cfg["data_source_cls"] = data_cfg.class_name
        cfg["data_source_params"] = data_cfg.params or {}
        # Do not create a shared instance here to avoid cross-thread connection reuse
        ds_instance = None

    # From cost config
    executor_cls: Optional[type] = None
    if cost_cfg:
        try:
            executor_cls = load_class_from_str(cost_cfg.class_name)
        except Exception:
            executor_cls = None
        params = cost_cfg.params or {}
        # Only set defaults if not explicitly provided in payload
        for k in ["initial_balance", "fee_rate", "slippage_bps"]:
            if cfg.get(k) is None and params.get(k) is not None:
                cfg[k] = params.get(k)
        # Attach raw params as executor_cfg for low-level knobs
        cfg.setdefault("executor_cfg", params)

    # Sensible defaults
    cfg.setdefault("market", "okx")
    cfg.setdefault("quote_currency", "USDT")
    cfg.setdefault("ins_type", TradeInsType.SWAP.value)
    cfg.setdefault("initial_balance", 10000)
    cfg.setdefault("embargo_days", 0)
    cfg.setdefault("mode", "rolling")
    cfg.setdefault("cv_splits", 0)
    cfg.setdefault("max_workers", 1)

    return cfg, ds_instance, executor_cls


def _to_iso(value):
    try:
        if isinstance(value, datetime):
            return value.isoformat()
    except Exception:
        pass
    return value


def _serialize_windows(windows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for item in windows or []:
        obj = dict(item)
        # convert (start, end) tuples to [iso, iso]
        if isinstance(obj.get("train"), (list, tuple)) and len(obj.get("train")) == 2:
            tr_s, tr_e = obj["train"]
            obj["train"] = [_to_iso(tr_s), _to_iso(tr_e)]
        if isinstance(obj.get("test"), (list, tuple)) and len(obj.get("test")) == 2:
            te_s, te_e = obj["test"]
            obj["test"] = [_to_iso(te_s), _to_iso(te_e)]
        # encode equity series compactly
        if isinstance(obj.get("equity_values"), list):
            try:
                # ensure numeric type first
                values = [float(x) for x in obj["equity_values"]]
                obj["equity_values"] = encode_values(values)
            except Exception:
                pass
        if isinstance(obj.get("equity_times"), list):
            try:
                times = [int(x) for x in obj["equity_times"]]
                obj["equity_times"] = encode_time_series(times)
            except Exception:
                pass
        serialized.append(obj)
    return serialized


def _serialize_summary(summary: Dict[Any, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    # Convert tuple keys like (symbol, timeframe) to string keys 'symbol|timeframe'
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in (summary or {}).items():
        if isinstance(k, (list, tuple)) and len(k) == 2:
            key_str = f"{k[0]}|{k[1]}"
        else:
            key_str = str(k)
        out[key_str] = v
    return out


def run_walk_forward_task(task_id: int) -> Dict[str, Any]:
    with db_connect() as db:
        task: BacktestTask | None = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
        if not task:
            raise ValueError("Backtest task not found")

        cfg_raw = task.config or {}
        # Merge effective config using reusable configs
        cfg, data_source, executor_cls = _merge_effective_config(db, cfg_raw)
        # Ensure mount dirs are visible to this worker process
        try:
            from app.models.project_config import ProjectConfig
            pc = db.query(ProjectConfig).filter(ProjectConfig.project_id == int(task.project_id)).first()
            dirs = (pc.mount_dirs or []) if pc else []
            for dir_path in dirs:
                if dir_path == "default":
                    continue
                if os.path.isdir(dir_path) and dir_path not in sys.path:
                    sys.path.append(dir_path)
            # 把挂载目录传入配置，供子线程再次挂载
            cfg["mount_dirs"] = dirs
        except Exception:
            pass
        strategy_cls = _import_strategy_class(cfg["strategy_class"])  # noqa

        symbols: List[str] = cfg.get("symbols", [])
        timeframes: List[TimeFrame] = [_ensure_timeframe(t) for t in cfg.get("timeframes", [])]

        wf = WalkForwardOptimizer()

        def _on_progress(done: int, total: int):
            try:
                update_status(task.id, status="running", progress=float(done) / float(total))
            except Exception:
                pass

        # 若参数空间全为单值，视为未启用寻优，强制跳过训练阶段
        ps = cfg.get("param_space", {}) or {}
        try:
            all_singleton = len(ps) == 0 or all((isinstance(v, (list, tuple)) and len(v) <= 1) for v in ps.values())
        except Exception:
            all_singleton = False
        computed_train_days = 0 if all_singleton else int(cfg.get("train_days") or 0)

        results = wf.walk_forward(
            strategy=StrategySearchConfig(strategy_cls=strategy_cls, param_space=cfg.get("param_space", {})),
            evaluation=EvaluationConfig(
                symbols=symbols,
                timeframes=timeframes,
                start=cfg.get("start"),
                end=cfg.get("end"),
                train_days=computed_train_days,
                test_days=int(cfg.get("test_days")),
                embargo_days=int(cfg.get("embargo_days", 0)),
                mode=str(cfg.get("mode", "rolling")),
                cv_splits=int(cfg.get("cv_splits", 0)),
                max_workers=int(cfg.get("max_workers", 1)),
                sharpe_median_min=cfg.get("sharpe_median_min"),
                sharpe_p25_min=cfg.get("sharpe_p25_min"),
                mdd_median_max=cfg.get("mdd_median_max"),
                min_trades_per_window=int(cfg.get("min_trades_per_window", 0)),
            ),
            executor_cfg=ExecutorConfig(
                market=cfg.get("market", "okx"),
                quote_currency=cfg.get("quote_currency", "USDT"),
                ins_type=TradeInsType(cfg.get("ins_type", TradeInsType.SWAP.value)),
                initial_balance=cfg.get("initial_balance", 10000),
                fee_rate=cfg.get("fee_rate"),
                slippage_bps=cfg.get("slippage_bps"),
                data_source=None,  # instantiate per window using data_source_cls/params inside backtester
                executor=executor_cls or ExecutorConfig.executor,
                executor_cfg={ **(cfg.get("executor_cfg") or {}),
                               "data_source_cls": cfg.get("data_source_cls"),
                               "data_source_params": cfg.get("data_source_params") or {},
                               "mount_dirs": cfg.get("mount_dirs") or [] },
            ),
            risk_policies=[
                {
                    "class_name": (rp.get("class_name") or rp.get("cls")),
                    "config": rp.get("config") or rp.get("params") or {},
                }
                for rp in (cfg.get("risk_policies") or [])
            ] or None,
            on_progress=_on_progress,
        )

        # 保存结果（JSON 可序列化）
        raw_windows = results.get("windows") or []
        raw_summary = results.get("summary") or {}
        task.windows = _serialize_windows(raw_windows)
        task.summary = _serialize_summary(raw_summary)
        task.status = "completed"
        task.finished_at = datetime.now()
        task.progress = 1.0
        # 汇总结论冗余字段
        try:
            # summary 为 { (symbol|timeframe): { ...agg } } 的键值；取整体汇总：窗口数等
            sm = task.summary or {}
            windows_count = 0
            sharpe_vals = []
            mdd_vals = []
            trades_vals = []
            turnover_vals = []
            pnl_vals = []
            win_rate_vals = []
            pass_flags = []
            for k, v in sm.items():
                windows_count += int(v.get("windows", 0))
                if "sharpe_median" in v:
                    sharpe_vals.append(float(v.get("sharpe_median", 0)))
                if "mdd_median" in v:
                    mdd_vals.append(float(v.get("mdd_median", 0)))
                if "trades_median" in v:
                    trades_vals.append(float(v.get("trades_median", 0)))
                if "turnover_median" in v:
                    turnover_vals.append(float(v.get("turnover_median", 0)))
                if "pnl_median" in v:
                    pnl_vals.append(float(v.get("pnl_median", 0)))
                if "win_rate" in v:
                    win_rate_vals.append(float(v.get("win_rate", 0)))
                if "pass_thresholds" in v:
                    pass_flags.append(bool(v.get("pass_thresholds")))
            task.windows_count = windows_count
            task.sharpe_median = sum(sharpe_vals) / len(sharpe_vals) if sharpe_vals else None
            task.mdd_median = sum(mdd_vals) / len(mdd_vals) if mdd_vals else None
            task.trades_median = sum(trades_vals) / len(trades_vals) if trades_vals else None
            task.turnover_median = sum(turnover_vals) / len(turnover_vals) if turnover_vals else None
            task.pnl_median = sum(pnl_vals) / len(pnl_vals) if pnl_vals else None
            task.pass_thresholds = all(pass_flags) if pass_flags else None
            # 胜率（各分组胜率的平均）
            task.win_rate = sum(win_rate_vals) / len(win_rate_vals) if win_rate_vals else None
            # 交易胜率（窗口级 win_trades/test_trades 汇总）
            try:
                tw = 0
                tt = 0
                pf_sum = 0.0
                wl_sum = 0.0
                pf_count = 0
                for w in raw_windows:
                    tw += int(w.get("win_trades") or 0)
                    tt += int(w.get("test_trades") or 0)
                    # 盈亏比（Profit Factor）和平均盈亏比（win_loss_ratio）
                    try:
                        pf = w.get("profit_factor")
                        if pf is not None:
                            pf_sum += float(pf)
                            pf_count += 1
                        wl = w.get("win_loss_ratio")
                        if wl is not None:
                            wl_sum += float(wl)
                        aw = w.get("avg_win")
                        if aw is not None:
                            task.avg_win = float(aw)
                        al = w.get("avg_loss")
                        if al is not None:
                            task.avg_loss = float(al)
                        # 汇总总盈利/总亏损与次数（核心窗口已输出这些字段）
                        ps = w.get("profit_sum")
                        if ps is not None:
                            task.profit_sum = (task.profit_sum or 0.0) + float(ps)
                        ls = w.get("loss_sum")
                        if ls is not None:
                            task.loss_sum = (task.loss_sum or 0.0) + float(ls)
                        pc = w.get("profit_count")
                        if pc is not None:
                            task.profit_count = (task.profit_count or 0) + int(pc)
                        lc = w.get("loss_count")
                        if lc is not None:
                            task.loss_count = (task.loss_count or 0) + int(lc)
                    except Exception:
                        ...
                task.trade_win_rate = (float(tw) / float(tt)) if tt > 0 else None
                # 首选订单级统计的盈亏指标
                task.profit_factor = (pf_sum / pf_count) if pf_count > 0 else None
                task.win_loss_ratio = (wl_sum / pf_count) if pf_count > 0 else None
                # 回退：用窗口级数据近似（无订单级明细时）
                if task.profit_factor is None or task.win_loss_ratio is None or task.avg_win is None or task.avg_loss is None:
                    try:
                        # 使用窗口级交易数据而非PnL来计算交易级别的盈亏统计
                        win_trades_sum = 0  # 盈利交易总数
                        lose_trades_sum = 0  # 亏损交易总数
                        profit_sum_fb = 0.0  # 总盈利
                        loss_sum_fb = 0.0   # 总亏损
                        
                        for w in raw_windows:
                            # 基于窗口的交易级盈亏统计（如果有的话）
                            wt = int(w.get("win_trades") or 0)
                            tt = int(w.get("test_trades") or 0)
                            lt = max(0, tt - wt)  # 亏损交易数 = 总交易数 - 盈利交易数
                            
                            win_trades_sum += wt
                            lose_trades_sum += lt
                            
                            # 累计盈亏金额（如果有的话）
                            ps = w.get("profit_sum")
                            if ps is not None:
                                profit_sum_fb += float(ps)
                            ls = w.get("loss_sum") 
                            if ls is not None:
                                loss_sum_fb += float(ls)
                                
                        # 如果没有明确的profit_sum/loss_sum，用窗口PnL近似
                        if profit_sum_fb == 0.0 and loss_sum_fb == 0.0:
                            for w in raw_windows:
                                pnl = float(w.get("test_pnl") or 0.0)
                                if pnl > 0:
                                    profit_sum_fb += pnl
                                elif pnl < 0:
                                    loss_sum_fb += abs(pnl)
                        
                        avg_win_fb = (profit_sum_fb / win_trades_sum) if win_trades_sum > 0 else 0.0
                        avg_loss_fb = (loss_sum_fb / lose_trades_sum) if lose_trades_sum > 0 else 0.0
                        pf_fb = (profit_sum_fb / loss_sum_fb) if loss_sum_fb > 0 else None
                        wl_fb = (avg_win_fb / avg_loss_fb) if (avg_loss_fb > 0) else None
                        
                        # 使用交易级别的计数，而不是窗口级别
                        task.profit_sum = profit_sum_fb
                        task.loss_sum = loss_sum_fb
                        task.profit_count = win_trades_sum
                        task.loss_count = lose_trades_sum
                        if task.avg_win is None or task.avg_win == 0: task.avg_win = avg_win_fb
                        if task.avg_loss is None or task.avg_loss == 0: task.avg_loss = avg_loss_fb
                        if task.profit_factor is None: task.profit_factor = pf_fb
                        if task.win_loss_ratio is None: task.win_loss_ratio = wl_fb
                    except Exception:
                        ...
            except Exception:
                task.trade_win_rate = None
                task.profit_factor = None
                task.win_loss_ratio = None
            # 冗余衍生指标：总收益率/年化/总交易次数
            try:
                cfg = task.config or {}
                initial_balance = float(cfg.get('initial_balance') or 10000)
                tr = None
                if task.pnl_median is not None and initial_balance:
                    tr = float(task.pnl_median) / float(initial_balance)
                task.total_return = tr
                # 年化
                ar = None
                if tr is not None and task.start and task.end:
                    from datetime import datetime as _dt
                    try:
                        d1 = _dt.fromisoformat(str(task.start))
                        d2 = _dt.fromisoformat(str(task.end))
                        days = max(1, (d2 - d1).days)
                        ar = (1.0 + float(tr)) ** (365.0 / float(days)) - 1.0
                    except Exception:
                        ar = None
                task.annual_return = ar
                # 总交易次数
                try:
                    task.total_trades = int(sum(int(w.get('test_trades') or 0) for w in raw_windows))
                except Exception:
                    task.total_trades = None
            except Exception:
                pass
        except Exception:
            pass
        db.commit()
        return {"windows": task.windows, "summary": task.summary}


def update_status(task_id: int, status: str, progress: Optional[float] = None, started_at: Optional[datetime] = None, finished_at: Optional[datetime] = None, error: Optional[str] = None, windows=None, summary=None):
    """Service-level status updater to avoid importing API layer in worker process."""
    from app.models.backtest import BacktestTask
    with db_connect() as db:
        t = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
        if not t:
            return
        # 保持状态与进度单调：避免多线程更新导致回退
        t.status = status
        if progress is not None:
            try:
                current = float(t.progress or 0.0)
                incoming = float(progress)
                if incoming > current:
                    t.progress = incoming
            except Exception:
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


def run_walk_forward_task_job(task_id: int) -> None:
    """Top-level job function for scheduler process pool."""
    from datetime import datetime
    update_status(task_id, status="running", started_at=datetime.now(), progress=0.01)
    try:
        result = run_walk_forward_task(task_id)
        update_status(task_id, status="completed", finished_at=datetime.now(), progress=1.0, **result)
    except Exception as e:
        logger.error(f"Walk-forward task {task_id} failed: {e}", exc_info=True)
        update_status(task_id, status="failed", finished_at=datetime.now(), error=str(e))


