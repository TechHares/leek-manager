from sqlalchemy import Column, String, JSON, DateTime
from app.models.base import ComponentModel
from datetime import datetime, UTC

class Strategy(ComponentModel):
    __tablename__ = "strategies"
    data_source_config = Column(JSON, nullable=True)
    position_config = Column(JSON, nullable=True)
    enter_strategy_class_name = Column(String(200), nullable=False)
    enter_strategy_config = Column(JSON, nullable=True)
    exit_strategy_class_name = Column(String(200), nullable=False)
    exit_strategy_config = Column(JSON, nullable=True)
    risk_policies = Column(JSON, nullable=True)
    info_fabricator_configs = Column(JSON, nullable=True)
    data = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))