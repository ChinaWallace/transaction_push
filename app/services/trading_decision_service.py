# -*- coding: utf-8 -*-
"""
交易决策服务
Trading Decision Service - 融合传统技术分析和机器学习的综合交易决策系统
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import asyncio
import numpy as np
import pandas as pd

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.core.technical_analysis_config import get_technical_config
from app.services.ml_enhanced_service import MLEnhancedService, PredictionSignal
# from app.services.trend_analysis_service import TrendAnalysisService  # 已禁用，有问题
from app.services.binance_service import BinanceService
from app.services.okx_service import OKXService
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class TradingAction(Enum):
    """交易动作枚举"""
    STRONG_BUY = "强烈买入"
    BUY = "买入"
    HOLD = "持有"
    SELL = "卖出"
    STRONG_SELL = "强烈卖出"
    WAIT = "等待"  # 等待更好的入场时机


class RiskLevel(Enum):
    """风险等级枚举"""
    VERY_LOW = "极低风险"
    LOW = "低风险"
    MEDIUM = "中等风险"
    HIGH = "高风险"
    VERY_HIGH = "极高风险"


@dataclass
class TradingRecommendation:
    """交易建议"""
    symbol: str
    action: TradingAction
    confidence: float
    
    # 核心交易参数
    position_size_usdt: float    # 建议仓位金额(USDT)
    position_size_percent: float # 建议仓位百分比
    leverage: float              # 建议杠杆倍数
    
    # 价格点位
    entry_price: float           # 建议入场价格
    stop_loss_price: float       # 止损价格
    take_profit_price: float     # 止盈价格
    
    # 风险管理
    risk_level: RiskLevel
    max_loss_usdt: float         # 最大亏损金额
    expected_profit_usdt: float  # 预期盈利金额
    risk_reward_ratio: float     # 风险收益比
    
    # 执行建议
    entry_timing: str            # 入场时机
    hold_duration_hours: Optional[int]  # 持仓时间
    
    # 决策依据
    reasoning: str               # 决策理由
    key_levels: Dict[str, List[float]]  # 关键价位
    
    # 当前市场状态
    current_price: float
    current_positions: Dict[str, Any]  # 当前持仓
    account_info: Dict[str, Any]       # 账户信息


@dataclass
class MarketAnalysis:
    """市场分析结果"""
    symbol: str
    timestamp: datetime
    
    # 传统技术分析
    traditional_signals: Dict[str, Any]
    
    # 机器学习分析
    ml_prediction: Dict[str, Any]
    ml_anomalies: List[Dict[str, Any]]
    
    # 综合评分
    bullish_score: float    # 看涨评分 (0-100)
    bearish_score: float    # 看跌评分 (0-100)
    volatility_score: float # 波动性评分 (0-100)
    
    # 市场状态
    market_regime: str      # "trending", "ranging", "volatile", "calm"
    trend_strength: float   # 趋势强度 (0-1)


class TradingDecisionService:
    """交易决策服务类"""
    
    def __init__(self, exchange: str = 'okx'):
        self.exchange = exchange.lower()
        
        # 初始化服务
        if self.exchange == 'okx':
            self.exchange_service = OKXService()
        else:
            self.exchange_service = BinanceService()
        
        # 可选的ML服务（如果需要）
        try:
            self.ml_service = MLEnhancedService()
            # self.trend_service = TrendAnalysisService()  # 已禁用，有问题
            self.trend_service = None  # 不使用有问题的TrendAnalysisService
            self.ml_enabled = True
        except Exception as e:
            logger.warning(f"ML服务初始化失败，将使用基础技术分析: {e}")
            self.ml_service = None
            self.trend_service = None
            self.ml_enabled = False
        
        # 技术分析配置
        self.tech_config = get_technical_config()
        
        # 风险管理参数
        self.max_position_percent = 25.0  # 单个交易对最大仓位25%
        self.max_leverage = 3.0           # 最大杠杆3倍（保守）
        self.base_stop_loss = 0.03        # 基础止损3%
        self.base_take_profit = 0.09      # 基础止盈9% (1:3风险收益比)
    
    async def analyze_market(self, symbol: str) -> MarketAnalysis:
        """
        综合市场分析 - 使用内置技术分析，不依赖TrendAnalysisService
        
        Args:
            symbol: 交易对
            
        Returns:
            市场分析结果
        """
        try:
            # 使用内置的市场信号分析替代TrendAnalysisService
            async with self.exchange_service as exchange:
                market_signals = await self._get_market_signals(symbol, exchange)
            
            # 转换为传统分析格式
            traditional_analysis = {
                'overall_signal': 'strong_buy' if market_signals.get('trend') == 'bullish' and market_signals.get('confidence', 0) > 75 
                                 else 'buy' if market_signals.get('trend') == 'bullish' and market_signals.get('confidence', 0) > 55
                                 else 'strong_sell' if market_signals.get('trend') == 'bearish' and market_signals.get('confidence', 0) > 75
                                 else 'sell' if market_signals.get('trend') == 'bearish' and market_signals.get('confidence', 0) > 55
                                 else 'hold',
                'signal_strength': market_signals.get('confidence', 50.0) / 100.0,
                'trend_direction': market_signals.get('trend', 'neutral'),
                'volatility_score': 80.0 if market_signals.get('volatility') == 'high' 
                                   else 30.0 if market_signals.get('volatility') == 'low' 
                                   else 50.0,
                'volume_anomaly': market_signals.get('volume_anomaly', False),
                'funding_rate_signal': market_signals.get('funding_rate_signal', 'neutral')
            }
            
            # 获取ML分析（如果可用）
            ml_prediction = None
            ml_anomalies = []
            
            if self.ml_service:
                try:
                    ml_prediction = await self.ml_service.predict_signal(symbol)
                except Exception as e:
                    logger.warning(f"ML prediction failed for {symbol}: {e}")
                
                try:
                    ml_anomalies = await self.ml_service.detect_anomalies(symbol)
                except Exception as e:
                    logger.warning(f"ML anomaly detection failed for {symbol}: {e}")
                    ml_anomalies = []
            
            # 计算综合评分
            bullish_score, bearish_score, volatility_score = self._calculate_scores(
                traditional_analysis, ml_prediction, ml_anomalies
            )
            
            # 判断市场状态
            market_regime, trend_strength = self._analyze_market_regime(
                traditional_analysis, volatility_score
            )
            
            # 将详细技术指标合并到traditional_signals中
            traditional_analysis.update(market_signals)  # 包含所有技术指标数据
            
            return MarketAnalysis(
                symbol=symbol,
                timestamp=datetime.now(),
                traditional_signals=traditional_analysis,
                ml_prediction=self._format_ml_prediction(ml_prediction),
                ml_anomalies=self._format_ml_anomalies(ml_anomalies),
                bullish_score=bullish_score,
                bearish_score=bearish_score,
                volatility_score=volatility_score,
                market_regime=market_regime,
                trend_strength=trend_strength
            )
            
        except Exception as e:
            logger.error(f"Market analysis failed for {symbol}: {e}")
            raise TradingToolError(f"Market analysis failed: {e}")
    
    async def get_trading_recommendation(self, symbol: str) -> TradingRecommendation:
        """
        获取交易建议 - 基于实际账户和持仓情况
        
        Args:
            symbol: 交易对 (如: BTC-USDT-SWAP)
            
        Returns:
            交易建议
        """
        try:
            async with self.exchange_service as exchange:
                # 并行获取数据
                tasks = [
                    exchange.get_current_price(symbol),
                    exchange.get_account_balance(),
                    exchange.get_positions(),
                    self._get_market_signals(symbol, exchange)
                ]
                
                current_price, account_info, positions, market_signals = await asyncio.gather(*tasks)
                
                if not current_price:
                    raise TradingToolError(f"无法获取{symbol}当前价格")
                
                # 分析当前持仓
                current_position = self._find_current_position(symbol, positions)
                
                # 计算交易动作
                action = self._determine_action_from_signals(market_signals)
                
                # 计算仓位和风险参数
                position_params = self._calculate_position_parameters(
                    action, current_price, account_info, current_position, market_signals
                )
                
                # 计算价格点位
                price_levels = self._calculate_price_levels(
                    action, current_price, market_signals
                )
                
                # 生成决策理由
                reasoning = self._generate_trading_reasoning(market_signals, action, position_params)
                
                return TradingRecommendation(
                    symbol=symbol,
                    action=action,
                    confidence=market_signals.get('confidence', 50.0),
                    
                    # 核心交易参数
                    position_size_usdt=position_params['size_usdt'],
                    position_size_percent=position_params['size_percent'],
                    leverage=position_params['leverage'],
                    
                    # 价格点位
                    entry_price=price_levels['entry'],
                    stop_loss_price=price_levels['stop_loss'],
                    take_profit_price=price_levels['take_profit'],
                    
                    # 风险管理
                    risk_level=position_params['risk_level'],
                    max_loss_usdt=position_params['max_loss'],
                    expected_profit_usdt=position_params['expected_profit'],
                    risk_reward_ratio=position_params['risk_reward_ratio'],
                    
                    # 执行建议
                    entry_timing=self._determine_entry_timing(market_signals, action),
                    hold_duration_hours=self._estimate_hold_duration(market_signals, action),
                    
                    # 决策依据
                    reasoning=reasoning,
                    key_levels=price_levels.get('key_levels', {}),
                    
                    # 当前状态
                    current_price=current_price,
                    current_positions=current_position,
                    account_info=account_info
                )
            
        except Exception as e:
            logger.error(f"获取{symbol}交易建议失败: {e}")
            raise TradingToolError(f"获取交易建议失败: {e}")
    
    async def _get_market_signals(self, symbol: str, exchange) -> Dict[str, Any]:
        """获取市场信号 - 完全基于OKX数据，包含完整技术分析指标"""
        signals = {
            'confidence': 50.0,
            'trend': 'neutral',
            'volatility': 'medium',
            'volume_anomaly': False,
            'funding_rate_signal': 'neutral',
            'technical_indicators': {}  # 存储所有技术指标
        }
        
        try:
            # 获取基础数据 - 扩展到50根K线以支持更多指标
            klines = await exchange.get_kline_data(symbol, '1H', 50)
            funding_rate = await exchange.get_funding_rate(symbol)
            
            if klines and len(klines) >= 30:
                # 提取OHLCV数据
                closes = [k['close'] for k in klines]
                highs = [k['high'] for k in klines]
                lows = [k['low'] for k in klines]
                volumes = [k['volume'] for k in klines]
                opens = [k['open'] for k in klines]
                
                current_price = closes[-1]
                
                # ========== 移动平均线分析 (MA) ==========
                sma_5 = sum(closes[-5:]) / 5
                sma_10 = sum(closes[-10:]) / 10
                sma_20 = sum(closes[-20:]) / 20
                sma_30 = sum(closes[-30:]) / 30
                
                # EMA指数移动平均
                ema_12 = self._calculate_ema(closes, 12)
                ema_26 = self._calculate_ema(closes, 26)
                
                signals['technical_indicators']['sma_5'] = sma_5
                signals['technical_indicators']['sma_10'] = sma_10
                signals['technical_indicators']['sma_20'] = sma_20
                signals['technical_indicators']['ema_12'] = ema_12
                signals['technical_indicators']['ema_26'] = ema_26
                
                # ========== RSI相对强弱指数 ==========
                rsi_14 = self._calculate_rsi(closes, 14)
                signals['technical_indicators']['rsi_14'] = rsi_14
                
                # ========== MACD指标 ==========
                macd_line, macd_signal, macd_histogram = self._calculate_macd(closes)
                signals['technical_indicators']['macd_line'] = macd_line
                signals['technical_indicators']['macd_signal'] = macd_signal
                signals['technical_indicators']['macd_histogram'] = macd_histogram
                
                # ========== 布林带 (Bollinger Bands) ==========
                bb_upper, bb_middle, bb_lower = self._calculate_bollinger_bands(closes, 20, 2)
                signals['technical_indicators']['bb_upper'] = bb_upper
                signals['technical_indicators']['bb_middle'] = bb_middle
                signals['technical_indicators']['bb_lower'] = bb_lower
                
                # ========== KDJ随机指标 ==========
                k_value, d_value, j_value = self._calculate_kdj(highs, lows, closes, 9, 3, 3)
                signals['technical_indicators']['kdj_k'] = k_value
                signals['technical_indicators']['kdj_d'] = d_value
                signals['technical_indicators']['kdj_j'] = j_value
                
                # ========== ATR平均真实波幅 ==========
                atr_14 = self._calculate_atr(highs, lows, closes, 14)
                signals['technical_indicators']['atr_14'] = atr_14
                
                # ========== 威廉指标 %R ==========
                williams_r = self._calculate_williams_r(highs, lows, closes, 14)
                signals['technical_indicators']['williams_r'] = williams_r
                
                # ========== 综合技术分析评分系统 ==========
                config = self.tech_config.get_config()
                weights = config.indicator_weights
                
                trend_score = 0
                bullish_signals = 0
                bearish_signals = 0
                
                # 1. 均线排列分析 (动态权重)
                ma_weight = weights.get('moving_averages', 25)
                ma_score = 0
                if sma_5 > sma_10 > sma_20 > sma_30:
                    ma_score = ma_weight
                    bullish_signals += 1
                    signals['trend'] = 'bullish'
                elif sma_5 < sma_10 < sma_20 < sma_30:
                    ma_score = ma_weight
                    bearish_signals += 1
                    signals['trend'] = 'bearish'
                elif sma_5 > sma_10 > sma_20:  # 部分多头排列
                    ma_score = ma_weight * 0.6
                    bullish_signals += 0.6
                elif sma_5 < sma_10 < sma_20:  # 部分空头排列
                    ma_score = ma_weight * 0.6
                    bearish_signals += 0.6
                
                # EMA交叉确认
                if ema_12 > ema_26:
                    ma_score += ma_weight * 0.2
                    bullish_signals += 0.3
                elif ema_12 < ema_26:
                    ma_score += ma_weight * 0.2
                    bearish_signals += 0.3
                
                trend_score += ma_score
                
                # 2. RSI超买超卖分析 (动态权重)
                rsi_weight = weights.get('rsi', 20)
                rsi_score = 0
                if rsi_14 > config.rsi_overbought:  # 超买
                    rsi_score = rsi_weight * 0.75
                    bearish_signals += 0.8
                    signals['technical_indicators']['rsi_signal'] = 'overbought'
                elif rsi_14 < config.rsi_oversold:  # 超卖
                    rsi_score = rsi_weight * 0.75
                    bullish_signals += 0.8
                    signals['technical_indicators']['rsi_signal'] = 'oversold'
                elif 40 < rsi_14 < 60:  # 中性区域
                    rsi_score = rsi_weight * 0.25
                    signals['technical_indicators']['rsi_signal'] = 'neutral'
                elif rsi_14 > 50:  # 偏强
                    rsi_score = rsi_weight * 0.4
                    bullish_signals += 0.4
                    signals['technical_indicators']['rsi_signal'] = 'bullish'
                else:  # 偏弱
                    rsi_score = rsi_weight * 0.4
                    bearish_signals += 0.4
                    signals['technical_indicators']['rsi_signal'] = 'bearish'
                
                trend_score += rsi_score
                
                # 3. MACD趋势分析 (动态权重)
                macd_weight = weights.get('macd', 20)
                macd_score = 0
                if macd_line > macd_signal and macd_histogram > 0:  # 金叉且柱状图为正
                    macd_score = macd_weight
                    bullish_signals += 1
                    signals['technical_indicators']['macd_signal'] = 'golden_cross'
                elif macd_line < macd_signal and macd_histogram < 0:  # 死叉且柱状图为负
                    macd_score = macd_weight
                    bearish_signals += 1
                    signals['technical_indicators']['macd_signal'] = 'death_cross'
                elif macd_line > 0 and macd_signal > 0:  # 零轴上方
                    macd_score = macd_weight * 0.5
                    bullish_signals += 0.5
                    signals['technical_indicators']['macd_signal'] = 'above_zero'
                elif macd_line < 0 and macd_signal < 0:  # 零轴下方
                    macd_score = macd_weight * 0.5
                    bearish_signals += 0.5
                    signals['technical_indicators']['macd_signal'] = 'below_zero'
                
                trend_score += macd_score
                
                # 4. 布林带位置分析 (动态权重)
                bb_weight = weights.get('bollinger_bands', 15)
                bb_score = 0
                bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
                
                if bb_position > 0.8:  # 接近上轨
                    bb_score = bb_weight * 0.67
                    bearish_signals += 0.6
                    signals['technical_indicators']['bb_signal'] = 'near_upper'
                elif bb_position < 0.2:  # 接近下轨
                    bb_score = bb_weight * 0.67
                    bullish_signals += 0.6
                    signals['technical_indicators']['bb_signal'] = 'near_lower'
                elif current_price > bb_upper:  # 突破上轨
                    bb_score = bb_weight
                    bullish_signals += 0.8
                    signals['technical_indicators']['bb_signal'] = 'breakout_upper'
                elif current_price < bb_lower:  # 跌破下轨
                    bb_score = bb_weight
                    bearish_signals += 0.8
                    signals['technical_indicators']['bb_signal'] = 'breakdown_lower'
                
                trend_score += bb_score
                
                # 5. KDJ随机指标 (动态权重)
                kdj_weight = weights.get('kdj', 10)
                kdj_score = 0
                if k_value > config.kdj_overbought and d_value > config.kdj_overbought:  # 超买
                    kdj_score = kdj_weight * 0.8
                    bearish_signals += 0.5
                    signals['technical_indicators']['kdj_signal'] = 'overbought'
                elif k_value < config.kdj_oversold and d_value < config.kdj_oversold:  # 超卖
                    kdj_score = kdj_weight * 0.8
                    bullish_signals += 0.5
                    signals['technical_indicators']['kdj_signal'] = 'oversold'
                elif k_value > d_value and j_value > k_value:  # 金叉
                    kdj_score = kdj_weight
                    bullish_signals += 0.6
                    signals['technical_indicators']['kdj_signal'] = 'golden_cross'
                elif k_value < d_value and j_value < k_value:  # 死叉
                    kdj_score = kdj_weight
                    bearish_signals += 0.6
                    signals['technical_indicators']['kdj_signal'] = 'death_cross'
                
                trend_score += kdj_score
                
                # 6. 威廉指标确认 (动态权重)
                wr_weight = weights.get('williams_r', 5)
                wr_score = 0
                if williams_r > config.williams_overbought:  # 超买
                    wr_score = wr_weight * 0.6
                    bearish_signals += 0.3
                elif williams_r < config.williams_oversold:  # 超卖
                    wr_score = wr_weight * 0.6
                    bullish_signals += 0.3
                elif williams_r > -50:  # 偏强
                    wr_score = wr_weight * 0.4
                    bullish_signals += 0.2
                else:  # 偏弱
                    wr_score = wr_weight * 0.4
                    bearish_signals += 0.2
                
                trend_score += wr_score
                
                # 7. 价格突破分析 (动态权重)
                breakout_weight = weights.get('breakout', 5)
                recent_high = max(highs[-5:])
                recent_low = min(lows[-5:])
                
                if current_price > recent_high * 1.005:  # 突破近期高点
                    trend_score += breakout_weight
                    bullish_signals += 0.5
                    signals['technical_indicators']['breakout'] = 'upward'
                elif current_price < recent_low * 0.995:  # 跌破近期低点
                    trend_score += breakout_weight
                    bearish_signals += 0.5
                    signals['technical_indicators']['breakout'] = 'downward'
                
                # ========== 综合趋势判断 ==========
                signal_ratio = bullish_signals / (bullish_signals + bearish_signals) if (bullish_signals + bearish_signals) > 0 else 0.5
                
                if signal_ratio > 0.65:
                    signals['trend'] = 'bullish'
                elif signal_ratio < 0.35:
                    signals['trend'] = 'bearish'
                else:
                    signals['trend'] = 'neutral'
                
                # 计算最终置信度
                base_confidence = min(95.0, 50.0 + trend_score)
                
                # 信号一致性加成
                consistency_bonus = 0
                if bullish_signals > bearish_signals * 2:  # 多头信号占绝对优势
                    consistency_bonus = 15
                elif bearish_signals > bullish_signals * 2:  # 空头信号占绝对优势
                    consistency_bonus = 15
                elif abs(bullish_signals - bearish_signals) < 0.5:  # 信号分歧较大
                    consistency_bonus = -10
                
                signals['confidence'] = min(95.0, base_confidence + consistency_bonus)
                signals['technical_indicators']['bullish_signals'] = bullish_signals
                signals['technical_indicators']['bearish_signals'] = bearish_signals
                signals['technical_indicators']['signal_ratio'] = signal_ratio
                
                # 波动性分析
                price_changes = [abs(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                avg_volatility = sum(price_changes) / len(price_changes)
                
                if avg_volatility > 0.04:
                    signals['volatility'] = 'high'
                elif avg_volatility < 0.015:
                    signals['volatility'] = 'low'
                
                # 成交量分析增强
                if len(volumes) > 5:
                    avg_volume = sum(volumes[:-5]) / len(volumes[:-5])
                    recent_volume = sum(volumes[-3:]) / 3
                    
                    volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1
                    
                    if volume_ratio > 1.5:  # 成交量放大
                        signals['volume_anomaly'] = True
                        signals['confidence'] = min(95.0, signals['confidence'] + 10)
                        
                        # 量价配合
                        if signals['trend'] == 'bullish' and recent_change > 0:
                            signals['confidence'] = min(95.0, signals['confidence'] + 10)
                        elif signals['trend'] == 'bearish' and recent_change < 0:
                            signals['confidence'] = min(95.0, signals['confidence'] + 10)
            
            # 资金费率分析
            if funding_rate:
                rate = funding_rate.get('funding_rate', 0)
                if rate > 0.01:  # 高正费率，多头过热
                    signals['funding_rate_signal'] = 'bearish'
                    signals['confidence'] = min(80.0, signals['confidence'] + 10)
                elif rate < -0.005:  # 负费率，空头过热
                    signals['funding_rate_signal'] = 'bullish'
                    signals['confidence'] = min(80.0, signals['confidence'] + 10)
            
            logger.debug(f"获取{symbol}市场信号成功: 趋势={signals['trend']}, 置信度={signals['confidence']:.1f}%")
            
        except Exception as e:
            logger.warning(f"获取{symbol}市场信号失败: {e}")
        
        return signals
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """计算指数移动平均线 (EMA)"""
        if len(prices) < period:
            return sum(prices) / len(prices)
        
        multiplier = 2 / (period + 1)
        ema = prices[0]
        
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """计算相对强弱指数 (RSI)"""
        if len(prices) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50.0
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_macd(self, prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
        """计算MACD指标"""
        if len(prices) < slow:
            return 0.0, 0.0, 0.0
        
        ema_fast = self._calculate_ema(prices, fast)
        ema_slow = self._calculate_ema(prices, slow)
        
        macd_line = ema_fast - ema_slow
        
        # 简化的信号线计算
        macd_values = []
        for i in range(slow, len(prices)):
            ema_f = self._calculate_ema(prices[:i+1], fast)
            ema_s = self._calculate_ema(prices[:i+1], slow)
            macd_values.append(ema_f - ema_s)
        
        if len(macd_values) >= signal:
            macd_signal = self._calculate_ema(macd_values, signal)
        else:
            macd_signal = macd_line
        
        macd_histogram = macd_line - macd_signal
        
        return macd_line, macd_signal, macd_histogram
    
    def _calculate_bollinger_bands(self, prices: List[float], period: int = 20, std_dev: float = 2) -> Tuple[float, float, float]:
        """计算布林带"""
        if len(prices) < period:
            avg = sum(prices) / len(prices)
            return avg, avg, avg
        
        recent_prices = prices[-period:]
        middle = sum(recent_prices) / period
        
        variance = sum((p - middle) ** 2 for p in recent_prices) / period
        std = variance ** 0.5
        
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        
        return upper, middle, lower
    
    def _calculate_kdj(self, highs: List[float], lows: List[float], closes: List[float], 
                      k_period: int = 9, k_smooth: int = 3, d_smooth: int = 3) -> Tuple[float, float, float]:
        """计算KDJ随机指标"""
        if len(closes) < k_period:
            return 50.0, 50.0, 50.0
        
        # 计算RSV (Raw Stochastic Value)
        recent_high = max(highs[-k_period:])
        recent_low = min(lows[-k_period:])
        current_close = closes[-1]
        
        if recent_high == recent_low:
            rsv = 50.0
        else:
            rsv = (current_close - recent_low) / (recent_high - recent_low) * 100
        
        # 简化的K、D、J计算
        # 在实际应用中，这里应该使用移动平均
        k_value = rsv  # 简化处理
        d_value = k_value  # 简化处理
        j_value = 3 * k_value - 2 * d_value
        
        return k_value, d_value, j_value
    
    def _calculate_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """计算平均真实波幅 (ATR)"""
        if len(closes) < 2:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            
            true_range = max(high_low, high_close, low_close)
            true_ranges.append(true_range)
        
        if len(true_ranges) < period:
            return sum(true_ranges) / len(true_ranges)
        
        return sum(true_ranges[-period:]) / period
    
    def _calculate_williams_r(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """计算威廉指标 (%R)"""
        if len(closes) < period:
            return -50.0
        
        recent_high = max(highs[-period:])
        recent_low = min(lows[-period:])
        current_close = closes[-1]
        
        if recent_high == recent_low:
            return -50.0
        
        williams_r = ((recent_high - current_close) / (recent_high - recent_low)) * -100
        
        return williams_r
    
    def _find_current_position(self, symbol: str, positions: List[Dict]) -> Optional[Dict]:
        """查找当前持仓"""
        for pos in positions:
            if pos.get('symbol') == symbol and pos.get('size', 0) != 0:
                return pos
        return None
    
    def _determine_action_from_signals(self, signals: Dict[str, Any]) -> TradingAction:
        """根据信号确定交易动作"""
        confidence = signals.get('confidence', 50.0)
        trend = signals.get('trend', 'neutral')
        volatility = signals.get('volatility', 'medium')
        volume_anomaly = signals.get('volume_anomaly', False)
        funding_signal = signals.get('funding_rate_signal', 'neutral')
        
        # 更积极的交易决策逻辑
        
        # 明确趋势时的决策
        if trend == 'bullish':
            if confidence > 75 or (confidence > 65 and volume_anomaly):
                return TradingAction.STRONG_BUY
            elif confidence > 55 or (confidence > 45 and funding_signal == 'bullish'):
                return TradingAction.BUY
            elif confidence > 40:
                return TradingAction.HOLD
            else:
                return TradingAction.WAIT
                
        elif trend == 'bearish':
            if confidence > 75 or (confidence > 65 and volume_anomaly):
                return TradingAction.STRONG_SELL
            elif confidence > 55 or (confidence > 45 and funding_signal == 'bearish'):
                return TradingAction.SELL
            elif confidence > 40:
                return TradingAction.HOLD
            else:
                return TradingAction.WAIT
        
        # 中性趋势时，更积极地寻找交易机会
        else:
            # 高置信度时，即使趋势中性也给出交易建议
            if confidence > 80:
                # 根据其他信号判断方向
                if funding_signal == 'bullish' or volume_anomaly:
                    return TradingAction.BUY
                elif funding_signal == 'bearish':
                    return TradingAction.SELL
                else:
                    # 高置信度但无明确方向，建议买入（偏向乐观）
                    return TradingAction.BUY
            
            # 资金费率信号
            elif funding_signal == 'bullish' and confidence > 50:
                return TradingAction.BUY
            elif funding_signal == 'bearish' and confidence > 50:
                return TradingAction.SELL
            
            # 成交量异常 + 一定置信度
            elif volume_anomaly and confidence > 60:
                return TradingAction.BUY  # 成交量放大通常是好信号
            
            # 中等置信度时给出持有建议
            elif confidence > 60:
                return TradingAction.HOLD
            
            # 高波动时等待
            elif volatility == 'high' and confidence < 70:
                return TradingAction.WAIT
            
            # 低置信度时等待
            else:
                return TradingAction.WAIT
    
    def _calculate_position_parameters(self, action: TradingAction, current_price: float,
                                     account_info: Dict, current_position: Optional[Dict],
                                     signals: Dict) -> Dict[str, Any]:
        """计算仓位参数"""
        total_equity = account_info.get('total_equity', 0)
        
        # 基础仓位百分比
        base_percent = 10.0  # 基础10%
        
        # 根据信号强度调整
        confidence = signals.get('confidence', 50.0)
        confidence_multiplier = confidence / 100.0
        
        # 根据交易动作调整
        if action in [TradingAction.STRONG_BUY, TradingAction.STRONG_SELL]:
            action_multiplier = 1.5
        elif action in [TradingAction.BUY, TradingAction.SELL]:
            action_multiplier = 1.0
        else:
            action_multiplier = 0.0
        
        # 根据波动性调整
        volatility = signals.get('volatility', 'medium')
        if volatility == 'high':
            volatility_multiplier = 0.6
        elif volatility == 'low':
            volatility_multiplier = 1.2
        else:
            volatility_multiplier = 1.0
        
        # 计算最终仓位
        position_percent = min(
            base_percent * confidence_multiplier * action_multiplier * volatility_multiplier,
            self.max_position_percent
        )
        
        position_usdt = total_equity * (position_percent / 100.0)
        
        # 计算杠杆
        leverage = self._calculate_optimal_leverage(signals, action)
        
        # 风险管理
        stop_loss_percent = self._calculate_stop_loss_percent(signals, volatility)
        max_loss = position_usdt * leverage * (stop_loss_percent / 100.0)
        
        take_profit_percent = stop_loss_percent * 3  # 1:3风险收益比
        expected_profit = position_usdt * leverage * (take_profit_percent / 100.0)
        
        risk_reward_ratio = expected_profit / max_loss if max_loss > 0 else 0
        
        # 评估风险等级
        risk_level = self._assess_position_risk(leverage, position_percent, volatility, confidence)
        
        return {
            'size_usdt': position_usdt,
            'size_percent': position_percent,
            'leverage': leverage,
            'max_loss': max_loss,
            'expected_profit': expected_profit,
            'risk_reward_ratio': risk_reward_ratio,
            'risk_level': risk_level
        }
    
    def _calculate_optimal_leverage(self, signals: Dict, action: TradingAction) -> float:
        """计算最优杠杆"""
        base_leverage = 2.0
        
        confidence = signals.get('confidence', 50.0)
        volatility = signals.get('volatility', 'medium')
        
        # 根据置信度调整
        if confidence > 85:
            leverage_multiplier = 1.2
        elif confidence > 70:
            leverage_multiplier = 1.0
        else:
            leverage_multiplier = 0.8
        
        # 根据波动性调整
        if volatility == 'high':
            leverage_multiplier *= 0.6
        elif volatility == 'low':
            leverage_multiplier *= 1.1
        
        # 根据动作调整
        if action in [TradingAction.WAIT, TradingAction.HOLD]:
            leverage_multiplier = 0.5
        
        leverage = base_leverage * leverage_multiplier
        return min(leverage, self.max_leverage)
    
    def _calculate_price_levels(self, action: TradingAction, current_price: float,
                              signals: Dict) -> Dict[str, Any]:
        """计算价格点位"""
        volatility = signals.get('volatility', 'medium')
        
        # 根据波动性调整止损止盈幅度
        if volatility == 'high':
            stop_loss_pct = 0.04  # 4%
        elif volatility == 'low':
            stop_loss_pct = 0.02  # 2%
        else:
            stop_loss_pct = 0.03  # 3%
        
        take_profit_pct = stop_loss_pct * 3  # 1:3风险收益比
        
        if action in [TradingAction.BUY, TradingAction.STRONG_BUY]:
            entry_price = current_price
            stop_loss_price = current_price * (1 - stop_loss_pct)
            take_profit_price = current_price * (1 + take_profit_pct)
        elif action in [TradingAction.SELL, TradingAction.STRONG_SELL]:
            entry_price = current_price
            stop_loss_price = current_price * (1 + stop_loss_pct)
            take_profit_price = current_price * (1 - take_profit_pct)
        else:
            entry_price = current_price
            stop_loss_price = current_price
            take_profit_price = current_price
        
        # 计算关键支撑阻力位
        key_levels = self._calculate_key_levels(current_price)
        
        return {
            'entry': entry_price,
            'stop_loss': stop_loss_price,
            'take_profit': take_profit_price,
            'key_levels': key_levels
        }
    
    def _calculate_key_levels(self, current_price: float) -> Dict[str, List[float]]:
        """计算关键价位"""
        # 简单的百分比支撑阻力位
        support_levels = [
            current_price * 0.98,  # 2%
            current_price * 0.95,  # 5%
            current_price * 0.90   # 10%
        ]
        
        resistance_levels = [
            current_price * 1.02,  # 2%
            current_price * 1.05,  # 5%
            current_price * 1.10   # 10%
        ]
        
        return {
            'support': support_levels,
            'resistance': resistance_levels
        }
    
    def _calculate_stop_loss_percent(self, signals: Dict, volatility: str) -> float:
        """计算止损百分比"""
        base_stop_loss = 3.0  # 基础3%
        
        if volatility == 'high':
            return base_stop_loss * 1.5
        elif volatility == 'low':
            return base_stop_loss * 0.7
        else:
            return base_stop_loss
    
    def _assess_position_risk(self, leverage: float, position_percent: float,
                            volatility: str, confidence: float) -> RiskLevel:
        """评估仓位风险"""
        risk_score = 0
        
        # 杠杆风险
        if leverage > 2.5:
            risk_score += 2
        elif leverage > 1.5:
            risk_score += 1
        
        # 仓位风险
        if position_percent > 20:
            risk_score += 2
        elif position_percent > 10:
            risk_score += 1
        
        # 波动性风险
        if volatility == 'high':
            risk_score += 2
        elif volatility == 'medium':
            risk_score += 1
        
        # 置信度风险
        if confidence < 60:
            risk_score += 2
        elif confidence < 75:
            risk_score += 1
        
        # 风险等级映射
        if risk_score >= 6:
            return RiskLevel.VERY_HIGH
        elif risk_score >= 4:
            return RiskLevel.HIGH
        elif risk_score >= 2:
            return RiskLevel.MEDIUM
        elif risk_score >= 1:
            return RiskLevel.LOW
        else:
            return RiskLevel.VERY_LOW
    
    def _generate_trading_reasoning(self, signals: Dict, action: TradingAction,
                                  position_params: Dict) -> str:
        """生成交易决策理由"""
        reasons = []
        
        # 趋势分析
        trend = signals.get('trend', 'neutral')
        confidence = signals.get('confidence', 50.0)
        reasons.append(f"趋势: {trend} (置信度: {confidence:.1f}%)")
        
        # 波动性
        volatility = signals.get('volatility', 'medium')
        reasons.append(f"波动性: {volatility}")
        
        # 成交量
        if signals.get('volume_anomaly'):
            reasons.append("检测到成交量异常放大")
        
        # 资金费率
        funding_signal = signals.get('funding_rate_signal', 'neutral')
        if funding_signal != 'neutral':
            reasons.append(f"资金费率信号: {funding_signal}")
        
        # ML信号
        if signals.get('ml_signal'):
            reasons.append(f"ML预测: {signals['ml_signal']}")
        
        # 风险评估
        risk_level = position_params.get('risk_level', RiskLevel.MEDIUM)
        reasons.append(f"风险等级: {risk_level.value}")
        
        # 风险收益比
        risk_reward = position_params.get('risk_reward_ratio', 0)
        reasons.append(f"风险收益比: 1:{risk_reward:.1f}")
        
        return " | ".join(reasons)
    
    def _calculate_scores(self, traditional: Dict, ml_prediction, ml_anomalies: List) -> Tuple[float, float, float]:
        """计算综合评分"""
        bullish_score = 0.0
        bearish_score = 0.0
        volatility_score = 50.0
        
        # 传统技术分析评分 (权重40%)
        if traditional:
            traditional_signal = traditional.get('overall_signal', 'hold')
            signal_strength = traditional.get('signal_strength', 0.5)
            
            if traditional_signal in ['strong_buy', 'buy']:
                bullish_score += 40 * signal_strength
            elif traditional_signal in ['strong_sell', 'sell']:
                bearish_score += 40 * signal_strength
            
            # 波动性评分
            volatility_score = traditional.get('volatility_score', 50.0)
        
        # ML预测评分 (权重50%)
        if ml_prediction:
            ml_signal = ml_prediction.signal.value
            ml_confidence = ml_prediction.confidence
            
            if ml_signal in ['strong_buy', 'buy']:
                bullish_score += 50 * ml_confidence
            elif ml_signal in ['strong_sell', 'sell']:
                bearish_score += 50 * ml_confidence
        
        # 异常检测调整 (权重10%)
        if ml_anomalies:
            high_severity_count = sum(1 for a in ml_anomalies if a.severity > 0.7)
            if high_severity_count > 0:
                # 异常增加不确定性，降低信号强度
                adjustment = min(10, high_severity_count * 3)
                bullish_score = max(0, bullish_score - adjustment)
                bearish_score = max(0, bearish_score - adjustment)
                volatility_score = min(100, volatility_score + adjustment)
        
        return bullish_score, bearish_score, volatility_score
    
    def _analyze_market_regime(self, traditional: Dict, volatility_score: float) -> Tuple[str, float]:
        """分析市场状态"""
        trend_strength = traditional.get('trend_strength', 0.5) if traditional else 0.5
        
        if volatility_score > 80:
            regime = "volatile"
        elif volatility_score < 30:
            regime = "calm"
        elif trend_strength > 0.7:
            regime = "trending"
        else:
            regime = "ranging"
        
        return regime, trend_strength
    
    def _determine_trading_action(self, analysis: MarketAnalysis) -> TradingAction:
        """确定交易动作"""
        bullish = analysis.bullish_score
        bearish = analysis.bearish_score
        
        # 强信号阈值
        if bullish > 80 and bullish > bearish * 1.5:
            return TradingAction.STRONG_BUY
        elif bearish > 80 and bearish > bullish * 1.5:
            return TradingAction.STRONG_SELL
        elif bullish > 60 and bullish > bearish * 1.2:
            return TradingAction.BUY
        elif bearish > 60 and bearish > bullish * 1.2:
            return TradingAction.SELL
        elif analysis.volatility_score > 70:
            return TradingAction.WAIT  # 高波动时等待
        else:
            return TradingAction.HOLD
    
    def _calculate_position_size(self, analysis: MarketAnalysis, 
                               balance: float, positions: Dict[str, float]) -> float:
        """计算建议仓位大小"""
        base_size = 10.0  # 基础仓位10%
        
        # 根据信号强度调整
        confidence = max(analysis.bullish_score, analysis.bearish_score)
        size_multiplier = confidence / 100.0
        
        # 根据市场状态调整
        if analysis.market_regime == "volatile":
            size_multiplier *= 0.5  # 高波动减半仓位
        elif analysis.market_regime == "trending":
            size_multiplier *= 1.2  # 趋势市场增加仓位
        
        # 根据风险调整
        if analysis.volatility_score > 80:
            size_multiplier *= 0.3
        elif analysis.volatility_score < 30:
            size_multiplier *= 1.5
        
        position_size = base_size * size_multiplier
        
        # 限制最大仓位
        return min(position_size, self.max_position_size * 100)
    
    def _calculate_leverage(self, analysis: MarketAnalysis, action: TradingAction) -> float:
        """计算建议杠杆"""
        base_leverage = 2.0
        
        # 根据信号强度调整
        if action in [TradingAction.STRONG_BUY, TradingAction.STRONG_SELL]:
            leverage = base_leverage * 1.5
        elif action in [TradingAction.BUY, TradingAction.SELL]:
            leverage = base_leverage
        else:
            leverage = 1.0
        
        # 根据波动性调整
        if analysis.volatility_score > 70:
            leverage *= 0.5  # 高波动降低杠杆
        elif analysis.volatility_score < 30:
            leverage *= 1.2  # 低波动可适当增加杠杆
        
        return min(leverage, self.max_leverage)
    
    def _calculate_stop_loss_take_profit(self, analysis: MarketAnalysis, 
                                       action: TradingAction, price: float) -> Tuple[float, float]:
        """计算止损止盈"""
        # 基础止损止盈
        stop_loss = self.base_stop_loss
        take_profit = self.base_take_profit
        
        # 根据波动性调整
        volatility_multiplier = analysis.volatility_score / 50.0
        stop_loss *= volatility_multiplier
        take_profit *= volatility_multiplier
        
        # 根据趋势强度调整
        if analysis.trend_strength > 0.8:
            take_profit *= 1.5  # 强趋势扩大止盈
        
        return stop_loss * 100, take_profit * 100  # 转换为百分比
    
    def _assess_risk_level(self, analysis: MarketAnalysis, 
                          leverage: float, position_size: float) -> RiskLevel:
        """评估风险等级"""
        risk_score = 0
        
        # 波动性风险
        if analysis.volatility_score > 80:
            risk_score += 3
        elif analysis.volatility_score > 60:
            risk_score += 2
        elif analysis.volatility_score > 40:
            risk_score += 1
        
        # 杠杆风险
        if leverage > 4:
            risk_score += 3
        elif leverage > 2:
            risk_score += 2
        elif leverage > 1:
            risk_score += 1
        
        # 仓位风险
        if position_size > 25:
            risk_score += 2
        elif position_size > 15:
            risk_score += 1
        
        # 异常风险
        high_anomalies = sum(1 for a in analysis.ml_anomalies if a.get('severity', 0) > 0.7)
        if high_anomalies > 3:
            risk_score += 2
        elif high_anomalies > 1:
            risk_score += 1
        
        # 风险等级映射
        if risk_score >= 8:
            return RiskLevel.VERY_HIGH
        elif risk_score >= 6:
            return RiskLevel.HIGH
        elif risk_score >= 4:
            return RiskLevel.MEDIUM
        elif risk_score >= 2:
            return RiskLevel.LOW
        else:
            return RiskLevel.VERY_LOW
    
    def _generate_reasoning(self, analysis: MarketAnalysis, action: TradingAction) -> str:
        """生成决策理由"""
        reasons = []
        
        # 传统技术分析
        if analysis.traditional_signals:
            signal = analysis.traditional_signals.get('overall_signal', 'hold')
            strength = analysis.traditional_signals.get('signal_strength', 0.5)
            reasons.append(f"技术指标: {signal} (强度: {strength:.1%})")
        
        # ML预测
        if analysis.ml_prediction:
            ml_signal = analysis.ml_prediction.get('signal', 'hold')
            ml_confidence = analysis.ml_prediction.get('confidence', 0.5)
            reasons.append(f"ML预测: {ml_signal} (置信度: {ml_confidence:.1%})")
        
        # 市场状态
        reasons.append(f"市场状态: {analysis.market_regime}")
        reasons.append(f"趋势强度: {analysis.trend_strength:.1%}")
        
        # 异常情况
        if analysis.ml_anomalies:
            high_anomalies = sum(1 for a in analysis.ml_anomalies if a.get('severity', 0) > 0.7)
            if high_anomalies > 0:
                reasons.append(f"检测到{high_anomalies}个高风险异常")
        
        # 综合评分
        reasons.append(f"看涨评分: {analysis.bullish_score:.1f}")
        reasons.append(f"看跌评分: {analysis.bearish_score:.1f}")
        
        return " | ".join(reasons)
    
    def _calculate_support_resistance(self, analysis: MarketAnalysis, 
                                    current_price: float) -> Tuple[List[float], List[float]]:
        """计算支撑阻力位"""
        # 简化实现，实际可以基于更复杂的算法
        support_levels = []
        resistance_levels = []
        
        # 基于当前价格的百分比计算
        for pct in [0.02, 0.05, 0.10]:
            support_levels.append(current_price * (1 - pct))
            resistance_levels.append(current_price * (1 + pct))
        
        return support_levels, resistance_levels
    
    def _determine_entry_timing(self, analysis: MarketAnalysis, action: TradingAction) -> str:
        """确定入场时机"""
        if action in [TradingAction.WAIT, TradingAction.HOLD]:
            return "wait_for_signal"
        elif analysis.volatility_score > 80:
            return "wait_for_calm"
        elif analysis.trend_strength > 0.8:
            return "immediate"
        else:
            return "wait_for_confirmation"
    
    def _estimate_hold_duration(self, analysis: MarketAnalysis, action: TradingAction) -> Optional[int]:
        """估计持仓时间"""
        if action in [TradingAction.WAIT, TradingAction.HOLD]:
            return None
        
        base_hours = 24  # 基础24小时
        
        if analysis.market_regime == "trending":
            return base_hours * 3  # 趋势市场持有更久
        elif analysis.market_regime == "volatile":
            return base_hours // 2  # 波动市场快进快出
        else:
            return base_hours
    
    def _format_ml_prediction(self, prediction) -> Dict[str, Any]:
        """格式化ML预测结果"""
        if not prediction:
            return {}
        
        return {
            'signal': prediction.signal.value,
            'confidence': prediction.confidence,
            'model_accuracy': prediction.model_accuracy,
            'probability_distribution': prediction.probability_distribution
        }
    
    def _format_ml_anomalies(self, anomalies: List) -> List[Dict[str, Any]]:
        """格式化ML异常结果"""
        if not anomalies:
            return []
        
        return [
            {
                'type': anomaly.anomaly_type.value,
                'severity': anomaly.severity,
                'description': anomaly.description,
                'recommendation': anomaly.recommendation
            }
            for anomaly in anomalies
        ]
    
    def _determine_entry_timing(self, signals: Dict[str, Any], action: TradingAction) -> str:
        """确定入场时机"""
        confidence = signals.get('confidence', 50.0)
        volatility = signals.get('volatility', 'medium')
        volume_anomaly = signals.get('volume_anomaly', False)
        
        if action in [TradingAction.STRONG_BUY, TradingAction.STRONG_SELL]:
            return "立即执行"
        elif action in [TradingAction.BUY, TradingAction.SELL]:
            if confidence > 75:
                return "立即执行"
            elif volatility == 'high':
                return "等待波动减缓"
            elif volume_anomaly:
                return "趁成交量放大时执行"
            else:
                return "择机执行"
        elif action == TradingAction.WAIT:
            return "等待更好时机"
        else:
            return "观望"
    
    def _estimate_hold_duration(self, signals: Dict[str, Any], action: TradingAction) -> Optional[int]:
        """估算持仓时间"""
        if action in [TradingAction.WAIT, TradingAction.HOLD]:
            return None
        
        confidence = signals.get('confidence', 50.0)
        volatility = signals.get('volatility', 'medium')
        
        # 基础持仓时间
        if action in [TradingAction.STRONG_BUY, TradingAction.STRONG_SELL]:
            base_hours = 24  # 1天
        else:
            base_hours = 12  # 半天
        
        # 根据置信度调整
        if confidence > 80:
            base_hours *= 1.5
        elif confidence < 60:
            base_hours *= 0.7
        
        # 根据波动性调整
        if volatility == 'high':
            base_hours *= 0.5  # 高波动时缩短持仓
        elif volatility == 'low':
            base_hours *= 1.3  # 低波动时延长持仓
        
        return int(base_hours)
    
    def _format_ml_prediction(self, ml_prediction) -> Dict[str, Any]:
        """格式化ML预测结果"""
        if ml_prediction is None:
            return {}
        
        try:
            return {
                'signal': ml_prediction.signal.value,
                'confidence': ml_prediction.confidence,
                'probability_distribution': ml_prediction.probability_distribution,
                'features_importance': ml_prediction.features_importance,
                'model_accuracy': ml_prediction.model_accuracy
            }
        except Exception:
            return {}
    
    def _format_ml_anomalies(self, ml_anomalies: List) -> List[Dict[str, Any]]:
        """格式化ML异常检测结果"""
        if not ml_anomalies:
            return []
        
        formatted_anomalies = []
        for anomaly in ml_anomalies:
            try:
                formatted_anomalies.append({
                    'type': anomaly.anomaly_type.value,
                    'severity': anomaly.severity,
                    'description': anomaly.description,
                    'affected_features': anomaly.affected_features,
                    'recommendation': anomaly.recommendation,
                    'timestamp': anomaly.timestamp
                })
            except Exception:
                continue
        
        return formatted_anomalies