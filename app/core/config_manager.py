import os
import configparser
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel
import json

class AdminConfig(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class DatabaseConfig(BaseModel):
    type: str  # 'sqlite', 'mysql', or 'clickhouse'
    host: Optional[str] = None
    port: Optional[int] = None
    database: str = "default"  # 默认数据库名
    username: Optional[str] = None
    password: Optional[str] = None  # 密码是可选的
    path: Optional[str] = None  # For SQLite

    def get_connection_string(self) -> str:
        """Get database connection string."""
        if self.type == "sqlite":
            return f"sqlite:///{self.path}"
        elif self.type in ["mysql", "clickhouse"]:
            # 如果密码为空，则不包含密码部分
            auth = f"{self.username}" if not self.password else f"{self.username}:{self.password}"
            return f"{self.type}://{auth}@{self.host}:{self.port}/{self.database}"
        return None

class Config(BaseModel):
    is_configured: bool = False
    business_db: Optional[DatabaseConfig] = None
    data_db: Optional[DatabaseConfig] = None
    admin: Optional[AdminConfig] = None  # 添加管理员配置

class ConfigManager:
    def __init__(self):
        # 根据操作系统选择配置目录
        if os.name == 'nt':  # Windows
            self.config_dir = Path(os.environ.get('APPDATA', '')) / 'leek-manager'
        else:  # Linux/Mac
            self.config_dir = Path.home() / '.leek-manager'
            
        self.config_file = self.config_dir / 'config.json'
        self._ensure_config_dir()
        self._load_config()

    def _ensure_config_dir(self):
        """确保配置目录存在"""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self):
        """加载配置文件"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                config_data = json.load(f)
                self.config = Config(**config_data)
        else:
            self.config = Config()
            self._save_config()

    def _save_config(self):
        """保存配置到文件"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config.model_dump(), f, indent=2)

    def get_config(self) -> Dict[str, Any]:
        """获取当前配置"""
        return self.config.model_dump()

    def update_config(self, config_data: Dict[str, Any]):
        """更新配置"""
        self.config = Config(**config_data)
        self._save_config()

    def reset_config(self):
        """重置配置"""
        self.config = Config()
        self._save_config()

    def get_connection_string(self, db_type: str) -> Optional[str]:
        """Get database connection string for the specified database type."""
        config = self._get_db_config(db_type)
        if not config:
            return None

        if config["type"] == "sqlite":
            return f"sqlite:///{config['path']}"
        elif config["type"] in ["mysql", "clickhouse"]:
            # 如果密码为空，则不包含密码部分
            auth = f"{config['username']}" if not config.get('password') else f"{config['username']}:{config['password']}"
            return f"{config['type']}://{auth}@{config['host']}:{config['port']}/{config['database']}"
        
        return None

    def _get_db_config(self, section: str) -> Optional[Dict[str, Any]]:
        """Get database configuration for a specific section."""
        db_config = getattr(self.config, section, None)
        if not db_config:
            return None

        config = {"type": db_config.type}
        
        if db_config.type == "sqlite":
            config["path"] = db_config.path
        else:
            config.update({
                "host": db_config.host,
                "port": db_config.port,
                "database": db_config.database,
                "username": db_config.username,
                "password": db_config.password
            })
        
        return config

# 创建全局配置管理器实例
config_manager = ConfigManager() 