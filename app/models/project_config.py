from sqlalchemy import Column, Integer, String, JSON, Boolean, BigInteger
from app.models.base import BaseModel

class ProjectConfig(BaseModel):
    __tablename__ = "project_configs"
    project_id = Column(BigInteger, nullable=False, unique=True, index=True)
    log_alarm = Column(Boolean, default=False)
    log_level = Column(String(20), default="INFO")
    log_format = Column(String(10), default="json")  # json/text
    alert_methods = Column(String(200), default="")  # 逗号分隔
    alert_config = Column(JSON, default=dict)        # JSON 类型
    mount_dirs = Column(JSON, default=list)          # 挂载代码目录，JSON数组
    position_setting = Column(JSON, default=dict)
    position_data = Column(JSON, default=dict)