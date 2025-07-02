from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from app.models.rbac import PermissionType

class PermissionItem(BaseModel):
    id: str
    actions: List[str]

class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None

class RoleCreate(RoleBase):
    permissions: Optional[List[PermissionItem]] = None

class RoleUpdate(RoleBase):
    permissions: Optional[List[PermissionItem]] = None

class RoleResponse(RoleBase):
    id: int
    permissions: Optional[List[PermissionItem]] = None

    class Config:
        from_attributes = True

class UserRoleCreate(BaseModel):
    user_id: int
    role_id: int 