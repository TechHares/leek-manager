from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

class DataSourceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    class_name: str = Field(..., min_length=1, max_length=200)
    params: Optional[Dict[str, Any]] = None
    project_id: Optional[int] = None

class DataSourceCreate(DataSourceBase):
    pass

class DataSourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    class_name: Optional[str] = Field(None, min_length=1, max_length=200)
    params: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None

class DataSourceInDB(DataSourceBase):
    id: int
    created_at: datetime
    updated_at: datetime
    is_enabled: bool = False
    is_deleted: bool = False

    class Config:
        from_attributes = True

class DataSource(DataSourceInDB):
    pass 