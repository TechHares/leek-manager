from sqlalchemy import Column, String, JSON
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
import enum

class PermissionType(str, enum.Enum):
    READ = "read"
    WRITE = "write"

class Role(BaseModel):
    __tablename__ = "roles"

    name = Column(String(50), unique=True, index=True, nullable=False)
    description = Column(String(200))
    
    # 角色的权限列表，存储为JSON格式
    # 格式例如: [{"resource": "users", "permission": "read"}, {"resource": "users", "permission": "write"}]
    permissions = Column(JSON, nullable=True) 