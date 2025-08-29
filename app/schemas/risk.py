from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime


class RiskPolicyBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    class_name: str = Field(..., min_length=1, max_length=200)
    params: Optional[Dict[str, Any]] = None
    scope: str = Field(default="all")
    strategy_template_ids: Optional[List[str]] = None
    strategy_instance_ids: Optional[List[int]] = None


class RiskPolicyCreate(RiskPolicyBase):
    pass


class RiskPolicyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    class_name: Optional[str] = Field(None, min_length=1, max_length=200)
    params: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None
    scope: Optional[str] = None
    strategy_template_ids: Optional[List[str]] = None
    strategy_instance_ids: Optional[List[int]] = None


class RiskPolicyInDB(RiskPolicyBase):
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime
    is_enabled: bool = False
    is_deleted: bool = False

    class Config:
        from_attributes = True


class RiskPolicy(RiskPolicyInDB):
    pass


