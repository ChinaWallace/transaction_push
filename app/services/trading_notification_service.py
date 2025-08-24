# -*- coding: utf-8 -*-
"""
交易通知服务
Trading Notification Service - 专门处理交易相关的通知推送
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import asyncio

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.notification_service import NotificationService
from app.services.trading_decision_service import TradingRecommendation, MarketAnalysis

logger = get_logger(__name__)
settings = get_settings()


class TradingNotificationService:
    """交易通知服务类"""
    
    def __init__(self):
        self.notification_service = NotificationService()
        
        # 通知配置
        self.notification_config = {
            'enable_trading_notifications': True,
            'min_confidence_for_notification': 65.0,
            'strong_signal_threshold': 80.0,
            'notification_cooldown_minutes': 30,  # 同一交易对通知冷却时间
            'max_notifications_per_hour': 10,     # 每小时最大通知数量
        }
        
        # 通知历史记录（用于冷却控制）
        self.notification_history = {}
        self.hourly_notification_count = 0
        self.last_hour_reset = datetime.now().hour
    
    async def send_trading_recommendation(self, recommendation: TradingRecommendation) -> bool:
        """
        发送交易建议通知
        
        Args:
            recommendation: 交易建议
            
        Returns:
            是否发送成功
        """
        if not self.notification_config['enable_trading_notifications']:
            return False
        
        # 检查通知限制 - 只发送强信号
        if not self._should_send_notification(recommendation.symbol, recommendation.confidence, recommendation.action.value):
            return False
        
        try:
            # 构建通知内容
            title, message = self._build_recommendation_notification(recommendation)
            
            # 确定优先级
            priority = self._determine_notification_priority(recommendation)
            
            # 发送通知
            success_results = await self.notification_service.send_notification(
                message=f"{title}\n\n{message}",
                priority=priority,
                subject=title
            )
            success = any(success_results.values()) if success_results else False
            
            if success:
                # 记录通知历史
                self._record_notification(recommendation.symbol)
                trading_logger.info(f"📢 已发送 {recommendation.symbol} 交易建议通知: {recommendation.action.value}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 发送交易建议通知失败: {e}")
            return False
    
    async def send_market_analysis(self, analysis: MarketAnalysis) -> bool:
        """
        发送市场分析通知
        
        Args:
            analysis: 市场分析结果
            
        Returns:
            是否发送成功
        """
        try:
            # 只有重要的市场变化才发送通知
            if not self._is_significant_market_change(analysis):
                return False
            
            title, message = self._build_analysis_notification(analysis)
            
            success_results = await self.notification_service.send_notification(
                message=f"{title}\n\n{message}",
                priority="normal",
                subject=title
            )
            success = any(success_results.values()) if success_results else False
            
            if success:
                trading_logger.info(f"📢 已发送 {analysis.symbol} 市场分析通知")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 发送市场分析通知失败: {e}")
            return False
    
    async def send_risk_alert(self, symbol: str, risk_info: Dict[str, Any]) -> bool:
        """
        发送风险警报
        
        Args:
            symbol: 交易对
            risk_info: 风险信息
            
        Returns:
            是否发送成功
        """
        try:
            risk_level = risk_info.get('risk_level', 'medium')
            risk_factors = risk_info.get('risk_factors', [])
            
            title = f"⚠️ 风险警报 - {symbol}"
            
            message_parts = [
                f"交易对: {symbol}",
                f"风险等级: {risk_level}",
                "",
                "风险因素:"
            ]
            
            for factor in risk_factors[:5]:  # 最多显示5个风险因素
                message_parts.append(f"  • {factor}")
            
            if risk_info.get('recommendation'):
                message_parts.extend([
                    "",
                    f"建议: {risk_info['recommendation']}"
                ])
            
            message = "\n".join(message_parts)
            
            # 风险警报使用高优先级
            priority = "high" if risk_level in ['high', 'very_high'] else "medium"
            
            success_results = await self.notification_service.send_notification(
                message=f"{title}\n\n{message}",
                priority=priority,
                subject=title
            )
            success = any(success_results.values()) if success_results else False
            
            if success:
                trading_logger.info(f"📢 已发送 {symbol} 风险警报")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 发送风险警报失败: {e}")
            return False
    
    async def send_batch_summary(self, batch_results: Dict[str, Any]) -> bool:
        """
        发送批量分析摘要通知
        
        Args:
            batch_results: 批量分析结果
            
        Returns:
            是否发送成功
        """
        try:
            summary = batch_results.get('summary', {})
            results = batch_results.get('results', {})
            
            title = f"📊 批量交易分析摘要 ({len(results)} 个交易对)"
            
            message_parts = [
                f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                f"分析交易对: {summary.get('total_symbols', 0)} 个",
                f"平均置信度: {summary.get('average_confidence', 0):.1f}%",
                "",
                "信号分布:"
            ]
            
            recommendations = summary.get('recommendations', {})
            for action, count in recommendations.items():
                if count > 0:
                    action_text = {
                        'strong_buy': '强烈买入',
                        'buy': '买入',
                        'hold': '持有',
                        'sell': '卖出',
                        'strong_sell': '强烈卖出',
                        'wait': '等待'
                    }.get(action, action)
                    message_parts.append(f"  • {action_text}: {count} 个")
            
            # 显示高置信度信号
            high_confidence_signals = []
            for symbol, result in results.items():
                if isinstance(result, dict) and 'confidence' in result:
                    if result['confidence'] > 75:
                        high_confidence_signals.append((symbol, result))
            
            if high_confidence_signals:
                message_parts.extend([
                    "",
                    "高置信度信号:"
                ])
                
                for symbol, result in high_confidence_signals[:5]:
                    action_text = {
                        'strong_buy': '强烈买入',
                        'buy': '买入',
                        'sell': '卖出',
                        'strong_sell': '强烈卖出'
                    }.get(result['action'], result['action'])
                    
                    message_parts.append(
                        f"  • {symbol}: {action_text} ({result['confidence']:.1f}%)"
                    )
            
            message = "\n".join(message_parts)
            
            success_results = await self.notification_service.send_notification(
                message=f"{title}\n\n{message}",
                priority="normal",
                subject=title
            )
            success = any(success_results.values()) if success_results else False
            
            if success:
                trading_logger.info("📢 已发送批量分析摘要通知")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 发送批量摘要通知失败: {e}")
            return False
    
    def _should_send_notification(self, symbol: str, confidence: float, action: str = None) -> bool:
        """
        检查是否应该发送通知 - 发送买入/卖出及以上信号
        
        Args:
            symbol: 交易对
            confidence: 置信度
            action: 交易动作
            
        Returns:
            是否应该发送
        """
        # 过滤掉观望信号，只发送明确的买入/卖出信号
        if action and action not in ['强烈买入', '买入', '强烈卖出', '卖出', '谨慎买入', '谨慎卖出', '技术买入', '技术卖出']:
            logger.debug(f"{symbol} 非交易信号 ({action})，跳过通知")
            return False
        
        # 明确过滤观望类信号
        if action in ['持有观望', '观望', '持有', '等待']:
            logger.debug(f"{symbol} 观望信号 ({action})，跳过通知")
            return False
        
        # 检查置信度阈值 - 降低阈值以发送更多信号
        min_threshold = 65.0 if action in ['强烈买入', '强烈卖出'] else 60.0
        if confidence < min_threshold:
            logger.debug(f"{symbol} 置信度不足 ({confidence:.1f}% < {min_threshold}%)，跳过通知")
            return False
        
        # 检查每小时通知限制
        current_hour = datetime.now().hour
        if current_hour != self.last_hour_reset:
            self.hourly_notification_count = 0
            self.last_hour_reset = current_hour
        
        if self.hourly_notification_count >= self.notification_config['max_notifications_per_hour']:
            logger.warning(f"已达到每小时通知限制 ({self.notification_config['max_notifications_per_hour']})")
            return False
        
        # 检查冷却时间
        if symbol in self.notification_history:
            last_notification = self.notification_history[symbol]
            cooldown_minutes = self.notification_config['notification_cooldown_minutes']
            
            if (datetime.now() - last_notification).total_seconds() < cooldown_minutes * 60:
                logger.debug(f"{symbol} 在冷却期内，跳过通知")
                return False
        
        return True
    
    def _record_notification(self, symbol: str) -> None:
        """
        记录通知历史
        
        Args:
            symbol: 交易对
        """
        self.notification_history[symbol] = datetime.now()
        self.hourly_notification_count += 1
    
    def _determine_notification_priority(self, recommendation: TradingRecommendation) -> str:
        """
        确定通知优先级
        
        Args:
            recommendation: 交易建议
            
        Returns:
            优先级字符串
        """
        confidence = recommendation.confidence
        action = recommendation.action.value
        risk_level = recommendation.risk_level.value
        
        # 强信号 + 高置信度 = 高优先级
        if action in ['strong_buy', 'strong_sell'] and confidence > 85:
            return "high"
        
        # 高风险 = 高优先级
        if risk_level in ['high', 'very_high']:
            return "high"
        
        # 高置信度 = 中优先级
        if confidence > self.notification_config['strong_signal_threshold']:
            return "medium"
        
        return "low"
    
    def _build_recommendation_notification(self, recommendation: TradingRecommendation) -> tuple[str, str]:
        """
        构建交易建议通知内容
        
        Args:
            recommendation: 交易建议
            
        Returns:
            (标题, 消息内容)
        """
        # 动作表情符号
        action_emoji = {
            'strong_buy': '🚀',
            'buy': '📈',
            'hold': '⏸️',
            'sell': '📉',
            'strong_sell': '💥',
            'wait': '⏳'
        }
        
        # 动作文本
        action_text = {
            'strong_buy': '强烈买入',
            'buy': '买入',
            'hold': '持有',
            'sell': '卖出',
            'strong_sell': '强烈卖出',
            'wait': '等待'
        }
        
        emoji = action_emoji.get(recommendation.action.value, '📊')
        action_name = action_text.get(recommendation.action.value, recommendation.action.value)
        
        title = f"{emoji} 交易信号 - {recommendation.symbol}"
        
        message_parts = [
            f"交易对: {recommendation.symbol}",
            f"当前价格: ${recommendation.current_price:.4f}",
            f"建议操作: {action_name}",
            f"置信度: {recommendation.confidence:.1f}%",
            "",
            f"建议仓位: {recommendation.position_size_percent:.1f}%",
            f"建议杠杆: {recommendation.leverage:.1f}x",
            f"风险等级: {recommendation.risk_level.value}",
            "",
            f"入场价格: ${recommendation.entry_price:.4f}",
            f"止损价格: ${recommendation.stop_loss_price:.4f}",
            f"止盈价格: ${recommendation.take_profit_price:.4f}",
            "",
            f"入场时机: {recommendation.entry_timing}",
        ]
        
        if recommendation.hold_duration_hours:
            message_parts.append(f"建议持仓: {recommendation.hold_duration_hours} 小时")
        
        message_parts.extend([
            "",
            f"决策理由: {recommendation.reasoning}"
        ])
        
        return title, "\n".join(message_parts)
    
    def _build_analysis_notification(self, analysis: MarketAnalysis) -> tuple[str, str]:
        """
        构建市场分析通知内容
        
        Args:
            analysis: 市场分析
            
        Returns:
            (标题, 消息内容)
        """
        title = f"📊 市场分析 - {analysis.symbol}"
        
        message_parts = [
            f"交易对: {analysis.symbol}",
            f"分析时间: {analysis.timestamp.strftime('%H:%M')}",
            "",
            f"看涨评分: {analysis.bullish_score:.1f}/100",
            f"看跌评分: {analysis.bearish_score:.1f}/100",
            f"波动性评分: {analysis.volatility_score:.1f}/100",
            "",
            f"市场状态: {analysis.market_regime}",
            f"趋势强度: {analysis.trend_strength:.1%}",
        ]
        
        # 添加传统信号信息
        if analysis.traditional_signals:
            signal = analysis.traditional_signals.get('overall_signal', 'unknown')
            strength = analysis.traditional_signals.get('signal_strength', 0)
            message_parts.extend([
                "",
                f"技术信号: {signal} (强度: {strength:.1%})"
            ])
        
        # 添加ML预测信息
        if analysis.ml_prediction:
            ml_signal = analysis.ml_prediction.get('signal', 'unknown')
            ml_confidence = analysis.ml_prediction.get('confidence', 0)
            message_parts.extend([
                f"ML预测: {ml_signal} (置信度: {ml_confidence:.1%})"
            ])
        
        # 添加异常信息
        if analysis.ml_anomalies:
            high_severity = sum(1 for a in analysis.ml_anomalies if a.get('severity', 0) > 0.7)
            if high_severity > 0:
                message_parts.extend([
                    "",
                    f"⚠️ 检测到 {high_severity} 个高严重度异常"
                ])
        
        return title, "\n".join(message_parts)
    
    def _is_significant_market_change(self, analysis: MarketAnalysis) -> bool:
        """
        判断是否为重要的市场变化
        
        Args:
            analysis: 市场分析
            
        Returns:
            是否重要
        """
        # 强烈的看涨或看跌信号
        if analysis.bullish_score > 85 or analysis.bearish_score > 85:
            return True
        
        # 高波动性
        if analysis.volatility_score > 80:
            return True
        
        # 强趋势
        if analysis.trend_strength > 0.8:
            return True
        
        # 高严重度异常
        high_severity_anomalies = sum(1 for a in analysis.ml_anomalies if a.get('severity', 0) > 0.8)
        if high_severity_anomalies > 2:
            return True
        
        return False
    
    async def send_unified_trading_notification(self, notification_data: Dict[str, Any]) -> bool:
        """
        发送统一交易通知 - 包含详细技术分析
        
        Args:
            notification_data: 通知数据
            
        Returns:
            是否发送成功
        """
        try:
            symbol = notification_data['symbol']
            action = notification_data['action']
            confidence = notification_data['confidence']
            reasoning = notification_data['reasoning']
            current_price = notification_data['current_price']
            stop_loss = notification_data['stop_loss']
            take_profit = notification_data['take_profit']
            position_size = notification_data['position_size']
            risk_level = notification_data['risk_level']
            
            # 获取额外的技术分析详情
            traditional_signal = notification_data.get('traditional_signal', '未知')
            traditional_confidence = notification_data.get('traditional_confidence', 0)
            ml_signal = notification_data.get('ml_signal', '未知')
            ml_confidence = notification_data.get('ml_confidence', 0)
            market_regime = notification_data.get('market_regime', '未知')
            volatility_level = notification_data.get('volatility_level', '中等')
            key_factors = notification_data.get('key_factors', [])
            entry_timing = notification_data.get('entry_timing', '立即')
            leverage = notification_data.get('leverage', 1.0)
            risk_reward_ratio = notification_data.get('risk_reward_ratio', 0)
            
            # 检查通知限制 - 只发送强信号
            if not self._should_send_notification(symbol, confidence, action):
                return False
            
            # 获取详细技术分析
            detailed_analysis = await self._get_detailed_technical_analysis(symbol)
            
            # 动作图标映射
            action_icons = {
                '强烈买入': '🚀',
                '买入': '📈',
                '持有': '⏸️',
                '卖出': '📉',
                '强烈卖出': '💥',
                '等待': '⏳'
            }
            
            # 风险等级图标
            risk_icons = {
                '极低风险': '🟢',
                '低风险': '🟡',
                '中等风险': '🟠',
                '高风险': '🔴',
                '极高风险': '⚫'
            }
            
            # 市场状态图标
            regime_icons = {
                '上涨趋势': '📈',
                '下跌趋势': '📉',
                '震荡整理': '↔️',
                '高波动': '🌊',
                '平静': '😴'
            }
            
            icon = action_icons.get(action, '📊')
            risk_icon = risk_icons.get(risk_level, '⚪')
            regime_icon = regime_icons.get(market_regime, '📊')
            
            title = f"{icon} 统一交易决策 - {symbol}"
            
            # 构建详细通知消息
            message_parts = [
                f"🎯 交易对: {symbol}",
                f"💰 当前价格: ${current_price:.4f}",
                f"🎯 综合建议: {action}",
                f"📊 总体置信度: {confidence:.1f}%",
                "",
                "📈 技术分析详情:",
                f"  传统分析: {traditional_signal} ({traditional_confidence:.1f}%)",
                f"  机器学习: {ml_signal} ({ml_confidence:.1f}%)",
                f"  {regime_icon} 市场状态: {market_regime}",
                f"  🌊 波动水平: {volatility_level}",
                "",
                "🎯 交易参数:",
                f"  💵 建议仓位: {position_size:.1f}%",
                f"  ⚖️ 建议杠杆: {leverage:.1f}x",
                f"  🛡️ 止损价: ${stop_loss:.4f} ({((current_price - stop_loss) / current_price * 100):+.2f}%)",
                f"  🎯 止盈价: ${take_profit:.4f} ({((take_profit - current_price) / current_price * 100):+.2f}%)",
                f"  📊 风险收益比: 1:{risk_reward_ratio:.1f}",
                f"  {risk_icon} 风险等级: {risk_level}",
                "",
                "⏰ 执行建议:",
                f"  🕐 入场时机: {entry_timing}",
            ]
            
            # 添加详细技术分析
            if detailed_analysis:
                message_parts.extend([
                    "",
                    "📊 技术指标分析:"
                ])
                
                # 添加各类指标评分
                for category, score in detailed_analysis.weighted_breakdown.items():
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
                    "🔍 关键技术指标:"
                ])
                
                # 选择最重要的指标显示
                all_indicators = (detailed_analysis.trend_indicators + detailed_analysis.momentum_indicators + 
                                detailed_analysis.volume_indicators + detailed_analysis.volatility_indicators)
                
                # 按权重排序，取前4个
                important_indicators = sorted(all_indicators, key=lambda x: x.weight, reverse=True)[:4]
                
                for indicator in important_indicators:
                    signal_emoji = "📈" if indicator.signal == 'buy' else "📉" if indicator.signal == 'sell' else "⏸️"
                    message_parts.append(
                        f"  • {indicator.name}: {signal_emoji} {indicator.description}"
                    )
            else:
                # 如果没有详细分析，使用原有的关键因素
                message_parts.extend([
                    "",
                    "🔍 关键因素:"
                ])
                
                if key_factors:
                    for factor in key_factors[:5]:  # 最多显示5个关键因素
                        message_parts.append(f"  • {factor}")
                else:
                    message_parts.append(f"  • {reasoning}")
            
            message_parts.extend([
                "",
                f"💡 综合分析: {reasoning}",
                "",
                f"⏰ 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "⚠️ 风险提示: 本建议融合传统技术分析和机器学习，仅供参考，请谨慎投资！"
            ])
            
            message = "\n".join(message_parts)
            
            # 确定优先级
            if action in ['强烈买入', '强烈卖出'] and confidence > 80:
                priority = "high"
            elif confidence > 75:
                priority = "medium"
            else:
                priority = "low"
            
            # 发送通知
            success_results = await self.notification_service.send_notification(
                message=f"{title}\n\n{message}",
                priority=priority,
                subject=title
            )
            success = any(success_results.values()) if success_results else False
            
            if success:
                # 记录通知历史
                self._record_notification(symbol)
                trading_logger.info(f"📢 已发送 {symbol} 详细技术分析通知: {action} (置信度: {confidence:.1f}%)")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 发送统一交易通知失败: {e}")
            return False
    
    async def _get_detailed_technical_analysis(self, symbol: str) -> Optional[Any]:
        """获取详细技术分析"""
        try:
            from app.services.detailed_technical_analysis_service import DetailedTechnicalAnalysisService
            
            detailed_service = DetailedTechnicalAnalysisService()
            analysis = await detailed_service.analyze_symbol_detailed(symbol)
            return analysis
            
        except Exception as e:
            logger.warning(f"获取{symbol}详细技术分析失败: {e}")
            return None

    async def send_notification(self, title: str, message: str, 
                              notification_type: str = "general", 
                              priority: str = "medium") -> bool:
        """
        发送通用通知（兼容接口）
        
        Args:
            title: 通知标题
            message: 通知内容
            notification_type: 通知类型
            priority: 优先级
            
        Returns:
            是否发送成功
        """
        success_results = await self.notification_service.send_notification(
            message=f"{title}\n\n{message}" if title else message,
            priority=priority
        )
        return any(success_results.values()) if success_results else False