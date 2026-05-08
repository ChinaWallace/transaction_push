# -*- coding: utf-8 -*-
"""
详细技术分析服务
Detailed Technical Analysis Service - 提供详细的技术分析构成和占比
"""

from typing import Dict, List, Tuple
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import pandas as pd
import numpy as np

from app.core.logging import get_logger
from app.services.binance_service import BinanceService
from app.utils.indicators import SuperTrendIndicator, MovingAverageIndicator, RSIIndicator, VolumeIndicator

logger = get_logger(__name__)


class IndicatorWeight(Enum):
    """技术指标权重"""
    HIGH = 0.25      # 高权重 25%
    MEDIUM = 0.15    # 中权重 15%
    LOW = 0.10       # 低权重 10%


@dataclass
class IndicatorResult:
    """单个指标结果"""
    name: str
    signal: str  # 'buy', 'sell', 'neutral'
    strength: float  # 0-1 信号强度
    weight: float  # 权重
    value: float  # 指标值
    description: str  # 描述


@dataclass
class TechnicalAnalysisBreakdown:
    """技术分析详细分解"""
    symbol: str
    timestamp: datetime
    
    # 各类指标结果
    trend_indicators: List[IndicatorResult]
    momentum_indicators: List[IndicatorResult]
    volume_indicators: List[IndicatorResult]
    volatility_indicators: List[IndicatorResult]
    
    # 综合评分
    trend_score: float  # 趋势评分 0-100
    momentum_score: float  # 动量评分 0-100
    volume_score: float  # 成交量评分 0-100
    volatility_score: float  # 波动性评分 0-100
    
    # 最终结果
    overall_signal: str
    overall_confidence: float
    weighted_breakdown: Dict[str, float]  # 各类指标的权重占比


