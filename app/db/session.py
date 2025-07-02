from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.core.config_manager import config_manager
from app.models.base import Base
from app.models.user import User  # 导入所有模型以确保它们被注册到 Base.metadata
from app.db.init_db import init_db
import subprocess
import os
from pathlib import Path
import threading

_engine = None
_SessionLocal = None
_migration_lock = threading.Lock()
_migration_checked = False

def get_engine():
    global _engine
    if _engine is None:
        config = config_manager.get_config()
        if not config["is_configured"]:
            return None
        
        # 使用业务数据库配置
        db_config = config["business_db"]
        if not db_config:
            return None
            
        if db_config["type"] == "sqlite":
            database_url = f"sqlite:///{db_config['path']}"
            connect_args = {"check_same_thread": False}
        else:
            # 使用新的连接字符串生成方法
            database_url = db_config.get_connection_string()
            connect_args = {}
            
        _engine = create_engine(database_url, connect_args=connect_args)
    return _engine

def get_session_local():
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        if engine is None:
            return None
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _SessionLocal

def reset_connection():
    global _engine, _SessionLocal, _migration_checked
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _migration_checked = False

def get_connection_string():
    config = get_database_config()
    if config.password:
        return f"clickhouse://{config.username}:{config.password}@{config.host}:{config.port}/{config.database}"
    return f"clickhouse://{config.username}@{config.host}:{config.port}/{config.database}"

def check_and_run_migration():
    """检查并运行alembic迁移（只执行一次）"""
    global _migration_checked
    
    with _migration_lock:
        if _migration_checked:
            return True
        
        try:
            # 获取后端目录路径
            backend_dir = Path(__file__).parent.parent.parent
            alembic_ini = backend_dir / "alembic.ini"
            
            if not alembic_ini.exists():
                print("警告: alembic.ini不存在，跳过迁移")
                _migration_checked = True
                return False
            
            # 检查是否有待应用的迁移
            result = subprocess.run(
                ["alembic", "current"],
                cwd=backend_dir,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print(f"检查迁移状态失败: {result.stderr}")
                _migration_checked = True
                return False
            
            # 检查是否有待应用的迁移
            upgrade_result = subprocess.run(
                ["alembic", "upgrade", "head"],
                cwd=backend_dir,
                capture_output=True,
                text=True
            )
            
            if upgrade_result.returncode == 0:
                print("数据库迁移执行成功")
            else:
                print(f"数据库迁移执行失败: {upgrade_result.stderr}")
            
            _migration_checked = True
            return upgrade_result.returncode == 0
                
        except Exception as e:
            print(f"执行alembic迁移时出错: {e}")
            _migration_checked = True
            return False

def get_db():
    session_local = get_session_local()
    if session_local is None:
        return None
        
    db = session_local()
    try:
        # 检查并运行alembic迁移（只执行一次）
        check_and_run_migration()
        # 初始化数据库，创建管理员账号
        init_db(db)
        yield db
    finally:
        db.close() 