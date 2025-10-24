# -*- coding: utf-8 -*-
"""
调度服务
Scheduler service for background tasks
"""

import asyncio
from typing import Dict, Any
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.core.logging import get_logger, monitor_logger
from app.core.config import get_settings
from app.services.exchanges.exchange_service_manager import get_exchange_service
from app.services.analysis.grid_trading_service import get_grid_trading_service

logger = get_logger(__name__)
settings = get_settings()


class SchedulerService:
    """调度服务类"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)
        self.running = False
        self.jobs = {}
        
        # 导入服务（延迟导入避免循环依赖）
        self._monitor_service = None
        self._trend_service = None
        self._position_analysis_service = None
    
    def _get_monitor_service(self):
        """获取监控服务实例"""
        if self._monitor_service is None:
            from app.services.core_monitoring_service import CoreMonitoringService
            self._monitor_service = CoreMonitoringService()
        return self._monitor_service
    
    def _get_trend_service(self):
        """获取趋势分析服务实例"""
        if self._trend_service is None:
            from app.services.analysis.trend_analysis_service import TrendAnalysisService
            # 使用配置的交易所，而不是硬编码
            self._trend_service = TrendAnalysisService()
        return self._trend_service
    
    def _get_ml_service(self):
        """获取机器学习服务实例"""
        if not hasattr(self, '_ml_service') or self._ml_service is None:
            from app.services.ml.ml_enhanced_service import MLEnhancedService
            # 使用配置的交易所，而不是硬编码
            self._ml_service = MLEnhancedService()
        return self._ml_service
    
    async def _get_core_notification_service(self):
        """获取核心通知服务实例"""
        if not hasattr(self, '_core_notification_service') or self._core_notification_service is None:
            from app.services.notification.core_notification_service import get_core_notification_service
            self._core_notification_service = await get_core_notification_service()
        return self._core_notification_service
    
    def _get_position_analysis_service(self):
        """获取持仓分析服务实例"""
        if self._position_analysis_service is None:
            from app.services.analysis.position_analysis_service import PositionAnalysisService
            self._position_analysis_service = PositionAnalysisService()
        return self._position_analysis_service
    
    async def start(self):
        """启动调度服务"""
        try:
            # 启动调度器
            self.scheduler.start()
            self.running = True
            
            # 添加定时任务
            await self._setup_scheduled_jobs()
            
            # 启动时更新一次交易对列表（增加错误处理）
            try:
                await self._update_trading_pairs_on_startup()
            except Exception as e:
                logger.warning(f"⚠️ 启动时更新交易对列表失败: {e}")
            
            logger.info("✅ 调度服务启动成功")
            
        except Exception as e:
            logger.error(f"❌ 调度服务启动失败: {e}")
            raise
    
    async def stop(self):
        """停止调度服务"""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            
            self.running = False
            self.jobs.clear()
            
            logger.info("Scheduler service stopped")
            
        except Exception as e:
            logger.error(f"Error stopping scheduler service: {e}")
    
    def is_running(self) -> bool:
        """检查调度器是否运行中"""
        return self.running and self.scheduler.running
    
    def _convert_confidence_to_percent(self, confidence: float) -> float:
        """统一的置信度转换方法 - 修复重复乘100问题"""
        if confidence <= 1:
            return confidence * 100  # 0.85 -> 85%
        else:
            return confidence  # 已经是百分比格式
    
    async def _setup_scheduled_jobs(self):
        """设置定时任务"""
        try:
            # 🔄 核心监控任务组 - 高频监控
            
            # 持仓量监控 - 每30分钟执行一次 (降低频率，减少噪音)
            self.scheduler.add_job(
                self._open_interest_job,
                trigger=IntervalTrigger(minutes=30),
                id="open_interest_monitor", 
                name="持仓量变化监控",
                max_instances=1
            )
            
            # 交易量异常监控 - 每60分钟执行一次 (降低频率，目前功能不完整)
            # 注意：当前交易量异常监控没有独立的通知功能，主要用于数据收集
            self.scheduler.add_job(
                self._volume_anomaly_job,
                trigger=IntervalTrigger(minutes=60),
                id="volume_anomaly_monitor",
                name="交易量异常监控 (数据收集)",
                max_instances=1
            )
            
            
            # 综合监控报告 - 每天早上9点执行
            self.scheduler.add_job(
                self._daily_report_job,
                trigger=CronTrigger(hour=9, minute=0),
                id="daily_report",
                name="每日监控报告",
                max_instances=1
            )
            
            # 健康检查 - 每30分钟执行一次
            self.scheduler.add_job(
                self._health_check_job,
                trigger=IntervalTrigger(minutes=30),
                id="health_check",
                name="系统健康检查",
                max_instances=1
            )
            
            # 🎯 动态权重监控 - 每60分钟执行一次
            self.scheduler.add_job(
                self._dynamic_weight_monitoring_job,
                trigger=IntervalTrigger(minutes=60),
                id="dynamic_weight_monitoring",
                name="动态权重监控",
                max_instances=1
            )
            
            # 持仓分析已由Kronos持仓分析服务接管
            
            # 📊 市场机会分析任务组 - 低频深度分析
            
            # 网格机会分析 - 每60分钟执行一次 (震荡市策略)
            self.scheduler.add_job(
                self._grid_opportunities_job,
                trigger=IntervalTrigger(minutes=60),
                id="grid_opportunities",
                name="网格交易机会分析 (震荡市策略)",
                max_instances=1
            )
            
            # 网格交易服务分析 - 每60分钟执行一次
            self.scheduler.add_job(
                self._grid_trading_service_job,
                trigger=IntervalTrigger(minutes=60),
                id="grid_trading_service",
                name="网格交易服务分析",
                max_instances=1
            )
            
            # 综合市场机会分析 - 每60分钟执行一次 (宏观分析)
            self.scheduler.add_job(
                self._comprehensive_market_analysis_job,
                trigger=IntervalTrigger(minutes=60),
                id="comprehensive_market_analysis",
                name="综合市场机会分析 (宏观分析)",
                max_instances=1
            )
            
            # 🤖 ML增强分析任务组
            
            # ML预测信号 - 每30分钟执行一次 (辅助验证Kronos信号)
            self.scheduler.add_job(
                self._ml_prediction_job,
                trigger=IntervalTrigger(minutes=30),
                id="ml_prediction",
                name="ML预测信号分析 (辅助验证)",
                max_instances=1
            )
            
            # 🎯 核心币种推送任务 - 每30分钟执行一次
            self.scheduler.add_job(
                self._core_symbols_push_job,
                trigger=IntervalTrigger(minutes=30),
                id="core_symbols_push",
                name="核心币种总体推送",
                max_instances=1
            )
            logger.info("✅ 核心币种推送任务已启用 - 每30分钟执行一次")
            
            # 🔄 ML模型重训练 - 每天凌晨2点执行
            self.scheduler.add_job(
                self._ml_model_retrain_job,
                trigger=CronTrigger(hour=2, minute=0),
                id="ml_model_retrain",
                name="ML模型重训练",
                max_instances=1
            )
            
            # 交易对列表更新 - 每天凌晨1点执行
            self.scheduler.add_job(
                self._update_trading_pairs_job,
                trigger=CronTrigger(hour=1, minute=0),
                id="update_trading_pairs",
                name="更新交易对列表",
                max_instances=1
            )
            
            logger.info("✅ 定时任务设置完成")
            
        except Exception as e:
            logger.error(f"❌ 定时任务设置失败: {e}")
            raise
    
    async def _update_trading_pairs_on_startup(self):
        """启动时更新交易对列表"""
        try:
            logger.info("🔄 启动时更新交易对列表...")
            
            # 获取交易所服务
            exchange_service = await get_exchange_service()
            
            # 验证主要交易对
            if hasattr(exchange_service, '_validate_symbols'):
                valid_symbols = await exchange_service._validate_symbols(exchange_service.major_symbols)
                if valid_symbols != exchange_service.major_symbols:
                    logger.info(f"📝 更新主要交易对列表: {len(valid_symbols)} 个有效交易对")
                    exchange_service.major_symbols = valid_symbols
            
            logger.info("✅ 交易对列表更新完成")
            
        except Exception as e:
            logger.error(f"❌ 更新交易对列表失败: {e}")
            # 不抛出异常，允许服务继续启动
    
    async def _funding_rate_job(self):
        """资金费率监控任务 - 已禁用，由NegativeFundingMonitorService接管"""
        pass
    
    async def _open_interest_job(self):
        """持仓量监控任务 - 增强版，集成趋势确认"""
        try:
            monitor_logger.info("📊 执行持仓量变动监控 (增强版)")
            
            # 使用新的持仓量分析服务
            from app.services.analysis.open_interest_analysis_service import get_oi_analysis_service
            oi_service = get_oi_analysis_service()
            
            # 监控核心币种
            core_symbols = settings.kronos_config.get('target_symbols', [])
            if not core_symbols:
                core_symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
            
            # 批量分析持仓量
            analysis_summary = await oi_service.get_analysis_summary(core_symbols)
            
            monitor_logger.info(
                f"✅ 持仓量变动监控完成: 分析 {analysis_summary.get('total_symbols', 0)} 个币种, "
                f"发现 {analysis_summary.get('significant_changes', 0)} 个显著变化 "
                f"(看涨确认: {analysis_summary.get('bullish_confirmations', 0)}, "
                f"看跌确认: {analysis_summary.get('bearish_confirmations', 0)})"
            )
            
            # 记录前3个变化
            top_changes = analysis_summary.get('top_changes', [])[:3]
            for i, change in enumerate(top_changes, 1):
                symbol_name = change['symbol'].replace('-USDT-SWAP', '')
                direction = "📈" if change['oi_change_percent'] > 0 else "📉"
                monitor_logger.info(
                    f"   {i}. {direction} {symbol_name}: 持仓量 {change['oi_change_percent']:+.2f}% "
                    f"价格: {change['price_change_24h']:+.2f}% "
                    f"信号: {change['trend_signal']}"
                )
            
            # 如果有显著变化，发送通知
            if analysis_summary.get('significant_changes', 0) > 0:
                try:
                    # 使用原有的监控服务发送通知
                    monitor_service = self._get_monitor_service()
                    symbols = [change['symbol'] for change in top_changes]
                    await monitor_service.monitor_open_interest(symbols, notify=True)
                except Exception as e:
                    logger.warning(f"发送持仓量变化通知失败: {e}")
            
        except Exception as e:
            logger.error(f"❌ 持仓量变动监控失败: {e}")
    
    async def _volume_anomaly_job(self):
        """交易量异常监控任务 - 增强版，集成到交易决策中"""
        try:
            monitor_logger.info("🔊 执行交易量异常监控 (增强版)")
            
            # 使用新的交易量异常服务
            from app.services.volume_anomaly_service import get_volume_anomaly_service
            volume_service = get_volume_anomaly_service()
            
            # 监控核心币种
            core_symbols = settings.kronos_config.get('target_symbols', [])
            if not core_symbols:
                core_symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
            
            # 批量检测异常
            anomaly_summary = await volume_service.get_anomaly_summary(core_symbols)
            
            monitor_logger.info(
                f"✅ 交易量异常监控完成: 检测 {anomaly_summary.get('total_symbols', 0)} 个币种, "
                f"发现 {anomaly_summary.get('anomalies_found', 0)} 个异常 "
                f"(看涨: {anomaly_summary.get('bullish_anomalies', 0)}, "
                f"看跌: {anomaly_summary.get('bearish_anomalies', 0)})"
            )
            
            # 记录前3个异常
            top_anomalies = anomaly_summary.get('top_anomalies', [])[:3]
            for i, anomaly in enumerate(top_anomalies, 1):
                symbol_name = anomaly['symbol'].replace('-USDT-SWAP', '')
                monitor_logger.info(
                    f"   {i}. 🔊 {symbol_name}: {anomaly['volume_ratio']:.1f}倍成交量 "
                    f"价格: {anomaly['price_change_24h']:+.2f}% "
                    f"级别: {anomaly['anomaly_level']}"
                )
            
        except Exception as e:
            logger.error(f"❌ 交易量异常监控失败: {e}")
    
    async def _core_trading_analysis_job(self):
        """核心交易服务分析任务 - 每30分钟执行一次的详细推送"""
        try:
            monitor_logger.info("🎯 执行核心交易服务分析 (详细推送)...")
            
            # 使用核心交易服务进行完整的交易决策分析
            from app.services.trading.core_trading_service import get_core_trading_service, AnalysisType
            from app.services.notification.core_notification_service import get_core_notification_service
            
            core_trading_service = await get_core_trading_service()
            await get_core_notification_service()
            
            # 分析核心币种 - 使用配置中的target_symbols
            core_symbols = settings.kronos_config.get('target_symbols', [])
            if not core_symbols:
                monitor_logger.warning("⚠️ 未配置核心分析币种，使用默认币种")
                core_symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
            
            monitor_logger.info(f"📊 开始分析 {len(core_symbols)} 个核心币种: {[s.replace('-USDT-SWAP', '') for s in core_symbols]}")
            
            # 🚀 执行完整的交易决策分析
            analysis_start_time = datetime.now()
            strong_signals = []
            notifications_sent = 0
            
            for symbol in core_symbols:
                try:
                    # 使用集成分析 - 包含Kronos AI预测 + 传统技术分析 + ML预测
                    trading_signal = await core_trading_service.analyze_symbol(
                        symbol=symbol,
                        analysis_type=AnalysisType.INTEGRATED,  # 使用综合分析
                        force_update=False  # 定时任务不强制更新，使用缓存提高效率
                    )
                    
                    if not trading_signal:
                        monitor_logger.warning(f"⚠️ {symbol} 分析失败，跳过")
                        continue
                    
                    # 检查是否是强信号 (非HOLD且置信度>50% - 适合30分钟推送频率)
                    if (trading_signal.final_action.upper() not in ['HOLD', '持有', '观望', '等待'] and 
                        trading_signal.final_confidence > 0.50):
                        
                        # 转换置信度格式 - 修复重复乘100的问题
                        if trading_signal.final_confidence <= 1:
                            confidence_percent = trading_signal.final_confidence * 100  # 0.85 -> 85%
                        else:
                            confidence_percent = trading_signal.final_confidence  # 已经是百分比格式
                        
                        strong_signals.append({
                            "symbol": symbol,
                            "action": trading_signal.final_action,
                            "confidence": confidence_percent,
                            "signal_strength": trading_signal.signal_strength.value if hasattr(trading_signal.signal_strength, 'value') else str(trading_signal.signal_strength),
                            "reasoning": trading_signal.reasoning,
                            "kronos_confidence": self._convert_confidence_to_percent(trading_signal.confidence_breakdown.get('kronos', 0)),
                            "technical_confidence": self._convert_confidence_to_percent(trading_signal.confidence_breakdown.get('technical', 0)),
                            "ml_confidence": self._convert_confidence_to_percent(trading_signal.confidence_breakdown.get('ml', 0))
                        })
                        
                        # 使用核心交易服务的推送方法
                        try:
                            success = await core_trading_service.send_trading_signal_notification(trading_signal)
                            if success:
                                notifications_sent += 1
                                monitor_logger.info(f"✅ 发送 {symbol} 核心交易信号通知成功")
                            else:
                                monitor_logger.warning(f"❌ 发送 {symbol} 核心交易信号通知失败")
                                
                        except Exception as e:
                            logger.warning(f"发送 {symbol} 交易信号通知失败: {e}")
                    else:
                        confidence_percent = trading_signal.final_confidence * 100 if trading_signal.final_confidence <= 1 else trading_signal.final_confidence
                        monitor_logger.debug(f"📊 {symbol}: {trading_signal.final_action} (置信度: {confidence_percent:.1f}%) - 不符合推送条件")
                    
                except Exception as e:
                    monitor_logger.warning(f"❌ 分析 {symbol} 失败: {e}")
                    continue
            
            analysis_duration = (datetime.now() - analysis_start_time).total_seconds()
            
            # 📈 统计和性能记录
            monitor_logger.info(f"✅ 核心交易服务分析完成:")
            monitor_logger.info(f"   📊 分析币种: {len(core_symbols)} 个")
            monitor_logger.info(f"   🎯 发现强信号: {len(strong_signals)} 个")
            monitor_logger.info(f"   📢 通知发送: {notifications_sent} 条")
            monitor_logger.info(f"   ⏱️ 分析耗时: {analysis_duration:.2f}秒")
            
            # 记录强信号详情
            for i, signal in enumerate(strong_signals[:3], 1):
                symbol_name = signal['symbol'].replace('-USDT-SWAP', '')
                action = signal['action']
                confidence = signal['confidence']
                signal_strength = signal['signal_strength']
                kronos_conf = signal.get('kronos_confidence', 0)
                technical_conf = signal.get('technical_confidence', 0)
                ml_conf = signal.get('ml_confidence', 0)
                
                monitor_logger.info(f"   {i}. 🎯 {symbol_name}: {action} (综合: {confidence:.1f}%)")
                monitor_logger.info(f"      🤖 Kronos: {kronos_conf:.1f}% | 📊 技术: {technical_conf:.1f}% | 🧠 ML: {ml_conf:.1f}%")
                monitor_logger.info(f"      🔥 信号强度: {signal_strength}")
            
        except Exception as e:
            logger.error(f"❌ 核心交易服务分析失败: {e}")

    async def _enhanced_kronos_analysis_job(self):
        """完整交易决策分析任务 - 核心任务 (使用Kronos+传统+ML的综合决策服务)"""
        try:
            monitor_logger.info("🎯 执行完整交易决策分析 (Kronos+传统+ML综合)...")
            
            # 使用增强的核心交易服务，集成Kronos分析
            from app.services.trading.core_trading_service import get_core_trading_service, AnalysisType
            from app.services.notification.core_notification_service import get_core_notification_service
            
            core_trading_service = await get_core_trading_service()
            await get_core_notification_service()
            
            # 分析核心币种 - 使用配置中的target_symbols
            core_symbols = settings.kronos_config.get('target_symbols', [])
            if not core_symbols:
                monitor_logger.warning("⚠️ 未配置核心分析币种，使用默认币种")
                core_symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
            
            monitor_logger.info(f"📊 开始分析 {len(core_symbols)} 个核心币种: {[s.replace('-USDT-SWAP', '') for s in core_symbols]}")
            
            # 🚀 执行完整的交易决策分析
            analysis_start_time = datetime.now()
            strong_signals = []
            notifications_sent = 0
            
            for symbol in core_symbols:
                try:
                    # 使用集成分析 - 包含Kronos、传统技术分析、ML预测
                    trading_signal = await core_trading_service.analyze_symbol(
                        symbol=symbol,
                        analysis_type=AnalysisType.INTEGRATED,  # 使用综合分析
                        force_update=False  # 定时任务不强制更新，使用缓存提高效率
                    )
                    
                    if not trading_signal:
                        monitor_logger.warning(f"⚠️ {symbol} 分析失败，跳过")
                        continue
                    
                    # 检查是否是强信号 (非HOLD且置信度>65%)
                    if (trading_signal.final_action.upper() not in ['HOLD', '持有', '观望', '等待'] and 
                        trading_signal.final_confidence > 0.65):
                        
                        # 转换置信度格式
                        confidence_percent = trading_signal.final_confidence * 100 if trading_signal.final_confidence <= 1 else trading_signal.final_confidence
                        
                        strong_signals.append({
                            "symbol": symbol,
                            "action": trading_signal.final_action,
                            "confidence": confidence_percent,
                            "signal_strength": trading_signal.signal_strength.value if hasattr(trading_signal.signal_strength, 'value') else str(trading_signal.signal_strength),
                            "reasoning": trading_signal.reasoning,
                            "kronos_confidence": self._convert_confidence_to_percent(trading_signal.confidence_breakdown.get('kronos', 0)),
                            "technical_confidence": self._convert_confidence_to_percent(trading_signal.confidence_breakdown.get('technical', 0)),
                            "ml_confidence": self._convert_confidence_to_percent(trading_signal.confidence_breakdown.get('ml', 0))
                        })
                        
                        # 使用核心交易服务的推送方法
                        try:
                            success = await core_trading_service.send_trading_signal_notification(trading_signal)
                            if success:
                                notifications_sent += 1
                                monitor_logger.info(f"✅ 发送 {symbol} 综合交易信号通知成功")
                            else:
                                monitor_logger.warning(f"❌ 发送 {symbol} 综合交易信号通知失败")
                                
                        except Exception as e:
                            logger.warning(f"发送 {symbol} 交易信号通知失败: {e}")
                    else:
                        confidence_percent = trading_signal.final_confidence * 100 if trading_signal.final_confidence <= 1 else trading_signal.final_confidence
                        monitor_logger.debug(f"📊 {symbol}: {trading_signal.final_action} (置信度: {confidence_percent:.1f}%) - 不符合推送条件")
                    
                except Exception as e:
                    monitor_logger.warning(f"❌ 分析 {symbol} 失败: {e}")
                    continue
            
            analysis_duration = (datetime.now() - analysis_start_time).total_seconds()
            
            # 📈 统计和性能记录
            monitor_logger.info(f"✅ 完整交易决策分析完成 (Kronos+技术+ML):")
            monitor_logger.info(f"   📊 分析币种: {len(core_symbols)} 个")
            monitor_logger.info(f"   🎯 发现强信号: {len(strong_signals)} 个")
            monitor_logger.info(f"   📢 通知发送: {notifications_sent} 条")
            monitor_logger.info(f"   ⏱️ 分析耗时: {analysis_duration:.2f}秒")
            
            # 记录强信号详情
            for i, signal in enumerate(strong_signals[:3], 1):
                symbol_name = signal['symbol'].replace('-USDT-SWAP', '')
                action = signal['action']
                confidence = signal['confidence']
                signal_strength = signal['signal_strength']
                kronos_conf = signal.get('kronos_confidence', 0)
                technical_conf = signal.get('technical_confidence', 0)
                ml_conf = signal.get('ml_confidence', 0)
                
                monitor_logger.info(f"   {i}. 🎯 {symbol_name}: {action} (综合: {confidence:.1f}%)")
                monitor_logger.info(f"      🤖 Kronos: {kronos_conf:.1f}% | 📊 技术: {technical_conf:.1f}% | 🧠 ML: {ml_conf:.1f}%")
                monitor_logger.info(f"      🔥 信号强度: {signal_strength}")
            
        except Exception as e:
            logger.error(f"❌ 完整交易决策分析失败 (Kronos+技术+ML): {e}")
    
    async def _daily_report_job(self):
        """每日监控报告任务"""
        try:
            monitor_logger.info("Generating daily monitoring report")
            monitor_service = self._get_monitor_service()
            
            # 执行综合监控
            result = await monitor_service.run_comprehensive_monitoring()
            
            # 生成报告消息
            report_message = self._format_daily_report(result)
            
            # 发送报告
            from app.services.notification.notification_service import NotificationService
            notification_service = NotificationService()
            
            await notification_service.send_notification(
                report_message,
                priority="normal",
                subject="每日监控报告"
            )
            
            monitor_logger.info("Daily report sent successfully")
            
        except Exception as e:
            logger.error(f"Daily report job failed: {e}")
    
    async def _health_check_job(self):
        """健康检查任务"""
        try:
            monitor_logger.info("Executing system health check")
            
            # 检查各个服务的健康状态
            from app.core.database import db_manager
            from app.services.exchanges.exchange_service_manager import get_exchange_service
            
            db_healthy = db_manager.health_check()
            
            exchange_service = await get_exchange_service()
            api_healthy = await exchange_service.health_check()
            
            # 如果有严重问题，发送警报
            if not db_healthy or not api_healthy:
                from app.services.notification.notification_service import NotificationService
                notification_service = NotificationService()
                
                error_message = f"""🚨 系统健康检查警报

