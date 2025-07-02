from enum import Enum
from typing import List, Optional, Any
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, field_validator
from .enums import AssetType, TradeInsType

class PositionSide(int, Enum):
    LONG = 1
    SHORT = 2
    NEUTRAL = 4

class Asset(BaseModel):
    asset_type: AssetType
    ins_type: TradeInsType
    symbol: str
    side: PositionSide
    price: Decimal
    ratio: Decimal
    quote_currency: Optional[str] = None
    extra: Optional[Any] = None
    class Config:
        from_attributes = True

class StrategyPositionConfig(BaseModel):
    principal: Decimal
    leverage: Decimal
    order_type: int
    executor_id: Optional[int] = None

    class Config:
        from_attributes = True

class Signal(BaseModel):
    id: str
    project_id: int
    data_source_instance_id: int
    data_source_class_name: str
    strategy_id: int
    strategy_instance_id: str
    strategy_name: str
    strategy_class_name: str
    strategy_template_name: str
    signal_time: datetime
    assets: List[Asset] = []
    config: Optional[StrategyPositionConfig] = None
    extra: Optional[Any] = None

    class Config:
        from_attributes = True 

    @field_validator('id', mode='before')
    @classmethod
    def convert_id_to_str(cls, v):
        return str(v)