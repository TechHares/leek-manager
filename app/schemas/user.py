from typing import List, Optional
from pydantic import BaseModel, field_validator

class UserBase(BaseModel):
    username: str
    email: Optional[str] = None
    is_active: bool = True
    is_admin: bool = False
    role_ids: List[int] = []

class UserCreate(UserBase):
    password: str
    
    @field_validator('password')
    @classmethod
    def password_validation(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        return v

class UserUpdate(BaseModel):
    email: Optional[str] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    role_ids: Optional[List[int]] = None
    password: Optional[str] = None
    
    @field_validator('password')
    @classmethod
    def password_validation(cls, v):
        if v is not None and len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        return v

class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    is_active: bool
    is_admin: bool
    role_ids: List[int] = []
    
    class Config:
        from_attributes = True 