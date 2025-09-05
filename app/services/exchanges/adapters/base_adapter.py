# -*- coding: utf-8 -*-
"""
交易所数据适配器基类
Base exchange data adapter
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
from datetime import datetime
from decimal import Decimal
import decimal

from app.core.logging import get_logger
from app.models.unified_exchange_data import (
    UnifiedInstrument, UnifiedTicker, UnifiedFundingRate, UnifiedPosition,
    DataAdaptationError, FieldMappingError, DataValidationError
)

logger = get_logger(__name__)


class ExchangeDataAdapter(ABC):
    """
    交易所数据适配器抽象基类
    Abstract base class for exchange data adapters
    
    定义了将不同交易所的原始数据转换为统一格式的标准接口
    """
    
    def __init__(self, exchange_name: str):
        """
        初始化适配器
        Initialize adapter
        
        Args:
            exchange_name: 交易所名称 / Exchange name
        """
        self.exchange_name = exchange_name.lower()
        self._cache = {}  # 简单缓存机制
        logger.debug(f"🔧 初始化 {exchange_name} 数据适配器")
    
    @abstractmethod
    def adapt_instruments(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedInstrument]:
        """
        适配交易对数据
        Adapt trading instruments data
        
        Args:
            raw_data: 交易所原始交易对数据 / Raw instruments data from exchange
            
        Returns:
            List[UnifiedInstrument]: 统一格式的交易对数据列表
            
        Raises:
            DataAdaptationError: 数据适配失败时抛出
        """
    
    @abstractmethod
    def adapt_ticker(self, raw_data: Dict[str, Any]) -> UnifiedTicker:
        """
        适配ticker数据
        Adapt ticker data
        
        Args:
            raw_data: 交易所原始ticker数据 / Raw ticker data from exchange
            
        Returns:
            UnifiedTicker: 统一格式的ticker数据
            
        Raises:
            DataAdaptationError: 数据适配失败时抛出
        """
    
    @abstractmethod
    def adapt_tickers(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedTicker]:
        """
        批量适配ticker数据
        Batch adapt ticker data
        
        Args:
            raw_data: 交易所原始ticker数据列表 / Raw ticker data list from exchange
            
        Returns:
            List[UnifiedTicker]: 统一格式的ticker数据列表
        """
    
    @abstractmethod
    def adapt_funding_rate(self, raw_data: Dict[str, Any]) -> UnifiedFundingRate:
        """
        适配资金费率数据
        Adapt funding rate data
        
        Args:
            raw_data: 交易所原始资金费率数据 / Raw funding rate data from exchange
            
        Returns:
            UnifiedFundingRate: 统一格式的资金费率数据
            
        Raises:
            DataAdaptationError: 数据适配失败时抛出
        """
    
    @abstractmethod
    def adapt_funding_rates(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedFundingRate]:
        """
        批量适配资金费率数据
        Batch adapt funding rate data
        
        Args:
            raw_data: 交易所原始资金费率数据列表 / Raw funding rate data list from exchange
            
        Returns:
            List[UnifiedFundingRate]: 统一格式的资金费率数据列表
        """
    
    @abstractmethod
    def adapt_position(self, raw_data: Dict[str, Any]) -> UnifiedPosition:
        """
        适配持仓数据
        Adapt position data
        
        Args:
            raw_data: 交易所原始持仓数据 / Raw position data from exchange
            
        Returns:
            UnifiedPosition: 统一格式的持仓数据
            
        Raises:
            DataAdaptationError: 数据适配失败时抛出
        """
    
    @abstractmethod
    def adapt_positions(self, raw_data: List[Dict[str, Any]]) -> List[UnifiedPosition]:
        """
        批量适配持仓数据
        Batch adapt position data
        
        Args:
            raw_data: 交易所原始持仓数据列表 / Raw position data list from exchange
            
        Returns:
            List[UnifiedPosition]: 统一格式的持仓数据列表
        """
    
    # 辅助方法
    def _safe_get(self, data: Dict[str, Any], key: str, default: str = "") -> str:
        """
        安全获取字典值并转换为字符串
        Safely get dictionary value and convert to string
        """
        try:
            value = data.get(key, default)
            return str(value) if value is not None else default
        except Exception as e:
            logger.warning(f"⚠️ 获取字段 {key} 失败: {e}")
            return default
    
    def _safe_get_float(self, data: Dict[str, Any], key: str, default: float = 0.0) -> str:
        """
        安全获取数值并转换为字符串
        Safely get numeric value and convert to string
        """
        try:
            value = data.get(key, default)
            if value is None:
                return str(default)
            return str(float(value))
        except (ValueError, TypeError) as e:
            logger.warning(f"⚠️ 转换数值字段 {key} 失败: {e}")
            return str(default)
    
    def _safe_get_timestamp(self, data: Dict[str, Any], key: str, default: str = "") -> str:
        """
        安全获取时间戳并标准化格式
        Safely get timestamp and normalize format
        """
        try:
            value = data.get(key, default)
            if not value:
                return default
            
            # 如果是数字时间戳，转换为毫秒
            if isinstance(value, (int, float)):
                # 判断是秒还是毫秒时间戳
                if value < 10000000000:  # 秒时间戳
                    value = int(value * 1000)
                return str(int(value))
            
            # 如果是字符串，直接返回
            return str(value)
        except Exception as e:
            logger.warning(f"⚠️ 处理时间戳字段 {key} 失败: {e}")
            return default
    
    def _normalize_symbol(self, raw_symbol: str, exchange_format: str = None) -> str:
        """
        标准化交易对符号格式
        Normalize trading pair symbol format
        
        Args:
            raw_symbol: 原始交易对符号
            exchange_format: 交易所格式标识
            
        Returns:
            str: 标准化的交易对符号 (BTC-USDT-SWAP)
        """
        try:
            if not raw_symbol:
                return ""
            
            # 移除空格和转换为大写
            symbol = raw_symbol.strip().upper()
            
            # 如果已经是标准格式，直接返回
            if '-' in symbol and symbol.endswith('-SWAP'):
                return symbol
            
            # 根据交易所格式进行转换
            if exchange_format == 'binance':
                # 币安格式: BTCUSDT -> BTC-USDT-SWAP
                if symbol.endswith('USDT') and len(symbol) > 4:
                    base = symbol[:-4]
                    return f"{base}-USDT-SWAP"
            elif exchange_format == 'okx':
                # OKX格式: BTC-USDT-SWAP -> 保持不变
                return symbol
            
            # 默认处理：尝试识别USDT结尾的交易对
            if symbol.endswith('USDT') and len(symbol) > 4:
                base = symbol[:-4]
                return f"{base}-USDT-SWAP"
            
            return symbol
            
        except Exception as e:
            logger.warning(f"⚠️ 标准化交易对符号失败: {raw_symbol} -> {e}")
            return raw_symbol
    
    def _normalize_state(self, raw_state: str) -> str:
        """
        标准化状态值
        Normalize state value
        """
        if not raw_state:
            return "suspend"
        
        state = raw_state.lower().strip()
        
        # 活跃状态映射
        if state in ['trading', 'active', 'live', 'online']:
            return 'live'
        # 暂停状态映射
        elif state in ['break', 'suspend', 'inactive', 'offline', 'pause']:
            return 'suspend'
        else:
            # 默认为暂停状态
            return 'suspend'
    
    def _validate_required_fields(self, data: Dict[str, Any], required_fields: List[str], 
                                 data_type: str = "data") -> None:
        """
        验证必需字段
        Validate required fields
        
        Args:
            data: 数据字典
            required_fields: 必需字段列表
            data_type: 数据类型描述
            
        Raises:
            FieldMappingError: 缺少必需字段时抛出
        """
        missing_fields = []
        for field in required_fields:
            if field not in data or data[field] is None:
                missing_fields.append(field)
        
        if missing_fields:
            raise FieldMappingError(
                f"{data_type} 缺少必需字段: {missing_fields}",
                missing_fields=missing_fields,
                exchange_name=self.exchange_name,
                data_type=data_type
            )
    
    def _handle_adaptation_error(self, error: Exception, data_type: str, 
                               raw_data: Dict[str, Any] = None) -> None:
        """
        统一处理适配错误
        Handle adaptation errors uniformly
        
        Args:
            error: 原始异常
            data_type: 数据类型
            raw_data: 原始数据（可选）
        """
        error_details = {
            "error_type": type(error).__name__,
            "error_message": str(error)
        }
        
        if raw_data:
            # 只记录关键字段，避免日志过长
            key_fields = ["symbol", "instId", "status", "state", "baseAsset", "quoteAsset"]
            error_details["raw_data_sample"] = {
                k: v for k, v in raw_data.items() 
                if k in key_fields and v is not None
            }
        
        logger.error(f"❌ {self.exchange_name} {data_type}数据适配失败: {error}")
        
        # 重新抛出为统一的适配异常
        if isinstance(error, DataAdaptationError):
            # 如果已经是数据适配异常，更新上下文信息
            if not error.exchange_name:
                error.exchange_name = self.exchange_name
            if not error.data_type:
                error.data_type = data_type
            error.details.update(error_details)
            raise error
        else:
            # 转换为数据适配异常
            raise DataAdaptationError(
                f"{data_type}数据适配失败: {str(error)}",
                exchange_name=self.exchange_name,
                data_type=data_type
            )
    
    def _validate_and_set_defaults(self, data: Dict[str, Any], field_defaults: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证数据并设置默认值
        Validate data and set default values
        
        Args:
            data: 原始数据
            field_defaults: 字段默认值映射
            
        Returns:
            Dict: 处理后的数据
        """
        processed_data = data.copy()
        validation_errors = []
        
        for field, default_value in field_defaults.items():
            if field not in processed_data or processed_data[field] is None:
                processed_data[field] = default_value
                logger.debug(f"🔧 设置默认值: {field} = {default_value}")
            elif isinstance(default_value, str) and not isinstance(processed_data[field], str):
                # 类型转换
                try:
                    processed_data[field] = str(processed_data[field])
                except (ValueError, TypeError) as e:
                    validation_errors.append(f"字段 {field} 类型转换失败: {e}")
        
        if validation_errors:
            raise DataValidationError(
                f"数据验证失败: {', '.join(validation_errors)}",
                validation_errors=validation_errors,
                exchange_name=self.exchange_name
            )
        
        return processed_data
    
    def _safe_decimal_convert(self, value: Any, field_name: str, default: str = "0") -> str:
        """
        安全的数值转换
        Safe decimal conversion
        
        Args:
            value: 要转换的值
            field_name: 字段名称
            default: 默认值
            
        Returns:
            str: 转换后的字符串数值
        """
        if value is None or value == "":
            return default
        
        try:
            # 尝试转换为Decimal再转为字符串，确保格式正确
            decimal_value = Decimal(str(value))
            return str(decimal_value)
        except (ValueError, TypeError, decimal.InvalidOperation) as e:
            logger.warning(f"⚠️ 数值转换失败 {field_name}={value}: {e}，使用默认值 {default}")
            return default
    
    def _safe_timestamp_convert(self, timestamp: Any, field_name: str, default: str = "") -> str:
        """
        安全的时间戳转换
        Safe timestamp conversion
        
        Args:
            timestamp: 时间戳值
            field_name: 字段名称
            default: 默认值
            
        Returns:
            str: ISO格式的时间字符串
        """
        if timestamp is None or timestamp == "":
            return default
        
        try:
            # 如果是数字，假设是毫秒时间戳
            if isinstance(timestamp, (int, float)):
                # 如果是秒级时间戳，转换为毫秒
                if timestamp < 10000000000:  # 小于这个值认为是秒级
                    timestamp = timestamp * 1000
                dt = datetime.fromtimestamp(timestamp / 1000)
                return dt.isoformat()
            
            # 如果是字符串，尝试解析
            elif isinstance(timestamp, str):
                # 尝试解析ISO格式
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    return dt.isoformat()
                except ValueError:
                    # 尝试解析为数字
                    numeric_timestamp = float(timestamp)
                    return self._safe_timestamp_convert(numeric_timestamp, field_name, default)
            
            else:
                logger.warning(f"⚠️ 不支持的时间戳格式 {field_name}={timestamp}，使用默认值")
                return default
                
        except (ValueError, TypeError, OSError) as e:
            logger.warning(f"⚠️ 时间戳转换失败 {field_name}={timestamp}: {e}，使用默认值 {default}")
            return default
    
    def get_adapter_info(self) -> Dict[str, Any]:
        """
        获取适配器信息
        Get adapter information
        """
        return {
            "exchange_name": self.exchange_name,
            "adapter_class": self.__class__.__name__,
            "cache_size": len(self._cache),
            "supported_data_types": [
                "instruments", "ticker", "funding_rate", "position"
            ],
            "error_handling": {
                "supports_validation": True,
                "supports_defaults": True,
                "supports_type_conversion": True
            }
        }