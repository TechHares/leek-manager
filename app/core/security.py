import hashlib
import secrets
import base64
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码
    
    使用一个简单的 SHA-256 + salt 哈希来验证密码，避免 bcrypt 依赖
    """
    if not hashed_password or ':' not in hashed_password:
        return False
    
    salt, stored_hash = hashed_password.split(':', 1)
    computed_hash = hashlib.sha256((plain_password + salt).encode()).hexdigest()
    return secrets.compare_digest(stored_hash, computed_hash)

def get_password_hash(password: str) -> str:
    """获取密码哈希值
    
    使用 SHA-256 + salt 哈希，而不是 bcrypt
    """
    salt = secrets.token_hex(16)  # 生成 32 字符长度的随机盐
    password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return f"{salt}:{password_hash}"

def get_permission_type(method: str) -> str:
    """
    根据HTTP方法判断权限类型
    GET, HEAD, OPTIONS 为读权限
    其他方法为写权限
    """
    if method.upper() in ["GET", "HEAD", "OPTIONS"]:
        return "read"
    return "write"

def check_permission(
    db: Session,
    user_id: int,
    resource_path: str,
    method: str
) -> bool:
    """
    检查用户是否有权限访问指定资源
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        resource_path: 资源路径
        method: HTTP方法
    
    Returns:
        bool: 是否有权限
    """
    # 导入放在函数内部以避免循环导入
    from app.models.user import User
    
    # 首先检查用户是否是管理员
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.is_admin:
        return True
    
    # 获取所需权限类型
    required_permission = get_permission_type(method)
    
    # 检查用户是否具有该资源路径的权限
    if not user or not user.role_ids or not isinstance(user.role_ids, list):
        return False
    
    # 导入 Role 模型
    from app.models.rbac import Role
    
    # 获取用户的所有角色
    roles = db.query(Role).filter(Role.id.in_(user.role_ids)).all()
    
    # 构造资源名 - 使用路径的最后一部分作为资源名
    resource_name = resource_path.split('/')[-1]
    
    # 检查每个角色的权限
    for role in roles:
        if not role.permissions:
            continue
        
        # 解析角色权限（现在是JSON格式）
        permissions = role.permissions
        
        # 检查特定权限
        for perm in permissions:
            # 检查是否有对应的权限
            if perm.get("resource") == resource_name and perm.get("permission") == required_permission:
                return True
            
            # 检查是否有写权限对应的资源（写权限包含读权限）
            if perm.get("resource") == resource_name and perm.get("permission") == "write" and required_permission == "read":
                return True
            
            # 检查是否有通配符权限
            if perm.get("resource") == "*" or (perm.get("resource") == resource_name and perm.get("permission") == "*"):
                return True
    
    return False

async def check_request_permission(request: Request, db: Session, user_id: int) -> bool:
    """
    检查请求的权限
    
    Args:
        request: FastAPI请求对象
        db: 数据库会话
        user_id: 用户ID
    
    Returns:
        bool: 是否有权限
    """
    # 获取请求路径和方法
    path = request.url.path
    method = request.method
    
    # 检查权限
    if not check_permission(db, user_id, path, method):
        raise HTTPException(
            status_code=403,
            detail="Permission denied"
        )
    return True

def get_current_user_id():
    # 这里需要实现获取当前用户ID的逻辑
    # 可以通过JWT token或其他方式获取
    pass 