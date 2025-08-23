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
from app.services.okx_service import OKXService
from app.services.trading_decision_service import TradingDecisionService, TradingAction, RiskLevel
from app.services.ml_enhanced_service import MLEnhancedService, PredictionSignal
from app.services.notification_service import NotificationService
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
        self.decision_service = TradingDecisionService(exchange='okx')
        self.ml_service = MLEnhancedService()
        self.notification_service = NotificationService()
        
        # 机会筛选阈值
        self.min_confidence = 75.0          # 最低置信度75%
        self.min_risk_reward = 2.0          # 最低风险收益比2:1
        self.min_expected_profit = 50.0     # 最低预期盈利50 USDT
        
        # 推送频率控制
        self.last_notification_time = {}
        self.min_notification_interval = timedelta(hours=2)  # 同一币种最少2小时间隔
    
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
            
            # 推送通知
            notification_results = await self._send_opportunity_notifications(
                premium_opportunities, high_opportunities, force_scan
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
        """分析单个交易对的机会"""
        try:
            # 获取交易建议
            recommendation = await self.decision_service.get_trading_recommendation(symbol)
            
            # 获取ML预测
            ml_prediction = None
            market_anomalies = []
            try:
                ml_prediction = await self.ml_service.predict_signal(symbol)
                anomalies = await self.ml_service.detect_anomalies(symbol)
                market_anomalies = [a.description for a in anomalies if a.severity > 0.7]
            except Exception as e:
                logger.debug(f"ML分析失败 {symbol}: {e}")
            
            # 评估机会质量
            opportunity_level = self._evaluate_opportunity_level(
                recommendation, ml_prediction, market_anomalies
            )
            
            # 只返回中等以上的机会
            if opportunity_level == OpportunityLevel.LOW:
                return None
            
            # 计算胜率
            win_probability = self._calculate_win_probability(
                recommendation, ml_prediction
            )
            
            # 提取关键因素
            key_factors = self._extract_key_factors(
                recommendation, ml_prediction, market_anomalies
            )
            
            # 确定紧急程度
            urgency, valid_until = self._determine_urgency(
                recommendation, ml_prediction
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
                
                ml_signal_strength=ml_prediction.confidence if ml_prediction else 0.0,
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
    
    def _evaluate_opportunity_level(self, 
                                  recommendation, 
                                  ml_prediction, 
                                  anomalies: List[str]) -> OpportunityLevel:
        """评估机会等级"""
        score = 0
        
        # 基础信号强度 (40分)
        if recommendation.confidence > 85:
            score += 40
        elif recommendation.confidence > 75:
            score += 30
        elif recommendation.confidence > 65:
            score += 20
        else:
            score += 10
        
        # 风险收益比 (25分)
        if recommendation.risk_reward_ratio > 4:
            score += 25
        elif recommendation.risk_reward_ratio > 3:
            score += 20
        elif recommendation.risk_reward_ratio > 2:
            score += 15
        else:
            score += 5
        
        # ML信号确认 (20分)
        if ml_prediction:
            if (recommendation.action.value in ['buy', 'strong_buy'] and 
                ml_prediction.signal.value in ['buy', 'strong_buy']):
                score += 20
            elif (recommendation.action.value in ['sell', 'strong_sell'] and 
                  ml_prediction.signal.value in ['sell', 'strong_sell']):
                score += 20
            elif ml_prediction.confidence > 0.8:
                score += 15
            else:
                score += 5
        
        # 风险等级调整 (15分)
        if recommendation.risk_level in [RiskLevel.LOW, RiskLevel.VERY_LOW]:
            score += 15
        elif recommendation.risk_level == RiskLevel.MEDIUM:
            score += 10
        else:
            score += 0
        
        # 市场异常加分
        if len(anomalies) > 0:
            score += min(10, len(anomalies) * 3)
        
        # 等级判定
        if score >= 85:
            return OpportunityLevel.PREMIUM
        elif score >= 70:
            return OpportunityLevel.HIGH
        elif score >= 50:
            return OpportunityLevel.MEDIUM
        else:
            return OpportunityLevel.LOW
    
    def _calculate_win_probability(self, recommendation, ml_prediction) -> float:
        """计算胜率"""
        base_probability = 0.5
        
        # 基于置信度调整
        confidence_factor = recommendation.confidence / 100.0
        base_probability += (confidence_factor - 0.5) * 0.4
        
        # ML预测调整
        if ml_prediction and ml_prediction.confidence > 0.7:
            base_probability += 0.1
        
        # 风险收益比调整
        if recommendation.risk_reward_ratio > 3:
            base_probability += 0.05
        
        return min(0.95, max(0.3, base_probability))
    
    def _extract_key_factors(self, recommendation, ml_prediction, anomalies) -> List[str]:
        """提取关键决策因素"""
        factors = []
        
        # 从reasoning中提取
        reasoning_parts = recommendation.reasoning.split('|')
        for part in reasoning_parts[:3]:  # 取前3个最重要的
            factors.append(part.strip())
        
        # ML信号
        if ml_prediction and ml_prediction.confidence > 0.75:
            factors.append(f"ML预测: {ml_prediction.signal.value} ({ml_prediction.confidence:.1%})")
        
        # 异常情况
        if anomalies:
            factors.append(f"市场异常: {len(anomalies)}项")
        
        return factors[:5]  # 最多5个关键因素
    
    def _determine_urgency(self, recommendation, ml_prediction) -> Tuple[str, datetime]:
        """确定紧急程度和有效期"""
        now = datetime.now()
        
        # 强信号立即执行
        if (recommendation.confidence > 85 and 
            recommendation.action in [TradingAction.STRONG_BUY, TradingAction.STRONG_SELL]):
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
                                           force_send: bool = False) -> Dict[str, Any]:
        """发送机会通知"""
        sent_count = 0
        
        # 顶级机会 - 必须推送
        for op in premium_ops:
            if self._should_send_notification(op, force_send):
                message = self._format_premium_opportunity_message(op)
                await self.notification_service.send_notification(
                    message, priority="urgent"
                )
                self.last_notification_time[op.symbol] = datetime.now()
                sent_count += 1
        
        # 高质量机会 - 有限制推送
        high_ops_to_send = []
        for op in high_ops:
            if self._should_send_notification(op, force_send):
                high_ops_to_send.append(op)
        
        # 批量推送高质量机会（最多3个）
        if high_ops_to_send:
            message = self._format_batch_opportunities_message(high_ops_to_send[:3])
            await self.notification_service.send_notification(
                message, priority="high"
            )
            for op in high_ops_to_send[:3]:
                self.last_notification_time[op.symbol] = datetime.now()
            sent_count += len(high_ops_to_send[:3])
        
        return {'sent_count': sent_count}
    
    def _should_send_notification(self, opportunity: TradingOpportunity, force_send: bool) -> bool:
        """判断是否应该发送通知"""
        if force_send:
            return True
        
        # 检查时间间隔
        last_time = self.last_notification_time.get(opportunity.symbol)
        if last_time and datetime.now() - last_time < self.min_notification_interval:
            return False
        
        # 顶级机会总是发送
        if opportunity.level == OpportunityLevel.PREMIUM:
            return True
        
        # 高质量机会需要满足额外条件
        if opportunity.level == OpportunityLevel.HIGH:
            return (opportunity.confidence > self.min_confidence and
                   opportunity.risk_reward_ratio > self.min_risk_reward and
                   opportunity.expected_profit_usdt > self.min_expected_profit)
        
        return False
    
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
    
    def _format_batch_opportunities_message(self, opportunities: List[TradingOpportunity]) -> str:
        """格式化批量机会消息"""
        message = f"""📊 【高质量交易机会】

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