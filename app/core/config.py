from pydantic_settings import BaseSettings
from typing import Optional
import os
import secrets
import string

class Settings(BaseSettings):
    VERSION: str = "1.0.0"
    SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    
    def __init__(self, **kwargs):
        # 检查SECRET_KEY是否存在，不存在则生成一个
        secret_key = os.getenv("LEEK_SECRET_KEY")
        if not secret_key:
            # 生成一个32位的随机字符串作为SECRET_KEY
            secret_key = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
            # 设置环境变量
            os.environ["LEEK_SECRET_KEY"] = secret_key
        
        # 更新kwargs中的值
        kwargs["SECRET_KEY"] = secret_key
        kwargs["ACCESS_TOKEN_EXPIRE_MINUTES"] = int(os.getenv("LEEK_ACCESS_TOKEN_EXPIRE_MINUTES", 1440))
        
        super().__init__(**kwargs)

settings = Settings() 
