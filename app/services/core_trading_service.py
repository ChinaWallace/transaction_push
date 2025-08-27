# -*- coding: utf-8 -*-
"""
核心交易服务
Core Trading Service - 统一管理所有交易决策功能
整合Kronos预测、技术分析、ML预测、持仓分析等所有交易相关功能
"""

import asyncio
from typing import Dict, Any, List, Optional, Tuple, Union
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger, trading_logger
from app.services.kronos_integrated_decision_service import (
    get_kronos_integrated_service, 
    KronosEnhancedDecision,
    KronosSignalStrength
)
from app.services.position_analysis_service import PositionAnalysisService, PositionRisk
from app.services.okx_service import OKXService
from app.services.trading_decision_service import TradingAction, RiskLevel, TradingDecisionService
from app.services.ml_enhanced_service import MLEnhancedService, PredictionSignal
from app.services.trend_analysis_service import TrendAnalysisService
from app.services.core_notification_service import get_core_notification_service
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class AnalysisType(Enum):
    """分析类型"""
    KRONOS_ONLY = "kronos_only"
    TECHNICAL_ONLY = "technical_only" 
    ML_ONLY = "ml_only"
    INTEGRATED = "integrated"
    POSITION_FOCUSED = "position_focused"


class SignalStrength(Enum):
    """信号强度"""
    VERY_WEAK = "very_weak"
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


@dataclass
class TradingSignal:
    """统一交易信号"""
    symbol: str
    timestamp: datetime
    
    # 综合决策
    final_action: str
    final_confidence: float
    signal_strength: SignalStrength
    
    # 各模块分析结果
    kronos_result: Optional[KronosEnhancedDecision] = None
    technical_result: Optional[Dict[str, Any]] = None
    ml_result: Optional[Dict[str, Any]] = None
    position_result: Optional[Dict[str, Any]] = None
    
    # 交易参数
    entry_price: float = 0
    stop_loss_price: float = 0
    take_profit_price: float = 0
    position_size_usdt: float = 0
    leverage: float = 1
    risk_reward_ratio: float = 0
    
    # 决策依据
    reasoning: str = ""
    key_factors: List[str] = None
    confidence_breakdown: Dict[str, float] = None
    
    # 技术分析详情
    technical_indicators: Dict[str, Any] = None
    
    # 交易时间建议
    trading_timeframe: str = "日内"  # 超短线, 短线, 日内, 波段, 中长线
    holding_period: str = "2-6小时"  # 具体持有时间建议
    optimal_entry_time: str = "立即"  # 最佳入场时机
    
    # 时效性
    urgency: str = "normal"  # immediate, urgent, normal, low
    valid_until: datetime = None
    
    def __post_init__(self):
        if self.key_factors is None:
            self.key_factors = []
        if self.confidence_breakdown is None:
            self.confidence_breakdown = {}
        if self.technical_indicators is None:
            self.technical_indicators = {}
        if self.valid_until is None:
            self.valid_until = self.timestamp + timedelta(hours=4)


@dataclass
class PositionAnalysisResult:
    """持仓分析结果"""
    timestamp: datetime
    total_positions: int
    total_value_usdt: float
    total_pnl_usdt: float
    total_pnl_percent: float
    risk_level: str
    positions: List[Dict[str, Any]]
    recommendations: List[str]
    urgent_actions: List[str]


@dataclass
class MarketOpportunity:
    """市场机会"""
    symbol: str
    opportunity_type: str  # "strong_signal", "grid_trading", "arbitrage"
    score: float
    description: str
    parameters: Dict[str, Any]
    risk_level: str
    estimated_return: float
    recommended_position: float


