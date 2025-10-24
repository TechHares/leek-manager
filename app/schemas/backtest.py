from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum
from app.schemas.enums import TradeInsType


class BacktestTaskOut(BaseModel):
    id: int
    name: str
    type: str
    run_mode: Optional[str] = None  # 前端运行模式
    status: str
    progress: float
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    # 原始配置（用于重试/复用）
    config: Optional[Dict[str, Any]] = None
    # 关键信息（冗余列）
    strategy_class: Optional[str] = None
    data_config_id: Optional[int] = None
    cost_config_id: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    train_days: Optional[int] = None
    test_days: Optional[int] = None
    embargo_days: Optional[int] = None
    mode: Optional[str] = None
    cv_splits: Optional[int] = None
    max_workers: Optional[int] = None
    symbols: Optional[List[str]] = None
    timeframes: Optional[List[str]] = None
    # 结果聚合
    windows_count: Optional[int] = None
    sharpe_median: Optional[float] = None
    sharpe_p25: Optional[float] = None
    mdd_median: Optional[float] = None
    trades_median: Optional[float] = None
    turnover_median: Optional[float] = None
    pnl_median: Optional[float] = None
    win_rate: Optional[float] = None
    trade_win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    win_loss_ratio: Optional[float] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    profit_sum: Optional[float] = None
    loss_sum: Optional[float] = None
    profit_count: Optional[int] = None
    loss_count: Optional[int] = None
    # 衍生指标（由后端在返回时计算，不一定落库）
    total_return: Optional[float] = None
    annual_return: Optional[float] = None
    total_trades: Optional[int] = None
    pass_thresholds: Optional[bool] = None
    # 保留原始结果
    summary: Optional[Dict[str, Any]] = None
    windows: Optional[List[Dict[str, Any]]] = None

    class Config:
        from_attributes = True
class BacktestTaskBriefOut(BaseModel):
    id: int
    name: str
    type: str
    run_mode: Optional[str] = None  # 前端运行模式
    status: str
    progress: float
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    # 原始配置（用于复制）
    config: Optional[Dict[str, Any]] = None
    # 关键信息（冗余列）
    strategy_class: Optional[str] = None
    data_config_id: Optional[int] = None
    cost_config_id: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    train_days: Optional[int] = None
    test_days: Optional[int] = None
    embargo_days: Optional[int] = None
    mode: Optional[str] = None
    cv_splits: Optional[int] = None
    max_workers: Optional[int] = None
    symbols: Optional[List[str]] = None
    timeframes: Optional[List[str]] = None
    # 结果聚合（精简）
    windows_count: Optional[int] = None
    sharpe_median: Optional[float] = None
    sharpe_p25: Optional[float] = None
    mdd_median: Optional[float] = None
    trades_median: Optional[float] = None
    turnover_median: Optional[float] = None
    pnl_median: Optional[float] = None
    win_rate: Optional[float] = None
    trade_win_rate: Optional[float] = None
    # 衍生指标
    total_return: Optional[float] = None
    annual_return: Optional[float] = None
    total_trades: Optional[int] = None

    class Config:
        from_attributes = True



class BacktestConfigBase(BaseModel):
    name: str
    remark: Optional[str] = None
    type: str  # cost | data
    class_name: str
    params: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None


class BacktestConfigCreate(BacktestConfigBase):
    pass


class BacktestConfigUpdate(BaseModel):
    name: Optional[str] = None
    remark: Optional[str] = None
    type: Optional[str] = None
    class_name: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None


class BacktestConfigOut(BacktestConfigBase):
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==================== Enhanced Backtest Schemas ====================

class BacktestModeEnum(str, Enum):
    """回测模式枚举"""
    SINGLE = "single"
    NORMAL = "normal"
    PARAM_SEARCH = "param_search"
    WALK_FORWARD = "walk_forward"
    MONTE_CARLO = "monte_carlo"


class OptimizationObjectiveEnum(str, Enum):
    """优化目标枚举"""
    SHARPE_RATIO = "sharpe_ratio"
    CALMAR_RATIO = "calmar_ratio"
    SORTINO_RATIO = "sortino_ratio"
    PROFIT_FACTOR = "profit_factor"
    WIN_RATE = "win_rate"
    CUSTOM = "custom"