⏰ 检查时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

❌ 发现问题：
• 数据库：{'正常' if db_healthy else '异常'}
• 交易所API：{'正常' if api_healthy else '异常'}

请及时检查系统状态！"""
                
                await notification_service.send_notification(
                    error_message,
                    priority="urgent",
                    subject="系统健康检查警报"
                )
            
            monitor_logger.info(
                f"Health check completed: DB={'OK' if db_healthy else 'FAIL'}, "
                f"API={'OK' if api_healthy else 'FAIL'}"
            )
            
        except Exception as e:
            logger.error(f"Health check job failed: {e}")
    
    async def _dynamic_weight_monitoring_job(self):
        """动态权重监控任务 - 展示权重调整效果"""
        try:
            monitor_logger.info("⚖️ 执行动态权重监控")
            
            # 使用动态权重服务
            from app.services.core.dynamic_weight_service import get_dynamic_weight_service
            weight_service = get_dynamic_weight_service()
            
            # 监控核心币种
            core_symbols = settings.kronos_config.get('target_symbols', [])
            if not core_symbols:
                core_symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
            
            # 获取权重摘要
            weight_summary = await weight_service.get_weight_summary(core_symbols)
            
            # 统计市场状态分布
            regime_dist = weight_summary.get('regime_distribution', {})
            avg_weights = weight_summary.get('average_weights', {})
            
            monitor_logger.info(
                f"✅ 动态权重监控完成: 分析 {weight_summary.get('total_symbols', 0)} 个币种"
            )
            
            # 显示市场状态分布
            for regime, count in regime_dist.items():
                if count > 0:
                    monitor_logger.info(f"   📊 {regime}: {count} 个币种")
            
            # 显示平均权重
            monitor_logger.info(
                f"   ⚖️ 平均权重: Kronos={avg_weights.get('kronos', 0):.2f} "
                f"技术={avg_weights.get('technical', 0):.2f} "
                f"ML={avg_weights.get('ml', 0):.2f}"
            )
            
            # 显示权重调整示例
            regime_examples = weight_summary.get('regime_examples', {})
            for regime, examples in regime_examples.items():
                if examples:
                    example = examples[0]  # 取第一个示例
                    symbol_name = example['symbol'].replace('-USDT-SWAP', '')
                    monitor_logger.info(
                        f"   🎯 {regime}示例 ({symbol_name}): "
                        f"Kronos={example['kronos_weight']:.2f} "
                        f"技术={example['technical_weight']:.2f}"
                    )
            
        except Exception as e:
            logger.error(f"❌ 动态权重监控失败: {e}")
    
    def _format_daily_report(self, monitor_result: Dict[str, Any]) -> str:
        """格式化每日报告"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        report = f"""📊 【每日监控报告】

