from sqlalchemy import Column, String, JSON, DateTime, Integer
from app.models.base import ComponentModel
from datetime import datetime

class Factor(ComponentModel):
    __tablename__ = "factors"
    
    # 因子相关字段
    factor_count = Column(Integer, nullable=False, default=1, comment="因子数量")
    output_names = Column(JSON, nullable=True, comment="输出名称列表")
    categories = Column(JSON, nullable=True, comment="因子分类列表")
    
    created_at = Column(DateTime, default=lambda: datetime.now())
    updated_at = Column(DateTime, default=lambda: datetime.now(), onupdate=lambda: datetime.now())

