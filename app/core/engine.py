import asyncio
import logging
import os
import threading
import time
from typing import Dict, List, Optional
from leek_core.engine.process import ProcessEngineClient
from leek_core.event import Event, EventType
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
from decimal import Decimal
from datetime import datetime
from app.models.position import Position
from app.core.config_manager import config_manager
from app.core.template_manager import template_manager

logger = get_logger(__name__)

EVENTS = set([EventType.EXEC_ORDER_UPDATED, EventType.EXEC_ORDER_CREATED, EventType.ORDER_UPDATED,
              EventType.ORDER_CREATED, EventType.STRATEGY_SIGNAL, EventType.POSITION_UPDATE, EventType.POSITION_INIT])
class EngineManager:
    def __init__(self):
        self.clients: Dict[str, ProcessEngineClient] = {}
        self.last_pong: Dict[str, float] = {}
        self.scan_interval = 10  # 秒
        self.pong_timeout = 10    # 秒
        self._lock = asyncio.Lock()

    def register_client_callbacks(self, client: ProcessEngineClient):
        """注册客户端回调"""
        client.register_handler("pong", self.pong)
        client.register_handler("event", self.handle_event)
        client.register_handler("strategy_data", self.handle_strategy_data)
        client.register_handler("position_data", self.handle_position_data)

    def handle_strategy_data(self, project_id: int, strategy_id: str, data: dict):
        with db_connect() as db:
            strategy = db.query(Strategy).filter(Strategy.project_id == int(project_id), Strategy.id == int(strategy_id), Strategy.is_enabled == True).first()
            if strategy:
                strategy.data = data
                db.commit()

    def handle_position_data(self, project_id: str, data: dict):
        with db_connect() as db:
            project_config = db.query(ProjectConfig).filter(ProjectConfig.project_id == int(project_id)).first()
            project_config.position_data = data
            db.commit()

    def convert_position(self, project_id: int, position) -> Position:
        """转换仓位模型"""
        return Position(
            project_id=int(project_id),
            id=int(position.position_id),
            strategy_id=int(position.strategy_id),
            strategy_instance_id=str(position.strategy_instance_id),
            symbol=position.symbol,
            quote_currency=position.quote_currency,
            ins_type=position.ins_type.value,
            asset_type=position.asset_type.value,
            side=position.side.value,
            cost_price=position.cost_price,
            amount=position.amount,
            ratio=position.ratio,
            max_sz=position.sz,
            max_amount=position.amount,
            executor_id=int(position.executor_id) if position.executor_id else None,
            is_fake=position.is_fake,
            pnl=position.pnl,
            fee=position.fee,
            friction=position.friction,
            leverage=position.leverage,
            open_time=position.open_time,
            sz=position.sz,
            executor_sz={k: str(v) for k, v in position.executor_sz.items()},
            is_closed=position.sz <= 0,
            total_amount=position.total_amount,
            total_sz=position.total_sz,
            close_price=position.close_price,
            current_price=position.current_price,
        )

    def update_position(self, existing_position: Position, position):
        """更新仓位信息"""
        existing_position.amount = position.amount
        existing_position.ratio = position.ratio
        existing_position.pnl = position.pnl
        existing_position.fee = position.fee
        existing_position.friction = position.friction
        existing_position.cost_price = position.cost_price
        existing_position.close_price = position.close_price
        existing_position.total_amount = position.total_amount
        existing_position.total_sz = position.total_sz
        existing_position.sz = position.sz
        existing_position.executor_sz = {k: str(v) for k, v in position.executor_sz.items()}
        existing_position.max_sz = max(existing_position.max_sz, position.sz)
        existing_position.max_amount = max(existing_position.max_amount, position.amount)
        existing_position.current_price = position.current_price

        existing_position.updated_at = datetime.now()
        if existing_position.sz <= 0:
            existing_position.is_closed = True
            existing_position.close_time = datetime.now()

    def handle_event(self, project_id: int, event: Event):
        logger.info(f"收到事件[{project_id}]: {event.event_type} {event.data}")
        if event.event_type == EventType.EXEC_ORDER_UPDATED:
            with db_connect() as db:
                execution_info = db.query(ExecutionOrder).filter(ExecutionOrder.id == int(event.data.context_id)).first()
                if execution_info:
                    execution_info.actual_ratio = event.data.actual_ratio
                    execution_info.actual_amount = event.data.actual_amount
                    execution_info.actual_pnl = event.data.actual_pnl
                    execution_info.execution_assets = [
                        {
                            "asset_type": asset.asset_type.value,
                            "ins_type": asset.ins_type.value,
                            "symbol": asset.symbol,
                            "side": asset.side.value,
                            "price": str(asset.price) if asset.price else None,
                            "is_open": asset.is_open,
                            "is_fake": asset.is_fake,
                            "ratio": str(asset.ratio) if asset.ratio else None,
                            "amount": str(asset.amount) if asset.amount else None,
                            "sz": str(asset.sz) if asset.sz else None,
                            "quote_currency": asset.quote_currency,
                            "extra": asset.extra,
                            "position_id": asset.position_id,
                            "actual_pnl": str(asset.actual_pnl) if asset.actual_pnl else None,
                        }  for asset in event.data.execution_assets
                    ]
                    execution_info.extra = event.data.extra
                    db.commit()
            return

        if event.event_type == EventType.EXEC_ORDER_CREATED:
            execution_info = self.convert_exec_order(project_id, event)
            with db_connect() as db:
                db.add(execution_info)
                db.commit()
            return

        if event.event_type == EventType.POSITION_UPDATE:
            position = event.data
            with db_connect() as db:
                # 查找是否存在该仓位
                existing_position = db.query(Position).filter(
                Position.project_id == project_id,
                Position.id == int(position.position_id)
            ).first()
            if existing_position:
                # 更新现有仓位
                self.update_position(existing_position, position)
            else:
                # 创建新仓位
                new_position = self.convert_position(project_id, position)
                db.add(new_position)
            
            db.commit()
            client = self.get_client(str(project_id))
            if client:
                client.send_action('storage_strategy')
                client.send_action('storage_postion')
            return

        if event.event_type == EventType.ORDER_UPDATED or event.event_type == EventType.POSITION_INIT:
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
            return
        if event.event_type == EventType.ORDER_CREATED:
            orders = self.convert_order(project_id, event)
            with db_connect() as db:
                for order in orders:
                    db.add(order)
                db.commit()
            return
        
        if event.event_type == EventType.STRATEGY_SIGNAL:
            with db_connect() as db:
                signal = self.convert_signal(project_id, event)
                db.add(signal)
                db.commit()
            return
    
    def convert_order(self, project_id, event) -> List[Order]:
        datas = event.data
    
        return [Order(
            id=int(data.order_id),
            position_id=int(data.position_id) if data.position_id else None,
            strategy_id=int(data.strategy_id),
            strategy_instant_id=str(data.strategy_instant_id),
            project_id=project_id,
            signal_id=int(data.signal_id),
            exec_order_id=int(data.exec_order_id) if data.exec_order_id else None,  
            order_status=data.order_status.value,
            order_time=data.order_time,
            ratio=data.ratio,
            
            symbol=data.symbol,
            quote_currency=data.quote_currency,
            ins_type=data.ins_type.value,
            asset_type=data.asset_type.value,
            side=data.side.value,
            
            is_open=data.is_open,
            is_fake=data.is_fake,
            order_amount=data.order_amount,
            order_price=data.order_price,
            order_type=data.order_type.value,
            
            settle_amount=data.settle_amount,
            execution_price=data.execution_price,
            sz=data.sz,
            sz_value=data.sz_value,
            fee=data.fee,
            pnl=data.pnl,
            unrealized_pnl=data.unrealized_pnl,
            finish_time=data.finish_time,
            friction=data.friction,
            leverage=data.leverage,

            executor_id=int(data.executor_id) if data.executor_id else None,
            trade_mode=data.trade_mode.value,
            extra={
                **(data.extra or {})
            },
            market_order_id=data.market_order_id
        ) for data in datas]

    def convert_exec_order(self, project_id, event) -> ExecutionOrder:
        # 处理数据类型
            data = event.data
            execution_info = ExecutionOrder(
                id=int(data.context_id),
                project_id=project_id,
                signal_id=int(data.signal_id),
                strategy_id=int(data.strategy_id),
                strategy_instant_id=str(data.strategy_instant_id),
                target_executor_id=str(data.target_executor_id),
                execution_assets=[
                    {
                        "asset_type": asset.asset_type.value,
                        "ins_type": asset.ins_type.value,
                        "symbol": asset.symbol,
                        "side": asset.side.value,
                        "price": str(asset.price) if asset.price else None,
                        "is_open": asset.is_open,
                        "is_fake": asset.is_fake,
                        "ratio": str(asset.ratio) if asset.ratio else None,
                        "amount": str(asset.amount) if asset.amount else None,
                        "sz": str(asset.sz) if asset.sz else None,
                        "quote_currency": asset.quote_currency,
                        "extra": asset.extra,
                        "position_id": asset.position_id,
                        "actual_pnl": str(asset.actual_pnl) if asset.actual_pnl else None,
                    }  for asset in event.data.execution_assets
                ],
                open_amount=data.open_amount,
                open_ratio=data.open_ratio,
                leverage=data.leverage,
                order_type=data.order_type.value,
                trade_type=data.trade_type.value,
                trade_mode=data.trade_mode.value,
                created_time=data.created_time,
                actual_ratio=data.actual_ratio,
                actual_amount=data.actual_amount,
                actual_pnl=data.actual_pnl,
                extra=data.extra,
            )
            return execution_info

    def convert_signal(self, project_id, event) -> Signal:
        cfg = None
        if event.data.config:
            cfg = {
                "principal": str(event.data.config.principal) if event.data.config.principal else None,
                "leverage": str(event.data.config.leverage) if event.data.config.leverage else None,
                "order_type": event.data.config.order_type.value,
                "executor_id": event.data.config.executor_id,
            }
        assets = []
        for asset in event.data.assets:
            assets.append({
                "asset_type": asset.asset_type.value,
                "ins_type": asset.ins_type.value,
                "symbol": asset.symbol,
                "side": asset.side.value,
                "price": str(asset.price) if asset.price else None,
                "ratio": str(asset.ratio) if asset.ratio else None,
                "quote_currency": asset.quote_currency,
                "extra": asset.extra,
            })
        return Signal(
            id=int(event.data.signal_id),
            project_id=project_id,
            strategy_id=int(event.data.strategy_id),
            data_source_instance_id=int(event.data.data_source_instance_id),
            strategy_instance_id=str(event.data.strategy_instance_id),
            data_source_class_name="",
            strategy_class_name=event.source.extra.get("class_name"),
            signal_time=event.data.signal_time,
            assets=assets,
            config=cfg,
            extra=event.data.extra,
        )

    async def add_client(self, instance_id: str, name: str) -> ProcessEngineClient:
        async with self._lock:
            await template_manager.get_manager(int(instance_id))
            if instance_id in self.clients:
                return self.clients[instance_id]
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
            client = ProcessEngineClient(instance_id, name,
                                          {c.name: getattr(project_config, c.name) for c in project_config.__table__.columns},
                                          event_hook=EVENTS)
            self.register_client_callbacks(client)
            client.start()
            self.clients[instance_id] = client
            threading.Thread(target=client.listen, daemon=True).start()

            # 3. 启用执行器
            executors = db.query(Executor).filter_by(project_id=int(instance_id), is_enabled=True).all()
            for ex in executors:
                client.add_executor(ex.to_config())

            # 2. 启用数据源
            datasources = db.query(DataSource).filter_by(project_id=int(instance_id), is_enabled=True).all()
            for ds in datasources:
                client.add_data_source(ds.to_config())
            
            await asyncio.sleep(5)
            # 4. 启用策略
            strategies = db.query(Strategy).filter_by(project_id=int(instance_id), is_enabled=True).all()
            for st in strategies:
                client.add_strategy(st.to_config())

            return client

    def remove_client(self, instance_id: str):
        client = self.clients.pop(instance_id, None)
        if client:
            client.stop()

    def get_client(self, project_id: str) -> Optional[ProcessEngineClient]:
        return self.clients.get(str(project_id))

    def pong(self, instance_id: str):
        self.last_pong[instance_id] = time.time()

    async def scan_projects(self):
        while True:
            config = config_manager.get_config()
            if not config["is_configured"]:
                await asyncio.sleep(self.scan_interval)
                continue
            db = get_db()
            try:
                projects = db.query(Project).filter(Project.is_deleted == False).all()
                # 获取所有活跃项目的ID
                active_project_ids = {str(project.id) for project in projects}
                # 清理那些在clients中存在但在数据库中已经不存在的项目对应的客户端
                for instance_id in list(self.clients.keys()):
                    if instance_id not in active_project_ids:
                        logger.info(f"Stopping client for deleted project {instance_id}")
                        self.remove_client(instance_id)
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
                        project.engine_info = {"process_id": client.process.pid}
                        db.commit()
                    else:
                        client = self.clients.get(instance_id)
                        if not client:
                            client = await self.add_client(instance_id, project.name)
                            project.engine_info = {"process_id": client.process.pid}
                            db.commit()
                            await asyncio.sleep(1)
                        # 发送ping
                        client.send_action('ping', instance_id=instance_id)
                        pong_ok = await self.wait_pong(instance_id)
                        if not pong_ok:
                            logger.warning(f"Project {project.name} pong timeout, killing process {pid}")
                            self.remove_client(instance_id)
                            self.kill_pid(pid)
                            project.engine_info = {"process_id": None}
                            db.commit()
                        else:
                            client.send_action('storage_postion')
                            client.send_action('storage_strategy')
            finally:
                db.close()
            await asyncio.sleep(self.scan_interval)

    async def wait_pong(self, instance_id, timeout=None):
        timeout = timeout or self.pong_timeout
        start = time.time()
        while time.time() - start < timeout:
            if self.last_pong.get(instance_id, 0) > start:
                return True
            await asyncio.sleep(0.2)
        return False

    @staticmethod
    def check_pid_alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    @staticmethod
    def kill_pid(pid):
        try:
            os.kill(pid, 9)
        except Exception:
            pass

    def stop_all(self):
        """停止所有客户端"""
        for client in self.clients.values():
            client.stop()
        self.clients.clear()

engine_manager = EngineManager()
async def start_engine_manager():
    try:
        await asyncio.gather(
            engine_manager.scan_projects()
        )
    except asyncio.CancelledError:
        engine_manager.stop_all()
        raise
