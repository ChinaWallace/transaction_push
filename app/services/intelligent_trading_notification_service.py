# -*- coding: utf-8 -*-
"""
智能交易通知服务
Intelligent Trading Notification Service - 只推送高质量交易机会
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import asyncio
import numpy as np

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.core.strong_signal_config import strong_signal_config, SignalUrgency
from app.services.okx_service import OKXService
from app.services.unified_trading_service import UnifiedTradingService
from app.services.trading_decision_service import TradingAction, RiskLevel
from app.services.trading_notification_service import TradingNotificationService
from app.services.notification_service import NotificationService
from app.services.kronos_prediction_service import get_kronos_service, KronosPrediction
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class OpportunityLevel(Enum):
    """机会等级"""
    PREMIUM = "premium"      # 顶级机会 - 必须推送
    HIGH = "high"           # 高质量机会
    MEDIUM = "medium"       # 中等机会
    LOW = "low"            # 低质量机会 - 不推送


@dataclass
class TradingOpportunity:
    """交易机会"""
    symbol: str
    level: OpportunityLevel
    action: TradingAction
    confidence: float
    
    # 交易参数
    position_size_usdt: float
    leverage: float
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    
    # 收益预期
    expected_profit_usdt: float
    risk_reward_ratio: float
    win_probability: float
    
    # ML增强信息
    ml_signal_strength: float
    market_anomalies: List[str]
    
    # 决策依据
    key_factors: List[str]
    reasoning: str
    
    # 时效性
    urgency: str  # "immediate", "within_1h", "within_4h", "today"
    valid_until: datetime
    
    timestamp: datetime


class IntelligentTradingNotificationService:
    """智能交易通知服务类"""
    
    def __init__(self):
        self.okx_service = OKXService()
        self.unified_service = UnifiedTradingService()
        self.trading_notification_service = TradingNotificationService()
        self.notification_service = None  # Will be initialized async
        self.kronos_service = None  # 延迟初始化
        
        # 机会筛选阈值 - 降低门槛，增加推送机会
        self.min_confidence = 60.0          # 最低置信度60%（降低15%）
        self.min_risk_reward = 1.5          # 最低风险收益比1.5:1（降低0.5）
        self.min_expected_profit = 30.0     # 最低预期盈利30 USDT（降低20）
        
        # 推送频率控制 - 移除所有冷却时间限制，实时推送
        self.last_notification_time = {}
        self.notification_intervals = {
            'premium': timedelta(seconds=0),    # 顶级机会无冷却，立即推送
            'high': timedelta(seconds=0),       # 高质量机会无冷却，立即推送
            'medium': timedelta(seconds=0),     # 中等机会无冷却，立即推送
            'low': timedelta(seconds=0)         # 低质量机会无冷却，立即推送
        }
        self.min_notification_interval = timedelta(seconds=0)  # 移除默认间隔限制
        
        # 移除每日限制 - 币圈机会不等人，全天候监控
        # 改用智能过滤：相同交易对的相同信号类型才限制
        self.signal_history = {}  # 记录信号历史，避免重复推送相同信号
    
    async def _ensure_notification_service(self):
        """确保通知服务已初始化"""
        if self.notification_service is None:
            from app.services.core_notification_service import get_core_notification_service
            self.notification_service = await get_core_notification_service()
    
    async def scan_and_notify_opportunities(self, 
                                          symbols: List[str] = None,
                                          force_scan: bool = False) -> Dict[str, Any]:
        """
        扫描并推送交易机会
        
        Args:
            symbols: 要扫描的交易对列表，None则使用默认列表
            force_scan: 是否强制扫描（忽略时间间隔限制）
            
        Returns:
            扫描结果统计
        """
        try:
            if symbols is None:
                symbols = await self._get_active_symbols()
            
            logger.info(f"开始扫描 {len(symbols)} 个交易对的机会")
            
            # 并行分析所有交易对
            opportunities = await self._analyze_opportunities(symbols)
            
            # 筛选高质量机会
            premium_opportunities = [op for op in opportunities if op.level == OpportunityLevel.PREMIUM]
            high_opportunities = [op for op in opportunities if op.level == OpportunityLevel.HIGH]
            medium_opportunities = [op for op in opportunities if op.level == OpportunityLevel.MEDIUM]
            
            # 推送通知（包含中等级别机会）
            notification_results = await self._send_opportunity_notifications(
                premium_opportunities, high_opportunities, medium_opportunities, force_scan
            )
            
            # 记录统计
            stats = {
                'scan_time': datetime.now(),
                'total_scanned': len(symbols),
                'total_opportunities': len(opportunities),
                'premium_opportunities': len(premium_opportunities),
                'high_opportunities': len(high_opportunities),
                'notifications_sent': notification_results.get('sent_count', 0),
                'top_opportunities': [self._format_opportunity_summary(op) for op in premium_opportunities[:3]]
            }
            
            trading_logger.info(f"机会扫描完成: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"扫描交易机会失败: {e}")
            raise TradingToolError(f"机会扫描失败: {e}")
    
    async def _get_active_symbols(self) -> List[str]:
        """获取活跃交易对列表"""
        # 主流币种的永续合约
        return [
            "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP",
            "DOGE-USDT-SWAP", "XRP-USDT-SWAP", "ADA-USDT-SWAP",
            "AVAX-USDT-SWAP", "DOT-USDT-SWAP", "LINK-USDT-SWAP",
            "UNI-USDT-SWAP", "LTC-USDT-SWAP", "BCH-USDT-SWAP"
        ]
    
    async def _analyze_opportunities(self, symbols: List[str]) -> List[TradingOpportunity]:
        """分析交易机会"""
        opportunities = []
        
        # 并行分析
        tasks = [self._analyze_single_opportunity(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"分析 {symbols[i]} 失败: {result}")
                continue
            
            if result:
                opportunities.append(result)
        
        return opportunities
    
    async def _analyze_single_opportunity(self, symbol: str) -> Optional[TradingOpportunity]:
        """分析单个交易对的机会 - 优化Kronos集成"""
        try:
            # 优先获取Kronos预测 - 作为核心决策依据
            kronos_prediction = None
            market_anomalies = []
            
            try:
                if self.kronos_service is None:
                    self.kronos_service = await get_kronos_service()
                
                # 获取Kronos预测 - 使用更稳定的方法
                if self.kronos_service is None:
                    # 延迟初始化Kronos服务
                    try:
                        self.kronos_service = await get_kronos_service()
                    except Exception as e:
                        logger.warning(f"初始化Kronos服务失败: {e}")
                        self.kronos_service = None
                
                if self.kronos_service:
                    # 先尝试从缓存获取
                    kronos_prediction = self.kronos_service.get_cached_prediction(symbol)
                    
                    # 如果缓存没有，则生成新预测
                    if not kronos_prediction:
                        # 获取历史数据用于Kronos预测
                        from app.services.okx_service import OKXService
                        okx_service = OKXService()
                        kline_data = await okx_service.get_kline_data(symbol, '1h', 100)
                        
                        if kline_data and len(kline_data) >= 50:
                            import pandas as pd
                            historical_df = pd.DataFrame(kline_data)
                            kronos_prediction = await self.kronos_service.get_prediction(symbol, historical_df)
                    
                    # 基于Kronos预测检测市场异常
                    if kronos_prediction:
                        market_anomalies = self._detect_market_anomalies(kronos_prediction)
                        logger.info(f"✅ {symbol} Kronos预测成功: 信号={kronos_prediction.signal}, 置信度={kronos_prediction.confidence:.2f}")
                    
            except Exception as e:
                logger.warning(f"Kronos预测失败 {symbol}: {e}")
                kronos_prediction = None
            
            # 获取传统交易建议 - 作为辅助参考
            recommendation = await self.unified_service.get_trading_recommendation(symbol)
            
            # 评估机会质量
            opportunity_level = self._evaluate_opportunity_level(
                recommendation, kronos_prediction, market_anomalies
            )
            
            # 只返回中等以上的机会
            if opportunity_level == OpportunityLevel.LOW:
                return None
            
            # 计算胜率
            win_probability = self._calculate_win_probability(
                recommendation, kronos_prediction
            )
            
            # 提取关键因素
            key_factors = self._extract_key_factors(
                recommendation, kronos_prediction, market_anomalies
            )
            
            # 确定紧急程度
            urgency, valid_until = self._determine_urgency(
                recommendation, kronos_prediction
            )
            
            return TradingOpportunity(
                symbol=symbol,
                level=opportunity_level,
                action=recommendation.action,
                confidence=recommendation.confidence,
                
                position_size_usdt=recommendation.position_size_usdt,
                leverage=recommendation.leverage,
                entry_price=recommendation.entry_price,
                stop_loss_price=recommendation.stop_loss_price,
                take_profit_price=recommendation.take_profit_price,
                
                expected_profit_usdt=recommendation.expected_profit_usdt,
                risk_reward_ratio=recommendation.risk_reward_ratio,
                win_probability=win_probability,
                
                ml_signal_strength=kronos_prediction.confidence if kronos_prediction else 0.0,
                market_anomalies=market_anomalies,
                
                key_factors=key_factors,
                reasoning=recommendation.reasoning,
                
                urgency=urgency,
                valid_until=valid_until,
                
                timestamp=datetime.now()
            )
            
        except Exception as e:
            logger.warning(f"分析 {symbol} 机会失败: {e}")
            return None
    
    def _detect_market_anomalies(self, kronos_prediction: KronosPrediction) -> List[str]:
        """基于Kronos预测检测市场异常"""
        anomalies = []
        
        try:
            # 检测价格异常变化
            if abs(kronos_prediction.price_change_pct) > 0.1:  # 10%以上变化
                anomalies.append(f"预测价格大幅变化: {kronos_prediction.price_change_pct:.1%}")
            
            # 检测高波动率
            if kronos_prediction.volatility > 0.05:  # 5%以上波动率
                anomalies.append(f"高波动率预警: {kronos_prediction.volatility:.1%}")
            
            # 检测强信号
            if kronos_prediction.signal in ['strong_buy', 'strong_sell']:
                anomalies.append(f"Kronos强信号: {kronos_prediction.signal}")
            
            # 检测高置信度预测
            if kronos_prediction.confidence > 0.8:
                anomalies.append(f"高置信度预测: {kronos_prediction.confidence:.1%}")
                
        except Exception as e:
            logger.warning(f"检测市场异常失败: {e}")
        
        return anomalies
    
    def _evaluate_opportunity_level(self, 
                                  recommendation, 
                                  kronos_prediction, 
                                  anomalies: List[str]) -> OpportunityLevel:
        """评估机会等级 - 优化Kronos权重"""
        score = 0
        symbol = getattr(recommendation, 'symbol', 'UNKNOWN')
        
        logger.info(f"🔍 评估机会等级 {symbol}:")
        logger.info(f"  - 传统分析置信度: {recommendation.confidence}%")
        logger.info(f"  - 风险收益比: {recommendation.risk_reward_ratio}")
        if kronos_prediction:
            logger.info(f"  - Kronos置信度: {kronos_prediction.confidence:.2f}")
            logger.info(f"  - Kronos信号: {kronos_prediction.signal}")
            logger.info(f"  - 预测价格变化: {kronos_prediction.price_change_pct:.2%}")
        else:
            logger.info(f"  - Kronos预测: 无")
        
        # Kronos预测权重提升到50分 (核心决策依据)
        if kronos_prediction:
            kronos_confidence = kronos_prediction.confidence
            kronos_signal = kronos_prediction.signal
            price_change = abs(kronos_prediction.price_change_pct)
            
            # Kronos置信度评分 (30分)
            if kronos_confidence >= 0.8:
                score += 30
            elif kronos_confidence >= 0.7:
                score += 25
            elif kronos_confidence >= 0.6:
                score += 20
            elif kronos_confidence >= 0.5:
                score += 15
            else:
                score += 5
            
            # Kronos信号强度评分 (20分)
            if kronos_signal in ['strong_buy', 'strong_sell']:
                score += 20
            elif kronos_signal in ['buy', 'sell']:
                score += 15
            elif price_change >= 0.05:  # 预测5%以上变化
                score += 10
            elif price_change >= 0.03:  # 预测3%以上变化
                score += 5
        else:
            # 没有Kronos预测时，轻微扣分（允许基于传统分析推送）
            score -= 5
        
        # 传统信号强度 (25分，权重降低)
        if recommendation.confidence > 85:
            score += 25
        elif recommendation.confidence > 75:
            score += 20
        elif recommendation.confidence > 65:
            score += 15
        else:
            score += 8
        
        # 风险收益比 (15分，权重降低)
        if recommendation.risk_reward_ratio > 4:
            score += 15
        elif recommendation.risk_reward_ratio > 3:
            score += 12
        elif recommendation.risk_reward_ratio > 2:
            score += 8
        else:
            score += 3
        
        # Kronos与传统信号一致性加分 (10分)
        if kronos_prediction:
            if ((recommendation.action.value in ['buy', 'strong_buy'] and 
                 kronos_prediction.signal in ['buy', 'strong_buy']) or
                (recommendation.action.value in ['sell', 'strong_sell'] and 
                 kronos_prediction.signal in ['sell', 'strong_sell'])):
                score += 10  # 信号一致性加分
            elif ((recommendation.action.value in ['buy', 'strong_buy'] and 
                   kronos_prediction.signal in ['sell', 'strong_sell']) or
                  (recommendation.action.value in ['sell', 'strong_sell'] and 
                   kronos_prediction.signal in ['buy', 'strong_buy'])):
                score -= 15  # 信号冲突扣分
        
        # 市场异常加分 (基于Kronos检测)
        if len(anomalies) > 0:
            score += min(15, len(anomalies) * 4)  # 提高异常检测权重
        
        # 风险等级调整 (10分，权重降低)
        if recommendation.risk_level in [RiskLevel.LOW, RiskLevel.VERY_LOW]:
            score += 10
        elif recommendation.risk_level == RiskLevel.MEDIUM:
            score += 5
        else:
            score -= 5  # 高风险扣分
        
        # 等级判定 - 降低阈值，更容易触发通知
        level = None
        if score >= 60:
            level = OpportunityLevel.PREMIUM
        elif score >= 40:
            level = OpportunityLevel.HIGH
        elif score >= 15:  # 大幅降低medium阈值
            level = OpportunityLevel.MEDIUM
        else:
            level = OpportunityLevel.LOW
        
        logger.info(f"  - 总评分: {score} -> 等级: {level.value}")
        return level
    
    def _calculate_win_probability(self, recommendation, kronos_prediction) -> float:
        """计算胜率"""
        base_probability = 0.5
        
        # 基于置信度调整
        confidence_factor = recommendation.confidence / 100.0
        base_probability += (confidence_factor - 0.5) * 0.4
        
        # Kronos预测调整
        if kronos_prediction and kronos_prediction.confidence > 0.7:
            base_probability += 0.1
            
            # 趋势方向一致性加分
            if ((recommendation.action.value in ['buy', 'strong_buy'] and 
                 kronos_prediction.trend_direction == 'bullish') or
                (recommendation.action.value in ['sell', 'strong_sell'] and 
                 kronos_prediction.trend_direction == 'bearish')):
                base_probability += 0.05
        
        # 风险收益比调整
        if recommendation.risk_reward_ratio > 3:
            base_probability += 0.05
        
        return min(0.95, max(0.3, base_probability))
    
    def _extract_key_factors(self, recommendation, kronos_prediction, anomalies) -> List[str]:
        """提取关键决策因素 - 优先展示Kronos预测"""
        factors = []
        
        # 优先展示Kronos预测结果
        if kronos_prediction:
            # Kronos核心预测信息
            factors.append(f"🤖 Kronos: {kronos_prediction.signal} (置信度{kronos_prediction.confidence:.1%})")
            
            # 价格变化预测 - 降低阈值以显示更多信息
            if abs(kronos_prediction.price_change_pct) > 0.01:  # 1%以上变化就显示
                direction = "📈上涨" if kronos_prediction.price_change_pct > 0 else "📉下跌"
                factors.append(f"{direction}: {abs(kronos_prediction.price_change_pct):.1%}")
            
            # 趋势方向
            if kronos_prediction.trend_direction != 'sideways':
                trend_emoji = "🚀" if kronos_prediction.trend_direction == 'bullish' else "🔻"
                trend_text = "看涨趋势" if kronos_prediction.trend_direction == 'bullish' else "看跌趋势"
                factors.append(f"{trend_emoji} {trend_text}")
            
            # 波动率预警
            if hasattr(kronos_prediction, 'volatility') and kronos_prediction.volatility > 0.05:
                factors.append(f"⚠️ 高波动率: {kronos_prediction.volatility:.1%}")
        else:
            # 没有Kronos预测时的提示
            factors.append("❌ Kronos预测不可用")
        
        # 传统分析作为补充 - 权重降低
        if recommendation and recommendation.reasoning:
            reasoning_parts = recommendation.reasoning.split('|')
            # 只取最重要的1-2个传统因素
            for part in reasoning_parts[:2]:
                clean_part = part.strip()
                if clean_part and len(factors) < 4:  # 为Kronos预留更多空间
                    factors.append(f"📊 {clean_part}")
        
        # 市场异常情况 - 基于Kronos检测
        if anomalies:
            if len(anomalies) == 1:
                factors.append(f"🔍 {anomalies[0]}")
            else:
                factors.append(f"🔍 检测到{len(anomalies)}项异常")
        
        return factors[:5]  # 最多5个关键因素，确保Kronos信息优先显示
    
    def _determine_urgency(self, recommendation, kronos_prediction) -> Tuple[str, datetime]:
        """确定紧急程度和有效期"""
        now = datetime.now()
        
        # 强信号立即执行
        if (recommendation.confidence > 85 and 
            recommendation.action in [TradingAction.STRONG_BUY, TradingAction.STRONG_SELL]):
            return "immediate", now + timedelta(minutes=30)
        
        # Kronos强信号也立即执行
        if (kronos_prediction and 
            kronos_prediction.signal in ['strong_buy', 'strong_sell'] and
            kronos_prediction.confidence > 0.8):
            return "immediate", now + timedelta(minutes=30)
        
        # 高置信度1小时内
        elif recommendation.confidence > 75:
            return "within_1h", now + timedelta(hours=2)
        
        # 中等信号4小时内
        elif recommendation.confidence > 65:
            return "within_4h", now + timedelta(hours=6)
        
        # 其他当日有效
        else:
            return "today", now + timedelta(hours=12)
    
    async def _send_opportunity_notifications(self, 
                                           premium_ops: List[TradingOpportunity],
                                           high_ops: List[TradingOpportunity],
                                           medium_ops: List[TradingOpportunity] = None,
                                           force_send: bool = False) -> Dict[str, Any]:
        """发送机会通知"""
        sent_count = 0
        
        # 确保通知服务已初始化
        await self._ensure_notification_service()
        
        # 顶级机会 - 必须推送
        for op in premium_ops:
            if self._should_send_notification(op, force_send):
                message = self._format_premium_opportunity_message(op)
                
                # 创建NotificationContent对象
                from app.services.core_notification_service import NotificationContent, NotificationType, NotificationPriority
                notification_content = NotificationContent(
                    type=NotificationType.TRADING_SIGNAL,
                    priority=NotificationPriority.HIGH,
                    title=f"🎯 顶级交易机会 - {op.symbol}",
                    message=message,
                    metadata={
                        'symbol': op.symbol,
                        'action': op.action.value,
                        'confidence': float(op.confidence),
                        'expected_profit': float(op.expected_profit_usdt),
                        'urgency': op.urgency
                    }
                )
                
                await self.notification_service.send_notification(notification_content)
                self.last_notification_time[op.symbol] = datetime.now()
                self._update_signal_history(op)
                sent_count += 1
        
        # 高质量机会 - 有限制推送
        high_ops_to_send = []
        for op in high_ops:
            if self._should_send_notification(op, force_send):
                high_ops_to_send.append(op)
        
        # 批量推送高质量机会（最多3个）
        if high_ops_to_send:
            message = self._format_batch_opportunities_message(high_ops_to_send[:3])
            
            # 创建NotificationContent对象
            from app.services.core_notification_service import NotificationContent, NotificationType, NotificationPriority
            notification_content = NotificationContent(
                type=NotificationType.TRADING_SIGNAL,
                priority=NotificationPriority.NORMAL,
                title=f"📊 高质量交易机会 ({len(high_ops_to_send[:3])}个)",
                message=message,
                metadata={
                    'batch_size': len(high_ops_to_send[:3]),
                    'symbols': [op.symbol for op in high_ops_to_send[:3]]
                }
            )
            
            await self.notification_service.send_notification(notification_content)
            for op in high_ops_to_send[:3]:
                self.last_notification_time[op.symbol] = datetime.now()
                self._update_signal_history(op)
            sent_count += len(high_ops_to_send[:3])
        
        # 中等质量机会 - 有限制推送
        if medium_ops:
            medium_ops_to_send = []
            for op in medium_ops:
                if self._should_send_notification(op, force_send):
                    medium_ops_to_send.append(op)
            
            # 批量推送中等机会（最多2个，避免过多通知）
            if medium_ops_to_send:
                message = self._format_batch_opportunities_message(medium_ops_to_send[:2], "中等质量")
                
                # 创建NotificationContent对象
                from app.services.core_notification_service import NotificationContent, NotificationType, NotificationPriority
                notification_content = NotificationContent(
                    type=NotificationType.TRADING_SIGNAL,
                    priority=NotificationPriority.LOW,
                    title=f"📊 中等质量交易机会 ({len(medium_ops_to_send[:2])}个)",
                    message=message,
                    metadata={
                        'batch_size': len(medium_ops_to_send[:2]),
                        'symbols': [op.symbol for op in medium_ops_to_send[:2]]
                    }
                )
                
                await self.notification_service.send_notification(notification_content)
                for op in medium_ops_to_send[:2]:
                    self.last_notification_time[op.symbol] = datetime.now()
                    self._update_signal_history(op)
                sent_count += len(medium_ops_to_send[:2])
        
        return {'sent_count': sent_count}
    
    def _should_send_notification(self, opportunity: TradingOpportunity, force_send: bool) -> bool:
        """判断是否应该发送通知 - 币圈优化版：快速响应，智能去重"""
        logger.info(f"🔔 检查是否推送通知 {opportunity.symbol}:")
        logger.info(f"  - 等级: {opportunity.level.value}")
        logger.info(f"  - 操作: {opportunity.action.value}")
        logger.info(f"  - 置信度: {opportunity.confidence}%")
        logger.info(f"  - 强制推送: {force_send}")
        
        if force_send:
            logger.info(f"  ✅ 强制推送模式，直接发送")
            return True
        
        level_key = opportunity.level.value.lower()
        current_time = datetime.now()
        
        # 智能去重：检查是否是相同交易对的相同信号类型
        signal_key = f"{opportunity.symbol}_{opportunity.action.value}_{level_key}"
        last_signal_time = self.signal_history.get(signal_key)
        
        # 相同信号的最小间隔（移除所有冷却限制）
        same_signal_interval = {
            'premium': timedelta(seconds=0),    # 相同顶级信号无冷却
            'high': timedelta(seconds=0),       # 相同高质量信号无冷却
            'medium': timedelta(seconds=0),     # 相同中等信号无冷却
            'low': timedelta(seconds=0)         # 相同低质量信号无冷却
        }
        
        # 移除相同信号的时间限制检查 - 允许所有信号立即推送
        # if last_signal_time:
        #     required_same_signal_interval = same_signal_interval.get(level_key, timedelta(hours=1))
        #     if current_time - last_signal_time < required_same_signal_interval:
        #         # 除非置信度显著提升（+10%以上）
        #         if opportunity.confidence > getattr(self, f'last_{signal_key}_confidence', 0) + 10:
        #             logger.info(f"{opportunity.symbol} 置信度显著提升，允许重新推送")
        #         else:
        #             return False
        
        # 移除不同交易对的时间间隔检查 - 允许所有机会立即推送
        # required_interval = self.notification_intervals.get(level_key, self.min_notification_interval)
        # last_time = self.last_notification_time.get(opportunity.symbol)
        # 
        # if last_time and current_time - last_time < required_interval:
        #     # 顶级机会的特殊处理
        #     if opportunity.level == OpportunityLevel.PREMIUM:
        #         # 如果是不同方向的信号（如从买入变卖出），立即推送
        #         last_action = getattr(self, f'last_{opportunity.symbol}_action', None)
        #         if (last_action and 
        #             ((last_action in ['buy', 'strong_buy'] and opportunity.action.value in ['sell', 'strong_sell']) or
        #              (last_action in ['sell', 'strong_sell'] and opportunity.action.value in ['buy', 'strong_buy']))):
        #             logger.info(f"{opportunity.symbol} 信号方向反转，立即推送")
        #             return True
        #         
        #         # 极高置信度（90%+）可以忽略时间限制
        #         if opportunity.confidence > 90:
        #             logger.info(f"顶级机会 {opportunity.symbol} 极高置信度 {opportunity.confidence}%，忽略时间限制")
        #             return True
        #     return False
        
        # 质量检查 - 大幅降低门槛，确保更多信号能够推送
        result = False
        reason = ""
        
        if opportunity.level == OpportunityLevel.PREMIUM:
            # 顶级机会：降低门槛，优先推送
            has_kronos_support = (hasattr(opportunity, 'ml_signal_strength') and 
                                opportunity.ml_signal_strength > 0.6)  # 降低Kronos阈值
            result = opportunity.confidence > 65 or has_kronos_support  # 大幅降低置信度要求
            reason = f"顶级机会: 置信度{opportunity.confidence}% > 65% 或 Kronos支持{has_kronos_support}"
        
        elif opportunity.level == OpportunityLevel.HIGH:
            # 高质量机会：大幅降低门槛
            conf_ok = opportunity.confidence > (self.min_confidence - 15)  # 60%
            risk_ok = opportunity.risk_reward_ratio > (self.min_risk_reward - 1.0)  # 1:1
            profit_ok = opportunity.expected_profit_usdt > (self.min_expected_profit - 30)  # 20 USDT
            result = conf_ok and risk_ok and profit_ok
            reason = f"高质量机会: 置信度{conf_ok}({opportunity.confidence}%>60%), 风险比{risk_ok}({opportunity.risk_reward_ratio:.1f}>1.0), 收益{profit_ok}({opportunity.expected_profit_usdt:.0f}>20)"
        
        elif opportunity.level == OpportunityLevel.MEDIUM:
            # 中等机会：降低门槛，增加推送机会
            conf_ok = opportunity.confidence > (self.min_confidence - 20)  # 55%
            risk_ok = opportunity.risk_reward_ratio > (self.min_risk_reward - 1.5)  # 0.5:1
            result = conf_ok and risk_ok
            reason = f"中等机会: 置信度{conf_ok}({opportunity.confidence}%>55%), 风险比{risk_ok}({opportunity.risk_reward_ratio:.1f}>0.5)"
        
        else:
            # 低质量机会：进一步降低门槛
            result = opportunity.confidence > (self.min_confidence - 25)  # 50%
            reason = f"低质量机会: 置信度{opportunity.confidence}% > 50%"
        
        logger.info(f"  - 质量检查: {reason}")
        logger.info(f"  {'✅ 通过' if result else '❌ 未通过'} 质量检查")
        
        return result
    
    def _format_premium_opportunity_message(self, op: TradingOpportunity) -> str:
        """格式化顶级机会消息"""
        action_emoji = "🚀" if op.action.value in ['buy', 'strong_buy'] else "📉"
        urgency_emoji = "⚡" if op.urgency == "immediate" else "⏰"
        
        message = f"""🎯 【顶级交易机会】{action_emoji}

