from typing import List, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum

class FieldType(str, Enum):
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    DATETIME = "datetime"
    RADIO = "radio"
    SELECT = "select"
    ARRAY = "array"

class ChoiceType(str, Enum):
    STR = "str"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    DATETIME = "datetime"

class ParameterField(BaseModel):
    """
    用于表示参数的类。
    """
    name: str  # 字段名称
    label: Optional[str] = None  # 显示名称，默认为name
    description: str = ""  # 字段描述
    type: FieldType = FieldType.STRING  # 入参类型
    default: Any = None  # 默认值
    length: Optional[int] = None  # 字段长度，仅适用于str
    min: Optional[float] = None  # 最小值，仅适用于 int、float和datetime
    max: Optional[float] = None  # 最大值，仅适用于 int、float和datetime
    required: bool = False  # 是否必传
    choices: List[Any] = Field(default_factory=list)  # 可选值列表，仅适用于radio和select
    choice_type: Optional[ChoiceType] = None  # 可选值类型，仅适用于radio和select

class TemplateResponse(BaseModel):
    """
    模板响应体
    """
    cls: str  # 类名
    name: str  # 显示名称
    tag: str  # 标签
    desc: str  # 描述
    parameters: List[ParameterField] = Field(default_factory=list)  # 参数列表 