class CoreTradingService:
    """核心交易服务类 - 统一交易决策中心"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # 初始化各个分析服务
        self.okx_service = OKXService()
        self.position_service = PositionAnalysisService()
        self.traditional_service = TradingDecisionService()
        
        # 可选服务（可能初始化失败）
        self.kronos_service = None
        self.ml_service = None
        self.trend_service = None
        self.notification_service = None
        
        # 初始化可选服务
        self._initialize_optional_services()
        
        # 分析权重配置 - 加重Kronos权重
        self.analysis_weights = {
            'kronos': 0.55,     # Kronos AI预测权重55% (提升)
            'technical': 0.25,  # 技术分析权重25%
            'ml': 0.15,         # ML预测权重15%
            'position': 0.05    # 持仓分析权重5%
        }
        
        # 信号强度阈值
        self.strength_thresholds = {
            SignalStrength.VERY_STRONG: 0.85,
            SignalStrength.STRONG: 0.75,
            SignalStrength.MODERATE: 0.65,
            SignalStrength.WEAK: 0.55,
            SignalStrength.VERY_WEAK: 0.0
        }
    
    def _initialize_optional_services(self):
        """初始化可选服务"""
        try:
            self.ml_service = MLEnhancedService()
            self.logger.info("✅ ML服务初始化成功")
        except Exception as e:
            self.logger.warning(f"⚠️ ML服务初始化失败: {e}")
        
        try:
            self.trend_service = TrendAnalysisService()
            self.logger.info("✅ 趋势分析服务初始化成功")
        except Exception as e:
            self.logger.warning(f"⚠️ 趋势分析服务初始化失败: {e}")
    
    async def analyze_trading_signal(
        self,
        symbol: str,
        analysis_type: AnalysisType = AnalysisType.INTEGRATED,
        force_update: bool = False
    ) -> Optional[TradingSignal]:
        """
        分析交易信号 - 统一入口
        
        Args:
            symbol: 交易对
            analysis_type: 分析类型
            force_update: 是否强制更新
            
        Returns:
            统一交易信号
        """
        try:
            self.logger.info(f"🎯 开始分析 {symbol} 交易信号 (类型: {analysis_type.value})")
            
            # 并行执行各种分析
            analysis_tasks = []
            
            if analysis_type in [AnalysisType.KRONOS_ONLY, AnalysisType.INTEGRATED]:
                analysis_tasks.append(self._get_kronos_analysis(symbol, force_update))
            
            if analysis_type in [AnalysisType.TECHNICAL_ONLY, AnalysisType.INTEGRATED]:
                analysis_tasks.append(self._get_technical_analysis(symbol))
            
            if analysis_type in [AnalysisType.ML_ONLY, AnalysisType.INTEGRATED]:
                analysis_tasks.append(self._get_ml_analysis(symbol))
            
            if analysis_type in [AnalysisType.POSITION_FOCUSED, AnalysisType.INTEGRATED]:
                analysis_tasks.append(self._get_position_analysis(symbol))
            
            # 执行分析
            results = await asyncio.gather(*analysis_tasks, return_exceptions=True)
            
            # 解析结果
            kronos_result = None
            technical_result = None
            ml_result = None
            position_result = None
            
            result_index = 0
            
            if analysis_type in [AnalysisType.KRONOS_ONLY, AnalysisType.INTEGRATED]:
                kronos_result = results[result_index] if not isinstance(results[result_index], Exception) else None
                result_index += 1
            
            if analysis_type in [AnalysisType.TECHNICAL_ONLY, AnalysisType.INTEGRATED]:
                technical_result = results[result_index] if not isinstance(results[result_index], Exception) else None
                result_index += 1
            
            if analysis_type in [AnalysisType.ML_ONLY, AnalysisType.INTEGRATED]:
                ml_result = results[result_index] if not isinstance(results[result_index], Exception) else None
                result_index += 1
            
            if analysis_type in [AnalysisType.POSITION_FOCUSED, AnalysisType.INTEGRATED]:
                position_result = results[result_index] if not isinstance(results[result_index], Exception) else None
                result_index += 1
            
            # 生成综合信号
            signal = await self._generate_integrated_signal(
                symbol=symbol,
                kronos_result=kronos_result,
                technical_result=technical_result,
                ml_result=ml_result,
                position_result=position_result,
                analysis_type=analysis_type
            )
            
            # 记录交易日志
            if signal:
                trading_logger.info(
                    f"交易信号生成 - {symbol}: {signal.final_action} "
                    f"(置信度: {signal.final_confidence:.2f}, 强度: {signal.signal_strength.value})"
                )
            
            return signal
            
        except Exception as e:
            self.logger.error(f"分析交易信号失败 {symbol}: {e}")
            return None
    
    async def _get_kronos_analysis(self, symbol: str, force_update: bool = False) -> Optional[KronosEnhancedDecision]:
        """获取Kronos分析结果"""
        try:
            if not self.settings.kronos_config.get('enable_kronos_prediction', False):
                return None
            
            kronos_service = await get_kronos_integrated_service()
            return await kronos_service.get_kronos_enhanced_decision(symbol, force_update)
            
        except Exception as e:
            self.logger.warning(f"Kronos分析失败 {symbol}: {e}")
            return None
    
    async def _get_technical_analysis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取技术分析结果"""
        try:
            recommendation = await self.traditional_service.get_trading_recommendation(symbol)
            if recommendation:
                # 获取详细技术指标
                detailed_indicators = await self._get_detailed_technical_indicators(symbol)
                
                return {
                    'action': recommendation.action.value,
                    'confidence': recommendation.confidence,
                    'reasoning': recommendation.reasoning,
                    'entry_price': recommendation.entry_price,
                    'stop_loss': recommendation.stop_loss_price,
                    'take_profit': recommendation.take_profit_price,
                    'risk_level': recommendation.risk_level.value,
                    'detailed_indicators': detailed_indicators
                }
            return None
            
        except Exception as e:
            self.logger.warning(f"技术分析失败 {symbol}: {e}")
            return None
    
    async def _get_detailed_technical_indicators(self, symbol: str) -> Dict[str, Any]:
        """获取详细技术指标分析"""
        try:
            # 获取多周期K线数据
            async with self.okx_service as exchange:
                # 获取不同周期的数据
                kline_1h = await exchange.get_kline_data(symbol, '1H', 100)
                kline_4h = await exchange.get_kline_data(symbol, '4H', 50)
                kline_1d = await exchange.get_kline_data(symbol, '1D', 30)
                
                if not kline_1h:
                    return {}
                
                # 转换为DataFrame进行技术分析
                df_1h = pd.DataFrame(kline_1h)
                df_4h = pd.DataFrame(kline_4h) if kline_4h else pd.DataFrame()
                df_1d = pd.DataFrame(kline_1d) if kline_1d else pd.DataFrame()
                
                indicators = {}
                
                # 移动平均线分析
                if len(df_1h) >= 20:
                    df_1h['ma5'] = df_1h['close'].rolling(5).mean()
                    df_1h['ma10'] = df_1h['close'].rolling(10).mean()
                    df_1h['ma20'] = df_1h['close'].rolling(20).mean()
                    
                    current_price = df_1h['close'].iloc[-1]
                    ma5 = df_1h['ma5'].iloc[-1]
                    ma10 = df_1h['ma10'].iloc[-1]
                    ma20 = df_1h['ma20'].iloc[-1]
                    
                    # MA趋势判断
                    ma_trend = "多头排列" if ma5 > ma10 > ma20 else "空头排列" if ma5 < ma10 < ma20 else "震荡"
                    ma_signal = "看多" if current_price > ma20 else "看空"
                    
                    indicators['moving_averages'] = {
                        'ma5': ma5,
                        'ma10': ma10,
                        'ma20': ma20,
                        'trend': ma_trend,
                        'signal': ma_signal,
                        'price_vs_ma20': (current_price - ma20) / ma20 * 100
                    }
                
                # 布林带分析
                if len(df_1h) >= 20:
                    df_1h['bb_middle'] = df_1h['close'].rolling(20).mean()
                    df_1h['bb_std'] = df_1h['close'].rolling(20).std()
                    df_1h['bb_upper'] = df_1h['bb_middle'] + 2 * df_1h['bb_std']
                    df_1h['bb_lower'] = df_1h['bb_middle'] - 2 * df_1h['bb_std']
                    
                    bb_upper = df_1h['bb_upper'].iloc[-1]
                    bb_lower = df_1h['bb_lower'].iloc[-1]
                    bb_middle = df_1h['bb_middle'].iloc[-1]
                    
                    # 布林带位置判断
                    bb_position = "上轨附近" if current_price > bb_upper * 0.98 else \
                                 "下轨附近" if current_price < bb_lower * 1.02 else \
                                 "中轨附近"
                    
                    bb_width = (bb_upper - bb_lower) / bb_middle * 100
                    bb_signal = "超买" if current_price > bb_upper else \
                               "超卖" if current_price < bb_lower else "正常"
                    
                    indicators['bollinger_bands'] = {
                        'upper': bb_upper,
                        'middle': bb_middle,
                        'lower': bb_lower,
                        'position': bb_position,
                        'width': bb_width,
                        'signal': bb_signal
                    }
                
                # RSI分析
                if len(df_1h) >= 14:
                    delta = df_1h['close'].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                    rs = gain / loss
                    df_1h['rsi'] = 100 - (100 / (1 + rs))
                    
                    rsi = df_1h['rsi'].iloc[-1]
                    rsi_signal = "超买" if rsi > 70 else "超卖" if rsi < 30 else "正常"
                    
                    indicators['rsi'] = {
                        'value': rsi,
                        'signal': rsi_signal,
                        'level': "强" if rsi > 80 or rsi < 20 else "中" if rsi > 70 or rsi < 30 else "弱"
                    }
                
                # MACD分析
                if len(df_1h) >= 26:
                    exp1 = df_1h['close'].ewm(span=12).mean()
                    exp2 = df_1h['close'].ewm(span=26).mean()
                    df_1h['macd'] = exp1 - exp2
                    df_1h['macd_signal'] = df_1h['macd'].ewm(span=9).mean()
                    df_1h['macd_histogram'] = df_1h['macd'] - df_1h['macd_signal']
                    
                    macd = df_1h['macd'].iloc[-1]
                    macd_signal_line = df_1h['macd_signal'].iloc[-1]
                    macd_histogram = df_1h['macd_histogram'].iloc[-1]
                    
                    macd_trend = "金叉" if macd > macd_signal_line and df_1h['macd'].iloc[-2] <= df_1h['macd_signal'].iloc[-2] else \
                                "死叉" if macd < macd_signal_line and df_1h['macd'].iloc[-2] >= df_1h['macd_signal'].iloc[-2] else \
                                "多头" if macd > macd_signal_line else "空头"
                    
                    indicators['macd'] = {
                        'macd': macd,
                        'signal': macd_signal_line,
                        'histogram': macd_histogram,
                        'trend': macd_trend
                    }
                
                # 成交量分析
                if len(df_1h) >= 20:
                    df_1h['volume_ma'] = df_1h['volume'].rolling(20).mean()
                    current_volume = df_1h['volume'].iloc[-1]
                    avg_volume = df_1h['volume_ma'].iloc[-1]
                    
                    volume_ratio = current_volume / avg_volume
                    volume_signal = "放量" if volume_ratio > 1.5 else "缩量" if volume_ratio < 0.7 else "正常"
                    
                    indicators['volume'] = {
                        'current': current_volume,
                        'average': avg_volume,
                        'ratio': volume_ratio,
                        'signal': volume_signal
                    }
                
                # SuperTrend多周期分析
                supertrend_signals = await self._get_supertrend_multi_timeframe(symbol)
                if supertrend_signals:
                    indicators['supertrend'] = supertrend_signals
                
                return indicators
                
        except Exception as e:
            self.logger.warning(f"获取详细技术指标失败 {symbol}: {e}")
            return {}
    
    async def _get_supertrend_multi_timeframe(self, symbol: str) -> Dict[str, Any]:
        """获取SuperTrend多周期分析"""
        try:
            if not self.trend_service:
                return {}
            
            # 获取多周期SuperTrend信号
            timeframes = ['15m', '1h', '4h', '1d']
            signals = {}
            
            for tf in timeframes:
                try:
                    # 这里需要调用趋势分析服务的SuperTrend方法
                    # 暂时使用模拟数据
                    signals[tf] = "up"  # 实际应该调用真实的SuperTrend计算
                except Exception:
                    signals[tf] = "neutral"
            
            # 分析信号组合
            signal_combination = tuple(signals.values())
            
            # 根据信号组合判断强度和建议
            if signal_combination == ('up', 'up', 'up', 'up'):
                strength = "强势多头共振"
                recommendation = "坚决做多，分批建仓"
                priority = 1
            elif signal_combination.count('up') >= 3:
                strength = "多头优势"
                recommendation = "偏多操作，谨慎建仓"
                priority = 2
            elif signal_combination.count('down') >= 3:
                strength = "空头优势"
                recommendation = "偏空操作，考虑减仓"
                priority = 2
            elif signal_combination == ('down', 'down', 'down', 'down'):
                strength = "强势空头共振"
                recommendation = "坚决做空，严格止损"
                priority = 1
            else:
                strength = "震荡整理"
                recommendation = "观望为主，等待明确信号"
                priority = 3
            
            return {
                'signals': signals,
                'combination': signal_combination,
                'strength': strength,
                'recommendation': recommendation,
                'priority': priority
            }
            
        except Exception as e:
            self.logger.warning(f"SuperTrend多周期分析失败 {symbol}: {e}")
            return {}
    
    async def _get_ml_analysis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取ML分析结果"""
        try:
            if not self.ml_service:
                return None
            
            prediction = await self.ml_service.predict_signal(symbol)
            if prediction:
                return {
                    'signal': prediction.signal.value,
                    'confidence': prediction.confidence,
                    'probability_distribution': prediction.probability_distribution,
                    'features_importance': prediction.features_importance
                }
            return None
            
        except Exception as e:
            self.logger.warning(f"ML分析失败 {symbol}: {e}")
            return None
    
    async def _get_position_analysis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取持仓分析结果"""
        try:
            async with self.okx_service as exchange:
                positions = await exchange.get_positions()
                current_position = None
                
                for pos in positions:
                    if pos.get('instId') == symbol:
                        current_position = pos
                        break
                
                if current_position:
                    # 分析当前持仓
                    size = float(current_position.get('pos', 0))
                    if size != 0:
                        return {
                            'has_position': True,
                            'position_size': size,
                            'position_side': current_position.get('posSide', ''),
                            'unrealized_pnl': float(current_position.get('upl', 0)),
                            'unrealized_pnl_ratio': float(current_position.get('uplRatio', 0)),
                            'avg_price': float(current_position.get('avgPx', 0))
                        }
                
                return {'has_position': False}
                
        except Exception as e:
            self.logger.warning(f"持仓分析失败 {symbol}: {e}")
            return None
    
    async def _generate_integrated_signal(
        self,
        symbol: str,
        kronos_result: Optional[KronosEnhancedDecision],
        technical_result: Optional[Dict[str, Any]],
        ml_result: Optional[Dict[str, Any]],
        position_result: Optional[Dict[str, Any]],
        analysis_type: AnalysisType
    ) -> Optional[TradingSignal]:
        """生成综合交易信号"""
        
        if analysis_type == AnalysisType.KRONOS_ONLY and not kronos_result:
            return None
        
        # 获取当前价格
        current_price = 0
        try:
            async with self.okx_service as exchange:
                price_data = await exchange.get_current_price(symbol)
                current_price = float(price_data) if price_data else 0
        except Exception as e:
            self.logger.warning(f"获取价格失败 {symbol}: {e}")
        
        # 计算综合置信度和决策
        final_action, final_confidence, reasoning, key_factors = self._calculate_integrated_decision(
            kronos_result, technical_result, ml_result, position_result, analysis_type
        )
        
        # 确定信号强度
        signal_strength = self._determine_signal_strength(final_confidence)
        
        # 计算交易参数
        trade_params = self._calculate_trade_parameters(
            symbol, final_action, final_confidence, current_price,
            kronos_result, technical_result, position_result
        )
        
        # 确定紧急程度
        urgency = self._determine_urgency(final_action, final_confidence, signal_strength)
        
        # 确定交易时间建议
        trading_timeframe, holding_period, optimal_entry_time = self._determine_trading_timeframe(
            final_action, final_confidence, signal_strength, kronos_result, technical_result
        )
        
        # 整理技术指标详情
        technical_indicators = {}
        if technical_result and 'detailed_indicators' in technical_result:
            technical_indicators = technical_result['detailed_indicators']
        
        return TradingSignal(
            symbol=symbol,
            timestamp=datetime.now(),
            final_action=final_action,
            final_confidence=final_confidence,
            signal_strength=signal_strength,
            kronos_result=kronos_result,
            technical_result=technical_result,
            ml_result=ml_result,
            position_result=position_result,
            entry_price=current_price,
            stop_loss_price=trade_params['stop_loss'],
            take_profit_price=trade_params['take_profit'],
            position_size_usdt=trade_params['position_size'],
            leverage=trade_params['leverage'],
            risk_reward_ratio=trade_params['risk_reward_ratio'],
            reasoning=reasoning,
            key_factors=key_factors,
            confidence_breakdown=self._get_confidence_breakdown(
                kronos_result, technical_result, ml_result, position_result
            ),
            technical_indicators=technical_indicators,
            trading_timeframe=trading_timeframe,
            holding_period=holding_period,
            optimal_entry_time=optimal_entry_time,
            urgency=urgency
        )
    
    def _calculate_integrated_decision(
        self,
        kronos_result: Optional[KronosEnhancedDecision],
        technical_result: Optional[Dict[str, Any]],
        ml_result: Optional[Dict[str, Any]],
        position_result: Optional[Dict[str, Any]],
        analysis_type: AnalysisType
    ) -> Tuple[str, float, str, List[str]]:
        """计算综合决策 - 加重Kronos权重"""
        
        # 收集所有信号
        signals = []
        weights = []
        reasoning_parts = []
        key_factors = []
        
        # Kronos信号 - 提升权重和优先级
        kronos_confidence = 0
        if kronos_result:
            signals.append(kronos_result.final_action)
            weights.append(self.analysis_weights['kronos'])
            kronos_confidence = kronos_result.final_confidence
            reasoning_parts.append(f"Kronos预测: {kronos_result.final_action} (置信度: {kronos_confidence:.2f})")
            key_factors.append(f"Kronos强度: {kronos_result.kronos_signal_strength.value}")
        
        # 技术分析信号 - 增加详细指标信息
        technical_confidence = 0
        technical_details = []
        if technical_result:
            signals.append(technical_result['action'])
            weights.append(self.analysis_weights['technical'])
            technical_confidence = technical_result['confidence'] / 100.0  # 转换为小数形式
            
            # 构建详细的技术分析描述
            indicators = technical_result.get('detailed_indicators', {})
            
            # MA分析
            if 'moving_averages' in indicators:
                ma_info = indicators['moving_averages']
                technical_details.append(f"MA趋势: {ma_info.get('trend', 'N/A')}")
                technical_details.append(f"价格相对MA20: {ma_info.get('price_vs_ma20', 0):.1f}%")
            
            # 布林带分析
            if 'bollinger_bands' in indicators:
                bb_info = indicators['bollinger_bands']
                technical_details.append(f"布林带: {bb_info.get('position', 'N/A')} ({bb_info.get('signal', 'N/A')})")
            
            # RSI分析
            if 'rsi' in indicators:
                rsi_info = indicators['rsi']
                technical_details.append(f"RSI: {rsi_info.get('value', 0):.1f} ({rsi_info.get('signal', 'N/A')})")
            
            # MACD分析
            if 'macd' in indicators:
                macd_info = indicators['macd']
                technical_details.append(f"MACD: {macd_info.get('trend', 'N/A')}")
            
            # SuperTrend分析
            if 'supertrend' in indicators:
                st_info = indicators['supertrend']
                technical_details.append(f"SuperTrend: {st_info.get('strength', 'N/A')}")
            
            tech_detail_str = ", ".join(technical_details) if technical_details else "基础技术分析"
            reasoning_parts.append(f"技术分析: {technical_result['action']} (置信度: {technical_confidence:.2f}) [{tech_detail_str}]")
            key_factors.append(f"技术分析: {technical_result['action']}")
        
        # ML信号
        ml_confidence = 0
        if ml_result:
            signals.append(ml_result['signal'])
            weights.append(self.analysis_weights['ml'])
            ml_confidence = ml_result['confidence']
            reasoning_parts.append(f"ML预测: {ml_result['signal']} (置信度: {ml_confidence:.2f})")
            key_factors.append(f"ML信号: {ml_result['signal']}")
        
        # 持仓信息
        if position_result and position_result.get('has_position'):
            pnl_ratio = position_result.get('unrealized_pnl_ratio', 0)
            if pnl_ratio < -0.1:  # 亏损超过10%
                key_factors.append("持仓亏损较大")
            elif pnl_ratio > 0.1:  # 盈利超过10%
                key_factors.append("持仓盈利良好")
        
        if not signals:
            return "观望", 0.0, "无有效分析信号", []
        
        # 加权决策逻辑 - Kronos优先
        final_action = "观望"
        final_confidence = 0.5
        
        # 1. Kronos信号权重最高，优先考虑
        if kronos_result and kronos_confidence > 0.45:  # 降低Kronos阈值，增加其影响力
            # Kronos信号强度评估
            if kronos_confidence > 0.75:
                final_action = kronos_result.final_action
                final_confidence = kronos_confidence * 0.9  # 高置信度Kronos信号
            elif kronos_confidence > 0.6:
                # 中等置信度Kronos，结合技术分析
                if technical_result and technical_confidence > 0.7:
                    # 如果技术分析也支持，增强信号
                    if self._signals_align(kronos_result.final_action, technical_result['action']):
                        final_action = kronos_result.final_action
                        final_confidence = min(0.85, kronos_confidence * 0.7 + technical_confidence * 0.3)
                    else:
                        final_action = kronos_result.final_action
                        final_confidence = kronos_confidence * 0.8
                else:
                    final_action = kronos_result.final_action
                    final_confidence = kronos_confidence * 0.8
            else:
                # 低置信度Kronos，需要技术分析支持
                if technical_result and technical_confidence > 0.75:
                    if self._signals_align(kronos_result.final_action, technical_result['action']):
                        final_action = technical_result['action']
                        final_confidence = technical_confidence * 0.8
                    else:
                        final_action = "观望"
                        final_confidence = 0.5
                else:
                    final_action = "观望"
                    final_confidence = 0.5
        
        # 2. 如果没有Kronos信号，依赖技术分析
        elif technical_result and technical_confidence > 0.75:
            final_action = technical_result['action']
            final_confidence = technical_confidence * 0.85
        
        # 3. 最后考虑ML信号
        elif ml_result and ml_confidence > 0.8:
            final_action = ml_result['signal']
            final_confidence = ml_confidence * 0.7
        
        reasoning = " | ".join(reasoning_parts)
        
        return final_action, final_confidence, reasoning, key_factors
    
    def _signals_align(self, signal1: str, signal2: str) -> bool:
        """判断两个信号是否一致"""
        buy_signals = ['买入', 'buy', 'strong_buy', '强烈买入']
        sell_signals = ['卖出', 'sell', 'strong_sell', '强烈卖出']
        hold_signals = ['持有', 'hold', '观望']
        
        signal1_lower = signal1.lower()
        signal2_lower = signal2.lower()
        
        if signal1_lower in [s.lower() for s in buy_signals] and signal2_lower in [s.lower() for s in buy_signals]:
            return True
        elif signal1_lower in [s.lower() for s in sell_signals] and signal2_lower in [s.lower() for s in sell_signals]:
            return True
        elif signal1_lower in [s.lower() for s in hold_signals] and signal2_lower in [s.lower() for s in hold_signals]:
            return True
        
        return False
    
    def _determine_signal_strength(self, confidence: float) -> SignalStrength:
        """确定信号强度"""
        for strength, threshold in self.strength_thresholds.items():
            if confidence >= threshold:
                return strength
        return SignalStrength.VERY_WEAK
    
    def _calculate_trade_parameters(
        self,
        symbol: str,
        action: str,
        confidence: float,
        current_price: float,
        kronos_result: Optional[KronosEnhancedDecision],
        technical_result: Optional[Dict[str, Any]],
        position_result: Optional[Dict[str, Any]]
    ) -> Dict[str, float]:
        """计算交易参数"""
        
        # 基础参数
        base_stop_loss_pct = 0.03  # 3%止损
        base_take_profit_pct = 0.09  # 9%止盈 (1:3风险收益比)
        base_position_size = 1000  # 1000 USDT
        base_leverage = 2.0
        
        # 根据置信度调整参数
        confidence_multiplier = min(confidence / 0.8, 1.5)  # 最大1.5倍
        
        position_size = base_position_size * confidence_multiplier
        leverage = min(base_leverage * confidence_multiplier, 5.0)  # 最大5倍杠杆
        
        # 计算止损止盈价格
        if action.lower() in ['buy', 'strong_buy', '买入', '强烈买入']:
            stop_loss_price = current_price * (1 - base_stop_loss_pct)
            take_profit_price = current_price * (1 + base_take_profit_pct)
        elif action.lower() in ['sell', 'strong_sell', '卖出', '强烈卖出']:
            stop_loss_price = current_price * (1 + base_stop_loss_pct)
            take_profit_price = current_price * (1 - base_take_profit_pct)
        else:
            stop_loss_price = current_price
            take_profit_price = current_price
        
        # 使用技术分析的价格建议（如果可用）
        if technical_result:
            if technical_result.get('stop_loss', 0) > 0:
                stop_loss_price = technical_result['stop_loss']
            if technical_result.get('take_profit', 0) > 0:
                take_profit_price = technical_result['take_profit']
        
        # 计算风险收益比
        if current_price > 0 and stop_loss_price > 0:
            risk = abs(current_price - stop_loss_price) / current_price
            reward = abs(take_profit_price - current_price) / current_price
            risk_reward_ratio = reward / risk if risk > 0 else 0
        else:
            risk_reward_ratio = 3.0  # 默认1:3
        
        return {
            'stop_loss': stop_loss_price,
            'take_profit': take_profit_price,
            'position_size': position_size,
            'leverage': leverage,
            'risk_reward_ratio': risk_reward_ratio
        }
    
    def _determine_urgency(self, action: str, confidence: float, strength: SignalStrength) -> str:
        """确定紧急程度"""
        if strength == SignalStrength.VERY_STRONG and confidence > 0.9:
            return "immediate"
        elif strength == SignalStrength.STRONG and confidence > 0.8:
            return "urgent"
        elif strength in [SignalStrength.MODERATE, SignalStrength.STRONG]:
            return "normal"
        else:
            return "low"
    
    def _determine_trading_timeframe(
        self,
        action: str,
        confidence: float,
        strength: SignalStrength,
        kronos_result: Optional[KronosEnhancedDecision],
        technical_result: Optional[Dict[str, Any]]
    ) -> Tuple[str, str, str]:
        """
        确定交易时间建议
        
        Returns:
            Tuple[交易周期, 持有时间, 最佳入场时机]
        """
        
        # 基于信号强度和置信度确定交易周期
        if strength == SignalStrength.VERY_STRONG and confidence > 0.85:
            # 极强信号 - 短线快进快出
            trading_timeframe = "超短线"
            holding_period = "30分钟-2小时"
            optimal_entry_time = "立即执行"
            
        elif strength == SignalStrength.STRONG and confidence > 0.75:
            # 强信号 - 日内交易
            trading_timeframe = "日内"
            holding_period = "2-8小时"
            optimal_entry_time = "15分钟内"
            
        elif strength == SignalStrength.MODERATE and confidence > 0.65:
            # 中等信号 - 短线波段
            trading_timeframe = "短线"
            holding_period = "1-3天"
            optimal_entry_time = "1小时内"
            
        elif confidence > 0.55:
            # 较弱信号 - 波段操作
            trading_timeframe = "波段"
            holding_period = "3-7天"
            optimal_entry_time = "等待回调"
            
        else:
            # 弱信号 - 观望为主
            trading_timeframe = "观望"
            holding_period = "暂不建议"
            optimal_entry_time = "等待更强信号"
        
        # 根据Kronos预测调整时间框架
        if kronos_result:
            # Kronos通常适合中短期预测
            if kronos_result.final_confidence > 0.7:
                if trading_timeframe == "观望":
                    trading_timeframe = "日内"
                    holding_period = "4-12小时"
                    optimal_entry_time = "30分钟内"
                elif trading_timeframe in ["波段", "短线"]:
                    # Kronos信号强时，缩短持有周期
                    holding_period = "2-6小时"
        
        # 根据技术分析调整
        if technical_result and 'detailed_indicators' in technical_result:
            indicators = technical_result['detailed_indicators']
            
            # SuperTrend多周期共振时，延长持有时间
            if 'supertrend' in indicators:
                st_info = indicators['supertrend']
                if st_info.get('priority', 3) == 1:  # 强势共振
                    if trading_timeframe in ["超短线", "日内"]:
                        trading_timeframe = "短线"
                        holding_period = "1-2天"
            
            # RSI极值时，建议快进快出
            if 'rsi' in indicators:
                rsi_info = indicators['rsi']
                rsi_value = rsi_info.get('value', 50)
                if rsi_value > 80 or rsi_value < 20:
                    if trading_timeframe not in ["观望"]:
                        trading_timeframe = "超短线"
                        holding_period = "1-4小时"
                        optimal_entry_time = "立即执行"
            
            # 成交量异常时，建议快速反应
            if 'volume' in indicators:
                volume_info = indicators['volume']
                if volume_info.get('signal') == "放量" and volume_info.get('ratio', 1) > 2:
                    if optimal_entry_time not in ["立即执行"]:
                        optimal_entry_time = "15分钟内"
        
        # 市场时间调整（考虑美股开盘等重要时点）
        current_hour = datetime.now().hour
        
        # 美股开盘时间（北京时间21:30-22:30）
        if 21 <= current_hour <= 22:
            if optimal_entry_time == "等待回调":
                optimal_entry_time = "30分钟内"  # 美股开盘时段，加快节奏
        
        # 亚洲交易时段（北京时间9:00-17:00）
        elif 9 <= current_hour <= 17:
            if trading_timeframe == "超短线":
                holding_period = "2-6小时"  # 亚洲时段相对平稳，可适当延长
        
        return trading_timeframe, holding_period, optimal_entry_time
    
    def _get_confidence_breakdown(
        self,
        kronos_result: Optional[KronosEnhancedDecision],
        technical_result: Optional[Dict[str, Any]],
        ml_result: Optional[Dict[str, Any]],
        position_result: Optional[Dict[str, Any]]
    ) -> Dict[str, float]:
        """获取置信度分解"""
        breakdown = {}
        
        if kronos_result:
            breakdown['kronos'] = kronos_result.final_confidence
        if technical_result:
            breakdown['technical'] = technical_result['confidence'] / 100.0  # 转换为小数形式
        if ml_result:
            breakdown['ml'] = ml_result['confidence']
        if position_result:
            breakdown['position'] = 0.5  # 持仓分析默认中等置信度
        
        return breakdown
    
    async def batch_analyze_symbols(
        self,
        symbols: List[str],
        analysis_type: AnalysisType = AnalysisType.INTEGRATED,
        max_concurrent: int = 5
    ) -> Dict[str, Optional[TradingSignal]]:
        """批量分析交易对"""
        
        self.logger.info(f"🔄 开始批量分析 {len(symbols)} 个交易对")
        
        # 分批处理，避免过载
        results = {}
        
        for i in range(0, len(symbols), max_concurrent):
            batch_symbols = symbols[i:i + max_concurrent]
            
            # 并行分析当前批次
            tasks = [
                self.analyze_trading_signal(symbol, analysis_type, force_update=True)
                for symbol in batch_symbols
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 收集结果
            for j, result in enumerate(batch_results):
                symbol = batch_symbols[j]
                if isinstance(result, Exception):
                    self.logger.error(f"分析失败 {symbol}: {result}")
                    results[symbol] = None
                else:
                    results[symbol] = result
            
            # 批次间稍作延迟，避免API限制
            if i + max_concurrent < len(symbols):
                await asyncio.sleep(1)
        
        successful_count = sum(1 for r in results.values() if r is not None)
        self.logger.info(f"✅ 批量分析完成: {successful_count}/{len(symbols)} 成功")
        
        return results
    
    async def get_comprehensive_position_analysis(self) -> Optional[PositionAnalysisResult]:
        """获取综合持仓分析"""
        try:
            self.logger.info("📊 开始综合持仓分析...")
            
            # 获取当前持仓
            async with self.okx_service as exchange:
                positions = await exchange.get_positions()
                account_info = await exchange.get_account_balance()
            
            if not positions:
                return PositionAnalysisResult(
                    timestamp=datetime.now(),
                    total_positions=0,
                    total_value_usdt=0,
                    total_pnl_usdt=0,
                    total_pnl_percent=0,
                    risk_level="低",
                    positions=[],
                    recommendations=["当前无持仓"],
                    urgent_actions=[]
                )
            
            # 分析每个持仓
            position_analyses = []
            total_value = 0
            total_pnl = 0
            
            for pos in positions:
                pos_size = float(pos.get('pos', 0))
                if pos_size == 0:
                    continue
                
                symbol = pos.get('instId', '')
                notional_usd = float(pos.get('notionalUsd', 0))
                upl = float(pos.get('upl', 0))
                upl_ratio = float(pos.get('uplRatio', 0))
                
                total_value += abs(notional_usd)
                total_pnl += upl
                
                # 分析单个持仓
                position_analysis = {
                    'symbol': symbol,
                    'size': pos_size,
                    'side': pos.get('posSide', ''),
                    'notional_usd': notional_usd,
                    'unrealized_pnl': upl,
                    'unrealized_pnl_ratio': upl_ratio,
                    'avg_price': float(pos.get('avgPx', 0)),
                    'mark_price': float(pos.get('markPx', 0)),
                    'risk_level': self._assess_position_risk(upl_ratio)
                }
                position_analyses.append(position_analysis)
            
            # 计算总体指标
            total_pnl_percent = (total_pnl / total_value * 100) if total_value > 0 else 0
            overall_risk = self._assess_overall_risk(position_analyses, total_pnl_percent)
            
            # 生成建议
            recommendations, urgent_actions = self._generate_position_recommendations(
                position_analyses, total_pnl_percent, overall_risk
            )
            
            result = PositionAnalysisResult(
                timestamp=datetime.now(),
                total_positions=len(position_analyses),
                total_value_usdt=total_value,
                total_pnl_usdt=total_pnl,
                total_pnl_percent=total_pnl_percent,
                risk_level=overall_risk,
                positions=position_analyses,
                recommendations=recommendations,
                urgent_actions=urgent_actions
            )
            
            self.logger.info(f"✅ 持仓分析完成: {len(position_analyses)}个持仓, 总盈亏: {total_pnl_percent:.1f}%")
            return result
            
        except Exception as e:
            self.logger.error(f"综合持仓分析失败: {e}")
            return None
    
    def _assess_position_risk(self, pnl_ratio: float) -> str:
        """评估单个持仓风险"""
        if pnl_ratio < -0.15:
            return "高风险"
        elif pnl_ratio < -0.08:
            return "中风险"
        elif pnl_ratio > 0.2:
            return "高收益"
        else:
            return "正常"
    
    def _assess_overall_risk(self, positions: List[Dict[str, Any]], total_pnl_percent: float) -> str:
        """评估整体风险"""
        high_risk_count = sum(1 for pos in positions if pos['risk_level'] == "高风险")
        
        if total_pnl_percent < -10 or high_risk_count >= 2:
            return "高风险"
        elif total_pnl_percent < -5 or high_risk_count >= 1:
            return "中风险"
        else:
            return "低风险"
    
    def _generate_position_recommendations(
        self,
        positions: List[Dict[str, Any]],
        total_pnl_percent: float,
        overall_risk: str
    ) -> Tuple[List[str], List[str]]:
        """生成持仓建议"""
        recommendations = []
        urgent_actions = []
        
        # 检查高风险持仓
        high_risk_positions = [pos for pos in positions if pos['risk_level'] == "高风险"]
        for pos in high_risk_positions:
            urgent_actions.append(f"⚠️ {pos['symbol']} 亏损 {pos['unrealized_pnl_ratio']:.1%}，建议考虑止损")
        
        # 检查高收益持仓
        high_profit_positions = [pos for pos in positions if pos['risk_level'] == "高收益"]
        for pos in high_profit_positions:
            recommendations.append(f"🎯 {pos['symbol']} 盈利 {pos['unrealized_pnl_ratio']:.1%}，建议考虑止盈")
        
        # 整体建议
        if total_pnl_percent < -10:
            urgent_actions.append("❌ 整体账户亏损超过10%，建议严格风控")
        elif total_pnl_percent > 15:
            recommendations.append("✅ 整体账户盈利良好，可适当加仓优质标的")
        
        if not recommendations:
            recommendations.append("📊 持仓状况正常，继续观察市场走势")
        
        return recommendations, urgent_actions
    
    async def send_trading_signal_notification(self, signal: TradingSignal) -> bool:
        """发送交易信号通知"""
        try:
            # 只推送强信号
            if signal.signal_strength not in [SignalStrength.STRONG, SignalStrength.VERY_STRONG]:
                return False
            
            # 获取通知服务
            if not self.notification_service:
                self.notification_service = await get_core_notification_service()
            
            # 构建详细的技术分析描述
            technical_summary = self._build_technical_summary(signal.technical_indicators)
            
            # 构建通知数据
            signal_data = {
                'symbol': signal.symbol,
                'action': signal.final_action,
                'confidence': signal.final_confidence,
                'current_price': signal.entry_price,
                'stop_loss': signal.stop_loss_price,
                'take_profit': signal.take_profit_price,
                'reasoning': signal.reasoning,
                'key_factors': signal.key_factors,
                'urgency': signal.urgency,
                'timestamp': signal.timestamp,
                
                # 新增详细信息
                'technical_summary': technical_summary,
                'trading_timeframe': signal.trading_timeframe,
                'holding_period': signal.holding_period,
                'optimal_entry_time': signal.optimal_entry_time,
                'confidence_breakdown': signal.confidence_breakdown,
                'signal_strength': signal.signal_strength.value
            }
            
            # 发送通知
            return await self.notification_service.send_trading_signal(signal_data)
            
        except Exception as e:
            self.logger.error(f"发送交易信号通知失败: {e}")
            return False
    
    def _build_technical_summary(self, technical_indicators: Dict[str, Any]) -> str:
        """构建技术分析摘要"""
        if not technical_indicators:
            return "基础技术分析"
        
        summary_parts = []
        
        # MA分析
        if 'moving_averages' in technical_indicators:
            ma_info = technical_indicators['moving_averages']
            trend = ma_info.get('trend', 'N/A')
            price_vs_ma20 = ma_info.get('price_vs_ma20', 0)
            summary_parts.append(f"MA{trend}(偏离MA20: {price_vs_ma20:+.1f}%)")
        
        # 布林带分析
        if 'bollinger_bands' in technical_indicators:
            bb_info = technical_indicators['bollinger_bands']
            position = bb_info.get('position', 'N/A')
            signal = bb_info.get('signal', 'N/A')
            summary_parts.append(f"布林带{position}({signal})")
        
        # RSI分析
        if 'rsi' in technical_indicators:
            rsi_info = technical_indicators['rsi']
            rsi_value = rsi_info.get('value', 0)
            rsi_signal = rsi_info.get('signal', 'N/A')
            summary_parts.append(f"RSI{rsi_value:.0f}({rsi_signal})")
        
        # MACD分析
        if 'macd' in technical_indicators:
            macd_info = technical_indicators['macd']
            macd_trend = macd_info.get('trend', 'N/A')
            summary_parts.append(f"MACD{macd_trend}")
        
        # SuperTrend分析
        if 'supertrend' in technical_indicators:
            st_info = technical_indicators['supertrend']
            st_strength = st_info.get('strength', 'N/A')
            summary_parts.append(f"SuperTrend{st_strength}")
        
        # 成交量分析
        if 'volume' in technical_indicators:
            volume_info = technical_indicators['volume']
            volume_signal = volume_info.get('signal', 'N/A')
            volume_ratio = volume_info.get('ratio', 1)
            summary_parts.append(f"成交量{volume_signal}({volume_ratio:.1f}倍)")
        
        return " | ".join(summary_parts) if summary_parts else "基础技术分析"


# 全局服务实例
_core_trading_service = None


async def get_core_trading_service() -> CoreTradingService:
    """获取核心交易服务实例"""
    global _core_trading_service
    if _core_trading_service is None:
        _core_trading_service = CoreTradingService()
    return _core_trading_service
