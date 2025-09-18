# -*- coding: utf-8 -*-
"""
增强版技术分析服务
Enhanced Technical Analysis Service - 集成更多指标和量价分析
"""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import pandas as pd
import numpy as np
import talib

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.exchanges.service_manager import get_exchange_service
from app.schemas.trading import SignalStrength, TradingAction

logger = get_logger(__name__)


class TechnicalSignal(Enum):
    """技术信号类型"""
    STRONG_BUY = "强烈买入"
    BUY = "买入"
    NEUTRAL = "中性"
    SELL = "卖出"
    STRONG_SELL = "强烈卖出"


@dataclass
class PriceLevel:
    """价格水平"""
    price: float
    level_type: str  # 'support', 'resistance', 'entry', 'stop_loss', 'take_profit'
    strength: float  # 0-1 强度
    description: str


@dataclass
class TradingRecommendation:
    """交易建议"""
    action: TechnicalSignal
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_size: Optional[float] = None  # 建议仓位比例 0-1
    confidence: float = 0.0
    reasoning: str = ""
    risk_reward_ratio: Optional[float] = None


@dataclass
class EnhancedTechnicalAnalysis:
    """增强版技术分析结果"""
    symbol: str
    timestamp: datetime
    current_price: float
    
    # 核心信号
    overall_signal: TechnicalSignal
    confidence: float
    
    # 详细分析
    trend_analysis: Dict[str, Any]
    momentum_analysis: Dict[str, Any] 
    volume_analysis: Dict[str, Any]
    volatility_analysis: Dict[str, Any]
    
    # 价格水平
    support_levels: List[PriceLevel]
    resistance_levels: List[PriceLevel]
    
    # 交易建议
    recommendation: TradingRecommendation
    
    # 技术指标详情
    indicators: Dict[str, Any]
    
    # 分析推理
    detailed_reasoning: str