{urgency_emoji} 紧急程度: {self._get_urgency_text(op.urgency)}
💎 交易对: {op.symbol}
📊 操作: {self._get_action_text(op.action)} 
🎯 置信度: {op.confidence:.1f}%
💰 预期收益: {op.expected_profit_usdt:.0f} USDT
📈 风险收益比: 1:{op.risk_reward_ratio:.1f}
🎲 胜率: {op.win_probability:.1%}

💡 建议参数:
• 仓位: {op.position_size_usdt:.0f} USDT ({op.leverage:.1f}x杠杆)
• 入场: {op.entry_price:.4f}
• 止损: {op.stop_loss_price:.4f}
• 止盈: {op.take_profit_price:.4f}

🔍 关键因素:
{chr(10).join(f"• {factor}" for factor in op.key_factors[:3])}

⏳ 有效期至: {op.valid_until.strftime('%H:%M')}"""

        return message
    
    def _format_batch_opportunities_message(self, opportunities: List[TradingOpportunity], level_name: str = "高质量") -> str:
        """格式化批量机会消息"""
        message = f"""📊 【{level_name}交易机会】

⏰ 扫描时间: {datetime.now().strftime('%H:%M')}
🎯 发现 {len(opportunities)} 个优质机会:

"""
        
        for i, op in enumerate(opportunities, 1):
            action_text = "做多" if op.action.value in ['buy', 'strong_buy'] else "做空"
            message += f"""{i}. {op.symbol} - {action_text}
   置信度: {op.confidence:.1f}% | 收益: {op.expected_profit_usdt:.0f}U | 胜率: {op.win_probability:.0%}
   入场: {op.entry_price:.4f} | 止损: {op.stop_loss_price:.4f}

