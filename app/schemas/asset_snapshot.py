from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime
from decimal import Decimal

class AssetSnapshotBase(BaseModel):
    project_id: int
    snapshot_time: datetime
    activate_amount: Decimal
    pnl: Decimal = Decimal('0')
    friction: Decimal = Decimal('0')
    fee: Decimal = Decimal('0')
    total_amount: Decimal
    virtual_pnl: Decimal = Decimal('0')
    position_amount: int = 0

class AssetSnapshotCreate(AssetSnapshotBase):
    pass

class AssetSnapshotOut(AssetSnapshotBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            Decimal: str,
            datetime: lambda dt: dt.isoformat()
        }

class AssetSnapshotFilter(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None 