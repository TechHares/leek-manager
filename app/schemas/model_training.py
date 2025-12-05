from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class ModelTrainingCreate(BaseModel):
    """创建模型训练任务的请求"""
    name: str = Field(..., description="训练任务名称")
    description: Optional[str] = Field(None, description="备注")
    
    # 数据配置
    data_config_id: int = Field(..., description="数据配置ID")
    symbols: List[str] = Field(..., description="交易标的列表")
    timeframes: List[str] = Field(..., description="时间框架列表")
    start_time: str = Field(..., description="开始时间")
    end_time: str = Field(..., description="结束时间")
    
    # 训练配置
    factor_ids: List[int] = Field(..., description="要使用的因子ID列表")
    label_generator_id: int = Field(..., description="标签生成器ID")
    trainer_id: int = Field(..., description="训练器ID")
    train_split_ratio: float = Field(0.8, ge=0.01, le=0.99, description="训练数据比例")
    base_model_id: Optional[int] = Field(None, description="基础模型ID（用于继续训练）")
    enable_symbol_timeframe_encoding: bool = Field(True, description="是否启用 symbol 和 timeframe 编码")


class ModelTrainingTaskOut(BaseModel):
    """模型训练任务输出"""
    id: int
    name: str
    description: Optional[str] = None
    status: str
    progress: float
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    
    # 配置
    config: Optional[Dict[str, Any]] = None
    data_config_id: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    symbols: Optional[List[str]] = None
    timeframes: Optional[List[str]] = None
    factor_ids: Optional[List[int]] = None
    label_generator_id: Optional[int] = None
    trainer_id: Optional[int] = None
    train_split_ratio: Optional[float] = None
    
    # 结果
    metrics: Optional[Dict[str, Any]] = None
    model_id: Optional[int] = None

    class Config:
        from_attributes = True


class ModelTrainingTaskBriefOut(BaseModel):
    """模型训练任务简要输出（用于列表）"""
    id: int
    name: str
    description: Optional[str] = None
    status: str
    progress: float
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    
    # 关键信息
    data_config_id: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    symbols: Optional[List[str]] = None
    timeframes: Optional[List[str]] = None
    factor_ids: Optional[List[int]] = None
    label_generator_id: Optional[int] = None
    trainer_id: Optional[int] = None
    train_split_ratio: Optional[float] = None
    model_id: Optional[int] = None
    
    # 模型评分（分类任务：accuracy，回归任务：R²）
    score: Optional[float] = None
    # 任务类型（用于前端格式化显示）
    task_type: Optional[str] = None

    class Config:
        from_attributes = True

