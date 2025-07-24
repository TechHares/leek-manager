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
    price: Optional[Decimal] = None
    ratio: Optional[Decimal] = None
    quote_currency: Optional[str] = None
    extra: Optional[Any] = None
    
    @field_validator('price', 'ratio', mode='before')
    @classmethod
    def convert_decimal_fields(cls, v):
        if v is None:
            return Decimal('0')
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v
    
    class Config:
        from_attributes = True

class StrategyPositionConfig(BaseModel):
    principal: Optional[Decimal] = None
    leverage: Optional[Decimal] = None
    order_type: int
    executor_id: Optional[int] = None

    @field_validator('principal', 'leverage', mode='before')
    @classmethod
    def convert_decimal_fields(cls, v):
        if v is None:
            return Decimal('0')
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v

    class Config:
        from_attributes = True

class Signal(BaseModel):
    id: str
    project_id: int
    data_source_instance_id: Optional[int] = None
    data_source_class_name: str
    strategy_id: int
    strategy_instance_id: str
    strategy_name: Optional[str] = None
    strategy_class_name: str
    strategy_template_name: Optional[str] = None
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
    
    @field_validator('data_source_instance_id', mode='before')
    @classmethod
    def convert_data_source_instance_id(cls, v):
        if v is None:
            return None
        if isinstance(v, dict):
            # If it's stored as JSON, try to extract an ID
            return v.get('id') if isinstance(v, dict) else None
        return v