from sqlalchemy import Column, String, JSON, DateTime, BigInteger, Boolean, Integer, Float
from app.models.base import BaseModel
from datetime import datetime

class Model(BaseModel):
    __tablename__ = "models"
    
    name = Column(String(200), nullable=False)
    description = Column(String(500), nullable=True)
    version = Column(String(50), nullable=False)
    file_path = Column(String(500), nullable=False, comment="Full path to model file")
    file_size = Column(BigInteger, nullable=True, comment="File size in bytes")
    project_id = Column(BigInteger, nullable=False, index=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    feature_config = Column(JSON, nullable=True, comment="Feature configuration used for training")

