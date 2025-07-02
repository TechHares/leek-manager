from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(ProjectBase):
    name: Optional[str] = None

class ProjectInDBBase(ProjectBase):
    id: int
    created_at: datetime
    updated_at: datetime
    created_by: int
    is_deleted: bool

    class Config:
        from_attributes = True

class Project(ProjectInDBBase):
    pass

class ProjectInDB(ProjectInDBBase):
    pass 