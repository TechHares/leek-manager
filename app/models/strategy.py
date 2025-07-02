from sqlalchemy import Column, Integer, String, JSON, DateTime
from app.models.base import ComponentModel
from datetime import datetime, UTC
from leek_core.models import  LeekComponentConfig, StrategyConfig, StrategyPositionConfig
from leek_core.base import  load_class_from_str

class Strategy(ComponentModel):
    __tablename__ = "strategies"
    data_source_config = Column(JSON, nullable=True)
    position_config = Column(JSON, nullable=True)
    enter_strategy_class_name = Column(String(200), nullable=False)
    enter_strategy_config = Column(JSON, nullable=True)
    exit_strategy_class_name = Column(String(200), nullable=False)
    exit_strategy_config = Column(JSON, nullable=True)
    risk_policies = Column(JSON, nullable=True)
    info_fabricator_configs = Column(JSON, nullable=True)
    data = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    def to_config(self) -> LeekComponentConfig:
        return LeekComponentConfig(
            instance_id=str(self.id),
            name=self.name,
            cls=load_class_from_str(self.class_name),
            data=self.data,
            config=StrategyConfig(
                data_source_configs=[LeekComponentConfig(
                    instance_id=str(cfg.get("id")),
                    name=cfg.get("name", ""),
                    cls=load_class_from_str(cfg.get("class_name")),
                    config=cfg.get("config", {})
                ) for cfg in self.data_source_config],
                info_fabricator_configs=[LeekComponentConfig(
                    instance_id=str(self.id),
                    name=self.name,
                    cls=load_class_from_str(cfg.get("class_name")),
                    config=cfg.get("config", {})
                ) for cfg in self.info_fabricator_configs],
                strategy_config=self.params if self.params else {},
                strategy_position_config=StrategyPositionConfig(**self.position_config) if self.position_config else None,
                enter_strategy_cls=load_class_from_str(self.enter_strategy_class_name),
                enter_strategy_config=self.enter_strategy_config if self.enter_strategy_config else {},
                exit_strategy_cls=load_class_from_str(self.exit_strategy_class_name),
                exit_strategy_config=self.exit_strategy_config if self.exit_strategy_config else {},
                risk_policies=[LeekComponentConfig(
                    instance_id=str(self.id),
                    name=self.name,
                    cls=load_class_from_str(cfg.get("class_name")),
                    config=cfg.get("config", {})
                ) for cfg in self.risk_policies],
            )
        )