"""
        
        message += "💡 详细建议请查看具体分析接口"
        return message
    
    def _format_opportunity_summary(self, op: TradingOpportunity) -> Dict[str, Any]:
        """格式化机会摘要"""
        return {
            'symbol': op.symbol,
            'action': op.action.value,
            'confidence': op.confidence,
            'expected_profit': op.expected_profit_usdt,
            'risk_reward_ratio': op.risk_reward_ratio,
            'win_probability': op.win_probability,
            'urgency': op.urgency,
            'key_factor': op.key_factors[0] if op.key_factors else ""
        }
    
    def _get_action_text(self, action: TradingAction) -> str:
        """获取操作文本"""
        action_map = {
            TradingAction.STRONG_BUY: "强烈做多",
            TradingAction.BUY: "做多",
            TradingAction.STRONG_SELL: "强烈做空", 
            TradingAction.SELL: "做空",
            TradingAction.HOLD: "持有",
            TradingAction.WAIT: "等待"
        }
        return action_map.get(action, action.value)
    
    def _get_urgency_text(self, urgency: str) -> str:
        """获取紧急程度文本"""
        urgency_map = {
            "immediate": "立即执行",
            "within_1h": "1小时内",
            "within_4h": "4小时内", 
            "today": "今日内"
        }
        return urgency_map.get(urgency, urgency)
    
    def _update_signal_history(self, opportunity: TradingOpportunity):
        """更新信号历史记录"""
        try:
            level_key = opportunity.level.value.lower()
            signal_key = f"{opportunity.symbol}_{opportunity.action.value}_{level_key}"
            current_time = datetime.now()
            
            # 更新信号历史
            self.signal_history[signal_key] = current_time
            
            # 记录置信度用于后续比较
            setattr(self, f'last_{signal_key}_confidence', opportunity.confidence)
            
            # 记录操作类型用于方向反转检测
            setattr(self, f'last_{opportunity.symbol}_action', opportunity.action.value)
            
            # 清理过期的历史记录（保留24小时内的记录）
            cutoff_time = current_time - timedelta(hours=24)
            expired_keys = [
                key for key, timestamp in self.signal_history.items() 
                if timestamp < cutoff_time
            ]
            for key in expired_keys:
                del self.signal_history[key]
            
            logger.debug(f"📝 更新信号历史: {signal_key} -> {current_time}")
            
        except Exception as e:
            logger.error(f"❌ 更新信号历史失败: {e}")
    
    async def get_current_opportunities(self) -> List[Dict[str, Any]]:
        """获取当前有效的交易机会"""
        try:
            symbols = await self._get_active_symbols()
            opportunities = await self._analyze_opportunities(symbols)
            
            # 只返回中等以上的机会
            valid_opportunities = [
                op for op in opportunities 
                if op.level in [OpportunityLevel.PREMIUM, OpportunityLevel.HIGH, OpportunityLevel.MEDIUM]
                and op.valid_until > datetime.now()
            ]
            
            # 按等级和置信度排序
            valid_opportunities.sort(
                key=lambda x: (x.level.value, x.confidence), 
                reverse=True
            )
            
            return [self._format_opportunity_summary(op) for op in valid_opportunities]
            
        except Exception as e:
            logger.error(f"获取当前机会失败: {e}")
            return []
    
    async def debug_signal_analysis(self, symbols: List[str] = None) -> Dict[str, Any]:
        """调试信号分析 - 帮助诊断为什么没有推送交易信号"""
        try:
            if symbols is None:
                symbols = await self._get_active_symbols()
            
            logger.info(f"🔍 开始调试信号分析，检查 {len(symbols)} 个交易对")
            
            debug_results = {
                'timestamp': datetime.now().isoformat(),
                'total_symbols': len(symbols),
                'analysis_results': [],
                'summary': {
                    'total_opportunities': 0,
                    'by_level': {'premium': 0, 'high': 0, 'medium': 0, 'low': 0},
                    'notification_eligible': 0,
                    'notification_blocked_reasons': {}
                }
            }
            
            # 分析每个交易对
            for symbol in symbols[:5]:  # 限制为前5个，避免过多日志
                try:
                    logger.info(f"🔍 调试分析 {symbol}...")
                    
                    # 获取交易建议
                    recommendation = await self.unified_service.get_trading_recommendation(symbol)
                    
                    # 获取Kronos预测
                    kronos_prediction = None
                    try:
                        if self.kronos_service is None:
                            self.kronos_service = await get_kronos_service()
                        if self.kronos_service:
                            kronos_prediction = await self.kronos_service.get_prediction(symbol, None)
                    except Exception as e:
                        logger.warning(f"Kronos预测失败 {symbol}: {e}")
                    
                    # 评估机会等级
                    market_anomalies = self._detect_market_anomalies(kronos_prediction) if kronos_prediction else []
                    opportunity_level = self._evaluate_opportunity_level(
                        recommendation, kronos_prediction, market_anomalies
                    )
                    
                    # 创建机会对象用于测试
                    test_opportunity = TradingOpportunity(
                        symbol=symbol,
                        level=opportunity_level,
                        action=recommendation.action,
                        confidence=recommendation.confidence,
                        position_size_usdt=recommendation.position_size_usdt,
                        leverage=recommendation.leverage,
                        entry_price=recommendation.entry_price,
                        stop_loss_price=recommendation.stop_loss_price,
                        take_profit_price=recommendation.take_profit_price,
                        expected_profit_usdt=recommendation.expected_profit_usdt,
                        risk_reward_ratio=recommendation.risk_reward_ratio,
                        win_probability=0.6,
                        ml_signal_strength=kronos_prediction.confidence if kronos_prediction else 0.0,
                        market_anomalies=market_anomalies,
                        key_factors=[],
                        reasoning=recommendation.reasoning,
                        urgency="normal",
                        valid_until=datetime.now() + timedelta(hours=4),
                        timestamp=datetime.now()
                    )
                    
                    # 检查是否应该推送通知
                    should_notify = self._should_send_notification(test_opportunity, force_send=False)
                    
                    # 记录分析结果
                    analysis_result = {
                        'symbol': symbol,
                        'confidence': recommendation.confidence,
                        'action': recommendation.action.value,
                        'level': opportunity_level.value,
                        'risk_reward_ratio': recommendation.risk_reward_ratio,
                        'expected_profit': recommendation.expected_profit_usdt,
                        'kronos_available': kronos_prediction is not None,
                        'kronos_confidence': kronos_prediction.confidence if kronos_prediction else 0,
                        'should_notify': should_notify,
                        'anomalies_count': len(market_anomalies)
                    }
                    
                    debug_results['analysis_results'].append(analysis_result)
                    debug_results['summary']['total_opportunities'] += 1
                    debug_results['summary']['by_level'][opportunity_level.value] += 1
                    
                    if should_notify:
                        debug_results['summary']['notification_eligible'] += 1
                    
                    logger.info(f"  📊 {symbol}: {opportunity_level.value} 级别, 置信度 {recommendation.confidence}%, {'✅会推送' if should_notify else '❌不推送'}")
                    
                except Exception as e:
                    logger.error(f"调试分析 {symbol} 失败: {e}")
                    continue
            
            # 记录汇总信息
            logger.info(f"🔍 调试分析完成:")
            logger.info(f"  📊 总机会: {debug_results['summary']['total_opportunities']}")
            logger.info(f"  🎯 各等级: {debug_results['summary']['by_level']}")
            logger.info(f"  📢 可推送: {debug_results['summary']['notification_eligible']}")
            
            return debug_results
            
        except Exception as e:
            logger.error(f"调试信号分析失败: {e}")
            return {'error': str(e), 'timestamp': datetime.now().isoformat()}   
    def _detect_strong_signal(self, opportunity: TradingOpportunity, market_data: Dict[str, Any]) -> SignalUrgency:
        """
        检测强信号并确定紧急程度
        
        Args:
            opportunity: 交易机会
            market_data: 市场数据
            
        Returns:
            SignalUrgency: 信号紧急程度
        """
        try:
            # 提取关键指标
            confidence = opportunity.confidence / 100.0  # 转换为0-1范围
            volume_ratio = market_data.get('volume_ratio', 1.0)
            price_change = market_data.get('price_change_24h', 0.0)
            funding_rate = market_data.get('funding_rate', 0.0)
            
            # 检查多周期一致性
            supertrend_signals = market_data.get('supertrend_signals', {})
            all_timeframes_aligned = self._check_timeframe_alignment(supertrend_signals)
            
            # 构建信号类型
            signal_type = self._build_signal_type(opportunity, market_data)
            
            # 使用强信号配置判断紧急程度
            urgency = strong_signal_config.get_signal_urgency(
                signal_type=signal_type,
                confidence=confidence,
                all_timeframes_aligned=all_timeframes_aligned,
                volume_ratio=volume_ratio,
                price_change_abs=abs(price_change),
                funding_rate=funding_rate
            )
            
            logger.info(f"强信号检测 {opportunity.symbol}: {signal_type} -> {urgency.value}")
            return urgency
            
        except Exception as e:
            logger.error(f"强信号检测失败 {opportunity.symbol}: {e}")
            return SignalUrgency.MEDIUM
    
    def _check_timeframe_alignment(self, supertrend_signals: Dict[str, str]) -> bool:
        """检查多周期SuperTrend一致性"""
        if not supertrend_signals:
            return False
        
        # 获取所有周期的信号
        signals = list(supertrend_signals.values())
        if len(signals) < 3:  # 至少需要3个周期
            return False
        
        # 检查是否所有信号一致
        first_signal = signals[0]
        return all(signal == first_signal for signal in signals)
    
    def _build_signal_type(self, opportunity: TradingOpportunity, market_data: Dict[str, Any]) -> str:
        """构建信号类型字符串"""
        signal_parts = []
        
        # 基础信号强度
        confidence = opportunity.confidence / 100.0
        if confidence >= 0.75:
            signal_parts.append("very_strong")
        elif confidence >= 0.55:
            signal_parts.append("strong")
        else:
            signal_parts.append("medium")
        
        # 操作方向
        if opportunity.action.value in ['buy', 'strong_buy']:
            signal_parts.append("buy")
        elif opportunity.action.value in ['sell', 'strong_sell']:
            signal_parts.append("sell")
        
        # 特殊条件
        volume_ratio = market_data.get('volume_ratio', 1.0)
        if volume_ratio >= 3.0:
            signal_parts.append("volume_spike")
        
        supertrend_signals = market_data.get('supertrend_signals', {})
        if self._check_timeframe_alignment(supertrend_signals):
            signal_parts.append("multi_timeframe_consensus")
        
        funding_rate = market_data.get('funding_rate', 0.0)
        if abs(funding_rate) >= 0.01:
            signal_parts.append("extreme_funding")
        
        return "_".join(signal_parts)
    
    async def _send_immediate_notification(self, opportunity: TradingOpportunity) -> bool:
        """
        发送立即通知
        
        Args:
            opportunity: 交易机会
            
        Returns:
            bool: 是否发送成功
        """
        try:
            # 获取强信号配置
            urgency_config = strong_signal_config.get_notification_config(SignalUrgency.IMMEDIATE)
            
            # 构建紧急通知消息
            message = self._format_immediate_notification(opportunity)
            
            # 确保通知服务已初始化
            await self._ensure_notification_service()
            
            # 多渠道推送
            success_count = 0
            
            # 创建NotificationContent对象
            from app.services.core_notification_service import NotificationContent, NotificationType, NotificationPriority
            notification_content = NotificationContent(
                type=NotificationType.TRADING_SIGNAL,
                priority=NotificationPriority.URGENT,
                title=f"🚨 强交易信号: {opportunity.symbol}",
                message=message,
                metadata={
                    'symbol': opportunity.symbol,
                    'action': opportunity.action.value,
                    'confidence': float(opportunity.confidence),
                    'urgency': 'immediate',
                    'expected_profit': float(opportunity.expected_profit_usdt)
                }
            )
            
            try:
                await self.notification_service.send_notification(notification_content)
                success_count = 1
            except Exception as e:
                logger.error(f"发送立即通知失败: {e}")
                success_count = 0
            
            # 记录通知时间
            self.last_notification_time[opportunity.symbol] = datetime.now()
            
            logger.info(f"✅ 立即通知发送完成 {opportunity.symbol}: {success_count}/{len(urgency_config['channels'])} 渠道成功")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"发送立即通知失败 {opportunity.symbol}: {e}")
            return False
    
    def _format_immediate_notification(self, op: TradingOpportunity) -> str:
        """格式化立即通知消息"""
        action_emoji = "🚀" if op.action.value in ['buy', 'strong_buy'] else "🔻"
        
        message = f"""🚨 【强交易信号 - 立即关注】{action_emoji}

