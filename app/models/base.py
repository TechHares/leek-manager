from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, DateTime, String, Boolean, BigInteger, JSON, Integer
from datetime import datetime

Base = declarative_base()

class BaseModel(Base):
    __abstract__ = True
    
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, index=True, autoincrement=True)
    created_at = Column(DateTime, index=True, default=lambda: datetime.now())
    updated_at = Column(DateTime, default=lambda: datetime.now(), onupdate=lambda: datetime.now()) 
    
class ComponentModel(BaseModel):
    __abstract__ = True
    
    name = Column(String(50), nullable=False)
    description = Column(String(500), nullable=True)
    class_name = Column(String(200), nullable=False)
    params = Column(JSON, nullable=True)
    project_id = Column(BigInteger, nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    def dumps_map(self) -> dict:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}