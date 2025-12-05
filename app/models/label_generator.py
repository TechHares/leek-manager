from sqlalchemy import Column, String, JSON, DateTime
from app.models.base import ComponentModel
from datetime import datetime

class LabelGenerator(ComponentModel):
    __tablename__ = "label_generators"