⚡ 交易对: {op.symbol}
🎯 操作: {self._get_action_text(op.action)}
📊 置信度: {op.confidence:.1f}%
💰 预期收益: {op.expected_profit_usdt:.0f} USDT
📈 风险收益比: 1:{op.risk_reward_ratio:.1f}

💡 交易参数:
• 入场价: {op.entry_price:.4f}
• 止损价: {op.stop_loss_price:.4f}  
• 止盈价: {op.take_profit_price:.4f}
• 建议仓位: {op.position_size_usdt:.0f} USDT

🔥 关键因素:
{chr(10).join(f"• {factor}" for factor in op.key_factors[:3])}

⏰ 时间: {datetime.now().strftime('%H:%M:%S')}
⚠️ 请及时关注市场变化！"""

        return message
    
    def _format_premium_opportunity_message(self, op: TradingOpportunity) -> str:
        """格式化顶级机会消息"""
        action_emoji = "🚀" if op.action.value in ['buy', 'strong_buy'] else "📉"
        urgency_emoji = "⚡" if op.urgency == "immediate" else "🔔"
        
        message = f"""{urgency_emoji} 【顶级交易机会】{action_emoji}

💎 交易对: {op.symbol}
🎯 操作: {self._get_action_text(op.action)}
📊 置信度: {op.confidence:.1f}%
💰 预期收益: {op.expected_profit_usdt:.0f} USDT
📈 风险收益比: 1:{op.risk_reward_ratio:.1f}
🎲 胜率: {op.win_probability:.1%}

