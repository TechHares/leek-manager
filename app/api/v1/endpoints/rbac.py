from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict
from app.api.deps import get_db_session
from app.models.rbac import Role
from app.schemas.rbac import (
    RoleCreate,
    RoleUpdate,
    RoleResponse
)
from app.utils.permission_scanner import get_available_permissions, scan_api_endpoints

router = APIRouter()

@router.post("/authorization/roles", response_model=RoleResponse)
async def create_role(
    role: RoleCreate,
    db: Session = Depends(get_db_session)
):
    """创建新角色"""
    db_role = Role(**role.dict())
    db.add(db_role)
    db.commit()
    db.refresh(db_role)
    return db_role

@router.get("/authorization/roles", response_model=List[RoleResponse])
async def list_roles(
    db: Session = Depends(get_db_session)
):
    """获取所有角色"""
    return db.query(Role).all()

@router.put("/authorization/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: int,
    role_update: RoleUpdate,
    db: Session = Depends(get_db_session)
):
    """更新角色信息"""
    db_role = db.query(Role).filter(Role.id == role_id).first()
    if not db_role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    update_data = role_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_role, key, value)
    
    db.commit()
    db.refresh(db_role)
    return db_role

@router.delete("/authorization/roles/{role_id}")
async def delete_role(
    role_id: int,
    db: Session = Depends(get_db_session)
):
    """删除角色"""
    db_role = db.query(Role).filter(Role.id == role_id).first()
    if not db_role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    db.delete(db_role)
    db.commit()
    return {"message": "Role deleted successfully"}

@router.get("/authorization/permissions")
async def get_permissions():
    return scan_api_endpoints()
