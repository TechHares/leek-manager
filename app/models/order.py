from sqlalchemy import Column, String, Integer, DateTime, Numeric, Boolean, JSON, BigInteger, DECIMAL
from app.models.base import BaseModel
from datetime import datetime

class Order(BaseModel):
    __tablename__ = "orders"

    position_id = Column(BigInteger().with_variant(Integer, "sqlite"), index=True, nullable=True, comment="仓位ID")
    exec_order_id = Column(BigInteger().with_variant(Integer, "sqlite"), index=True, nullable=False, comment="执行订单ID")
    signal_id = Column(BigInteger().with_variant(Integer, "sqlite"), index=True, nullable=False, comment="信号ID")
    strategy_id = Column(BigInteger().with_variant(Integer, "sqlite"), index=True, nullable=False, comment="策略ID")
    project_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=False, index=True)
    strategy_instant_id = Column(String(200), index=True, nullable=False, comment="策略实例ID")
    order_status = Column(String(32), nullable=False, comment="订单状态")
    order_time = Column(DateTime, nullable=False, comment="订单时间")
    ratio = Column(DECIMAL(36, 20), nullable=True, comment="仓位比例")

    symbol = Column(String(32), nullable=False, comment="交易标的")
    quote_currency = Column(String(16), nullable=False, comment="计价货币")
    ins_type = Column(Integer, nullable=False, comment="合约/现货类型")
    asset_type = Column(String(16), nullable=False, comment="资产类型")
    side = Column(String(8), nullable=False, comment="交易方向")

    is_open = Column(Boolean, nullable=False, comment="是否开仓")
    is_fake = Column(Boolean, nullable=False, default=False, comment="是否虚拟仓位")
    order_amount = Column(DECIMAL(36, 20), nullable=False, comment="订单金额")
    order_price = Column(DECIMAL(36, 20), nullable=False, comment="订单价格")
    order_type = Column(String(16), nullable=True, comment="订单类型")

    settle_amount = Column(DECIMAL(36, 20), nullable=True, comment="实际成交金额")
    execution_price = Column(DECIMAL(36, 20), nullable=True, comment="实际成交价格")
    sz = Column(DECIMAL(36, 20), nullable=True, comment="订单数量")
    sz_value = Column(DECIMAL(36, 20), nullable=True, comment="订单数量价值")
    fee = Column(DECIMAL(36, 20), nullable=True, comment="手续费")
    pnl = Column(DECIMAL(36, 20), nullable=True, comment="已实现盈亏")
    unrealized_pnl = Column(DECIMAL(36, 20), nullable=True, comment="未实现盈亏")
    finish_time = Column(DateTime, nullable=True, comment="完成时间")
    friction = Column(DECIMAL(36, 20), nullable=False, default=0, comment="摩擦成本")
    leverage = Column(DECIMAL(12, 8), nullable=False, default=1, comment="杠杆倍数")

    executor_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=True, comment="执行ID")
    trade_mode = Column(String(16), nullable=True, comment="交易模式")
    extra = Column(JSON, nullable=True, comment="附加信息")
    market_order_id = Column(String(200), nullable=True, comment="市场订单ID")

class ExecutionOrder(BaseModel):
    __tablename__ = "execution_orders"  # 执行订单

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, index=True)
    project_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=False)
    signal_id = Column(String(64), nullable=False)
    strategy_id = Column(BigInteger().with_variant(Integer, "sqlite"), nullable=False)
    strategy_instant_id = Column(String(64), nullable=False)
    target_executor_id = Column(String(64), nullable=False)
    execution_assets = Column(JSON, nullable=False)
    open_amount = Column(DECIMAL(36, 20), nullable=False)
    open_ratio = Column(DECIMAL(36, 20), nullable=False)
    extra = Column(JSON, nullable=True)
    leverage = Column(DECIMAL(12, 8), nullable=True)
    order_type = Column(Integer, nullable=False)
    trade_type = Column(Integer, nullable=False)
    trade_mode = Column(String(32), nullable=False)
    created_time = Column(DateTime, nullable=False)
    actual_ratio = Column(DECIMAL(36, 20), nullable=True)
    actual_amount = Column(DECIMAL(36, 20), nullable=True)
    actual_pnl = Column(DECIMAL(36, 20), nullable=True)
