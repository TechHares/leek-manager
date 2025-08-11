from typing import Generator, Optional
from fastapi import Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from app.db.session import get_db
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from app.core.config import settings
from app.models.user import User
from app.schemas.token import TokenData
from leek_core.utils import get_logger
from app.service.cache import get_user_by_username
logger = get_logger(__name__)

def get_db_session() -> Generator[Optional[Session], None, None]:
    """
    获取数据库会话的依赖项。
    如果数据库未配置，返回 None。
    """
    db = get_db()
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured"
        )
    try:
        # 供路由处理逻辑使用
        yield db
        if db.in_transaction():
            db.commit()
    except Exception:
        if db.in_transaction():
            db.rollback()
        raise
    finally:
        db.close()

def get_project_id(project_id: Optional[int] = Header(None, alias="project-id")) -> Optional[int]:
    """
    从请求头中获取项目ID
    """
    return int(project_id) if project_id else None

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        username: str = payload.get("sub")
        if username is None:
            logger.error(f"username is None", payload)
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError as e:
        logger.error(f"JWTError: {e}")
        raise credentials_exception
    
    user = get_user_by_username(token_data.username)
    if user is None:
        logger.error(f"user is None", token_data.username)
        raise credentials_exception
    return user