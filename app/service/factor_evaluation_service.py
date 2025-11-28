#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import traceback
import concurrent.futures
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np
import multiprocessing

from sqlalchemy.orm import Session
from app.models.factor_evaluation import FactorEvaluationTask
from app.models.factor import Factor as FactorModel
from app.models.backtest_config import BacktestConfig as BacktestConfigModel
from app.db.session import db_connect
from app.schemas.factor_evaluation import FactorEvaluationCreate
from leek_core.models import TimeFrame, TradeInsType
from leek_core.utils import get_logger, DateTimeUtils
from leek_core.backtest.factor_evaluation import FactorEvaluatorExecutor
from leek_core.backtest.types import FactorEvaluationConfig
from app.utils.json_sanitize import sanitize_for_json
from app.utils.series_codec import encode_time_series, encode_values, downsample_series

logger = get_logger(__name__)


class FactorEvaluationService:
    """因子评价服务"""
    
    def __init__(self):
        self.running_tasks: Dict[int, Any] = {}
    
    async def create_evaluation_task(
        self, 
        task: FactorEvaluationTask, 
        req: FactorEvaluationCreate
    ):
        """创建因子评价任务"""
        # 初始化任务状态
        task_id = task.id
        self.running_tasks[task_id] = {
            'status': 'pending',
            'progress': 0.0,
            'factors': {},
            'total_tasks': 0,
            'completed_tasks': 0,
            'data_analysis_status': 'pending',
            'data_storage_status': 'pending',
            'data_merge_status': 'pending',
            'correlation_status': 'pending',
            'summary_status': 'pending'
        }
        # 异步执行评价
        asyncio.create_task(self._execute_evaluation_async(task, req))
    
    async def _execute_evaluation_async(
        self, 
        task: FactorEvaluationTask, 
        req: FactorEvaluationCreate
    ):
        """异步执行因子评价"""
        # 在 session 关闭前保存 task_id，避免 DetachedInstanceError
        task_id = task.id
        logger.info(f"[Task {task_id}] Starting async evaluation execution")
        
        try:
            self._update_task_status(task_id, "running", 0.0, datetime.now())
            
            # 更新 running_tasks 状态
            if task_id in self.running_tasks:
                self.running_tasks[task_id]['status'] = 'running'
            
            # 加载配置
            data_config, factors, market_config = self._load_evaluation_config(req)
            
            # 构建 FactorEvaluationConfig
            eval_config = self._build_evaluation_config(task_id, req, data_config, factors, market_config)
            
            # 初始化任务状态：计算总任务数和每个因子的任务
            total_tasks = len(req.symbols) * len(req.timeframes) * len(req.factor_ids)
            factor_tasks = {}
            for factor in factors:
                factor_tasks[factor.id] = {
                    'factor_id': factor.id,
                    'factor_name': factor.name,
                    'tasks': {}  # key: symbol_timeframe, value: status
                }
                for symbol in req.symbols:
                    for timeframe in req.timeframes:
                        task_key = f"{symbol}_{timeframe}"
                        factor_tasks[factor.id]['tasks'][task_key] = {
                            'symbol': symbol,
                            'timeframe': timeframe,
                            'status': 'pending'  # pending | running | completed | failed
                        }
            
            # 更新 running_tasks
            if task_id in self.running_tasks:
                self.running_tasks[task_id].update({
                    'status': 'running',
                    'progress': 0.0,
                    'factors': factor_tasks,
                    'total_tasks': total_tasks,
                    'completed_tasks': 0
                })
            
            # 设置进度回调，更新每个任务的状态
            completed_count = 0
            total_tasks = len(req.symbols) * len(req.timeframes)
            
            def progress_callback(symbol: str, timeframe: str, factor_ids: List[int], status: str):
                nonlocal completed_count
                try:
                    if task_id not in self.running_tasks:
                        return
                    
                    task_state = self.running_tasks[task_id]
                    factors = task_state.get('factors', {})
                    
                    # 更新每个因子的任务状态
                    for factor_id in factor_ids:
                        if factor_id in factors:
                            task_key = f"{symbol}_{timeframe}"
                            if task_key in factors[factor_id]['tasks']:
                                factors[factor_id]['tasks'][task_key]['status'] = status
                    
                    # 统计完成的任务数
                    if status in ['completed', 'NoResult', 'failed']:
                        completed_count += 1
                    
                    # 更新总体进度
                    progress = min(0.9, completed_count / total_tasks) if total_tasks > 0 else 0.0
                    task_state['completed_tasks'] = completed_count
                    task_state['progress'] = progress
                    self._update_task_progress(task_id, progress)
                except Exception as e:
                    logger.error(f"[Task {task_id}] Progress callback failed: {e}", exc_info=True)
            
            # 设置子阶段进度回调
            def subphase_callback(phase_name: str, status: str):
                try:
                    if task_id not in self.running_tasks:
                        return
                    
                    task_state = self.running_tasks[task_id]
                    status_field_map = {
                        'data_merge': 'data_merge_status',
                        'correlation': 'correlation_status',
                        'summary': 'summary_status'
                    }
                    status_field = status_field_map.get(phase_name)
                    if status_field:
                        task_state[status_field] = status
                except Exception as e:
                    logger.error(f"[Task {task_id}] Subphase callback failed: {e}", exc_info=True)
            
            # 执行评价（在独立线程中运行，避免阻塞事件循环）
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as thread_executor:
                    executor = FactorEvaluatorExecutor(eval_config, progress_callback, subphase_callback)
                    final_result = await asyncio.get_event_loop().run_in_executor(
                        thread_executor, 
                        executor.evaluate
                    )
            
            # 所有任务完成，进入数据分析阶段
            if task_id in self.running_tasks:
                self.running_tasks[task_id]['data_analysis_status'] = 'running'
                self.running_tasks[task_id]['progress'] = 0.92
                self._update_task_progress(task_id, 0.92)
            
            # Executor 已经处理了所有数据，直接获取结果
            summary = final_result.get('summary', {})
            factor_metrics = final_result.get('metrics', [])
            evaluation_results = final_result.get('evaluation_results', {})
            correlation_matrix = final_result.get('correlation_matrix', {})
            
            # 添加因子名称到 metrics 和 evaluation_results（需要从 factors 获取）
            factor_map = {factor.id: factor for factor in factors}
            for metric in factor_metrics:
                factor_id = metric.get('factor_id')
                if factor_id in factor_map:
                    factor_model = factor_map[factor_id]
                    output_name = metric.get('output_name', '')
                    metric['factor_name'] = f"{factor_model.name}_{output_name}" if output_name else factor_model.name
            
            # 为 evaluation_results 添加 factor_name（用于生成图表）
            for factor_key, result in evaluation_results.items():
                factor_id = result.get('factor_id')
                if factor_id in factor_map:
                    factor_model = factor_map[factor_id]
                    output_name = result.get('output_name', factor_key.split('_', 1)[1] if '_' in factor_key else '')
                    result['factor_name'] = f"{factor_model.name}_{output_name}" if output_name else factor_model.name
            
            # 数据分析完成，进入数据压缩入库阶段
            if task_id in self.running_tasks:
                self.running_tasks[task_id]['data_analysis_status'] = 'completed'
                self.running_tasks[task_id]['data_storage_status'] = 'running'
                self.running_tasks[task_id]['progress'] = 0.96
                self._update_task_progress(task_id, 0.96)
            
            # 生成图表数据（压缩）- 需要压缩工具，在 Service 层完成
            charts = self._generate_chart_data(
                task_id, evaluation_results, correlation_matrix
            )
            
            # 保存结果
            with db_connect() as db:
                task = db.query(FactorEvaluationTask).filter(
                    FactorEvaluationTask.id == task_id
                ).first()
                # 保存评价结果（已压缩）
                task.summary = sanitize_for_json(summary)
                task.metrics = sanitize_for_json(factor_metrics)
                task.charts = sanitize_for_json(charts)
                
                # 更新汇总指标
                task.ic_mean = summary.get('ic_mean')
                task.ir = summary.get('ir')
                task.ic_win_rate = summary.get('ic_win_rate')
                task.factor_count = len(req.factor_ids)
                
                # 确保进度和状态正确
                task.progress = 1.0
                task.status = "completed"
                task.finished_at = datetime.now()
                
                db.commit()
            
            # 数据压缩入库完成
            if task_id in self.running_tasks:
                self.running_tasks[task_id]['data_storage_status'] = 'completed'
            
            # 再次更新任务状态为完成（确保状态正确）
            self._update_task_status(task_id, "completed", 1.0, finished_at=datetime.now())
            
            # 清理 running_tasks
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
            logger.info(f"[Task {task_id}] Async evaluation execution completed successfully")
        except Exception as e:
            logger.error(f"Factor evaluation task {task_id} failed: {e}", exc_info=True)
            # 更新任务状态为失败
            self._update_task_status(
                task_id, "failed", 
                0.0, 
                finished_at=datetime.now(),
                error=str(e)[:2000]
            )
            
            # 清理 running_tasks
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
    
    def _load_evaluation_config(
        self,
        req: FactorEvaluationCreate
    ) -> tuple[BacktestConfigModel, List[FactorModel], Dict[str, Any]]:
        """加载评价配置"""
        with db_connect() as db:
            data_config = db.query(BacktestConfigModel).filter(
                BacktestConfigModel.id == req.data_config_id
            ).first()
            
            if not data_config:
                raise ValueError(f"Data config {req.data_config_id} not found")
            
            factors = db.query(FactorModel).filter(
                FactorModel.id.in_(req.factor_ids),
                FactorModel.is_deleted == False
            ).all()
            
            if not factors:
                raise ValueError("No factors found")
            
            # 解析数据配置的extra字段
            extra = data_config.extra or {}
            market = extra.get('market', 'okx')
            quote_currency = extra.get('quote_currency', 'USDT')
            ins_type_str = extra.get('ins_type')
            
            return data_config, factors, {
                'market': market,
                'quote_currency': quote_currency,
                'ins_type_str': ins_type_str
            }
    
    def _build_evaluation_config(
        self,
        task_id: int,
        req: FactorEvaluationCreate,
        data_config: BacktestConfigModel,
        factors: List[FactorModel],
        market_config: Dict[str, Any]
    ) -> FactorEvaluationConfig:
        """构建 FactorEvaluationConfig"""
        # 构建两个字典：id 作为 key
        factor_classes_dict = {}
        factor_params_dict = {}
        for factor in factors:
            factor_classes_dict[factor.id] = factor.class_name
            factor_params_dict[factor.id] = factor.params or {}
        # 确定 worker 数量
        max_workers = req.max_workers or 1
        # 转换合约类型
        ins_type_str = market_config.get('ins_type_str')
        ins_type = TradeInsType(ins_type_str) if ins_type_str else TradeInsType.SWAP
        
        config = FactorEvaluationConfig(
            id=task_id,
            name=req.name or f"Factor Evaluation {task_id}",
            symbols=req.symbols,
            timeframes=req.timeframes,
            start_time=req.start_time,
            end_time=req.end_time,
            market=market_config['market'],
            quote_currency=market_config['quote_currency'],
            ins_type=ins_type,
            factor_classes=factor_classes_dict,
            factor_params=factor_params_dict,
            data_source_class=data_config.class_name,
            data_source_config=data_config.params or {},
            future_periods=req.future_periods,
            quantile_count=req.quantile_count,
            ic_window=req.ic_window,
            max_workers=max_workers,
        )
        
        return config
    
    def _merge_and_evaluate_results(
        self,
        task_id: int,
        factor_results_buffer: Dict[str, Dict[str, Any]],
        factors: List[FactorModel],
        req: FactorEvaluationCreate
    ) -> tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
        """合并因子结果并生成最终评价指标"""
        # 构建因子映射：factor_class_name -> FactorModel
        factor_map = {factor.class_name: factor for factor in factors}
        
        evaluation_results = {}
        factor_metrics = []
        
        # 现在 factor_results_buffer 的 key 已经是 factor_id_output_name 格式
        for factor_key, buffer in factor_results_buffer.items():
            # 合并 IC 序列（展平所有列表）
            all_ic_series = []
            for ic_list in buffer['ic_series_list']:
                if isinstance(ic_list, list):
                    all_ic_series.extend(ic_list)
            
            # 合并分位数收益（取平均值）
            quantile_returns_merged = {}
            if buffer['quantile_returns_list']:
                # 收集所有分位数收益
                quantile_dicts = buffer['quantile_returns_list']
                all_keys = set()
                for qd in quantile_dicts:
                    all_keys.update(qd.keys())
                
                # 计算平均值
                for key in all_keys:
                    values = [qd.get(key, 0.0) for qd in quantile_dicts if key in qd]
                    if values:
                        quantile_returns_merged[key] = float(np.mean(values))
            
            # 计算聚合指标（取平均值）
            ic_mean = float(np.mean([v for v in buffer['ic_mean_list'] if not np.isnan(v)])) if buffer['ic_mean_list'] else 0.0
            ic_std = float(np.mean([v for v in buffer['ic_std_list'] if not np.isnan(v)])) if buffer['ic_std_list'] else 0.0
            ir = float(np.mean([v for v in buffer['ir_list'] if not np.isnan(v)])) if buffer['ir_list'] else 0.0
            ic_win_rate = float(np.mean(buffer['ic_win_rate_list'])) if buffer['ic_win_rate_list'] else 0.0
            ic_skewness = float(np.mean([v for v in buffer['ic_skewness_list'] if not np.isnan(v)])) if buffer['ic_skewness_list'] else 0.0
            long_short_return = float(np.mean([v for v in buffer['long_short_return_list'] if not np.isnan(v)])) if buffer['long_short_return_list'] else 0.0
            
            # 获取因子信息
            factor_id = buffer.get('factor_id')
            output_name = buffer.get('output_name', factor_key.split('_', 1)[1] if '_' in factor_key else factor_key)
            
            # 查找对应的因子模型
            factor_model = next((f for f in factors if f.id == factor_id), None)
            if not factor_model:
                logger.warning(f"[Task {task_id}] Factor {factor_id} not found in factors list")
                continue
            
            # 构建完整的因子名称
            full_factor_name = f"{factor_model.name}_{output_name}"
            
            # 构建结果（evaluation_results 包含 ic_series 用于生成图表）
            result = {
                'factor_name': full_factor_name,
                'factor_id': factor_id,
                'ic_mean': ic_mean,
                'ic_std': ic_std,
                'ir': ir,
                'ic_win_rate': ic_win_rate,
                'ic_skewness': ic_skewness,
                'ic_series': all_ic_series,  # 未压缩，将在生成图表时压缩
                'quantile_returns': quantile_returns_merged,
                'long_short_return': long_short_return,
            }
            
            evaluation_results[factor_key] = result
            
            # factor_metrics 不包含 ic_series，只存储汇总指标（减少存储大小）
            metric_result = {
                'factor_name': full_factor_name,
                'factor_id': factor_id,
                'ic_mean': ic_mean,
                'ic_std': ic_std,
                'ir': ir,
                'ic_win_rate': ic_win_rate,
                'ic_skewness': ic_skewness,
                'quantile_returns': quantile_returns_merged,
                'long_short_return': long_short_return,
            }
            factor_metrics.append(metric_result)
        
        return evaluation_results, factor_metrics
    
    def _merge_correlation_matrices(
        self,
        correlation_matrices: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """合并多个相关性矩阵（取平均值）"""
        if not correlation_matrices:
            return {}
        
        if len(correlation_matrices) == 1:
            return correlation_matrices[0]
        
        # 收集所有矩阵的键
        all_keys = set()
        for matrix in correlation_matrices:
            if isinstance(matrix, dict):
                all_keys.update(matrix.keys())
        
        # 计算平均值
        merged = {}
        for key in all_keys:
            values = []
            for matrix in correlation_matrices:
                if isinstance(matrix, dict) and key in matrix:
                    row = matrix[key]
                    if isinstance(row, dict):
                        values.append(row)
            
            if values:
                # 合并行（取平均值）
                row_keys = set()
                for row in values:
                    row_keys.update(row.keys())
                
                merged_row = {}
                for row_key in row_keys:
                    row_values = [row.get(row_key, 0.0) for row in values if row_key in row]
                    if row_values:
                        merged_row[row_key] = float(np.mean(row_values))
                
                merged[key] = merged_row
        
        return merged
    
    def _generate_summary_metrics(
        self,
        task_id: int,
        factor_metrics: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """生成汇总指标"""
        
        if not factor_metrics:
            logger.warning(f"[Task {task_id}] No factor metrics generated!")
            return {
                'ic_mean': 0.0,
                'ir': 0.0,
                'ic_win_rate': 0.0,
                'factor_count': 0,
            }
        
        ic_means = [m['ic_mean'] for m in factor_metrics if not np.isnan(m.get('ic_mean', np.nan))]
        irs = [m['ir'] for m in factor_metrics if not np.isnan(m.get('ir', np.nan))]
        ic_win_rates = [m['ic_win_rate'] for m in factor_metrics]
        
        summary = {
            'ic_mean': float(np.mean(ic_means)) if ic_means else 0.0,
            'ir': float(np.mean(irs)) if irs else 0.0,
            'ic_win_rate': float(np.mean(ic_win_rates)) if ic_win_rates else 0.0,
            'factor_count': len(factor_metrics),
        }
        
        return summary
    
    def _generate_chart_data(
        self,
        task_id: int,
        evaluation_results: Dict[str, Dict[str, Any]],
        correlation_matrix: Dict[str, Any]
    ) -> Dict[str, Any]:
        """生成图表数据（压缩时间序列）"""
        
        # 下采样配置
        DOWNSAMPLE_MAX_POINTS = 15000
        
        compressed_ic_series = {}
        compressed_quantile_returns = {}
        
        for factor_key, result in evaluation_results.items():
            # 使用 factor_name 作为 key（如果存在），否则使用 factor_key
            factor_name = result.get('factor_name', factor_key)
            
            # 获取合并后的IC序列和时间戳
            merged_ic_series = result.get('ic_series', [])
            merged_ic_times = result.get('ic_times', [])
            
            # 获取按symbol×timeframe保存的IC序列
            ic_series_by_st = result.get('ic_series_by_st', {})
            
            # 压缩合并后的IC序列和时间戳
            factor_chart_data = {}
            if merged_ic_series and merged_ic_times and len(merged_ic_series) == len(merged_ic_times):
                # 下采样
                if len(merged_ic_series) > DOWNSAMPLE_MAX_POINTS:
                    downsampled_times, downsampled_ic = downsample_series(
                        merged_ic_times, merged_ic_series, DOWNSAMPLE_MAX_POINTS
                    )
                else:
                    downsampled_times = merged_ic_times
                    downsampled_ic = merged_ic_series
                
                # 压缩时间序列和IC值
                factor_chart_data['merged'] = {
                    'times': encode_time_series(downsampled_times),
                    'values': encode_values(downsampled_ic),
                }
            else:
                # 如果没有合并后的数据，创建空数据
                factor_chart_data['merged'] = {
                    'times': encode_time_series([]),
                    'values': encode_values([]),
                }
            
            # 压缩每个symbol×timeframe的IC序列和时间戳
            for st_key, st_data in ic_series_by_st.items():
                ic_series_st = st_data.get('ic_series', [])
                ic_times_st = st_data.get('ic_times', [])
                
                if ic_series_st and ic_times_st and len(ic_series_st) == len(ic_times_st):
                    # 下采样
                    if len(ic_series_st) > DOWNSAMPLE_MAX_POINTS:
                        downsampled_times_st, downsampled_ic_st = downsample_series(
                            ic_times_st, ic_series_st, DOWNSAMPLE_MAX_POINTS
                        )
                    else:
                        downsampled_times_st = ic_times_st
                        downsampled_ic_st = ic_series_st
                    
                    # 压缩时间序列和IC值
                    factor_chart_data[st_key] = {
                        'times': encode_time_series(downsampled_times_st),
                        'values': encode_values(downsampled_ic_st),
                        'symbol': st_data.get('symbol', ''),
                        'timeframe': st_data.get('timeframe', ''),
                    }
            
            compressed_ic_series[factor_name] = factor_chart_data
            
            # 分位数收益不需要压缩（已经是字典）
            compressed_quantile_returns[factor_name] = result.get('quantile_returns', {})
        
        return {
            'ic_series': compressed_ic_series,
            'quantile_returns': compressed_quantile_returns,
            'correlation_matrix': correlation_matrix,
        }
    
    def _update_task_status(
        self, 
        task_id: int, 
        status: str, 
        progress: float,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        error: Optional[str] = None
    ):
        """更新任务状态"""
        try:
            with db_connect() as db:
                task = db.query(FactorEvaluationTask).filter(
                    FactorEvaluationTask.id == task_id
                ).first()
                if task:
                    task.status = status
                    task.progress = progress
                    if started_at:
                        task.started_at = started_at
                    if finished_at:
                        task.finished_at = finished_at
                    if error:
                        task.error = error
                    db.commit()
        except Exception as e:
            logger.error(f"Failed to update task status: {e}", exc_info=True)
    
    def _update_task_progress(self, task_id: int, progress: float):
        """更新任务进度"""
        try:
            with db_connect() as db:
                task = db.query(FactorEvaluationTask).filter(
                    FactorEvaluationTask.id == task_id
                ).first()
                if task:
                    task.progress = progress
                    db.commit()
        except Exception as e:
            logger.error(f"Failed to update task progress: {e}", exc_info=True)
    
    def get_task_status(self, task_id: int) -> Optional[Dict[str, Any]]:
        """获取任务状态信息"""
        return self.running_tasks.get(task_id)


# 创建全局服务实例
factor_evaluation_service = FactorEvaluationService()
