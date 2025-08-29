from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
from enum import Enum


class RiskType(str, Enum):
    """风控类型枚举"""
    EMBEDDED = "embedded"  # 策略内嵌风控（仓位风控）
    SIGNAL = "signal"      # 信号风控
    ACTIVE = "active"      # 主动风控


class RiskLogBase(BaseModel):
    """风控日志基础模型"""
    project_id: int = Field(..., description="项目ID")
    risk_type: RiskType = Field(..., description="风控类型")
    
    # 策略相关
    strategy_id: Optional[int] = Field(None, description="策略ID")
    strategy_instance_id: Optional[str] = Field(None, max_length=200, description="策略实例ID")
    strategy_class_name: Optional[str] = Field(None, max_length=200, description="策略类名")
    strategy_name: Optional[str] = Field(None, max_length=50, description="策略名称")
    
    # 风控策略信息
    risk_policy_id: Optional[int] = Field(None, description="风控策略实例ID")
    risk_policy_class_name: str = Field(..., max_length=200, description="风控策略类名")
    risk_policy_name: Optional[str] = Field(None, max_length=50, description="风控策略名称")
    
    # 触发信息
    trigger_time: datetime = Field(default_factory=datetime.now, description="触发时间")
    trigger_reason: Optional[str] = Field(None, description="触发原因描述")
    
    # 信号相关（仅 signal 类型）
    signal_id: Optional[int] = Field(None, description="信号ID")
    execution_order_id: Optional[int] = Field(None, description="执行订单ID")
    
    # 仓位相关（embedded 和 active 类型）
    position_id: Optional[int] = Field(None, description="仓位ID")
    
    # 风控结果
    original_amount: Optional[Decimal] = Field(None, description="原始交易金额")
    pnl: Optional[Decimal] = Field(None, description="盈亏金额")
    
    # 扩展信息
    extra_info: Optional[Dict[str, Any]] = Field(None, description="额外信息")
    tags: Optional[List[str]] = Field(None, description="标签")


class RiskLogQuery(BaseModel):
    """查询风控日志的参数模型"""
    project_id: Optional[int] = Field(None, description="项目ID")
    risk_type: Optional[RiskType] = Field(None, description="风控类型")
    strategy_id: Optional[int] = Field(None, description="策略ID")
    strategy_instance_id: Optional[str] = Field(None, description="策略实例ID")
    risk_policy_class_name: Optional[str] = Field(None, description="风控策略类名")
    
    # 时间范围
    start_time: Optional[datetime] = Field(None, description="开始时间")
    end_time: Optional[datetime] = Field(None, description="结束时间")
    
    # 分页
    page: int = Field(default=1, ge=1, description="页码")
    size: int = Field(default=20, ge=1, le=100, description="每页数量")
    
    # 排序
    order_by: Optional[str] = Field(default="trigger_time", description="排序字段")
    order_desc: bool = Field(default=True, description="是否降序")


class RiskLogInDB(RiskLogBase):
    """数据库中的风控日志模型"""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RiskLog(RiskLogInDB):
    """返回给客户端的风控日志模型"""
    pass


class RiskDashboardData(BaseModel):
    """风控仪表盘数据模型"""
    # 今日概况
    today_total_signals: int = Field(default=0, description="今日总信号数")
    today_blocked_signals: int = Field(default=0, description="今日被阻止信号数")
    today_block_rate: Decimal = Field(default=0, description="今日拦截率")
    
    # 最近7天趋势
    recent_7days_stats: List[Dict[str, Any]] = Field(default_factory=list, description="最近7天统计")
    
    # 策略风控排行
    top_triggered_strategies: List[Dict[str, Any]] = Field(default_factory=list, description="被风控最多的策略")
    
    # 风控策略效果
    policy_effectiveness: List[Dict[str, Any]] = Field(default_factory=list, description="风控策略效果")
    
    # 性能指标
    avg_evaluation_time: Optional[Decimal] = Field(None, description="平均风控评估耗时")
    total_avoided_loss: Optional[Decimal] = Field(None, description="总避免损失")