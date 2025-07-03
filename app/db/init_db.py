from sqlalchemy.orm import Session
from app.models.user import User
from app.core.config_manager import config_manager
from app.core.security import get_password_hash
__init_lock = False
def init_db(db: Session) -> None:
    """初始化数据库，创建管理员账号"""
    # 检查是否已配置管理员账号
    global __init_lock
    if __init_lock:
        return
    __init_lock = True
    admin_config = config_manager.config.admin
    if not admin_config:
        return

    # 检查管理员账号是否已存在
    admin = db.query(User).filter(User.username == admin_config.username).first()
    if admin:
        return

    # 创建管理员账号
    admin = User(
        username=admin_config.username,
        email=admin_config.email,
        hashed_password=get_password_hash(admin_config.password),
        is_admin=True,
        role_ids=[]  # 设置空的角色ID列表
    )
    db.add(admin)
    db.commit() 