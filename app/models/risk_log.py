from sqlalchemy import Column, String, DateTime, JSON, Integer, BigInteger, Boolean, DECIMAL, Text, Index
from datetime import datetime
from app.models.base import BaseModel


class RiskLog(BaseModel):
    """
    风控日志表 - 记录所有类型的风控触发情况
    
    用于记录三种类型的风控：
    1. 策略内嵌风控（在 on_cta_data 中触发的仓位风控，属于策略子策略）
    2. 信号风控（do_risk_policy 中对信号的风控，会使用假仓位代替）
    3. 主动风控（系统主动触发的风控检查）
    """
    __tablename__ = "risk_logs"

    # 基本信息
    project_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=False, index=True, comment="项目ID")
    risk_type = Column(String(32), nullable=False, index=True, comment="风控类型: embedded/signal/active")
    
    # 策略相关
    strategy_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=True, index=True, comment="策略ID")
    strategy_instance_id = Column(String(200), nullable=True, index=True, comment="策略实例ID")
    strategy_class_name = Column(String(200), nullable=True, comment="策略类名")
    
    # 风控策略信息
    risk_policy_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=True, comment="风控策略实例ID")
    risk_policy_class_name = Column(String(200), nullable=False, comment="风控策略类名")
    
    # 触发信息
    trigger_time = Column(DateTime, nullable=False, index=True, default=lambda: datetime.now(), comment="触发时间")
    trigger_reason = Column(Text, nullable=True, comment="触发原因描述")
    
    # 信号相关（仅 signal 类型）
    signal_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=True, index=True, comment="信号ID")
    execution_order_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=True, index=True, comment="执行订单ID")
    
    # 仓位相关（embedded 和 active 类型）
    position_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=True, index=True, comment="仓位ID")
    
    # 风控结果
    original_amount = Column(DECIMAL(36, 20), nullable=True, comment="原始交易金额")
    pnl = Column(DECIMAL(36, 20), nullable=True, comment="盈亏金额")
    
    # 扩展信息
    extra_info = Column(JSON, nullable=True, comment="额外信息")
    tags = Column(JSON, nullable=True, comment="标签")

    # 创建复合索引提高查询性能
    __table_args__ = (
        Index('idx_risk_log_strategy_time', 'strategy_instance_id', 'trigger_time'),
        Index('idx_risk_log_type_time', 'risk_type', 'trigger_time'),
        Index('idx_risk_log_project_time', 'project_id', 'trigger_time'),
    )