class DetailedTechnicalAnalysisService:
    """详细技术分析服务类"""
    
    def __init__(self):
        self.binance_service = BinanceService()
        self.supertrend_indicator = SuperTrendIndicator()
        self.ma_indicator = MovingAverageIndicator()
        self.rsi_indicator = RSIIndicator()
        self.volume_indicator = VolumeIndicator()
        
        # 指标权重配置
        self.indicator_weights = {
            # 趋势指标 (总权重40%)
            'supertrend': IndicatorWeight.HIGH.value,      # 25%
            'ema_cross': IndicatorWeight.MEDIUM.value,     # 15%
            
            # 动量指标 (总权重30%)
            'rsi': IndicatorWeight.MEDIUM.value,           # 15%
            'macd': IndicatorWeight.MEDIUM.value,          # 15%
            
            # 成交量指标 (总权重20%)
            'volume_sma': IndicatorWeight.MEDIUM.value,    # 15%
            'obv': IndicatorWeight.LOW.value,              # 5%
            
            # 波动性指标 (总权重10%)
            'bollinger': IndicatorWeight.LOW.value,        # 10%
        }
    
    async def analyze_symbol_detailed(self, symbol: str) -> TechnicalAnalysisBreakdown:
        """
        详细分析单个交易对
        
        Args:
            symbol: 交易对
            
        Returns:
            详细技术分析结果
        """
        try:
            # 获取多周期数据
            timeframes = ['1d', '4h', '1h', '15m']
            klines_data = await self.binance_service.get_multi_timeframe_klines(
                symbol, timeframes, limit=100
            )
            
            if not klines_data:
                raise ValueError(f"无法获取 {symbol} 的K线数据")
            
            # 分析各类指标
            trend_results = await self._analyze_trend_indicators(symbol, klines_data)
            momentum_results = await self._analyze_momentum_indicators(symbol, klines_data)
            volume_results = await self._analyze_volume_indicators(symbol, klines_data)
            volatility_results = await self._analyze_volatility_indicators(symbol, klines_data)
            
            # 计算各类评分
            trend_score = self._calculate_category_score(trend_results)
            momentum_score = self._calculate_category_score(momentum_results)
            volume_score = self._calculate_category_score(volume_results)
            volatility_score = self._calculate_category_score(volatility_results)
            
            # 计算综合信号
            overall_signal, overall_confidence, weighted_breakdown = self._calculate_overall_signal(
                trend_results, momentum_results, volume_results, volatility_results
            )
            
            return TechnicalAnalysisBreakdown(
                symbol=symbol,
                timestamp=datetime.now(),
                trend_indicators=trend_results,
                momentum_indicators=momentum_results,
                volume_indicators=volume_results,
                volatility_indicators=volatility_results,
                trend_score=trend_score,
                momentum_score=momentum_score,
                volume_score=volume_score,
                volatility_score=volatility_score,
                overall_signal=overall_signal,
                overall_confidence=overall_confidence,
                weighted_breakdown=weighted_breakdown
            )
            
        except Exception as e:
            logger.error(f"❌ 详细技术分析失败 {symbol}: {e}")
            raise
    
    async def _analyze_trend_indicators(self, symbol: str, klines_data: Dict) -> List[IndicatorResult]:
        """分析趋势指标"""
        results = []
        
        try:
            # 使用日线数据进行趋势分析
            daily_data = klines_data.get('1d', [])
            if not daily_data:
                return results
            
            df = pd.DataFrame(daily_data)
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            
            # SuperTrend指标
            try:
                high_list = df['high'].tolist()
                low_list = df['low'].tolist()
                close_list = df['close'].tolist()
                
                supertrend_values, trend_directions = self.supertrend_indicator.calculate(
                    high_list, low_list, close_list
                )
                
                if supertrend_values and len(supertrend_values) > 0:
                    current_price = df['close'].iloc[-1]
                    supertrend_value = supertrend_values[-1]
                    is_uptrend = trend_directions[-1] if len(trend_directions) > 0 else False
                    
                    if supertrend_value is not None:
                        if is_uptrend:
                            signal = 'buy'
                            strength = min(1.0, (current_price - supertrend_value) / current_price * 10)
                            description = f"SuperTrend上升趋势，支撑位{supertrend_value:.4f}"
                        else:
                            signal = 'sell'
                            strength = min(1.0, (supertrend_value - current_price) / current_price * 10)
                            description = f"SuperTrend下降趋势，阻力位{supertrend_value:.4f}"
                        
                        results.append(IndicatorResult(
                            name="SuperTrend",
                            signal=signal,
                            strength=strength,
                            weight=self.indicator_weights['supertrend'],
                            value=supertrend_value,
                            description=description
                        ))
            except Exception as e:
                logger.warning(f"⚠️ SuperTrend计算失败: {e}")
            
            # EMA交叉
            try:
                close_list = df['close'].tolist()
                ema_12 = self.ma_indicator.ema(close_list, 12)
                ema_26 = self.ma_indicator.ema(close_list, 26)
                
                if ema_12 and ema_26 and ema_12[-1] is not None and ema_26[-1] is not None:
                    ema_12_current = ema_12[-1]
                    ema_26_current = ema_26[-1]
                    
                    if ema_12_current > ema_26_current:
                        signal = 'buy'
                        strength = min(1.0, (ema_12_current - ema_26_current) / ema_26_current * 20)
                        description = f"EMA12({ema_12_current:.4f})在EMA26上方，短期趋势向上"
                    else:
                        signal = 'sell'
                        strength = min(1.0, (ema_26_current - ema_12_current) / ema_26_current * 20)
                        description = f"EMA12({ema_12_current:.4f})在EMA26下方，短期趋势向下"
                    
                    results.append(IndicatorResult(
                        name="EMA交叉",
                        signal=signal,
                        strength=strength,
                        weight=self.indicator_weights['ema_cross'],
                        value=ema_12_current - ema_26_current,
                        description=description
                    ))
            except Exception as e:
                logger.warning(f"⚠️ EMA交叉计算失败: {e}")
            
        except Exception as e:
            logger.error(f"❌ 趋势指标分析失败: {e}")
        
        return results    
    
    async def _analyze_momentum_indicators(self, symbol: str, klines_data: Dict) -> List[IndicatorResult]:
        """分析动量指标"""
        results = []
        
        try:
            # 使用4小时数据进行动量分析
            hourly_data = klines_data.get('4h', [])
            if not hourly_data:
                return results
            
            df = pd.DataFrame(hourly_data)
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            
            # RSI指标
            try:
                close_list = df['close'].tolist()
                rsi_values = self.rsi_indicator.calculate(close_list, 14)
                
                if rsi_values and rsi_values[-1] is not None:
                    rsi_value = rsi_values[-1]
                    
                    if rsi_value > 70:
                        signal = 'sell'
                        strength = min(1.0, (rsi_value - 70) / 30)
                        description = f"RSI超买区域({rsi_value:.1f})，可能回调"
                    elif rsi_value < 30:
                        signal = 'buy'
                        strength = min(1.0, (30 - rsi_value) / 30)
                        description = f"RSI超卖区域({rsi_value:.1f})，可能反弹"
                    elif rsi_value > 50:
                        signal = 'buy'
                        strength = (rsi_value - 50) / 20 * 0.5
                        description = f"RSI中性偏强({rsi_value:.1f})，动量向上"
                    else:
                        signal = 'sell'
                        strength = (50 - rsi_value) / 20 * 0.5
                        description = f"RSI中性偏弱({rsi_value:.1f})，动量向下"
                    
                    results.append(IndicatorResult(
                        name="RSI",
                        signal=signal,
                        strength=strength,
                        weight=self.indicator_weights['rsi'],
                        value=rsi_value,
                        description=description
                    ))
            except Exception as e:
                logger.warning(f"⚠️ RSI计算失败: {e}")
            
            # MACD指标 (使用TA-Lib)
            try:
                import talib
                close_array = df['close'].values
                macd_line, signal_line, histogram = talib.MACD(close_array)
                
                if len(macd_line) > 0 and not np.isnan(macd_line[-1]) and not np.isnan(signal_line[-1]):
                    macd_current = macd_line[-1]
                    signal_current = signal_line[-1]
                    
                    if macd_current > signal_current and macd_current > 0:
                        signal = 'buy'
                        strength = min(1.0, abs(macd_current - signal_current) * 100)
                        description = f"MACD金叉且在零轴上方，强势上涨"
                    elif macd_current > signal_current:
                        signal = 'buy'
                        strength = min(0.7, abs(macd_current - signal_current) * 100)
                        description = f"MACD金叉但在零轴下方，弱势反弹"
                    elif macd_current < signal_current and macd_current < 0:
                        signal = 'sell'
                        strength = min(1.0, abs(macd_current - signal_current) * 100)
                        description = f"MACD死叉且在零轴下方，强势下跌"
                    else:
                        signal = 'sell'
                        strength = min(0.7, abs(macd_current - signal_current) * 100)
                        description = f"MACD死叉但在零轴上方，弱势回调"
                    
                    results.append(IndicatorResult(
                        name="MACD",
                        signal=signal,
                        strength=strength,
                        weight=self.indicator_weights['macd'],
                        value=macd_current - signal_current,
                        description=description
                    ))
            except Exception as e:
                logger.warning(f"⚠️ MACD计算失败: {e}")
            
        except Exception as e:
            logger.error(f"❌ 动量指标分析失败: {e}")
        
        return results
    
    async def _analyze_volume_indicators(self, symbol: str, klines_data: Dict) -> List[IndicatorResult]:
        """分析成交量指标"""
        results = []
        
        try:
            # 使用1小时数据进行成交量分析
            hourly_data = klines_data.get('1h', [])
            if not hourly_data:
                return results
            
            df = pd.DataFrame(hourly_data)
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            
            # 成交量SMA
            try:
                volume_list = df['volume'].tolist()
                volume_sma = self.ma_indicator.sma(volume_list, 20)
                
                if volume_sma and volume_sma[-1] is not None:
                    current_volume = df['volume'].iloc[-1]
                    avg_volume = volume_sma[-1]
                    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
                    
                    if volume_ratio > 2.0:
                        signal = 'buy'  # 大成交量通常是突破信号
                        strength = min(1.0, (volume_ratio - 1) / 3)
                        description = f"成交量放大{volume_ratio:.1f}倍，资金活跃"
                    elif volume_ratio > 1.5:
                        signal = 'buy'
                        strength = min(0.7, (volume_ratio - 1) / 2)
                        description = f"成交量温和放大{volume_ratio:.1f}倍"
                    elif volume_ratio < 0.5:
                        signal = 'sell'
                        strength = min(0.8, (1 - volume_ratio) / 0.5)
                        description = f"成交量萎缩至{volume_ratio:.1f}倍，缺乏动力"
                    else:
                        signal = 'neutral'
                        strength = 0.3
                        description = f"成交量正常({volume_ratio:.1f}倍)"
                    
                    results.append(IndicatorResult(
                        name="成交量",
                        signal=signal,
                        strength=strength,
                        weight=self.indicator_weights['volume_sma'],
                        value=volume_ratio,
                        description=description
                    ))
            except Exception as e:
                logger.warning(f"⚠️ 成交量指标计算失败: {e}")
            
            # OBV指标 (使用TA-Lib)
            try:
                import talib
                close_array = df['close'].values
                volume_array = df['volume'].values
                obv = talib.OBV(close_array, volume_array)
                
                if len(obv) > 20:
                    obv_sma = self.ma_indicator.sma(obv.tolist(), 20)
                    if obv_sma and obv_sma[-1] is not None:
                        obv_current = obv[-1]
                        obv_avg = obv_sma[-1]
                        
                        if obv_current > obv_avg:
                            signal = 'buy'
                            strength = min(1.0, abs(obv_current - obv_avg) / abs(obv_avg) * 5 if obv_avg != 0 else 0.5)
                            description = f"OBV上升，资金净流入"
                        else:
                            signal = 'sell'
                            strength = min(1.0, abs(obv_avg - obv_current) / abs(obv_avg) * 5 if obv_avg != 0 else 0.5)
                            description = f"OBV下降，资金净流出"
                        
                        results.append(IndicatorResult(
                            name="OBV",
                            signal=signal,
                            strength=strength,
                            weight=self.indicator_weights['obv'],
                            value=obv_current - obv_avg,
                            description=description
                        ))
            except Exception as e:
                logger.warning(f"⚠️ OBV计算失败: {e}")
            
        except Exception as e:
            logger.error(f"❌ 成交量指标分析失败: {e}")
        
        return results
    
    async def _analyze_volatility_indicators(self, symbol: str, klines_data: Dict) -> List[IndicatorResult]:
        """分析波动性指标"""
        results = []
        
        try:
            # 使用15分钟数据进行波动性分析
            minute_data = klines_data.get('15m', [])
            if not minute_data:
                return results
            
            df = pd.DataFrame(minute_data)
            df['close'] = df['close'].astype(float)
            
            # 布林带指标 (使用TA-Lib)
            try:
                import talib
                close_array = df['close'].values
                bb_upper, bb_middle, bb_lower = talib.BBANDS(close_array, timeperiod=20)
                
                if len(bb_upper) > 0 and not np.isnan(bb_upper[-1]) and not np.isnan(bb_lower[-1]):
                    current_price = df['close'].iloc[-1]
                    upper_band = bb_upper[-1]
                    lower_band = bb_lower[-1]
                    
                    # 计算价格在布林带中的位置
                    if upper_band != lower_band:
                        bb_position = (current_price - lower_band) / (upper_band - lower_band)
                        
                        if bb_position > 0.8:
                            signal = 'sell'
                            strength = min(1.0, (bb_position - 0.8) / 0.2)
                            description = f"价格接近布林带上轨({bb_position:.1%})，可能回调"
                        elif bb_position < 0.2:
                            signal = 'buy'
                            strength = min(1.0, (0.2 - bb_position) / 0.2)
                            description = f"价格接近布林带下轨({bb_position:.1%})，可能反弹"
                        elif bb_position > 0.5:
                            signal = 'buy'
                            strength = (bb_position - 0.5) * 0.6
                            description = f"价格在布林带上半部({bb_position:.1%})，偏强势"
                        else:
                            signal = 'sell'
                            strength = (0.5 - bb_position) * 0.6
                            description = f"价格在布林带下半部({bb_position:.1%})，偏弱势"
                        
                        results.append(IndicatorResult(
                            name="布林带",
                            signal=signal,
                            strength=strength,
                            weight=self.indicator_weights['bollinger'],
                            value=bb_position,
                            description=description
                        ))
            except Exception as e:
                logger.warning(f"⚠️ 布林带计算失败: {e}")
            
        except Exception as e:
            logger.error(f"❌ 波动性指标分析失败: {e}")
        
        return results
    
    def _calculate_category_score(self, indicators: List[IndicatorResult]) -> float:
        """计算某类指标的综合评分"""
        if not indicators:
            return 50.0  # 中性评分
        
        total_weighted_score = 0.0
        total_weight = 0.0
        
        for indicator in indicators:
            # 将信号转换为评分
            if indicator.signal == 'buy':
                score = 50 + (indicator.strength * 50)  # 50-100
            elif indicator.signal == 'sell':
                score = 50 - (indicator.strength * 50)  # 0-50
            else:  # neutral
                score = 50
            
            total_weighted_score += score * indicator.weight
            total_weight += indicator.weight
        
        return total_weighted_score / total_weight if total_weight > 0 else 50.0
    
    def _calculate_overall_signal(self, trend_results: List[IndicatorResult], 
                                momentum_results: List[IndicatorResult],
                                volume_results: List[IndicatorResult],
                                volatility_results: List[IndicatorResult]) -> Tuple[str, float, Dict[str, float]]:
        """计算综合信号"""
        
        # 各类指标的权重
        category_weights = {
            'trend': 0.40,      # 趋势 40%
            'momentum': 0.30,   # 动量 30%
            'volume': 0.20,     # 成交量 20%
            'volatility': 0.10  # 波动性 10%
        }
        
        # 计算各类评分
        trend_score = self._calculate_category_score(trend_results)
        momentum_score = self._calculate_category_score(momentum_results)
        volume_score = self._calculate_category_score(volume_results)
        volatility_score = self._calculate_category_score(volatility_results)
        
        # 计算加权综合评分
        overall_score = (
            trend_score * category_weights['trend'] +
            momentum_score * category_weights['momentum'] +
            volume_score * category_weights['volume'] +
            volatility_score * category_weights['volatility']
        )
        
        # 确定信号
        if overall_score >= 70:
            signal = 'strong_buy'
            confidence = min(95, overall_score)
        elif overall_score >= 60:
            signal = 'buy'
            confidence = overall_score
        elif overall_score <= 30:
            signal = 'strong_sell'
            confidence = min(95, 100 - overall_score)
        elif overall_score <= 40:
            signal = 'sell'
            confidence = 100 - overall_score
        else:
            signal = 'hold'
            confidence = 100 - abs(overall_score - 50) * 2
        
        # 构建权重分解
        weighted_breakdown = {
            f"趋势指标({category_weights['trend']:.0%})": trend_score,
            f"动量指标({category_weights['momentum']:.0%})": momentum_score,
            f"成交量指标({category_weights['volume']:.0%})": volume_score,
            f"波动性指标({category_weights['volatility']:.0%})": volatility_score
        }
        
        return signal, confidence, weighted_breakdown
    
    def format_analysis_message(self, analysis: TechnicalAnalysisBreakdown) -> str:
        """格式化分析消息"""
        
        # 信号图标
        signal_icons = {
            'strong_buy': '🚀',
            'buy': '📈',
            'hold': '⏸️',
            'sell': '📉',
            'strong_sell': '💥'
        }
        
        # 信号文本
        signal_texts = {
            'strong_buy': '强烈买入',
            'buy': '买入',
            'hold': '持有',
            'sell': '卖出',
            'strong_sell': '强烈卖出'
        }
        
        icon = signal_icons.get(analysis.overall_signal, '📊')
        signal_text = signal_texts.get(analysis.overall_signal, analysis.overall_signal)
        
        message_parts = [
            f"{icon} 技术分析 - {analysis.symbol}",
            "",
            f"📊 综合信号: {signal_text}",
            f"🎯 置信度: {analysis.overall_confidence:.1f}%",
            "",
            "📈 技术分析构成:"
        ]
        
        # 添加各类指标评分
        for category, score in analysis.weighted_breakdown.items():
            if score >= 70:
                status = "强势 🟢"
            elif score >= 60:
                status = "偏强 🟡"
            elif score <= 30:
                status = "弱势 🔴"
            elif score <= 40:
                status = "偏弱 🟠"
            else:
                status = "中性 ⚪"
            
            message_parts.append(f"  • {category}: {score:.1f}分 {status}")
        
        # 添加关键指标详情
        message_parts.extend([
            "",
            "🔍 关键指标:"
        ])
        
        # 选择最重要的指标显示
        all_indicators = (analysis.trend_indicators + analysis.momentum_indicators + 
                         analysis.volume_indicators + analysis.volatility_indicators)
        
        # 按权重排序，取前3个
        important_indicators = sorted(all_indicators, key=lambda x: x.weight, reverse=True)[:3]
        
        for indicator in important_indicators:
            signal_emoji = "📈" if indicator.signal == 'buy' else "📉" if indicator.signal == 'sell' else "⏸️"
            message_parts.append(
                f"  • {indicator.name}: {signal_emoji} {indicator.description}"
            )
        
        message_parts.extend([
            "",
            f"⏰ 分析时间: {analysis.timestamp.strftime('%H:%M:%S')}",
            "",
            "💡 技术分析仅供参考，请结合基本面和风险管理！"
        ])
        
        return "\n".join(message_parts)


# 便利函数
def get_detailed_technical_analysis_service() -> DetailedTechnicalAnalysisService:
    """
    获取详细技术分析服务实例
    Get detailed technical analysis service instance
    """
    return DetailedTechnicalAnalysisService()
