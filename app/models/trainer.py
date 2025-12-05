from sqlalchemy import Column, String, JSON, DateTime
from app.models.base import ComponentModel
from datetime import datetime

class Trainer(ComponentModel):
    __tablename__ = "trainers"
    
    created_at = Column(DateTime, default=lambda: datetime.now())
    updated_at = Column(DateTime, default=lambda: datetime.now(), onupdate=lambda: datetime.now())

