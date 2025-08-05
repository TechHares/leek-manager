from typing import Optional, List, Union
from pydantic import BaseModel, field_validator
from datetime import datetime
from decimal import Decimal
from enum import Enum

class TransactionType(int, Enum):
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

class TransactionOut(BaseModel):
    """交易流水输出模型"""
    id: int
    project_id: int
    strategy_id: Optional[int] = None
    strategy_instance_id: Optional[str] = None
    position_id: Optional[int] = None
    order_id: Optional[int] = None
    signal_id: Optional[int] = None
    executor_id: Optional[str] = None
    asset_key: str
    transaction_type: TransactionType
    amount: Decimal
    balance_before: Optional[Decimal] = None
    balance_after: Optional[Decimal] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class TransactionFilter(BaseModel):
    """交易流水过滤器"""
    id: Optional[int] = None  # 支持查询：流水ID、策略ID、仓位ID、订单ID、信号ID
    transaction_type: Optional[TransactionType] = None
    show_frozen: bool = True  # 是否显示冻结/解冻类型