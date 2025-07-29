from sqlalchemy import Column, Integer, String, DateTime, Numeric, Index
from datetime import datetime, UTC
from app.models.base import BaseModel

class AssetSnapshot(BaseModel):
    __tablename__ = "asset_snapshots"

    project_id = Column(Integer, nullable=False, index=True, comment="项目ID")
    snapshot_time = Column(DateTime, nullable=False, index=True, comment="快照时间")
    
    # 资产相关字段
    activate_amount = Column(Numeric(36, 18), nullable=False, comment="激活金额")
    pnl = Column(Numeric(36, 18), nullable=False, default=0, comment="盈亏")
    friction = Column(Numeric(36, 18), nullable=False, default=0, comment="摩擦成本")
    fee = Column(Numeric(36, 18), nullable=False, default=0, comment="手续费")
    total_amount = Column(Numeric(36, 18), nullable=False, comment="总金额")
    virtual_pnl = Column(Numeric(36, 18), nullable=False, default=0, comment="虚拟盈亏")
    position_amount = Column(Integer, nullable=False, default=0, comment="仓位数量")

    # 创建复合索引
    __table_args__ = (
        Index('idx_project_snapshot_time', 'project_id', 'snapshot_time'),
    ) 