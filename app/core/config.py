from pydantic_settings import BaseSettings
from typing import Optional
import os
import secrets
import string
from pathlib import Path

def get_version_from_pyproject():
    """从pyproject.toml文件中读取版本信息"""
    try:
        # 尝试使用Python 3.11+内置的tomllib
        import tomllib
    except ImportError:
        return "1.0.0"
    
    try:
        # 获取项目根目录的pyproject.toml文件路径
        current_dir = Path(__file__).parent
        project_root = current_dir.parent.parent  # app/core/ -> app/ -> leek-manager/
        pyproject_path = project_root / "pyproject.toml"
        
        if pyproject_path.exists():
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
                # 从poetry配置中获取版本
                version = data.get("tool", {}).get("poetry", {}).get("version", "1.0.0")
                return version
        else:
            return "1.0.0"
    except Exception:
        # 如果读取失败，返回默认版本
        return "1.0.0"

class Settings(BaseSettings):
    VERSION: str = get_version_from_pyproject()
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
