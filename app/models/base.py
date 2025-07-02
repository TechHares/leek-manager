from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, DateTime, String, JSON, Boolean
from datetime import datetime, UTC
from leek_core.base import  load_class_from_str
from leek_core.models import  LeekComponentConfig 

Base = declarative_base()

class BaseModel(Base):
    __abstract__ = True
    
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)) 
    
class ComponentModel(BaseModel):
    __abstract__ = True
    
    name = Column(String(50), nullable=False)
    description = Column(String(500), nullable=True)
    class_name = Column(String(200), nullable=False)
    params = Column(JSON, nullable=True)
    project_id = Column(Integer, nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    def to_config(self) -> LeekComponentConfig:
        return LeekComponentConfig(
            instance_id=str(self.id),
            name=self.name,
            cls=load_class_from_str(self.class_name),
            config=self.params
        )