class EnhancedTechnicalAnalysisService:
    """增强版技术分析服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.exchange_service = None
        self.initialized = False
        
        # 技术指标权重配置
        self.indicator_weights = {
            'trend': {
                'supertrend': 0.25,
                'ema_cross': 0.20,
                'macd': 0.15,
                'adx': 0.10
            },
            'momentum': {
                'rsi': 0.20,
                'stoch': 0.15,
                'cci': 0.10,
                'williams_r': 0.05
            },
            'volume': {
                'obv': 0.25,
                'volume_sma': 0.20,
                'vwap': 0.15,
                'mfi': 0.10
            },
            'volatility': {
                'bollinger': 0.20,
                'atr': 0.15,
                'keltner': 0.10
            }
        }
    
    async def initialize(self) -> None:
        """初始化服务"""
        if self.initialized:
            return
            
        try:
            self.exchange_service = await get_exchange_service()
            self.initialized = True
            self.logger.info("✅ 增强版技术分析服务初始化完成")
        except Exception as e:
            self.logger.error(f"❌ 增强版技术分析服务初始化失败: {e}")
            raise
    
    async def analyze_symbol(self, symbol: str, timeframe: str = "1h") -> Optional[EnhancedTechnicalAnalysis]:
        """分析交易对"""
        try:
            if not self.initialized:
                await self.initialize()
            
            # 获取市场数据
            market_data = await self._fetch_market_data(symbol, timeframe)
            if market_data is None or len(market_data) < 100:
                self.logger.warning(f"数据不足，无法分析 {symbol}")
                return None
            
            # 计算技术指标
            indicators = await self._calculate_indicators(market_data)
            
            # 分析各个维度
            trend_analysis = await self._analyze_trend(market_data, indicators)
            momentum_analysis = await self._analyze_momentum(market_data, indicators)
            volume_analysis = await self._analyze_volume(market_data, indicators)
            volatility_analysis = await self._analyze_volatility(market_data, indicators)
            
            # 计算支撑阻力位
            support_levels, resistance_levels = await self._calculate_support_resistance(market_data)
            
            # 生成综合信号
            overall_signal, confidence = await self._generate_overall_signal(
                trend_analysis, momentum_analysis, volume_analysis, volatility_analysis
            )
            
            # 生成交易建议
            recommendation = await self._generate_trading_recommendation(
                market_data, overall_signal, confidence, support_levels, resistance_levels
            )
            
            # 生成详细推理
            detailed_reasoning = await self._generate_detailed_reasoning(
                trend_analysis, momentum_analysis, volume_analysis, volatility_analysis, recommendation
            )
            
            current_price = float(market_data['close'].iloc[-1])
            
            return EnhancedTechnicalAnalysis(
                symbol=symbol,
                timestamp=datetime.now(),
                current_price=current_price,
                overall_signal=overall_signal,
                confidence=confidence,
                trend_analysis=trend_analysis,
                momentum_analysis=momentum_analysis,
                volume_analysis=volume_analysis,
                volatility_analysis=volatility_analysis,
                support_levels=support_levels,
                resistance_levels=resistance_levels,
                recommendation=recommendation,
                indicators=indicators,
                detailed_reasoning=detailed_reasoning
            )
            
        except Exception as e:
            self.logger.error(f"技术分析失败 {symbol}: {e}")
            return None
    
    async def _fetch_market_data(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> Optional[pd.DataFrame]:
        """获取市场数据"""
        try:
            # 获取K线数据
            klines = await self.exchange_service.get_kline_data(symbol, timeframe, limit)
            if not klines:
                return None
            
            # 转换为DataFrame
            df = pd.DataFrame(klines)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
            
            # 确保数据类型正确
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            return df
            
        except Exception as e:
            self.logger.error(f"获取市场数据失败 {symbol}: {e}")
            return None
    
    async def _calculate_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        """计算技术指标"""
        try:
            indicators = {}
            
            # 价格数据
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values
            volume = df['volume'].values
            
            # 趋势指标
            indicators['sma_20'] = talib.SMA(close, timeperiod=20)
            indicators['sma_50'] = talib.SMA(close, timeperiod=50)
            indicators['ema_12'] = talib.EMA(close, timeperiod=12)
            indicators['ema_26'] = talib.EMA(close, timeperiod=26)
            
            # MACD
            macd, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
            indicators['macd'] = macd
            indicators['macd_signal'] = macd_signal
            indicators['macd_hist'] = macd_hist
            
            # 动量指标
            indicators['rsi'] = talib.RSI(close, timeperiod=14)
            indicators['stoch_k'], indicators['stoch_d'] = talib.STOCH(high, low, close)
            indicators['cci'] = talib.CCI(high, low, close, timeperiod=14)
            indicators['williams_r'] = talib.WILLR(high, low, close, timeperiod=14)
            
            # 成交量指标
            indicators['obv'] = talib.OBV(close, volume)
            indicators['volume_sma'] = talib.SMA(volume, timeperiod=20)
            indicators['mfi'] = talib.MFI(high, low, close, volume, timeperiod=14)
            
            # 计算VWAP
            typical_price = (high + low + close) / 3
            vwap_num = np.cumsum(typical_price * volume)
            vwap_den = np.cumsum(volume)
            indicators['vwap'] = vwap_num / vwap_den
            
            # 波动率指标
            indicators['atr'] = talib.ATR(high, low, close, timeperiod=14)
            bb_upper, bb_middle, bb_lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
            indicators['bb_upper'] = bb_upper
            indicators['bb_middle'] = bb_middle
            indicators['bb_lower'] = bb_lower
            
            # ADX趋势强度
            indicators['adx'] = talib.ADX(high, low, close, timeperiod=14)
            
            # SuperTrend (简化版本)
            hl2 = (high + low) / 2
            atr = indicators['atr']
            factor = 3.0
            
            upper_band = hl2 + (factor * atr)
            lower_band = hl2 - (factor * atr)
            
            supertrend = np.zeros_like(close)
            trend = np.ones_like(close)
            
            for i in range(1, len(close)):
                if close[i] <= lower_band[i-1]:
                    trend[i] = -1
                elif close[i] >= upper_band[i-1]:
                    trend[i] = 1
                else:
                    trend[i] = trend[i-1]
                
                if trend[i] == 1:
                    supertrend[i] = lower_band[i]
                else:
                    supertrend[i] = upper_band[i]
            
            indicators['supertrend'] = supertrend
            indicators['supertrend_trend'] = trend
            
            return indicators
            
        except Exception as e:
            self.logger.error(f"计算技术指标失败: {e}")
            return {}
    
    async def _analyze_trend(self, df: pd.DataFrame, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """分析趋势"""
        try:
            trend_signals = []
            trend_strength = 0.0
            
            current_price = df['close'].iloc[-1]
            
            # SuperTrend分析
            if 'supertrend' in indicators and 'supertrend_trend' in indicators:
                st_trend = indicators['supertrend_trend'][-1]
                if st_trend > 0:
                    trend_signals.append(('SuperTrend', 'bullish', 0.25))
                    trend_strength += 0.25
                else:
                    trend_signals.append(('SuperTrend', 'bearish', 0.25))
                    trend_strength -= 0.25
            
            # EMA交叉分析
            if 'ema_12' in indicators and 'ema_26' in indicators:
                ema12 = indicators['ema_12'][-1]
                ema26 = indicators['ema_26'][-1]
                if ema12 > ema26:
                    trend_signals.append(('EMA交叉', 'bullish', 0.20))
                    trend_strength += 0.20
                else:
                    trend_signals.append(('EMA交叉', 'bearish', 0.20))
                    trend_strength -= 0.20
            
            # MACD分析
            if 'macd' in indicators and 'macd_signal' in indicators:
                macd = indicators['macd'][-1]
                macd_signal = indicators['macd_signal'][-1]
                if macd > macd_signal and macd > 0:
                    trend_signals.append(('MACD', 'bullish', 0.15))
                    trend_strength += 0.15
                elif macd < macd_signal and macd < 0:
                    trend_signals.append(('MACD', 'bearish', 0.15))
                    trend_strength -= 0.15
                else:
                    trend_signals.append(('MACD', 'neutral', 0.0))
            
            # ADX趋势强度
            adx_strength = 0.0
            if 'adx' in indicators:
                adx = indicators['adx'][-1]
                if adx > 25:
                    adx_strength = min((adx - 25) / 50, 1.0)  # 标准化到0-1
                trend_signals.append(('ADX强度', f'{adx:.1f}', adx_strength * 0.10))
            
            # 移动平均线排列
            ma_alignment = 0.0
            if all(k in indicators for k in ['sma_20', 'sma_50']):
                sma20 = indicators['sma_20'][-1]
                sma50 = indicators['sma_50'][-1]
                
                if current_price > sma20 > sma50:
                    ma_alignment = 0.10  # 多头排列
                elif current_price < sma20 < sma50:
                    ma_alignment = -0.10  # 空头排列
                
                trend_strength += ma_alignment
                trend_signals.append(('均线排列', 'bullish' if ma_alignment > 0 else 'bearish' if ma_alignment < 0 else 'neutral', abs(ma_alignment)))
            
            # 确定趋势方向
            if trend_strength > 0.3:
                trend_direction = 'strong_bullish'
            elif trend_strength > 0.1:
                trend_direction = 'bullish'
            elif trend_strength < -0.3:
                trend_direction = 'strong_bearish'
            elif trend_strength < -0.1:
                trend_direction = 'bearish'
            else:
                trend_direction = 'neutral'
            
            return {
                'direction': trend_direction,
                'strength': abs(trend_strength),
                'signals': trend_signals,
                'score': trend_strength,
                'adx_strength': adx_strength
            }
            
        except Exception as e:
            self.logger.error(f"趋势分析失败: {e}")
            return {'direction': 'neutral', 'strength': 0.0, 'signals': [], 'score': 0.0}
    
    async def _analyze_momentum(self, df: pd.DataFrame, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """分析动量"""
        try:
            momentum_signals = []
            momentum_score = 0.0
            
            # RSI分析
            if 'rsi' in indicators:
                rsi = indicators['rsi'][-1]
                if rsi > 70:
                    momentum_signals.append(('RSI', 'overbought', -0.20))
                    momentum_score -= 0.20
                elif rsi < 30:
                    momentum_signals.append(('RSI', 'oversold', 0.20))
                    momentum_score += 0.20
                elif rsi > 50:
                    momentum_signals.append(('RSI', 'bullish', 0.10))
                    momentum_score += 0.10
                else:
                    momentum_signals.append(('RSI', 'bearish', -0.10))
                    momentum_score -= 0.10
            
            # 随机指标分析
            if 'stoch_k' in indicators and 'stoch_d' in indicators:
                stoch_k = indicators['stoch_k'][-1]
                stoch_d = indicators['stoch_d'][-1]
                
                if stoch_k > 80 and stoch_d > 80:
                    momentum_signals.append(('Stoch', 'overbought', -0.15))
                    momentum_score -= 0.15
                elif stoch_k < 20 and stoch_d < 20:
                    momentum_signals.append(('Stoch', 'oversold', 0.15))
                    momentum_score += 0.15
                elif stoch_k > stoch_d:
                    momentum_signals.append(('Stoch', 'bullish_cross', 0.10))
                    momentum_score += 0.10
                else:
                    momentum_signals.append(('Stoch', 'bearish_cross', -0.10))
                    momentum_score -= 0.10
            
            # CCI分析
            if 'cci' in indicators:
                cci = indicators['cci'][-1]
                if cci > 100:
                    momentum_signals.append(('CCI', 'overbought', -0.10))
                    momentum_score -= 0.10
                elif cci < -100:
                    momentum_signals.append(('CCI', 'oversold', 0.10))
                    momentum_score += 0.10
                else:
                    momentum_signals.append(('CCI', 'neutral', 0.0))
            
            # Williams %R分析
            if 'williams_r' in indicators:
                williams_r = indicators['williams_r'][-1]
                if williams_r > -20:
                    momentum_signals.append(('Williams%R', 'overbought', -0.05))
                    momentum_score -= 0.05
                elif williams_r < -80:
                    momentum_signals.append(('Williams%R', 'oversold', 0.05))
                    momentum_score += 0.05
            
            # 确定动量状态
            if momentum_score > 0.3:
                momentum_state = 'strong_bullish'
            elif momentum_score > 0.1:
                momentum_state = 'bullish'
            elif momentum_score < -0.3:
                momentum_state = 'strong_bearish'
            elif momentum_score < -0.1:
                momentum_state = 'bearish'
            else:
                momentum_state = 'neutral'
            
            return {
                'state': momentum_state,
                'score': momentum_score,
                'signals': momentum_signals,
                'strength': abs(momentum_score)
            }
            
        except Exception as e:
            self.logger.error(f"动量分析失败: {e}")
            return {'state': 'neutral', 'score': 0.0, 'signals': [], 'strength': 0.0}
    
    async def _analyze_volume(self, df: pd.DataFrame, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """分析成交量"""
        try:
            volume_signals = []
            volume_score = 0.0
            
            current_volume = df['volume'].iloc[-1]
            current_price = df['close'].iloc[-1]
            
            # OBV分析
            if 'obv' in indicators and len(indicators['obv']) >= 2:
                obv_current = indicators['obv'][-1]
                obv_prev = indicators['obv'][-2]
                
                price_prev = df['close'].iloc[-2]
                
                # 量价背离检测
                price_change = (current_price - price_prev) / price_prev
                obv_change = (obv_current - obv_prev) / abs(obv_prev) if obv_prev != 0 else 0
                
                if price_change > 0 and obv_change > 0:
                    volume_signals.append(('OBV', 'price_volume_confirm', 0.25))
                    volume_score += 0.25
                elif price_change < 0 and obv_change < 0:
                    volume_signals.append(('OBV', 'price_volume_confirm', -0.25))
                    volume_score -= 0.25
                elif price_change > 0 and obv_change < 0:
                    volume_signals.append(('OBV', 'bearish_divergence', -0.20))
                    volume_score -= 0.20
                elif price_change < 0 and obv_change > 0:
                    volume_signals.append(('OBV', 'bullish_divergence', 0.20))
                    volume_score += 0.20
            
            # 成交量均线分析
            if 'volume_sma' in indicators:
                volume_sma = indicators['volume_sma'][-1]
                volume_ratio = current_volume / volume_sma if volume_sma > 0 else 1
                
                if volume_ratio > 1.5:
                    volume_signals.append(('成交量', 'high_volume', 0.15))
                    volume_score += 0.15
                elif volume_ratio < 0.5:
                    volume_signals.append(('成交量', 'low_volume', -0.10))
                    volume_score -= 0.10
                else:
                    volume_signals.append(('成交量', 'normal_volume', 0.0))
            
            # VWAP分析
            if 'vwap' in indicators:
                vwap = indicators['vwap'][-1]
                if current_price > vwap:
                    volume_signals.append(('VWAP', 'above_vwap', 0.15))
                    volume_score += 0.15
                else:
                    volume_signals.append(('VWAP', 'below_vwap', -0.15))
                    volume_score -= 0.15
            
            # MFI分析
            if 'mfi' in indicators:
                mfi = indicators['mfi'][-1]
                if mfi > 80:
                    volume_signals.append(('MFI', 'overbought', -0.10))
                    volume_score -= 0.10
                elif mfi < 20:
                    volume_signals.append(('MFI', 'oversold', 0.10))
                    volume_score += 0.10
                else:
                    volume_signals.append(('MFI', 'neutral', 0.0))
            
            # 确定成交量状态
            if volume_score > 0.3:
                volume_state = 'strong_bullish'
            elif volume_score > 0.1:
                volume_state = 'bullish'
            elif volume_score < -0.3:
                volume_state = 'strong_bearish'
            elif volume_score < -0.1:
                volume_state = 'bearish'
            else:
                volume_state = 'neutral'
            
            return {
                'state': volume_state,
                'score': volume_score,
                'signals': volume_signals,
                'strength': abs(volume_score),
                'volume_ratio': current_volume / indicators.get('volume_sma', [1])[-1] if 'volume_sma' in indicators else 1.0
            }
            
        except Exception as e:
            self.logger.error(f"成交量分析失败: {e}")
            return {'state': 'neutral', 'score': 0.0, 'signals': [], 'strength': 0.0, 'volume_ratio': 1.0}
    
    async def _analyze_volatility(self, df: pd.DataFrame, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """分析波动率"""
        try:
            volatility_signals = []
            volatility_score = 0.0
            
            current_price = df['close'].iloc[-1]
            
            # 布林带分析
            if all(k in indicators for k in ['bb_upper', 'bb_middle', 'bb_lower']):
                bb_upper = indicators['bb_upper'][-1]
                bb_middle = indicators['bb_middle'][-1]
                bb_lower = indicators['bb_lower'][-1]
                
                bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
                
                if bb_position > 0.8:
                    volatility_signals.append(('布林带', 'near_upper', -0.15))
                    volatility_score -= 0.15
                elif bb_position < 0.2:
                    volatility_signals.append(('布林带', 'near_lower', 0.15))
                    volatility_score += 0.15
                else:
                    volatility_signals.append(('布林带', 'middle_range', 0.0))
                
                # 布林带宽度分析
                bb_width = (bb_upper - bb_lower) / bb_middle if bb_middle > 0 else 0
                if bb_width > 0.1:  # 高波动
                    volatility_signals.append(('波动率', 'high_volatility', 0.05))
                elif bb_width < 0.02:  # 低波动
                    volatility_signals.append(('波动率', 'low_volatility', -0.05))
            
            # ATR分析
            if 'atr' in indicators and len(indicators['atr']) >= 14:
                atr_current = indicators['atr'][-1]
                atr_avg = np.mean(indicators['atr'][-14:])
                
                atr_ratio = atr_current / atr_avg if atr_avg > 0 else 1
                
                if atr_ratio > 1.5:
                    volatility_signals.append(('ATR', 'increasing_volatility', 0.10))
                    volatility_score += 0.10
                elif atr_ratio < 0.7:
                    volatility_signals.append(('ATR', 'decreasing_volatility', -0.05))
                    volatility_score -= 0.05
            
            # 确定波动率状态
            if volatility_score > 0.15:
                volatility_state = 'high_bullish'
            elif volatility_score > 0.05:
                volatility_state = 'moderate_bullish'
            elif volatility_score < -0.15:
                volatility_state = 'high_bearish'
            elif volatility_score < -0.05:
                volatility_state = 'moderate_bearish'
            else:
                volatility_state = 'neutral'
            
            return {
                'state': volatility_state,
                'score': volatility_score,
                'signals': volatility_signals,
                'strength': abs(volatility_score)
            }
            
        except Exception as e:
            self.logger.error(f"波动率分析失败: {e}")
            return {'state': 'neutral', 'score': 0.0, 'signals': [], 'strength': 0.0}
    
    async def _calculate_support_resistance(self, df: pd.DataFrame) -> Tuple[List[PriceLevel], List[PriceLevel]]:
        """计算支撑阻力位"""
        try:
            support_levels = []
            resistance_levels = []
            
            # 获取最近的高低点
            highs = df['high'].values
            lows = df['low'].values
            closes = df['close'].values
            
            current_price = closes[-1]
            
            # 寻找局部高低点
            window = 10
            local_highs = []
            local_lows = []
            
            for i in range(window, len(highs) - window):
                # 局部高点
                if all(highs[i] >= highs[i-j] for j in range(1, window+1)) and \
                   all(highs[i] >= highs[i+j] for j in range(1, window+1)):
                    local_highs.append((i, highs[i]))
                
                # 局部低点
                if all(lows[i] <= lows[i-j] for j in range(1, window+1)) and \
                   all(lows[i] <= lows[i+j] for j in range(1, window+1)):
                    local_lows.append((i, lows[i]))
            
            # 计算支撑位（基于局部低点）
            for idx, price in local_lows[-5:]:  # 最近5个低点
                if price < current_price:
                    distance = abs(current_price - price) / current_price
                    strength = max(0.1, 1.0 - distance * 10)  # 距离越近强度越高
                    
                    support_levels.append(PriceLevel(
                        price=price,
                        level_type='support',
                        strength=strength,
                        description=f'局部低点支撑 {price:.4f}'
                    ))
            
            # 计算阻力位（基于局部高点）
            for idx, price in local_highs[-5:]:  # 最近5个高点
                if price > current_price:
                    distance = abs(price - current_price) / current_price
                    strength = max(0.1, 1.0 - distance * 10)  # 距离越近强度越高
                    
                    resistance_levels.append(PriceLevel(
                        price=price,
                        level_type='resistance',
                        strength=strength,
                        description=f'局部高点阻力 {price:.4f}'
                    ))
            
            # 添加移动平均线作为动态支撑阻力
            if len(closes) >= 20:
                sma20 = np.mean(closes[-20:])
                if sma20 < current_price:
                    support_levels.append(PriceLevel(
                        price=sma20,
                        level_type='support',
                        strength=0.6,
                        description=f'20日均线支撑 {sma20:.4f}'
                    ))
                else:
                    resistance_levels.append(PriceLevel(
                        price=sma20,
                        level_type='resistance',
                        strength=0.6,
                        description=f'20日均线阻力 {sma20:.4f}'
                    ))
            
            if len(closes) >= 50:
                sma50 = np.mean(closes[-50:])
                if sma50 < current_price:
                    support_levels.append(PriceLevel(
                        price=sma50,
                        level_type='support',
                        strength=0.7,
                        description=f'50日均线支撑 {sma50:.4f}'
                    ))
                else:
                    resistance_levels.append(PriceLevel(
                        price=sma50,
                        level_type='resistance',
                        strength=0.7,
                        description=f'50日均线阻力 {sma50:.4f}'
                    ))
            
            # 按强度排序
            support_levels.sort(key=lambda x: x.strength, reverse=True)
            resistance_levels.sort(key=lambda x: x.strength, reverse=True)
            
            return support_levels[:3], resistance_levels[:3]  # 返回前3个最强的支撑阻力位
            
        except Exception as e:
            self.logger.error(f"计算支撑阻力位失败: {e}")
            return [], []
    
    async def _generate_overall_signal(
        self, 
        trend_analysis: Dict[str, Any], 
        momentum_analysis: Dict[str, Any],
        volume_analysis: Dict[str, Any], 
        volatility_analysis: Dict[str, Any]
    ) -> Tuple[TechnicalSignal, float]:
        """生成综合信号"""
        try:
            # 计算加权得分
            total_score = 0.0
            
            # 趋势权重40%
            trend_score = trend_analysis.get('score', 0.0) * 0.4
            total_score += trend_score
            
            # 动量权重25%
            momentum_score = momentum_analysis.get('score', 0.0) * 0.25
            total_score += momentum_score
            
            # 成交量权重25%
            volume_score = volume_analysis.get('score', 0.0) * 0.25
            total_score += volume_score
            
            # 波动率权重10%
            volatility_score = volatility_analysis.get('score', 0.0) * 0.1
            total_score += volatility_score
            
            # 计算置信度
            confidence = min(abs(total_score), 1.0)
            
            # 确定信号
            if total_score > 0.5:
                signal = TechnicalSignal.STRONG_BUY
            elif total_score > 0.2:
                signal = TechnicalSignal.BUY
            elif total_score < -0.5:
                signal = TechnicalSignal.STRONG_SELL
            elif total_score < -0.2:
                signal = TechnicalSignal.SELL
            else:
                signal = TechnicalSignal.NEUTRAL
            
            return signal, confidence
            
        except Exception as e:
            self.logger.error(f"生成综合信号失败: {e}")
            return TechnicalSignal.NEUTRAL, 0.0
    
    async def _generate_trading_recommendation(
        self,
        df: pd.DataFrame,
        signal: TechnicalSignal,
        confidence: float,
        support_levels: List[PriceLevel],
        resistance_levels: List[PriceLevel]
    ) -> TradingRecommendation:
        """生成交易建议"""
        try:
            current_price = df['close'].iloc[-1]
            
            # 计算ATR用于止损止盈
            atr = np.mean(df['high'].values[-14:] - df['low'].values[-14:])
            
            recommendation = TradingRecommendation(
                action=signal,
                confidence=confidence
            )
            
            if signal in [TechnicalSignal.BUY, TechnicalSignal.STRONG_BUY]:
                # 买入建议
                
                # 入场价格：当前价格或回调到支撑位
                if support_levels:
                    nearest_support = max(support_levels, key=lambda x: x.price if x.price < current_price else 0)
                    if nearest_support.price > 0:
                        entry_price = min(current_price, nearest_support.price * 1.002)  # 支撑位上方0.2%
                    else:
                        entry_price = current_price * 0.998  # 当前价格下方0.2%
                else:
                    entry_price = current_price * 0.998
                
                # 止损：最近支撑位下方或ATR
                if support_levels:
                    stop_loss = nearest_support.price * 0.995  # 支撑位下方0.5%
                else:
                    stop_loss = current_price - (atr * 2)  # 2倍ATR
                
                # 止盈：最近阻力位或风险回报比1:2
                risk = entry_price - stop_loss
                if resistance_levels:
                    nearest_resistance = min(resistance_levels, key=lambda x: x.price if x.price > current_price else float('inf'))
                    if nearest_resistance.price < float('inf'):
                        take_profit = min(nearest_resistance.price * 0.995, entry_price + risk * 2)
                    else:
                        take_profit = entry_price + risk * 2
                else:
                    take_profit = entry_price + risk * 2
                
                # 仓位建议
                if signal == TechnicalSignal.STRONG_BUY and confidence > 0.7:
                    position_size = 0.8  # 80%仓位
                elif signal == TechnicalSignal.STRONG_BUY:
                    position_size = 0.6  # 60%仓位
                elif confidence > 0.6:
                    position_size = 0.4  # 40%仓位
                else:
                    position_size = 0.2  # 20%仓位
                
                recommendation.entry_price = entry_price
                recommendation.stop_loss = stop_loss
                recommendation.take_profit = take_profit
                recommendation.position_size = position_size
                recommendation.risk_reward_ratio = (take_profit - entry_price) / (entry_price - stop_loss) if entry_price > stop_loss else 0
                
                recommendation.reasoning = f"技术面看多，建议在 {entry_price:.4f} 附近买入，止损 {stop_loss:.4f}，止盈 {take_profit:.4f}，风险回报比 1:{recommendation.risk_reward_ratio:.1f}"
                
            elif signal in [TechnicalSignal.SELL, TechnicalSignal.STRONG_SELL]:
                # 卖出建议
                
                # 入场价格：当前价格或反弹到阻力位
                if resistance_levels:
                    nearest_resistance = min(resistance_levels, key=lambda x: x.price if x.price > current_price else float('inf'))
                    if nearest_resistance.price < float('inf'):
                        entry_price = max(current_price, nearest_resistance.price * 0.998)  # 阻力位下方0.2%
                    else:
                        entry_price = current_price * 1.002  # 当前价格上方0.2%
                else:
                    entry_price = current_price * 1.002
                
                # 止损：最近阻力位上方或ATR
                if resistance_levels:
                    stop_loss = nearest_resistance.price * 1.005  # 阻力位上方0.5%
                else:
                    stop_loss = current_price + (atr * 2)  # 2倍ATR
                
                # 止盈：最近支撑位或风险回报比1:2
                risk = stop_loss - entry_price
                if support_levels:
                    nearest_support = max(support_levels, key=lambda x: x.price if x.price < current_price else 0)
                    if nearest_support.price > 0:
                        take_profit = max(nearest_support.price * 1.005, entry_price - risk * 2)
                    else:
                        take_profit = entry_price - risk * 2
                else:
                    take_profit = entry_price - risk * 2
                
                # 仓位建议
                if signal == TechnicalSignal.STRONG_SELL and confidence > 0.7:
                    position_size = 0.8  # 80%仓位
                elif signal == TechnicalSignal.STRONG_SELL:
                    position_size = 0.6  # 60%仓位
                elif confidence > 0.6:
                    position_size = 0.4  # 40%仓位
                else:
                    position_size = 0.2  # 20%仓位
                
                recommendation.entry_price = entry_price
                recommendation.stop_loss = stop_loss
                recommendation.take_profit = take_profit
                recommendation.position_size = position_size
                recommendation.risk_reward_ratio = (entry_price - take_profit) / (stop_loss - entry_price) if stop_loss > entry_price else 0
                
                recommendation.reasoning = f"技术面看空，建议在 {entry_price:.4f} 附近卖出，止损 {stop_loss:.4f}，止盈 {take_profit:.4f}，风险回报比 1:{recommendation.risk_reward_ratio:.1f}"
                
            else:
                # 中性建议
                recommendation.reasoning = "技术面信号不明确，建议观望等待更清晰的信号"
                recommendation.position_size = 0.0
            
            return recommendation
            
        except Exception as e:
            self.logger.error(f"生成交易建议失败: {e}")
            return TradingRecommendation(
                action=TechnicalSignal.NEUTRAL,
                confidence=0.0,
                reasoning="生成交易建议时发生错误"
            )
    
    async def _generate_detailed_reasoning(
        self,
        trend_analysis: Dict[str, Any],
        momentum_analysis: Dict[str, Any], 
        volume_analysis: Dict[str, Any],
        volatility_analysis: Dict[str, Any],
        recommendation: TradingRecommendation
    ) -> str:
        """生成详细推理"""
        try:
            reasoning_parts = []
            
            # 趋势分析推理
            trend_direction = trend_analysis.get('direction', 'neutral')
            trend_strength = trend_analysis.get('strength', 0.0)
            reasoning_parts.append(f"📈 趋势分析: {trend_direction} (强度: {trend_strength:.2f})")
            
            trend_signals = trend_analysis.get('signals', [])
            if trend_signals:
                trend_details = ", ".join([f"{signal[0]}:{signal[1]}" for signal in trend_signals[:3]])
                reasoning_parts.append(f"   主要信号: {trend_details}")
            
            # 动量分析推理
            momentum_state = momentum_analysis.get('state', 'neutral')
            momentum_strength = momentum_analysis.get('strength', 0.0)
            reasoning_parts.append(f"⚡ 动量分析: {momentum_state} (强度: {momentum_strength:.2f})")
            
            momentum_signals = momentum_analysis.get('signals', [])
            if momentum_signals:
                momentum_details = ", ".join([f"{signal[0]}:{signal[1]}" for signal in momentum_signals[:3]])
                reasoning_parts.append(f"   主要信号: {momentum_details}")
            
            # 成交量分析推理
            volume_state = volume_analysis.get('state', 'neutral')
            volume_strength = volume_analysis.get('strength', 0.0)
            volume_ratio = volume_analysis.get('volume_ratio', 1.0)
            reasoning_parts.append(f"📊 成交量分析: {volume_state} (强度: {volume_strength:.2f}, 量比: {volume_ratio:.1f})")
            
            volume_signals = volume_analysis.get('signals', [])
            if volume_signals:
                volume_details = ", ".join([f"{signal[0]}:{signal[1]}" for signal in volume_signals[:3]])
                reasoning_parts.append(f"   主要信号: {volume_details}")
            
            # 波动率分析推理
            volatility_state = volatility_analysis.get('state', 'neutral')
            volatility_strength = volatility_analysis.get('strength', 0.0)
            reasoning_parts.append(f"📉 波动率分析: {volatility_state} (强度: {volatility_strength:.2f})")
            
            # 交易建议推理
            reasoning_parts.append(f"🎯 交易建议: {recommendation.reasoning}")
            
            if recommendation.position_size and recommendation.position_size > 0:
                reasoning_parts.append(f"💰 建议仓位: {recommendation.position_size*100:.0f}%")
                if recommendation.risk_reward_ratio:
                    reasoning_parts.append(f"⚖️ 风险回报比: 1:{recommendation.risk_reward_ratio:.1f}")
            
            return "".join(reasoning_parts)
            
        except Exception as e:
            self.logger.error(f"生成详细推理失败: {e}")
            return "技术分析推理生成失败"


# 全局服务实例
_enhanced_technical_analysis_service: Optional[EnhancedTechnicalAnalysisService] = None

async def get_enhanced_technical_analysis_service() -> EnhancedTechnicalAnalysisService:
    """获取增强版技术分析服务实例"""
    global _enhanced_technical_analysis_service
    if _enhanced_technical_analysis_service is None:
        _enhanced_technical_analysis_service = EnhancedTechnicalAnalysisService()
        await _enhanced_technical_analysis_service.initialize()
    return _enhanced_technical_analysis_service