#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
数据处理工具

用于从资产快照数据中提取和处理数据，为性能指标计算提供干净的数值列表。
"""

from typing import List, Dict, Union
from datetime import datetime, timedelta
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


def get_daily_snapshots_from_hourly(
    snapshots: List[Dict], 
    start_date: datetime, 
    end_date: datetime,
    field: str = 'total_amount'
) -> List[float]:
    """
    从小时级快照数据中提取并补充0点的日级数据，直接返回指定字段的数值列表
    
    Args:
        snapshots: 小时级资产快照列表
        start_date: 开始日期
        end_date: 结束日期
        field: 要提取的字段名，默认为'total_amount'
        
    Returns:
        日级数值列表（0点数据）
    """
    try:
        # 创建日期范围
        daily_values = []
        
        current_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 按日期分组快照数据
        snapshots_by_date = {}
        for snapshot in snapshots:
            snapshot_time = snapshot.get('snapshot_time')
            if isinstance(snapshot_time, str):
                # 统一转换为本地时区
                if snapshot_time.endswith('Z'):
                    # UTC时间，转换为本地时间
                    utc_time = datetime.fromisoformat(snapshot_time.replace('Z', '+00:00'))
                    snapshot_time = utc_time.replace(tzinfo=None)  # 假设本地时区
                else:
                    snapshot_time = datetime.fromisoformat(snapshot_time)
            elif snapshot_time is None:
                continue
            
            # 确保是naive datetime（本地时区）
            if snapshot_time.tzinfo is not None:
                snapshot_time = snapshot_time.replace(tzinfo=None)
                
            date_key = snapshot_time.replace(hour=0, minute=0, second=0, microsecond=0)
            if date_key not in snapshots_by_date:
                snapshots_by_date[date_key] = []
            snapshots_by_date[date_key].append(snapshot)
        
        # 遍历每一天
        while current_date <= end_date:
            if current_date in snapshots_by_date:
                # 找到该日期的0点数据，如果没有则使用该日期的第一个数据
                day_snapshots = snapshots_by_date[current_date]
                
                # 优先选择0点的数据
                zero_hour_snapshot = None
                for snapshot in day_snapshots:
                    snapshot_time = snapshot.get('snapshot_time')
                    if isinstance(snapshot_time, str):
                        # 统一转换为本地时区
                        if snapshot_time.endswith('Z'):
                            utc_time = datetime.fromisoformat(snapshot_time.replace('Z', '+00:00'))
                            snapshot_time = utc_time.replace(tzinfo=None)  # 假设本地时区
                        else:
                            snapshot_time = datetime.fromisoformat(snapshot_time)
                    
                    # 确保是naive datetime（本地时区）
                    if snapshot_time.tzinfo is not None:
                        snapshot_time = snapshot_time.replace(tzinfo=None)
                    
                    if snapshot_time.hour == 0:
                        zero_hour_snapshot = snapshot
                        break
                
                # 如果没有0点数据，使用该日期的第一个数据
                if zero_hour_snapshot is None and day_snapshots:
                    zero_hour_snapshot = day_snapshots[0]
                
                if zero_hour_snapshot:
                    # 提取指定字段的数值
                    value = zero_hour_snapshot.get(field, 0)
                    daily_values.append(float(value))
                else:
                    # 该日期没有数据，使用默认值
                    daily_values.append(0.0)
            else:
                # 该日期没有数据，使用前一个有效数据或默认值
                if daily_values:
                    last_value = daily_values[-1]
                    daily_values.append(last_value)
                else:
                    # 如果没有任何历史数据，使用默认值
                    daily_values.append(0.0)
            
            current_date += timedelta(days=1)
        
        return daily_values
        
    except Exception as e:
        logger.error(f"从小时级快照提取日级数据失败: {e}")
        # 返回原始数据的字段值列表作为fallback
        return [float(snapshot.get(field, 0)) for snapshot in snapshots]





def calculate_performance_from_values(
    values: List[float],
    periods_per_year: int = 365
) -> Dict:
    """
    从数值列表计算性能指标
    
    Args:
        values: 数值列表（如资产总额序列）
        periods_per_year: 一年的期数，默认365（日数据）
        
    Returns:
        性能指标字典
    """
    try:
        from leek_core.analysis import calculate_performance_from_values as core_calculate_performance
        
        # 计算性能指标
        return core_calculate_performance(values, periods_per_year)
        
    except Exception as e:
        logger.error(f"从数值列表计算性能指标失败: {e}")
        return {
            "annualized_return": 0.0,
            "max_drawdown": {"max_drawdown": 0.0, "drawdown_duration": 0},
            "volatility": 0.0,
            "sharpe_ratio": 0.0
        } 