# -*- coding: utf-8 -*-
"""
综合交易策略服务
Comprehensive Trading Service - 整合所有交易分析功能的核心服务
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import asyncio
import numpy as np

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.trading_decision_service import TradingDecisionService, TradingRecommendation, MarketAnalysis
from app.services.trading_notification_service import TradingNotificationService
from app.services.trend_analysis_service import TrendAnalysisService
from app.services.ml_enhanced_service import MLEnhancedService
from app.services.binance_service import BinanceService
from app.services.scheduler_service import SchedulerService
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


@dataclass
class TradingSession:
    """交易会话"""
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
    """投资组合快照"""
    timestamp: datetime
    total_value: float
    positions: Dict[str, float]
    risk_score: float
    recommendations: List[TradingRecommendation]
    market_conditions: Dict[str, Any]


class ComprehensiveTradingService:
    """综合交易策略服务类"""
    
    def __init__(self):
        self.decision_service = TradingDecisionService()
        self.notification_service = TradingNotificationService()
        self.trend_service = TrendAnalysisService()
        self.ml_service = MLEnhancedService()
        self.binance_service = BinanceService()
        self.scheduler_service = SchedulerService()
        
        # 会话管理
        self.active_sessions: Dict[str, TradingSession] = {}
        self.portfolio_history: List[PortfolioSnapshot] = []
        
        # 配置参数
        self.max_concurrent_analyses = 10
        self.session_timeout_hours = 24
        self.portfolio_snapshot_interval = 3600  # 1小时
    
    async def start_trading_session(self, symbols: List[str], 
                                  session_config: Dict[str, Any] = None) -> str:
        """
        启动交易会话
        
        Args:
            symbols: 要分析的交易对列表
            session_config: 会话配置
            
        Returns:
            会话ID
        """
        try:
            session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            session = TradingSession(
                session_id=session_id,
                symbols=symbols,
                start_time=datetime.now(),
                end_time=None,
                total_analyses=0,
                successful_analyses=0,
                recommendations_sent=0,
                alerts_sent=0,
                status="active"
            )
            
            self.active_sessions[session_id] = session
            
            trading_logger.info(f"Trading session started: {session_id} with {len(symbols)} symbols")
            
            # 启动定时任务
            if session_config and session_config.get('auto_analysis', True):
                await self._schedule_session_tasks(session_id, session_config)
            
            return session_id
            
        except Exception as e:
            logger.error(f"Failed to start trading session: {e}")
            raise TradingToolError(f"启动交易会话失败: {e}")
    
    async def comprehensive_market_scan(self, symbols: List[str], 
                                     account_balance: float = 10000,
                                     send_notifications: bool = True) -> Dict[str, Any]:
        """
        综合市场扫描
        
        Args:
            symbols: 交易对列表
            account_balance: 账户余额
            send_notifications: 是否发送通知
            
        Returns:
            扫描结果
        """
        try:
            scan_start = datetime.now()
            
            # 分批处理以避免过载
            batch_size = self.max_concurrent_analyses
            batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
            
            all_results = {}
            market_summary = {
                "scan_time": scan_start,
                "total_symbols": len(symbols),
                "successful_analyses": 0,
                "failed_analyses": 0,
                "strong_buy_signals": 0,
                "strong_sell_signals": 0,
                "high_risk_symbols": 0,
                "market_regime_distribution": {},
                "average_confidence": 0.0,
                "top_opportunities": [],
                "risk_alerts": []
            }
            
            total_confidence = 0.0
            
            for batch in batches:
                batch_results = await self._process_symbol_batch(
                    batch, account_balance, send_notifications
                )
                all_results.update(batch_results)
                
                # 更新统计
                for symbol, result in batch_results.items():
                    if "error" not in result:
                        market_summary["successful_analyses"] += 1
                        
                        recommendation = result.get("recommendation")
                        if recommendation:
                            # 统计信号类型
                            action = recommendation.get("action")
                            if action == "strong_buy":
                                market_summary["strong_buy_signals"] += 1
                            elif action == "strong_sell":
                                market_summary["strong_sell_signals"] += 1
                            
                            # 统计风险
                            if recommendation.get("risk_level") in ["high", "very_high"]:
                                market_summary["high_risk_symbols"] += 1
                            
                            # 统计市场状态
                            analysis = result.get("analysis")
                            if analysis:
                                regime = analysis.get("market_regime", "unknown")
                                market_summary["market_regime_distribution"][regime] = \
                                    market_summary["market_regime_distribution"].get(regime, 0) + 1
                            
                            # 累计置信度
                            confidence = recommendation.get("confidence", 0)
                            total_confidence += confidence
                            
                            # 收集顶级机会
                            if action in ["strong_buy", "strong_sell"] and confidence > 80:
                                market_summary["top_opportunities"].append({
                                    "symbol": symbol,
                                    "action": action,
                                    "confidence": confidence,
                                    "risk_level": recommendation.get("risk_level")
                                })
                    else:
                        market_summary["failed_analyses"] += 1
            
            # 计算平均置信度
            if market_summary["successful_analyses"] > 0:
                market_summary["average_confidence"] = total_confidence / market_summary["successful_analyses"]
            
            # 排序顶级机会
            market_summary["top_opportunities"].sort(key=lambda x: x["confidence"], reverse=True)
            market_summary["top_opportunities"] = market_summary["top_opportunities"][:10]
            
            # 生成市场概览通知
            if send_notifications and market_summary["successful_analyses"] > 0:
                await self._send_market_scan_summary(market_summary)
            
            scan_duration = (datetime.now() - scan_start).total_seconds()
            
            return {
                "scan_results": all_results,
                "market_summary": market_summary,
                "scan_duration_seconds": scan_duration,
                "timestamp": scan_start
            }
            
        except Exception as e:
            logger.error(f"Comprehensive market scan failed: {e}")
            raise TradingToolError(f"市场扫描失败: {e}")
    
    async def portfolio_analysis(self, positions: Dict[str, float], 
                               account_balance: float) -> Dict[str, Any]:
        """
        投资组合分析
        
        Args:
            positions: 当前持仓 {symbol: position_size}
            account_balance: 账户余额
            
        Returns:
            投资组合分析结果
        """
        try:
            analysis_start = datetime.now()
            
            # 获取所有持仓的分析
            position_analyses = {}
            total_risk_score = 0.0
            total_value = sum(positions.values())
            
            for symbol, position_size in positions.items():
                try:
                    # 获取市场分析和交易建议
                    analysis_task = self.decision_service.analyze_market(symbol)
                    recommendation_task = self.decision_service.get_trading_recommendation(
                        symbol, account_balance, positions
                    )
                    
                    analysis, recommendation = await asyncio.gather(
                        analysis_task, recommendation_task, return_exceptions=True
                    )
                    
                    if not isinstance(analysis, Exception) and not isinstance(recommendation, Exception):
                        # 计算仓位风险
                        position_weight = position_size / total_value if total_value > 0 else 0
                        position_risk = self._calculate_position_risk(
                            analysis, recommendation, position_weight
                        )
                        
                        total_risk_score += position_risk * position_weight
                        
                        position_analyses[symbol] = {
                            "position_size": position_size,
                            "position_weight": position_weight * 100,
                            "current_recommendation": {
                                "action": recommendation.action.value,
                                "confidence": recommendation.confidence,
                                "risk_level": recommendation.risk_level.value
                            },
                            "market_analysis": {
                                "bullish_score": analysis.bullish_score,
                                "bearish_score": analysis.bearish_score,
                                "volatility_score": analysis.volatility_score,
                                "market_regime": analysis.market_regime
                            },
                            "position_risk": position_risk,
                            "recommendations": self._generate_position_recommendations(
                                symbol, analysis, recommendation, position_weight
                            )
                        }
                    else:
                        position_analyses[symbol] = {
                            "error": "分析失败",
                            "position_size": position_size,
                            "position_weight": (position_size / total_value * 100) if total_value > 0 else 0
                        }
                        
                except Exception as e:
                    logger.warning(f"Position analysis failed for {symbol}: {e}")
                    position_analyses[symbol] = {
                        "error": str(e),
                        "position_size": position_size
                    }
            
            # 计算投资组合指标
            portfolio_metrics = self._calculate_portfolio_metrics(
                positions, position_analyses, account_balance, total_risk_score
            )
            
            # 生成投资组合建议
            portfolio_recommendations = self._generate_portfolio_recommendations(
                portfolio_metrics, position_analyses
            )
            
            # 创建投资组合快照
            snapshot = PortfolioSnapshot(
                timestamp=analysis_start,
                total_value=total_value,
                positions=positions.copy(),
                risk_score=total_risk_score,
                recommendations=[],  # 简化版本
                market_conditions={}
            )
            
            self.portfolio_history.append(snapshot)
            
            # 保持历史记录在合理范围内
            if len(self.portfolio_history) > 100:
                self.portfolio_history = self.portfolio_history[-100:]
            
            analysis_duration = (datetime.now() - analysis_start).total_seconds()
            
            return {
                "portfolio_metrics": portfolio_metrics,
                "position_analyses": position_analyses,
                "portfolio_recommendations": portfolio_recommendations,
                "risk_assessment": {
                    "overall_risk_score": total_risk_score,
                    "risk_level": self._get_risk_level_from_score(total_risk_score),
                    "risk_factors": self._identify_risk_factors(position_analyses)
                },
                "analysis_duration_seconds": analysis_duration,
                "timestamp": analysis_start
            }
            
        except Exception as e:
            logger.error(f"Portfolio analysis failed: {e}")
            raise TradingToolError(f"投资组合分析失败: {e}")
    
    async def real_time_monitoring(self, symbols: List[str], 
                                 monitoring_config: Dict[str, Any] = None) -> str:
        """
        启动实时监控
        
        Args:
            symbols: 监控的交易对列表
            monitoring_config: 监控配置
            
        Returns:
            监控任务ID
        """
        try:
            config = monitoring_config or {}
            interval_minutes = config.get("interval_minutes", 15)
            alert_thresholds = config.get("alert_thresholds", {})
            
            # 创建监控任务
            task_id = f"monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            async def monitoring_task():
                """监控任务函数"""
                while True:
                    try:
                        # 执行快速扫描
                        scan_results = await self.comprehensive_market_scan(
                            symbols, send_notifications=False
                        )
                        
                        # 检查警报条件
                        alerts = self._check_alert_conditions(
                            scan_results, alert_thresholds
                        )
                        
                        # 发送警报
                        for alert in alerts:
                            await self.notification_service.send_risk_alert(
                                alert["symbol"], alert["message"]
                            )
                        
                        # 等待下一次检查
                        await asyncio.sleep(interval_minutes * 60)
                        
                    except Exception as e:
                        logger.error(f"Monitoring task error: {e}")
                        await asyncio.sleep(60)  # 错误时等待1分钟后重试
            
            # 启动监控任务
            self.scheduler_service.add_job(
                func=monitoring_task,
                trigger="interval",
                minutes=interval_minutes,
                id=task_id,
                replace_existing=True
            )
            
            trading_logger.info(f"Real-time monitoring started: {task_id}")
            return task_id
            
        except Exception as e:
            logger.error(f"Failed to start real-time monitoring: {e}")
            raise TradingToolError(f"启动实时监控失败: {e}")
    
    async def _process_symbol_batch(self, symbols: List[str], 
                                  account_balance: float,
                                  send_notifications: bool) -> Dict[str, Any]:
        """处理交易对批次"""
        batch_results = {}
        
        # 创建并发任务
        tasks = []
        for symbol in symbols:
            task = self._analyze_single_symbol(symbol, account_balance, send_notifications)
            tasks.append((symbol, task))
        
        # 执行并发分析
        for symbol, task in tasks:
            try:
                result = await task
                batch_results[symbol] = result
            except Exception as e:
                logger.warning(f"Symbol analysis failed for {symbol}: {e}")
                batch_results[symbol] = {"error": str(e)}
        
        return batch_results
    
    async def _analyze_single_symbol(self, symbol: str, account_balance: float,
                                   send_notifications: bool) -> Dict[str, Any]:
        """分析单个交易对"""
        try:
            # 并行获取分析和建议
            analysis_task = self.decision_service.analyze_market(symbol)
            recommendation_task = self.decision_service.get_trading_recommendation(
                symbol, account_balance
            )
            
            analysis, recommendation = await asyncio.gather(
                analysis_task, recommendation_task
            )
            
            # 发送通知（如果需要且是强信号）
            if send_notifications and recommendation.action.value in ['strong_buy', 'strong_sell']:
                await self.notification_service.send_trading_recommendation(recommendation)
            
            return {
                "analysis": {
                    "bullish_score": analysis.bullish_score,
                    "bearish_score": analysis.bearish_score,
                    "volatility_score": analysis.volatility_score,
                    "market_regime": analysis.market_regime,
                    "trend_strength": analysis.trend_strength
                },
                "recommendation": {
                    "action": recommendation.action.value,
                    "confidence": recommendation.confidence,
                    "position_size_percent": recommendation.position_size_percent,
                    "leverage": recommendation.leverage,
                    "risk_level": recommendation.risk_level.value,
                    "entry_timing": recommendation.entry_timing
                }
            }
            
        except Exception as e:
            raise TradingToolError(f"Symbol analysis failed for {symbol}: {e}")    

    def _calculate_position_risk(self, analysis: MarketAnalysis, 
                               recommendation: TradingRecommendation,
                               position_weight: float) -> float:
        """计算单个仓位风险"""
        risk_score = 0.0
        
        # 波动性风险
        volatility_risk = analysis.volatility_score / 100 * 0.3
        
        # 异常风险
        high_anomalies = sum(1 for a in analysis.ml_anomalies if a.get('severity', 0) > 0.7)
        anomaly_risk = min(high_anomalies * 0.1, 0.2)
        
        # 仓位集中度风险
        concentration_risk = min(position_weight * 2, 0.3)
        
        # 杠杆风险
        leverage_risk = (recommendation.leverage - 1) * 0.1
        
        risk_score = volatility_risk + anomaly_risk + concentration_risk + leverage_risk
        return min(risk_score, 1.0)
    
    def _calculate_portfolio_metrics(self, positions: Dict[str, float],
                                   position_analyses: Dict[str, Any],
                                   account_balance: float,
                                   total_risk_score: float) -> Dict[str, Any]:
        """计算投资组合指标"""
        total_value = sum(positions.values())
        
        # 基础指标
        metrics = {
            "total_positions": len(positions),
            "total_value": total_value,
            "account_utilization": (total_value / account_balance) * 100 if account_balance > 0 else 0,
            "cash_reserve": account_balance - total_value,
            "cash_reserve_percent": ((account_balance - total_value) / account_balance) * 100 if account_balance > 0 else 0
        }
        
        if positions:
            # 仓位分布
            position_sizes = list(positions.values())
            metrics.update({
                "largest_position": max(position_sizes),
                "smallest_position": min(position_sizes),
                "average_position": sum(position_sizes) / len(position_sizes),
                "position_concentration": (max(position_sizes) / total_value) * 100 if total_value > 0 else 0
            })
            
            # 风险指标
            successful_analyses = [a for a in position_analyses.values() if "error" not in a]
            if successful_analyses:
                avg_volatility = sum(a["market_analysis"]["volatility_score"] for a in successful_analyses) / len(successful_analyses)
                high_risk_positions = sum(1 for a in successful_analyses if a["current_recommendation"]["risk_level"] in ["high", "very_high"])
                
                metrics.update({
                    "average_volatility": avg_volatility,
                    "high_risk_positions": high_risk_positions,
                    "high_risk_ratio": (high_risk_positions / len(successful_analyses)) * 100,
                    "overall_risk_score": total_risk_score
                })
        
        return metrics
    
    def _generate_position_recommendations(self, symbol: str, analysis: MarketAnalysis,
                                         recommendation: TradingRecommendation,
                                         position_weight: float) -> List[str]:
        """生成仓位建议"""
        recommendations = []
        
        # 基于当前建议
        if recommendation.action.value in ['sell', 'strong_sell']:
            recommendations.append(f"考虑减仓或平仓 {symbol}")
        elif recommendation.action.value in ['buy', 'strong_buy']:
            if position_weight < 0.05:  # 仓位小于5%
                recommendations.append(f"可考虑增加 {symbol} 仓位")
        
        # 基于风险
        if recommendation.risk_level.value in ['high', 'very_high']:
            recommendations.append(f"降低 {symbol} 杠杆或减仓")
        
        # 基于波动性
        if analysis.volatility_score > 80:
            recommendations.append(f"{symbol} 波动性过高，建议谨慎操作")
        
        # 基于仓位集中度
        if position_weight > 0.25:  # 仓位超过25%
            recommendations.append(f"{symbol} 仓位过于集中，建议分散投资")
        
        return recommendations
    
    def _generate_portfolio_recommendations(self, metrics: Dict[str, Any],
                                          position_analyses: Dict[str, Any]) -> List[str]:
        """生成投资组合建议"""
        recommendations = []
        
        # 现金储备建议
        cash_reserve_percent = metrics.get("cash_reserve_percent", 0)
        if cash_reserve_percent < 10:
            recommendations.append("现金储备不足，建议保持至少10%的现金储备")
        elif cash_reserve_percent > 50:
            recommendations.append("现金储备过多，可考虑增加投资")
        
        # 仓位集中度建议
        concentration = metrics.get("position_concentration", 0)
        if concentration > 40:
            recommendations.append("投资组合过于集中，建议分散投资降低风险")
        
        # 风险管理建议
        high_risk_ratio = metrics.get("high_risk_ratio", 0)
        if high_risk_ratio > 30:
            recommendations.append("高风险仓位占比过高，建议降低整体风险敞口")
        
        # 波动性建议
        avg_volatility = metrics.get("average_volatility", 50)
        if avg_volatility > 70:
            recommendations.append("投资组合整体波动性较高，建议增加稳定性资产")
        
        return recommendations
    
    def _get_risk_level_from_score(self, risk_score: float) -> str:
        """根据风险评分获取风险等级"""
        if risk_score > 0.8:
            return "very_high"
        elif risk_score > 0.6:
            return "high"
        elif risk_score > 0.4:
            return "medium"
        elif risk_score > 0.2:
            return "low"
        else:
            return "very_low"
    
    def _identify_risk_factors(self, position_analyses: Dict[str, Any]) -> List[str]:
        """识别风险因素"""
        risk_factors = []
        
        successful_analyses = [a for a in position_analyses.values() if "error" not in a]
        if not successful_analyses:
            return risk_factors
        
        # 高波动性资产
        high_volatility_count = sum(1 for a in successful_analyses if a["market_analysis"]["volatility_score"] > 80)
        if high_volatility_count > 0:
            risk_factors.append(f"{high_volatility_count}个高波动性资产")
        
        # 高风险仓位
        high_risk_count = sum(1 for a in successful_analyses if a["current_recommendation"]["risk_level"] in ["high", "very_high"])
        if high_risk_count > 0:
            risk_factors.append(f"{high_risk_count}个高风险仓位")
        
        # 市场状态风险
        volatile_markets = sum(1 for a in successful_analyses if a["market_analysis"]["market_regime"] == "volatile")
        if volatile_markets > len(successful_analyses) * 0.5:
            risk_factors.append("市场整体波动性较高")
        
        return risk_factors
    
    def _check_alert_conditions(self, scan_results: Dict[str, Any],
                              alert_thresholds: Dict[str, Any]) -> List[Dict[str, str]]:
        """检查警报条件"""
        alerts = []
        
        # 默认阈值
        default_thresholds = {
            "high_volatility_threshold": 85,
            "strong_signal_confidence_threshold": 85,
            "risk_level_alert": ["high", "very_high"]
        }
        thresholds = {**default_thresholds, **alert_thresholds}
        
        scan_data = scan_results.get("scan_results", {})
        
        for symbol, result in scan_data.items():
            if "error" in result:
                continue
            
            analysis = result.get("analysis", {})
            recommendation = result.get("recommendation", {})
            
            # 高波动性警报
            volatility = analysis.get("volatility_score", 0)
            if volatility > thresholds["high_volatility_threshold"]:
                alerts.append({
                    "symbol": symbol,
                    "type": "high_volatility",
                    "message": f"检测到高波动性: {volatility:.1f}%"
                })
            
            # 强信号警报
            confidence = recommendation.get("confidence", 0)
            action = recommendation.get("action", "")
            if confidence > thresholds["strong_signal_confidence_threshold"] and action in ["strong_buy", "strong_sell"]:
                alerts.append({
                    "symbol": symbol,
                    "type": "strong_signal",
                    "message": f"强{action}信号，置信度: {confidence:.1f}%"
                })
            
            # 高风险警报
            risk_level = recommendation.get("risk_level", "")
            if risk_level in thresholds["risk_level_alert"]:
                alerts.append({
                    "symbol": symbol,
                    "type": "high_risk",
                    "message": f"检测到{risk_level}风险等级"
                })
        
        return alerts
    
    async def _send_market_scan_summary(self, market_summary: Dict[str, Any]):
        """发送市场扫描摘要通知"""
        try:
            total = market_summary["total_symbols"]
            successful = market_summary["successful_analyses"]
            strong_buy = market_summary["strong_buy_signals"]
            strong_sell = market_summary["strong_sell_signals"]
            high_risk = market_summary["high_risk_symbols"]
            avg_confidence = market_summary["average_confidence"]
            
            message = f"""📊 **市场扫描摘要**

