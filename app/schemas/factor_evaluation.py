from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class FactorEvaluationMetrics(BaseModel):
    """因子评价指标"""
    # IC相关指标
    ic_mean: float = Field(0.0, description="IC均值")
    ic_std: float = Field(0.0, description="IC标准差")
    ic_win_rate: float = Field(0.0, description="IC胜率（IC>0的比例）")
    ic_skewness: float = Field(0.0, description="IC偏度")
    ic_series: List[float] = Field(default_factory=list, description="IC时序序列")
    
    # IR指标
    ir: float = Field(0.0, description="IR (Information Ratio) = IC均值 / IC标准差")
    
    # 收益分析
    quantile_returns: Dict[str, float] = Field(default_factory=dict, description="分位数收益（key为分位数名称，value为平均收益）")
    long_short_return: float = Field(0.0, description="多空收益（最高分位数 - 最低分位数）")
    
    # AlphaEval 新增维度
    temporal_stability: float = Field(0.0, description="时间稳定性（RRE）[0,1]")
    estimated_turnover: float = Field(0.0, description="预估年化换手率")
    
    robustness_gaussian: float = Field(1.0, description="高斯噪声鲁棒性[0,1]")
    robustness_t_dist: float = Field(1.0, description="t分布鲁棒性[0,1]")
    robustness_min: float = Field(1.0, description="最小鲁棒性得分[0,1]")
    robustness_enabled: bool = Field(False, description="是否启用鲁棒性评估")
    
    # 综合评分
    alpha_eval_score: float = Field(0.0, description="AlphaEval综合得分[0,1]")
    
    # 因子名称
    factor_name: str = Field(..., description="因子名称")
    factor_id: int = Field(..., description="因子ID")


class FactorEvaluationCreate(BaseModel):
    """创建因子评价任务的请求"""
    name: str = Field(..., description="评价任务名称")
    remark: Optional[str] = Field(None, description="备注")
    
    # 数据配置
    data_config_id: int = Field(..., description="数据配置ID")
    symbols: List[str] = Field(..., description="交易标的列表")
    timeframes: List[str] = Field(..., description="时间框架列表")
    start_time: str = Field(..., description="开始时间")
    end_time: str = Field(..., description="结束时间")
    
    # 因子配置
    factor_ids: List[int] = Field(..., description="要评价的因子ID列表")
    
    # 评价参数
    future_periods: int = Field(1, description="未来收益期数（用于计算未来收益）")
    quantile_count: int = Field(5, description="分位数数量（用于收益分析）")
    ic_window: Optional[int] = Field(None, description="IC计算窗口大小（None表示累计，int表示固定窗口大小）")
    
    # AlphaEval 新增配置
    enable_robustness: bool = Field(False, description="是否启用鲁棒性评估（会增加2-3倍计算时间）")
    robustness_noise_level: float = Field(0.05, description="鲁棒性测试噪声水平（标准差的倍数）")
    robustness_trials: int = Field(5, description="鲁棒性测试次数")
    
    # 综合评分权重配置
    scoring_weights: Optional[Dict[str, float]] = Field(
        default=None,
        description="综合评分权重配置（默认：预测能力40%、稳定性30%、鲁棒性30%）"
    )
    
    # 并行配置
    max_workers: int = Field(1, description="最大工作进程数")


class FactorEvaluationTaskOut(BaseModel):
    """因子评价任务输出"""
    id: int
    name: str
    status: str
    progress: float
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    
    # 配置
    config: Optional[Dict[str, Any]] = None
    data_config_id: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    symbols: Optional[List[str]] = None
    timeframes: Optional[List[str]] = None
    factor_ids: Optional[List[int]] = None
    
    # 结果
    summary: Optional[Dict[str, Any]] = None
    metrics: Optional[List[Dict[str, Any]]] = None
    charts: Optional[Dict[str, Any]] = None
    
    # 汇总指标
    ic_mean: Optional[float] = None
    ir: Optional[float] = None
    ic_win_rate: Optional[float] = None
    factor_count: Optional[int] = None
    
    # AlphaEval 汇总指标
    temporal_stability: Optional[float] = None
    robustness_score: Optional[float] = None
    diversity_score: Optional[float] = None
    alpha_eval_score: Optional[float] = None

    class Config:
        from_attributes = True


class FactorEvaluationTaskBriefOut(BaseModel):
    """因子评价任务简要输出（用于列表）"""
    id: int
    name: str
    status: str
    progress: float
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    
    # 关键信息
    data_config_id: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    symbols: Optional[List[str]] = None
    timeframes: Optional[List[str]] = None
    factor_ids: Optional[List[int]] = None
    
    # 汇总指标
    ic_mean: Optional[float] = None
    ir: Optional[float] = None
    ic_win_rate: Optional[float] = None
    factor_count: Optional[int] = None
    
    # AlphaEval 汇总指标
    temporal_stability: Optional[float] = None
    robustness_score: Optional[float] = None
    diversity_score: Optional[float] = None
    alpha_eval_score: Optional[float] = None

    class Config:
        from_attributes = True

