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
        
        # 启动推送配置 - 优化推送条件
        self.startup_config = {
            'enable_startup_push': True,
            'enable_position_analysis': True,  # 启用持仓分析
            'min_confidence_threshold': 50.0,  # 进一步降低最低置信度阈值
            'strong_signal_threshold': 65.0,   # 进一步降低强信号阈值
            'max_symbols_to_analyze': 50,      # 最大分析交易对数量 - 支持所有监控币种
            'analysis_timeout': 300,           # 分析超时时间(秒)
            'always_send_summary': True,       # 总是发送分析摘要
            'max_anomaly_alerts': 1,           # 最多发送1个异常警报
            'send_individual_signals': True,   # 发送单个币种信号
            'individual_signal_threshold': 60.0,  # 单个信号推送阈值
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
            
            # 2. 并发分析所有交易对（限制并发数量避免API限制）
            semaphore = asyncio.Semaphore(3)  # 最多3个并发请求
            
            async def analyze_symbol_with_semaphore(symbol: str) -> Dict[str, Any]:
                async with semaphore:
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