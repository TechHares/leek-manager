from sqlalchemy import Column, Integer, String, JSON, DateTime, Enum, Float, Boolean
from app.models.base import ComponentModel
import enum
from datetime import datetime
from leek_core.base import  load_class_from_str
from leek_core.models import  LeekComponentConfig 

class Executor(ComponentModel):
    __tablename__ = "executors"

