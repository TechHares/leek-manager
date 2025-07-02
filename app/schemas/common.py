from enum import Enum
from typing import Any, List, Generic, TypeVar
from pydantic import BaseModel

T = TypeVar('T')

class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    size: int
    items: List[T]