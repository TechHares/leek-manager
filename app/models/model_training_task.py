from sqlalchemy import Column, String, JSON, DateTime, Integer, Float, Boolean
from datetime import datetime
from app.models.base import BaseModel

class ModelTrainingTask(BaseModel):
    __tablename__ = "model_training_tasks"
    
    # 基本信息
    project_id = Column(Integer, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(String(500), nullable=True)
    
    # 配置与状态
    config = Column(JSON, nullable=True, comment="Request configuration snapshot")
    status = Column(String(32), nullable=False, default="pending", comment="pending | running | completed | failed")
    progress = Column(Float, nullable=False, default=0.0)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error = Column(String(2000), nullable=True)
    
    # 数据配置
    data_config_id = Column(Integer, nullable=True)
    start_time = Column(String(32), nullable=True)
    end_time = Column(String(32), nullable=True)
    symbols = Column(JSON, nullable=True)
    timeframes = Column(JSON, nullable=True)
    
    # 训练配置
    factor_ids = Column(JSON, nullable=True, comment="List of factor IDs")
    label_generator_id = Column(Integer, nullable=True, comment="FK to label_generators")
    trainer_id = Column(Integer, nullable=True, comment="FK to trainers")
    train_split_ratio = Column(Float, nullable=False, default=0.8, comment="Training data ratio (0.01-0.99)")
    
    # 结果
    metrics = Column(JSON, nullable=True, comment="Training and validation metrics")
    model_id = Column(Integer, nullable=True, comment="FK to models (created after successful training)")
    
    created_at = Column(DateTime, default=lambda: datetime.now())
    updated_at = Column(DateTime, default=lambda: datetime.now(), onupdate=lambda: datetime.now())

