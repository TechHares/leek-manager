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
from app.models.project_config import ProjectConfig
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from leek_core import __version__ as core_version
import time
from app.api import deps
from datetime import datetime, timedelta
from decimal import Decimal
from app.utils.data_processor import get_daily_snapshots_from_hourly, calculate_performance_from_values

router = APIRouter()
logger = logging.getLogger(__name__)
_version_cache = [0, "未获取到", "..."]

@router.get("/dashboard/overview", response_model=Dict[str, Any])
async def get_dashboard_overview(current_user: User = Depends(get_current_user), db: Session = Depends(deps.get_db_session), project_id: int = Depends(get_project_id)):
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
    db: Session = Depends(deps.get_db_session), 
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
            position_data = await engine.invoke("get_position_state")
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
        
        # 计算性能指标（使用日级数据处理）
        daily_values = get_daily_snapshots_from_hourly(asset_snapshots_formatted, start_time, end_time)
        performance_metrics = calculate_performance_from_values(daily_values, 365)
        
        # 计算上一时期的性能指标对比
        # 根据当前时间范围计算上一时期
        # 统一使用本地时区
        if start_time.tzinfo is not None:
            start_time = start_time.replace(tzinfo=None)
        if end_time.tzinfo is not None:
            end_time = end_time.replace(tzinfo=None)
            
        time_diff = end_time - start_time
        previous_start = start_time - time_diff
        previous_end = start_time
        
        # 获取上一时期的资产快照数据
        previous_snapshots_query = db.query(AssetSnapshot).filter(
            AssetSnapshot.project_id == project_id,
            AssetSnapshot.snapshot_time >= previous_start,
            AssetSnapshot.snapshot_time <= previous_end
        ).order_by(AssetSnapshot.snapshot_time.asc())
        
        previous_snapshots = previous_snapshots_query.all()
        previous_snapshots_formatted = []
        for snapshot in previous_snapshots:
            previous_snapshots_formatted.append({
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
        
        # 计算时期对比（使用日级数据处理）
        current_daily_values = get_daily_snapshots_from_hourly(asset_snapshots_formatted, start_time, end_time)
        previous_daily_values = get_daily_snapshots_from_hourly(previous_snapshots_formatted, previous_start, previous_end)
        
        # 计算时期对比
        current_metrics = calculate_performance_from_values(current_daily_values, 365)
        previous_metrics = calculate_performance_from_values(previous_daily_values, 365)
        
        period_comparison = {
            "current": current_metrics,
            "previous": previous_metrics
        }
        
        result = {
            "asset_snapshots": asset_snapshots_formatted,
            "strategy_pnl": strategy_pnl_formatted,
            "strategy_fee": strategy_fee_formatted,
            "performance_metrics": performance_metrics,
            "period_comparison": period_comparison,
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

@router.get("/dashboard/position-status")
async def get_position_status(
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(deps.get_db_session), 
    project_id: int = Depends(get_project_id)
):
    """
    获取仓位状态数据，包含：
    1. 最新仓位数据
    2. 24小时前的历史数据
    3. 各项指标的变化率
    """
    try:
        logger.info(f"Getting position status for project_id: {project_id}")
        db.query()
        # 获取最新数据
        engine = engine_manager.get_client(project_id)
        try:
            if not engine:
                project_config = db.query(ProjectConfig).filter(ProjectConfig.project_id == project_id).first()
                position_data = project_config.position_data
            else:
                position_data = await engine.invoke("get_position_state")
            current_data = {
                "total_amount": Decimal(position_data.get('total_amount', '0')),
                "activate_amount": Decimal(position_data.get('activate_amount', '0')),
                "pnl": Decimal(position_data.get('pnl', '0')),
                "friction": Decimal(position_data.get('friction', '0')),
                "fee": Decimal(position_data.get('fee', '0')),
                "virtual_pnl": Decimal(position_data.get('virtual_pnl', '0')),
                "positions": position_data.get('positions', []),
                "asset_count": position_data.get('asset_count', 0),
                "timestamp": datetime.now()
            }
        except Exception as e:
            logger.error(f"Failed to get current position data: {str(e)}")
            # 如果获取数据失败，也返回null
            return None
        
        # 获取24小时前的历史数据
        history_time = datetime.now() - timedelta(hours=24)
        historical_snapshot = db.query(AssetSnapshot).filter(
            AssetSnapshot.project_id == project_id,
            AssetSnapshot.snapshot_time <= history_time
        ).order_by(AssetSnapshot.snapshot_time.desc()).first()
        
        # 计算变化率
        def calculate_change_rate(current, historical):
            if historical and historical != 0:
                return ((current - historical) / historical) * 100
            return 0
        
        historical_data = None
        if historical_snapshot:
            historical_data = {
                "total_amount": historical_snapshot.total_amount,
                "activate_amount": historical_snapshot.activate_amount,
                "pnl": historical_snapshot.pnl,
                "friction": historical_snapshot.friction,
                "fee": historical_snapshot.fee,
                "virtual_pnl": historical_snapshot.virtual_pnl,
                "timestamp": historical_snapshot.snapshot_time
            }
        
        # 计算变化率
        change_rates = {}
        if historical_data:
            change_rates = {
                "total_amount_change": calculate_change_rate(current_data["total_amount"], historical_data["total_amount"]),
                "activate_amount_change": calculate_change_rate(current_data["activate_amount"], historical_data["activate_amount"]),
                "pnl_change": calculate_change_rate(current_data["pnl"], historical_data["pnl"]),
                "friction_change": calculate_change_rate(current_data["friction"], historical_data["friction"]),
                "fee_change": calculate_change_rate(current_data["fee"], historical_data["fee"]),
                "virtual_pnl_change": calculate_change_rate(current_data["virtual_pnl"], historical_data["virtual_pnl"])
            }
        else:
            change_rates = {
                "total_amount_change": 0,
                "activate_amount_change": 0,
                "pnl_change": 0,
                "friction_change": 0,
                "fee_change": 0,
                "virtual_pnl_change": 0
            }
        
        result = {
            "current": {
                "total_amount": float(current_data["total_amount"]),
                "activate_amount": float(current_data["activate_amount"]),
                "pnl": float(current_data["pnl"]),
                "friction": float(current_data["friction"]),
                "fee": float(current_data["fee"]),
                "virtual_pnl": float(current_data["virtual_pnl"]),
                "positions": current_data["positions"],
                "asset_count": current_data["asset_count"],
                "position_count": len(current_data["positions"]),
                "timestamp": current_data["timestamp"].isoformat()
            },
            "historical": {
                "total_amount": float(historical_data["total_amount"]) if historical_data else 0,
                "activate_amount": float(historical_data["activate_amount"]) if historical_data else 0,
                "pnl": float(historical_data["pnl"]) if historical_data else 0,
                "friction": float(historical_data["friction"]) if historical_data else 0,
                "fee": float(historical_data["fee"]) if historical_data else 0,
                "virtual_pnl": float(historical_data["virtual_pnl"]) if historical_data else 0,
                "timestamp": historical_data["timestamp"].isoformat() if historical_data else None
            },
            "change_rates": change_rates
        }
        
        logger.info(f"Position status data prepared successfully")
        return result
        
    except Exception as e:
        logger.error(f"Position status error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取仓位状态失败: {str(e)}"
        )