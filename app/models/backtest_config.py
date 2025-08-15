from sqlalchemy import Column, String, JSON, Integer
from app.models.base import BaseModel


class BacktestConfig(BaseModel):
    __tablename__ = "backtest_config"

    project_id = Column(Integer, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    remark = Column(String(500), nullable=True)
    type = Column(String(32), nullable=False)  # cost | data
    class_name = Column(String(300), nullable=False)
    params = Column(JSON, nullable=True)
    extra = Column(JSON, nullable=True)


