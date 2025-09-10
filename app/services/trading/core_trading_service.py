# -*- coding: utf-8 -*-
"""
核心交易服务
Core Trading Service - 统一管理所有交易决策功能
整合Kronos预测、技术分析、ML预测、持仓分析等所有交易相关功能
"""

import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.ml_weight_config import get_ml_weight_config
from app.services.ml.kronos_integrated_decision_service import (
    get_kronos_integrated_service, 
    KronosEnhancedDecision
)
from app.services.analysis.position_analysis_service import PositionAnalysisService
from app.services.exchanges.service_manager import get_current_exchange_service
from app.services.trading.trading_decision_service import TradingDecisionService
from app.services.ml.ml_enhanced_service import MLEnhancedService
from app.services.analysis.trend_analysis_service import TrendAnalysisService
from app.services.volume_anomaly_service import get_volume_anomaly_service
from app.services.analysis.open_interest_analysis_service import get_oi_analysis_service
from app.services.core.dynamic_weight_service import get_dynamic_weight_service
from app.services.notification.core_notification_service import get_core_notification_service

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


@dataclass
class TradingSession:
    """交易会话 - 整合自comprehensive_trading_service"""
    session_id: str
    symbols: List[str]
    start_time: datetime
    end_time: Optional[datetime]
    total_analyses: int
    successful_analyses: int
    recommendations_sent: int
    alerts_sent: int
    status: str  # "active", "completed", "error"


@dataclass
class PortfolioSnapshot:
    """投资组合快照 - 整合自comprehensive_trading_service"""
    timestamp: datetime
    total_value: float
    positions: Dict[str, float]
    risk_score: float
    recommendations: List[Dict[str, Any]]
    market_conditions: Dict[str, Any]


class MarketRegime(Enum):
    """市场状态枚举 - 整合自unified_trading_service"""
    TRENDING_UP = "上涨趋势"
    TRENDING_DOWN = "下跌趋势"
    RANGING = "震荡整理"
    VOLATILE = "高波动"
    CALM = "平静"


@dataclass
class UnifiedTradingRecommendation:
    """统一交易建议 - 整合自unified_trading_service"""
    symbol: str
    timestamp: datetime
    final_action: str
    confidence: float
    traditional_signal: str
    traditional_confidence: float
    ml_signal: str
    ml_confidence: float
    market_regime: MarketRegime
    volatility_level: str
    dynamic_stop_loss: float
    dynamic_take_profit: float
    risk_reward_ratio: float
    position_size_percent: float
    leverage: float
    risk_level: str
    current_price: float
    entry_price: float
    reasoning: str
    key_factors: List[str]
    entry_timing: str
    hold_duration_hours: Optional[int]


