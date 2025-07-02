from sqlalchemy import Column, String, JSON, Integer, Boolean, DateTime
from app.models.base import ComponentModel
from leek_core.base import load_class_from_str
from leek_core.models import LeekComponentConfig
from leek_core.data import DataSource
from typing import Dict, Any

class DataSource(ComponentModel):
    __tablename__ = "datasources"
    # 继承ComponentModel，包含name, description, class_name, params, project_id, is_enabled, is_deleted, created_at, updated_at
    # 可根据需要扩展字段 

    def to_config(self) -> LeekComponentConfig[DataSource, Dict[str, Any]]:
        return LeekComponentConfig(
            instance_id=self.id,
            name=self.name,
            cls=load_class_from_str(self.class_name),
            config=self.params
        )