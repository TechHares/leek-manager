from fastapi import Request, HTTPException, status
from jose import jwt, JWTError
from app.core.config import settings
from app.models.user import User
from app.models.rbac import Role
from app.service.cache import get_user_by_username, get_role_by_id
from sqlalchemy.orm import Session
from app.core.config_manager import config_manager
import re
from leek_core.utils import get_logger, log_function
from fastapi.responses import JSONResponse
logger = get_logger(__name__)

# 不需要权限检查的路径
EXEMPT_PATHS = [
    "/api/v1/auth/tokens",
    "/api/v1/system/configurations",
]

async def system_permission_middleware(request: Request, call_next):
    
    path = request.url.path
    if not path.startswith("/api/"): # 非API路径，跳过权限检查
        return await call_next(request)
    # 检查系统是否已配置
    config = config_manager.get_config()
    if not config["is_configured"] and not path.startswith("/api/v1/system/configurations"):
        return JSONResponse(
            status_code=status.HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS,
            content={"detail": "System not configured"}
        )
    # 跳过不需要权限检查的路径
    if any(path.startswith(exempt_path) for exempt_path in EXEMPT_PATHS):
        return await call_next(request)
    
    # 验证token
    authorization: str = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "未认证"})
    
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        username: str = payload.get("sub")
        if not username:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "无效token"})
        
        # 获取用户信息
        user = get_user_by_username(username)
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "用户不存在"})
        return await call_next(request)
        
        # # 系统级别资源（/api/v1/system/）需要管理员权限
        # if path.startswith("/api/v1/system/") and not user.is_admin:
        #     return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": "系统级资源需要管理员权限"})
        
        # # 管理员拥有所有接口权限
        # if user.is_admin:
        #     response = await call_next(request)
        #     return response
        
        # # 非管理员需要权限检查
        # if path.startswith("/api/v1/"):
        #     # 获取API版本和资源路径
        #     # 例如，"/api/v1/users/123" 转化为 "/api/v1/users"
        #     api_path = re.sub(r'/\d+', '/{id}', path)
            
        #     # 判断权限类型
        #     method = request.method
        #     required_permission = "read" if method.upper() in ["GET", "HEAD", "OPTIONS"] else "write"
            
        #     # 构造资源名 - 使用路径的最后一部分作为资源名
        #     resource_name = api_path.split('/')[-1]
            
        #     # 获取用户角色
        #     has_permission = False
            
        #     # 检查用户角色列表
        #     if user.role_ids and isinstance(user.role_ids, list) and len(user.role_ids) > 0:
        #         # 检查每个角色的权限
        #         for role_id in user.role_ids:
        #             role = get_role_by_id(role_id)
        #             if not role.permissions:
        #                 continue
                    
        #             # 解析角色权限（现在是JSON格式）
        #             permissions = role.permissions
                    
        #             # 检查特定权限
        #             for perm in permissions:
        #                 # 检查是否有对应的权限
        #                 if perm.get("resource") == resource_name and perm.get("permission") == required_permission:
        #                     has_permission = True
        #                     break
                        
        #                 # 检查是否有写权限对应的资源（写权限包含读权限）
        #                 if perm.get("resource") == resource_name and perm.get("permission") == "write" and required_permission == "read":
        #                     has_permission = True
        #                     break
                        
        #                 # 检查是否有通配符权限
        #                 if perm.get("resource") == "*" or (perm.get("resource") == resource_name and perm.get("permission") == "*"):
        #                     has_permission = True
        #                     break
                    
        #             if has_permission:
        #                 break
            
        #     if not has_permission:
        #         return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": "权限不足"})
    
    except JWTError as e:
        logger.warning(f"JWTError: {e}", exc_info=True)
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "无效token"})
    
    response = await call_next(request)
    return response 