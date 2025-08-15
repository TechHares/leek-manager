from sqlalchemy import Column, String, JSON, DateTime, Integer, Float, Boolean
from datetime import datetime
from app.models.base import BaseModel


class BacktestTask(BaseModel):
    __tablename__ = "backtest_tasks"

    # 基本信息
    project_id = Column(Integer, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    type = Column(String(32), nullable=False, default="walk_forward")  # single | walk_forward

    # 配置与状态
    config = Column(JSON, nullable=True)  # 请求配置快照
    status = Column(String(32), nullable=False, default="pending")  # pending | running | completed | failed
    progress = Column(Float, nullable=False, default=0.0)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error = Column(String(2000), nullable=True)

    # 关键信息（冗余，便于列表检索/展示）
    strategy_class = Column(String(512), nullable=True)
    data_config_id = Column(Integer, nullable=True)
    cost_config_id = Column(Integer, nullable=True)
    start = Column(String(32), nullable=True)
    end = Column(String(32), nullable=True)
    train_days = Column(Integer, nullable=True)
    test_days = Column(Integer, nullable=True)
    embargo_days = Column(Integer, nullable=True)
    mode = Column(String(32), nullable=True)
    cv_splits = Column(Integer, nullable=True)
    max_workers = Column(Integer, nullable=True)
    symbols = Column(JSON, nullable=True)
    timeframes = Column(JSON, nullable=True)

    # 结果
    summary = Column(JSON, nullable=True)  # 聚合摘要
    windows = Column(JSON, nullable=True)  # 窗口级明细
    artifacts = Column(JSON, nullable=True)  # 产物路径/图表等（可选）

    # 汇总结论（冗余字段，便于快速排序/筛选/展示）
    windows_count = Column(Integer, nullable=True)
    sharpe_median = Column(Float, nullable=True)
    sharpe_p25 = Column(Float, nullable=True)
    mdd_median = Column(Float, nullable=True)
    trades_median = Column(Float, nullable=True)
    turnover_median = Column(Float, nullable=True)
    pnl_median = Column(Float, nullable=True)
    pass_thresholds = Column(Boolean, nullable=True)
    # 冗余的衍生指标（避免列表接口解析大 JSON）
    win_rate = Column(Float, nullable=True)  # 窗口胜率
    trade_win_rate = Column(Float, nullable=True)  # 交易胜率（基于订单）
    total_return = Column(Float, nullable=True)  # 总收益率
    annual_return = Column(Float, nullable=True)  # 年化收益率
    total_trades = Column(Integer, nullable=True)  # 总交易次数（sum of window.test_trades）
    profit_factor = Column(Float, nullable=True)  # 盈亏比（总盈利/总亏损绝对值）
    win_loss_ratio = Column(Float, nullable=True)  # 平均盈利/平均亏损
    avg_win = Column(Float, nullable=True)  # 平均盈利（单笔）
    avg_loss = Column(Float, nullable=True)  # 平均亏损（单笔，取绝对值）
    # 盈亏合计与次数
    profit_sum = Column(Float, nullable=True)
    loss_sum = Column(Float, nullable=True)
    profit_count = Column(Integer, nullable=True)
    loss_count = Column(Integer, nullable=True)