⏰ 报告时间：{timestamp}

📈 监控概况：
• 总预警数量：{monitor_result.get('total_alerts', 0)}

"""
        
        # 资金费率
        funding_data = monitor_result.get('funding_rate_monitoring', {})
        if not isinstance(funding_data, dict) or 'error' not in funding_data:
            report += f"💰 资金费率：负费率 {funding_data.get('negative_count', 0)} 个，高费率 {funding_data.get('high_positive_count', 0)} 个\n"
        
        # 持仓量变化
        oi_data = monitor_result.get('open_interest_monitoring', {})
        if not isinstance(oi_data, dict) or 'error' not in oi_data:
            report += f"📊 持仓量变化：{oi_data.get('alert_count', 0)} 个标的异动\n"
        
        # 交易量异常
        volume_data = monitor_result.get('volume_anomaly_monitoring', {})
        if not isinstance(volume_data, dict) or 'error' not in volume_data:
            report += f"🔊 交易量异常：{volume_data.get('total_anomalies', 0)} 个标的放量\n"
        
        report += f"\n💡 如需详细信息，请查看具体监控接口"
        
        return report
    
    def add_job(self, func, trigger, **kwargs):
        """添加任务的包装方法"""
        return self.scheduler.add_job(func, trigger, **kwargs)
    
    def get_job(self, job_id: str):
        """获取指定任务的包装方法"""
        return self.scheduler.get_job(job_id)
    
    def get_job_status(self) -> Dict[str, Any]:
        """获取任务状态"""
        try:
            jobs_info = []
            
            for job in self.scheduler.get_jobs():
                jobs_info.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger)
                })
            
            return {
                "scheduler_running": self.is_running(),
                "total_jobs": len(jobs_info),
                "jobs": jobs_info
            }
            
        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            return {"error": str(e)}
    
    async def run_job_manually(self, job_id: str) -> bool:
        """手动执行任务"""
        try:
            job = self.scheduler.get_job(job_id)
            if job:
                self.scheduler.modify_job(job_id, next_run_time=datetime.now())
                logger.info(f"Job {job_id} scheduled for immediate execution")
                return True
            else:
                logger.warning(f"Job {job_id} not found")
                return False
                
        except Exception as e:
            logger.error(f"Failed to run job {job_id} manually: {e}")
            return False
    
    async def _ml_prediction_job(self):
        """ML预测信号任务"""
        try:
            monitor_logger.info("Executing scheduled ML prediction analysis")
            ml_service = self._get_ml_service()
            notification_service = await self._get_core_notification_service()
            
            # 获取监控的交易对
            symbols = settings.monitored_symbols
            
            for symbol in symbols:
                try:
                    # 获取ML预测
                    prediction = await ml_service.predict_signal(symbol)
                    
                    # 推送高置信度的买入/卖出信号
                    if (prediction.signal.value in ['buy', 'sell'] and prediction.confidence > 0.6) or \
                       prediction.signal.value in ['strong_buy', 'strong_sell']:
                        await notification_service.send_ml_prediction_notification({
                            'symbol': symbol,
                            'signal': prediction.signal.value,
                            'confidence': prediction.confidence,
                            'timestamp': datetime.now()
                        })
                    
                    # 记录预测结果
                    monitor_logger.info(
                        f"ML prediction for {symbol}: {prediction.signal.value} "
                        f"(confidence: {prediction.confidence:.3f})"
                    )
                    
                except Exception as e:
                    logger.warning(f"ML prediction failed for {symbol}: {e}")
                    continue
            
            monitor_logger.info("ML prediction analysis completed")
            
        except Exception as e:
            logger.error(f"ML prediction job failed: {e}")
    
    async def _ml_anomaly_detection_job(self):
        """ML异常检测任务"""
        try:
            monitor_logger.info("Executing scheduled ML anomaly detection")
            ml_service = self._get_ml_service()
            ml_notification_service = self._get_ml_notification_service()
            
            # 获取监控的交易对
            symbols = settings.monitored_symbols
            
            all_anomalies = []
            
            for symbol in symbols:
                try:
                    # 检测异常
                    anomalies = await ml_service.detect_anomalies(symbol)
                    
                    if anomalies:
                        all_anomalies.extend(anomalies)
                        monitor_logger.info(f"Detected {len(anomalies)} anomalies for {symbol}")
                    
                except Exception as e:
                    logger.warning(f"Anomaly detection failed for {symbol}: {e}")
                    continue
            
            # 发送异常通知
            if all_anomalies:
                await ml_notification_service.send_anomaly_alert(all_anomalies)
            
            monitor_logger.info(f"ML anomaly detection completed: {len(all_anomalies)} total anomalies")
            
        except Exception as e:
            logger.error(f"ML anomaly detection job failed: {e}")
    
    async def _update_trading_pairs_on_startup(self):
        """启动时更新交易对列表"""
        try:
            monitor_logger.info("Updating trading pairs on startup")
            from app.services.trading.trading_pair_service import TradingPairService
            
            trading_pair_service = TradingPairService()
            result = await trading_pair_service.fetch_and_update_trading_pairs()
            
            if result['success']:
                monitor_logger.info(
                    f"Trading pairs updated on startup: {result['updated_count']} pairs"
                )
            else:
                logger.warning(f"Failed to update trading pairs on startup: {result['error']}")
                
        except Exception as e:
            logger.error(f"Trading pairs startup update failed: {e}")
    
    async def _update_trading_pairs_job(self):
        """交易对列表更新任务"""
        try:
            monitor_logger.info("Executing scheduled trading pairs update")
            from app.services.trading.trading_pair_service import TradingPairService
            
            trading_pair_service = TradingPairService()
            result = await trading_pair_service.fetch_and_update_trading_pairs()
            
            if result['success']:
                monitor_logger.info(
                    f"Trading pairs updated: {result['updated_count']} pairs, "
                    f"total USDT pairs: {result['usdt_pairs']}"
                )
                
                # 发送更新通知（仅在有显著变化时）
                if result['updated_count'] > 10:  # 如果更新超过10个交易对
                    from app.services.notification.notification_service import NotificationService
                    notification_service = NotificationService()
                    
                    message = f"""📋 交易对列表更新完成

