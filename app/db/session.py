from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config_manager import config_manager
from app.db.init_db import init_db
import subprocess
import os
from pathlib import Path
import threading

def get_engine():
    config = config_manager.get_config()
    if not config["is_configured"]:
        return None
    
    # 使用业务数据库配置
    db_config = config["business_db"]
    if not db_config:
        return None
        
    database_url = config_manager.get_connection_string("business_db")
    if db_config["type"] == "sqlite":
        connect_args = {"check_same_thread": False}
        _engine = create_engine(database_url, connect_args=connect_args)
    else:
        _engine = create_engine(
            database_url,
            pool_size=20,
            max_overflow=25,
            pool_timeout=30,
            pool_recycle=1800,
        )
    return _engine

def get_session_local():
    engine = get_engine()
    if engine is None:
        return None
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

def check_and_run_migration():
    """检查并运行alembic迁移（只执行一次）"""
    try:
        # 获取后端目录路径
        backend_dir = Path(__file__).parent.parent.parent
        alembic_ini = backend_dir / "alembic.ini"

        if not alembic_ini.exists():
            print("警告: alembic.ini不存在，跳过迁移")
            return False

        # 获取当前数据库版本
        current_result = subprocess.run(
            ["alembic", "current"],
            cwd=backend_dir,
            capture_output=True,
            text=True
        )
        if current_result.returncode != 0:
            print(f"检查迁移状态失败: {current_result.stderr}")
            return False

        # 获取最新的 head 版本
        heads_result = subprocess.run(
            ["alembic", "heads"],
            cwd=backend_dir,
            capture_output=True,
            text=True
        )
        if heads_result.returncode != 0:
            print(f"获取 heads 失败: {heads_result.stderr}")
            return False

        # 如果 current 和 heads 一致，说明无需迁移
        if current_result.stdout.strip() == heads_result.stdout.strip():
            return True

        # 需要迁移才执行
        upgrade_result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=backend_dir,
            capture_output=True,
            text=True
        )
        if upgrade_result.returncode == 0:
            ...
        else:
            print(f"数据库迁移执行失败: {upgrade_result.stderr}")

        return upgrade_result.returncode == 0
    except Exception as e:
        print(f"执行alembic迁移时出错: {e}")
        return False

_session_local = None
_thread_lock = threading.Lock()
def get_db() -> Optional[Session]:
    global _session_local
    if _session_local is None:
        with _thread_lock:
            if _session_local is None:
                _session_local = get_session_local()
                if _session_local is None:
                    return None
                _db = _session_local()
                check_and_run_migration()
                init_db(_db)
                _db.close()
    return _session_local()

def reset_connection():
    global _session_local
    _session_local = None

@contextmanager
def db_connect() -> Generator[Optional[Session], None, None]:
    db = get_db()
    try:
        yield db
    finally:
        db.close()