class CoreTradingService:
    """核心交易服务类 - 统一交易决策中心
    整合了comprehensive_trading_service和unified_trading_service的所有功能
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # 初始化各个分析服务
        self.exchange_service = None  # 将在需要时异步初始化（通过工厂模式）
        self.position_service = PositionAnalysisService()
        self.traditional_service = TradingDecisionService()
        
        # 可选服务（可能初始化失败）
        self.kronos_service = None
        self.ml_service = None
        self.trend_service = None
        self.notification_service = None
        
        # 增强服务
        self.volume_anomaly_service = get_volume_anomaly_service()
        self.oi_analysis_service = get_oi_analysis_service()
        self.dynamic_weight_service = get_dynamic_weight_service()
        
        # 初始化可选服务
        self._initialize_optional_services()
        
        # 会话管理 - 整合自comprehensive_trading_service
        self.active_sessions: Dict[str, TradingSession] = {}
        self.portfolio_history: List[PortfolioSnapshot] = []
        
        # 配置参数
        self.max_concurrent_analyses = 10
        self.session_timeout_hours = 24
        self.portfolio_snapshot_interval = 3600  # 1小时
        
        # 获取ML权重配置管理器
        self.ml_config = get_ml_weight_config()
        
        # 基础权重配置 - 将被动态权重服务覆盖
        base_weights = self.ml_config.get_weights()
        self.base_analysis_weights = {
            'kronos': 0.50,                                    # Kronos AI预测权重50%
            'technical': base_weights.get('traditional', 0.35), # 技术分析权重(动态)
            'ml': base_weights.get('ml', 0.10),                # ML预测权重(动态)
            'position': 0.05                                   # 持仓分析权重5%
        }
        
        logger.info(f"🔧 基础交易权重配置: ML模式={self.ml_config.current_mode.value}, 权重={self.base_analysis_weights}")
        logger.info("⚖️ 启用动态权重管理: 将根据市场波动性自动调整权重")
        
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

    async def batch_analyze_symbols(
        self,
        symbols: List[str],
        analysis_type: AnalysisType = AnalysisType.INTEGRATED,
        max_concurrent: int = 5,
        force_update: bool = False
    ) -> Dict[str, Optional[TradingSignal]]:
        """批量分析多个交易对
        
        Args:
            symbols: 要分析的交易对列表
            analysis_type: 分析类型
            max_concurrent: 最大并发数
            force_update: 是否强制更新
            
        Returns:
            Dict[str, Optional[TradingSignal]]: 分析结果字典
        """
        self.logger.info(f"🔄 开始批量分析 {len(symbols)} 个交易对，分析类型: {analysis_type.value}")
        
        # 创建信号量控制并发
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def analyze_single_symbol(symbol: str) -> Tuple[str, Optional[TradingSignal]]:
            """分析单个交易对"""
            async with semaphore:
                try:
                    signal = await self.analyze_symbol(
                        symbol=symbol,
                        analysis_type=analysis_type,
                        force_update=force_update
                    )
                    return symbol, signal
                except Exception as e:
                    self.logger.error(f"❌ 分析 {symbol} 失败: {e}")
                    return symbol, None
        
        # 并发执行分析
        tasks = [analyze_single_symbol(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果
        analysis_results = {}
        successful_count = 0
        
        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"❌ 批量分析任务异常: {result}")
                continue
                
            symbol, signal = result
            analysis_results[symbol] = signal
            if signal is not None:
                successful_count += 1
        
        self.logger.info(f"✅ 批量分析完成: {successful_count}/{len(symbols)} 成功")
        return analysis_results

    async def analyze_symbol(
        self,
        symbol: str,
        analysis_type: AnalysisType = AnalysisType.INTEGRATED,
        force_update: bool = False
    ) -> Optional[TradingSignal]:
        """分析单个交易对 - 增强版，集成交易量异常、持仓量变动和动态权重
        
        Args:
            symbol: 交易对
            analysis_type: 分析类型
            force_update: 是否强制更新
            
        Returns:
            Optional[TradingSignal]: 交易信号
        """
        try:
            self.logger.debug(f"🔍 开始增强分析 {symbol}，类型: {analysis_type.value}")
            
            # 获取当前价格 - 使用交易所服务管理器
            try:
                if self.exchange_service is None:
                    self.exchange_service = await get_current_exchange_service()
                
                current_price = await self.exchange_service.get_current_price(symbol)
                if current_price is None:
                    current_price = 0
            except Exception as e:
                self.logger.warning(f"⚠️ 获取 {symbol} 价格失败: {e}")
                current_price = 0
            
            # 🚀 获取动态权重配置
            dynamic_weights = await self.dynamic_weight_service.get_dynamic_weights(symbol)
            
            # 🔊 获取交易量异常分析
            volume_anomaly = await self.volume_anomaly_service.detect_volume_anomaly(symbol)
            
            # 📊 获取持仓量变动分析
            oi_analysis = await self.oi_analysis_service.analyze_open_interest(symbol)
            
            # 根据分析类型执行不同的分析
            kronos_result = None
            technical_result = None
            ml_result = None
            position_result = None
            
            if analysis_type in [AnalysisType.KRONOS_ONLY, AnalysisType.INTEGRATED]:
                kronos_result = await self._get_kronos_analysis(symbol, force_update)
            
            if analysis_type in [AnalysisType.TECHNICAL_ONLY, AnalysisType.INTEGRATED]:
                technical_result = await self._get_technical_analysis(symbol)
            
            if analysis_type in [AnalysisType.ML_ONLY, AnalysisType.INTEGRATED]:
                ml_result = await self._get_ml_analysis(symbol)
            
            if analysis_type in [AnalysisType.POSITION_FOCUSED, AnalysisType.INTEGRATED]:
                position_result = await self._get_position_analysis(symbol)
            
            # 🎯 综合分析结果 - 使用增强版综合分析
            signal = await self._synthesize_enhanced_analysis_results(
                symbol=symbol,
                current_price=current_price,
                kronos_result=kronos_result,
                technical_result=technical_result,
                ml_result=ml_result,
                position_result=position_result,
                dynamic_weights=dynamic_weights,
                volume_anomaly=volume_anomaly,
                oi_analysis=oi_analysis,
                analysis_type=analysis_type
            )
            
            return signal
            
        except Exception as e:
            self.logger.error(f"❌ 增强分析 {symbol} 失败: {e}")
            return None

    async def _get_kronos_analysis(self, symbol: str, force_update: bool = False) -> Optional[KronosEnhancedDecision]:
        """获取Kronos分析结果"""
        try:
            if self.kronos_service is None:
                self.kronos_service = await get_kronos_integrated_service()
            
            return await self.kronos_service.get_kronos_enhanced_decision(symbol, force_update)
        except Exception as e:
            self.logger.warning(f"⚠️ Kronos分析失败 {symbol}: {e}")
            return None

    async def _get_technical_analysis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取技术分析结果"""
        try:
            recommendation = await self.traditional_service.get_trading_recommendation(symbol)
            return {
                'action': recommendation.action,
                'confidence': recommendation.confidence,
                'recommendation': recommendation
            }
        except Exception as e:
            self.logger.warning(f"⚠️ 技术分析失败 {symbol}: {e}")
            return None

    async def _get_ml_analysis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取ML分析结果"""
        try:
            if self.ml_service is None:
                return None
            
            prediction = await self.ml_service.predict_signal(symbol)
            return {
                'signal': prediction.signal.value if prediction else 'HOLD',
                'confidence': prediction.confidence if prediction else 0.5,
                'prediction': prediction
            }
        except Exception as e:
            self.logger.warning(f"⚠️ ML分析失败 {symbol}: {e}")
            return None

    async def _get_position_analysis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取持仓分析结果"""
        try:
            analysis = await self.position_service.analyze_account_positions()
            # 查找该交易对的持仓信息
            positions = analysis.get('positions', [])
            for pos in positions:
                if pos.get('symbol') == symbol:
                    return pos
            return None
        except Exception as e:
            self.logger.warning(f"⚠️ 持仓分析失败 {symbol}: {e}")
            return None

    async def _synthesize_enhanced_analysis_results(
        self,
        symbol: str,
        current_price: float,
        kronos_result: Optional[KronosEnhancedDecision],
        technical_result: Optional[Dict[str, Any]],
        ml_result: Optional[Dict[str, Any]],
        position_result: Optional[Dict[str, Any]],
        dynamic_weights,
        volume_anomaly,
        oi_analysis,
        analysis_type: AnalysisType
    ) -> TradingSignal:
        """增强版综合分析结果生成交易信号 - 集成交易量异常、持仓量变动和动态权重"""
        
        # 使用动态权重替代固定权重
        analysis_weights = {
            'kronos': dynamic_weights.kronos_weight,
            'technical': dynamic_weights.technical_weight,
            'ml': dynamic_weights.ml_weight,
            'position': dynamic_weights.position_weight
        }
        
        self.logger.debug(
            f"🎯 {symbol} 动态权重: Kronos={analysis_weights['kronos']:.2f} "
            f"技术={analysis_weights['technical']:.2f} ML={analysis_weights['ml']:.2f} "
            f"市场状态={dynamic_weights.market_regime.value}"
        )
        
        # 收集各模块的信号和置信度
        signals = []
        confidences = []
        reasoning_parts = []
        enhancement_factors = []  # 增强因子
        
        # Kronos分析 - 增强失败处理和权重转移
        kronos_weight_transferred = 0.0
        if kronos_result:
            signals.append(kronos_result.final_action)
            confidences.append(kronos_result.final_confidence * analysis_weights['kronos'])
            reasoning_parts.append(f"Kronos: {kronos_result.final_action} ({kronos_result.final_confidence:.2f})")
        else:
            # Kronos 分析失败，将权重转移给技术分析
            kronos_weight_transferred = analysis_weights['kronos']
            analysis_weights['technical'] += kronos_weight_transferred
            self.logger.info(f"⚠️ Kronos分析失败，权重({kronos_weight_transferred:.2f})转移给技术分析")
            reasoning_parts.append(f"Kronos: 分析失败，权重转移给技术分析")
        
        # 技术分析 - 支持Kronos权重转移
        if technical_result:
            tech_action_enum = technical_result.get('action', 'HOLD')
            # 处理TradingAction枚举对象
            if hasattr(tech_action_enum, 'value'):
                tech_action = tech_action_enum.value
            else:
                tech_action = str(tech_action_enum)
            tech_confidence = technical_result.get('confidence', 0.5)
            signals.append(tech_action)
            # 使用更新后的技术分析权重（可能包含从Kronos转移的权重）
            tech_weight_used = analysis_weights['technical']
            confidences.append(tech_confidence * tech_weight_used)
            
            if kronos_weight_transferred > 0:
                reasoning_parts.append(f"技术(含Kronos权重): {tech_action} ({tech_confidence:.2f}, 权重:{tech_weight_used:.2f})")
            else:
                reasoning_parts.append(f"技术: {tech_action} ({tech_confidence:.2f})")
        
        # ML分析
        if ml_result:
            ml_action = ml_result.get('signal', 'HOLD')
            ml_confidence = ml_result.get('confidence', 0.5)
            signals.append(ml_action)
            confidences.append(ml_confidence * analysis_weights['ml'])
            reasoning_parts.append(f"ML: {ml_action} ({ml_confidence:.2f})")
        
        # 🔊 交易量异常增强
        volume_boost = 0.0
        if volume_anomaly:
            # 根据信号方向调整置信度
            primary_action = self._determine_primary_action(signals)
            volume_boost = self.volume_anomaly_service.get_volume_confidence_adjustment(symbol, primary_action)
            if volume_boost != 0:
                enhancement_factors.append(f"交易量异常: {volume_boost:+.1%}")
                reasoning_parts.append(f"交易量: {volume_anomaly.anomaly_level.value} ({volume_anomaly.volume_ratio:.1f}倍)")
        
        # 📊 持仓量变动增强
        oi_boost = 0.0
        if oi_analysis:
            # 获取多周期趋势方向（从技术分析中提取）
            trend_direction = self._extract_trend_direction(technical_result)
            oi_boost = self.oi_analysis_service.get_trend_confirmation_boost(symbol, trend_direction)
            if oi_boost != 0:
                enhancement_factors.append(f"持仓量确认: {oi_boost:+.1%}")
                reasoning_parts.append(f"持仓量: {oi_analysis.trend_signal.value} ({oi_analysis.oi_change_percent:+.1f}%)")
        
        # 计算基础综合决策
        if not signals:
            final_action = "HOLD"
            final_confidence = 0.5
        else:
            final_action, base_confidence = self._enhanced_decision_logic(
                signals, confidences, kronos_result, dynamic_weights
            )
            
            # 🎯 应用增强因子
            final_confidence = base_confidence + volume_boost + oi_boost
            
            # 应用动态权重的置信度乘数
            final_confidence *= dynamic_weights.confidence_multiplier
            
            # 确保置信度在合理范围内
            final_confidence = max(0.1, min(final_confidence, 0.95))
        
        # 记录增强效果
        if enhancement_factors:
            self.logger.info(f"🚀 {symbol} 信号增强: {' | '.join(enhancement_factors)}")
        
        # 确定信号强度
        signal_strength = self._determine_signal_strength(final_confidence)
        
        # 提取技术指标详情（保持原有逻辑）
        technical_indicators = {}
        key_factors = []
        
        if technical_result and 'recommendation' in technical_result:
            recommendation = technical_result['recommendation']
            
            # 提取详细的技术指标数据
            if hasattr(recommendation, 'key_levels') and recommendation.key_levels:
                technical_indicators['support_levels'] = recommendation.key_levels.get('support', [])
                technical_indicators['resistance_levels'] = recommendation.key_levels.get('resistance', [])
            
            # 获取详细技术指标（保持原有逻辑）
            try:
                market_analysis = await self.traditional_service.analyze_market(symbol)
                if market_analysis and hasattr(market_analysis, 'traditional_signals'):
                    traditional_signals = market_analysis.traditional_signals
                    
                    if traditional_signals and 'technical_indicators' in traditional_signals:
                        tech_indicators = traditional_signals['technical_indicators']
                        technical_indicators.update({
                            'rsi_14': tech_indicators.get('rsi_14'),
                            'macd_line': tech_indicators.get('macd_line'),
                            'macd_signal': tech_indicators.get('macd_signal'),
                            'macd_histogram': tech_indicators.get('macd_histogram'),
                            'bb_upper': tech_indicators.get('bb_upper'),
                            'bb_middle': tech_indicators.get('bb_middle'),
                            'bb_lower': tech_indicators.get('bb_lower'),
                            'kdj_k': tech_indicators.get('kdj_k'),
                            'kdj_d': tech_indicators.get('kdj_d'),
                            'kdj_j': tech_indicators.get('kdj_j'),
                            'atr_14': tech_indicators.get('atr_14'),
                            'williams_r': tech_indicators.get('williams_r'),
                            'ma5': tech_indicators.get('ma5'),
                            'ma10': tech_indicators.get('ma10'),
                            'ma20': tech_indicators.get('ma20'),
                            'ma30': tech_indicators.get('ma30'),
                            'ma60': tech_indicators.get('ma60'),
                            'ema12': tech_indicators.get('ema12'),
                            'ema26': tech_indicators.get('ema26')
                        })
                        
                        if 'signals' in traditional_signals:
                            signals_data = traditional_signals['signals']
                            technical_indicators.update({
                                'rsi_signal': signals_data.get('rsi_signal'),
                                'macd_signal': signals_data.get('macd_signal'),
                                'bb_signal': signals_data.get('bb_signal'),
                                'kdj_signal': signals_data.get('kdj_signal'),
                                'ma_signal': signals_data.get('ma_signal'),
                                'trend_signal': signals_data.get('trend_signal'),
                                'volume_signal': signals_data.get('volume_signal')
                            })
            except Exception as e:
                self.logger.warning(f"❌ 获取详细技术指标失败 {symbol}: {e}")
            
            # 提取关键因子
            if hasattr(recommendation, 'reasoning') and recommendation.reasoning:
                reasoning_text = recommendation.reasoning
                if 'RSI' in reasoning_text:
                    key_factors.append("RSI技术指标")
                if 'MACD' in reasoning_text:
                    key_factors.append("MACD趋势指标")
                if 'MA' in reasoning_text or '均线' in reasoning_text:
                    key_factors.append("移动平均线")
                if '布林' in reasoning_text or 'Bollinger' in reasoning_text:
                    key_factors.append("布林带指标")
                if '成交量' in reasoning_text or 'volume' in reasoning_text:
                    key_factors.append("成交量分析")
                if '突破' in reasoning_text or 'breakout' in reasoning_text:
                    key_factors.append("价格突破")
        
        # 添加增强因子到关键因子
        if volume_anomaly and volume_anomaly.anomaly_level.value != 'normal':
            key_factors.append(f"交易量异常({volume_anomaly.anomaly_level.value})")
        
        if oi_analysis and oi_analysis.change_level.value != 'normal':
            key_factors.append(f"持仓量变动({oi_analysis.change_level.value})")
        
        # 添加其他因素
        if kronos_result:
            key_factors.append("Kronos AI预测")
            if hasattr(kronos_result, 'key_factors'):
                key_factors.extend(kronos_result.key_factors)
        
        if ml_result:
            key_factors.append("机器学习预测")
        
        key_factors.append(f"动态权重({dynamic_weights.market_regime.value})")
        
        # 计算风险管理参数
        stop_loss_price, take_profit_price, position_size_usdt = self._calculate_risk_management_params(
            current_price, final_action, final_confidence
        )
        
        # 创建增强版交易信号
        signal = TradingSignal(
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
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            position_size_usdt=position_size_usdt,
            leverage=self._calculate_leverage(final_confidence),
            reasoning=" | ".join(reasoning_parts),
            key_factors=key_factors,
            technical_indicators=technical_indicators,
            confidence_breakdown={
                'kronos': kronos_result.final_confidence if kronos_result else 0,
                'technical': technical_result.get('confidence', 0) if technical_result else 0,
                'ml': ml_result.get('confidence', 0) if ml_result else 0,
                'volume_boost': volume_boost,
                'oi_boost': oi_boost,
                'confidence_multiplier': dynamic_weights.confidence_multiplier
            }
        )
        
        return signal

    async def _synthesize_analysis_results(
        self,
        symbol: str,
        current_price: float,
        kronos_result: Optional[KronosEnhancedDecision],
        technical_result: Optional[Dict[str, Any]],
        ml_result: Optional[Dict[str, Any]],
        position_result: Optional[Dict[str, Any]],
        analysis_type: AnalysisType
    ) -> TradingSignal:
        """综合分析结果生成交易信号"""
        
        # 收集各模块的信号和置信度
        signals = []
        confidences = []
        reasoning_parts = []
        
        # Kronos分析
        if kronos_result:
            signals.append(kronos_result.final_action)
            confidences.append(kronos_result.final_confidence * self.analysis_weights['kronos'])
            reasoning_parts.append(f"Kronos: {kronos_result.final_action} ({kronos_result.final_confidence:.2f})")
        
        # 技术分析
        if technical_result:
            tech_action = technical_result.get('action', 'HOLD')
            tech_confidence = technical_result.get('confidence', 0.5)
            signals.append(tech_action)
            confidences.append(tech_confidence * self.analysis_weights['technical'])
            reasoning_parts.append(f"技术: {tech_action} ({tech_confidence:.2f})")
        
        # ML分析
        if ml_result:
            ml_action = ml_result.get('signal', 'HOLD')
            ml_confidence = ml_result.get('confidence', 0.5)
            signals.append(ml_action)
            confidences.append(ml_confidence * self.analysis_weights['ml'])
            reasoning_parts.append(f"ML: {ml_action} ({ml_confidence:.2f})")
        
        # 优化的综合决策逻辑
        if not signals:
            final_action = "HOLD"
            final_confidence = 0.5
        else:
            # 特殊处理：Kronos极高置信度时的决策优化
            kronos_confidence = kronos_result.final_confidence if kronos_result else 0
            kronos_action = kronos_result.final_action if kronos_result else "HOLD"
            
            # 当Kronos置信度>=90%时，给予绝对优先权
            if kronos_confidence >= 0.90:
                if "买入" in kronos_action or "BUY" in kronos_action.upper():
                    final_action = "BUY"
                    # 极高置信度时，即使技术分析冲突也保持高置信度
                    final_confidence = max(0.75, kronos_confidence * 0.9)  # 至少75%置信度
                    self.logger.info(f"🔥 Kronos极高置信度({kronos_confidence:.2f})主导决策: {final_action}")
                elif "卖出" in kronos_action or "SELL" in kronos_action.upper():
                    final_action = "SELL"
                    final_confidence = max(0.75, kronos_confidence * 0.9)
                    self.logger.info(f"🔥 Kronos极高置信度({kronos_confidence:.2f})主导决策: {final_action}")
                else:
                    # Kronos建议观望时使用常规逻辑
                    final_action, final_confidence = self._regular_decision_logic(signals, confidences)
            
            # 当Kronos置信度>=80%时，给予高权重
            elif kronos_confidence >= 0.80:
                if "买入" in kronos_action or "BUY" in kronos_action.upper():
                    final_action = "BUY"
                    # 动态调整权重：Kronos 70%, 其他 30%
                    kronos_weight = 0.7
                    other_weight = 0.3
                    final_confidence = (kronos_confidence * kronos_weight + 
                                      sum(confidences[1:]) * other_weight) if len(confidences) > 1 else kronos_confidence * 0.85
                    self.logger.info(f"🎯 Kronos高置信度({kronos_confidence:.2f})主导决策: {final_action}")
                elif "卖出" in kronos_action or "SELL" in kronos_action.upper():
                    final_action = "SELL"
                    kronos_weight = 0.7
                    other_weight = 0.3
                    final_confidence = (kronos_confidence * kronos_weight + 
                                      sum(confidences[1:]) * other_weight) if len(confidences) > 1 else kronos_confidence * 0.85
                    self.logger.info(f"🎯 Kronos高置信度({kronos_confidence:.2f})主导决策: {final_action}")
                else:
                    final_action, final_confidence = self._regular_decision_logic(signals, confidences)
            
            # 常规决策逻辑
            else:
                final_action, final_confidence = self._regular_decision_logic(signals, confidences)
        
        # 确定信号强度
        signal_strength = self._determine_signal_strength(final_confidence)
        
        # 提取技术指标详情
        technical_indicators = {}
        key_factors = []
        
        if technical_result and 'recommendation' in technical_result:
            recommendation = technical_result['recommendation']
            
            # 提取详细的技术指标数据
            if hasattr(recommendation, 'key_levels') and recommendation.key_levels:
                # 提取支撑阻力位
                technical_indicators['support_levels'] = recommendation.key_levels.get('support', [])
                technical_indicators['resistance_levels'] = recommendation.key_levels.get('resistance', [])
            
            # 总是尝试获取详细的技术指标数据
            try:
                # 获取详细的技术分析数据
                self.logger.info(f"🔍 开始获取技术指标数据: {symbol}")
                market_analysis = await self.traditional_service.analyze_market(symbol)
                self.logger.info(f"✅ 技术分析结果: {market_analysis is not None}")
                
                if market_analysis and hasattr(market_analysis, 'traditional_signals'):
                    traditional_signals = market_analysis.traditional_signals
                    self.logger.info(f"📊 技术指标数量: {len(traditional_signals.get('technical_indicators', {}))}")
                    
                    # 提取各种技术指标
                    if traditional_signals and 'technical_indicators' in traditional_signals:
                        tech_indicators = traditional_signals['technical_indicators']
                        technical_indicators.update({
                            'rsi_14': tech_indicators.get('rsi_14'),
                            'macd_line': tech_indicators.get('macd_line'),
                            'macd_signal': tech_indicators.get('macd_signal'),
                            'macd_histogram': tech_indicators.get('macd_histogram'),
                            'bb_upper': tech_indicators.get('bb_upper'),
                            'bb_middle': tech_indicators.get('bb_middle'),
                            'bb_lower': tech_indicators.get('bb_lower'),
                            'kdj_k': tech_indicators.get('kdj_k'),
                            'kdj_d': tech_indicators.get('kdj_d'),
                            'kdj_j': tech_indicators.get('kdj_j'),
                            'atr_14': tech_indicators.get('atr_14'),
                            'williams_r': tech_indicators.get('williams_r'),
                            'ma5': tech_indicators.get('ma5'),
                            'ma10': tech_indicators.get('ma10'),
                            'ma20': tech_indicators.get('ma20'),
                            'ma30': tech_indicators.get('ma30'),
                            'ma60': tech_indicators.get('ma60'),
                            'ema12': tech_indicators.get('ema12'),
                            'ema26': tech_indicators.get('ema26')
                        })
                        
                        # 提取信号状态
                        if 'signals' in traditional_signals:
                            signals = traditional_signals['signals']
                            technical_indicators.update({
                                'rsi_signal': signals.get('rsi_signal'),
                                'macd_signal': signals.get('macd_signal'),
                                'bb_signal': signals.get('bb_signal'),
                                'kdj_signal': signals.get('kdj_signal'),
                                'ma_signal': signals.get('ma_signal'),
                                'trend_signal': signals.get('trend_signal'),
                                'volume_signal': signals.get('volume_signal')
                            })
                        
                        self.logger.debug(f"✅ 成功获取 {symbol} 技术指标: {len(technical_indicators)} 个")
                    else:
                        self.logger.warning(f"⚠️ {symbol} traditional_signals 中没有 technical_indicators")
                else:
                    self.logger.warning(f"⚠️ {symbol} 未获取到 market_analysis 或 traditional_signals")
            except Exception as e:
                self.logger.warning(f"❌ 获取详细技术指标失败 {symbol}: {e}")
            
            if hasattr(recommendation, 'reasoning') and recommendation.reasoning:
                # 从reasoning中提取技术指标信息
                reasoning_text = recommendation.reasoning
                if 'RSI' in reasoning_text:
                    key_factors.append("RSI技术指标")
                if 'MACD' in reasoning_text:
                    key_factors.append("MACD趋势指标")
                if 'MA' in reasoning_text or '均线' in reasoning_text:
                    key_factors.append("移动平均线")
                if '布林' in reasoning_text or 'Bollinger' in reasoning_text:
                    key_factors.append("布林带指标")
                if '成交量' in reasoning_text or 'volume' in reasoning_text:
                    key_factors.append("成交量分析")
                if '突破' in reasoning_text or 'breakout' in reasoning_text:
                    key_factors.append("价格突破")
        
        # 添加Kronos因素
        if kronos_result:
            key_factors.append("Kronos AI预测")
            if hasattr(kronos_result, 'key_factors'):
                key_factors.extend(kronos_result.key_factors)
        
        # 添加ML因素
        if ml_result:
            key_factors.append("机器学习预测")
        
        # 计算风险管理参数
        stop_loss_price, take_profit_price, position_size_usdt = self._calculate_risk_management_params(
            current_price, final_action, final_confidence
        )
        
        # 创建交易信号
        signal = TradingSignal(
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
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            position_size_usdt=position_size_usdt,
            leverage=self._calculate_leverage(final_confidence),
            reasoning=" | ".join(reasoning_parts),
            key_factors=key_factors,
            technical_indicators=technical_indicators,
            confidence_breakdown={
                'kronos': kronos_result.final_confidence if kronos_result else 0,
                'technical': technical_result.get('confidence', 0) if technical_result else 0,
                'ml': ml_result.get('confidence', 0) if ml_result else 0
            }
        )
        
        return signal

    def _enhanced_decision_logic(self, signals: List[str], confidences: List[float], 
                               kronos_result, dynamic_weights) -> Tuple[str, float]:
        """增强版决策逻辑 - 考虑动态权重和市场状态"""
        if not signals:
            return "HOLD", 0.5
        
        # 特殊处理：Kronos极高置信度时的决策优化
        kronos_confidence = kronos_result.final_confidence if kronos_result else 0
        kronos_action = kronos_result.final_action if kronos_result else "HOLD"
        
        # 根据市场状态调整Kronos权重阈值
        if dynamic_weights.market_regime.value == 'low_volatility':
            # 低波动期：降低Kronos主导阈值，因为AI权重已经提高
            high_confidence_threshold = 0.85
            extreme_confidence_threshold = 0.92
        elif dynamic_weights.market_regime.value in ['high_volatility', 'extreme_volatility']:
            # 高波动期：提高Kronos主导阈值，更依赖技术分析
            high_confidence_threshold = 0.88
            extreme_confidence_threshold = 0.95
        else:
            # 正常波动期：使用标准阈值
            high_confidence_threshold = 0.80
            extreme_confidence_threshold = 0.90
        
        # 当Kronos置信度>=极高阈值时，给予绝对优先权
        if kronos_confidence >= extreme_confidence_threshold:
            if "买入" in kronos_action or "BUY" in kronos_action.upper():
                final_action = "BUY"
                final_confidence = max(0.75, kronos_confidence * 0.9)
                self.logger.info(f"🔥 Kronos极高置信度({kronos_confidence:.2f})主导决策: {final_action}")
            elif "卖出" in kronos_action or "SELL" in kronos_action.upper():
                final_action = "SELL"
                final_confidence = max(0.75, kronos_confidence * 0.9)
                self.logger.info(f"🔥 Kronos极高置信度({kronos_confidence:.2f})主导决策: {final_action}")
            else:
                final_action, final_confidence = self._regular_decision_logic(signals, confidences)
        
        # 当Kronos置信度>=高阈值时，给予高权重
        elif kronos_confidence >= high_confidence_threshold:
            if "买入" in kronos_action or "BUY" in kronos_action.upper():
                final_action = "BUY"
                # 使用动态权重计算
                kronos_weight = dynamic_weights.kronos_weight * 1.4  # 高置信度时额外提升40%
                other_weight = 1 - kronos_weight
                final_confidence = (kronos_confidence * kronos_weight + 
                                  sum(confidences[1:]) * other_weight) if len(confidences) > 1 else kronos_confidence * 0.85
                self.logger.info(f"🎯 Kronos高置信度({kronos_confidence:.2f})主导决策: {final_action}")
            elif "卖出" in kronos_action or "SELL" in kronos_action.upper():
                final_action = "SELL"
                kronos_weight = dynamic_weights.kronos_weight * 1.4
                other_weight = 1 - kronos_weight
                final_confidence = (kronos_confidence * kronos_weight + 
                                  sum(confidences[1:]) * other_weight) if len(confidences) > 1 else kronos_confidence * 0.85
                self.logger.info(f"🎯 Kronos高置信度({kronos_confidence:.2f})主导决策: {final_action}")
            else:
                final_action, final_confidence = self._regular_decision_logic(signals, confidences)
        
        # 常规决策逻辑
        else:
            final_action, final_confidence = self._regular_decision_logic(signals, confidences)
        
        return final_action, final_confidence

    def _regular_decision_logic(self, signals: List[str], confidences: List[float]) -> Tuple[str, float]:
        """常规决策逻辑"""
        # 投票机制
        buy_votes = sum(1 for s in signals if s in ['BUY', 'LONG', '买入', '强烈买入'])
        sell_votes = sum(1 for s in signals if s in ['SELL', 'SHORT', '卖出', '强烈卖出'])
        
        if buy_votes > sell_votes:
            final_action = "BUY"
        elif sell_votes > buy_votes:
            final_action = "SELL"
        else:
            final_action = "HOLD"
        
        # 加权平均置信度
        final_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        
        return final_action, final_confidence
    
    def _determine_primary_action(self, signals: List[str]) -> str:
        """确定主要信号方向"""
        if not signals:
            return "HOLD"
        
        buy_count = sum(1 for s in signals if str(s).upper() in ['BUY', 'LONG', '买入', '强烈买入'])
        sell_count = sum(1 for s in signals if str(s).upper() in ['SELL', 'SHORT', '卖出', '强烈卖出'])
        
        if buy_count > sell_count:
            return "BUY"
        elif sell_count > buy_count:
            return "SELL"
        else:
            return "HOLD"
    
    def _extract_trend_direction(self, technical_result: Optional[Dict[str, Any]]) -> str:
        """从技术分析结果中提取趋势方向"""
        if not technical_result:
            return "neutral"
        
        action_enum = technical_result.get('action', 'HOLD')
        # 处理TradingAction枚举对象
        if hasattr(action_enum, 'value'):
            action = action_enum.value.upper()
        else:
            action = str(action_enum).upper()
            
        if action in ['BUY', 'LONG', '买入', '强烈买入']:
            return "up"
        elif action in ['SELL', 'SHORT', '卖出', '强烈卖出']:
            return "down"
        else:
            return "neutral"

    def _calculate_risk_management_params(self, current_price: float, action: str, confidence: float) -> Tuple[float, float, float]:
        """计算风险管理参数 - 日内短线优化"""
        if not current_price or current_price <= 0:
            return 0, 0, 100  # 默认值
        
        # 日内短线风险管理参数
        if action.upper() in ['BUY', 'LONG']:
            # 买入信号的止损止盈
            stop_loss_pct = 0.015 if confidence >= 0.7 else 0.02   # 1.5%-2% 止损
            take_profit_pct = 0.03 if confidence >= 0.7 else 0.025  # 2.5%-3% 止盈
            
            stop_loss_price = current_price * (1 - stop_loss_pct)
            take_profit_price = current_price * (1 + take_profit_pct)
            
        elif action.upper() in ['SELL', 'SHORT']:
            # 卖出信号的止损止盈
            stop_loss_pct = 0.015 if confidence >= 0.7 else 0.02
            take_profit_pct = 0.03 if confidence >= 0.7 else 0.025
            
            stop_loss_price = current_price * (1 + stop_loss_pct)
            take_profit_price = current_price * (1 - take_profit_pct)
            
        else:
            return 0, 0, 100
        
        # 根据置信度计算仓位大小
        if confidence >= 0.8:
            position_size_usdt = 200  # 高置信度
        elif confidence >= 0.6:
            position_size_usdt = 150  # 中等置信度
        elif confidence >= 0.4:
            position_size_usdt = 100  # 低置信度
        else:
            position_size_usdt = 50   # 极低置信度
        
        return stop_loss_price, take_profit_price, position_size_usdt
    
    def _calculate_leverage(self, confidence: float) -> float:
        """根据置信度计算建议杠杆 - 日内短线保守"""
        if confidence >= 0.8:
            return 3.0  # 高置信度最多3倍
        elif confidence >= 0.6:
            return 2.0  # 中等置信度2倍
        else:
            return 1.0  # 低置信度不加杠杆

    def _determine_signal_strength(self, confidence: float) -> SignalStrength:
        """根据置信度确定信号强度"""
        for strength, threshold in self.strength_thresholds.items():
            if confidence >= threshold:
                return strength
        return SignalStrength.VERY_WEAK

    async def send_trading_signal_notification(self, signal) -> bool:
        """发送交易信号通知"""
        try:
            if not self.notification_service:
                self.notification_service = await get_core_notification_service()
            
            # 构建通知内容
            from app.services.notification.core_notification_service import NotificationContent, NotificationType, NotificationPriority
            
            # 根据信号强度确定优先级 - 强信号使用高优先级
            priority_map = {
                'very_strong': NotificationPriority.URGENT,  # 提升到紧急
                'strong': NotificationPriority.HIGH,         # 提升到高优先级
                'moderate': NotificationPriority.NORMAL,
                'weak': NotificationPriority.LOW,
                'very_weak': NotificationPriority.LOW
            }
            
            strength_value = getattr(signal.signal_strength, 'value', 'moderate') if hasattr(signal, 'signal_strength') else 'moderate'
            priority = priority_map.get(strength_value, NotificationPriority.NORMAL)
            
            # 收集完整的信号数据
            metadata = {
                'symbol': getattr(signal, 'symbol', 'Unknown'),
                'action': getattr(signal, 'final_action', 'Unknown'),
                'confidence': getattr(signal, 'final_confidence', 0),
                'strength': strength_value,
                'current_price': getattr(signal, 'current_price', None) or getattr(signal, 'entry_price', None),
                'reasoning': getattr(signal, 'reasoning', ''),
                'key_factors': getattr(signal, 'key_factors', [])
            }
            
            # 添加风险管理信息
            if hasattr(signal, 'stop_loss_price'):
                metadata['stop_loss'] = signal.stop_loss_price
            if hasattr(signal, 'take_profit_price'):
                metadata['take_profit'] = signal.take_profit_price
            if hasattr(signal, 'target_price'):
                metadata['target_price'] = signal.target_price
            
            # 添加收益预期信息
            if hasattr(signal, 'expected_return'):
                metadata['expected_return'] = signal.expected_return
            if hasattr(signal, 'risk_reward_ratio'):
                metadata['risk_reward_ratio'] = signal.risk_reward_ratio
            if hasattr(signal, 'win_probability'):
                metadata['win_probability'] = signal.win_probability
            
            # 添加仓位建议
            if hasattr(signal, 'position_size_usdt'):
                metadata['position_size'] = signal.position_size_usdt
            if hasattr(signal, 'leverage'):
                metadata['leverage'] = signal.leverage
            
            # 添加技术分析数据
            technical_data = {}
            
            # 优先使用 technical_indicators
            if hasattr(signal, 'technical_indicators') and signal.technical_indicators:
                technical_data.update(signal.technical_indicators)
                self.logger.info(f"📊 传递技术指标数据: {len(signal.technical_indicators)} 个指标")
            
            # 补充其他技术分析数据
            if hasattr(signal, 'technical_analysis') and signal.technical_analysis:
                technical_data.update(signal.technical_analysis)
            
            if technical_data:
                metadata['technical_analysis'] = technical_data
                self.logger.info(f"✅ 最终技术分析数据: {list(technical_data.keys())}")
            else:
                self.logger.warning("⚠️ 没有技术分析数据传递到通知")
            if hasattr(signal, 'market_conditions'):
                metadata['market_conditions'] = signal.market_conditions
            
            # 添加分析置信度分解
            if hasattr(signal, 'confidence_breakdown') and signal.confidence_breakdown:
                # 置信度已经是0-1的小数，需要转换为百分比显示
                kronos_conf = signal.confidence_breakdown.get('kronos', 0)
                technical_conf = signal.confidence_breakdown.get('technical', 0)
                ml_conf = signal.confidence_breakdown.get('ml', 0)
                
                # 如果值已经是百分比形式（>1），直接使用；否则转换为百分比
                metadata['kronos_confidence'] = kronos_conf if kronos_conf > 1 else kronos_conf * 100
                metadata['technical_confidence'] = technical_conf if technical_conf > 1 else technical_conf * 100
                metadata['ml_confidence'] = ml_conf if ml_conf > 1 else ml_conf * 100
            
            # 构建标题
            symbol = metadata['symbol']
            action = metadata['action']
            strength_emoji = {
                'very_strong': '🔥🔥🔥',
                'strong': '🔥🔥',
                'moderate': '🔥'
            }.get(strength_value, '🚀')
            
            title = f"{strength_emoji} 强信号 - {symbol} {action}"
            
            content = NotificationContent(
                type=NotificationType.TRADING_SIGNAL,
                priority=priority,
                title=title,
                message="",  # 将在格式化函数中生成详细消息
                metadata=metadata
            )
            
            self.logger.info(f"发送强信号通知: {symbol} {action} (置信度: {metadata['confidence']:.2f})")
            
            result = await self.notification_service.send_notification(content)
            success = any(result.values()) if isinstance(result, dict) else bool(result)
            
            if success:
                self.logger.info(f"✅ 强信号通知发送成功: {symbol}")
            else:
                self.logger.warning(f"❌ 强信号通知发送失败: {symbol}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"发送交易信号通知失败: {e}")
            return False


# 全局服务实例
_core_trading_service = None


async def get_core_trading_service() -> CoreTradingService:
    """获取核心交易服务实例"""
    global _core_trading_service
    if _core_trading_service is None:
        _core_trading_service = CoreTradingService()
    return _core_trading_service