⏰ 更新时间：{result['update_time'].strftime('%Y-%m-%d %H:%M:%S')}
📊 总交易对：{result['total_instruments']}
💰 USDT永续：{result['usdt_pairs']}
✅ 更新数量：{result['updated_count']}"""
                    
                    await notification_service.send_notification(
                        title="📋 交易对列表更新",
                        message=message,
                        notification_type="trading_pairs_update",
                        priority="low"
                    )
                    
        except Exception as e:
            logger.error(f"Trading pairs update job failed: {e}")
    
    async def _ml_model_retrain_job(self):
        try:
            monitor_logger.info("Executing scheduled ML model retraining")
            ml_service = self._get_ml_service()
            ml_notification_service = self._get_ml_notification_service()
            
            # 获取监控的交易对
            symbols = settings.monitored_symbols
            
            retrain_results = []
            
            for symbol in symbols:
                try:
                    # 获取当前模型准确率
                    current_model = ml_service.prediction_models.get(symbol)
                    previous_accuracy = getattr(current_model, '_accuracy', 0.0) if current_model else 0.0
                    
                    # 重新训练模型
                    await ml_service._train_new_model(symbol)
                    
                    # 获取新模型准确率
                    new_model = ml_service.prediction_models.get(symbol)
                    new_accuracy = getattr(new_model, '_accuracy', 0.0) if new_model else 0.0
                    
                    retrain_results.append({
                        'symbol': symbol,
                        'previous_accuracy': previous_accuracy,
                        'new_accuracy': new_accuracy,
                        'improvement': new_accuracy - previous_accuracy
                    })
                    
                    # 发送性能报告
                    await ml_notification_service.send_model_performance_report(
                        symbol, new_accuracy, previous_accuracy
                    )
                    
                    monitor_logger.info(
                        f"Model retrained for {symbol}: "
                        f"{previous_accuracy:.3f} -> {new_accuracy:.3f}"
                    )
                    
                except Exception as e:
                    logger.warning(f"Model retraining failed for {symbol}: {e}")
                    continue
            
            # 记录整体重训练结果
            total_improved = sum(1 for r in retrain_results if r['improvement'] > 0)
            monitor_logger.info(
                f"ML model retraining completed: {total_improved}/{len(retrain_results)} models improved"
            )
            
        except Exception as e:
            logger.error(f"ML model retraining job failed: {e}")
    
    async def _update_trading_pairs_on_startup(self):
        """启动时更新交易对列表"""
        try:
            monitor_logger.info("Updating trading pairs on startup")
            from app.services.trading.trading_pair_service import TradingPairService
            
            trading_pair_service = TradingPairService()
            result = await trading_pair_service.fetch_and_update_trading_pairs()
            
            if result['success']:
                monitor_logger.info(
                    f"Trading pairs updated on startup: {result['updated_count']} pairs"
                )
            else:
                logger.warning(f"Failed to update trading pairs on startup: {result['error']}")
                
        except Exception as e:
            logger.error(f"Trading pairs startup update failed: {e}")
    
    async def _update_trading_pairs_job(self):
        """交易对列表更新任务"""
        try:
            monitor_logger.info("Executing scheduled trading pairs update")
            from app.services.trading.trading_pair_service import TradingPairService
            
            trading_pair_service = TradingPairService()
            result = await trading_pair_service.fetch_and_update_trading_pairs()
            
            if result['success']:
                monitor_logger.info(
                    f"Trading pairs updated: {result['updated_count']} pairs, "
                    f"total USDT pairs: {result['usdt_pairs']}"
                )
                
                # 发送更新通知（仅在有显著变化时）
                if result['updated_count'] > 10:  # 如果更新超过10个交易对
                    from app.services.notification.notification_service import NotificationService
                    notification_service = NotificationService()
                    
                    message = f"""📋 交易对列表更新完成

