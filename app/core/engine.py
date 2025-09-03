import asyncio
import logging
import os
import time
import json
import uuid
from typing import Dict, List, Optional
from leek_core.engine.grpc_engine import GrpcEngineClient
from leek_core.event import Event, EventType
from leek_core.utils import thread_lock, LeekJSONEncoder
from app.models.project import Project
from app.models.signal import Signal
from app.models.order import ExecutionOrder, Order
from app.db.session import db_connect, get_db
from sqlalchemy.orm import Session
from leek_core.utils import get_logger
from app.models.project_config import ProjectConfig
from app.models.datasource import DataSource
from app.models.execution import Executor
from app.models.strategy import Strategy
from app.models.risk_policy import RiskPolicy
from app.models.risk_log import RiskLog
from decimal import Decimal
from datetime import datetime
from app.models.position import Position
from app.models.balance_transaction import BalanceTransaction, TransactionType
from app.models.risk_log import RiskLog
from app.core.config_manager import config_manager
from app.core.template_manager import leek_template_manager

logger = get_logger(__name__)

class EngineManager:
    def __init__(self):
        self.clients: Dict[str, GrpcEngineClient] = {}
        self.scan_interval = 20  # 秒
        self._lock = asyncio.Lock()
        self._initializing_clients: Dict[str, bool] = {}  # 跟踪正在初始化的客户端

    def register_event_handlers(self, client: GrpcEngineClient):
        """注册事件处理器"""
        # 注册事件处理器
        client.register_handler(EventType.EXEC_ORDER_UPDATED, self.handle_exec_order_updated)
        client.register_handler(EventType.EXEC_ORDER_CREATED, self.handle_exec_order_created)
        client.register_handler(EventType.ORDER_UPDATED, self.handle_order_updated)
        client.register_handler(EventType.ORDER_CREATED, self.handle_order_created)
        client.register_handler(EventType.STRATEGY_SIGNAL, self.handle_strategy_signal)
        client.register_handler(EventType.POSITION_UPDATE, self.handle_position_update)
        client.register_handler(EventType.POSITION_INIT, self.handle_order_updated)
        client.register_handler(EventType.TRANSACTION, self.handle_transaction)
        client.register_handler(EventType.RISK_TRIGGERED, self.handle_risk_triggered)

    def handle_transaction(self, project_id: int, event):
        """处理交易事件"""
        data = event.data
        
        # 处理交易类型
        transaction_type = TransactionType(int(data.get('type', 0)))
        
        # 处理金额字段，确保为 Decimal 类型
        amount = Decimal(str(data.get('amount', 0)))
        balance_before = Decimal(str(data.get('balance_before', 0)))
        balance_after = Decimal(str(data.get('balance_after', 0)))
        
        transaction = BalanceTransaction(
            project_id=project_id,
            strategy_id=int(data.get('strategy_id')) if data.get('strategy_id') else None,
            strategy_instance_id=str(data.get('strategy_instance_id')) if data.get('strategy_instance_id') else None,
            position_id=int(data.get('position_id')) if data.get('position_id') else None,
            order_id=int(data.get('order_id')) if data.get('order_id') else None,
            signal_id=int(data.get('signal_id')) if data.get('signal_id') else None,
            executor_id=str(data.get('executor_id')) if data.get('executor_id') else None,
            asset_key=str(data.get('asset_key', '')),
            transaction_type=transaction_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            description=str(data.get('desc', '')),
        )
        
        with db_connect() as db:
            db.add(transaction)
            db.commit()

    def handle_risk_triggered(self, project_id: int, event):
        """处理风控触发事件"""
        # 事件数据包含 RiskEvent 对象的信息
        risk_event_data = event.data
        logger.debug(f"收到风控触发事件[{project_id}]: {risk_event_data.get('risk_type')} - {risk_event_data.get('risk_policy_class_name')}")
        
        # 处理时间戳：如果是毫秒级时间戳，转换为秒级
        trigger_timestamp = risk_event_data.get('trigger_time')
        if trigger_timestamp:
            # 如果时间戳大于 10^12，说明是毫秒级时间戳，需要转换为秒级
            if trigger_timestamp > 10**12:
                trigger_timestamp = trigger_timestamp / 1000
            trigger_time = datetime.fromtimestamp(trigger_timestamp)
        else:
            trigger_time = datetime.now()
        
        # 将 RiskEvent 转换为 RiskLog 模型并保存到数据库
        risk_log = RiskLog(
            project_id=project_id,
            risk_type=risk_event_data.get('risk_type', ''),
            strategy_id=risk_event_data.get('strategy_id'),
            strategy_instance_id=risk_event_data.get('strategy_instance_id'),
            strategy_class_name=risk_event_data.get('strategy_class_name'),
            risk_policy_id=risk_event_data.get('risk_policy_id'),
            risk_policy_class_name=risk_event_data.get('risk_policy_class_name', ''),
            trigger_time=trigger_time,
            trigger_reason=risk_event_data.get('trigger_reason'),
            signal_id=risk_event_data.get('signal_id'),
            execution_order_id=risk_event_data.get('execution_order_id'),
            position_id=risk_event_data.get('position_id'),
            original_amount=Decimal(str(risk_event_data.get('original_amount'))) if risk_event_data.get('original_amount') is not None else None,
            pnl=Decimal(str(risk_event_data.get('pnl'))) if risk_event_data.get('pnl') is not None else None,
            extra_info=risk_event_data.get('extra_info'),
            tags=risk_event_data.get('tags'),
        )
        
        with db_connect() as db:
            db.add(risk_log)
            db.commit()
            db.refresh(risk_log)
            logger.debug(f"风控日志已保存: ID={risk_log.id}, 项目={project_id}, 类型={risk_event_data.get('risk_type')}, 策略={risk_event_data.get('risk_policy_class_name')}")
                

    def handle_exec_order_updated(self, project_id: int, event):
        """处理执行订单更新事件"""
        data = event.data
        with db_connect() as db:
            execution_info = db.query(ExecutionOrder).filter(ExecutionOrder.id == int(data.get('context_id'))).first()
            if execution_info:
                execution_info.actual_ratio = data.get('actual_ratio')
                execution_info.actual_amount = data.get('actual_amount')
                execution_info.actual_pnl = data.get('actual_pnl')
                execution_info.execution_assets = data.get('execution_assets', [])
                execution_info.extra = data.get('extra', {})
                db.commit()

    def handle_exec_order_created(self, project_id: int, event):
        """处理执行订单创建事件"""
        execution_info = self.convert_exec_order(project_id, event)
        with db_connect() as db:
            db.add(execution_info)
            db.commit()

    def handle_order_updated(self, project_id: int, event):
        """处理订单更新事件"""
        event.data = [event.data]
        orders = self.convert_order(project_id, event)
        with db_connect() as db:
            for order in orders:
                existing_order = db.query(Order).filter(Order.id == order.id).first()
                if existing_order:
                    for key, value in order.__dict__.items():
                        if not key.startswith('_'):
                            setattr(existing_order, key, value)
            db.commit()

    def handle_order_created(self, project_id: int, event):
        """处理订单创建事件"""
        orders = self.convert_order(project_id, event)
        with db_connect() as db:
            for order in orders:
                db.add(order)
            db.commit()

    def handle_strategy_signal(self, project_id: int, event):
        """处理策略信号事件"""
        signal = self.convert_signal(project_id, event)
        with db_connect() as db:
            db.add(signal)
            db.commit()

    def handle_position_update(self, project_id: int, event):
        """处理仓位更新事件"""
        position = event.data
        logger.info(f"收到仓位更新事件[{project_id}-{position.get('position_id')}]: {position}")
        with db_connect() as db:
            # 查找是否存在该仓位
            existing_position = db.query(Position).filter(
                Position.project_id == project_id,
                Position.id == int(position.get('position_id'))
            ).first()
            
            if existing_position:
                if existing_position.is_closed:
                    return
                # 更新现有仓位
                self.update_position(existing_position, position)
                # 如果有虚拟仓位，更新风控日志
                self.update_risk_log_with_virtual_positions(db, project_id, existing_position)
            else:
                # 创建新仓位
                new_position = self.convert_position(project_id, position)
                db.add(new_position)
            
            db.commit()
            logger.info(f"仓位更新: {project_id} {position.get('position_id')} {position}")

    def convert_position(self, project_id: int, position_data) -> Position:
        """转换仓位模型"""
        # 获取sz值用于判断是否已关闭
        sz = 0
        executor_sz = position_data.get('executor_sz', {})
        if executor_sz:
            sz = sum(Decimal(v) for v in executor_sz.values())
        vpos = position_data.get('virtual_positions', [])
        vsz = 0
        if vpos:
            vsz = sum(Decimal(vp.get("sz", 0)) for vp in vpos)
        is_closed = sz <= 0 and vsz <= 0
        
        return Position(
            project_id=project_id,
            id=int(position_data.get('position_id', 0)),
            strategy_id=int(position_data.get('strategy_id', 0)),
            strategy_instance_id=str(position_data.get('strategy_instance_id', '')),
            symbol=str(position_data.get('symbol', '')),
            quote_currency=str(position_data.get('quote_currency', '')),
            ins_type=str(position_data.get('ins_type', '')),
            asset_type=str(position_data.get('asset_type', '')),
            side=str(position_data.get('side', '')),
            cost_price=Decimal(str(position_data.get('cost_price', 0))),
            amount=Decimal(str(position_data.get('amount', 0))),
            ratio=Decimal(str(position_data.get('ratio', 0))),
            max_sz=Decimal(str(position_data.get('sz', 0))),
            max_amount=Decimal(str(position_data.get('amount', 0))),
            executor_id=str(position_data.get('executor_id')) if position_data.get('executor_id') else None,
            pnl=Decimal(str(position_data.get('pnl', 0))),
            fee=Decimal(str(position_data.get('fee', 0))),
            friction=Decimal(str(position_data.get('friction', 0))),
            leverage=Decimal(str(position_data.get('leverage', 1))),
            open_time=datetime.fromtimestamp(position_data.get('open_time') / 1000) if position_data.get('open_time') else datetime.now(),
            sz=sz,
            executor_sz=position_data.get('executor_sz', {}),
            is_closed=is_closed,
            total_amount=Decimal(str(position_data.get('total_amount', 0))),
            total_sz=Decimal(str(position_data.get('total_sz', 0))),
            virtual_positions=position_data.get('virtual_positions', []),
            close_price=Decimal(str(position_data.get('close_price'))) if position_data.get('close_price') else None,
            current_price=Decimal(str(position_data.get('current_price'))) if position_data.get('current_price') else None,
        )

    def update_position(self, existing_position: Position, position_data):
        """更新仓位信息"""
        # 更新仓位信息，直接转换类型
        if 'amount' in position_data:
            existing_position.amount = Decimal(str(position_data.get('amount', 0)))
        if 'ratio' in position_data:
            existing_position.ratio = Decimal(str(position_data.get('ratio', 0)))
        if 'pnl' in position_data:
            existing_position.pnl = Decimal(str(position_data.get('pnl', 0)))
        if 'fee' in position_data:
            existing_position.fee = Decimal(str(position_data.get('fee', 0)))
        if 'friction' in position_data:
            existing_position.friction = Decimal(str(position_data.get('friction', 0)))
        if 'cost_price' in position_data:
            existing_position.cost_price = Decimal(str(position_data.get('cost_price', 0)))
        if 'close_price' in position_data:
            existing_position.close_price = Decimal(str(position_data.get('close_price'))) if position_data.get('close_price') else None
        if 'total_amount' in position_data:
            existing_position.total_amount = Decimal(str(position_data.get('total_amount', 0)))
        if 'total_sz' in position_data:
            existing_position.total_sz = Decimal(str(position_data.get('total_sz', 0)))
        if 'executor_sz' in position_data:
            existing_position.executor_sz = position_data.get('executor_sz', {})
        if 'current_price' in position_data:
            existing_position.current_price = Decimal(str(position_data.get('current_price'))) if position_data.get('current_price') else None
        if 'virtual_positions' in position_data:
            existing_position.virtual_positions = position_data.get('virtual_positions', [])

        sz = 0
        executor_sz = position_data.get('executor_sz', {})
        if executor_sz:
            sz = sum(Decimal(v) for v in executor_sz.values())
        existing_position.sz = sz
        # 更新最大值
        existing_position.max_sz = max(existing_position.max_sz,  sz)
        existing_position.max_amount = max(existing_position.max_amount, Decimal(str(position_data.get('amount', 0))))
        vpos = position_data.get('virtual_positions', [])
        vsz = 0
        if vpos:
            vsz = sum(Decimal(vp.get("sz", 0)) for vp in vpos)
        # 检查是否已关闭
        if existing_position.sz <= 0 and vsz <= 0:
            existing_position.is_closed = True
            existing_position.close_time = datetime.now()

    def update_risk_log_with_virtual_positions(self, db, project_id: int, position: Position):
        """更新风控日志的虚拟仓位信息"""
        if not position.virtual_positions or len(position.virtual_positions) == 0:
            return
        
        # 查找相关的风控日志（signal类型，根据signal_id和policy_id）
        for virtual_position in position.virtual_positions:
            signal_id = virtual_position.get('signal_id')
            policy_id = virtual_position.get('policy_id')
            pnl = Decimal(virtual_position.get('pnl', 0))
            if pnl == 0:
                continue
            if not signal_id or not policy_id:
                continue

            # 查找匹配的风控日志（正常情况下只有一条）
            risk_log = db.query(RiskLog).filter(
                RiskLog.project_id == project_id,
                RiskLog.risk_type == 'signal',
                RiskLog.signal_id == int(signal_id),
                RiskLog.risk_policy_id == int(policy_id)
            ).first()
            
            if risk_log:
                # 更新extra_info，保留原有的其他信息
                risk_log.extra_info = (risk_log.extra_info or {})
                risk_log.extra_info[str(position.id)] = str(pnl)
                # 更新总盈亏
                risk_log.pnl = sum(Decimal(v) for v in risk_log.extra_info.values())
                logger.info(f"更新风控日志: {risk_log.id}, signal_id: {signal_id}, policy_id: {policy_id}, virtual_pnl: {risk_log.pnl}")
            else:
                logger.error(f"未找到风控日志: signal_id: {signal_id}, policy_id: {policy_id}, virtual_pnl: {pnl}")
        
    def convert_order(self, project_id: int, event) -> List[Order]:
        """转换订单模型"""
        orders = []
        for data in event.data:
            order = Order(
                id=int(data.get('order_id', 0)),
                position_id=int(data.get('position_id')) if data.get('position_id') else None,
                strategy_id=int(data.get('strategy_id')),
                strategy_instant_id=data.get('strategy_instant_id', ''),
                project_id=project_id,
                signal_id=int(data.get('signal_id')),
                exec_order_id=int(data.get('exec_order_id')) if data.get('exec_order_id') else None,
                order_status=data.get('order_status', ''),
                order_time=datetime.fromtimestamp(data.get('order_time') / 1000) if data.get('order_time') else datetime.now(),
                ratio=Decimal(data.get('ratio', 0)),
                symbol=data.get('symbol', ''),
                quote_currency=data.get('quote_currency', ''),
                ins_type=int(data.get('ins_type', 0)),
                asset_type=data.get('asset_type', ''),
                side=data.get('side', ''),
                is_open=bool(data.get('is_open', False)),
                is_fake=bool(data.get('is_fake', False)),
                order_amount=Decimal(str(data.get('order_amount', 0))),
                order_price=Decimal(str(data.get('order_price', 0))),
                order_type=str(data.get('order_type', '')),
                settle_amount=Decimal(str(data.get('settle_amount'))) if data.get('settle_amount') else None,
                execution_price=Decimal(str(data.get('execution_price'))) if data.get('execution_price') else None,
                sz=Decimal(str(data.get('sz'))) if data.get('sz') else None,
                sz_value=Decimal(str(data.get('sz_value'))) if data.get('sz_value') else None,
                fee=Decimal(str(data.get('fee'))) if data.get('fee') else None,
                pnl=Decimal(str(data.get('pnl'))) if data.get('pnl') else None,
                unrealized_pnl=Decimal(str(data.get('unrealized_pnl'))) if data.get('unrealized_pnl') else None,
                finish_time=datetime.fromtimestamp(data.get('finish_time') / 1000) if data.get('finish_time') else None,
                friction=Decimal(str(data.get('friction', 0))),
                leverage=Decimal(str(data.get('leverage', 1))),
                executor_id=int(data.get('executor_id')) if data.get('executor_id') else None,
                trade_mode=str(data.get('trade_mode')) if data.get('trade_mode') else None,
                extra=data.get('extra', {}),
                market_order_id=str(data.get('market_order_id')) if data.get('market_order_id') else None
            )
            orders.append(order)
        return orders

    def convert_exec_order(self, project_id: int, event) -> ExecutionOrder:
        """转换执行订单模型"""
        data = event.data
        execution_assets = data.get('execution_assets', [])
        
        # 按照leek-core中的逻辑计算open_amount和open_ratio
        open_amount = Decimal('0')
        open_ratio = Decimal('0')
        
        for asset in execution_assets:
            if asset.get('is_open', False):
                # 累加金额
                if asset.get('amount'):
                    open_amount += Decimal(str(asset['amount']))
                # 累加比例
                if asset.get('ratio'):
                    open_ratio += Decimal(str(asset['ratio']))
        
        execution_info = ExecutionOrder(
            id=int(data.get('context_id', 0)),
            project_id=project_id,
            signal_id=str(data.get('signal_id', '')),
            strategy_id=int(data.get('strategy_id', 0)),
            strategy_instant_id=str(data.get('strategy_instant_id', '')),
            target_executor_id=str(data.get('target_executor_id', '')),
            execution_assets=execution_assets,
            open_amount=open_amount,
            open_ratio=open_ratio,
            leverage=Decimal(str(data.get('leverage'))) if data.get('leverage') else None,
            order_type=data.get('order_type', 0),
            trade_type=data.get('trade_type', 0),
            trade_mode=data.get('trade_mode', ''),
            created_time=datetime.fromtimestamp(data.get('created_time') / 1000) if data.get('created_time') else datetime.now(),
            actual_ratio=Decimal(str(data.get('actual_ratio'))) if data.get('actual_ratio') else None,
            actual_amount=Decimal(str(data.get('actual_amount'))) if data.get('actual_amount') else None,
            actual_pnl=Decimal(str(data.get('actual_pnl'))) if data.get('actual_pnl') else None,
            extra=data.get('extra', {}),
        )
        return execution_info

    def convert_signal(self, project_id: int, event) -> Signal:
        """转换信号模型"""
        data = event.data
        source = event.source
        cfg = None
        if data.get('config'):
            cfg = {
                "principal": str(data['config'].get('principal')) if data['config'].get('principal') else None,
                "leverage": str(data['config'].get('leverage')) if data['config'].get('leverage') else None,
                "order_type": data['config'].get('order_type'),
                "executor_id": data['config'].get('executor_id'),
            }
        
        assets = data.get('assets', [])
        return Signal(
            id=int(data.get('signal_id')),
            project_id=project_id,
            strategy_id=int(data.get('strategy_id')),
            data_source_instance_id=int(data.get('data_source_instance_id')),
            strategy_instance_id=str(data.get('strategy_instance_id')),
            data_source_class_name="",
            strategy_class_name=source.extra.get('class_name', ''),
            signal_time=datetime.fromtimestamp(data.get('signal_time') / 1000) if data.get('signal_time') else datetime.now(),
            assets=assets,
            config=cfg,
            extra=data.get('extra'),
        )

    async def add_client(self, instance_id: str, name: str) -> GrpcEngineClient:
        """添加客户端"""
        await leek_template_manager.get_manager(int(instance_id))
        async with self._lock:
            if instance_id in self.clients:
                return self.clients[instance_id]
            
            # 标记客户端正在初始化，防止被扫描器移除
            self._initializing_clients[instance_id] = True
            
            try:
                # 1. 配置
                with db_connect() as db:
                    project_config = db.query(ProjectConfig).filter_by(project_id=int(instance_id)).first()
                    if not project_config:
                        # 没有则插入一条默认配置
                        project_config = ProjectConfig(project_id=int(instance_id))
                        project_config.alert_config = []
                        project_config.mount_dirs = ["default"]
                        db.add(project_config)
                        db.commit()
                        db.refresh(project_config)
                    
                    # 序列化配置
                    config_dict = {c.name: getattr(project_config, c.name) for c in project_config.__table__.columns}
                    
                # 创建 gRPC 客户端
                client = GrpcEngineClient(
                    instance_id, name, config_dict
                )
                
                # 注册事件处理器
                self.register_event_handlers(client)
                
                await client.start()
                self.clients[instance_id] = client
                
                # 等待子进程启动
                await asyncio.sleep(2)
                
                # 同步仓位风控策略（全局）—在启用执行器之前
                risk_policies = db.query(RiskPolicy).filter_by(project_id=int(instance_id), is_enabled=True).all()
                for rp in risk_policies:
                    await self.send_action(instance_id, "add_position_policy", config=rp.dumps_map())

                # 启用执行器
                executors = db.query(Executor).filter_by(project_id=int(instance_id), is_enabled=True).all()
                for ex in executors:
                    await self.send_action(instance_id, "add_executor", config=ex.dumps_map())

                # 启用数据源
                datasources = db.query(DataSource).filter_by(project_id=int(instance_id), is_enabled=True).all()
                for ds in datasources:
                    await self.send_action(instance_id, "add_data_source", config=ds.dumps_map())
                
                # 启用策略
                strategies = db.query(Strategy).filter_by(project_id=int(instance_id), is_enabled=True).all()
                for st in strategies:
                    await self.send_action(instance_id, "add_strategy", config=st.dumps_map())

                return client
            
            finally:
                # 初始化完成，移除标记
                self._initializing_clients.pop(instance_id, None)

    async def remove_client(self, instance_id: str):
        """移除客户端"""
        # 检查客户端是否正在初始化，如果是则不移除
        if instance_id in self._initializing_clients:
            logger.info(f"客户端 {instance_id} 正在初始化，跳过移除操作")
            return
            
        client = self.clients.pop(instance_id, None)
        if client:
            await client.stop()

    def get_client(self, project_id: str) -> Optional[GrpcEngineClient]:
        """获取客户端"""
        return self.clients.get(str(project_id))

    async def send_action(self, instance_id: str, action: str, *args, **kwargs):
        """向引擎发送动作"""
        try:
            client = self.get_client(instance_id)
            if not client:
                # 检查是否正在初始化
                if instance_id in self._initializing_clients:
                    logger.warning(f"客户端 {instance_id} 正在初始化，等待完成后重试")
                    # 等待初始化完成
                    max_wait = 10  # 最多等待10秒
                    wait_time = 0
                    while instance_id in self._initializing_clients and wait_time < max_wait:
                        await asyncio.sleep(0.5)
                        wait_time += 0.5
                    
                    # 重新获取客户端
                    client = self.get_client(instance_id)
                    if not client:
                        raise Exception(f"等待初始化完成后仍未找到客户端: {instance_id}")
                else:
                    raise Exception(f"未找到客户端: {instance_id}")
            return await client.invoke(action, *args, **kwargs)
                
        except Exception as e:
            logger.error(f"发送动作失败: {instance_id}, {action}, {args}, {kwargs}, {e}", exc_info=True)
            raise e

    async def storage_position_image(self):
        """异步调用仓位镜像存储 - 用于调度器"""
        # 为每个项目单独处理，避免事件循环冲突
        for project_id in self.clients.keys():
            try:
                await self.save_position_image(project_id)
            except Exception as e:
                logger.error(f"处理项目 {project_id} 的仓位镜像时出错: {e}")
    
    async def save_position_image(self, project_id: str):
        """处理仓位镜像事件"""
        logger.info(f"收到仓位镜像: {project_id}")
        # 保存资产快照
        try:
            client = self.get_client(project_id)
            if not client:
                raise Exception(f"未找到客户端: {project_id}")
            data = await client.invoke('get_position_state')
            from app.service.asset_snapshot_service import save_asset_snapshot_from_position_image
            save_asset_snapshot_from_position_image(int(project_id), data)
        except Exception as e:
            logger.error(f"保存资产快照失败: {str(e)}")

    async def scan_projects(self):
        """扫描项目"""
        while True:
            try:
                config = config_manager.get_config()
                if not config["is_configured"]:
                    await asyncio.sleep(self.scan_interval)
                    continue
                
                db = get_db()
                try:
                    projects = db.query(Project).filter(Project.is_deleted == False, Project.is_enabled == True).all()
                    # 获取所有活跃项目的ID
                    active_project_ids = {str(project.id) for project in projects}
                    
                    # 清理那些在clients中存在但在数据库中已经不存在的项目对应的客户端
                    for instance_id in list(self.clients.keys()):
                        if instance_id not in active_project_ids:
                            # 检查是否正在初始化，如果是则跳过
                            if instance_id in self._initializing_clients:
                                logger.info(f"Client {instance_id} is initializing, skipping removal")
                                continue
                            logger.info(f"Stopping client for deleted project {instance_id}")
                            await self.remove_client(instance_id)
                            # 如果数据库中有这个项目，更新其engine_info
                            project = db.query(Project).filter(Project.id == instance_id).first()
                            if project:
                                project.engine_info = {"process_id": None}
                                db.commit()
                    
                    for project in projects:
                        instance_id = str(project.id)
                        engine_info = project.engine_info or {}
                        pid = engine_info.get('process_id')
                        
                        if not pid:
                            # 没有进程，启动
                            client = await self.add_client(instance_id, project.name)
                            project.engine_info = {"process_id": client.process.pid if client.process else None}
                            db.commit()
                        else:
                            client = self.clients.get(instance_id)
                            if not client:
                                client = await self.add_client(instance_id, project.name)
                                project.engine_info = {"process_id": client.process.pid if client.process else None}
                                db.commit()
                                await asyncio.sleep(1)
                            
                            # 检查进程状态
                            if client and client.is_alive():
                                try:
                                    # 策略状态
                                    strategys_state = await client.invoke('get_strategy_state')
                                    # 更新策略状态到数据库
                                    if strategys_state and isinstance(strategys_state, dict):
                                        for strategy_id_str, strategy_data in strategys_state.items():
                                            try:
                                                strategy_id = int(strategy_id_str)
                                                strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
                                                if strategy:
                                                    strategy.data = strategy_data
                                                    logger.debug(f"更新策略 {strategy_id} 状态: {strategy_data}")
                                            except (ValueError, TypeError) as e:
                                                logger.warning(f"无效的策略ID格式: {strategy_id_str}, 错误: {e}")
                                        db.commit()
                                    # 仓位状态
                                    data = await client.invoke('get_position_state')
                                    project_config = db.query(ProjectConfig).filter(ProjectConfig.project_id == project.id).first()
                                    project_config.position_data = data
                                    db.commit()
                                except Exception as e:
                                    logger.warning(f"Project {project.name} gRPC 连接异常: {e}")
                                    await self.remove_client(instance_id)
                                    project.engine_info = {"process_id": None}
                                    db.commit()
                            else:
                                logger.warning(f"Project {project.name} 进程不存在，重新启动")
                                await self.remove_client(instance_id)
                                project.engine_info = {"process_id": None}
                                db.commit()
                finally:
                    db.close()
                
                await asyncio.sleep(self.scan_interval)
                
            except asyncio.CancelledError:
                logger.info("项目扫描任务被取消")
                break
            except Exception as e:
                logger.error(f"项目扫描异常: {e}", exc_info=True)
                await asyncio.sleep(self.scan_interval)

    def start(self):
        """启动引擎管理器"""
        try:
            # 注册事件处理器（这里只是初始化，具体的处理器会在 add_client 时注册）
            logger.info("引擎管理器启动完成")
            return True
            
        except Exception as e:
            logger.error(f"启动引擎管理器失败: {e}", exc_info=True)
            return False

    async def stop(self):
        """停止引擎管理器"""
        logger.info("正在停止引擎管理器...")
        
        # 停止所有客户端
        for instance_id, client in list(self.clients.items()):
            try:
                logger.info(f"正在停止客户端: {instance_id}")
                await client.stop()
            except Exception:
                ...
        
        self.clients.clear()
        
        logger.info("引擎管理器已停止")

# 创建引擎管理器实例
engine_manager = EngineManager()

async def start_engine_manager():
    """启动引擎管理器"""
    logger.info("start_engine_manager: 开始启动引擎管理器")
    try:
        # 启动引擎管理器
        if not engine_manager.start():
            logger.error("启动引擎管理器失败")
            return
        
        logger.info("start_engine_manager: 引擎管理器启动成功，开始扫描项目")
        
        await asyncio.gather(
            engine_manager.scan_projects()
        )
    except asyncio.CancelledError:
        logger.info("start_engine_manager: 引擎管理器任务被取消")
        await engine_manager.stop()
        raise
    except Exception as e:
        logger.error(f"引擎管理器运行异常: {e}", exc_info=True)
        await engine_manager.stop()
        raise
