from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.orm import defer
from typing import Any, Dict, Optional, List
from datetime import datetime

from app.api import deps
from app.models.model_training_task import ModelTrainingTask
from app.schemas.model_training import (
    ModelTrainingCreate,
    ModelTrainingTaskOut,
    ModelTrainingTaskBriefOut
)
from app.schemas.common import PageResponse
from leek_core.utils import get_logger
from app.service.model_training_service import model_training_service
from app.utils.json_sanitize import sanitize_for_json

logger = get_logger(__name__)

router = APIRouter()


@router.post("/model_training", response_model=ModelTrainingTaskOut)
async def create_model_training(
    req: ModelTrainingCreate,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
):
    """创建模型训练任务"""
    try:
        # 创建数据库记录
        task = ModelTrainingTask(
            project_id=project_id,
            name=req.name,
            description=req.description,
            config=req.model_dump(),
            status="pending",
            progress=0.0,
            data_config_id=req.data_config_id,
            start_time=req.start_time,
            end_time=req.end_time,
            symbols=req.symbols,
            timeframes=req.timeframes,
            factor_ids=req.factor_ids,
            label_generator_id=req.label_generator_id,
            trainer_id=req.trainer_id,
            train_split_ratio=req.train_split_ratio,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        import asyncio
        asyncio.create_task(model_training_service.create_training_task(task, req))
        
        return task
    except Exception as e:
        logger.error(f"Failed to create model training: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/model_training/{task_id}", response_model=ModelTrainingTaskOut)
async def get_model_training_task(
    task_id: int,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
):
    """获取模型训练任务详情"""
    task = db.query(ModelTrainingTask).filter(
        ModelTrainingTask.id == task_id,
        ModelTrainingTask.project_id == project_id
    ).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 如果任务未完成，从 running_tasks 获取详细状态（不保存到数据库）
    if task.status in ['pending', 'running']:
        task_status = model_training_service.get_task_status(task_id)
        if task_status:
            if not task.config:
                task.config = {}
            # task_status 只在响应中返回，不保存到数据库
            task.config['task_status'] = task_status
    
    # JSON合规清洗
    try:
        if isinstance(task.metrics, dict):
            logger.info(f"[API] Task {task_id} metrics before sanitize: type={type(task.metrics)}, keys={list(task.metrics.keys()) if task.metrics else 'None'}")
            task.metrics = sanitize_for_json(task.metrics)
            logger.info(f"[API] Task {task_id} metrics after sanitize: type={type(task.metrics)}, keys={list(task.metrics.keys()) if task.metrics else 'None'}")
        if isinstance(task.config, dict):
            task.config = sanitize_for_json(task.config)
    except Exception as e:
        logger.error(f"[API] Error sanitizing task {task_id} data: {e}", exc_info=True)
    
    return task


@router.get("/model_training", response_model=PageResponse[ModelTrainingTaskBriefOut])
async def list_model_training_tasks(
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """获取模型训练任务列表"""
    # defer大字段，优化查询性能
    query = db.query(ModelTrainingTask).options(
        defer(ModelTrainingTask.config),
        defer(ModelTrainingTask.metrics)
    ).filter(
        ModelTrainingTask.project_id == project_id
    )
    
    if name:
        query = query.filter(ModelTrainingTask.name.like(f"%{name}%"))
    
    if status:
        query = query.filter(ModelTrainingTask.status == status)
    
    # 时间范围过滤（按创建时间）
    if start_date:
        start_dt = datetime.fromisoformat(start_date)
        query = query.filter(ModelTrainingTask.created_at >= start_dt)
    if end_date:
        end_dt = datetime.fromisoformat(end_date)
        end_dt = end_dt.replace(hour=23, minute=59, second=59)
        query = query.filter(ModelTrainingTask.created_at <= end_dt)
    
    total = query.count()
    items = (
        query.order_by(
            ModelTrainingTask.created_at.desc(), 
            ModelTrainingTask.id.desc()
        )
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    
    # 批量查询已完成任务的 metrics（优化：避免 N+1 查询问题）
    completed_task_ids = [item.id for item in items if item.status == 'completed']
    metrics_map = {}
    if completed_task_ids:
        # 一次性批量查询所有已完成任务的 metrics
        metrics_results = db.query(
            ModelTrainingTask.id,
            ModelTrainingTask.metrics
        ).filter(
            ModelTrainingTask.id.in_(completed_task_ids)
        ).all()
        
        # 构建 metrics 映射表
        for task_id, metrics in metrics_results:
            metrics_map[task_id] = metrics
    
    # 计算每个任务的评分（只对已完成的任务）
    items_with_score = []
    for item in items:
        score = None
        task_type = None  # 'classification' or 'regression'
        if item.status == 'completed':
            # 从批量查询的结果中获取 metrics
            metrics = metrics_map.get(item.id)
            
            if metrics:
                # 处理不同的 metrics 结构
                validation_metrics = None
                if isinstance(metrics, dict):
                    # 新格式：metrics.new_model.validation 或 metrics.validation
                    if 'new_model' in metrics and isinstance(metrics['new_model'], dict):
                        validation_metrics = metrics['new_model'].get('validation')
                    elif 'validation' in metrics:
                        validation_metrics = metrics['validation']
                    
                    if validation_metrics:
                        # 判断是分类还是回归任务
                        if 'accuracy' in validation_metrics:
                            # 分类任务：使用 accuracy
                            task_type = 'classification'
                            score = validation_metrics.get('accuracy')
                        elif 'r2' in validation_metrics:
                            # 回归任务：使用 R²
                            task_type = 'regression'
                            score = validation_metrics.get('r2')
        
        # 创建带评分的对象
        item_dict = {
            'id': item.id,
            'name': item.name,
            'description': item.description,
            'status': item.status,
            'progress': item.progress,
            'created_at': item.created_at,
            'started_at': item.started_at,
            'finished_at': item.finished_at,
            'error': item.error,
            'data_config_id': item.data_config_id,
            'start_time': item.start_time,
            'end_time': item.end_time,
            'symbols': item.symbols,
            'timeframes': item.timeframes,
            'factor_ids': item.factor_ids,
            'label_generator_id': item.label_generator_id,
            'trainer_id': item.trainer_id,
            'train_split_ratio': item.train_split_ratio,
            'model_id': item.model_id,
            'score': score,
            'task_type': task_type
        }
        items_with_score.append(item_dict)
    
    return PageResponse(total=total, page=page, size=size, items=items_with_score)


@router.delete("/model_training/{task_id}")
async def delete_model_training_task(
    task_id: int,
    db: Session = Depends(deps.get_db_session),
    project_id: int = Depends(deps.get_project_id),
):
    """删除模型训练任务"""
    task = db.query(ModelTrainingTask).filter(
        ModelTrainingTask.id == task_id,
        ModelTrainingTask.project_id == project_id
    ).first()
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    db.delete(task)
    db.commit()
    return {"status": "success"}

