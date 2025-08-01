from sqlalchemy import Column, Integer, String, Boolean, JSON, BigInteger
from sqlalchemy.orm import relationship

from app.models.base import BaseModel

class Project(BaseModel):
    __tablename__ = "projects"

    name = Column(String(100), nullable=False, index=True)
    description = Column(String(500))
    created_by = Column(BigInteger, nullable=False)
    is_deleted = Column(Boolean, default=False)
    engine_info = Column(JSON, nullable=True)

    # Relationships
    creator = relationship("User", foreign_keys=[created_by], primaryjoin="Project.created_by == User.id") 