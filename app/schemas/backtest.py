from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel
from pydantic import BaseModel, Field


class WalkForwardCreate(BaseModel):
    name: str
    # 策略与参数空间
    strategy_class: str = Field(..., description="策略类全名，如 leek_core.strategy.strategy_dmi.DMIStrategy")
    param_space: Dict[str, List[Any]]
    # 风控策略（可选）：与策略配置保持一致，元素为 { class_name, config }
    risk_policies: Optional[List[Dict[str, Any]]] = None
    # 关联配置（便于追踪与列表展示）
    data_config_id: Optional[int] = None
    cost_config_id: Optional[int] = None

    # 执行/账户环境
    market: str = "okx"
    quote_currency: str = "USDT"
    ins_type: int = 3  # TradeInsType.SWAP
    initial_balance: float = 10000
    fee_rate: Optional[float] = None
    slippage_bps: Optional[float] = None

    # 评估配置
    symbols: List[str]
    timeframes: List[str]
    start: str
    end: str
    train_days: int
    test_days: int
    embargo_days: int = 0
    mode: str = "rolling"  # rolling | expanding
    cv_splits: int = 0
    max_workers: int = 1

    # 选择门槛
    sharpe_median_min: Optional[float] = None
    sharpe_p25_min: Optional[float] = None
    mdd_median_max: Optional[float] = None
    min_trades_per_window: int = 0


class BacktestTaskOut(BaseModel):
    id: int
    name: str
    type: str
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
    status: str
    progress: float
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
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