💡 交易参数:
• 入场价: {op.entry_price:.4f}
• 止损价: {op.stop_loss_price:.4f}
• 止盈价: {op.take_profit_price:.4f}
• 建议仓位: {op.position_size_usdt:.0f} USDT
• 杠杆倍数: {op.leverage:.0f}x

🔥 关键因素:
{chr(10).join(f"• {factor}" for factor in op.key_factors[:4])}

⏰ 有效期: {op.urgency}
📅 时间: {op.timestamp.strftime('%H:%M:%S')}"""

        return message
    
    def _format_batch_opportunities_message(self, ops: List[TradingOpportunity], quality: str = "高质量") -> str:
        """格式化批量机会消息"""
        message = f"📊 【{quality}交易机会汇总】\n\n"
        
        for i, op in enumerate(ops, 1):
            action_emoji = "🚀" if op.action.value in ['buy', 'strong_buy'] else "📉"
            
            message += f"{i}. {action_emoji} {op.symbol}\n"
            message += f"   🎯 {self._get_action_text(op.action)} | 📊 {op.confidence:.0f}%\n"
            message += f"   💰 {op.expected_profit_usdt:.0f}U | 📈 1:{op.risk_reward_ratio:.1f}\n"
            
            # 显示最重要的因素
            if op.key_factors:
                message += f"   🔥 {op.key_factors[0]}\n"
            
            message += "\n"
        
        message += f"⏰ 时间: {datetime.now().strftime('%H:%M:%S')}\n"
        message += "💡 详细参数请查看完整分析报告"
        
        return message
    
    def _get_action_text(self, action: TradingAction) -> str:
        """获取操作文本"""
        action_map = {
            TradingAction.STRONG_BUY: "强烈买入",
            TradingAction.BUY: "买入",
            TradingAction.HOLD: "持有",
            TradingAction.SELL: "卖出",
            TradingAction.STRONG_SELL: "强烈卖出"
        }
        return action_map.get(action, action.value)
    
    def _format_opportunity_summary(self, op: TradingOpportunity) -> Dict[str, Any]:
        """格式化机会摘要"""
        return {
            'symbol': op.symbol,
            'level': op.level.value,
            'action': op.action.value,
            'confidence': op.confidence,
            'expected_profit_usdt': op.expected_profit_usdt,
            'risk_reward_ratio': op.risk_reward_ratio,
            'win_probability': op.win_probability,
            'urgency': op.urgency,
            'key_factors': op.key_factors[:3],
            'timestamp': op.timestamp.isoformat(),
            'valid_until': op.valid_until.isoformat()
        }


    def _update_signal_history(self, opportunity: TradingOpportunity):
        """更新信号历史记录"""
        current_time = datetime.now()
        level_key = opportunity.level.value.lower()
        signal_key = f"{opportunity.symbol}_{opportunity.action.value}_{level_key}"
        
        # 记录信号时间和置信度
        self.signal_history[signal_key] = current_time
        setattr(self, f'last_{signal_key}_confidence', opportunity.confidence)
        setattr(self, f'last_{opportunity.symbol}_action', opportunity.action.value)
        
        # 清理过期记录（保留最近24小时）
        cutoff_time = current_time - timedelta(hours=24)
        expired_keys = [
            key for key, timestamp in self.signal_history.items()
            if timestamp < cutoff_time
        ]
        for key in expired_keys:
            del self.signal_history[key]
    
    def get_signal_stats(self) -> Dict[str, Any]:
        """获取信号统计"""
        current_time = datetime.now()
        
        # 统计最近1小时、4小时、24小时的信号数量
        stats = {
            'last_1h': 0,
            'last_4h': 0, 
            'last_24h': 0,
            'by_level': {'premium': 0, 'high': 0, 'medium': 0, 'low': 0},
            'by_symbol': {},
            'by_action': {'buy': 0, 'sell': 0, 'strong_buy': 0, 'strong_sell': 0, 'hold': 0}
        }
        
        for signal_key, timestamp in self.signal_history.items():
            time_diff = (current_time - timestamp).total_seconds() / 3600  # 转换为小时
            
            if time_diff <= 1:
                stats['last_1h'] += 1
            if time_diff <= 4:
                stats['last_4h'] += 1
            if time_diff <= 24:
                stats['last_24h'] += 1
            
            # 解析信号key: symbol_action_level
            parts = signal_key.split('_')
            if len(parts) >= 3:
                symbol = parts[0]
                action = parts[1]
                level = parts[2]
                
                stats['by_level'][level] = stats['by_level'].get(level, 0) + 1
                stats['by_symbol'][symbol] = stats['by_symbol'].get(symbol, 0) + 1
                stats['by_action'][action] = stats['by_action'].get(action, 0) + 1
        
        return {
            'timestamp': current_time.isoformat(),
            'stats': stats,
            'total_active_signals': len(self.signal_history)
        }


# 全局服务实例
_intelligent_notification_service = None

async def get_intelligent_notification_service() -> IntelligentTradingNotificationService:
    """获取智能通知服务实例"""
    global _intelligent_notification_service
    if _intelligent_notification_service is None:
        _intelligent_notification_service = IntelligentTradingNotificationService()
    return _intelligent_notification_service