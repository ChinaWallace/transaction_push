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
        
        # 会话管理 - 整合自comprehensive_trading_service
        self.active_sessions: Dict[str, TradingSession] = {}
        self.portfolio_history: List[PortfolioSnapshot] = []
        
        # 配置参数
        self.max_concurrent_analyses = 10
        self.session_timeout_hours = 24
        self.portfolio_snapshot_interval = 3600  # 1小时
        
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
        """分析单个交易对
        
        Args:
            symbol: 交易对
            analysis_type: 分析类型
            force_update: 是否强制更新
            
        Returns:
            Optional[TradingSignal]: 交易信号
        """
        try:
            self.logger.debug(f"🔍 开始分析 {symbol}，类型: {analysis_type.value}")
            
            # 获取当前价格
            try:
                current_price = await self.okx_service.get_current_price(symbol)
                if current_price is None:
                    current_price = 0
            except Exception as e:
                self.logger.warning(f"⚠️ 获取 {symbol} 价格失败: {e}")
                current_price = 0
            
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
            
            # 综合分析结果
            signal = await self._synthesize_analysis_results(
                symbol=symbol,
                current_price=current_price,
                kronos_result=kronos_result,
                technical_result=technical_result,
                ml_result=ml_result,
                position_result=position_result,
                analysis_type=analysis_type
            )
            
            return signal
            
        except Exception as e:
            self.logger.error(f"❌ 分析 {symbol} 失败: {e}")
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
        
        # 综合决策
        if not signals:
            final_action = "HOLD"
            final_confidence = 0.5
        else:
            # 简单投票机制
            buy_votes = sum(1 for s in signals if s in ['BUY', 'LONG'])
            sell_votes = sum(1 for s in signals if s in ['SELL', 'SHORT'])
            
            if buy_votes > sell_votes:
                final_action = "BUY"
            elif sell_votes > buy_votes:
                final_action = "SELL"
            else:
                final_action = "HOLD"
            
            # 加权平均置信度
            final_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        
        # 确定信号强度
        signal_strength = self._determine_signal_strength(final_confidence)
        
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
            reasoning=" | ".join(reasoning_parts),
            confidence_breakdown={
                'kronos': kronos_result.final_confidence if kronos_result else 0,
                'technical': technical_result.get('confidence', 0) if technical_result else 0,
                'ml': ml_result.get('confidence', 0) if ml_result else 0
            }
        )
        
        return signal

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
            from app.services.core_notification_service import NotificationContent, NotificationType, NotificationPriority
            
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
            if hasattr(signal, 'technical_analysis'):
                metadata['technical_analysis'] = signal.technical_analysis
            if hasattr(signal, 'market_conditions'):
                metadata['market_conditions'] = signal.market_conditions
            
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