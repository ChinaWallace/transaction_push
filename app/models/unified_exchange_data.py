# -*- coding: utf-8 -*-
"""
统一交易所数据模型
Unified exchange data models for cross-exchange compatibility
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from decimal import Decimal

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class UnifiedInstrument:
    """
    统一的交易对数据模型
    Unified trading instrument data model
    
    统一不同交易所的交易对格式，确保所有业务服务使用相同的数据结构
    """
    instId: str              # 统一交易对ID (BTC-USDT-SWAP)
    instType: str            # 交易对类型 (SWAP, SPOT, FUTURES)
    baseCcy: str             # 基础货币 (BTC)
    quoteCcy: str            # 计价货币 (USDT)
    settleCcy: str           # 结算货币 (USDT)
    ctVal: str               # 合约面值
    ctMult: str              # 合约乘数
    ctValCcy: str            # 合约面值货币
    minSz: str               # 最小下单数量
    lotSz: str               # 下单数量精度
    tickSz: str              # 价格精度
    state: str               # 状态 (live/suspend)
    listTime: str            # 上线时间
    expTime: str             # 到期时间
    source: str              # 数据源 (binance/okx)
    
    # 原始数据保留
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """数据验证和标准化"""
        # 确保状态值标准化
        if self.state.lower() in ['trading', 'active']:
            self.state = 'live'
        elif self.state.lower() in ['break', 'suspend', 'inactive']:
            self.state = 'suspend'
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，用于向后兼容"""
        return {
            'instId': self.instId,
            'instType': self.instType,
            'baseCcy': self.baseCcy,
            'quoteCcy': self.quoteCcy,
            'settleCcy': self.settleCcy,
            'ctVal': self.ctVal,
            'ctMult': self.ctMult,
            'ctValCcy': self.ctValCcy,
            'minSz': self.minSz,
            'lotSz': self.lotSz,
            'tickSz': self.tickSz,
            'state': self.state,
            'listTime': self.listTime,
            'expTime': self.expTime,
            'source': self.source
        }
    
    @property
    def is_active(self) -> bool:
        """是否为活跃状态"""
        return self.state == 'live'
    
    @property
    def is_usdt_perpetual(self) -> bool:
        """是否为USDT永续合约"""
        return (self.instType == 'SWAP' and 
                self.quoteCcy == 'USDT' and 
                self.settleCcy == 'USDT')


@dataclass
class UnifiedTicker:
    """
    统一的Ticker数据模型
    Unified ticker data model
    """
    instId: str
    last: str           # 最新价格
    lastSz: str         # 最新成交量
    askPx: str          # 卖一价
    askSz: str          # 卖一量
    bidPx: str          # 买一价
    bidSz: str          # 买一量
    open24h: str        # 24小时开盘价
    high24h: str        # 24小时最高价
    low24h: str         # 24小时最低价
    vol24h: str         # 24小时成交量
    volCcy24h: str      # 24小时成交额
    ts: str             # 时间戳
    source: str         # 数据源
    
    # 原始数据保留
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'instId': self.instId,
            'last': self.last,
            'lastSz': self.lastSz,
            'askPx': self.askPx,
            'askSz': self.askSz,
            'bidPx': self.bidPx,
            'bidSz': self.bidSz,
            'open24h': self.open24h,
            'high24h': self.high24h,
            'low24h': self.low24h,
            'vol24h': self.vol24h,
            'volCcy24h': self.volCcy24h,
            'ts': self.ts,
            'source': self.source
        }
    
    @property
    def price_change_24h(self) -> Optional[Decimal]:
        """24小时价格变化"""
        try:
            if self.last and self.open24h:
                return Decimal(self.last) - Decimal(self.open24h)
        except (ValueError, TypeError):
            pass
        return None
    
    @property
    def price_change_percent_24h(self) -> Optional[Decimal]:
        """24小时价格变化百分比"""
        try:
            if self.last and self.open24h:
                last_price = Decimal(self.last)
                open_price = Decimal(self.open24h)
                if open_price != 0:
                    return ((last_price - open_price) / open_price) * 100
        except (ValueError, TypeError):
            pass
        return None


@dataclass
class UnifiedFundingRate:
    """
    统一的资金费率数据模型
    Unified funding rate data model
    """
    instId: str
    fundingRate: str    # 资金费率
    nextFundingTime: str # 下次费率时间
    fundingTime: str    # 当前费率时间
    source: str         # 数据源
    
    # 原始数据保留
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'instId': self.instId,
            'symbol': self.instId,  # 为向后兼容添加symbol字段
            'fundingRate': self.fundingRate,
            'funding_rate': float(self.fundingRate) if self.fundingRate else 0.0,  # 为向后兼容添加数值字段
            'nextFundingTime': self.nextFundingTime,
            'fundingTime': self.fundingTime,
            'source': self.source
        }
    
    @property
    def is_negative(self) -> bool:
        """是否为负费率"""
        try:
            return Decimal(self.fundingRate) < 0
        except (ValueError, TypeError):
            return False
    
    @property
    def rate_percentage(self) -> Optional[Decimal]:
        """费率百分比"""
        try:
            return Decimal(self.fundingRate) * 100
        except (ValueError, TypeError):
            return None


