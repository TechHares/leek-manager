from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

class LabelGeneratorConfigBase(BaseModel):
    class_name: str
    params: Optional[Dict[str, Any]] = {}
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    project_id: Optional[int] = None

class LabelGeneratorConfigCreate(LabelGeneratorConfigBase):
    is_enabled: bool = True

class LabelGeneratorConfigUpdate(BaseModel):
    class_name: Optional[str] = None
    params: Optional[Dict[str, Any]] = {}
    name: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    project_id: Optional[int] = None
    is_enabled: Optional[bool] = None

class LabelGeneratorConfigInDB(LabelGeneratorConfigCreate):
    id: int
    created_at: datetime
    updated_at: datetime
    is_enabled: bool = True
    is_deleted: bool = False

    class Config:
        from_attributes = True

class LabelGeneratorConfigOut(LabelGeneratorConfigInDB):
    pass