🔍 **扫描概况**:
• 总计分析: {total}个交易对
• 成功分析: {successful}个
• 平均置信度: {avg_confidence:.1f}%

📈 **信号统计**:
• 强买入信号: {strong_buy}个
• 强卖出信号: {strong_sell}个
• 高风险标的: {high_risk}个

🏆 **顶级机会**:"""

            # 添加顶级机会
            top_opportunities = market_summary["top_opportunities"][:5]
            for i, opp in enumerate(top_opportunities, 1):
                action_emoji = "🚀" if opp["action"] == "strong_buy" else "💥"
                message += f"\n{i}. {action_emoji} {opp['symbol']} - {opp['confidence']:.1f}%"
            
            if not top_opportunities:
                message += "\n暂无强信号机会"
            
            message += f"""

📊 **市场状态分布**:"""
            
            regime_dist = market_summary["market_regime_distribution"]
            for regime, count in regime_dist.items():
                percentage = (count / successful) * 100 if successful > 0 else 0
                message += f"\n• {regime}: {count}个 ({percentage:.1f}%)"
            
            message += f"""

⏰ **扫描时间**: {market_summary['scan_time'].strftime('%Y-%m-%d %H:%M:%S')}"""
            
            await self.notification_service.notification_service.send_notification(
                message=message,
                priority="normal",
                subject="📊 市场扫描摘要"
            )
            
        except Exception as e:
            logger.error(f"Failed to send market scan summary: {e}")
    
    async def _schedule_session_tasks(self, session_id: str, config: Dict[str, Any]):
        """为会话安排定时任务"""
        try:
            session = self.active_sessions.get(session_id)
            if not session:
                return
            
            # 定期分析任务
            analysis_interval = config.get("analysis_interval_minutes", 30)
            
            async def periodic_analysis():
                """定期分析任务"""
                try:
                    if session_id in self.active_sessions:
                        scan_results = await self.comprehensive_market_scan(
                            session.symbols, send_notifications=True
                        )
                        session.total_analyses += 1
                        session.successful_analyses += scan_results["market_summary"]["successful_analyses"]
                except Exception as e:
                    logger.error(f"Periodic analysis failed for session {session_id}: {e}")
            
            # 添加定时任务
            self.scheduler_service.add_job(
                func=periodic_analysis,
                trigger="interval",
                minutes=analysis_interval,
                id=f"{session_id}_analysis",
                replace_existing=True
            )
            
        except Exception as e:
            logger.error(f"Failed to schedule session tasks: {e}")
    
    async def stop_trading_session(self, session_id: str) -> Dict[str, Any]:
        """
        停止交易会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话摘要
        """
        try:
            session = self.active_sessions.get(session_id)
            if not session:
                raise TradingToolError(f"Session not found: {session_id}")
            
            # 更新会话状态
            session.end_time = datetime.now()
            session.status = "completed"
            
            # 停止相关的定时任务
            try:
                self.scheduler_service.remove_job(f"{session_id}_analysis")
            except:
                pass  # 任务可能不存在
            
            # 生成会话摘要
            duration = session.end_time - session.start_time
            summary = {
                "session_id": session_id,
                "duration_hours": duration.total_seconds() / 3600,
                "symbols_analyzed": len(session.symbols),
                "total_analyses": session.total_analyses,
                "successful_analyses": session.successful_analyses,
                "success_rate": (session.successful_analyses / session.total_analyses * 100) if session.total_analyses > 0 else 0,
                "recommendations_sent": session.recommendations_sent,
                "alerts_sent": session.alerts_sent,
                "start_time": session.start_time,
                "end_time": session.end_time
            }
            
            # 从活跃会话中移除
            del self.active_sessions[session_id]
            
            trading_logger.info(f"Trading session completed: {session_id}")
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to stop trading session {session_id}: {e}")
            raise TradingToolError(f"停止交易会话失败: {e}")
    
    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """获取会话状态"""
        session = self.active_sessions.get(session_id)
        if not session:
            return {"error": "Session not found"}
        
        current_time = datetime.now()
        duration = current_time - session.start_time
        
        return {
            "session_id": session_id,
            "status": session.status,
            "symbols": session.symbols,
            "start_time": session.start_time,
            "duration_hours": duration.total_seconds() / 3600,
            "total_analyses": session.total_analyses,
            "successful_analyses": session.successful_analyses,
            "recommendations_sent": session.recommendations_sent,
            "alerts_sent": session.alerts_sent
        }
    
    def get_portfolio_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """获取投资组合历史"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        recent_snapshots = [
            {
                "timestamp": snapshot.timestamp,
                "total_value": snapshot.total_value,
                "risk_score": snapshot.risk_score,
                "position_count": len(snapshot.positions)
            }
            for snapshot in self.portfolio_history
            if snapshot.timestamp >= cutoff_time
        ]
        
        return recent_snapshots