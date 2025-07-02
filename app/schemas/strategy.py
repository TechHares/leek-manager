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
    enter_strategy_config: Optional[Dict[str, Any]] = None
    exit_strategy_config: Optional[Dict[str, Any]] = None
    risk_policies: Optional[List[ComponentConfig]] = None
    info_fabricator_configs: Optional[List[ComponentConfig]] = None
    project_id: Optional[int] = None
    data: Optional[Dict[str, Any]] = None

class StrategyConfigCreate(StrategyConfigBase):
    enter_strategy_class_name: str
    exit_strategy_class_name: str
    is_enabled: bool = True

class StrategyConfigUpdate(BaseModel):
    class_name: Optional[str] = None
    params: Optional[Dict[str, Any]] = {}
    name: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    data_source_config: Optional[List[DataSourceConfig]] = []
    position_config: Optional[Dict[str, Any]] = None
    enter_strategy_config: Optional[Dict[str, Any]] = None
    exit_strategy_config: Optional[Dict[str, Any]] = None
    risk_policies: Optional[List[ComponentConfig]] = None
    info_fabricator_configs: Optional[List[ComponentConfig]] = None
    project_id: Optional[int] = None
    enter_strategy_class_name: Optional[str] = None
    exit_strategy_class_name: Optional[str] = None
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