#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
性能分析API接口
"""

from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
from app.api.deps import get_project_id, get_db_session
from app.service.performance_service import performance_service
from leek_core.utils import get_logger

logger = get_logger(__name__)

router = APIRouter()

@router.get("/performance")
async def get_project_performance(
    start_time: Optional[datetime] = Query(None, description="开始时间"),
    end_time: Optional[datetime] = Query(None, description="结束时间"),
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db_session)
):
    """获取项目整体性能指标"""
    if not project_id:
        raise HTTPException(status_code=400, detail="项目ID不能为空")
    
    try:
        result = performance_service.get_project_performance(
            project_id, start_time, end_time, db
        )
        return result
    except Exception as e:
        logger.error(f"获取项目性能指标失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取性能指标失败")

@router.get("/performance/strategies")
async def get_strategies_performance(
    start_time: Optional[datetime] = Query(None, description="开始时间"),
    end_time: Optional[datetime] = Query(None, description="结束时间"),
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db_session)
):
    """获取项目下所有策略的性能数据"""
    if not project_id:
        raise HTTPException(status_code=400, detail="项目ID不能为空")
    
    try:
        result = performance_service.get_strategies_performance(
            project_id, start_time, end_time, db
        )
        return result
    except Exception as e:
        logger.error(f"获取策略性能数据失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取策略性能数据失败")

@router.get("/performance/equity-curve")
async def get_equity_curve(
    start_time: Optional[datetime] = Query(None, description="开始时间"),
    end_time: Optional[datetime] = Query(None, description="结束时间"),
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db_session)
):
    """获取项目整体资产曲线数据"""
    if not project_id:
        raise HTTPException(status_code=400, detail="项目ID不能为空")
    
    try:
        result = performance_service.get_equity_curve(
            project_id, start_time, end_time, db
        )
        return result
    except Exception as e:
        logger.error(f"获取资产曲线数据失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取资产曲线数据失败")

@router.get("/performance/trades")
async def get_trade_statistics(
    start_time: Optional[datetime] = Query(None, description="开始时间"),
    end_time: Optional[datetime] = Query(None, description="结束时间"),
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db_session)
):
    """获取项目整体交易统计"""
    if not project_id:
        raise HTTPException(status_code=400, detail="项目ID不能为空")
    
    try:
        result = performance_service.get_trade_statistics(
            project_id, start_time, end_time, db
        )
        return result
    except Exception as e:
        logger.error(f"获取交易统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取交易统计失败")

@router.post("/performance/clear-cache")
async def clear_performance_cache():
    """清除性能分析缓存"""
    try:
        performance_service.clear_cache()
        return {"code": 200, "data": None, "message": "缓存清除成功"}
    except Exception as e:
        logger.error(f"清除缓存失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="清除缓存失败")