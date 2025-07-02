from enum import Enum
from typing import Any, List
from pydantic import BaseModel

class TradeMode(str, Enum):
    """
    交易模式
    """
    ISOLATED = "isolated"  # 保证金模式-逐仓
    CROSS = "cross"  # 保证金模式-全仓
    CASH = "cash"  # 非保证金模式-非保证金
    SPOT_ISOLATED = "spot_isolated" # 现货-带单

class AssetType(str, Enum):
    """金融资产类型。"""
    STOCK = "stock"           # 股票
    FUTURES = "futures"       # 期货
    CRYPTO = "crypto"         # 加密货币
    FOREX = "forex"           # 外汇
    INDEX = "index"           # 指数
    BOND = "bond"             # 债券
    COMMODITY = "commodity"   # 商品
    OPTION = "option"         # 期权

class TradeInsType(int, Enum):
    """交易产品类型"""
    SPOT = 1      # 现货
    MARGIN = 2    # 杠杆
    SWAP = 3      # 合约
    FUTURES = 4   # 期货
    OPTION = 5    # 期权 

class OrderType(int, Enum):
    """
    交易类型 OrderType
    """
    MarketOrder = 1  # 市价单
    LimitOrder = 2   # 限价单

class OrderStatus(str, Enum):
    """
    订单状态。
    """
    CREATED = "created"      # 已创建，待提交
    SUBMITTED = "submitted"  # 已提交到交易所/撮合系统
    PARTIALLY_FILLED = "partially_filled"  # 部分成交
    FILLED = "filled"        # 全部成交
    CANCELED = "canceled"    # 已撤单
    REJECTED = "rejected"    # 被拒绝
    EXPIRED = "expired"      # 过期未成交
    ERROR = "error"          # 异常
