from sqlalchemy import Column, String, Boolean, JSON
from app.models.base import BaseModel
from app.core.security import get_password_hash, verify_password

class User(BaseModel):
    __tablename__ = "users"

    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=True)
    hashed_password = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    
    # 用户角色ID列表，存储为JSON数组
    role_ids = Column(JSON, nullable=True, default=list)

    def set_password(self, password: str):
        """设置密码"""
        self.hashed_password = get_password_hash(password)

    def verify_password(self, password: str) -> bool:
        """验证密码"""
        return verify_password(password, self.hashed_password) 