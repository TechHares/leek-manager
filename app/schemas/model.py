from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class ModelBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    version: str = Field(..., min_length=1, max_length=50)
    project_id: Optional[int] = None
    training_config: Optional[Dict[str, Any]] = None
    label_generator_id: Optional[int] = None
    trainer_id: Optional[int] = None
    factor_ids: Optional[List[int]] = None
    metrics: Optional[Dict[str, Any]] = None
    # feature_config 统一使用字典格式：{'factors': [...], 'encoder_classes': {...}}
    feature_config: Optional[Dict[str, Any]] = None

class ModelCreate(ModelBase):
    file_path: str
    file_size: Optional[int] = None

class ModelUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    version: Optional[str] = Field(None, max_length=50)
    feature_config: Optional[Dict[str, Any]] = None

class ModelUpload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    version: str = Field(..., min_length=1, max_length=50)

class ModelInDB(ModelCreate):
    id: int
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ModelOut(ModelInDB):
    pass