⏰ 更新时间：{result['update_time'].strftime('%Y-%m-%d %H:%M:%S')}
📊 总交易对：{result['total_instruments']}
💰 USDT永续：{result['usdt_pairs']}
✅ 更新数量：{result['updated_count']}

💡 新的交易对已加入负费率监控范围"""
                    
                    await notification_service.send_notification(
                        message,
                        priority="low"
                    )
            else:
                logger.error(f"Trading pairs update failed: {result['error']}")
                
        except Exception as e:
            logger.error(f"Trading pairs update job failed: {e}")
    
    async def _position_analysis_job(self):
        """持仓分析任务"""
        try:
            monitor_logger.info("Executing scheduled position analysis")
            position_service = self._get_position_analysis_service()
            
            # 执行持仓分析 (添加超时保护)
            try:
                analysis_result = await asyncio.wait_for(
                    position_service.analyze_account_positions(),
                    timeout=120.0  # 2分钟超时
                )
                
                if analysis_result.get("status") != "error":
                    overall_score = analysis_result.get("overall_score", 0)
                    risk_level = analysis_result.get("risk_assessment", {}).get("overall_risk")
                    
                    # 只有在评分较低或风险较高时才发送通知
                    if overall_score < 70 or (risk_level and hasattr(risk_level, 'value') and risk_level.value in ['高风险', '极高风险']):
                        try:
                            await asyncio.wait_for(
                                position_service.send_position_analysis_notification(analysis_result),
                                timeout=60.0  # 1分钟超时
                            )
                            monitor_logger.info(f"Position analysis notification sent (score: {overall_score}/100)")
                        except asyncio.TimeoutError:
                            monitor_logger.warning("⏰ 持仓分析通知发送超时")
                    else:
                        monitor_logger.info(f"Position analysis completed (score: {overall_score}/100, no notification needed)")
            except asyncio.TimeoutError:
                monitor_logger.warning("⏰ 持仓分析执行超时，跳过本次分析")
            else:
                logger.warning(f"Position analysis failed: {analysis_result.get('message', 'unknown error')}")
            
        except Exception as e:
            logger.error(f"Position analysis job failed: {e}")
    
    async def _grid_opportunities_job(self):
        """网格交易机会分析任务 - 只推送经过Kronos分析的网格机会"""
        try:
            monitor_logger.info("Executing scheduled Kronos-enhanced grid opportunities analysis")
            
            # 检查是否启用Kronos集成
            if not settings.kronos_config.get('enable_kronos_prediction', False):
                monitor_logger.info("Kronos预测功能已禁用，跳过网格机会分析")
                return
            
            # 使用策略交易服务进行Kronos增强的网格分析
            try:
                from app.services.trading.strategy_trading_service import StrategyTradingService
                strategy_service = StrategyTradingService()
            except ImportError:
                monitor_logger.warning("策略交易服务不可用，跳过网格分析")
                return
            
            # 获取交易量大或涨幅大的币种进行网格分析
            from app.services.negative_funding_monitor_service import NegativeFundingMonitorService
            funding_monitor = NegativeFundingMonitorService()
            
            # 获取热门币种（交易量大或涨幅大）
            hot_symbols = await funding_monitor.get_top_volume_symbols(limit=30)
            
            # 进一步筛选：只要涨幅超过50%或交易量前10的币种
            filtered_symbols = []
            try:
                async with funding_monitor.exchange_service as exchange:
                    result = await exchange._make_request('GET', '/api/v5/market/tickers', 
                                                   params={'instType': 'SWAP'})
                    
                    if result:
                        for ticker in result:
                            symbol = ticker.get('instId', '')
                            if symbol in hot_symbols:
                                volume_24h = float(ticker.get('volCcy24h', '0') or '0')
                                change_24h = abs(float(ticker.get('chg', '0') or '0'))  # 这里保留abs，用于筛选活跃币种
                                
                                # 筛选条件：涨幅超过50% 或 交易量前10
                                if (change_24h > 0.10 or  # 涨幅超过10%
                                    symbol in hot_symbols[:10]):  # 或者是交易量前10
                                    filtered_symbols.append({
                                        'symbol': symbol,
                                        'volume_24h': volume_24h,
                                        'change_24h': change_24h
                                    })
                        
                        # 按涨幅和交易量排序，优先分析
                        filtered_symbols.sort(key=lambda x: x['change_24h'] + x['volume_24h']/10000000, reverse=True)
                        symbols = [s['symbol'] for s in filtered_symbols[:15]]  # 最多分析15个币种
                        
                        monitor_logger.info(f"📊 筛选出 {len(symbols)} 个高潜力币种进行网格分析")
                        for s in filtered_symbols[:5]:  # 显示前5个
                            monitor_logger.info(f"   {s['symbol']}: 涨幅 {s['change_24h']:.1%}, 交易量 {s['volume_24h']/1000000:.1f}M")
                    else:
                        symbols = settings.monitored_symbols  # 备用方案
            except Exception as e:
                logger.warning(f"获取热门币种失败，使用默认币种: {e}")
                symbols = settings.monitored_symbols
            
            kronos_grid_opportunities = []
            
            for symbol in symbols:
                try:
                    # 使用集成Kronos的网格分析
                    grid_recommendation = await strategy_service.analyze_grid_opportunity(symbol, investment=1000)
                    
                    # 推送有潜力的网格机会 - 平衡收益和风险
                    if (grid_recommendation.recommended and 
                        grid_recommendation.confidence > 65 and  # 适中的置信度要求
                        grid_recommendation.parameters.get('kronos_confidence', 0) > 0.5 and  # Kronos置信度要求
                        grid_recommendation.parameters.get('grid_suitability_score', 0) >= 60 and  # 网格机会评分要求
                        grid_recommendation.expected_daily_return > 0.005):  # 日收益至少0.5%
                        
                        kronos_grid_opportunities.append({
                            'symbol': symbol,
                            'recommendation': grid_recommendation
                        })
                        
                except Exception as e:
                    logger.warning(f"分析{symbol}网格机会失败: {e}")
                    continue
            
            # 发送Kronos网格机会通知
            if kronos_grid_opportunities:
                try:
                    from app.services.notification.notification_service import NotificationService
                    notification_service = NotificationService()
                    
                    # 构建通知消息
                    message_parts = ["🤖 【Kronos网格交易机会】\n"]
                    
                    for opportunity in kronos_grid_opportunities:
                        rec = opportunity['recommendation']
                        symbol = opportunity['symbol']
                        
                        # 获取详细参数
                        grid_score = rec.parameters.get('grid_suitability_score', 0)
                        trend_strength = rec.parameters.get('trend_strength', 0)
                        predicted_volatility = rec.parameters.get('predicted_volatility', 0)
                        predicted_trend = rec.parameters.get('predicted_trend', 'unknown')
                        funding_rate = rec.parameters.get('funding_rate', 0)
                        daily_grid_return = rec.parameters.get('daily_grid_return', 0)
                        daily_funding_return = rec.parameters.get('daily_funding_return', 0)
                        
                        # 趋势描述
                        trend_desc = {
                            'sideways': '横盘震荡',
                            'bullish': '上涨趋势', 
                            'bearish': '下跌趋势'
                        }.get(predicted_trend, predicted_trend)
                        
                        # 资金费率描述
                        funding_desc = ""
                        if funding_rate < -0.01:
                            funding_desc = f" 🎁强负费率({funding_rate:.3%})"
                        elif funding_rate < 0:
                            funding_desc = f" 💰负费率({funding_rate:.3%})"
                        
                        message_parts.append(f"""
