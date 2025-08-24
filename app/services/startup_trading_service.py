# -*- coding: utf-8 -*-
"""
启动交易决策服务
Startup Trading Decision Service - 应用启动时立即分析并推送交易决策
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import asyncio

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.unified_trading_service import UnifiedTradingService
from app.services.trading_notification_service import TradingNotificationService
from app.services.notification_service import NotificationService
from app.services.okx_service import OKXService
from app.services.position_analysis_service import PositionAnalysisService
from app.services.kronos_integrated_decision_service import get_kronos_integrated_service, KronosEnhancedDecision, KronosSignalStrength
from app.services.kronos_notification_service import get_kronos_notification_service
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class StartupTradingService:
    """启动交易决策服务类"""
    
    def __init__(self):
        self.unified_trading_service = UnifiedTradingService()
        self.trading_notification_service = TradingNotificationService()
        self.notification_service = NotificationService()
        self.exchange_service = OKXService()
        self.position_analysis_service = PositionAnalysisService()
        
        # 启动推送配置 - 优化推送条件，集成Kronos
        self.startup_config = {
            'enable_startup_push': True,
            'enable_position_analysis': True,  # 启用持仓分析
            'enable_kronos_integration': True,  # 启用Kronos集成分析
            'min_confidence_threshold': 45.0,  # 进一步降低最低置信度阈值
            'strong_signal_threshold': 55.0,   # 大幅降低强信号阈值
            'kronos_confidence_threshold': 0.5,  # 降低Kronos置信度阈值
            'kronos_strong_signal_threshold': 0.55,  # 进一步降低Kronos强信号阈值
            'max_symbols_to_analyze': 50,      # 最大分析交易对数量 - 支持所有监控币种
            'analysis_timeout': 300,           # 分析超时时间(秒)
            'always_send_summary': True,       # 总是发送分析摘要
            'max_anomaly_alerts': 1,           # 最多发送1个异常警报
            'send_individual_signals': True,   # 发送单个币种信号
            'individual_signal_threshold': 60.0,  # 单个信号推送阈值
            'prioritize_kronos_signals': True,  # 优先处理Kronos信号
        }
    
    async def perform_startup_analysis(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        执行启动时的交易分析
        
        Args:
            symbols: 要分析的交易对列表，如果为None则使用配置中的监控列表
            
        Returns:
            分析结果摘要
        """
        if not self.startup_config['enable_startup_push']:
            logger.info("启动推送已禁用，跳过分析")
            return {"status": "disabled", "message": "启动推送已禁用"}
        
        # 使用配置的监控交易对
        if symbols is None:
            symbols = settings.monitored_symbols[:self.startup_config['max_symbols_to_analyze']]
        
        logger.info(f"🚀 开始启动交易分析，分析 {len(symbols)} 个交易对")
        
        analysis_results = {
            "total_analyzed": 0,
            "successful_analyses": 0,
            "notifications_sent": 0,
            "strong_signals": [],
            "medium_signals": [],
            "errors": [],
            "summary": {},
            "position_analysis": None  # 持仓分析结果
        }
        
        try:
            # 1. 首先执行持仓分析（如果启用）
            if self.startup_config.get('enable_position_analysis', True):
                logger.info("💼 开始分析账户持仓...")
                try:
                    position_analysis = await self.position_analysis_service.analyze_account_positions()
                    analysis_results["position_analysis"] = position_analysis
                    
                    # 发送持仓分析通知
                    if position_analysis.get("status") != "error":
                        await self.position_analysis_service.send_position_analysis_notification(position_analysis)
                        analysis_results["notifications_sent"] += 1
                        logger.info("✅ 持仓分析完成并已推送")
                    else:
                        logger.warning(f"持仓分析失败: {position_analysis.get('message', 'unknown error')}")
                        
                except Exception as e:
                    logger.error(f"❌ 持仓分析失败: {e}")
                    analysis_results["errors"].append(f"持仓分析: {str(e)}")
            
            # 2. Kronos集成分析（如果启用）
            kronos_results = {}
            if self.startup_config.get('enable_kronos_integration', True):
                logger.info("🤖 开始Kronos集成决策分析...")
                try:
                    kronos_service = await get_kronos_integrated_service()
                    kronos_results = await kronos_service.batch_analyze_symbols(symbols, force_update=True)
                    
                    # 统计Kronos分析结果
                    kronos_successful = sum(1 for r in kronos_results.values() if r is not None)
                    logger.info(f"✅ Kronos集成分析完成: {kronos_successful}/{len(symbols)} 个成功")
                    
                    # 处理Kronos强信号
                    await self._process_kronos_signals(kronos_results, analysis_results)
                    
                except Exception as e:
                    logger.error(f"❌ Kronos集成分析失败: {e}")
                    analysis_results["errors"].append(f"Kronos集成分析: {str(e)}")
            
            # 3. 并发分析所有交易对（限制并发数量避免API限制）
            semaphore = asyncio.Semaphore(3)  # 最多3个并发请求
            
            async def analyze_symbol_with_semaphore(symbol: str) -> Dict[str, Any]:
                async with semaphore:
                    # 如果有Kronos结果，优先使用Kronos增强分析
                    if symbol in kronos_results and kronos_results[symbol] is not None:
                        return await self._analyze_symbol_with_kronos(symbol, kronos_results[symbol])
                    else:
                        return await self._analyze_single_symbol(symbol)
            
            # 创建分析任务
            tasks = [analyze_symbol_with_semaphore(symbol) for symbol in symbols]
            
            # 等待所有分析完成，设置超时
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=self.startup_config['analysis_timeout']
                )
            except asyncio.TimeoutError:
                logger.warning(f"启动分析超时 ({self.startup_config['analysis_timeout']}秒)")
                results = [{"error": "分析超时"} for _ in symbols]
            
            # 处理分析结果
            for i, result in enumerate(results):
                symbol = symbols[i] if i < len(symbols) else f"unknown_{i}"
                analysis_results["total_analyzed"] += 1
                
                if isinstance(result, Exception):
                    error_msg = f"{symbol}: {str(result)}"
                    analysis_results["errors"].append(error_msg)
                    logger.warning(f"❌ {error_msg}")
                    continue
                
                if "error" in result:
                    analysis_results["errors"].append(f"{symbol}: {result['error']}")
                    continue
                
                analysis_results["successful_analyses"] += 1
                
                # 分类信号强度和推送逻辑
                confidence = result.get("confidence", 0)
                action = result.get("action", "hold")
                
                # 强信号处理
                if confidence >= self.startup_config['strong_signal_threshold']:
                    analysis_results["strong_signals"].append(result)
                    # 发送强信号通知
                    if await self._send_trading_notification(result):
                        analysis_results["notifications_sent"] += 1
                        logger.info(f"📢 已发送强信号通知: {result['symbol']} {action} ({confidence:.1f}%)")
                
                # 中等信号处理
                elif confidence >= self.startup_config['min_confidence_threshold']:
                    analysis_results["medium_signals"].append(result)
                    
                    # 更宽松的推送条件
                    should_send = False
                    
                    # 1. 明确的买卖信号
                    if action in ['buy', 'sell', 'strong_buy', 'strong_sell']:
                        should_send = True
                    
                    # 2. 高置信度的持有信号
                    elif action == 'hold' and confidence >= 75:
                        should_send = True
                    
                    # 3. 等待信号但置信度较高
                    elif action == 'wait' and confidence >= self.startup_config.get('individual_signal_threshold', 60):
                        should_send = True
                    
                    if should_send and await self._send_trading_notification(result):
                        analysis_results["notifications_sent"] += 1
                        logger.info(f"📢 已发送中等信号通知: {result['symbol']} {action} ({confidence:.1f}%)")
                
                # 低置信度但有明确信号
                else:
                    # 即使置信度不高，如果有明确的买卖信号也推送
                    if action in ['buy', 'sell', 'strong_buy', 'strong_sell'] and confidence > 40:
                        analysis_results["medium_signals"].append(result)
                        if await self._send_trading_notification(result):
                            analysis_results["notifications_sent"] += 1
                            logger.info(f"📢 已发送低置信度信号通知: {result['symbol']} {action} ({confidence:.1f}%)")
            
            # 生成摘要
            analysis_results["summary"] = self._generate_analysis_summary(analysis_results)
            
            # 总是发送整体摘要通知（如果启用）
            if (self.startup_config.get('always_send_summary', False) or 
                analysis_results["notifications_sent"] > 0 or 
                analysis_results["strong_signals"]):
                await self._send_summary_notification(analysis_results)
            
            logger.info(f"✅ 启动分析完成: {analysis_results['successful_analyses']}/{analysis_results['total_analyzed']} 成功, {analysis_results['notifications_sent']} 条通知已发送")
            
            return analysis_results
            
        except Exception as e:
            logger.error(f"❌ 启动分析失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "total_analyzed": analysis_results["total_analyzed"],
                "successful_analyses": analysis_results["successful_analyses"]
            }
    
    async def _analyze_single_symbol(self, symbol: str) -> Dict[str, Any]:
        """
        分析单个交易对 - 使用统一交易服务
        
        Args:
            symbol: 交易对符号
            
        Returns:
            分析结果
        """
        try:
            logger.info(f"🔍 统一分析 {symbol}...")
            
            # 使用统一交易服务获取综合建议
            recommendation = await self.unified_trading_service.get_unified_recommendation(symbol)
            
            result = {
                "symbol": symbol,
                "action": recommendation.final_action.value,
                "confidence": recommendation.confidence,
                "current_price": recommendation.current_price,
                "position_size_percent": recommendation.position_size_percent,
                "leverage": recommendation.leverage,
                "risk_level": recommendation.risk_level.value,
                "entry_timing": recommendation.entry_timing,
                "reasoning": recommendation.reasoning,
                "stop_loss_price": recommendation.dynamic_stop_loss,
                "take_profit_price": recommendation.dynamic_take_profit,
                "risk_reward_ratio": recommendation.risk_reward_ratio,
                "traditional_signal": recommendation.traditional_signal,
                "ml_signal": recommendation.ml_signal,
                "market_regime": recommendation.market_regime.value,
                "volatility_level": recommendation.volatility_level,
                "key_factors": recommendation.key_factors,
                "timestamp": recommendation.timestamp
            }
            
            logger.info(f"📊 {symbol}: {recommendation.final_action.value} (置信度: {recommendation.confidence:.1f}%, 风险: {recommendation.risk_level.value})")
            logger.info(f"   传统: {recommendation.traditional_signal}, ML: {recommendation.ml_signal}, 市场: {recommendation.market_regime.value}")
            
            return result
            
        except Exception as e:
            logger.warning(f"❌ 统一分析 {symbol} 失败: {e}")
            return {"symbol": symbol, "error": str(e)}
    
    async def _send_trading_notification(self, analysis_result: Dict[str, Any]) -> bool:
        """
        发送统一交易通知
        
        Args:
            analysis_result: 分析结果
            
        Returns:
            是否发送成功
        """
        try:
            # 构建统一通知数据 - 包含完整的技术分析信息
            notification_data = {
                'symbol': analysis_result["symbol"],
                'action': analysis_result["action"],
                'confidence': analysis_result["confidence"],
                'reasoning': analysis_result["reasoning"],
                'current_price': analysis_result.get("current_price", 0),
                'stop_loss': analysis_result.get("stop_loss_price", 0),
                'take_profit': analysis_result.get("take_profit_price", 0),
                'position_size': analysis_result.get("position_size_percent", 0),
                'risk_level': analysis_result.get("risk_level", "中等风险"),
                'traditional_signal': analysis_result.get("traditional_signal", "未知"),
                'traditional_confidence': analysis_result.get("traditional_confidence", 0),
                'ml_signal': analysis_result.get("ml_signal", "未知"),
                'ml_confidence': analysis_result.get("ml_confidence", 0),
                'market_regime': analysis_result.get("market_regime", "未知"),
                'volatility_level': analysis_result.get("volatility_level", "中等"),
                'key_factors': analysis_result.get("key_factors", []),
                'entry_timing': analysis_result.get("entry_timing", "立即"),
                'leverage': analysis_result.get("leverage", 1.0),
                'risk_reward_ratio': analysis_result.get("risk_reward_ratio", 0)
            }
            
            # 使用统一交易通知服务
            success = await self.trading_notification_service.send_unified_trading_notification(notification_data)
            
            if success:
                logger.info(f"📢 已发送 {analysis_result['symbol']} 统一交易通知")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 发送 {analysis_result.get('symbol', 'unknown')} 通知失败: {e}")
            return False
    
    async def _send_summary_notification(self, analysis_results: Dict[str, Any]) -> None:
        """
        发送分析摘要通知
        
        Args:
            analysis_results: 分析结果
        """
        try:
            summary = analysis_results["summary"]
            
            title = f"🎯 启动交易分析摘要 ({datetime.now().strftime('%H:%M')})"
            
            message_parts = [
                f"📊 分析完成: {analysis_results['successful_analyses']}/{analysis_results['total_analyzed']} 个交易对",
                f"📢 通知发送: {analysis_results['notifications_sent']} 条",
                "",
                "🔥 强信号交易对:",
            ]
            
            # 强信号列表
            for signal in analysis_results["strong_signals"][:5]:  # 最多显示5个
                action_text = {
                    'strong_buy': '强烈买入',
                    'buy': '买入', 
                    'sell': '卖出',
                    'strong_sell': '强烈卖出'
                }.get(signal["action"], signal["action"])
                
                message_parts.append(
                    f"  • {signal['symbol']}: {action_text} ({signal['confidence']:.1f}%)"
                )
            
            if not analysis_results["strong_signals"]:
                message_parts.append("  暂无强信号")
            
            # 中等信号统计
            if analysis_results["medium_signals"]:
                message_parts.extend([
                    "",
                    f"📈 中等信号: {len(analysis_results['medium_signals'])} 个",
                ])
            
            # 错误统计
            if analysis_results["errors"]:
                message_parts.extend([
                    "",
                    f"⚠️ 分析错误: {len(analysis_results['errors'])} 个"
                ])
            
            # 市场概况和具体建议
            message_parts.extend([
                "",
                "📋 市场概况:",
                f"  • 🟢 建议买入: {summary.get('bullish_count', 0)} 个",
                f"  • 🔴 建议卖出: {summary.get('bearish_count', 0)} 个", 
                f"  • 🟡 建议持有/等待: {summary.get('wait_count', 0)} 个",
                f"  • 📊 平均置信度: {summary.get('avg_confidence', 0):.1f}%"
            ])
            
            # 添加具体的买入/卖出建议
            buy_signals = [s for s in analysis_results["strong_signals"] + analysis_results["medium_signals"] 
                          if s["action"] in ['buy', 'strong_buy']]
            sell_signals = [s for s in analysis_results["strong_signals"] + analysis_results["medium_signals"] 
                           if s["action"] in ['sell', 'strong_sell']]
            
            if buy_signals:
                message_parts.extend([
                    "",
                    "🟢 建议买入币种:"
                ])
                for signal in buy_signals[:5]:  # 最多显示5个
                    action_text = "强烈买入" if signal["action"] == "strong_buy" else "买入"
                    message_parts.append(f"  • {signal['symbol']}: {action_text} ({signal['confidence']:.1f}%)")
            
            if sell_signals:
                message_parts.extend([
                    "",
                    "🔴 建议卖出币种:"
                ])
                for signal in sell_signals[:5]:  # 最多显示5个
                    action_text = "强烈卖出" if signal["action"] == "strong_sell" else "卖出"
                    message_parts.append(f"  • {signal['symbol']}: {action_text} ({signal['confidence']:.1f}%)")
            
            # 持有建议
            hold_signals = [s for s in analysis_results["strong_signals"] + analysis_results["medium_signals"] 
                           if s["action"] in ['hold', 'wait']]
            if hold_signals and len(hold_signals) <= 3:  # 只有少量持有信号时才显示
                message_parts.extend([
                    "",
                    "🟡 建议持有/等待:"
                ])
                for signal in hold_signals:
                    message_parts.append(f"  • {signal['symbol']}: 持有观望 ({signal['confidence']:.1f}%)")
            
            message = "\n".join(message_parts)
            
            success_results = await self.notification_service.send_notification(
                message=f"{title}\n\n{message}",
                priority="normal"
            )
            success = any(success_results.values()) if success_results else False
            
            logger.info("📢 已发送启动分析摘要通知")
            
        except Exception as e:
            logger.error(f"❌ 发送摘要通知失败: {e}")
    
    def _generate_analysis_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成分析摘要
        
        Args:
            results: 分析结果
            
        Returns:
            摘要数据
        """
        all_signals = results["strong_signals"] + results["medium_signals"]
        
        if not all_signals:
            return {
                "total_signals": 0,
                "avg_confidence": 0,
                "bullish_count": 0,
                "bearish_count": 0,
                "wait_count": 0
            }
        
        # 统计各类信号
        bullish_actions = ['buy', 'strong_buy']
        bearish_actions = ['sell', 'strong_sell']
        wait_actions = ['hold', 'wait']
        
        bullish_count = sum(1 for s in all_signals if s["action"] in bullish_actions)
        bearish_count = sum(1 for s in all_signals if s["action"] in bearish_actions)
        wait_count = sum(1 for s in all_signals if s["action"] in wait_actions)
        
        # 计算平均置信度
        total_confidence = sum(s["confidence"] for s in all_signals)
        avg_confidence = total_confidence / len(all_signals) if all_signals else 0
        
        return {
            "total_signals": len(all_signals),
            "avg_confidence": avg_confidence,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "wait_count": wait_count,
            "strong_signals_count": len(results["strong_signals"]),
            "medium_signals_count": len(results["medium_signals"])
        }
    
    async def get_quick_market_overview(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        获取快速市场概览（不发送通知）
        
        Args:
            symbols: 要分析的交易对列表
            
        Returns:
            市场概览数据
        """
        if symbols is None:
            symbols = settings.monitored_symbols  # 分析所有监控的交易对
        
        logger.info(f"📊 获取市场概览: {len(symbols)} 个交易对")
        
        overview = {
            "timestamp": datetime.now(),
            "symbols_analyzed": [],
            "market_sentiment": "neutral",
            "avg_confidence": 0,
            "top_opportunities": [],
            "risk_alerts": []
        }
        
        try:
            # 快速并发分析
            semaphore = asyncio.Semaphore(5)
            
            async def quick_analyze(symbol: str) -> Dict[str, Any]:
                async with semaphore:
                    try:
                        # 只获取基本信号，不做完整分析
                        async with self.exchange_service as exchange:
                            signals = await self.trading_service._get_market_signals(symbol, exchange)
                            current_price = await exchange.get_current_price(symbol)
                        
                        return {
                            "symbol": symbol,
                            "trend": signals.get("trend", "neutral"),
                            "confidence": signals.get("confidence", 50),
                            "volatility": signals.get("volatility", "medium"),
                            "current_price": current_price,
                            "volume_anomaly": signals.get("volume_anomaly", False)
                        }
                    except Exception as e:
                        return {"symbol": symbol, "error": str(e)}
            
            # 执行快速分析
            tasks = [quick_analyze(symbol) for symbol in symbols]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            valid_results = []
            for result in results:
                if isinstance(result, dict) and "error" not in result:
                    valid_results.append(result)
                    overview["symbols_analyzed"].append(result["symbol"])
            
            if valid_results:
                # 计算市场情绪
                bullish_count = sum(1 for r in valid_results if r["trend"] == "bullish")
                bearish_count = sum(1 for r in valid_results if r["trend"] == "bearish")
                
                if bullish_count > bearish_count * 1.5:
                    overview["market_sentiment"] = "bullish"
                elif bearish_count > bullish_count * 1.5:
                    overview["market_sentiment"] = "bearish"
                
                # 平均置信度
                overview["avg_confidence"] = sum(r["confidence"] for r in valid_results) / len(valid_results)
                
                # 顶级机会（高置信度 + 明确趋势）
                opportunities = [
                    r for r in valid_results 
                    if r["confidence"] > 70 and r["trend"] in ["bullish", "bearish"]
                ]
                overview["top_opportunities"] = sorted(
                    opportunities, 
                    key=lambda x: x["confidence"], 
                    reverse=True
                )[:3]
                
                # 风险警报（高波动 + 成交量异常）
                risk_alerts = [
                    r for r in valid_results
                    if r["volatility"] == "high" or r["volume_anomaly"]
                ]
                overview["risk_alerts"] = risk_alerts[:3]
            
            logger.info(f"📊 市场概览完成: 情绪={overview['market_sentiment']}, 平均置信度={overview['avg_confidence']:.1f}%")
            
            return overview
            
        except Exception as e:
            logger.error(f"❌ 获取市场概览失败: {e}")
            overview["error"] = str(e)
            return overview
    
    async def _process_kronos_signals(self, kronos_results: Dict[str, Any], analysis_results: Dict[str, Any]) -> None:
        """
        处理Kronos信号并发送通知
        
        Args:
            kronos_results: Kronos分析结果
            analysis_results: 总体分析结果
        """
        try:
            kronos_strong_signals = []
            kronos_medium_signals = []
            
            for symbol, decision in kronos_results.items():
                if decision is None:
                    continue
                
                # 检查是否为强Kronos信号
                is_strong_signal = (
                    decision.kronos_confidence >= self.startup_config['kronos_strong_signal_threshold'] and
                    decision.kronos_signal_strength in [KronosSignalStrength.STRONG, KronosSignalStrength.VERY_STRONG]
                )
                
                # 检查是否为中等Kronos信号
                is_medium_signal = (
                    decision.kronos_confidence >= self.startup_config['kronos_confidence_threshold'] and
                    decision.final_confidence >= 0.6
                )
                
                # 构建Kronos信号数据
                kronos_signal_data = {
                    "symbol": symbol,
                    "action": decision.final_action,
                    "confidence": decision.final_confidence * 100,  # 转换为百分比
                    "kronos_confidence": decision.kronos_confidence,
                    "kronos_signal_strength": decision.kronos_signal_strength.value,
                    "signal_confluence": decision.signal_confluence,
                    "technical_signal": decision.technical_signal,
                    "position_recommendation": decision.position_recommendation.value,
                    "position_size": decision.position_size,
                    "market_regime": decision.market_regime.value,
                    "reasoning": decision.reasoning,
                    "current_price": decision.entry_price,
                    "stop_loss_price": decision.stop_loss,
                    "take_profit_price": decision.take_profit,
                    "risk_level": decision.position_risk.value,
                    "timestamp": decision.timestamp,
                    "source": "kronos_integrated"
                }
                
                if is_strong_signal:
                    kronos_strong_signals.append(kronos_signal_data)
                    analysis_results["strong_signals"].append(kronos_signal_data)
                    
                    # 使用专门的Kronos通知服务发送强信号通知
                    kronos_notification_service = await get_kronos_notification_service()
                    if await kronos_notification_service.send_kronos_signal_notification(decision, "strong"):
                        analysis_results["notifications_sent"] += 1
                        logger.info(f"🚀 已发送强Kronos信号: {symbol} {decision.final_action} (Kronos: {decision.kronos_confidence:.2f})")
                
                elif is_medium_signal:
                    kronos_medium_signals.append(kronos_signal_data)
                    analysis_results["medium_signals"].append(kronos_signal_data)
                    
                    # 使用专门的Kronos通知服务发送中等信号通知
                    kronos_notification_service = await get_kronos_notification_service()
                    if await kronos_notification_service.send_kronos_signal_notification(decision, "medium"):
                        analysis_results["notifications_sent"] += 1
                        logger.info(f"📊 已发送中等Kronos信号: {symbol} {decision.final_action} (置信度: {decision.final_confidence:.2f})")
            
            # 记录Kronos信号统计
            logger.info(f"🤖 Kronos信号统计: 强信号 {len(kronos_strong_signals)} 个, 中等信号 {len(kronos_medium_signals)} 个")
            
            # 如果有多个强Kronos信号，发送汇总通知
            if len(kronos_strong_signals) >= 2:
                kronos_notification_service = await get_kronos_notification_service()
                strong_decisions = [decision for symbol, decision in kronos_results.items() 
                                  if decision and decision.kronos_confidence >= self.startup_config['kronos_strong_signal_threshold']]
                if await kronos_notification_service.send_batch_kronos_notification(strong_decisions, "strong_signals"):
                    analysis_results["notifications_sent"] += 1
                
        except Exception as e:
            logger.error(f"❌ 处理Kronos信号失败: {e}")
            analysis_results["errors"].append(f"Kronos信号处理: {str(e)}")
    
    async def _analyze_symbol_with_kronos(self, symbol: str, kronos_decision: KronosEnhancedDecision) -> Dict[str, Any]:
        """
        基于Kronos决策分析单个交易对
        
        Args:
            symbol: 交易对符号
            kronos_decision: Kronos集成决策结果
            
        Returns:
            增强的分析结果
        """
        try:
            logger.info(f"🤖 Kronos增强分析 {symbol}...")
            
            # 基于Kronos决策构建分析结果
            result = {
                "symbol": symbol,
                "action": kronos_decision.final_action,
                "confidence": kronos_decision.final_confidence * 100,  # 转换为百分比
                "current_price": kronos_decision.entry_price,
                "position_size_percent": kronos_decision.position_size * 100,  # 转换为百分比
                "leverage": 1.0,  # 默认无杠杆
                "risk_level": kronos_decision.position_risk.value,
                "entry_timing": "立即" if kronos_decision.final_confidence >= 0.8 else "谨慎",
                "reasoning": kronos_decision.reasoning,
                "stop_loss_price": kronos_decision.stop_loss,
                "take_profit_price": kronos_decision.take_profit,
                "risk_reward_ratio": self._calculate_risk_reward_ratio(
                    kronos_decision.entry_price,
                    kronos_decision.stop_loss,
                    kronos_decision.take_profit
                ),
                "traditional_signal": kronos_decision.technical_signal,
                "traditional_confidence": kronos_decision.technical_confidence * 100,
                "ml_signal": "Kronos AI",
                "ml_confidence": kronos_decision.kronos_confidence * 100,
                "market_regime": kronos_decision.market_regime.value,
                "volatility_level": "中等",  # 默认值
                "key_factors": [
                    f"Kronos置信度: {kronos_decision.kronos_confidence:.2f}",
                    f"信号强度: {kronos_decision.kronos_signal_strength.value}",
                    f"信号一致性: {kronos_decision.signal_confluence:.2f}",
                    f"持仓建议: {kronos_decision.position_recommendation.value}"
                ],
                "timestamp": kronos_decision.timestamp,
                "source": "kronos_integrated",
                # Kronos特有字段
                "kronos_confidence": kronos_decision.kronos_confidence,
                "kronos_signal_strength": kronos_decision.kronos_signal_strength.value,
                "signal_confluence": kronos_decision.signal_confluence,
                "position_recommendation": kronos_decision.position_recommendation.value
            }
            
            logger.info(f"🤖 {symbol}: {kronos_decision.final_action} (Kronos: {kronos_decision.kronos_confidence:.2f}, 综合: {kronos_decision.final_confidence:.2f})")
            logger.info(f"   信号强度: {kronos_decision.kronos_signal_strength.value}, 一致性: {kronos_decision.signal_confluence:.2f}")
            
            return result
            
        except Exception as e:
            logger.warning(f"❌ Kronos增强分析 {symbol} 失败: {e}")
            return {"symbol": symbol, "error": str(e)}
    
    def _calculate_risk_reward_ratio(self, entry_price: Optional[float], stop_loss: Optional[float], take_profit: Optional[float]) -> float:
        """计算风险收益比"""
        if not all([entry_price, stop_loss, take_profit]):
            return 1.0
        
        try:
            risk = abs(entry_price - stop_loss)
            reward = abs(take_profit - entry_price)
            return reward / risk if risk > 0 else 1.0
        except:
            return 1.0
    
    async def _send_kronos_notification(self, signal_data: Dict[str, Any], signal_type: str) -> bool:
        """
        发送Kronos信号通知
        
        Args:
            signal_data: 信号数据
            signal_type: 信号类型 ("strong" 或 "medium")
            
        Returns:
            是否发送成功
        """
        try:
            symbol = signal_data["symbol"]
            action = signal_data["action"]
            kronos_confidence = signal_data["kronos_confidence"]
            signal_strength = signal_data["kronos_signal_strength"]
            confluence = signal_data["signal_confluence"]
            
            # 构建Kronos专用通知消息
            if signal_type == "strong":
                title = f"🚀 强Kronos信号: {symbol}"
                emoji = "🔥"
            else:
                title = f"📊 Kronos信号: {symbol}"
                emoji = "🤖"
            
            message = f"""
{emoji} **{title}**

📈 **交易行动**: {action}
🤖 **Kronos置信度**: {kronos_confidence:.2f}
💪 **信号强度**: {signal_strength}
🤝 **信号一致性**: {confluence:.2f}
💼 **持仓建议**: {signal_data.get('position_recommendation', 'N/A')}
🌊 **市场状态**: {signal_data.get('market_regime', 'N/A')}

💰 **当前价格**: ${signal_data.get('current_price', 0):.2f}
🛑 **止损价格**: ${signal_data.get('stop_loss_price', 0):.2f}
🎯 **止盈价格**: ${signal_data.get('take_profit_price', 0):.2f}
📊 **建议仓位**: {signal_data.get('position_size', 0):.1%}

💡 **决策依据**: {signal_data.get('reasoning', 'N/A')}

⏰ 时间: {signal_data.get('timestamp', datetime.now()).strftime('%H:%M:%S')}
"""
            
            # 发送通知
            await self.notification_service.send_notification(
                title=title,
                message=message,
                notification_type="kronos_signal",
                priority="high" if signal_type == "strong" else "medium"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 发送Kronos通知失败: {e}")
            return False
    
    async def _send_kronos_summary_notification(self, strong_signals: List[Dict[str, Any]]) -> bool:
        """
        发送Kronos强信号汇总通知
        
        Args:
            strong_signals: 强信号列表
            
        Returns:
            是否发送成功
        """
        try:
            if not strong_signals:
                return False
            
            title = f"🔥 发现 {len(strong_signals)} 个强Kronos信号"
            
            message = f"🤖 **Kronos AI集成分析汇总**\n\n"
            
            for i, signal in enumerate(strong_signals[:5], 1):  # 最多显示5个
                symbol = signal["symbol"]
                action = signal["action"]
                kronos_conf = signal["kronos_confidence"]
                strength = signal["kronos_signal_strength"]
                
                message += f"{i}. **{symbol}**: {action}\n"
                message += f"   🤖 Kronos: {kronos_conf:.2f} | 💪 强度: {strength}\n\n"
            
            if len(strong_signals) > 5:
                message += f"... 还有 {len(strong_signals) - 5} 个信号\n\n"
            
            message += f"⏰ 分析时间: {datetime.now().strftime('%H:%M:%S')}\n"
            message += f"💡 建议优先关注Kronos置信度最高的信号"
            
            await self.notification_service.send_notification(
                title=title,
                message=message,
                notification_type="kronos_summary",
                priority="high"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 发送Kronos汇总通知失败: {e}")
            return False