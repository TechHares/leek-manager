from sqlalchemy import Column, String, DateTime, JSON, Integer, BigInteger

from app.models.base import Base, BaseModel

class Signal(Base):
    __tablename__ = "signals"

    id = Column(BigInteger, primary_key=True, index=True)
    project_id = Column(BigInteger, index=True)
    data_source_instance_id =  Column(JSON)
    data_source_class_name = Column(String(200), nullable=False)
    strategy_id =  Column(BigInteger, index=True)
    strategy_instance_id =  Column(String(200), nullable=False)
    strategy_class_name = Column(String(200), nullable=False)
    signal_time = Column(DateTime, index=True, nullable=False)
    assets = Column(JSON)  # 存储 Asset 列表
    config = Column(JSON)  # 存储 StrategyPositionConfig
    extra = Column(JSON)   # 存储其他扩展信息 