📊 {symbol}
├ 机会评分: {grid_score}/100
├ Kronos预测: {trend_desc} (置信度: {rec.parameters.get('kronos_confidence', 0):.1%})
├ 波动率: {predicted_volatility:.1%} (趋势强度: {trend_strength:.1%}){funding_desc}
├ 网格设置: {rec.parameters.get('grid_num', 0)}层网格
├ 价格区间: {rec.parameters.get('min_price', 0):.2f} - {rec.parameters.get('max_price', 0):.2f}
├ 日收益预期: {rec.expected_daily_return:.2%} (网格: {daily_grid_return:.2%} + 费率: {daily_funding_return:.2%})
├ 年化收益: {rec.expected_annual_return:.1%}
└ 推荐指数: {rec.confidence:.0f}%
""")
                    
                    message_parts.append(f"""
⚠️ 网格交易策略说明:
• 高波动率 = 高收益潜力，但风险也相应增加
• 突破网格区间时需要及时调整或止损
• 负费率币种可获得额外持仓收益
• 建议分批建仓，设置合理止损位
• 此分析基于Kronos AI预测和市场数据，请结合实际情况操作""")
                    
                    full_message = "".join(message_parts)
                    
                    await notification_service.send_notification(
                        full_message,
                        priority="medium"
                    )
                    
                    monitor_logger.info(f"Kronos网格机会通知已发送: {len(kronos_grid_opportunities)} 个机会")
                    
                except Exception as e:
                    logger.error(f"发送Kronos网格机会通知失败: {e}")
            else:
                monitor_logger.info("未发现符合Kronos标准的网格交易机会")
            
        except Exception as e:
            logger.error(f"Kronos网格机会分析任务失败: {e}")
    
    async def _comprehensive_market_analysis_job(self):
        """综合市场机会分析任务 - 宏观分析 (整合原市场机会分析)"""
        try:
            monitor_logger.info("📊 执行综合市场机会分析 (宏观分析)...")
            
            # 🔍 多维度市场分析
            analysis_results = {}
            
            # 1. 原有的持仓分析服务
            try:
                position_service = self._get_position_analysis_service()
                market_analysis = await position_service.analyze_market_opportunities()
                analysis_results['position_analysis'] = market_analysis
                
                if not market_analysis.get("error"):
                    coin_contracts = market_analysis.get('coin_contracts', [])
                    spot_opportunities = market_analysis.get('spot_opportunities', [])
                    positive_contracts = len([c for c in coin_contracts if '适合' in c.get('suggestion', '')])
                    positive_spots = len([s for s in spot_opportunities if '买入' in s.get('suggestion', '') or '适合' in s.get('suggestion', '')])
                    
                    monitor_logger.info(f"📈 持仓分析: {positive_contracts} 个合约机会, {positive_spots} 个现货机会")
                else:
                    monitor_logger.warning(f"持仓分析失败: {market_analysis.get('error')}")
            except Exception as e:
                logger.warning(f"持仓分析失败: {e}")
            
            # 2. 市场情绪分析
            try:
                market_sentiment = await self._analyze_market_sentiment()
                analysis_results['sentiment'] = market_sentiment
                monitor_logger.info(f"📈 市场情绪: {market_sentiment.get('overall', 'N/A')}")
            except Exception as e:
                logger.warning(f"市场情绪分析失败: {e}")
            
            # 3. 跨时间框架分析
            try:
                timeframe_analysis = await self._analyze_cross_timeframes()
                analysis_results['timeframes'] = timeframe_analysis
                monitor_logger.info(f"⏰ 跨时间框架分析完成: {len(timeframe_analysis)} 个币种")
            except Exception as e:
                logger.warning(f"跨时间框架分析失败: {e}")
            
            # 4. 发现高质量机会
            high_quality_opportunities = []
            if analysis_results:
                high_quality_opportunities = await self._identify_high_quality_opportunities(analysis_results)
            
            # 5. 发送综合分析报告 (仅在发现重要机会时)
            if high_quality_opportunities:
                await self._send_comprehensive_analysis_report(high_quality_opportunities)
                monitor_logger.info(f"📢 发送综合分析报告: {len(high_quality_opportunities)} 个高质量机会")
            else:
                # 如果有原有的持仓分析机会，也发送通知
                position_analysis = analysis_results.get('position_analysis', {})
                if not position_analysis.get("error"):
                    coin_contracts = position_analysis.get('coin_contracts', [])
                    spot_opportunities = position_analysis.get('spot_opportunities', [])
                    positive_contracts = len([c for c in coin_contracts if '适合' in c.get('suggestion', '')])
                    positive_spots = len([s for s in spot_opportunities if '买入' in s.get('suggestion', '') or '适合' in s.get('suggestion', '')])
                    
                    if positive_contracts > 0 or positive_spots > 0:
                        position_service = self._get_position_analysis_service()
                        grid_analysis = {
                            'total_analyzed': 0,
                            'top_opportunities': [],
                            'high_score_count': 0,
                            'avg_annual_return': 0
                        }
                        await position_service.send_market_analysis_notification(grid_analysis, position_analysis)
                        monitor_logger.info(f"📢 发送持仓分析通知: {positive_contracts} 个合约 + {positive_spots} 个现货机会")
            
            monitor_logger.info(f"✅ 综合市场分析完成: 发现 {len(high_quality_opportunities)} 个高质量机会")
            
        except Exception as e:
            logger.error(f"❌ 综合市场分析失败: {e}")
    
    async def _analyze_market_sentiment(self) -> dict:
        """分析市场情绪"""
        try:
            # 简化版市场情绪分析
            # 实际应该基于恐慌贪婪指数、资金流向等
            return {
                'overall': '中性',
                'fear_greed_index': 50,
                'trend': '震荡'
            }
        except Exception as e:
            logger.error(f"市场情绪分析失败: {e}")
            return {}
    
    async def _analyze_cross_timeframes(self) -> dict:
        """跨时间框架分析"""
        try:
            # 简化版跨时间框架分析
            # 实际应该分析多个时间周期的趋势一致性
            core_symbols = settings.kronos_config.get('target_symbols', [])[:3]  # 只分析前3个
            
            timeframe_results = {}
            for symbol in core_symbols:
                timeframe_results[symbol] = {
                    '15m': 'up',
                    '1h': 'up', 
                    '4h': 'neutral',
                    '1d': 'down'
                }
            
            return timeframe_results
        except Exception as e:
            logger.error(f"跨时间框架分析失败: {e}")
            return {}
    
    async def _identify_high_quality_opportunities(self, analysis_results: dict) -> list:
        """识别高质量机会"""
        try:
            opportunities = []
            
            # 基于综合分析结果识别机会
            # 这里应该有复杂的逻辑来评估机会质量
            
            # 示例：如果市场情绪极端，可能有反转机会
            sentiment = analysis_results.get('sentiment', {})
            if sentiment.get('fear_greed_index', 50) < 20:  # 极度恐慌
                opportunities.append({
                    'type': '恐慌抄底机会',
                    'description': '市场极度恐慌，可能存在抄底机会',
                    'risk_level': 'high',
                    'confidence': 0.6
                })
            elif sentiment.get('fear_greed_index', 50) > 80:  # 极度贪婪
                opportunities.append({
                    'type': '贪婪做空机会', 
                    'description': '市场极度贪婪，可能存在做空机会',
                    'risk_level': 'high',
                    'confidence': 0.6
                })
            
            return opportunities
        except Exception as e:
            logger.error(f"识别高质量机会失败: {e}")
            return []
    
    async def _send_comprehensive_analysis_report(self, opportunities: list):
        """发送综合分析报告"""
        try:
            from app.services.notification.notification_service import NotificationService
            notification_service = NotificationService()
            
            message = f"📊 **综合市场分析报告**\n\n"
            message += f"🔍 发现 {len(opportunities)} 个高质量机会:\n\n"
            
            for i, opp in enumerate(opportunities[:3], 1):
                opp_type = opp.get('type', 'N/A')
                description = opp.get('description', 'N/A')
                confidence = opp.get('confidence', 0)
                risk = opp.get('risk_level', 'medium')
                
                message += f"{i}. **{opp_type}**\n"
                message += f"   📝 {description}\n"
                message += f"   📊 置信度: {confidence:.1%}\n"
                message += f"   ⚠️ 风险等级: {risk}\n\n"
            
            message += f"⏰ 分析时间: {datetime.now().strftime('%H:%M:%S')}\n"
            message += f"💡 建议结合Kronos AI信号进行决策"
            
            await notification_service.send_notification(
                title=f"📊 综合市场分析: {len(opportunities)}个机会",
                message=message,
                notification_type="comprehensive_market_analysis",
                priority="medium"
            )
            
        except Exception as e:
            logger.error(f"发送综合分析报告失败: {e}")
    
    async def _core_symbols_push_job(self):
        """核心币种推送任务 - 每30分钟推送总体操作建议"""
        try:
            logger.info("🚀 开始核心币种总体推送...")
            
            # 获取核心交易服务
            from app.services.trading.core_trading_service import get_core_trading_service
            trading_service = await get_core_trading_service()
            
            # 执行核心币种推送 - 只推送汇总报告
            result = await trading_service.run_core_symbols_push()
            
            if result.get("success"):
                logger.info(f"✅ 核心币种总体推送完成: {result.get('message', '成功')}")
            else:
                logger.warning(f"⚠️ 核心币种推送部分失败: {result.get('message', '未知错误')}")
                
        except Exception as e:
            logger.error(f"❌ 核心币种推送任务失败: {e}")
    
    async def _grid_trading_service_job(self):
        """网格交易服务分析任务 - 每60分钟执行一次"""
        try:
            monitor_logger.info("🔄 执行网格交易服务分析...")
            
            # 获取网格交易服务
            grid_service = await get_grid_trading_service()
            
            # 使用GridTradingService的动态筛选功能
            # 不传入symbols参数，让服务自动筛选交易额大于1亿USDT的活跃币种
            grid_batch = await grid_service.analyze_grid_opportunities(
                symbols=None,  # 让服务自动筛选候选币种
                min_opportunity_level="MODERATE"  # 中等以上机会
            )
            
            # 记录分析结果
            monitor_logger.info(
                f"✅ 网格交易分析完成: "
                f"总计 {grid_batch.total_count} 个机会, "
                f"优秀 {grid_batch.excellent_count} 个, "
                f"良好 {grid_batch.good_count} 个"
            )
            
            # 如果有优质机会，发送通知
            if grid_batch.excellent_count > 0 or grid_batch.good_count > 0:
                try:
                    from app.services.notification.core_notification_service import get_core_notification_service
                    notification_service = await get_core_notification_service()
                    
                    # 构建通知消息
                    message_parts = ["📊 【网格交易机会分析】"]
                    message_parts.append(f"🎯 市场概况: {grid_batch.market_summary}")
                    message_parts.append(f"📈 发现机会: 优秀 {grid_batch.excellent_count} 个, 良好 {grid_batch.good_count} 个")
                    
                    # 显示前5个最佳机会
                    for i, rec in enumerate(grid_batch.recommendations[:5], 1):
                        symbol_name = rec.symbol.replace('-USDT-SWAP', '')
                        opportunity_level = rec.opportunity_level.value if hasattr(rec.opportunity_level, 'value') else str(rec.opportunity_level)
                        
                        message_parts.append(f"📊 {i}. {symbol_name}")
                        message_parts.append(f"├ 机会等级: {opportunity_level}")
                        message_parts.append(f"├ 当前价格: ${rec.current_price:.4f}")
                        message_parts.append(f"├ 趋势类型: {rec.trend_type.value if hasattr(rec.trend_type, 'value') else str(rec.trend_type)}")
                        message_parts.append(f"├ 建议资金: ${rec.recommended_capital:.0f} ({rec.position_percentage}%)")
                        message_parts.append(f"├ 交易区间: ${rec.trading_range.lower_bound:.4f} - ${rec.trading_range.upper_bound:.4f}")
                        message_parts.append(f"├ 网格设置: {rec.trading_range.grid_count}层, 间距{rec.trading_range.grid_spacing}%")
                        message_parts.append(f"├ 预期收益: 日{rec.expected_daily_return:.2f}%, 月{rec.expected_monthly_return:.2f}%")
                        message_parts.append(f"├ 风险等级: {rec.risk_level}")
                        message_parts.append(f"└ 推荐理由: {rec.reasoning}")
                    
                    message_parts.append("⚠️ 风险提示: 网格交易需要合理设置止损，避免单边行情造成损失")
                    
                    full_message = "".join(message_parts)
                    
                    # 发送通知
                    await notification_service.send_grid_trading_notification({
                        'title': f'网格交易机会: {grid_batch.excellent_count + grid_batch.good_count}个机会',
                        'message': full_message,
                        'opportunities_count': grid_batch.excellent_count + grid_batch.good_count,
                        'excellent_count': grid_batch.excellent_count,
                        'good_count': grid_batch.good_count,
                        'timestamp': datetime.now()
                    })
                    
                    monitor_logger.info(f"📢 网格交易机会通知已发送")
                    
                except Exception as e:
                    logger.warning(f"发送网格交易通知失败: {e}")
            else:
                monitor_logger.info("📊 当前市场条件下未发现优质网格交易机会")
            
        except Exception as e:
            logger.error(f"❌ 网格交易服务分析失败: {e}")
