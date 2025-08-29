from sqlalchemy import Column, String, JSON
from app.models.base import ComponentModel


class RiskPolicy(ComponentModel):
    __tablename__ = "risk_policies"

    # 适用范围: all / strategy_templates / strategy_instances / mixed
    scope = Column(String(32), nullable=False, default="all")
    # 当 scope 包含 strategy_templates 时，保存模板 cls 列表
    strategy_template_ids = Column(JSON, nullable=True)
    # 当 scope 包含 strategy_instances 时，保存实例 id 列表
    strategy_instance_ids = Column(JSON, nullable=True)


