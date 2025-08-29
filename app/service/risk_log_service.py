#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
风控日志服务模块

提供风控日志的数据库操作服务，包括创建、查询等功能。
"""

from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc

from app.models.risk_log import RiskLog
from app.schemas.risk_log import RiskLogQuery, RiskDashboardData


class RiskLogService:
    """风控日志服务"""

    @staticmethod
    def get_risk_log(db: Session, log_id: int, project_id: int) -> Optional[RiskLog]:
        """根据ID获取风控日志"""
        return db.query(RiskLog).filter(
            RiskLog.id == log_id,
            RiskLog.project_id == project_id
        ).first()

    @staticmethod
    def get_risk_logs(
        db: Session,
        project_id: int,
        query_params: RiskLogQuery
    ) -> tuple[List[RiskLog], int]:
        """查询风控日志列表"""
        query = db.query(RiskLog).filter(RiskLog.project_id == project_id)

        # 应用过滤条件
        if query_params.risk_type:
            query = query.filter(RiskLog.risk_type == query_params.risk_type)
        if query_params.strategy_id:
            query = query.filter(RiskLog.strategy_id == query_params.strategy_id)
        if query_params.strategy_instance_id:
            query = query.filter(RiskLog.strategy_instance_id == query_params.strategy_instance_id)
        if query_params.risk_policy_class_name:
            query = query.filter(RiskLog.risk_policy_class_name.like(f"%{query_params.risk_policy_class_name}%"))
        if query_params.start_time:
            query = query.filter(RiskLog.trigger_time >= query_params.start_time)
        if query_params.end_time:
            query = query.filter(RiskLog.trigger_time <= query_params.end_time)

        # 排序
        order_column = getattr(RiskLog, query_params.order_by, RiskLog.trigger_time)
        if query_params.order_desc:
            query = query.order_by(desc(order_column))
        else:
            query = query.order_by(order_column)

        # 分页
        total = query.count()
        items = query.offset((query_params.page - 1) * query_params.size).limit(query_params.size).all()

        return items, total

    @staticmethod
    def get_dashboard_data(db: Session, project_id: int) -> RiskDashboardData:
        """获取风控仪表盘数据"""
        today = date.today()
        week_ago = today - timedelta(days=7)

        # 今日概况 - 简化版本，只统计日志总数
        today_stats = db.query(
            func.count(RiskLog.id).label('total_signals')
        ).filter(
            RiskLog.project_id == project_id,
            func.date(RiskLog.trigger_time) == today
        ).first()

        today_total = today_stats.total_signals or 0
        today_blocked = 0  # 不再统计拦截数
        today_block_rate = 0

        # 最近7天趋势 - 简化版本
        recent_stats = db.query(
            func.date(RiskLog.trigger_time).label('date'),
            func.count(RiskLog.id).label('total_signals')
        ).filter(
            RiskLog.project_id == project_id,
            func.date(RiskLog.trigger_time) >= week_ago
        ).group_by(
            func.date(RiskLog.trigger_time)
        ).order_by(
            func.date(RiskLog.trigger_time)
        ).all()

        recent_7days_stats = [
            {
                'date': str(stat.date),
                'total_signals': stat.total_signals,
                'blocked_signals': 0,
                'block_rate': 0
            }
            for stat in recent_stats
        ]

        # 日志最多的策略实例
        top_strategies = db.query(
            RiskLog.strategy_instance_id,
            func.count(RiskLog.id).label('log_count')
        ).filter(
            RiskLog.project_id == project_id,
            func.date(RiskLog.trigger_time) >= week_ago,
            RiskLog.strategy_instance_id.isnot(None)
        ).group_by(
            RiskLog.strategy_instance_id
        ).order_by(
            desc(func.count(RiskLog.id))
        ).limit(10).all()

        top_triggered_strategies = [
            {
                'strategy_instance_id': strategy.strategy_instance_id,
                'trigger_count': strategy.log_count
            }
            for strategy in top_strategies
        ]

        # 风控策略日志统计 - 简化版本
        policy_stats = db.query(
            RiskLog.risk_policy_class_name,
            func.count(RiskLog.id).label('total_evaluations')
        ).filter(
            RiskLog.project_id == project_id,
            func.date(RiskLog.trigger_time) >= week_ago
        ).group_by(
            RiskLog.risk_policy_class_name
        ).all()

        policy_effectiveness = [
            {
                'policy_class_name': policy.risk_policy_class_name,
                'total_evaluations': policy.total_evaluations,
                'triggered_count': 0,
                'trigger_rate': 0,
                'avg_duration_ms': None
            }
            for policy in policy_stats
        ]

        return RiskDashboardData(
            today_total_signals=today_total,
            today_blocked_signals=today_blocked,
            today_block_rate=today_block_rate,
            recent_7days_stats=recent_7days_stats,
            top_triggered_strategies=top_triggered_strategies,
            policy_effectiveness=policy_effectiveness,
            avg_evaluation_time=None,
            total_avoided_loss=None
        )