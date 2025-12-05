#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import threading
from multiprocessing import Manager, Process
from datetime import datetime
from typing import Any, Dict, List, Optional
import joblib
from pathlib import Path

from sqlalchemy.orm import Session
from app.models.model_training_task import ModelTrainingTask
from app.models.model import Model as ModelModel
from app.models.factor import Factor as FactorModel
from app.models.label_generator import LabelGenerator as LabelGeneratorModel
from app.models.trainer import Trainer as TrainerModel
from app.models.backtest_config import BacktestConfig as BacktestConfigModel
from app.db.session import db_connect
from app.schemas.model_training import ModelTrainingCreate
from app.core.config_manager import config_manager
from leek_core.utils import get_logger
from leek_core.ml.training_engine import training
from app.utils.json_sanitize import sanitize_for_json

logger = get_logger(__name__)


class ModelTrainingService:
    """模型训练服务"""
    
    def __init__(self):
        self.running_tasks: Dict[int, Any] = {}
    
    async def create_training_task(
        self, 
        task: ModelTrainingTask, 
        req: ModelTrainingCreate
    ):
        """创建模型训练任务"""
        task_id = task.id
        # 初始化任务状态结构
        symbols = req.symbols or []
        timeframes = req.timeframes or []
        
        # 初始化所有 symbol×timeframe 组合
        symbol_timeframe_tasks = {}
        for symbol in symbols:
            for timeframe in timeframes:
                task_key = f"{symbol}_{timeframe}"
                symbol_timeframe_tasks[task_key] = {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'status': 'pending'
                }
        
        self.running_tasks[task_id] = {
            'status': 'pending',
            'progress': 0.0,
            'phases': {
                'loading_data': {
                    'status': 'pending',
                    'symbols': {k: {'status': 'pending', 'symbol': v['symbol'], 'timeframe': v['timeframe']} 
                               for k, v in symbol_timeframe_tasks.items()}
                },
                'computing_features': {
                    'status': 'pending',
                    'symbols': {k: {'status': 'pending', 'symbol': v['symbol'], 'timeframe': v['timeframe']} 
                               for k, v in symbol_timeframe_tasks.items()}
                },
                'generating_labels': {
                    'status': 'pending',
                    'symbols': {k: {'status': 'pending', 'symbol': v['symbol'], 'timeframe': v['timeframe']} 
                               for k, v in symbol_timeframe_tasks.items()}
                },
                'splitting_data': {
                    'status': 'pending',
                    'symbols': {k: {'status': 'pending', 'symbol': v['symbol'], 'timeframe': v['timeframe']} 
                               for k, v in symbol_timeframe_tasks.items()}
                },
                'loading_old_model': {'status': 'pending'},
                'evaluating_old_model': {'status': 'pending'},
                'merging_data': {'status': 'pending'},
                'training': {'status': 'pending'},
                'evaluating': {'status': 'pending'},
                'saving_model': {'status': 'pending'}
            },
            'old_model_metrics': None,
            'new_model_metrics': None
        }
        # 异步执行训练
        asyncio.create_task(self._execute_training_async(task, req))
    
    async def _execute_training_async(
        self, 
        task: ModelTrainingTask, 
        req: ModelTrainingCreate
    ):
        """异步执行模型训练"""
        task_id = task.id
        logger.info(f"[Task {task_id}] Starting async training execution")
        
        loop = asyncio.get_event_loop()
        try:
            
            # 更新任务状态（在线程池中执行，避免阻塞事件循环）
            await loop.run_in_executor(
                None, self._update_task_status, task_id, "running", 0.0, datetime.now(), None, None
            )
            
            # 加载配置（在线程池中执行，避免阻塞事件循环）
            data_config, factors, label_generator, trainer, market_config = await loop.run_in_executor(
                None, self._load_training_config, req
            )
            
            # 构建训练配置（在线程池中执行，避免阻塞事件循环）
            training_config = await loop.run_in_executor(
                None,
                self._build_training_config,
                task_id, req, data_config, factors, label_generator, trainer, market_config
            )
            
            # 创建进度队列
            manager = Manager()
            progress_queue = manager.Queue()
            
            # 启动进度监听线程
            stop_event = threading.Event()
            progress_thread = threading.Thread(
                target=self._progress_listener,
                args=(task_id, progress_queue, stop_event),
                daemon=True
            )
            progress_thread.start()
            
            # 在独立进程中运行训练
            training_process = Process(
                target=training,
                args=(training_config, progress_queue)
            )
            training_process.start()
            
            # 等待训练完成（在线程池中执行，避免阻塞事件循环）
            await loop.run_in_executor(None, training_process.join)
            
            # 停止进度监听
            stop_event.set()
            progress_queue.put(None)  # 发送结束信号
            progress_thread.join(timeout=5)
            
            # 检查进程退出码
            if training_process.exitcode != 0:
                # 检查是否已经有错误消息（通过进度队列传递并保存到数据库的）
                error_message = None
                with db_connect() as db:
                    task = db.query(ModelTrainingTask).filter(ModelTrainingTask.id == task_id).first()
                    if task and task.error:
                        error_message = task.error
                
                # 如果已经有错误消息，使用它；否则使用进程退出码的错误消息
                if error_message:
                    raise RuntimeError(error_message)
                else:
                    raise RuntimeError(f"Training process exited with code {training_process.exitcode}")
            
            # 获取训练结果
            training_result = None
            if task_id in self.running_tasks:
                training_result = self.running_tasks[task_id].get('training_result')
            
            # 处理训练结果：保存模型和更新数据库（在线程池中执行，避免阻塞事件循环）
            if training_result:
                await loop.run_in_executor(
                    None, self._save_training_result, task_id, task, training_result
                )
            
            logger.info(f"[Task {task_id}] Training process completed")
            
        except Exception as e:
            logger.error(f"Model training task {task_id} failed: {e}", exc_info=True)
            await loop.run_in_executor(
                None,
                self._update_task_status,
                task_id, "failed", 0.0, None, datetime.now(), str(e)[:2000]
            )
            # 任务失败后清理 running_tasks（task_status 只在运行时保存在内存中）
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
    
    def _progress_listener(
        self,
        task_id: int,
        progress_queue,
        stop_event: threading.Event
    ):
        """进度监听线程"""
        while not stop_event.is_set():
            try:
                # 设置超时，避免无限等待
                progress_info = progress_queue.get(timeout=1.0)
                if progress_info is None:  # 结束信号
                    break
                
                self._handle_progress_update(task_id, progress_info)
            except Exception:
                # 超时或其他异常，继续监听
                continue
    
    def _handle_progress_update(self, task_id: int, progress_info: Dict[str, Any]):
        """处理进度更新"""
        if task_id not in self.running_tasks:
            return
        
        phase = progress_info.get('phase')
        status = progress_info.get('status')
        symbol = progress_info.get('symbol')
        timeframe = progress_info.get('timeframe')
        # 支持 error_message 和 error 两种字段名
        error_message = progress_info.get('error_message') or progress_info.get('error')
        
        task_state = self.running_tasks[task_id]
        
        # 更新阶段状态
        if phase in task_state['phases']:
            phase_state = task_state['phases'][phase]
            
            # 如果是训练阶段，保存进度信息
            if phase == 'training' and 'progress' in progress_info:
                phase_state['progress'] = progress_info.get('progress', 0.0)
                phase_state['current_iteration'] = progress_info.get('current_iteration', 0)
                phase_state['total_iterations'] = progress_info.get('total_iterations', 0)
                phase_state['metrics'] = progress_info.get('metrics', {})
            
            # 如果有 symbol 和 timeframe，更新对应的 symbol×timeframe 状态
            if symbol is not None and timeframe is not None:
                task_key = f"{symbol}_{timeframe}"
                if 'symbols' in phase_state and task_key in phase_state['symbols']:
                    phase_state['symbols'][task_key]['status'] = status
            else:
                phase_state['status'] = status
        
        # 处理特殊阶段
        if phase == 'completed':
            task_state['status'] = 'completed'
            task_state['progress'] = 1.0
            # 保存训练结果（如果有）
            if 'result' in progress_info:
                task_state['training_result'] = progress_info['result']
        elif phase == 'failed':
            task_state['status'] = 'failed'
            task_state['progress'] = 0.0
            # 如果有错误消息，保存到数据库
            if error_message:
                # 限制错误消息长度
                error_msg_limited = error_message[:2000] if len(error_message) > 2000 else error_message
                self._update_task_status(
                    task_id, 
                    'failed', 
                    0.0, 
                    finished_at=datetime.now(),
                    error=error_msg_limited
                )
        
        # 根据任务状态计算总体进度
        calculated_progress = self._calculate_progress(task_state)
        task_state['progress'] = calculated_progress
        
        # 更新数据库进度
        self._update_task_progress(task_id, calculated_progress)
    
    def _calculate_progress(self, task_state: Dict[str, Any]) -> float:
        """
        根据任务状态计算总体进度（累加模式）
        
        进度分配：
        - loading_data: 0-20%
        - computing_features: 20-40%
        - generating_labels: 40-50%
        - splitting_data: 50-55%
        - loading_old_model: 55-60%
        - evaluating_old_model: 60-65%
        - merging_data: 65-70%
        - training: 70-90%
        - evaluating: 90-95%
        - saving_model: 95-100%
        
        累加模式：每个阶段根据完成的 symbol×timeframe 数量计算进度并累加
        例如：loading_data 共10个，完成了5个，阶段分配20%，那么当前进度就是 20% * (5/10) = 10%
        computing_features 共10个，完成了1个，阶段分配20%，那么当前进度就是 20% * (1/10) = 2%
        总体进度 = 10% + 2% = 12%
        """
        phases = task_state.get('phases', {})
        total_progress = 0.0
        
        # 1. loading_data: 0-20%
        loading_data_phase = phases.get('loading_data', {})
        loading_data_symbols = loading_data_phase.get('symbols', {})
        if loading_data_symbols:
            completed_count = sum(
                1 for s in loading_data_symbols.values() 
                if s.get('status') == 'completed'
            )
            total_count = len(loading_data_symbols)
            if total_count > 0:
                total_progress += 0.20 * (completed_count / total_count)
        
        # 2. computing_features: 20-40%
        computing_features_phase = phases.get('computing_features', {})
        computing_features_symbols = computing_features_phase.get('symbols', {})
        if computing_features_symbols:
            completed_count = sum(
                1 for s in computing_features_symbols.values() 
                if s.get('status') == 'completed'
            )
            total_count = len(computing_features_symbols)
            if total_count > 0:
                total_progress += 0.20 * (completed_count / total_count)
        
        # 3. generating_labels: 40-50%
        generating_labels_phase = phases.get('generating_labels', {})
        generating_labels_symbols = generating_labels_phase.get('symbols', {})
        if generating_labels_symbols:
            completed_count = sum(
                1 for s in generating_labels_symbols.values() 
                if s.get('status') == 'completed'
            )
            total_count = len(generating_labels_symbols)
            if total_count > 0:
                total_progress += 0.10 * (completed_count / total_count)
        
        # 4. splitting_data: 50-55%
        splitting_data_phase = phases.get('splitting_data', {})
        splitting_data_symbols = splitting_data_phase.get('symbols', {})
        if splitting_data_symbols:
            completed_count = sum(
                1 for s in splitting_data_symbols.values() 
                if s.get('status') == 'completed'
            )
            total_count = len(splitting_data_symbols)
            if total_count > 0:
                total_progress += 0.05 * (completed_count / total_count)
        
        # 5. loading_old_model: 55-60%
        loading_old_model_status = phases.get('loading_old_model', {}).get('status', 'pending')
        if loading_old_model_status == 'completed':
            total_progress += 0.05
        elif loading_old_model_status == 'running':
            total_progress += 0.025
        
        # 6. evaluating_old_model: 60-65%
        evaluating_old_model_status = phases.get('evaluating_old_model', {}).get('status', 'pending')
        if evaluating_old_model_status == 'completed':
            total_progress += 0.05
        elif evaluating_old_model_status == 'running':
            total_progress += 0.025
        
        # 7. merging_data: 65-70%
        merging_data_status = phases.get('merging_data', {}).get('status', 'pending')
        if merging_data_status == 'completed':
            total_progress += 0.05
        elif merging_data_status == 'running':
            total_progress += 0.025
        
        # 8. training: 70-90%
        training_status = phases.get('training', {}).get('status', 'pending')
        if training_status == 'completed':
            total_progress += 0.20
        elif training_status == 'running':
            total_progress += 0.10
        
        # 9. evaluating: 90-95%
        evaluating_status = phases.get('evaluating', {}).get('status', 'pending')
        if evaluating_status == 'completed':
            total_progress += 0.05
        elif evaluating_status == 'running':
            total_progress += 0.025
        
        # 10. saving_model: 95-100%
        saving_model_status = phases.get('saving_model', {}).get('status', 'pending')
        if saving_model_status == 'completed':
            total_progress += 0.05
        elif saving_model_status == 'running':
            total_progress += 0.025
        
        return min(1.0, max(0.0, total_progress))
    
    def _build_training_config(
        self,
        task_id: int,
        req: ModelTrainingCreate,
        data_config: BacktestConfigModel,
        factors: List[FactorModel],
        label_generator: LabelGeneratorModel,
        trainer: TrainerModel,
        market_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """构建训练配置"""
        # 构建因子配置
        factor_configs = []
        for factor in factors:
            factor_configs.append({
                'id': factor.id,
                'name': factor.name,
                'class_name': factor.class_name,
                'params': factor.params or {}
            })
        
        # 构建标签生成器配置
        label_gen_config = {
            'id': label_generator.id,
            'name': label_generator.name,
            'class_name': label_generator.class_name,
            'params': label_generator.params or {}
        }
        
        # 构建训练器配置
        trainer_config = {
            'id': trainer.id,
            'name': trainer.name,
            'class_name': trainer.class_name,
            'params': trainer.params or {}
        }
        
        # 构建数据源配置
        datasource_config = data_config.params or {}
        
        # 确定模型路径
        models_dir = config_manager.get_models_dir()
        load_model_path = None
        save_model_path = None
        
        if req.base_model_id:
            # 加载旧模型
            with db_connect() as db:
                base_model = db.query(ModelModel).filter(
                    ModelModel.id == req.base_model_id,
                    ModelModel.is_deleted == False
                ).first()
                if base_model:
                    # file_path 必须是绝对路径
                    model_file_path = Path(base_model.file_path)
                    if model_file_path.exists():
                        load_model_path = str(model_file_path)
        
        # 保存新模型
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        version = f"v{timestamp}"
        save_model_path = str(models_dir / f"{task_id}_{version}.joblib")
        
        config = {
            'id': task_id,
            'name': req.name or f"Training {task_id}",
            'symbols': req.symbols,
            'timeframes': req.timeframes,
            'start_time': req.start_time,
            'end_time': req.end_time,
            'datasource_class': data_config.class_name,
            'datasource_config': datasource_config,
            'factors': factor_configs,
            'label_generator': label_gen_config,
            'trainer': trainer_config,
            'train_split_ratio': req.train_split_ratio,
            'load_model_path': load_model_path,
            'save_model_path': save_model_path,
            'quote_currency': market_config['quote_currency'],
            'ins_type': market_config.get('ins_type_str', 'SWAP'),
            'market': market_config['market'],
            'max_workers': 1,  # 默认并发数
            'enable_symbol_timeframe_encoding': req.enable_symbol_timeframe_encoding
        }
        
        return config
    
    def _load_training_config(
        self,
        req: ModelTrainingCreate
    ) -> tuple[BacktestConfigModel, List[FactorModel], LabelGeneratorModel, TrainerModel, Dict[str, Any]]:
        """加载训练配置"""
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
            
            label_generator = db.query(LabelGeneratorModel).filter(
                LabelGeneratorModel.id == req.label_generator_id,
                LabelGeneratorModel.is_deleted == False
            ).first()
            
            if not label_generator:
                raise ValueError(f"Label generator {req.label_generator_id} not found")
            
            trainer = db.query(TrainerModel).filter(
                TrainerModel.id == req.trainer_id,
                TrainerModel.is_deleted == False
            ).first()
            
            if not trainer:
                raise ValueError(f"Trainer {req.trainer_id} not found")
            
            # 解析数据配置的extra字段
            extra = data_config.extra or {}
            market = extra.get('market', 'okx')
            quote_currency = extra.get('quote_currency', 'USDT')
            ins_type_str = extra.get('ins_type')
            
            return data_config, factors, label_generator, trainer, {
                'market': market,
                'quote_currency': quote_currency,
                'ins_type_str': ins_type_str
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
        with db_connect() as db:
            task = db.query(ModelTrainingTask).filter(
                ModelTrainingTask.id == task_id
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
    
    def _update_task_progress(self, task_id: int, progress: float):
        """更新任务进度"""
        if task_id in self.running_tasks:
            self.running_tasks[task_id]['progress'] = progress
        self._update_task_status(task_id, "running", progress)
    
    def _save_training_result(
        self,
        task_id: int,
        task: ModelTrainingTask,
        result: Dict[str, Any]
    ):
        """保存训练结果到数据库"""
        try:
            new_model_metrics = result.get('new_model_metrics', {})
            old_model_metrics = result.get('old_model_metrics')
            model_path = result.get('model_path')
            
            logger.info(f"[Task {task_id}] Saving training result: new_model_metrics keys={list(new_model_metrics.keys()) if new_model_metrics else None}, "
                      f"old_model_metrics={'present' if old_model_metrics else 'None'}, model_path={model_path}")
            
            # 验证 new_model_metrics 格式
            if not new_model_metrics or not isinstance(new_model_metrics, dict):
                logger.error(f"[Task {task_id}] Invalid new_model_metrics: {type(new_model_metrics)}, value: {new_model_metrics}")
                raise ValueError(f"Invalid new_model_metrics format: expected dict, got {type(new_model_metrics)}")
            
            if 'train' not in new_model_metrics or 'validation' not in new_model_metrics:
                logger.error(f"[Task {task_id}] Missing train or validation in new_model_metrics: keys={list(new_model_metrics.keys())}")
                raise ValueError(f"Missing train or validation in new_model_metrics")
            
            if not model_path:
                logger.warning(f"[Task {task_id}] No model path in result")
                return
            
            # 读取模型文件大小
            model_file_path = Path(model_path)
            if not model_file_path.exists():
                logger.error(f"[Task {task_id}] Model file not found: {model_path}")
                return
            
            file_size = model_file_path.stat().st_size
            
            # 从文件路径提取版本号（格式：{task_id}_v{timestamp}.joblib）
            file_name = model_file_path.name
            version = file_name.replace(f"{task_id}_", "").replace(".joblib", "")
            
            # 创建模型记录
            with db_connect() as db:
                # 重新查询 task 对象，避免使用 detached 对象
                task_record = db.query(ModelTrainingTask).filter(
                    ModelTrainingTask.id == task_id
                ).first()
                
                if not task_record:
                    logger.error(f"[Task {task_id}] Task not found in database")
                    return
                
                # 从训练配置中提取 feature_config
                feature_config = None
                # 优先从 config 中获取 factors（如果训练完成后保存了完整配置）
                if task_record.config:
                    config = task_record.config if isinstance(task_record.config, dict) else {}
                    factors = config.get('factors', [])
                    if factors:
                        # factors 就是 feature_config 格式
                        feature_config = factors
                        logger.info(f"[Task {task_id}] Extracted feature_config from config with {len(feature_config)} factors")
                
                # 如果 config 中没有 factors，从 factor_ids 重新查询
                if not feature_config and task_record.factor_ids:
                    factors = db.query(FactorModel).filter(
                        FactorModel.id.in_(task_record.factor_ids),
                        FactorModel.is_deleted == False
                    ).all()
                    if factors:
                        feature_config = []
                        for factor in factors:
                            feature_config.append({
                                'id': factor.id,
                                'name': factor.name,
                                'class_name': factor.class_name,
                                'params': factor.params or {}
                            })
                        logger.info(f"[Task {task_id}] Built feature_config from factor_ids with {len(feature_config)} factors")
                
                # 设置描述：来自训练任务 "{name}（{id}）"
                description = f'来自训练任务 "{task_record.name}（{task_id}）"'
                
                # 获取编码器类别信息（如果存在）
                encoder_classes = result.get('encoder_classes', {})
                
                feature_config_with_encoders = {
                        'factors': feature_config,
                        'encoder_classes': encoder_classes
                }
                
                model_record = ModelModel(
                    name=task_record.name,
                    version=version,
                    description=description,
                    project_id=task_record.project_id,
                    file_path=str(model_file_path),  # 保存全路径
                    file_size=file_size,
                    feature_config=feature_config_with_encoders,
                )
                
                db.add(model_record)
                db.commit()
                db.refresh(model_record)
                
                # 更新任务
                task_record.model_id = model_record.id
                # 如果有旧模型指标，保存为对比格式；否则只保存新模型指标
                # 注意：old_model_metrics 是单个指标字典（只评估了验证集），需要包装成 {'validation': {...}} 格式
                if old_model_metrics:
                    metrics_to_save = {
                        'old_model': {'validation': old_model_metrics},
                        'new_model': new_model_metrics
                    }
                else:
                    metrics_to_save = new_model_metrics
                
                logger.info(f"[Task {task_id}] Metrics structure before save: {type(metrics_to_save)}, keys={list(metrics_to_save.keys()) if isinstance(metrics_to_save, dict) else 'not a dict'}")
                if isinstance(metrics_to_save, dict) and 'train' in metrics_to_save:
                    logger.info(f"[Task {task_id}] Train metrics keys: {list(metrics_to_save['train'].keys()) if isinstance(metrics_to_save.get('train'), dict) else 'not a dict'}")
                if isinstance(metrics_to_save, dict) and 'validation' in metrics_to_save:
                    logger.info(f"[Task {task_id}] Validation metrics keys: {list(metrics_to_save['validation'].keys()) if isinstance(metrics_to_save.get('validation'), dict) else 'not a dict'}")
                
                task_record.metrics = sanitize_for_json(metrics_to_save)
                task_record.progress = 1.0
                task_record.status = "completed"
                task_record.finished_at = datetime.now()
                
                # 更新 config，保存完整的训练配置（包含 factors）以便后续使用
                if task_record.config and isinstance(task_record.config, dict):
                    # 如果 config 中没有 factors，添加进去
                    if 'factors' not in task_record.config and feature_config:
                        task_record.config['factors'] = feature_config
                        logger.info(f"[Task {task_id}] Updated config with feature_config")
                
                db.commit()
                
                # 重新查询以确认数据已保存
                db.refresh(task_record)
                logger.info(f"[Task {task_id}] Model saved: {model_record.id}")
                logger.info(f"[Task {task_id}] Saved metrics type: {type(task_record.metrics)}")
                if task_record.metrics:
                    logger.info(f"[Task {task_id}] Saved metrics keys: {list(task_record.metrics.keys()) if isinstance(task_record.metrics, dict) else 'not a dict'}")
                    if isinstance(task_record.metrics, dict):
                        if 'train' in task_record.metrics:
                            train_metrics = task_record.metrics['train']
                            logger.info(f"[Task {task_id}] Train metrics: accuracy={train_metrics.get('accuracy') if isinstance(train_metrics, dict) else 'not a dict'}, "
                                      f"precision={train_metrics.get('precision') if isinstance(train_metrics, dict) else 'not a dict'}")
                        if 'validation' in task_record.metrics:
                            val_metrics = task_record.metrics['validation']
                            logger.info(f"[Task {task_id}] Validation metrics: accuracy={val_metrics.get('accuracy') if isinstance(val_metrics, dict) else 'not a dict'}, "
                                      f"precision={val_metrics.get('precision') if isinstance(val_metrics, dict) else 'not a dict'}")
                else:
                    logger.warning(f"[Task {task_id}] Metrics is None or empty after save!")
                
                # 任务完成后清理 running_tasks（task_status 只在运行时保存在内存中）
                if task_id in self.running_tasks:
                    del self.running_tasks[task_id]
                    logger.info(f"[Task {task_id}] Cleaned up running_tasks")
                
        except Exception as e:
            logger.error(f"[Task {task_id}] Failed to save training result: {e}", exc_info=True)
            # 即使保存失败，也清理 running_tasks
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
    
    def get_task_status(self, task_id: int) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        return self.running_tasks.get(task_id)


# 创建全局服务实例
model_training_service = ModelTrainingService()