class EnhancedBacktestCreate(BaseModel):
    """增强型回测创建请求"""
    # 基础配置
    name: str = Field(..., description="回测名称")
    mode: BacktestModeEnum = Field(BacktestModeEnum.SINGLE, description="回测模式")
    
    # 策略配置
    strategy_class: str = Field(..., description="策略类全名")
    strategy_params: Optional[Dict[str, Any]] = Field(None, description="策略参数")
    
    # 数据配置
    symbols: List[str] = Field(..., description="交易标的列表")
    timeframes: List[str] = Field(..., description="时间框架列表")
    start_time: str = Field(..., description="开始时间")
    end_time: str = Field(..., description="结束时间")
    market: str = Field("okx", description="市场")
    quote_currency: str = Field("USDT", description="计价货币")
    ins_type: TradeInsType = Field(TradeInsType.SWAP, description="合约类型")
    
    # 执行配置
    initial_balance: float = Field(10000.0, description="初始资金")
    executor_class: str = Field("leek_core.executor.BacktestExecutor", description="执行器类")
    executor_config: Optional[Dict[str, Any]] = Field(None, description="执行器配置")
    
    # 参数搜索配置
    param_space: Optional[Dict[str, List[Any]]] = Field(None, description="参数空间")
    optimization_objective: OptimizationObjectiveEnum = Field(
        OptimizationObjectiveEnum.SHARPE_RATIO, 
        description="优化目标"
    )
    
    # 走向前配置
    train_days: Optional[int] = Field(None, description="训练天数")
    test_days: Optional[int] = Field(None, description="测试天数")
    embargo_days: int = Field(0, description="禁用天数")
    cv_splits: int = Field(0, description="交叉验证分割数")
    # Walk-Forward 窗口模式：rolling | expanding
    wf_window_mode: str = Field("rolling", description="WF窗口模式：rolling/expanding")
    
    # 并行配置
    max_workers: int = Field(1, description="最大并行数")
    min_window_size: int = Field(1, description="最小窗口大小")
    
    # 风险管理
    risk_policies: Optional[List[Dict[str, Any]]] = Field(None, description="风险策略列表")
    
    # 稳健性阈值（Walk-Forward专用）
    sharpe_median_min: Optional[float] = Field(None, description="夏普比率中位数下限")
    sharpe_p25_min: Optional[float] = Field(None, description="夏普比率P25下限")
    
    # 性能优化配置
    use_shared_memory_cache: bool = Field(False, description="是否使用共享内存缓存")
    # 与核心一致：允许直接传 use_cache
    use_cache: Optional[bool] = Field(None, description="是否使用缓存（别名，优先于 use_shared_memory_cache）")
    # 日志选项：是否写入 {id}.log
    log_file: Optional[bool] = Field(False, description="是否记录到文件（默认否）")
    cache_size_mb: int = Field(2048, description="缓存大小限制（MB）")
    mdd_median_max: Optional[float] = Field(None, description="最大回撤中位数上限")
    min_trades_per_window: Optional[int] = Field(None, description="每窗口最小交易数")
    
    # 配置模板ID
    data_config_id: Optional[int] = Field(None, description="数据配置ID")
    cost_config_id: Optional[int] = Field(None, description="费用配置ID")
    
    # 数据源配置
    data_source_config: Optional[Dict[str, Any]] = Field(None, description="数据源配置")
    data_source: Optional[str] = Field(None, description="数据源类名")


class EnhancedBacktestUpdate(BaseModel):
    """增强型回测更新请求"""
    name: Optional[str] = None
    status: Optional[str] = None


class PerformanceMetricsOut(BaseModel):
    """性能指标输出"""
    # 基础指标
    total_return: float = 0.0
    annual_return: float = 0.0
    volatility: float = 0.0
    
    # 风险调整收益指标
    sharpe_ratio: float = 0.0
    calmar_ratio: float = 0.0
    sortino_ratio: float = 0.0
    omega_ratio: float = 0.0
    sterling_ratio: float = 0.0
    information_ratio: float = 0.0
    
    # 回撤指标
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    avg_drawdown: float = 0.0
    drawdown_periods: int = 0
    
    # 交易指标
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0
    long_win_rate: float = 0.0
    short_win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_loss_ratio: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    
    # 其他指标
    turnover: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    beta: float = 0.0
    alpha: float = 0.0
    r_squared: float = 0.0
    
    # 时间相关
    best_month: float = 0.0
    worst_month: float = 0.0
    positive_months: int = 0
    negative_months: int = 0


class BacktestResultOut(BaseModel):
    """回测结果输出"""
    task_id: int
    name: str
    status: str
    config: Dict[str, Any]
    summary: Optional[Dict[str, Any]] = None
    windows: Optional[List[Dict[str, Any]]] = None
    metrics: Optional[PerformanceMetricsOut] = None
    created_at: datetime
    finished_at: Optional[datetime] = None
    execution_time: Optional[float] = None

