from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, cast, Boolean
from datetime import datetime
from app.db.session import get_db
from app.models.balance_transaction import BalanceTransaction, TransactionType
from app.api.deps import get_project_id
from app.schemas.common import PageResponse
from app.schemas.transaction import TransactionOut, TransactionFilter
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/transactions", response_model=PageResponse[TransactionOut])
async def list_transactions(
    filters: TransactionFilter = Depends(),
    page: int = 1,
    size: int = 20,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db)
):
    """
    List transactions with filters and pagination
    """
    query = db.query(BalanceTransaction)
    query = query.filter(BalanceTransaction.project_id == project_id)
    
    # 应用过滤器
    if filters.id is not None:
        # ID 查询支持多个字段：流水ID、策略ID、仓位ID、订单ID、信号ID
        query = query.filter(
            or_(
                BalanceTransaction.id == filters.id,
                BalanceTransaction.strategy_id == filters.id,
                BalanceTransaction.position_id == filters.id,
                BalanceTransaction.order_id == filters.id,
                BalanceTransaction.signal_id == filters.id
            )
        )
    if filters.transaction_type is not None:
        query = query.filter(BalanceTransaction.transaction_type == filters.transaction_type)
    if filters.show_frozen is False:
        # 如果不显示冻结，则排除冻结和解冻类型
        query = query.filter(
            BalanceTransaction.transaction_type.notin_([
                TransactionType.FROZEN, 
                TransactionType.UNFROZEN
            ])
        )
    
    total = query.count()
    items = query.order_by(BalanceTransaction.created_at.desc(), BalanceTransaction.id.desc()).offset((page - 1) * size).limit(size).all()
    
    return PageResponse(total=total, page=page, size=size, items=items)

@router.get("/transactions/{transaction_id}", response_model=TransactionOut)
async def get_transaction(
    transaction_id: int,
    project_id: int = Depends(get_project_id),
    db: Session = Depends(get_db)
):
    """
    Get transaction by ID
    """
    transaction = db.query(BalanceTransaction).filter(
        BalanceTransaction.id == transaction_id,
        BalanceTransaction.project_id == project_id
    ).first()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    return transaction 