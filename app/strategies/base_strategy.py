# -*- coding: utf-8 -*-
"""
基础策略类
Base strategy class inspired by freqtrade architecture
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import pandas as pd

from app.core.logging import get_logger
from app.utils.exceptions import ValidationError

logger = get_logger(__name__)


class SignalType(Enum):
    """信号类型"""
    BUY = "buy"
    SELL = "sell" 
    HOLD = "hold"
    STRONG_BUY = "strong_buy"
    STRONG_SELL = "strong_sell"


class SignalStrength(Enum):
    """信号强度"""
    VERY_STRONG = 5
    STRONG = 4
    MEDIUM = 3
    WEAK = 2
    VERY_WEAK = 1


@dataclass
class StrategySignal:
    """策略信号"""
    signal_type: SignalType
    strength: SignalStrength
    confidence: float  # 0-1
    price: float
    timestamp: datetime
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'signal_type': self.signal_type.value,
            'strength': self.strength.value,
            'confidence': self.confidence,
            'price': self.price,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata
        }


@dataclass
class MarketData:
    """市场数据"""
    symbol: str
    timeframe: str
    ohlcv: pd.DataFrame  # OHLCV数据
    indicators: Dict[str, pd.Series]  # 技术指标
    metadata: Dict[str, Any]


class BaseStrategy(ABC):
    """
    基础策略类
    所有策略都应该继承此类并实现必要的方法
    """
    
    def __init__(self, name: str, config: Dict[str, Any] = None):
        self.name = name
        self.config = config or {}
        self.logger = get_logger(f"strategy.{name}")
        
        # 策略参数
        self.timeframes = self.config.get('timeframes', ['1h'])
        self.min_data_points = self.config.get('min_data_points', 100)
        
        # 验证配置
        self._validate_config()
    
    def _validate_config(self):
        """验证策略配置"""
        required_params = self.get_required_params()
        for param in required_params:
            if param not in self.config:
                raise ValidationError(f"Missing required parameter: {param}")
    
    @abstractmethod
    def get_required_params(self) -> List[str]:
        """获取必需参数列表"""
        pass
    
    @abstractmethod
    def populate_indicators(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        填充技术指标
        
        Args:
            dataframe: OHLCV数据框
            
        Returns:
            包含指标的数据框
        """
        pass
    
    @abstractmethod
    def populate_entry_trend(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        填充入场信号
        
        Args:
            dataframe: 包含指标的数据框
            
        Returns:
            包含入场信号的数据框
        """
        pass
    
    @abstractmethod
    def populate_exit_trend(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        填充出场信号
        
        Args:
            dataframe: 包含指标的数据框
            
        Returns:
            包含出场信号的数据框
        """
        pass
    
    def analyze(self, market_data: MarketData) -> StrategySignal:
        """
        分析市场数据并生成信号
        
        Args:
            market_data: 市场数据
            
        Returns:
            策略信号
        """
        try:
            # 验证数据
            if len(market_data.ohlcv) < self.min_data_points:
                raise ValidationError(f"Insufficient data points: {len(market_data.ohlcv)}")
            
            # 复制数据框避免修改原始数据
            df = market_data.ohlcv.copy()
            
            # 填充指标
            df = self.populate_indicators(df)
            
            # 填充信号
            df = self.populate_entry_trend(df)
            df = self.populate_exit_trend(df)
            
            # 生成最终信号
            signal = self._generate_signal(df, market_data)
            
            self.logger.info(f"Generated signal for {market_data.symbol}: {signal.signal_type.value}")
            return signal
            
        except Exception as e:
            self.logger.error(f"Strategy analysis failed for {market_data.symbol}: {e}")
            raise
    
    def _generate_signal(self, dataframe: pd.DataFrame, market_data: MarketData) -> StrategySignal:
        """
        根据数据框生成最终信号
        
        Args:
            dataframe: 包含所有指标和信号的数据框
            market_data: 原始市场数据
            
        Returns:
            策略信号
        """
        # 获取最新数据
        latest = dataframe.iloc[-1]
        
        # 确定信号类型
        if latest.get('enter_long', False):
            signal_type = SignalType.BUY
        elif latest.get('enter_short', False):
            signal_type = SignalType.SELL
        elif latest.get('exit_long', False) or latest.get('exit_short', False):
            signal_type = SignalType.HOLD
        else:
            signal_type = SignalType.HOLD
        
        # 计算信号强度和置信度
        strength, confidence = self._calculate_signal_strength(dataframe)
        
        # 构建元数据
        metadata = {
            'strategy': self.name,
            'symbol': market_data.symbol,
            'timeframe': market_data.timeframe,
            'indicators': self._extract_indicator_values(latest),
            'config': self.config
        }
        
        return StrategySignal(
            signal_type=signal_type,
            strength=strength,
            confidence=confidence,
            price=float(latest['close']),
            timestamp=datetime.now(),
            metadata=metadata
        )
    
    def _calculate_signal_strength(self, dataframe: pd.DataFrame) -> Tuple[SignalStrength, float]:
        """
        计算信号强度和置信度
        子类可以重写此方法实现自定义逻辑
        """
        # 默认实现：基于最近几根K线的信号一致性
        recent_signals = dataframe.tail(5)
        
        # 计算买入信号数量
        buy_signals = recent_signals.get('enter_long', pd.Series([False] * len(recent_signals))).sum()
        sell_signals = recent_signals.get('enter_short', pd.Series([False] * len(recent_signals))).sum()
        
        # 计算强度
        max_signals = len(recent_signals)
        if buy_signals >= max_signals * 0.8:
            strength = SignalStrength.VERY_STRONG
            confidence = 0.9
        elif buy_signals >= max_signals * 0.6:
            strength = SignalStrength.STRONG
            confidence = 0.8
        elif sell_signals >= max_signals * 0.8:
            strength = SignalStrength.VERY_STRONG
            confidence = 0.9
        elif sell_signals >= max_signals * 0.6:
            strength = SignalStrength.STRONG
            confidence = 0.8
        else:
            strength = SignalStrength.MEDIUM
            confidence = 0.5
        
        return strength, confidence
    
    def _extract_indicator_values(self, latest_row: pd.Series) -> Dict[str, Any]:
        """提取指标值"""
        indicators = {}
        
        # 提取常见指标
        for col in latest_row.index:
            if col not in ['open', 'high', 'low', 'close', 'volume']:
                value = latest_row[col]
                if pd.notna(value):
                    indicators[col] = float(value) if isinstance(value, (int, float)) else str(value)
        
        return indicators
    
    def backtest(self, historical_data: List[MarketData]) -> Dict[str, Any]:
        """
        回测策略
        
        Args:
            historical_data: 历史市场数据列表
            
        Returns:
            回测结果
        """
        signals = []
        
        for data in historical_data:
            try:
                signal = self.analyze(data)
                signals.append(signal)
            except Exception as e:
                self.logger.warning(f"Backtest analysis failed for {data.symbol}: {e}")
                continue
        
        # 计算回测统计
        stats = self._calculate_backtest_stats(signals)
        
        return {
            'signals': [s.to_dict() for s in signals],
            'statistics': stats,
            'strategy': self.name,
            'config': self.config
        }
    
    def _calculate_backtest_stats(self, signals: List[StrategySignal]) -> Dict[str, Any]:
        """计算回测统计"""
        if not signals:
            return {}
        
        # 信号类型统计
        signal_counts = {}
        for signal in signals:
            signal_type = signal.signal_type.value
            signal_counts[signal_type] = signal_counts.get(signal_type, 0) + 1
        
        # 平均置信度
        avg_confidence = sum(s.confidence for s in signals) / len(signals)
        
        # 强度分布
        strength_counts = {}
        for signal in signals:
            strength = signal.strength.value
            strength_counts[strength] = strength_counts.get(strength, 0) + 1
        
        return {
            'total_signals': len(signals),
            'signal_distribution': signal_counts,
            'average_confidence': round(avg_confidence, 4),
            'strength_distribution': strength_counts,
            'period': {
                'start': min(s.timestamp for s in signals).isoformat(),
                'end': max(s.timestamp for s in signals).isoformat()
            }
        }
    
    def get_strategy_info(self) -> Dict[str, Any]:
        """获取策略信息"""
        return {
            'name': self.name,
            'config': self.config,
            'timeframes': self.timeframes,
            'required_params': self.get_required_params(),
            'min_data_points': self.min_data_points
        }