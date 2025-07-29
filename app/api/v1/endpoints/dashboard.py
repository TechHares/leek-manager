from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, List, Optional
import psutil
import os
import requests
import logging
from app.core.config import settings
from app.core.engine import engine_manager
from app.api.deps import get_current_user
from app.models.project import Project
from app.api.deps import get_project_id
from app.models.user import User
from app.models.asset_snapshot import AssetSnapshot
from app.models.position import Position
from app.models.strategy import Strategy
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from leek_core import __version__ as core_version
import time
from app.api import deps
from datetime import datetime, timedelta
from decimal import Decimal

router = APIRouter()
logger = logging.getLogger(__name__)
_version_cache = [0, "未获取到", "..."]

@router.get("/dashboard/overview", response_model=Dict[str, Any])
async def get_dashboard_overview(current_user: User = Depends(get_current_user), db: Session = Depends(deps.get_db), project_id: int = Depends(get_project_id)):
    try:
        engine = engine_manager.get_client(project_id)
        if engine is None:
            return {
                "core_version": core_version,
            "sys_version": settings.VERSION,
            }
        engine_state = await engine.invoke("engine_state")
        global _version_cache
        if time.time() - _version_cache[0] > 12*3600:
            try:
                version, body = await new_version()
                _version_cache = [time.time(), version, body]
            except Exception as e:
                _version_cache[0] = time.time()
        return {
            "core_version": core_version,
            "sys_version": settings.VERSION,
            "version": _version_cache[1],
            "body": _version_cache[2],
            "resources": engine_state.get("resources", {}),
            "state": engine_state.get("state", {}),
        }
    except Exception as e:
        logger.error(f"Dashboard overview error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取系统信息失败: {str(e)}"
        ) 

@router.get("/dashboard/asset", response_model=Dict[str, Any])
async def get_dashboard_asset(
    start_time: Optional[datetime] = Query(None, description="开始时间"),
    end_time: Optional[datetime] = Query(None, description="结束时间"),
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(deps.get_db), 
    project_id: int = Depends(get_project_id)
):
    """
    获取仪表板资产数据，包含：
    1. 资产快照数据（用于线图）
    2. 策略盈利数据（用于柱状图）
    3. 手续费数据（用于饼图）
    """
    try:
        logger.info(f"Getting dashboard asset data for project_id: {project_id}")
        
        # 如果没有提供时间范围，默认使用最近一个月
        if not start_time:
            start_time = datetime.now() - timedelta(days=30)
        not_end_time = not end_time
        if not_end_time:
            end_time = datetime.now()
        
        logger.info(f"Time range: {start_time} to {end_time}")
        
        # 1. 获取资产快照数据（不分页，用于线图）
        asset_snapshots_query = db.query(AssetSnapshot).filter(
            AssetSnapshot.project_id == project_id,
            AssetSnapshot.snapshot_time >= start_time,
            AssetSnapshot.snapshot_time <= end_time
        ).order_by(AssetSnapshot.snapshot_time.asc())
        
        asset_snapshots = asset_snapshots_query.all()
        engine = engine_manager.get_client(project_id)
        if not_end_time and engine:
            position_data = await engine.invoke("storage_postion")
            # 从数据中提取资产信息
            activate_amount = Decimal(position_data.get('activate_amount', '0'))
            pnl = Decimal(position_data.get('pnl', '0'))
            friction = Decimal(position_data.get('friction', '0'))
            fee = Decimal(position_data.get('fee', '0'))
            total_amount = Decimal(position_data.get('total_amount', '0'))
            virtual_pnl = Decimal(position_data.get('virtual_pnl', '0'))
            
            # 计算仓位数量
            positions = position_data.get('positions', [])
            position_amount = len(positions)
            
            # 保存到数据库
            snapshot = AssetSnapshot(project_id=project_id,
                snapshot_time=datetime.now(),
                activate_amount=activate_amount,
                pnl=pnl,
                friction=friction,
                fee=fee,
                total_amount=total_amount,
                virtual_pnl=virtual_pnl,
                position_amount=position_amount)
            asset_snapshots.append(snapshot)
        logger.info(f"Found {len(asset_snapshots)} asset snapshots")
        
        # 2. 获取策略盈利数据（按策略分组，用于柱状图）
        strategy_pnl_query = db.query(
            Strategy.name,
            func.sum(Position.pnl).label('total_pnl')
        ).join(
            Position, Strategy.id == Position.strategy_id
        ).filter(
            Strategy.project_id == project_id,
            Position.project_id == project_id,
            Position.open_time >= start_time,
            Position.open_time <= end_time
        ).group_by(
            Strategy.id, Strategy.name
        ).order_by(desc('total_pnl'))
        
        strategy_pnl_data = strategy_pnl_query.all()
        logger.info(f"Found {len(strategy_pnl_data)} strategy PnL records")
        
        # 3. 获取手续费数据（按策略分组，用于饼图）
        strategy_fee_query = db.query(
            Strategy.name,
            func.sum(Position.fee).label('total_fee')
        ).join(
            Position, Strategy.id == Position.strategy_id
        ).filter(
            Strategy.project_id == project_id,
            Position.project_id == project_id,
            Position.open_time >= start_time,
            Position.open_time <= end_time
        ).group_by(
            Strategy.id, Strategy.name
        ).order_by(desc('total_fee'))
        
        strategy_fee_data = strategy_fee_query.all()
        logger.info(f"Found {len(strategy_fee_data)} strategy fee records")
        
        # 格式化返回数据
        asset_snapshots_formatted = []
        for snapshot in asset_snapshots:
            asset_snapshots_formatted.append({
                "id": snapshot.id,
                "snapshot_time": snapshot.snapshot_time.isoformat(),
                "total_amount": float(snapshot.total_amount),
                "activate_amount": float(snapshot.activate_amount),
                "pnl": float(snapshot.pnl),
                "fee": float(snapshot.fee),
                "friction": float(snapshot.friction),
                "virtual_pnl": float(snapshot.virtual_pnl),
                "position_amount": snapshot.position_amount
            })
        
        strategy_pnl_formatted = []
        for item in strategy_pnl_data:
            strategy_pnl_formatted.append({
                "strategy_name": item.name,
                "total_pnl": float(item.total_pnl) if item.total_pnl else 0.0
            })
        
        strategy_fee_formatted = []
        for item in strategy_fee_data:
            strategy_fee_formatted.append({
                "strategy_name": item.name,
                "total_fee": float(item.total_fee) if item.total_fee else 0.0
            })
        
        result = {
            "asset_snapshots": asset_snapshots_formatted,
            "strategy_pnl": strategy_pnl_formatted,
            "strategy_fee": strategy_fee_formatted,
            "time_range": {
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat()
            }
        }
        
        logger.info(f"Returning data: {len(asset_snapshots_formatted)} snapshots, {len(strategy_pnl_formatted)} PnL records, {len(strategy_fee_formatted)} fee records")
        return result
        
    except Exception as e:
        logger.error(f"Dashboard asset error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取资产数据失败: {str(e)}"
        )

async def new_version():
    res = requests.get('https://api.github.com/repos/TechHares/leek/releases/latest')
    js = res.json()
    print(js)
    return js['tag_name'][1:], js["body"]