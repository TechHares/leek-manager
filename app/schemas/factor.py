from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class FactorConfigBase(BaseModel):
    class_name: str
    params: Optional[Dict[str, Any]] = {}
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    project_id: Optional[int] = None
    factor_count: Optional[int] = 1
    output_names: Optional[List[str]] = None
    categories: Optional[List[str]] = None

class FactorConfigCreate(FactorConfigBase):
    is_enabled: bool = True

class FactorConfigUpdate(BaseModel):
    class_name: Optional[str] = None
    params: Optional[Dict[str, Any]] = {}
    name: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    project_id: Optional[int] = None
    is_enabled: Optional[bool] = None
    factor_count: Optional[int] = None
    output_names: Optional[List[str]] = None
    categories: Optional[List[str]] = None

class FactorConfigInDB(FactorConfigCreate):
    id: int
    created_at: datetime
    updated_at: datetime
    is_enabled: bool = True
    is_deleted: bool = False

    class Config:
        from_attributes = True

class FactorConfigOut(FactorConfigInDB):
    pass

