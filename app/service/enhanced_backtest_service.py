#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import json
import traceback
from statistics import mean, median
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.backtest import BacktestTask
from app.utils.series_codec import encode_time_series, encode_values
from leek_core.backtest import (
    EnhancedBacktester, BacktestConfig, BacktestMode, OptimizationObjective,
    BacktestResult, WalkForwardResult, NormalBacktestResult
)
from leek_core.models import TimeFrame, TradeInsType
from leek_core.utils import get_logger
from app.db.session import db_connect
from app.schemas.backtest import EnhancedBacktestCreate
from app.utils.json_sanitize import sanitize_for_json

logger = get_logger(__name__)

"""
Enhanced Backtest Service - 回测服务

负责：
1. 回测任务的创建、调度和管理
2. 结果数据的压缩存储
3. 并行执行控制
4. 进度跟踪和状态更新
"""
class EnhancedBacktestService:
    """增强型回测服务"""
    
    def __init__(self):
        # 不再需要全局executor，每个任务独立创建ThreadPoolExecutor
        self.running_tasks: Dict[int, Any] = {}
    
    async def create_backtest_task(self, task: BacktestTask, req: EnhancedBacktestCreate, mount_dirs: List[str]):
        """创建回测任务"""
        
        backtest_config = BacktestConfig(
            id=task.id,
            name=task.name,
            mode=BacktestMode(task.mode),
            strategy_class=req.strategy_class,
            strategy_params=req.strategy_params,
            symbols=req.symbols,
            timeframes=[TimeFrame(tf) for tf in req.timeframes],
            start_time=req.start_time,
            end_time=req.end_time,
            market=req.market,
            quote_currency=req.quote_currency,
            ins_type=TradeInsType(req.ins_type),
            initial_balance=Decimal(str(req.initial_balance)),
            executor_class=req.executor_class,
            executor_config=req.executor_config,
            param_space=req.param_space,
            optimization_objective=OptimizationObjective(req.optimization_objective),
            train_days=req.train_days,
            test_days=req.test_days,
            embargo_days=req.embargo_days,
            cv_splits=req.cv_splits,
            wf_window_mode=getattr(req, 'wf_window_mode', 'rolling'),
            max_workers=req.max_workers,
            min_window_size=req.min_window_size,
            risk_policies=req.risk_policies,
            data_source=req.data_source,
            data_source_config=req.data_source_config,
            mount_dirs=mount_dirs,
            use_cache=(req.use_cache if getattr(req, 'use_cache', None) is not None else bool(getattr(req, 'use_shared_memory_cache', False))),
            log_file=bool(getattr(req, 'log_file', False)),
            optuna_enabled=bool(getattr(req, 'optuna_enabled', False)),
            optuna_n_trials=int(getattr(req, 'optuna_n_trials', 80) or 80),
        )
        # 异步执行回测
        asyncio.create_task(self._execute_backtest_async(backtest_config))
    
    async def _execute_backtest_async(self, config: BacktestConfig):
        """异步执行回测"""
        try:
            # 更新任务状态
            self._update_task_status(config.id, "running", 0.0, datetime.now())
            
            times_metrics = []
            last_total = None
            import time as _time
            run_start = _time.time()
            # 设置进度/结果回调（支持第四参 window_data）
            def progress_callback(current: int, total: int, times: List[int], window_data: Dict[str, Any] | None = None):
                progress = current / total if total > 0 else 0.0
                if times is not None and isinstance(times, (list, tuple)) and len(times) >= 6:
                    logger.info(f"窗口进度[{config.id}/{config.name}]: {current} / {total}, "
                    f"初始化: {(times[1] - times[0])/1000}s, 加载数据: {(times[2] - times[1])/1000}s, "
                    f"预处理: {(times[3] - times[2])/1000}s, 回测: {(times[4] - times[3])/1000}s, "
                    f"指标: {(times[5] - times[4])/1000}s, 总时间: {(times[5] - times[0])/1000}s")
                    times_metrics.append(times)
                self._update_task_progress(config.id, progress)
                nonlocal last_total
                last_total = last_total or total
                # 若附带窗口数据，则缓存并可能批量落库
                if window_data is not None:
                    try:
                        result_callback(int(window_data.get("window_idx") or 0), str(window_data.get("symbol") or ""), str(window_data.get("timeframe") or ""), window_data)
                    except Exception:
                        logger.error("progress_callback result handling failed", exc_info=True)
            # 结果缓冲与聚合器
            windows_buffer: List[Dict[str, Any]] = []
            total_windows_emitted = 0
            zero_trade_windows_count = 0  # 统计0交易窗口数量
            # 参数推荐聚合（仅 WFA 使用）
            params_agg: Dict[str, Dict[str, Any]] = {}

            def _canon_key(obj: Dict[str, Any]) -> str:
                try:
                    return json.dumps(obj or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                except Exception:
                    return str(obj or {})

            def _median(xs: List[float]) -> float:
                if not xs:
                    return 0.0
                arr = sorted([x for x in xs if x is not None and x == x])
                if not arr:
                    return 0.0
                n = len(arr)
                return arr[n//2] if n % 2 == 1 else (arr[n//2 - 1] + arr[n//2]) / 2.0

            # 批量持久化：每10个窗口批量写入
            def flush_windows_batch():
                nonlocal windows_buffer, total_windows_emitted, zero_trade_windows_count
                if not windows_buffer:
                    return
                with db_connect() as _db:
                    task = _db.query(BacktestTask).filter(BacktestTask.id == config.id).first()
                    if not task:
                        windows_buffer = []
                        return
                    existing = list(task.windows or [])
                    to_append: List[Dict[str, Any]] = []
                    # 下采样配置
                    DOWNSAMPLE_MAX_POINTS = 1500
                    
                    for w in windows_buffer:
                        # 检查是否为0交易窗口
                        test_metrics = w.get("test_metrics") or w.get("metrics") or {}
                        total_trades = int(test_metrics.get("total_trades") or 0)
                        if total_trades == 0:
                            # 跳过0交易窗口，只统计数量
                            zero_trade_windows_count += 1
                            continue
                        
                        # 存储前下采样（在压缩之前）
                        from app.utils.series_codec import downsample_series
                        
                        equity_times = w.get("equity_times") or []
                        equity_values = w.get("equity_values") or []
                        drawdown_curve = w.get("drawdown_curve") or []
                        benchmark_curve = w.get("benchmark_curve") or []
                        
                        # 下采样净值曲线
                        if equity_values and len(equity_values) > DOWNSAMPLE_MAX_POINTS:
                            equity_times, equity_values = downsample_series(equity_times, equity_values, DOWNSAMPLE_MAX_POINTS)
                        
                        # 下采样回撤曲线
                        if drawdown_curve and len(drawdown_curve) > DOWNSAMPLE_MAX_POINTS:
                            _, drawdown_curve = downsample_series(None, drawdown_curve, DOWNSAMPLE_MAX_POINTS)
                        
                        # 下采样基准曲线
                        if benchmark_curve and len(benchmark_curve) > DOWNSAMPLE_MAX_POINTS:
                            _, benchmark_curve = downsample_series(None, benchmark_curve, DOWNSAMPLE_MAX_POINTS)
                        
                        # 压缩时间序列和曲线
                        compressed_times = encode_time_series(equity_times)
                        compressed_equity = encode_values(equity_values)
                        compressed_drawdown = encode_values(drawdown_curve) if drawdown_curve else None
                        compressed_benchmark = encode_values(benchmark_curve) if benchmark_curve else None
                        
                        # 精简数据：只保留必要的字段
                        payload = {
                            "window_idx": w.get("window_idx"),
                            "symbol": w.get("symbol"),
                            "timeframe": w.get("timeframe"),
                            # 训练/测试区间如有
                            "train_period": w.get("train_period"),
                            "test_period": w.get("test_period"),
                            # NORMAL 记录 params，WFA 记录 best_params
                            "params": w.get("params") or {},
                            "best_params": w.get("best_params") or {},
                            # 合并metrics字段，只保留一个
                            "test_metrics": test_metrics,
                            "equity_times": compressed_times,
                            "equity_values": compressed_equity,
                            "drawdown_curve": compressed_drawdown,
                            "benchmark_curve": compressed_benchmark,
                            # 移除trades和execution_time字段
                        }
                        to_append.append(sanitize_for_json(payload))
                    existing.extend(to_append)
                    task.windows = existing
                    task.windows_count = int((task.windows_count or 0) + len(to_append))
                    _db.commit()
                    total_windows_emitted += len(to_append)
                windows_buffer = []

            def result_callback(window_idx: int, symbol: str, timeframe: str, window_data: Dict[str, Any]):
                # 缓存窗口数据，满足批量条件再落库
                windows_buffer.append({
                    "window_idx": window_idx,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    **(window_data or {}),
                })
                # 参数推荐聚合（WFA：使用 best_params 与测试指标）
                best_params = (window_data or {}).get("best_params")
                test_metrics = (window_data or {}).get("test_metrics") or (window_data or {}).get("metrics") or {}
                if best_params is not None:
                    key = _canon_key(best_params)
                    bucket = params_agg.setdefault(key, {"params": best_params, "count": 0, "sharpe": [], "mdd": [], "annual": [], "profit_factor": []})
                    bucket["count"] += 1
                    try:
                        bucket["sharpe"].append(float(test_metrics.get("sharpe_ratio") or 0.0))
                    except Exception:
                        bucket["sharpe"].append(0.0)
                    try:
                        bucket["mdd"].append(float(test_metrics.get("max_drawdown") or 0.0))
                    except Exception:
                        bucket["mdd"].append(0.0)
                    try:
                        bucket["annual"].append(float(test_metrics.get("annual_return") or 0.0))
                    except Exception:
                        bucket["annual"].append(0.0)
                    try:
                        bucket["profit_factor"].append(float(test_metrics.get("profit_factor") or 0.0))
                    except Exception:
                        bucket["profit_factor"].append(0.0)

                # 每10个 flush 一次
                if len(windows_buffer) >= 10:
                    flush_windows_batch()

            # 创建回测器（结果通过 progress_callback 第四参传递）
            backtester = EnhancedBacktester(config, progress_callback)
            
            # 执行回测（在独立线程中运行，避免阻塞事件循环）
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as thread_executor:
                result = await asyncio.get_event_loop().run_in_executor(
                    thread_executor, backtester.run
                )
            
            # 计算并保存时间指标聚合（秒）
            if times_metrics:
                agg = await asyncio.to_thread(
                    self._aggregate_time_metrics,
                    times_metrics,
                    run_start,
                    result,
                    last_total,
                    config,
                )
                if agg and agg.get("stages"):
                    self._save_times_metrics(config.id, agg)
            
            # 处理结果（流式模式：仅生成 summary 与推荐信息，不重写已落库的 windows）
            with db_connect() as db:
                task = db.query(BacktestTask).filter(BacktestTask.id == config.id).first()
                if task:
                    # 最后一次 flush 余量
                    flush_windows_batch()
                    # 生成 summary
                    if isinstance(result, WalkForwardResult):
                        # 参数推荐
                        rankings: List[Dict[str, Any]] = []
                        total_windows = int(total_windows_emitted or 0)
                        for k, v in params_agg.items():
                            rankings.append({
                                "params_key": k,
                                "params": v.get("params") or {},
                                "count": int(v.get("count") or 0),
                                "coverage_ratio": (float(v.get("count") or 0) / float(total_windows or 1)),
                                "median_sharpe": _median(v.get("sharpe") or []),
                                "median_mdd": _median(v.get("mdd") or []),
                                "median_annual": _median(v.get("annual") or []),
                                "median_profit_factor": _median(v.get("profit_factor") or []),
                            })
                        rankings.sort(key=lambda r: (
                            r.get("count", 0),
                            r.get("median_sharpe", 0.0),
                            -abs(float(r.get("median_mdd", 0.0) or 0.0))
                        ), reverse=True)
                        recommendation: Dict[str, Any] = {}
                        if rankings:
                            top = rankings[0]
                            recommendation = {
                                "recommended_key": top.get("params_key"),
                                "recommended_params": top.get("params") or {},
                                "coverage": int(top.get("count") or 0),
                                "total_windows": total_windows,
                                "median_sharpe": top.get("median_sharpe", 0.0),
                                "median_mdd": top.get("median_mdd", 0.0),
                                "median_annual": top.get("median_annual", 0.0),
                                "median_profit_factor": top.get("median_profit_factor", 0.0),
                                "rankings": rankings[:10],
                            }
                        summary_data = {
                            "walk_forward": {
                                "total_windows": total_windows,
                                "zero_trade_windows_count": zero_trade_windows_count,
                                "aggregated_metrics": result.aggregated_metrics.to_dict(),
                                "execution_time": result.execution_time,
                                "windows_by_symbol": self._group_windows_by_symbol(task.windows or []),
                                "recommendation": recommendation,
                            }
                        }
                        # 写入 summary 与 artifacts
                        task.summary = sanitize_for_json(summary_data)
                        artifacts = dict(task.artifacts or {})
                        wf_artifacts = dict(artifacts.get("walk_forward", {}))
                        wf_artifacts["recommendation"] = recommendation or {}
                        artifacts["walk_forward"] = wf_artifacts
                        task.artifacts = sanitize_for_json(artifacts)
                        # 更新聚合指标
                        m = result.aggregated_metrics
                        task.sharpe_median = m.sharpe_ratio
                        task.mdd_median = m.max_drawdown
                        task.trades_median = float(m.total_trades)
                        task.total_return = m.total_return
                        task.annual_return = m.annual_return
                        task.total_trades = m.total_trades
                        task.profit_factor = m.profit_factor
                        task.win_loss_ratio = m.win_loss_ratio
                        task.avg_win = m.avg_win
                        task.avg_loss = m.avg_loss
                        task.win_rate = m.win_rate
                        task.trade_win_rate = m.win_rate
                    elif isinstance(result, NormalBacktestResult):
                        # 组合曲线：读取已落库窗口，解压并按等权步进聚合
                        try:
                            from app.utils.series_codec import decode_time_series, decode_values
                            all_windows = list(task.windows or [])
                            series_list = []
                            for w in all_windows:
                                try:
                                    t = decode_time_series(w.get("equity_times")) if isinstance(w.get("equity_times"), dict) else (w.get("equity_times") or [])
                                    v = decode_values(w.get("equity_values")) if isinstance(w.get("equity_values"), dict) else (w.get("equity_values") or [])
                                    if t and v and len(t) == len(v):
                                        series_list.append((t, v))
                                except Exception:
                                    continue
                            union_times = sorted({tt for (ts, _) in series_list for tt in ts}) if series_list else []
                            combined_values: List[float] = []
                            if union_times:
                                # 初始等权净值
                                initial_values = [float(vals[0]) for (_, vals) in series_list if vals]
                                combined_current = (sum(initial_values) / float(len(initial_values))) if initial_values else 1.0
                                last_equities = [float(vals[0]) if vals else 0.0 for (_, vals) in series_list]
                                idx_by_series = [0 for _ in series_list]
                                combined_values.append(combined_current)
                                for t in union_times[1:]:
                                    step_returns = []
                                    for i, (times_i, vals_i) in enumerate(series_list):
                                        idx = idx_by_series[i]
                                        while idx + 1 < len(times_i) and times_i[idx + 1] <= t:
                                            idx += 1
                                            idx_by_series[i] = idx
                                            last_equities[i] = float(vals_i[idx])
                                        if idx >= 1:
                                            prev_eq = float(vals_i[idx - 1])
                                            curr_eq = float(vals_i[idx])
                                            ret = (curr_eq / prev_eq - 1.0) if prev_eq != 0 else 0.0
                                        else:
                                            ret = 0.0
                                        step_returns.append(ret)
                                    avg_ret = sum(step_returns) / float(len(step_returns)) if step_returns else 0.0
                                    combined_current = combined_current * (1.0 + avg_ret)
                                    combined_values.append(combined_current)
                            # 下采样组合曲线
                            DOWNSAMPLE_MAX_POINTS = 1500
                            if combined_values and len(combined_values) > DOWNSAMPLE_MAX_POINTS:
                                from app.utils.series_codec import downsample_series
                                union_times, combined_values = downsample_series(union_times, combined_values, DOWNSAMPLE_MAX_POINTS)
                            combined = {
                                "equity_times": encode_time_series(union_times) if union_times else None,
                                "equity_values": encode_values(combined_values) if combined_values else None,
                            }
                        except Exception:
                            combined = {"equity_times": None, "equity_values": None}
                        summary_data = {
                            "normal": {
                                "zero_trade_windows_count": zero_trade_windows_count,
                                "aggregated_metrics": result.aggregated_metrics.to_dict(),
                                "combined": combined,
                                "execution_time": result.execution_time,
                            }
                        }
                        task.summary = sanitize_for_json(summary_data)
                        # 更新聚合指标（来自 core 汇总）
                        m = result.aggregated_metrics
                        task.sharpe_median = m.sharpe_ratio
                        task.mdd_median = m.max_drawdown
                        task.trades_median = float(m.total_trades)
                        task.turnover_median = m.turnover
                        task.pnl_median = m.total_return
                        # 关键展示指标：总收益率/年化收益率
                        task.total_return = m.total_return
                        task.annual_return = m.annual_return
                        task.win_rate = m.win_rate
                        task.trade_win_rate = m.win_rate
                        task.long_win_rate = m.long_win_rate
                        task.short_win_rate = m.short_win_rate
                        # 窗口合计整数字段
                        task.total_trades = int(m.total_trades or 0)
                        task.profit_factor = m.profit_factor
                        task.win_loss_ratio = m.win_loss_ratio
                        task.avg_win = m.avg_win
                        task.avg_loss = m.avg_loss
                        # 盈亏合计与次数（使用聚合估计）
                        task.profit_sum = m.avg_win * float(m.win_trades or 0)
                        task.loss_sum = abs(m.avg_loss) * float(m.loss_trades or 0)
                        task.profit_count = int(m.win_trades or 0)
                        task.loss_count = int(m.loss_trades or 0)
                    else:
                        # 单次回测：已在回调中写入窗口，此处写简要 summary
                        summary_data = {
                            "single_result": {
                                "metrics": result.metrics.to_dict() if hasattr(result, 'metrics') else {},
                                "execution_time": getattr(result, 'execution_time', 0.0),
                                "metadata": getattr(result, 'metadata', {}) or {}
                            }
                        }
                        task.summary = sanitize_for_json(summary_data)
                    db.commit()
            
            # 更新任务状态为完成
            self._update_task_status(config.id, "completed", 1.0, finished_at=datetime.now())
        
        except Exception as e:
            logger.error(f"Backtest task {config.id} failed: {e}")
            logger.error(traceback.format_exc())
            
            # 更新任务状态为失败
            self._update_task_status(
                config.id, "failed", 
                error=str(e)[:2000],  # 限制错误信息长度
                finished_at=datetime.now()
            )
        
        finally:
            # 清理运行中的任务记录
            self.running_tasks.pop(config.id, None)
    
    async def _process_backtest_result(self, task_id: int, result):
        """处理回测结果"""
        with db_connect() as db:
            if isinstance(result, BacktestResult):
                await self._process_single_backtest_result(db, task_id, result)
            elif isinstance(result, WalkForwardResult):
                await self._process_walk_forward_result(db, task_id, result)
            elif isinstance(result, NormalBacktestResult):
                await self._process_normal_backtest_result(db, task_id, result)
            else:
                raise ValueError(f"Unknown result type: {type(result)}")
    
    async def _process_single_backtest_result(self, db: Session, task_id: int, result: BacktestResult):
        """处理单次回测结果"""
        
        # 压缩时间序列和净值曲线
        compressed_times = encode_time_series(result.equity_times)
        compressed_equity = encode_values(result.equity_curve)
        compressed_drawdown = encode_values(result.drawdown_curve) if result.drawdown_curve else None
        compressed_benchmark = encode_values(result.benchmark_curve) if result.benchmark_curve else None
        
        # 构建窗口数据（单次回测只有一个窗口）
        window_data = {
            "symbol": result.config["symbol"],
            "timeframe": result.config["timeframe"],
            "train": None,
            "test": (str(result.config["start_time"]), str(result.config["end_time"])),
            "params": result.config["strategy_params"] or {},
            "metrics": result.metrics.to_dict(),
            "equity_times": compressed_times,
            "equity_values": compressed_equity,
            "drawdown_curve": compressed_drawdown,
            "benchmark_curve": compressed_benchmark,
            "trades": result.trades,
            "execution_time": result.execution_time
        }
        
        # 构建汇总数据
        summary_data = {
            "single_result": {
                "metrics": result.metrics.to_dict(),
                "execution_time": result.execution_time,
                "metadata": result.metadata or {}
            }
        }
        
        # 更新数据库
        task = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
        if task:
            # 清洗 JSON 字段，避免 NaN/Inf 进入 DB
            task.windows = sanitize_for_json([window_data])
            task.summary = sanitize_for_json(summary_data)
            task.windows_count = 1
            
            # 更新冗余字段
            metrics = result.metrics
            task.sharpe_median = metrics.sharpe_ratio
            task.sharpe_p25 = metrics.sharpe_ratio
            task.mdd_median = metrics.max_drawdown
            task.trades_median = float(metrics.total_trades)
            task.turnover_median = metrics.turnover
            task.pnl_median = metrics.total_return * float(result.config["initial_balance"])
            task.win_rate = metrics.win_rate
            task.trade_win_rate = metrics.win_rate
            task.long_win_rate = metrics.long_win_rate
            task.short_win_rate = metrics.short_win_rate
            task.total_return = metrics.total_return
            task.annual_return = metrics.annual_return
            task.total_trades = metrics.total_trades
            task.profit_factor = metrics.profit_factor
            task.win_loss_ratio = metrics.win_loss_ratio
            task.avg_win = metrics.avg_win
            task.avg_loss = metrics.avg_loss
            task.profit_sum = metrics.avg_win * metrics.win_trades if metrics.win_trades > 0 else 0.0
            task.loss_sum = metrics.avg_loss * metrics.loss_trades if metrics.loss_trades > 0 else 0.0
            task.profit_count = metrics.win_trades
            task.loss_count = metrics.loss_trades
            
            db.commit()
    
    async def _process_walk_forward_result(self, db: Session, task_id: int, result: WalkForwardResult):
        """处理Walk-Forward回测结果"""
        
        # 构建窗口数据
        windows_data = []
        for window_result in result.window_results:
            # 压缩测试期数据
            test_result = window_result.test_result
            compressed_times = encode_time_series(test_result.equity_times)
            compressed_equity = encode_values(test_result.equity_curve)
            compressed_drawdown = encode_values(test_result.drawdown_curve) if test_result.drawdown_curve else None
            
            window_data = {
                "window_idx": window_result.window_idx,
                "symbol": window_result.symbol,
                "timeframe": window_result.timeframe,
                "train_period": (str(window_result.train_period[0]), str(window_result.train_period[1])),
                "test_period": (str(window_result.test_period[0]), str(window_result.test_period[1])),
                "best_params": window_result.best_params,
                "test_metrics": test_result.metrics.to_dict(),
                "equity_times": compressed_times,
                "equity_values": compressed_equity,
                "drawdown_curve": compressed_drawdown,
                "trades": test_result.trades[:100],  # 限制交易记录数量
                "test_trades": len(test_result.trades),
                "win_trades": test_result.metrics.win_trades,
                "execution_time": test_result.execution_time
            }
            
            # 如果有训练结果，也包含训练指标
            if window_result.train_result:
                window_data["train_metrics"] = window_result.train_result.metrics.to_dict()
            
            windows_data.append(window_data)
        
        # 构建汇总数据
        # 计算参数推荐（基于各窗口选出的best_params的稳健度：出现频次和指标中位数）
        def _canon_key(obj: Dict[str, Any]) -> str:
            try:
                return json.dumps(obj or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                return str(obj or {})

        # 聚合每组参数在测试窗口中的表现
        params_agg: Dict[str, Dict[str, Any]] = {}
        for w in windows_data:
            p = w.get("best_params") or {}
            key = _canon_key(p)
            m = (w.get("test_metrics") or {})
            bucket = params_agg.setdefault(key, {"params": p, "count": 0, "sharpe": [], "mdd": [], "annual": [], "profit_factor": []})
            bucket["count"] += 1
            # 指标采样
            try:
                bucket["sharpe"].append(float(m.get("sharpe_ratio") or 0.0))
            except Exception:
                bucket["sharpe"].append(0.0)
            try:
                bucket["mdd"].append(float(m.get("max_drawdown") or 0.0))
            except Exception:
                bucket["mdd"].append(0.0)
            try:
                bucket["annual"].append(float(m.get("annual_return") or 0.0))
            except Exception:
                bucket["annual"].append(0.0)
            try:
                bucket["profit_factor"].append(float(m.get("profit_factor") or 0.0))
            except Exception:
                bucket["profit_factor"].append(0.0)

        def _median(xs: List[float]) -> float:
            if not xs:
                return 0.0
            arr = sorted([x for x in xs if x is not None and x == x])
            if not arr:
                return 0.0
            n = len(arr)
            return arr[n//2] if n % 2 == 1 else (arr[n//2 - 1] + arr[n//2]) / 2.0

        rankings: List[Dict[str, Any]] = []
        total_windows = len(windows_data)
        for k, v in params_agg.items():
            rankings.append({
                "params_key": k,
                "params": v.get("params") or {},
                "count": int(v.get("count") or 0),
                "coverage_ratio": (float(v.get("count") or 0) / float(total_windows or 1)),
                "median_sharpe": _median(v.get("sharpe") or []),
                "median_mdd": _median(v.get("mdd") or []),
                "median_annual": _median(v.get("annual") or []),
                "median_profit_factor": _median(v.get("profit_factor") or []),
            })

        # 排序：优先覆盖率（count）降序，其次Sharpe中位数降序，再次回撤中位数绝对值升序
        rankings.sort(key=lambda r: (
            r.get("count", 0),
            r.get("median_sharpe", 0.0),
            -abs(float(r.get("median_mdd", 0.0) or 0.0))
        ), reverse=True)

        recommendation: Dict[str, Any] = {}
        if rankings:
            top = rankings[0]
            recommendation = {
                "recommended_key": top.get("params_key"),
                "recommended_params": top.get("params") or {},
                "coverage": int(top.get("count") or 0),
                "total_windows": total_windows,
                "median_sharpe": top.get("median_sharpe", 0.0),
                "median_mdd": top.get("median_mdd", 0.0),
                "median_annual": top.get("median_annual", 0.0),
                "median_profit_factor": top.get("median_profit_factor", 0.0),
                "rankings": rankings[:10],
            }

        summary_data = {
            "walk_forward": {
                "total_windows": len(windows_data),
                "aggregated_metrics": result.aggregated_metrics.to_dict(),
                "execution_time": result.execution_time,
                # 添加窗口统计
                "windows_by_symbol": self._group_windows_by_symbol(windows_data),
                # 参数推荐
                "recommendation": recommendation,
            }
        }
        
        # 计算聚合指标
        all_metrics = [wr.test_result.metrics for wr in result.window_results]
        sharpe_values = [m.sharpe_ratio for m in all_metrics]
        mdd_values = [m.max_drawdown for m in all_metrics]
        trades_values = [float(m.total_trades) for m in all_metrics]
        
        # 更新数据库
        task = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
        if task:
            task.windows = sanitize_for_json(windows_data)
            task.summary = sanitize_for_json(summary_data)
            task.windows_count = len(windows_data)
            # 写入 artifacts：保存WFA推荐信息，避免污染summary结构
            artifacts = dict(task.artifacts or {})
            wf_artifacts = dict(artifacts.get("walk_forward", {}))
            wf_artifacts["recommendation"] = recommendation or {}
            artifacts["walk_forward"] = wf_artifacts
            task.artifacts = sanitize_for_json(artifacts)
            
            # 更新聚合指标（使用整体聚合后的指标）
            metrics = result.aggregated_metrics
            task.sharpe_median = metrics.sharpe_ratio
            task.sharpe_p25 = self._calculate_percentile(sharpe_values, 25)
            task.mdd_median = self._calculate_median(mdd_values)
            task.trades_median = self._calculate_median(trades_values)
            task.total_return = metrics.total_return
            task.annual_return = metrics.annual_return
            task.total_trades = metrics.total_trades
            task.profit_factor = metrics.profit_factor
            task.win_loss_ratio = metrics.win_loss_ratio
            task.avg_win = metrics.avg_win
            task.avg_loss = metrics.avg_loss
            task.win_rate = metrics.win_rate
            task.trade_win_rate = metrics.win_rate
            
            # 计算盈亏合计
            task.profit_sum = metrics.avg_win * metrics.win_trades if metrics.win_trades > 0 else 0.0
            task.loss_sum = abs(metrics.avg_loss) * metrics.loss_trades if metrics.loss_trades > 0 else 0.0
            task.profit_count = metrics.win_trades
            task.loss_count = metrics.loss_trades
            
            db.commit()

    async def _process_normal_backtest_result(self, db: Session, task_id: int, result: NormalBacktestResult):
        """处理普通回测结果（多标的 × 多周期）"""
        windows_data = []
        for br in result.results:
            compressed_times = encode_time_series(br.equity_times)
            compressed_equity = encode_values(br.equity_curve)
            compressed_drawdown = encode_values(br.drawdown_curve) if br.drawdown_curve else None
            compressed_benchmark = encode_values(br.benchmark_curve) if br.benchmark_curve else None

            window_data = {
                "symbol": br.config["symbol"],
                "timeframe": br.config["timeframe"],
                "params": br.config.get("strategy_params") or {},
                "metrics": br.metrics.to_dict(),
                "equity_times": compressed_times,
                "equity_values": compressed_equity,
                "drawdown_curve": compressed_drawdown,
                "benchmark_curve": compressed_benchmark,
                "trades": br.trades[:100] if isinstance(br.trades, list) else [],
                "execution_time": br.execution_time,
            }
            windows_data.append(sanitize_for_json(window_data))

        # 组合曲线压缩
        combined = {
            "equity_times": encode_time_series(result.combined_equity_times) if result.combined_equity_times else None,
            "equity_values": encode_values(result.combined_equity_values) if result.combined_equity_values else None,
        }

        summary_data = {
            "normal": {
                "aggregated_metrics": result.aggregated_metrics.to_dict(),
                "combined": combined,
                "execution_time": result.execution_time,
            }
        }

        task = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
        if task:
            task.windows = sanitize_for_json(windows_data)
            task.summary = sanitize_for_json(summary_data)
            task.windows_count = len(windows_data)

            metrics = result.aggregated_metrics
            task.sharpe_median = metrics.sharpe_ratio
            task.mdd_median = metrics.max_drawdown
            task.trades_median = float(metrics.total_trades)
            task.turnover_median = metrics.turnover
            task.pnl_median = metrics.total_return  # 绝对金额可按需要另外计算
            task.win_rate = metrics.win_rate
            task.trade_win_rate = metrics.win_rate
            task.long_win_rate = metrics.long_win_rate
            task.short_win_rate = metrics.short_win_rate
            task.total_return = metrics.total_return
            task.annual_return = metrics.annual_return
            # 确保整数字段使用整数值：按窗口求和
            try:
                total_trades_sum = int(sum(int(getattr(br.metrics, 'total_trades', 0) or 0) for br in result.results))
            except Exception:
                total_trades_sum = int(metrics.total_trades or 0)
            task.total_trades = total_trades_sum
            task.profit_factor = metrics.profit_factor
            task.win_loss_ratio = metrics.win_loss_ratio
            task.avg_win = metrics.avg_win
            task.avg_loss = metrics.avg_loss
            # 盈亏合计和次数（使用窗口求和得到整数）
            try:
                win_trades_sum = int(sum(int(getattr(br.metrics, 'win_trades', 0) or 0) for br in result.results))
                loss_trades_sum = int(sum(int(getattr(br.metrics, 'loss_trades', 0) or 0) for br in result.results))
            except Exception:
                win_trades_sum = int(getattr(metrics, 'win_trades', 0) or 0)
                loss_trades_sum = int(getattr(metrics, 'loss_trades', 0) or 0)
            task.profit_sum = metrics.avg_win * float(win_trades_sum) if win_trades_sum > 0 else 0.0
            task.loss_sum = abs(metrics.avg_loss) * float(loss_trades_sum) if loss_trades_sum > 0 else 0.0
            task.profit_count = win_trades_sum
            task.loss_count = loss_trades_sum

            db.commit()
    
    def _group_windows_by_symbol(self, windows_data: List[Dict]) -> Dict[str, List[int]]:
        """按标的分组窗口"""
        groups = {}
        for window in windows_data:
            symbol = window.get("symbol", "unknown")
            if symbol not in groups:
                groups[symbol] = []
            groups[symbol].append(window["window_idx"])
        return groups
    
    def _update_task_status(
        self, 
        task_id: int, 
        status: str, 
        progress: Optional[float] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        error: Optional[str] = None
    ):
        """更新任务状态"""
        with db_connect() as db:
            task = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
            if task:
                task.status = status
                if progress is not None:
                    task.progress = progress
                if started_at is not None:
                    task.started_at = started_at
                if finished_at is not None:
                    task.finished_at = finished_at
                if error is not None:
                    task.error = error
                db.commit()
    
    def _update_task_progress(self, task_id: int, progress: float):
        """更新任务进度"""
        with db_connect() as db:
            task = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
            if task:
                task.progress = progress
                db.commit()

    def _save_times_metrics(self, task_id: int, metrics_json: Dict[str, Any]):
        """保存时间指标聚合到任务表 times_metrics 字段"""
        with db_connect() as db:
            task = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
            if task:
                try:
                    task.times_metrics = metrics_json
                    db.commit()
                except Exception as e:
                    logger.error(f"Failed to save times_metrics for task {task_id}: {e}")
    
    def _aggregate_time_metrics(self, times_metrics: List[List[int]], run_start: float, result: Any, last_total: Optional[int], config: BacktestConfig) -> Dict[str, Any]:
        """在后台线程聚合时间指标，返回聚合结果。"""
        import time as _time
        if not times_metrics:
            return {}
        stage_names = [
            "init", "get_data", "skip_data", "backtest", "metrics", "total"
        ]
        durations_by_stage = {name: [] for name in stage_names}

        for t in times_metrics:
            try:
                if not isinstance(t, (list, tuple)) or len(t) < 6:
                    continue
                d_init = (t[1] - t[0]) / 1000.0
                d_get = (t[2] - t[1]) / 1000.0
                d_skip = (t[3] - t[2]) / 1000.0
                d_bt = (t[4] - t[3]) / 1000.0
                d_met = (t[5] - t[4]) / 1000.0
                d_tot = (t[5] - t[0]) / 1000.0
                vals = [d_init, d_get, d_skip, d_bt, d_met, d_tot]
                if any(v is None or v != v for v in vals):
                    continue
                durations_by_stage["init"].append(max(d_init, 0.0))
                durations_by_stage["get_data"].append(max(d_get, 0.0))
                durations_by_stage["skip_data"].append(max(d_skip, 0.0))
                durations_by_stage["backtest"].append(max(d_bt, 0.0))
                durations_by_stage["metrics"].append(max(d_met, 0.0))
                durations_by_stage["total"].append(max(d_tot, 0.0))
            except Exception:
                continue

        agg: Dict[str, Any] = {"unit": "seconds", "count": 0, "stages": {}}
        for name in stage_names:
            ds = durations_by_stage.get(name, [])
            if not ds:
                continue
            n = len(ds)
            agg["count"] = max(agg.get("count", 0), n)
            m = round(float(mean(ds)), 3)
            med = round(float(median(ds)), 3)
            p95 = round(float(self._calculate_percentile(ds, 95)), 3)
            p99 = round(float(self._calculate_percentile(ds, 99)), 3)
            agg["stages"][name] = {
                "mean": m,
                "median": med,
                "p95": p95,
                "p99": p99,
            }

        agg["total_time_sec"] = round(_time.time() - run_start, 3)
        agg["execution_time"] = round(getattr(result, 'execution_time', 0), 3)
        agg["window_count"] = int(last_total or 0)
        agg["concurrency"] = int(getattr(config, 'max_workers', 1) or 1)
        return agg
    
    def _calculate_median(self, values: List[float]) -> float:
        """计算中位数"""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        n = len(sorted_values)
        if n % 2 == 0:
            return (sorted_values[n//2 - 1] + sorted_values[n//2]) / 2
        else:
            return sorted_values[n//2]
    
    def _calculate_percentile(self, values: List[float], percentile: float) -> float:
        """计算百分位数"""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        k = (len(sorted_values) - 1) * percentile / 100.0
        f = int(k)
        c = min(f + 1, len(sorted_values) - 1)
        if f == c:
            return sorted_values[int(k)]
        d0 = sorted_values[f] * (c - k)
        d1 = sorted_values[c] * (k - f)
        return d0 + d1
    
    async def cancel_backtest_task(self, db: Session, task_id: int) -> bool:
        """取消回测任务"""
        task = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
        if not task:
            return False
        
        if task.status in ["pending", "running"]:
            task.status = "cancelled"
            task.finished_at = datetime.now()
            db.commit()
            
            # 如果任务正在运行，尝试停止
            if task_id in self.running_tasks:
                # TODO: 实现任务取消逻辑
                pass
            
            return True
        
        return False
    
    async def get_backtest_task_with_decompressed_data(
        self, 
        db: Session, 
        task_id: int, 
        expand_series: bool = False
    ) -> Optional[BacktestTask]:
        """获取回测任务并解压数据"""
        from app.utils.series_codec import decode_time_series, decode_values
        
        task = db.query(BacktestTask).filter(BacktestTask.id == task_id).first()
        if not task:
            return None
        
        # 如果需要展开序列数据
        if expand_series and task.windows:
            try:
                decompressed_windows = []
                for window in task.windows:
                    if not isinstance(window, dict):
                        decompressed_windows.append(window)
                        continue
                    
                    window_copy = dict(window)
                    
                    # 解压时间序列
                    if "equity_times" in window_copy and isinstance(window_copy["equity_times"], dict):
                        window_copy["equity_times"] = decode_time_series(window_copy["equity_times"])
                    
                    # 解压净值序列
                    if "equity_values" in window_copy and isinstance(window_copy["equity_values"], dict):
                        window_copy["equity_values"] = decode_values(window_copy["equity_values"])
                    
                    # 解压回撤序列
                    if "drawdown_curve" in window_copy and isinstance(window_copy["drawdown_curve"], dict):
                        window_copy["drawdown_curve"] = decode_values(window_copy["drawdown_curve"])
                    
                    # 解压基准曲线序列
                    if "benchmark_curve" in window_copy and isinstance(window_copy["benchmark_curve"], dict):
                        window_copy["benchmark_curve"] = decode_values(window_copy["benchmark_curve"])
                    
                    decompressed_windows.append(window_copy)
                
                task.windows = decompressed_windows
                
            except Exception as e:
                logger.error(f"Failed to decompress data for task {task_id}: {e}")
        
        return task


# 全局服务实例
enhanced_backtest_service = EnhancedBacktestService()
