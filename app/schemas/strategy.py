from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class ComponentConfig(BaseModel):
    class_name: str
    config: Dict[str, Any]

class DataSourceConfig(ComponentConfig):
    id: int

class StrategyConfigBase(BaseModel):
    class_name: str
    params: Optional[Dict[str, Any]] = {}
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    data_source_config: List[DataSourceConfig] = []
    position_config: Optional[Dict[str, Any]] = None
    # 进出场子策略已移除
    risk_policies: Optional[List[ComponentConfig]] = None
    info_fabricator_configs: Optional[List[ComponentConfig]] = None
    project_id: Optional[int] = None
    data: Optional[Dict[str, Any]] = None

class StrategyConfigCreate(StrategyConfigBase):
    is_enabled: bool = True

class StrategyConfigUpdate(BaseModel):
    class_name: Optional[str] = None
    params: Optional[Dict[str, Any]] = {}
    name: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    data_source_config: Optional[List[DataSourceConfig]] = []
    position_config: Optional[Dict[str, Any]] = None
    # 进出场子策略已移除
    risk_policies: Optional[List[ComponentConfig]] = None
    info_fabricator_configs: Optional[List[ComponentConfig]] = None
    project_id: Optional[int] = None
    # 进出场子策略已移除
    is_enabled: Optional[bool] = None
    data: Optional[Dict[str, Any]] = None
    
class StrategyConfigInDB(StrategyConfigCreate):
    id: int
    created_at: datetime
    updated_at: datetime
    is_enabled: bool = True
    is_deleted: bool = False

    class Config:
        from_attributes = True

class StrategyConfigOut(StrategyConfigInDB):
    pass 