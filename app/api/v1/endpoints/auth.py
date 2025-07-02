from datetime import datetime, timedelta, UTC
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from app.core.config import settings
from app.db.session import get_db
from sqlalchemy.orm import Session
from app.models.user import User
from app.api.deps import get_current_user
from app.schemas.token import Token, TokenData, LoginRequest
from app.schemas.user import UserCreate, UserUpdate

if "json_encoders" not in BaseModel.model_config:
    BaseModel.model_config["json_encoders"] = {}
BaseModel.model_config["json_encoders"][Decimal] = lambda v: str(v)

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/tokens")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt

@router.post("/tokens", response_model=Token)
async def login_for_access_token(login_data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == login_data.username).first()
    if not user or not user.verify_password(login_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username})
    return Token(
        access_token=access_token,
        token_type="bearer"
    )

# @router.post("/users", response_model=UserCreate)
# def create_user(user: UserCreate, db: Session = Depends(get_db)):
#     db_user = db.query(User).filter(User.username == user.username).first()
#     if db_user:
#         raise HTTPException(status_code=400, detail="Username already registered")
#     return User.create(db, user)

@router.get("/users/me", response_model=UserUpdate)
def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

# @router.put("/users/me", response_model=UserUpdate)
# def update_user_me(user: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
#     return current_user.update(db, user) 