from sqlalchemy.orm import Session
from datetime import datetime
from decimal import Decimal
from app.models.asset_snapshot import AssetSnapshot
from app.schemas.asset_snapshot import AssetSnapshotCreate
from leek_core.utils import get_logger
from app.db.session import db_connect

logger = get_logger(__name__)

def save_asset_snapshot_from_position_image(project_id: int, data: dict) -> AssetSnapshot:
    """
    从position_image数据直接保存资产快照
        
    Args:
        project_id: 项目ID
        data: position_image的数据字典
        
    Returns:
        保存的资产快照对象
    """
    with db_connect() as db:
        try:
            # 获取当前时间并调整到整点
            now = datetime.now()
            snapshot_time = now.replace(minute=0, second=0, microsecond=0)
            
            # 从数据中提取资产信息
            pnl = Decimal(data.get('pnl', '0'))
            friction = Decimal(data.get('friction', '0'))
            fee = Decimal(data.get('fee', '0'))
            total_amount = Decimal(data.get('total_value', '0'))
            virtual_pnl = Decimal(data.get('virtual_pnl', '0'))
            # 兼容不同结构，优先顶层，其次 capital 内
            principal_source = data.get('principal')
            if principal_source is None:
                principal_source = (data.get('') or {}).get('', '0')

            position_amount = int(data.get('position', {}).get('position_count', '0'))
            principal = Decimal(data.get('capital', {}).get('principal', '0'))
            activate_amount = Decimal(data.get('capital', {}).get('available_balance', '0'))
            
            # 创建快照对象
            snapshot_data = AssetSnapshotCreate(
                project_id=project_id,
                snapshot_time=snapshot_time,
                activate_amount=activate_amount,
                pnl=pnl,
                friction=friction,
                fee=fee,
                total_amount=total_amount,
                principal=principal,
                virtual_pnl=virtual_pnl,
                position_amount=position_amount
            )
            
            # 保存到数据库
            snapshot = AssetSnapshot(**snapshot_data.model_dump())
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
            
            logger.info(f"项目 {project_id} 资产快照保存成功: 本金={principal}, 激活金额={activate_amount}, 盈亏={pnl}, 仓位数量={position_amount}")
            
            return snapshot
        
        except Exception as e:
            logger.error(f"保存项目 {project_id} 资产快照失败: {str(e)}")
            db.rollback()
            raise

def generate_asset_snapshot(db: Session, project_id: int, snapshot_time: datetime = None) -> AssetSnapshot:
    """
    为指定项目生成资产快照（从position表计算）
    
    Args:
        db: 数据库会话
        project_id: 项目ID
        snapshot_time: 快照时间，默认为当前时间
        
    Returns:
        生成的资产快照对象
    """
    if snapshot_time is None:
        snapshot_time = datetime.now()
    
    try:
        # 查询项目的所有未平仓仓位
        from app.models.position import Position
        from sqlalchemy import and_
        
        positions = db.query(Position).filter(
            and_(
                Position.project_id == project_id,
                Position.is_closed == False
            )
        ).all()
        
        # 计算资产数据
        total_pnl = Decimal('0')
        total_fee = Decimal('0')
        total_friction = Decimal('0')
        total_amount = Decimal('0')
        position_count = 0
        
        for position in positions:
            total_pnl += position.pnl or Decimal('0')
            total_fee += position.fee or Decimal('0')
            total_friction += position.friction or Decimal('0')
            total_amount += position.total_amount or Decimal('0')
            position_count += 1
        
        # 计算激活金额（总金额 - 手续费 - 摩擦成本）
        activate_amount = total_amount - total_fee - total_friction
        principal = Decimal('0')
        
        # 创建快照对象
        snapshot_data = AssetSnapshotCreate(
            project_id=project_id,
            snapshot_time=snapshot_time,
            activate_amount=activate_amount,
            pnl=total_pnl,
            friction=total_friction,
            fee=total_fee,
            total_amount=total_amount,
            principal=principal,
            virtual_pnl=Decimal('0'),  # 虚拟盈亏暂时设为0
            position_amount=position_count
        )
        
        # 保存到数据库
        snapshot = AssetSnapshot(**snapshot_data.model_dump())
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        
        logger.info(f"项目 {project_id} 资产快照生成成功: 激活金额={activate_amount}, 盈亏={total_pnl}, 仓位数量={position_count}")
        
        return snapshot
        
    except Exception as e:
        logger.error(f"生成项目 {project_id} 资产快照失败: {str(e)}")
        db.rollback()
        raise 