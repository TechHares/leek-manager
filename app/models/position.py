from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, JSON, BigInteger
from datetime import datetime, UTC
from app.models.base import BaseModel

class Position(BaseModel):
    __tablename__ = "positions"

    strategy_id = Column(BigInteger, index=True, nullable=False, comment="策略ID")
    strategy_instance_id = Column(String(200), index=True, nullable=False, comment="策略实例ID")
    project_id = Column(BigInteger, nullable=False,index=True)
    symbol = Column(String(32), nullable=False, comment="交易标的")
    quote_currency = Column(String(16), nullable=False, comment="计价货币")
    ins_type = Column(String(16), nullable=False, comment="合约/现货类型")
    asset_type = Column(String(16), nullable=False, comment="资产类型")

    side = Column(String(8), nullable=False, comment="仓位方向")
    cost_price = Column(Numeric(36, 18), nullable=False, comment="开仓成本价")
    close_price = Column(Numeric(36, 18), nullable=True, comment="平仓成本价")
    current_price = Column(Numeric(36, 18), nullable=True, comment="当前价格")
    amount = Column(Numeric(36, 18), nullable=False, comment="仓位数量")
    ratio = Column(Numeric(36, 18), nullable=False, comment="占资金比例")
    sz = Column(Numeric(36, 18), nullable=True, comment="仓位大小")
    executor_sz = Column(JSON, nullable=True, comment="执行器仓位大小")
    max_sz = Column(Numeric(36, 18), nullable=True, comment="最大仓位大小")
    max_amount = Column(Numeric(36, 18), nullable=True, comment="最大价值")
    total_amount = Column(Numeric(36, 18), nullable=True, comment="累计价值")
    total_sz = Column(Numeric(36, 18), nullable=True, comment="累计仓位数量")

    executor_id = Column(String(64), index=True, nullable=True, comment="执行器ID")
    is_fake = Column(Boolean, default=False, comment="是否是假仓位")
    
    pnl = Column(Numeric(36, 18), default=0, nullable=False, comment="盈亏")
    fee = Column(Numeric(36, 18), default=0, nullable=False, comment="手续费")
    friction = Column(Numeric(36, 18), default=0, nullable=False, comment="摩擦成本")
    leverage = Column(Numeric(36, 18), default=1, nullable=False, comment="杠杆倍数")
    open_time = Column(DateTime, nullable=False, comment="开仓时间")
    close_time = Column(DateTime, nullable=True, comment="平仓时间")
    is_closed = Column(Boolean, default=False, comment="是否已平仓")
