from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.api.deps import get_db_session
from app.models.user import User
from app.api.deps import get_current_user
from app.schemas.user import UserCreate, UserUpdate, UserResponse

router = APIRouter()

# Endpoints
@router.get("/authorization/users", response_model=List[UserResponse])
async def list_users(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """获取所有用户列表"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看所有用户"
        )
    return db.query(User).all()

@router.post("/authorization/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """创建新用户"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="只有管理员可以创建用户"
        )
    
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在"
        )
    
    # 如果提供了邮箱，检查邮箱是否已存在
    if user_data.email:
        existing_email = db.query(User).filter(User.email == user_data.email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="邮箱已被使用"
            )
    
    # 创建用户
    user = User(
        username=user_data.username,
        email=user_data.email,
        is_active=user_data.is_active,
        is_admin=user_data.is_admin,
        role_ids=user_data.role_ids
    )
    user.set_password(user_data.password)
    
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.put("/authorization/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """更新用户信息"""
    if not current_user.is_admin and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能更新自己或管理员权限更新任意用户"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 更新邮箱（如果提供）
    if user_data.email is not None:
        # 检查邮箱是否被其他用户使用
        existing_user = db.query(User).filter(
            User.email == user_data.email,
            User.id != user_id
        ).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="邮箱已被其他用户使用"
            )
        user.email = user_data.email
    
    # 更新其他字段（如果提供）
    if user_data.is_active is not None:
        # 防止非管理员将自己设置为非活跃
        if not current_user.is_admin and user_id == current_user.id and not user_data.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="不能将自己设置为非活跃状态"
            )
        user.is_active = user_data.is_active
    
    # 只有管理员可以更新is_admin和role_ids
    if current_user.is_admin:
        if user_data.is_admin is not None:
            user.is_admin = user_data.is_admin
        
        if user_data.role_ids is not None:
            user.role_ids = user_data.role_ids
    
    # 更新密码（如果提供）
    if user_data.password:
        user.set_password(user_data.password)
    
    db.commit()
    db.refresh(user)
    return user

@router.delete("/authorization/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """删除用户"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以删除用户"
        )
    
    # 防止删除自己
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能删除自己的账户"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    db.delete(user)
    db.commit()
    return None 