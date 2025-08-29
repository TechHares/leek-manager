from pydantic import BaseModel, Field, field_validator
from typing import List, Any, Optional, Dict
from .enums import AssetType, TradeInsType, TradeMode, OrderType
from datetime import datetime
from decimal import Decimal

class PositionSettingBase(BaseModel):
    init_amount: str = "10000"
    max_strategy_amount: str = "5000"
    max_strategy_ratio: str = "0.5"
    max_symbol_amount: str = "3000"
    max_symbol_ratio: str = "0.3"
    max_amount: str = "1000"
    max_ratio: str = "0.1"
    
    default_leverage: str = "3"
    order_type: OrderType = OrderType.LimitOrder
    trade_type: TradeInsType = TradeInsType.FUTURES
    trade_mode: TradeMode = TradeMode.ISOLATED

class PositionSettingCreate(PositionSettingBase):
    pass

class PositionSettingUpdate(PositionSettingBase):
    pass

class PositionSettingOut(PositionSettingBase):
    positiondata: Optional[Dict[str, Any]] = None

class PositionBase(BaseModel):
    strategy_id: int
    strategy_instance_id: str
    project_id: int
    symbol: str
    quote_currency: str
    ins_type: str
    asset_type: str
    side: str
    cost_price: Decimal
    amount: Decimal
    ratio: Decimal
    sz: Optional[Decimal] = None
    executor_sz: Optional[Dict[str, Any]] = None
    executor_id: Optional[int] = None
    pnl: Decimal = Decimal('0')
    fee: Decimal = Decimal('0')
    friction: Decimal = Decimal('0')
    leverage: Decimal = Decimal('1')
    open_time: datetime
    close_time: Optional[datetime] = None
    is_closed: bool = False
    total_amount: Decimal = Decimal('0')
    total_sz: Decimal = Decimal('0')
    virtual_positions: Optional[List[Dict[str, Any]]] = None

class PositionUpdate(BaseModel):
    cost_price: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    ratio: Optional[Decimal] = None
    sz: Optional[Decimal] = None

class PositionOut(PositionBase):
    id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    max_sz: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    close_price: Optional[Decimal] = None

    class Config:
        from_attributes = True
        json_encoders = {
            Decimal: str,
            datetime: lambda dt: dt.isoformat()
        }

    @field_validator('id', 'strategy_instance_id', mode='before')
    @classmethod
    def convert_ids_to_str(cls, values):
        return str(values)

class PositionFilter(BaseModel):
    is_closed: Optional[bool] = None
    strategy_id: Optional[int] = None
    strategy_instance_id: Optional[str] = None
    symbol: Optional[str] = None
    ins_type: Optional[str] = None
    asset_type: Optional[str] = None
