#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
性能分析服务模块

提供基于订单和仓位数据的性能指标计算功能
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from app.models.order import Order
from app.models.position import Position
from app.models.project_config import ProjectConfig
from app.models.strategy import Strategy
from leek_core.analysis.performance import PerformanceMetrics
from leek_core.utils import get_logger

logger = get_logger(__name__)

class PerformanceAnalysisService:
    """性能分析服务"""
    
    def __init__(self):
        self.cache = {}
        self.cache_ttl = 3600  # 1小时缓存过期
    
    def get_project_performance(self, project_id: int, 
                               start_time: datetime = None, end_time: datetime = None,
                               db: Session = None):
        """获取项目整体性能指标"""
        cache_key = f"project_{project_id}_start_{start_time}_end_{end_time}"
        
        # 检查缓存
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if datetime.now().timestamp() - timestamp < self.cache_ttl:
                return cached_data
        
        # 计算性能指标
        result = self._calculate_performance(project_id, start_time, end_time, db)
        
        # 更新缓存
        self.cache[cache_key] = (result, datetime.now().timestamp())
        return result
    
    def get_strategies_performance(self, project_id: int,
                                  start_time: datetime = None, end_time: datetime = None,
                                  db: Session = None):
        """获取项目下所有策略的性能数据"""
        
        # 设置默认时间范围
        if not end_time:
            end_time = datetime.now()
        if not start_time:
            start_time = end_time - timedelta(days=30)
        
        # 确保时间对象都是时区无关的
        if end_time.tzinfo is not None:
            end_time = end_time.replace(tzinfo=None)
        if start_time.tzinfo is not None:
            start_time = start_time.replace(tzinfo=None)
        
        # 直接查询平仓订单，只查询需要的字段（包含 position_id 便于计算持仓时长）
        query = db.query(
            Order.strategy_id,
            Order.position_id,
            Order.pnl,
            Order.order_time,
            Order.finish_time
        ).filter(
            Order.project_id == project_id,
            Order.is_open == False,  # 只查平仓订单
            Order.pnl.isnot(None),   # 确保有盈亏数据
            Order.order_time >= start_time,
            Order.order_time <= end_time
        )
        
        closed_orders = query.order_by(Order.order_time).all()
        logger.info(f"项目 {project_id} 平仓订单总数: {len(closed_orders)}")
        
        if not closed_orders:
            return {}
        
        # 调试：输出前几个订单的信息
        for i, order in enumerate(closed_orders[:3]):
            logger.info(f"订单 {i+1}: 策略ID={order.strategy_id}, PnL={order.pnl}, 时间={order.order_time}")
        
        # 生成策略累计盈利曲线
        strategies_curves = self._generate_strategies_profit_curves(
            closed_orders, start_time, end_time, project_id, db
        )
        
        # 计算每个 position_id 的开仓时间，便于更准确计算持仓时长
        position_ids = list({o.position_id for o in closed_orders if getattr(o, 'position_id', None) is not None})
        pos_open_time_map: Dict[int, datetime] = {}
        if position_ids:
            open_orders = db.query(
                Order.position_id,
                Order.order_time
            ).filter(
                Order.project_id == project_id,
                Order.is_open == True,
                Order.position_id.in_(position_ids)
            ).all()
            for rec in open_orders:
                # 如果同一 position_id 存在多条开仓记录，取最早时间
                exist = pos_open_time_map.get(rec.position_id)
                if exist is None or rec.order_time < exist:
                    pos_open_time_map[rec.position_id] = rec.order_time

        # 计算基础统计指标（传入开仓时间映射以获得更准确的平均持仓时间）
        strategy_stats = self._calculate_strategy_stats(closed_orders, pos_open_time_map)
        
        # 获取策略名称映射
        strategy_names = {}
        if strategy_stats:
            strategies = db.query(Strategy.id, Strategy.name).filter(
                Strategy.project_id == project_id,
                Strategy.id.in_(strategy_stats.keys())
            ).all()
            strategy_names = {s.id: s.name for s in strategies}
        
        # 构建最终结果
        results = {}
        for strategy_id, stats in strategy_stats.items():
            strategy_name = strategy_names.get(strategy_id, f"策略{strategy_id}")
            
            results[strategy_id] = {
                'strategy_name': strategy_name,
                'strategy_id': strategy_id,
                'profit_curve': strategies_curves.get(strategy_id, []),
                **stats
            }
            
            # 调试：输出策略统计信息
            logger.info(f"策略 {strategy_id} ({strategy_name}): 总盈利={stats['total_pnl']}, 胜率={stats['win_rate']:.2%}, 交易次数={stats['total_trades']}")
        
        logger.info(f"计算完成，共 {len(results)} 个策略")
        return results
    
    def _generate_strategies_profit_curves(self, closed_orders: List[Order], 
                                          start_time: datetime, end_time: datetime,
                                          project_id: int, db: Session = None):
        """生成策略累计盈利曲线"""
        
        # 确定时间间隔
        time_delta = end_time - start_time
        days = time_delta.days
        
        if days <= 7:
            interval_hours = 1  # 1小时一个点
        elif days <= 30:
            interval_hours = 4  # 4小时一个点
        elif days <= 90:
            interval_hours = 6  # 6小时一个点
        elif days <= 180:
            interval_hours = 12  # 12小时一个点
        else:
            interval_hours = 24  # 1天一个点
        
        logger.info(f"时间范围: {days}天, 使用间隔: {interval_hours}小时")
        
        # 生成时间点
        time_points = []
        current_time = start_time.replace(minute=0, second=0, microsecond=0)
        while current_time <= end_time:
            time_points.append(current_time)
            current_time += timedelta(hours=interval_hours)
        
        # 按策略ID分组订单
        orders_by_strategy = {}
        for order in closed_orders:
            strategy_id = order.strategy_id
            if strategy_id not in orders_by_strategy:
                orders_by_strategy[strategy_id] = []
            orders_by_strategy[strategy_id].append(order)
        
        # 为每个策略生成累计盈利曲线，确保所有策略都有相同的时间点
        strategies_curves = {}
        
        # 获取所有策略ID
        all_strategy_ids = set(order.strategy_id for order in closed_orders)
        
        for strategy_id in all_strategy_ids:
            # 获取该策略的订单
            strategy_orders = [o for o in closed_orders if o.strategy_id == strategy_id]
            strategy_orders.sort(key=lambda x: x.order_time)  # 按时间排序
            
            curve = []
            cumulative_pnl = 0.0
            order_index = 0
            
            for time_point in time_points:
                # 累加到当前时间点为止的所有盈利
                while (order_index < len(strategy_orders) and 
                       strategy_orders[order_index].order_time <= time_point):
                    cumulative_pnl += float(strategy_orders[order_index].pnl or 0)
                    order_index += 1
                
                curve.append({
                    'time': time_point.isoformat(),
                    'value': cumulative_pnl
                })
            
            strategies_curves[strategy_id] = curve
        
        return strategies_curves
    
    def _calculate_strategy_stats(self, closed_orders: List[Order], pos_open_time_map: Optional[Dict[int, datetime]] = None):
        """计算策略基础统计指标"""
        strategy_stats = {}
        
        for order in closed_orders:
            strategy_id = order.strategy_id
            if strategy_id not in strategy_stats:
                strategy_stats[strategy_id] = {
                    'total_pnl': 0.0,
                    'winning_trades': 0,
                    'losing_trades': 0,
                    'total_trades': 0,
                    'holding_times': []
                }
            
            pnl = float(order.pnl or 0)
            strategy_stats[strategy_id]['total_pnl'] += pnl
            strategy_stats[strategy_id]['total_trades'] += 1
            
            if pnl > 0:
                strategy_stats[strategy_id]['winning_trades'] += 1
            elif pnl < 0:
                strategy_stats[strategy_id]['losing_trades'] += 1
            
            # 计算持仓时间
            duration = None
            if order.finish_time:
                open_time = None
                if pos_open_time_map is not None and getattr(order, 'position_id', None) in pos_open_time_map:
                    open_time = pos_open_time_map.get(order.position_id)
                # 如果能拿到对应 position 的开仓时间，按开仓->平仓计算
                if open_time is not None:
                    duration = (order.finish_time - open_time).total_seconds() / 3600
                # 否则退化为使用该平仓订单的下单时间与完成时间计算（可能会被撮合为接近零）
                elif order.order_time is not None:
                    duration = (order.finish_time - order.order_time).total_seconds() / 3600
            if duration is not None:
                strategy_stats[strategy_id]['holding_times'].append(duration)
        
        # 计算最终指标
        for strategy_id, stats in strategy_stats.items():
            # 胜率
            win_rate = stats['winning_trades'] / stats['total_trades'] if stats['total_trades'] > 0 else 0
            
            # 盈亏比
            strategy_orders = [o for o in closed_orders if o.strategy_id == strategy_id]
            winning_pnl = [float(o.pnl) for o in strategy_orders if float(o.pnl) > 0]
            losing_pnl = [abs(float(o.pnl)) for o in strategy_orders if float(o.pnl) < 0]
            
            avg_win = sum(winning_pnl) / len(winning_pnl) if winning_pnl else 0
            avg_loss = sum(losing_pnl) / len(losing_pnl) if losing_pnl else 0
            profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
            
            # 平均持仓时间
            avg_holding_time = sum(stats['holding_times']) / len(stats['holding_times']) if stats['holding_times'] else 0
            
            strategy_stats[strategy_id].update({
                'win_rate': win_rate,
                'profit_loss_ratio': profit_loss_ratio,
                'avg_holding_time': avg_holding_time,
                # 暂时设置为0，因为需要更复杂的计算
                'annualized_return': 0.0,
                'max_drawdown': 0.0,
                'volatility': 0.0,
                'sharpe_ratio': 0.0
            })
        
        return strategy_stats
    
    def get_equity_curve(self, project_id: int,
                        start_time: datetime = None, end_time: datetime = None,
                        db: Session = None):
        """获取项目整体资产曲线数据"""
        
        # 获取项目配置
        project_config = db.query(ProjectConfig).filter(
            ProjectConfig.project_id == project_id
        ).first()
        
        if not project_config or not project_config.position_setting:
            return []
        
        init_amount = Decimal(project_config.position_setting.get('init_amount', '10000'))
        
        # 获取订单数据
        query = db.query(Order).filter(Order.project_id == project_id)
        if start_time:
            query = query.filter(Order.order_time >= start_time)
        if end_time:
            query = query.filter(Order.order_time <= end_time)
        
        orders = query.order_by(Order.order_time).all()
        
        # 获取未平仓仓位
        open_positions = db.query(Position).filter(
            Position.project_id == project_id,
            Position.is_closed == False
        ).all()
        
        # 构建资产曲线
        return self._build_hourly_equity_curve(orders, open_positions, init_amount)
    
    def get_trade_statistics(self, project_id: int,
                           start_time: datetime = None, end_time: datetime = None,
                           db: Session = None):
        """获取交易统计数据"""
        
        # 获取订单数据
        query = db.query(Order).filter(Order.project_id == project_id)
        if start_time:
            query = query.filter(Order.order_time >= start_time)
        if end_time:
            query = query.filter(Order.order_time <= end_time)
        
        orders = query.order_by(Order.order_time).all()
        
        return self._calculate_trade_metrics(orders)
    
    def _calculate_performance(self, project_id: int, 
                              start_time: datetime = None, end_time: datetime = None,
                              db: Session = None):
        """计算项目整体性能指标"""
        
        # 获取项目配置
        project_config = db.query(ProjectConfig).filter(
            ProjectConfig.project_id == project_id
        ).first()
        
        if not project_config or not project_config.position_setting:
            return self._empty_performance_result()
        
        init_amount = Decimal(project_config.position_setting.get('init_amount', '10000'))
        
        # 获取所有订单数据
        query = db.query(Order).filter(Order.project_id == project_id)
        if start_time:
            query = query.filter(Order.order_time >= start_time)
        if end_time:
            query = query.filter(Order.order_time <= end_time)
        
        orders = query.order_by(Order.order_time).all()
        
        logger.info(f"项目 {project_id} 订单总数: {len(orders)}")
        logger.info(f"项目 {project_id} 开仓订单: {len([o for o in orders if o.is_open])}")
        logger.info(f"项目 {project_id} 平仓订单: {len([o for o in orders if not o.is_open])}")
        
        # 获取所有未平仓仓位
        open_positions = db.query(Position).filter(
            Position.project_id == project_id,
            Position.is_closed == False
        ).all()
        
        # 构建资产曲线
        equity_curve = self._build_equity_curve(orders, open_positions, init_amount)
        
        # 计算各项指标
        return self._calculate_metrics(equity_curve, orders, open_positions)
    
    def _build_equity_curve(self, orders: List[Order], open_positions: List[Position], 
                           init_amount: Decimal) -> List[float]:
        """构建资产曲线"""
        if not orders:
            return [float(init_amount)]
        
        # 按小时分组订单
        hourly_data = {}
        
        for order in orders:
            hour_key = order.order_time.replace(minute=0, second=0, microsecond=0)
            if hour_key not in hourly_data:
                hourly_data[hour_key] = []
            hourly_data[hour_key].append(order)
        
        # 计算每小时的资产变化
        equity_curve = []
        current_amount = float(init_amount)
        
        for hour in sorted(hourly_data.keys()):
            hour_orders = hourly_data[hour]
            
            for order in hour_orders:
                if order.is_open:  # 开仓
                    current_amount -= float(order.settle_amount or 0)
                else:  # 平仓
                    current_amount += float(order.settle_amount or 0) + float(order.pnl or 0)
            
            equity_curve.append(current_amount)
        
        # 加上未平仓仓位的盈亏
        if open_positions:
            unrealized_pnl = sum(float(pos.pnl or 0) for pos in open_positions)
            if equity_curve:
                equity_curve[-1] += unrealized_pnl
            else:
                equity_curve.append(current_amount + unrealized_pnl)
        
        return equity_curve
    
    def _build_hourly_equity_curve(self, orders: List[Order], open_positions: List[Position], 
                                  init_amount: Decimal) -> List[Dict]:
        """构建带时间戳的小时级资产曲线"""
        if not orders:
            return [{"time": datetime.now().isoformat(), "value": float(init_amount)}]
        
        # 按小时分组订单
        hourly_data = {}
        
        for order in orders:
            hour_key = order.order_time.replace(minute=0, second=0, microsecond=0)
            if hour_key not in hourly_data:
                hourly_data[hour_key] = []
            hourly_data[hour_key].append(order)
        
        # 计算每小时的资产变化
        equity_curve = []
        current_amount = float(init_amount)
        
        for hour in sorted(hourly_data.keys()):
            hour_orders = hourly_data[hour]
            
            for order in hour_orders:
                if order.is_open:  # 开仓
                    current_amount -= float(order.settle_amount or 0)
                else:  # 平仓
                    current_amount += float(order.settle_amount or 0) + float(order.pnl or 0)
            
            # 加上未平仓仓位的盈亏
            unrealized_pnl = sum(float(pos.pnl or 0) for pos in open_positions)
            
            equity_curve.append({
                "time": hour.isoformat(),
                "value": current_amount + unrealized_pnl
            })
        
        return equity_curve
    
    def _calculate_metrics(self, equity_curve: List[float], orders: List[Order], 
                          open_positions: List[Position]) -> Dict:
        """计算所有性能指标"""
        
        if not equity_curve or len(equity_curve) < 2:
            return self._empty_performance_result()
        
        # 使用现有的性能计算器
        performance_calculator = PerformanceMetrics(risk_free_rate=0.02)
        basic_metrics = performance_calculator.calculate_all_metrics(equity_curve, periods_per_year=365*24)
        
        # 计算交易统计
        trade_metrics = self._calculate_trade_metrics(orders)
        
        # 计算资金利用率
        utilization_metrics = self._calculate_utilization_metrics(orders, open_positions)
        
        return {
            **basic_metrics,
            **trade_metrics,
            **utilization_metrics
        }
    
    def _calculate_trade_metrics(self, orders: List[Order]) -> Dict:
        """计算交易相关指标"""
        
        # 只统计已完成的平仓订单
        closed_orders = [o for o in orders if not o.is_open and o.pnl is not None]
        
        if not closed_orders:
            return {
                'win_rate': 0.0,
                'profit_loss_ratio': 0.0,
                'avg_holding_time': 0.0,
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0
            }
        
        # 胜率
        winning_trades = [o for o in closed_orders if o.pnl > 0]
        losing_trades = [o for o in closed_orders if o.pnl < 0]
        win_rate = len(winning_trades) / len(closed_orders)
        
        # 盈亏比
        avg_win = float(sum(o.pnl for o in winning_trades) / len(winning_trades)) if winning_trades else 0
        avg_loss = abs(float(sum(o.pnl for o in losing_trades) / len(losing_trades))) if losing_trades else 0
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        
        # 平均持仓时间
        holding_times = []
        for order in closed_orders:
            if order.finish_time and order.order_time:
                duration = (order.finish_time - order.order_time).total_seconds() / 3600
                holding_times.append(duration)
        
        avg_holding_time = sum(holding_times) / len(holding_times) if holding_times else 0
        
        return {
            'win_rate': win_rate,
            'profit_loss_ratio': profit_loss_ratio,
            'avg_holding_time': avg_holding_time,
            'total_trades': len(closed_orders),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades)
        }
    
    def _calculate_utilization_metrics(self, orders: List[Order], 
                                     open_positions: List[Position]) -> Dict:
        """计算资金利用率指标"""
        # 计算总投入资金
        total_investment = sum(float(o.settle_amount or 0) for o in orders if o.is_open)
        
        # 计算当前占用资金
        current_utilization = sum(float(pos.amount or 0) for pos in open_positions)
        
        # 计算平均利用率（简化计算）
        avg_utilization = total_investment / len(orders) if orders else 0
        
        return {
            'total_investment': total_investment,
            'current_utilization': current_utilization,
            'avg_utilization': avg_utilization,
            'utilization_rate': current_utilization / total_investment if total_investment > 0 else 0
        }
    
    def _empty_performance_result(self) -> Dict:
        """返回空的性能指标结果"""
        return {
            "annualized_return": 0.0,
            "max_drawdown": {"max_drawdown": 0.0, "drawdown_duration": 0},
            "volatility": 0.0,
            "sharpe_ratio": 0.0,
            'win_rate': 0.0,
            'profit_loss_ratio': 0.0,
            'avg_holding_time': 0.0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_investment': 0.0,
            'current_utilization': 0.0,
            'avg_utilization': 0.0,
            'utilization_rate': 0.0,
            'total_pnl': 0.0
        }
    
    def clear_cache(self):
        """清除缓存"""
        self.cache.clear()

# 全局实例
performance_service = PerformanceAnalysisService()