@dataclass
class UnifiedPosition:
    """
    统一的持仓数据模型
    Unified position data model
    """
    instId: str
    posSide: str        # 持仓方向 (long/short/net)
    pos: str            # 持仓数量
    posNotional: str    # 持仓名义价值
    avgPx: str          # 平均价格
    upl: str            # 未实现盈亏
    uplRatio: str       # 未实现盈亏比例
    margin: str         # 保证金
    source: str         # 数据源
    
    # 原始数据保留
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            'instId': self.instId,
            'symbol': self.instId,  # 为向后兼容添加symbol字段
            'posSide': self.posSide,
            'pos': self.pos,
            'posNotional': self.posNotional,
            'avgPx': self.avgPx,
            'upl': self.upl,
            'uplRatio': self.uplRatio,
            'margin': self.margin,
            'source': self.source,
            # 添加数值格式的字段用于计算
            'position_size': self._safe_float(self.pos),
            'size': self._safe_float(self.pos),  # 为向后兼容添加size字段
            'position_value': self._safe_float(self.posNotional),
            'position_value_usd': self._safe_float(self.posNotional),  # 为向后兼容添加position_value_usd字段
            'avg_price': self._safe_float(self.avgPx),
            'unrealized_pnl': self._safe_float(self.upl),
            'margin_amount': self._safe_float(self.margin)
        }
        
        # 从原始数据中提取额外信息
        if self.raw_data:
            # 优先使用原始数据中的mark_price
            mark_price = self.raw_data.get('mark_price', self.raw_data.get('markPx', 0))
            result['mark_price'] = float(mark_price) if mark_price else self._safe_float(self.avgPx)
            
            # 优先使用原始数据中的position_value_usd
            if 'position_value_usd' in self.raw_data:
                result['position_value_usd'] = float(self.raw_data['position_value_usd'])
                result['position_value'] = float(self.raw_data['position_value_usd'])
        else:
            # 回退到平均价格作为市场价格
            result['mark_price'] = self._safe_float(self.avgPx)
        
        return result
    
    def _safe_float(self, value: str) -> float:
        """安全转换字符串为浮点数"""
        try:
            return float(value) if value else 0.0
        except (ValueError, TypeError):
            return 0.0
    
    @property
    def has_position(self) -> bool:
        """是否有持仓"""
        try:
            return Decimal(self.pos) != 0
        except (ValueError, TypeError):
            return False
    
    @property
    def is_profitable(self) -> bool:
        """是否盈利"""
        try:
            return Decimal(self.upl) > 0
        except (ValueError, TypeError):
            return False


# 数据适配异常类
from app.utils.exceptions import TradingToolError, ErrorSeverity, RecoveryAction

class DataAdaptationError(TradingToolError):
    """
    数据适配异常基类
    Data adaptation exception base class
    """
    
    def __init__(
        self, 
        message: str, 
        error_code: str = None, 
        details: dict = None,
        exchange_name: str = None,
        data_type: str = None
    ):
        super().__init__(
            message=message,
            error_code=error_code or "DATA_ADAPTATION_ERROR",
            details=details or {},
            severity=ErrorSeverity.MEDIUM,
            recovery_actions=[RecoveryAction.RETRY, RecoveryAction.CHECK_CONFIG],
            context={
                "exchange_name": exchange_name,
                "data_type": data_type
            }
        )
        self.exchange_name = exchange_name
        self.data_type = data_type


class FieldMappingError(DataAdaptationError):
    """
    字段映射异常
    Field mapping exception
    """
    
    def __init__(
        self, 
        message: str, 
        missing_fields: list = None,
        exchange_name: str = None,
        data_type: str = None
    ):
        details = {
            "missing_fields": missing_fields or [],
            "field_count": len(missing_fields) if missing_fields else 0
        }
        
        super().__init__(
            message=message,
            error_code="FIELD_MAPPING_ERROR",
            details=details,
            exchange_name=exchange_name,
            data_type=data_type
        )
        self.missing_fields = missing_fields or []


class DataValidationError(DataAdaptationError):
    """
    数据验证异常
    Data validation exception
    """
    
    def __init__(
        self, 
        message: str, 
        validation_errors: list = None,
        exchange_name: str = None,
        data_type: str = None
    ):
        details = {
            "validation_errors": validation_errors or [],
            "error_count": len(validation_errors) if validation_errors else 0
        }
        
        super().__init__(
            message=message,
            error_code="DATA_VALIDATION_ERROR",
            details=details,
            exchange_name=exchange_name,
            data_type=data_type
        )
        self.validation_errors = validation_errors or []


class DataTransformationError(DataAdaptationError):
    """
    数据转换异常
    Data transformation exception
    """
    
    def __init__(
        self, 
        message: str, 
        source_format: str = None,
        target_format: str = None,
        exchange_name: str = None,
        data_type: str = None
    ):
        details = {
            "source_format": source_format,
            "target_format": target_format,
            "transformation_type": f"{source_format} -> {target_format}" if source_format and target_format else None
        }
        
        super().__init__(
            message=message,
            error_code="DATA_TRANSFORMATION_ERROR",
            details=details,
            exchange_name=exchange_name,
            data_type=data_type
        )
        self.source_format = source_format
        self.target_format = target_format


# 数据验证函数
def validate_unified_instrument(instrument: UnifiedInstrument) -> bool:
    """
    验证统一交易对数据的完整性
    Validate unified instrument data integrity
    """
    required_fields = ['instId', 'instType', 'baseCcy', 'quoteCcy', 'state']
    
    for field in required_fields:
        value = getattr(instrument, field, None)
        if not value or not isinstance(value, str):
            logger.warning(f"⚠️ 交易对数据验证失败: {field} 字段无效")
            return False
    
    # 验证交易对ID格式
    if not instrument.instId or len(instrument.instId) < 3:
        logger.warning(f"⚠️ 交易对ID格式无效: {instrument.instId}")
        return False
    
    return True


def sanitize_instrument_data(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    清理交易对原始数据中的敏感信息
    Sanitize sensitive information in raw instrument data
    """
    sensitive_keys = ["api_key", "secret", "passphrase", "signature", "timestamp"]
    sanitized = raw_data.copy()
    
    for key in sensitive_keys:
        if key in sanitized:
            sanitized[key] = "***HIDDEN***"
    
    return sanitized