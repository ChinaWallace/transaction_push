# -*- coding: utf-8 -*-
"""
增强版量价分析服务
Enhanced Volume Price Analysis Service - 专注于量价关系分析
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

logger = get_logger(__name__)


class VolumePattern(Enum):
    """成交量模式"""
    ACCUMULATION = "吸筹"           # 价格横盘，成交量增加
    DISTRIBUTION = "派发"           # 价格横盘，成交量减少
    BREAKOUT_VOLUME = "突破放量"    # 价格突破，成交量放大
    EXHAUSTION = "量能衰竭"         # 价格上涨，成交量萎缩
    CLIMAX = "高潮"                # 价格和成交量都达到极值
    NORMAL = "正常"                # 正常的量价关系


class PriceTrend(Enum):
    """价格趋势"""
    STRONG_UP = "强势上涨"
    WEAK_UP = "弱势上涨"
    SIDEWAYS = "横盘整理"
    WEAK_DOWN = "弱势下跌"
    STRONG_DOWN = "强势下跌"


@dataclass
class VolumeAnalysis:
    """成交量分析结果"""
    current_volume: float
    avg_volume: float
    volume_ratio: float
    volume_trend: str  # 'increasing', 'decreasing', 'stable'
    volume_percentile: float  # 当前成交量在历史中的百分位


@dataclass
class PriceVolumeRelation:
    """量价关系"""
    price_change: float
    volume_change: float
    correlation: float  # 量价相关性
    divergence_detected: bool
    divergence_type: Optional[str]  # 'bullish', 'bearish'
    pattern: VolumePattern


@dataclass
class VolumeIndicators:
    """成交量指标"""
    obv: float
    obv_trend: str
    vwap: float
    vwap_position: str  # 'above', 'below'
    mfi: float
    mfi_signal: str
    volume_oscillator: float
    accumulation_distribution: float


@dataclass
class EnhancedVolumePriceAnalysis:
    """增强版量价分析结果"""
    symbol: str
    timestamp: datetime
    current_price: float
    
    # 成交量分析
    volume_analysis: VolumeAnalysis
    
    # 量价关系
    price_volume_relation: PriceVolumeRelation
    
    # 成交量指标
    volume_indicators: VolumeIndicators
    
    # 综合评估
    overall_signal: str  # 'bullish', 'bearish', 'neutral'
    confidence: float
    
    # 详细分析
    key_observations: List[str]
    trading_implications: List[str]
    
    # 风险提示
    risk_factors: List[str]


class EnhancedVolumePriceAnalysisService:
    """增强版量价分析服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.exchange_service = None
        self.initialized = False
    
    async def initialize(self) -> None:
        """初始化服务"""
        if self.initialized:
            return
            
        try:
            self.exchange_service = await get_exchange_service()
            self.initialized = True
            self.logger.info("✅ 增强版量价分析服务初始化完成")
        except Exception as e:
            self.logger.error(f"❌ 增强版量价分析服务初始化失败: {e}")
            raise
    
    async def analyze_volume_price(self, symbol: str, timeframe: str = "1h") -> Optional[EnhancedVolumePriceAnalysis]:
        """分析量价关系"""
        try:
            if not self.initialized:
                await self.initialize()
            
            # 获取市场数据
            market_data = await self._fetch_market_data(symbol, timeframe)
            if market_data is None or len(market_data) < 50:
                self.logger.warning(f"数据不足，无法进行量价分析 {symbol}")
                return None
            
            # 成交量分析
            volume_analysis = await self._analyze_volume(market_data)
            
            # 量价关系分析
            price_volume_relation = await self._analyze_price_volume_relation(market_data)
            
            # 计算成交量指标
            volume_indicators = await self._calculate_volume_indicators(market_data)
            
            # 生成综合信号
            overall_signal, confidence = await self._generate_volume_signal(
                volume_analysis, price_volume_relation, volume_indicators
            )
            
            # 生成关键观察和交易含义
            key_observations = await self._generate_key_observations(
                volume_analysis, price_volume_relation, volume_indicators
            )
            
            trading_implications = await self._generate_trading_implications(
                overall_signal, confidence, price_volume_relation
            )
            
            risk_factors = await self._identify_risk_factors(
                volume_analysis, price_volume_relation
            )
            
            current_price = float(market_data['close'].iloc[-1])
            
            return EnhancedVolumePriceAnalysis(
                symbol=symbol,
                timestamp=datetime.now(),
                current_price=current_price,
                volume_analysis=volume_analysis,
                price_volume_relation=price_volume_relation,
                volume_indicators=volume_indicators,
                overall_signal=overall_signal,
                confidence=confidence,
                key_observations=key_observations,
                trading_implications=trading_implications,
                risk_factors=risk_factors
            )
            
        except Exception as e:
            self.logger.error(f"量价分析失败 {symbol}: {e}")
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
    
    async def _analyze_volume(self, df: pd.DataFrame) -> VolumeAnalysis:
        """分析成交量"""
        try:
            volumes = df['volume'].values
            current_volume = volumes[-1]
            
            # 计算平均成交量
            avg_volume_20 = np.mean(volumes[-20:])
            avg_volume_50 = np.mean(volumes[-50:]) if len(volumes) >= 50 else avg_volume_20
            
            # 成交量比率
            volume_ratio = current_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0
            
            # 成交量趋势
            recent_volumes = volumes[-10:]
            if len(recent_volumes) >= 5:
                volume_slope = np.polyfit(range(len(recent_volumes)), recent_volumes, 1)[0]
                if volume_slope > avg_volume_20 * 0.05:
                    volume_trend = 'increasing'
                elif volume_slope < -avg_volume_20 * 0.05:
                    volume_trend = 'decreasing'
                else:
                    volume_trend = 'stable'
            else:
                volume_trend = 'stable'
            
            # 成交量百分位
            volume_percentile = (np.sum(volumes <= current_volume) / len(volumes)) * 100
            
            return VolumeAnalysis(
                current_volume=current_volume,
                avg_volume=avg_volume_20,
                volume_ratio=volume_ratio,
                volume_trend=volume_trend,
                volume_percentile=volume_percentile
            )
            
        except Exception as e:
            self.logger.error(f"成交量分析失败: {e}")
            return VolumeAnalysis(0, 0, 1.0, 'stable', 50.0)
    
    async def _analyze_price_volume_relation(self, df: pd.DataFrame) -> PriceVolumeRelation:
        """分析量价关系"""
        try:
            prices = df['close'].values
            volumes = df['volume'].values
            
            # 计算价格和成交量变化
            price_changes = np.diff(prices) / prices[:-1]
            volume_changes = np.diff(volumes) / volumes[:-1]
            
            # 最近的价格和成交量变化
            recent_price_change = price_changes[-1] if len(price_changes) > 0 else 0
            recent_volume_change = volume_changes[-1] if len(volume_changes) > 0 else 0
            
            # 计算量价相关性
            if len(price_changes) >= 20:
                correlation = np.corrcoef(price_changes[-20:], volume_changes[-20:])[0, 1]
                if np.isnan(correlation):
                    correlation = 0.0
            else:
                correlation = 0.0
            
            # 检测量价背离
            divergence_detected = False
            divergence_type = None
            
            # 检查最近5个周期的量价关系
            if len(price_changes) >= 5 and len(volume_changes) >= 5:
                recent_price_trend = np.mean(price_changes[-5:])
                recent_volume_trend = np.mean(volume_changes[-5:])
                
                # 价格上涨但成交量下降 - 看跌背离
                if recent_price_trend > 0.01 and recent_volume_trend < -0.1:
                    divergence_detected = True
                    divergence_type = 'bearish'
                
                # 价格下跌但成交量上升 - 看涨背离
                elif recent_price_trend < -0.01 and recent_volume_trend > 0.1:
                    divergence_detected = True
                    divergence_type = 'bullish'
            
            # 确定量价模式
            pattern = await self._identify_volume_pattern(
                recent_price_change, recent_volume_change, correlation
            )
            
            return PriceVolumeRelation(
                price_change=recent_price_change,
                volume_change=recent_volume_change,
                correlation=correlation,
                divergence_detected=divergence_detected,
                divergence_type=divergence_type,
                pattern=pattern
            )
            
        except Exception as e:
            self.logger.error(f"量价关系分析失败: {e}")
            return PriceVolumeRelation(0, 0, 0, False, None, VolumePattern.NORMAL)
    
    async def _identify_volume_pattern(self, price_change: float, volume_change: float, correlation: float) -> VolumePattern:
        """识别成交量模式"""
        try:
            # 突破放量：价格大幅变动且成交量放大
            if abs(price_change) > 0.03 and volume_change > 0.5:
                return VolumePattern.BREAKOUT_VOLUME
            
            # 量能衰竭：价格上涨但成交量萎缩
            if price_change > 0.02 and volume_change < -0.3:
                return VolumePattern.EXHAUSTION
            
            # 吸筹：价格横盘但成交量增加
            if abs(price_change) < 0.01 and volume_change > 0.3:
                return VolumePattern.ACCUMULATION
            
            # 派发：价格横盘但成交量减少
            if abs(price_change) < 0.01 and volume_change < -0.3:
                return VolumePattern.DISTRIBUTION
            
            # 高潮：价格和成交量都达到极值
            if abs(price_change) > 0.05 and volume_change > 1.0:
                return VolumePattern.CLIMAX
            
            return VolumePattern.NORMAL
            
        except Exception as e:
            self.logger.error(f"识别成交量模式失败: {e}")
            return VolumePattern.NORMAL
    
    async def _calculate_volume_indicators(self, df: pd.DataFrame) -> VolumeIndicators:
        """计算成交量指标"""
        try:
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values
            volume = df['volume'].values
            
            current_price = close[-1]
            
            # OBV (On Balance Volume)
            obv = talib.OBV(close, volume)
            current_obv = obv[-1]
            
            # OBV趋势
            if len(obv) >= 10:
                obv_slope = np.polyfit(range(10), obv[-10:], 1)[0]
                if obv_slope > 0:
                    obv_trend = 'increasing'
                elif obv_slope < 0:
                    obv_trend = 'decreasing'
                else:
                    obv_trend = 'stable'
            else:
                obv_trend = 'stable'
            
            # VWAP (Volume Weighted Average Price)
            typical_price = (high + low + close) / 3
            vwap_num = np.cumsum(typical_price * volume)
            vwap_den = np.cumsum(volume)
            vwap = vwap_num / vwap_den
            current_vwap = vwap[-1]
            
            # VWAP位置
            vwap_position = 'above' if current_price > current_vwap else 'below'
            
            # MFI (Money Flow Index)
            mfi = talib.MFI(high, low, close, volume, timeperiod=14)
            current_mfi = mfi[-1] if not np.isnan(mfi[-1]) else 50.0
            
            # MFI信号
            if current_mfi > 80:
                mfi_signal = 'overbought'
            elif current_mfi < 20:
                mfi_signal = 'oversold'
            elif current_mfi > 50:
                mfi_signal = 'bullish'
            else:
                mfi_signal = 'bearish'
            
            # Volume Oscillator
            volume_short = talib.SMA(volume, timeperiod=5)
            volume_long = talib.SMA(volume, timeperiod=20)
            volume_oscillator = ((volume_short[-1] - volume_long[-1]) / volume_long[-1] * 100) if volume_long[-1] > 0 else 0
            
            # Accumulation/Distribution Line
            ad_line = talib.AD(high, low, close, volume)
            current_ad = ad_line[-1]
            
            return VolumeIndicators(
                obv=current_obv,
                obv_trend=obv_trend,
                vwap=current_vwap,
                vwap_position=vwap_position,
                mfi=current_mfi,
                mfi_signal=mfi_signal,
                volume_oscillator=volume_oscillator,
                accumulation_distribution=current_ad
            )
            
        except Exception as e:
            self.logger.error(f"计算成交量指标失败: {e}")
            return VolumeIndicators(0, 'stable', 0, 'below', 50, 'neutral', 0, 0)
    
    async def _generate_volume_signal(
        self, 
        volume_analysis: VolumeAnalysis,
        price_volume_relation: PriceVolumeRelation,
        volume_indicators: VolumeIndicators
    ) -> Tuple[str, float]:
        """生成成交量信号"""
        try:
            bullish_signals = 0
            bearish_signals = 0
            signal_strength = 0.0
            
            # 成交量分析信号
            if volume_analysis.volume_ratio > 1.5:  # 放量
                if volume_analysis.volume_trend == 'increasing':
                    bullish_signals += 1
                    signal_strength += 0.15
            elif volume_analysis.volume_ratio < 0.5:  # 缩量
                bearish_signals += 1
                signal_strength -= 0.10
            
            # 量价关系信号
            if price_volume_relation.divergence_detected:
                if price_volume_relation.divergence_type == 'bullish':
                    bullish_signals += 2  # 量价背离是强信号
                    signal_strength += 0.25
                elif price_volume_relation.divergence_type == 'bearish':
                    bearish_signals += 2
                    signal_strength -= 0.25
            
            # 量价模式信号
            pattern = price_volume_relation.pattern
            if pattern == VolumePattern.BREAKOUT_VOLUME:
                if price_volume_relation.price_change > 0:
                    bullish_signals += 2
                    signal_strength += 0.30
                else:
                    bearish_signals += 2
                    signal_strength -= 0.30
            elif pattern == VolumePattern.ACCUMULATION:
                bullish_signals += 1
                signal_strength += 0.20
            elif pattern == VolumePattern.DISTRIBUTION:
                bearish_signals += 1
                signal_strength -= 0.20
            elif pattern == VolumePattern.EXHAUSTION:
                bearish_signals += 1
                signal_strength -= 0.15
            
            # OBV信号
            if volume_indicators.obv_trend == 'increasing':
                bullish_signals += 1
                signal_strength += 0.15
            elif volume_indicators.obv_trend == 'decreasing':
                bearish_signals += 1
                signal_strength -= 0.15
            
            # VWAP信号
            if volume_indicators.vwap_position == 'above':
                bullish_signals += 1
                signal_strength += 0.10
            else:
                bearish_signals += 1
                signal_strength -= 0.10
            
            # MFI信号
            if volume_indicators.mfi_signal == 'oversold':
                bullish_signals += 1
                signal_strength += 0.15
            elif volume_indicators.mfi_signal == 'overbought':
                bearish_signals += 1
                signal_strength -= 0.15
            elif volume_indicators.mfi_signal == 'bullish':
                bullish_signals += 1
                signal_strength += 0.05
            elif volume_indicators.mfi_signal == 'bearish':
                bearish_signals += 1
                signal_strength -= 0.05
            
            # Volume Oscillator信号
            if volume_indicators.volume_oscillator > 20:
                bullish_signals += 1
                signal_strength += 0.10
            elif volume_indicators.volume_oscillator < -20:
                bearish_signals += 1
                signal_strength -= 0.10
            
            # 确定最终信号
            confidence = min(abs(signal_strength), 1.0)
            
            if bullish_signals > bearish_signals and signal_strength > 0.2:
                overall_signal = 'bullish'
            elif bearish_signals > bullish_signals and signal_strength < -0.2:
                overall_signal = 'bearish'
            else:
                overall_signal = 'neutral'
                confidence = max(confidence, 0.1)  # 中性信号也有一定置信度
            
            return overall_signal, confidence
            
        except Exception as e:
            self.logger.error(f"生成成交量信号失败: {e}")
            return 'neutral', 0.0
    
    async def _generate_key_observations(
        self,
        volume_analysis: VolumeAnalysis,
        price_volume_relation: PriceVolumeRelation,
        volume_indicators: VolumeIndicators
    ) -> List[str]:
        """生成关键观察"""
        try:
            observations = []
            
            # 成交量观察
            if volume_analysis.volume_ratio > 2.0:
                observations.append(f"🔥 异常放量 {volume_analysis.volume_ratio:.1f}倍，市场关注度极高")
            elif volume_analysis.volume_ratio > 1.5:
                observations.append(f"📈 明显放量 {volume_analysis.volume_ratio:.1f}倍，资金活跃")
            elif volume_analysis.volume_ratio < 0.5:
                observations.append(f"📉 成交量萎缩至 {volume_analysis.volume_ratio:.1f}倍，市场观望情绪浓厚")
            
            # 成交量趋势观察
            if volume_analysis.volume_trend == 'increasing':
                observations.append("📊 成交量呈上升趋势，资金持续流入")
            elif volume_analysis.volume_trend == 'decreasing':
                observations.append("📊 成交量呈下降趋势，市场参与度降低")
            
            # 量价背离观察
            if price_volume_relation.divergence_detected:
                if price_volume_relation.divergence_type == 'bullish':
                    observations.append("⚠️ 检测到看涨量价背离，价格下跌但成交量放大，可能见底")
                elif price_volume_relation.divergence_type == 'bearish':
                    observations.append("⚠️ 检测到看跌量价背离，价格上涨但成交量萎缩，上涨乏力")
            
            # 量价模式观察
            pattern = price_volume_relation.pattern
            if pattern == VolumePattern.BREAKOUT_VOLUME:
                observations.append("🚀 突破放量，价格突破伴随成交量放大，信号较强")
            elif pattern == VolumePattern.ACCUMULATION:
                observations.append("🏗️ 吸筹模式，价格横盘但成交量增加，可能有主力建仓")
            elif pattern == VolumePattern.DISTRIBUTION:
                observations.append("📦 派发模式，价格横盘但成交量减少，可能有主力出货")
            elif pattern == VolumePattern.EXHAUSTION:
                observations.append("😴 量能衰竭，价格上涨但成交量萎缩，上涨动能不足")
            elif pattern == VolumePattern.CLIMAX:
                observations.append("💥 成交量高潮，价格和成交量都达到极值，可能出现反转")
            
            # OBV观察
            if volume_indicators.obv_trend == 'increasing':
                observations.append("📈 OBV上升趋势，累积成交量支持价格上涨")
            elif volume_indicators.obv_trend == 'decreasing':
                observations.append("📉 OBV下降趋势，累积成交量显示抛压增加")
            
            # VWAP观察
            if volume_indicators.vwap_position == 'above':
                observations.append(f"🎯 价格位于VWAP({volume_indicators.vwap:.4f})上方，短期强势")
            else:
                observations.append(f"🎯 价格位于VWAP({volume_indicators.vwap:.4f})下方，短期弱势")
            
            # MFI观察
            if volume_indicators.mfi_signal == 'overbought':
                observations.append(f"⚡ MFI({volume_indicators.mfi:.1f})显示超买，资金流入过度")
            elif volume_indicators.mfi_signal == 'oversold':
                observations.append(f"⚡ MFI({volume_indicators.mfi:.1f})显示超卖，可能出现反弹")
            
            return observations
            
        except Exception as e:
            self.logger.error(f"生成关键观察失败: {e}")
            return ["量价分析观察生成失败"]
    
    async def _generate_trading_implications(
        self, 
        overall_signal: str, 
        confidence: float,
        price_volume_relation: PriceVolumeRelation
    ) -> List[str]:
        """生成交易含义"""
        try:
            implications = []
            
            if overall_signal == 'bullish':
                if confidence > 0.7:
                    implications.append("💪 强烈看多信号，建议积极做多")
                    implications.append("📈 可考虑加大仓位，但注意风险控制")
                elif confidence > 0.5:
                    implications.append("👍 看多信号，建议适度做多")
                    implications.append("⚖️ 建议分批建仓，控制风险")
                else:
                    implications.append("🤔 弱看多信号，谨慎做多")
                    implications.append("👀 建议观察更多确认信号")
                
                # 特殊模式的交易含义
                if price_volume_relation.pattern == VolumePattern.BREAKOUT_VOLUME:
                    implications.append("🚀 突破放量，可考虑追涨，但设好止损")
                elif price_volume_relation.pattern == VolumePattern.ACCUMULATION:
                    implications.append("🏗️ 吸筹阶段，适合中长线布局")
                
            elif overall_signal == 'bearish':
                if confidence > 0.7:
                    implications.append("💀 强烈看空信号，建议积极做空或减仓")
                    implications.append("📉 可考虑增加空头仓位")
                elif confidence > 0.5:
                    implications.append("👎 看空信号，建议适度做空或减仓")
                    implications.append("⚖️ 建议分批减仓，保护利润")
                else:
                    implications.append("🤔 弱看空信号，谨慎做空")
                    implications.append("👀 建议观察更多确认信号")
                
                # 特殊模式的交易含义
                if price_volume_relation.pattern == VolumePattern.DISTRIBUTION:
                    implications.append("📦 派发阶段，建议逐步减仓")
                elif price_volume_relation.pattern == VolumePattern.EXHAUSTION:
                    implications.append("😴 上涨乏力，注意高位风险")
                
            else:  # neutral
                implications.append("😐 量价信号不明确，建议观望")
                implications.append("👀 等待更清晰的量价配合信号")
                implications.append("⚖️ 如有仓位，建议保持现状")
            
            return implications
            
        except Exception as e:
            self.logger.error(f"生成交易含义失败: {e}")
            return ["交易含义生成失败"]
    
    async def _identify_risk_factors(
        self,
        volume_analysis: VolumeAnalysis,
        price_volume_relation: PriceVolumeRelation
    ) -> List[str]:
        """识别风险因素"""
        try:
            risk_factors = []
            
            # 成交量风险
            if volume_analysis.volume_ratio > 3.0:
                risk_factors.append("⚠️ 成交量异常放大，可能存在操纵风险")
            elif volume_analysis.volume_ratio < 0.3:
                risk_factors.append("⚠️ 成交量极度萎缩，流动性风险较高")
            
            # 量价背离风险
            if price_volume_relation.divergence_detected:
                if price_volume_relation.divergence_type == 'bearish':
                    risk_factors.append("⚠️ 看跌量价背离，上涨可能不可持续")
                elif price_volume_relation.divergence_type == 'bullish':
                    risk_factors.append("⚠️ 看涨量价背离，下跌可能接近尾声但需确认")
            
            # 模式风险
            pattern = price_volume_relation.pattern
            if pattern == VolumePattern.CLIMAX:
                risk_factors.append("⚠️ 成交量高潮，可能出现急剧反转")
            elif pattern == VolumePattern.EXHAUSTION:
                risk_factors.append("⚠️ 量能衰竭，上涨动能不足，注意回调风险")
            
            # 相关性风险
            if abs(price_volume_relation.correlation) < 0.3:
                risk_factors.append("⚠️ 量价相关性较低，信号可靠性降低")
            
            return risk_factors
            
        except Exception as e:
            self.logger.error(f"识别风险因素失败: {e}")
            return ["风险因素识别失败"]
    
    async def analyze_volume_price_relationship(self, symbol: str, timeframe: str = "1h") -> Optional[EnhancedVolumePriceAnalysis]:
        """分析量价关系 - 向后兼容别名"""
        return await self.analyze_volume_price(symbol, timeframe)


# 全局服务实例
_enhanced_volume_price_analysis_service: Optional[EnhancedVolumePriceAnalysisService] = None

async def get_enhanced_volume_price_analysis_service() -> EnhancedVolumePriceAnalysisService:
    """获取增强版量价分析服务实例"""
    global _enhanced_volume_price_analysis_service
    if _enhanced_volume_price_analysis_service is None:
        _enhanced_volume_price_analysis_service = EnhancedVolumePriceAnalysisService()
        await _enhanced_volume_price_analysis_service.initialize()
    return _enhanced_volume_price_analysis_service