from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from app.core.config_manager import config_manager
from app.models.base import Base
import importlib
import pkgutil
import os

# 动态导入所有模型以确保它们被注册到 Base.metadata
def import_all_models():
    """动态导入 app.models 模块下的所有模型"""
    models_dir = os.path.join(os.path.dirname(__file__), '..', 'app', 'models')
    
    # 导入 app.models 包
    import app.models
    
    # 遍历 app.models 包下的所有模块
    for module_info in pkgutil.iter_modules(app.models.__path__):
        module_name = module_info.name
        
        # 跳过 __pycache__ 等特殊模块
        if module_name.startswith('_'):
            continue
            
        try:
            # 动态导入模块
            module = importlib.import_module(f'app.models.{module_name}')
            
            # 查找模块中的模型类（继承自 Base 的类）
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (hasattr(attr, '__bases__') and 
                    Base in attr.__bases__ and 
                    attr != Base and 
                    hasattr(attr, '__tablename__')):
                    # 这是一个模型类，导入它
                    globals()[attr_name] = attr
                    
        except ImportError as e:
            print(f"警告: 无法导入模块 app.models.{module_name}: {e}")
        except Exception as e:
            print(f"警告: 处理模块 app.models.{module_name} 时出错: {e}")

# 执行动态导入
import_all_models()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

def get_url():
    db_config = config_manager.get_config()["business_db"]
    if db_config["type"] == "sqlite":
        return f"sqlite:///{db_config['path']}"
    return db_config.get_connection_string()

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table="alembic_version",  # 指定版本表名
        version_table_schema=None,  # 使用默认 schema
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    connect_args = {}
    if configuration["sqlalchemy.url"].startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table="alembic_version",  # 指定版本表名
            version_table_schema=None,  # 使用默认 schema
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
