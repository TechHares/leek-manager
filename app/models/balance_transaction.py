from sqlalchemy import Column, String, Integer, DateTime, Numeric, Boolean, JSON, BigInteger, Enum as SQLEnum
from app.models.base import BaseModel
from datetime import datetime
from enum import Enum
from typing import Optional

class TransactionType(Enum):
    """流水类型枚举"""
    FROZEN = 0  # 冻结
    UNFROZEN = 1  # 解冻
    DEPOSIT = 2  # 充值
    WITHDRAW = 3  # 提现
    TRADE = 4  # 交易
    FEE = 5  # 手续费
    PNL = 6  # 盈亏
    FUNDING = 7  # 资金费
    SETTLE = 8  # 结算
    OTHER = 9  # 其他

    def __str__(self):
        return self.name.upper()

class BalanceTransaction(BaseModel):
    """
    余额流水表
    
    记录所有影响账户余额的交易流水，包括交易、费用、盈亏、资金变动等。
    """
    __tablename__ = "balance_transactions"
    project_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=False, index=True, comment="项目ID")
    strategy_id = Column(BigInteger().with_variant(Integer, "sqlite"), index=True, nullable=True, comment="策略ID")
    strategy_instance_id = Column(String(200), index=True, nullable=True, comment="策略实例ID")
    position_id = Column(BigInteger().with_variant(Integer, "sqlite"), index=True, nullable=True, comment="仓位ID")
    order_id = Column(BigInteger().with_variant(Integer, "sqlite"), index=True, nullable=True, comment="订单ID")
    signal_id = Column(BigInteger().with_variant(Integer, "sqlite"), index=True, nullable=True, comment="信号ID")
    executor_id = Column(String(64), index=True, nullable=True, comment="执行器ID")
    asset_key = Column(String(64), nullable=False, comment="资产键值")
    
    transaction_type = Column(SQLEnum(TransactionType), nullable=False, comment="流水类型")
    amount = Column(Numeric(36, 18), nullable=False, comment="流水金额")
    balance_before = Column(Numeric(36, 18), nullable=True, comment="变动前余额")
    balance_after = Column(Numeric(36, 18), nullable=True, comment="变动后余额")

    description = Column(String(500), nullable=True, comment="流水描述")