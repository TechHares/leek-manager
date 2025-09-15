from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from app.schemas.enums import OrderStatus, OrderType, TradeInsType, TradeMode, AssetType
from pydantic import field_validator, model_validator

class OrderBase(BaseModel):
    position_id: Optional[str] = None
    strategy_id: int
    strategy_name: Optional[str] = None
    exec_name: Optional[str] = None
    strategy_instance_id: str
    exec_order_id: Optional[str] = None
    signal_id: str
    order_status: OrderStatus
    order_time: datetime
    symbol: str
    quote_currency: str
    ins_type: int
    asset_type: str
    side: str
    is_open: bool
    is_fake: bool
    order_amount: Decimal
    order_price: Decimal
    order_type: Optional[str] = None
    target_executor_id: Optional[str] = None
    settle_amount: Optional[Decimal] = None
    execution_price: Optional[Decimal] = None
    fee: Optional[Decimal] = None
    pnl: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    sz: Optional[Decimal] = None
    sz_value: Optional[Decimal] = None
    finish_time: Optional[datetime] = None
    friction: Decimal
    leverage: Decimal
    executor_id: Optional[int] = None
    trade_mode: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    market_order_id: Optional[str] = None

class OrderOut(OrderBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True
        coerce_numbers_to_str = True

    @model_validator(mode='before')
    @classmethod
    def convert_ids_to_str(cls, values):
        if isinstance(values, dict):
            for key in ['id', 'position_id', 'signal_id', 'exec_order_id']:
                if key in values and values[key] is not None:
                    values[key] = str(values[key])
        return values

class OrderFilter(BaseModel):
    position_id: Optional[int] = None
    strategy_id: Optional[int] = None
    order_status: Optional[OrderStatus] = None
    is_open: Optional[bool] = None
    is_fake: Optional[bool] = None
    market_order_id: Optional[str] = None
    executor_id: Optional[int] = None
    project_id: int

class ExecutionAsset(BaseModel):
    symbol: str
    asset_type: AssetType
    ins_type: TradeInsType
    side: int
    price: Optional[str] = None
    is_open: bool = True
    is_fake: bool = False
    ratio: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    quote_currency: str = "USDT"
    sz: Optional[Decimal] = None
    extra: Optional[Dict[str, Any]] = None
    position_id: Optional[str] = None
    actual_pnl: Optional[Decimal] = None

class ExecutionInfo(BaseModel):
    id: str = Field(..., description="Execution ID")
    signal_id: str
    strategy_id: int
    strategy_name: Optional[str] = None
    strategy_instance_id: str
    target_executor_id: str
    open_amount: Decimal
    open_ratio: Decimal
    actual_ratio: Optional[Decimal] = None
    actual_amount: Optional[Decimal] = None
    actual_pnl: Optional[Decimal] = None
    leverage: Decimal
    order_type: OrderType
    trade_type: TradeInsType
    trade_mode: TradeMode
    created_time: datetime
    execution_assets: List[ExecutionAsset]
    extra: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True
        populate_by_name = True
        coerce_numbers_to_str = True

    @model_validator(mode='before')
    @classmethod
    def convert_ids_to_str(cls, values):
        if isinstance(values, dict):
            if 'id' in values and values['id'] is not None:
                values['id'] = str(values['id'])
            if 'signal_id' in values and values['signal_id'] is not None:
                values['signal_id'] = str(values['signal_id'])
        return values