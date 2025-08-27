# -*- coding: utf-8 -*-
"""
调度服务
Scheduler service for background tasks
"""

import asyncio
from typing import Dict, Any, Callable
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.core.logging import get_logger, monitor_logger
from app.core.config import get_settings

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
            from app.services.monitor_service import MonitorService
            self._monitor_service = MonitorService(exchange='okx')
        return self._monitor_service
    
    def _get_trend_service(self):
        """获取趋势分析服务实例"""
        if self._trend_service is None:
            from app.services.trend_analysis_service import TrendAnalysisService
            self._trend_service = TrendAnalysisService(exchange='okx')
        return self._trend_service
    
    def _get_ml_service(self):
        """获取机器学习服务实例"""
        if not hasattr(self, '_ml_service') or self._ml_service is None:
            from app.services.ml_enhanced_service import MLEnhancedService
            self._ml_service = MLEnhancedService(exchange='okx')
        return self._ml_service
    
    def _get_ml_notification_service(self):
        """获取ML通知服务实例"""
        if not hasattr(self, '_ml_notification_service') or self._ml_notification_service is None:
            from app.services.ml_notification_service import MLNotificationService
            self._ml_notification_service = MLNotificationService()
        return self._ml_notification_service
    
    def _get_position_analysis_service(self):
        """获取持仓分析服务实例"""
        if self._position_analysis_service is None:
            from app.services.position_analysis_service import PositionAnalysisService
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
            
            # 启动时更新一次交易对列表
            await self._update_trading_pairs_on_startup()
            
            logger.info("Scheduler service started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start scheduler service: {e}")
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
    
    async def _setup_scheduled_jobs(self):
        """设置定时任务"""
        try:
            # 资金费率监控 - 已由NegativeFundingMonitorService接管，此处禁用避免重复推送
            # self.scheduler.add_job(
            #     self._funding_rate_job,
            #     trigger=IntervalTrigger(minutes=settings.funding_rate_interval),
            #     id="funding_rate_monitor",
            #     name="资金费率监控",
            #     max_instances=1
            # )
            
            # 持仓量监控 - 每5分钟执行一次
            self.scheduler.add_job(
                self._open_interest_job,
                trigger=IntervalTrigger(minutes=settings.open_interest_interval),
                id="open_interest_monitor", 
                name="持仓量变化监控",
                max_instances=1
            )
            
            # 交易量异常监控 - 每1小时执行一次
            self.scheduler.add_job(
                self._volume_anomaly_job,
                trigger=IntervalTrigger(minutes=settings.volume_monitor_interval),
                id="volume_anomaly_monitor",
                name="交易量异常监控",
                max_instances=1
            )
            
            # 趋势分析 - 每15分钟执行一次
            self.scheduler.add_job(
                self._trend_analysis_job,
                trigger=IntervalTrigger(minutes=settings.trend_analysis_interval),
                id="trend_analysis",
                name="趋势信号分析",
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
            
            # 持仓分析 - 已由Kronos持仓分析服务接管，此处禁用避免重复推送
            # self.scheduler.add_job(
            #     self._position_analysis_job,
            #     trigger=IntervalTrigger(minutes=settings.position_analysis_interval),
            #     id="position_analysis",
            #     name="持仓分析",
            #     max_instances=1
            # )
            
            # 网格机会分析 - 每4小时执行一次
            self.scheduler.add_job(
                self._grid_opportunities_job,
                trigger=IntervalTrigger(minutes=settings.grid_opportunities_interval),
                id="grid_opportunities",
                name="网格交易机会分析",
                max_instances=1
            )
            
            # 市场机会分析 - 每6小时执行一次
            self.scheduler.add_job(
                self._market_opportunities_job,
                trigger=IntervalTrigger(minutes=settings.market_opportunities_interval),
                id="market_opportunities",
                name="市场交易机会分析",
                max_instances=1
            )
            
            # ML预测信号 - 每30分钟执行一次
            self.scheduler.add_job(
                self._ml_prediction_job,
                trigger=IntervalTrigger(minutes=30),
                id="ml_prediction",
                name="ML预测信号分析",
                max_instances=1
            )
            
            # ML异常检测 - 已禁用，避免过多推送
            # self.scheduler.add_job(
            #     self._ml_anomaly_detection_job,
            #     trigger=IntervalTrigger(minutes=15),
            #     id="ml_anomaly_detection",
            #     name="ML异常检测",
            #     max_instances=1
            # )
            
            # ML模型重训练 - 每天凌晨2点执行
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
            
            logger.info("Scheduled jobs setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup scheduled jobs: {e}")
            raise
    
    async def _funding_rate_job(self):
        """资金费率监控任务 - 已禁用，由NegativeFundingMonitorService接管"""
        # 此方法已被禁用，避免与详细的负费率机会分析服务冲突
        # 详细的负费率分析由main.py中的NegativeFundingMonitorService.run_monitoring_cycle()处理
        pass
        # try:
        #     monitor_logger.info("Executing scheduled funding rate monitoring")
        #     monitor_service = self._get_monitor_service()
        #     
        #     result = await monitor_service.monitor_funding_rate(notify=True)
        #     
        #     monitor_logger.info(
        #         f"Funding rate monitoring completed: {result['negative_count']} negative, "
        #         f"{result['high_positive_count']} high positive rates"
        #     )
        #     
        # except Exception as e:
        #     logger.error(f"Funding rate monitoring job failed: {e}")
    
    async def _open_interest_job(self):
        """持仓量监控任务"""
        try:
            monitor_logger.info("Executing scheduled open interest monitoring")
            monitor_service = self._get_monitor_service()
            
            # 监控配置的交易对
            symbols = settings.monitored_symbols
            result = await monitor_service.monitor_open_interest(symbols, notify=True)
            
            monitor_logger.info(
                f"Open interest monitoring completed: {result['alert_count']} alerts"
            )
            
        except Exception as e:
            logger.error(f"Open interest monitoring job failed: {e}")
    
    async def _volume_anomaly_job(self):
        """交易量异常监控任务"""
        try:
            monitor_logger.info("Executing scheduled volume anomaly monitoring")
            monitor_service = self._get_monitor_service()
            
            result = await monitor_service.monitor_volume_anomaly(notify=True)
            
            monitor_logger.info(
                f"Volume anomaly monitoring completed: {result['total_anomalies']} anomalies found"
            )
            
        except Exception as e:
            logger.error(f"Volume anomaly monitoring job failed: {e}")
    
    async def _trend_analysis_job(self):
        """趋势分析任务 - 只推送经过Kronos分析的信号"""
        try:
            monitor_logger.info("Executing scheduled Kronos-enhanced trend analysis")
            
            # 检查是否启用Kronos集成
            if not settings.kronos_config.get('enable_kronos_prediction', False):
                monitor_logger.info("Kronos预测功能已禁用，跳过趋势分析")
                return
            
            # 使用Kronos集成决策服务而不是传统趋势分析
            try:
                from app.services.kronos_integrated_decision_service import get_kronos_integrated_service, KronosSignalStrength
                kronos_service = await get_kronos_integrated_service()
            except ImportError:
                monitor_logger.warning("Kronos集成服务不可用，跳过趋势分析")
                return
            
            # 分析配置的交易对趋势 - 只分析ETH和SOL
            symbols = settings.monitored_symbols  # 只包含ETH-USDT-SWAP和SOL-USDT-SWAP
            
            # 使用Kronos进行批量分析
            kronos_results = await kronos_service.batch_analyze_symbols(symbols, force_update=True)
            
            # 筛选需要推送的Kronos强信号
            strong_signals = []
            for symbol, decision in kronos_results.items():
                if decision is None:
                    continue
                
                # 只推送Kronos置信度高的强信号
                kronos_threshold = settings.kronos_config.get('notification_config', {}).get('strong_signal_threshold', 0.6)
                
                if (decision.kronos_confidence >= kronos_threshold and 
                    decision.kronos_signal_strength in [KronosSignalStrength.VERY_STRONG, KronosSignalStrength.STRONG]):
                    
                    strong_signals.append({
                        'symbol': symbol,
                        'kronos_decision': decision
                    })
            
            # 发送Kronos强信号通知
            if strong_signals:
                try:
                    from app.services.kronos_notification_service import get_kronos_notification_service
                    kronos_notification_service = await get_kronos_notification_service()
                    
                    for signal in strong_signals:
                        await kronos_notification_service.send_kronos_signal_notification(
                            signal['symbol'],
                            signal['kronos_decision'],
                            priority="high"
                        )
                        
                except ImportError:
                    # 如果Kronos通知服务不可用，使用普通通知服务
                    from app.services.notification_service import NotificationService
                    notification_service = NotificationService()
                    
                    for signal in strong_signals:
                        decision = signal['kronos_decision']
                        message = f"""🤖 【Kronos预测信号 - {signal['symbol']}】

🔮 Kronos预测置信度：{decision.kronos_confidence:.1%}
📊 信号强度：{decision.kronos_signal_strength.value}
💡 预测方向：{getattr(decision.kronos_prediction, 'predicted_direction', '未知') if decision.kronos_prediction else '未知'}
💰 预期收益：{(getattr(decision.kronos_prediction, 'expected_return', 0) if decision.kronos_prediction else 0):.2%}

⚠️ 注：此信号基于Kronos AI模型预测生成"""
                        
                        await notification_service.send_notification(
                            message,
                            priority="high"
                        )
            
            monitor_logger.info(
                f"Kronos趋势分析完成: {len(strong_signals)} 个强信号推送"
            )
            
        except Exception as e:
            logger.error(f"Kronos趋势分析任务失败: {e}")
    
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
            from app.services.notification_service import NotificationService
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
            from app.services.okx_service import OKXService
            
            db_healthy = db_manager.health_check()
            
            async with OKXService() as okx_service:
                api_healthy = await okx_service.health_check()
            
            # 如果有严重问题，发送警报
            if not db_healthy or not api_healthy:
                from app.services.notification_service import NotificationService
                notification_service = NotificationService()
                
                error_message = f"""🚨 系统健康检查警报

⏰ 检查时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

❌ 发现问题：
• 数据库：{'正常' if db_healthy else '异常'}
• OKX API：{'正常' if api_healthy else '异常'}

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
            ml_notification_service = self._get_ml_notification_service()
            
            # 获取监控的交易对
            symbols = settings.monitored_symbols
            
            for symbol in symbols:
                try:
                    # 获取ML预测
                    prediction = await ml_service.predict_signal(symbol)
                    
                    # 推送高置信度的买入/卖出信号
                    if (prediction.signal.value in ['buy', 'sell'] and prediction.confidence > 0.6) or \
                       prediction.signal.value in ['strong_buy', 'strong_sell']:
                        await ml_notification_service.send_ml_prediction_alert(prediction)
                    
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
            from app.services.trading_pair_service import TradingPairService
            
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
            from app.services.trading_pair_service import TradingPairService
            
            trading_pair_service = TradingPairService()
            result = await trading_pair_service.fetch_and_update_trading_pairs()
            
            if result['success']:
                monitor_logger.info(
                    f"Trading pairs updated: {result['updated_count']} pairs, "
                    f"total USDT pairs: {result['usdt_pairs']}"
                )
                
                # 发送更新通知（仅在有显著变化时）
                if result['updated_count'] > 10:  # 如果更新超过10个交易对
                    from app.services.notification_service import NotificationService
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
            from app.services.trading_pair_service import TradingPairService
            
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
            from app.services.trading_pair_service import TradingPairService
            
            trading_pair_service = TradingPairService()
            result = await trading_pair_service.fetch_and_update_trading_pairs()
            
            if result['success']:
                monitor_logger.info(
                    f"Trading pairs updated: {result['updated_count']} pairs, "
                    f"total USDT pairs: {result['usdt_pairs']}"
                )
                
                # 发送更新通知（仅在有显著变化时）
                if result['updated_count'] > 10:  # 如果更新超过10个交易对
                    from app.services.notification_service import NotificationService
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
            
            # 执行持仓分析
            analysis_result = await position_service.analyze_account_positions()
            
            if analysis_result.get("status") != "error":
                overall_score = analysis_result.get("overall_score", 0)
                risk_level = analysis_result.get("risk_assessment", {}).get("overall_risk")
                
                # 只有在评分较低或风险较高时才发送通知
                if overall_score < 70 or (risk_level and hasattr(risk_level, 'value') and risk_level.value in ['high', 'critical']):
                    await position_service.send_position_analysis_notification(analysis_result)
                    monitor_logger.info(f"Position analysis notification sent (score: {overall_score}/100)")
                else:
                    monitor_logger.info(f"Position analysis completed (score: {overall_score}/100, no notification needed)")
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
                from app.services.strategy_trading_service import StrategyTradingService
                strategy_service = StrategyTradingService()
            except ImportError:
                monitor_logger.warning("策略交易服务不可用，跳过网格分析")
                return
            
            # 分析主要监控币种的网格机会（只分析ETH和SOL）
            symbols = settings.monitored_symbols
            kronos_grid_opportunities = []
            
            for symbol in symbols:
                try:
                    # 使用集成Kronos的网格分析
                    grid_recommendation = await strategy_service.analyze_grid_opportunity(symbol, investment=1000)
                    
                    # 只推送Kronos推荐的高置信度网格机会
                    if (grid_recommendation.recommended and 
                        grid_recommendation.confidence > 60 and
                        grid_recommendation.parameters.get('kronos_confidence', 0) > 0.5):
                        
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
                    from app.services.notification_service import NotificationService
                    notification_service = NotificationService()
                    
                    # 构建通知消息
                    message_parts = ["🤖 【Kronos网格交易机会】\n"]
                    
                    for opportunity in kronos_grid_opportunities:
                        rec = opportunity['recommendation']
                        symbol = opportunity['symbol']
                        
                        message_parts.append(f"""
📊 {symbol}
├ Kronos置信度: {rec.parameters.get('kronos_confidence', 0):.1%}
├ 预测趋势: {rec.parameters.get('predicted_trend', 'unknown')}
├ 网格数量: {rec.parameters.get('grid_num', 0)}
├ 预期年化收益: {rec.expected_annual_return:.1%}
└ 推荐置信度: {rec.confidence:.0f}%
""")
                    
                    message_parts.append("\n⚠️ 注：此网格机会基于Kronos AI预测分析生成，请谨慎操作")
                    
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
    
    async def _market_opportunities_job(self):
        """市场交易机会分析任务"""
        try:
            monitor_logger.info("Executing scheduled market opportunities analysis")
            position_service = self._get_position_analysis_service()
            
            # 执行市场机会分析
            market_analysis = await position_service.analyze_market_opportunities()
            
            if not market_analysis.get("error"):
                # 创建简化的网格分析用于通知
                grid_analysis = {
                    'total_analyzed': 0,
                    'top_opportunities': [],
                    'high_score_count': 0,
                    'avg_annual_return': 0
                }
                
                # 检查是否有值得关注的市场机会
                coin_contracts = market_analysis.get('coin_contracts', [])
                spot_opportunities = market_analysis.get('spot_opportunities', [])
                
                # 统计有积极建议的机会
                positive_contracts = len([c for c in coin_contracts if '适合' in c.get('suggestion', '')])
                positive_spots = len([s for s in spot_opportunities if '买入' in s.get('suggestion', '') or '适合' in s.get('suggestion', '')])
                
                # 只有在发现积极机会时才发送通知
                if positive_contracts > 0 or positive_spots > 0:
                    await position_service.send_market_analysis_notification(grid_analysis, market_analysis)
                    monitor_logger.info(f"Market opportunities notification sent ({positive_contracts} contract + {positive_spots} spot opportunities)")
                else:
                    monitor_logger.info("Market opportunities analysis completed (no significant opportunities)")
            else:
                logger.warning(f"Market opportunities analysis failed: {market_analysis.get('error')}")
            
        except Exception as e:
            logger.error(f"Market opportunities analysis job failed: {e}")
