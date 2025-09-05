# -*- coding: utf-8 -*-
"""
交易量异常检测服务
Volume Anomaly Detection Service - 检测成交量异常并提供决策权重调整
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.exchanges.exchange_service_manager import get_exchange_service

logger = get_logger(__name__)
settings = get_settings()


class VolumeAnomalyLevel(Enum):
    """交易量异常级别"""
    NORMAL = "normal"           # 正常
    MODERATE = "moderate"       # 中等异常 (2-3倍)
    HIGH = "high"              # 高异常 (3-5倍)
    EXTREME = "extreme"        # 极端异常 (>5倍)


@dataclass
class VolumeAnomalyData:
    """交易量异常数据"""
    symbol: str
    current_volume: float
    avg_volume_24h: float
    volume_ratio: float
    anomaly_level: VolumeAnomalyLevel
    price_change_24h: float
    confidence_boost: float  # 置信度提升因子
    timestamp: datetime
    
    def is_bullish_anomaly(self) -> bool:
        """判断是否为看涨异常（放量上涨）"""
        return self.price_change_24h > 0 and self.volume_ratio > 2.0
    
    def is_bearish_anomaly(self) -> bool:
        """判断是否为看跌异常（放量下跌）"""
        return self.price_change_24h < 0 and self.volume_ratio > 2.0


class VolumeAnomalyService:
    """交易量异常检测服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.exchange_service = None  # 将在需要时异步初始化
        
        # 异常检测配置
        self.anomaly_config = {
            'moderate_threshold': 2.0,    # 2倍平均量
            'high_threshold': 3.0,        # 3倍平均量
            'extreme_threshold': 5.0,     # 5倍平均量
            'lookback_hours': 24,         # 回看24小时
            'min_volume_usdt': 1000000,   # 最小成交量100万USDT
        }
        
        # 置信度提升配置
        self.confidence_boost_config = {
            VolumeAnomalyLevel.NORMAL: 0.0,
            VolumeAnomalyLevel.MODERATE: 0.05,  # 提升5%
            VolumeAnomalyLevel.HIGH: 0.10,      # 提升10%
            VolumeAnomalyLevel.EXTREME: 0.15,   # 提升15%
        }
        
        # 缓存
        self._volume_cache = {}
        self._cache_expiry = {}
        self._cache_duration = 300  # 5分钟缓存
    
    async def detect_volume_anomaly(self, symbol: str) -> Optional[VolumeAnomalyData]:
        """
        检测单个交易对的交易量异常
        
        Args:
            symbol: 交易对符号
            
        Returns:
            VolumeAnomalyData: 异常数据，如果无异常返回None
        """
        try:
            # 检查缓存
            cache_key = f"volume_anomaly_{symbol}"
            if self._is_cache_valid(cache_key):
                return self._volume_cache.get(cache_key)
            
            # 确保交易所服务已初始化
            if self.exchange_service is None:
                self.exchange_service = await get_exchange_service()
            
            # 获取K线数据
            klines = await self.exchange_service.get_kline_data(
                symbol=symbol,
                timeframe='1h',
                limit=48  # 48小时数据
            )
            
            if not klines or len(klines) < 24:
                self.logger.warning(f"⚠️ {symbol} K线数据不足，无法检测交易量异常")
                return None
            
            # 计算交易量统计
            volumes = [float(kline.get('volume', 0)) for kline in klines]
            current_volume = volumes[-1]  # 最新1小时成交量
            
            # 计算24小时平均成交量（排除最新1小时）
            avg_volume_24h = np.mean(volumes[-25:-1]) if len(volumes) >= 25 else np.mean(volumes[:-1])
            
            # 计算成交量比率
            volume_ratio = current_volume / avg_volume_24h if avg_volume_24h > 0 else 1.0
            
            # 获取价格变化
            current_price = float(klines[-1].get('close', 0))
            price_24h_ago = float(klines[-24].get('close', current_price)) if len(klines) >= 24 else current_price
            price_change_24h = ((current_price - price_24h_ago) / price_24h_ago * 100) if price_24h_ago > 0 else 0
            
            # 判断异常级别
            anomaly_level = self._determine_anomaly_level(volume_ratio, current_volume)
            
            # 计算置信度提升因子
            confidence_boost = self._calculate_confidence_boost(anomaly_level, price_change_24h, volume_ratio)
            
            # 创建异常数据
            anomaly_data = VolumeAnomalyData(
                symbol=symbol,
                current_volume=current_volume,
                avg_volume_24h=avg_volume_24h,
                volume_ratio=volume_ratio,
                anomaly_level=anomaly_level,
                price_change_24h=price_change_24h,
                confidence_boost=confidence_boost,
                timestamp=datetime.now()
            )
            
            # 更新缓存
            self._volume_cache[cache_key] = anomaly_data
            self._cache_expiry[cache_key] = datetime.now() + timedelta(seconds=self._cache_duration)
            
            # 记录异常情况
            if anomaly_level != VolumeAnomalyLevel.NORMAL:
                direction = "📈" if price_change_24h > 0 else "📉" if price_change_24h < 0 else "➖"
                self.logger.info(
                    f"🔊 {symbol} 交易量异常: {volume_ratio:.2f}倍 ({anomaly_level.value}) "
                    f"{direction} 价格变化: {price_change_24h:+.2f}% "
                    f"置信度提升: +{confidence_boost:.1%}"
                )
            
            return anomaly_data
            
        except Exception as e:
            self.logger.error(f"❌ 检测 {symbol} 交易量异常失败: {e}")
            return None
    
    async def batch_detect_anomalies(self, symbols: List[str]) -> Dict[str, Optional[VolumeAnomalyData]]:
        """
        批量检测交易量异常
        
        Args:
            symbols: 交易对列表
            
        Returns:
            Dict[str, VolumeAnomalyData]: 异常数据字典
        """
        try:
            self.logger.info(f"🔍 开始批量检测交易量异常: {len(symbols)} 个交易对")
            
            # 并发检测
            tasks = [self.detect_volume_anomaly(symbol) for symbol in symbols]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            anomaly_results = {}
            anomaly_count = 0
            
            for i, result in enumerate(results):
                symbol = symbols[i]
                if isinstance(result, Exception):
                    self.logger.error(f"❌ 检测 {symbol} 异常失败: {result}")
                    anomaly_results[symbol] = None
                else:
                    anomaly_results[symbol] = result
                    if result and result.anomaly_level != VolumeAnomalyLevel.NORMAL:
                        anomaly_count += 1
            
            self.logger.info(f"✅ 批量异常检测完成: 发现 {anomaly_count} 个异常")
            return anomaly_results
            
        except Exception as e:
            self.logger.error(f"❌ 批量检测交易量异常失败: {e}")
            return {}
    
    def _determine_anomaly_level(self, volume_ratio: float, current_volume: float) -> VolumeAnomalyLevel:
        """确定异常级别"""
        # 检查最小成交量要求
        if current_volume < self.anomaly_config['min_volume_usdt']:
            return VolumeAnomalyLevel.NORMAL
        
        # 根据倍数确定级别
        if volume_ratio >= self.anomaly_config['extreme_threshold']:
            return VolumeAnomalyLevel.EXTREME
        elif volume_ratio >= self.anomaly_config['high_threshold']:
            return VolumeAnomalyLevel.HIGH
        elif volume_ratio >= self.anomaly_config['moderate_threshold']:
            return VolumeAnomalyLevel.MODERATE
        else:
            return VolumeAnomalyLevel.NORMAL
    
    def _calculate_confidence_boost(self, anomaly_level: VolumeAnomalyLevel, 
                                  price_change: float, volume_ratio: float) -> float:
        """
        计算置信度提升因子
        
        Args:
            anomaly_level: 异常级别
            price_change: 价格变化百分比
            volume_ratio: 成交量比率
            
        Returns:
            float: 置信度提升因子 (0-0.2)
        """
        base_boost = self.confidence_boost_config.get(anomaly_level, 0.0)
        
        # 根据价格方向调整
        if anomaly_level != VolumeAnomalyLevel.NORMAL:
            # 放量上涨：额外提升
            if price_change > 2.0:  # 上涨超过2%
                base_boost *= 1.2
            # 放量下跌：降低提升（但仍有提升，因为可能是抄底机会）
            elif price_change < -2.0:  # 下跌超过2%
                base_boost *= 0.8
            
            # 极端放量额外奖励
            if volume_ratio > 10.0:
                base_boost *= 1.1
        
        return min(base_boost, 0.2)  # 最大提升20%
    
    def get_volume_confidence_adjustment(self, symbol: str, signal_action: str) -> float:
        """
        获取基于交易量异常的置信度调整
        
        Args:
            symbol: 交易对
            signal_action: 信号动作 (BUY/SELL/HOLD)
            
        Returns:
            float: 置信度调整值 (-0.1 到 +0.2)
        """
        try:
            cache_key = f"volume_anomaly_{symbol}"
            anomaly_data = self._volume_cache.get(cache_key)
            
            if not anomaly_data or anomaly_data.anomaly_level == VolumeAnomalyLevel.NORMAL:
                return 0.0
            
            # 根据信号方向和异常类型调整
            if signal_action.upper() in ['BUY', 'LONG', '买入']:
                if anomaly_data.is_bullish_anomaly():
                    # 放量上涨 + 买入信号 = 正向调整
                    return anomaly_data.confidence_boost
                elif anomaly_data.is_bearish_anomaly():
                    # 放量下跌 + 买入信号 = 可能是抄底，小幅正向调整
                    return anomaly_data.confidence_boost * 0.5
            
            elif signal_action.upper() in ['SELL', 'SHORT', '卖出']:
                if anomaly_data.is_bearish_anomaly():
                    # 放量下跌 + 卖出信号 = 正向调整
                    return anomaly_data.confidence_boost
                elif anomaly_data.is_bullish_anomaly():
                    # 放量上涨 + 卖出信号 = 负向调整（逆势）
                    return -anomaly_data.confidence_boost * 0.3
            
            return 0.0
            
        except Exception as e:
            self.logger.error(f"❌ 获取 {symbol} 交易量置信度调整失败: {e}")
            return 0.0
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """检查缓存是否有效"""
        if cache_key not in self._cache_expiry:
            return False
        return datetime.now() < self._cache_expiry[cache_key]
    
    async def get_anomaly_summary(self, symbols: List[str]) -> Dict[str, Any]:
        """获取异常检测摘要"""
        try:
            anomalies = await self.batch_detect_anomalies(symbols)
            
            summary = {
                'timestamp': datetime.now(),
                'total_symbols': len(symbols),
                'anomalies_found': 0,
                'by_level': {level.value: 0 for level in VolumeAnomalyLevel},
                'bullish_anomalies': 0,
                'bearish_anomalies': 0,
                'top_anomalies': []
            }
            
            # 统计异常
            valid_anomalies = []
            for symbol, anomaly in anomalies.items():
                if anomaly and anomaly.anomaly_level != VolumeAnomalyLevel.NORMAL:
                    summary['anomalies_found'] += 1
                    summary['by_level'][anomaly.anomaly_level.value] += 1
                    
                    if anomaly.is_bullish_anomaly():
                        summary['bullish_anomalies'] += 1
                    elif anomaly.is_bearish_anomaly():
                        summary['bearish_anomalies'] += 1
                    
                    valid_anomalies.append(anomaly)
            
            # 排序并获取前5个异常
            valid_anomalies.sort(key=lambda x: x.volume_ratio, reverse=True)
            summary['top_anomalies'] = [
                {
                    'symbol': a.symbol,
                    'volume_ratio': a.volume_ratio,
                    'price_change_24h': a.price_change_24h,
                    'anomaly_level': a.anomaly_level.value,
                    'confidence_boost': a.confidence_boost
                }
                for a in valid_anomalies[:5]
            ]
            
            return summary
            
        except Exception as e:
            self.logger.error(f"❌ 获取异常检测摘要失败: {e}")
            return {
                'timestamp': datetime.now(),
                'error': str(e),
                'total_symbols': len(symbols),
                'anomalies_found': 0
            }


# 全局服务实例
_volume_anomaly_service = None


def get_volume_anomaly_service() -> VolumeAnomalyService:
    """获取交易量异常检测服务实例"""
    global _volume_anomaly_service
    if _volume_anomaly_service is None:
        _volume_anomaly_service = VolumeAnomalyService()
    return _volume_anomaly_service