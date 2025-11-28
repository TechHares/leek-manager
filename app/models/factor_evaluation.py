from sqlalchemy import Column, String, JSON, DateTime, Integer, Float, Boolean
from datetime import datetime
from app.models.base import BaseModel


class FactorEvaluationTask(BaseModel):
    __tablename__ = "factor_evaluation_tasks"

    # 基本信息
    project_id = Column(Integer, nullable=False, index=True)
    name = Column(String(200), nullable=False)

    # 配置与状态
    config = Column(JSON, nullable=True)  # 请求配置快照
    status = Column(String(32), nullable=False, default="pending")  # pending | running | completed | failed
    progress = Column(Float, nullable=False, default=0.0)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error = Column(String(2000), nullable=True)

    # 关键信息（冗余，便于列表检索/展示）
    data_config_id = Column(Integer, nullable=True)
    start = Column(String(32), nullable=True)
    end = Column(String(32), nullable=True)
    symbols = Column(JSON, nullable=True)
    timeframes = Column(JSON, nullable=True)
    factor_ids = Column(JSON, nullable=True)  # 评价的因子ID列表

    # 结果
    summary = Column(JSON, nullable=True)  # 聚合摘要
    metrics = Column(JSON, nullable=True)  # 评价指标明细
    charts = Column(JSON, nullable=True)  # 图表数据

    # 汇总结论（冗余字段，便于快速排序/筛选/展示）
    ic_mean = Column(Float, nullable=True)  # IC均值
    ir = Column(Float, nullable=True)  # IR (Information Ratio)
    ic_win_rate = Column(Float, nullable=True)  # IC胜率
    factor_count = Column(Integer, nullable=True)  # 评价的因子数量

