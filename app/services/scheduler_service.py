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
            # 资金费率监控 - 每4小时执行一次
            self.scheduler.add_job(
                self._funding_rate_job,
                trigger=IntervalTrigger(minutes=settings.funding_rate_interval),
                id="funding_rate_monitor",
                name="资金费率监控",
                max_instances=1
            )
            
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
            
            # 持仓分析 - 每2小时执行一次
            self.scheduler.add_job(
                self._position_analysis_job,
                trigger=IntervalTrigger(minutes=settings.position_analysis_interval),
                id="position_analysis",
                name="持仓分析",
                max_instances=1
            )
            
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
            
            # ML异常检测 - 每15分钟执行一次
            self.scheduler.add_job(
                self._ml_anomaly_detection_job,
                trigger=IntervalTrigger(minutes=15),
                id="ml_anomaly_detection",
                name="ML异常检测",
                max_instances=1
            )
            
            # ML模型重训练 - 每天凌晨2点执行
            self.scheduler.add_job(
                self._ml_model_retrain_job,
                trigger=CronTrigger(hour=2, minute=0),
                id="ml_model_retrain",
                name="ML模型重训练",
                max_instances=1
            )
            
            logger.info("Scheduled jobs setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup scheduled jobs: {e}")
            raise
    
    async def _funding_rate_job(self):
        """资金费率监控任务"""
        try:
            monitor_logger.info("Executing scheduled funding rate monitoring")
            monitor_service = self._get_monitor_service()
            
            result = await monitor_service.monitor_funding_rate(notify=True)
            
            monitor_logger.info(
                f"Funding rate monitoring completed: {result['negative_count']} negative, "
                f"{result['high_positive_count']} high positive rates"
            )
            
        except Exception as e:
            logger.error(f"Funding rate monitoring job failed: {e}")
    
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
        """趋势分析任务"""
        try:
            monitor_logger.info("Executing scheduled trend analysis")
            trend_service = self._get_trend_service()
            
            # 分析配置的交易对趋势
            symbols = settings.monitored_symbols
            
            results = await trend_service.analyze_batch_symbols(symbols)
            
            # 发送强烈信号通知
            strong_signals = []
            for symbol, result in results.items():
                if not isinstance(result, dict) or 'error' in result:
                    continue
                    
                if result.get('should_notify', False) and result.get('signal_level') == 'strong':
                    strong_signals.append({
                        'symbol': symbol,
                        'signal_data': result
                    })
            
            if strong_signals:
                from app.services.notification_service import NotificationService
                notification_service = NotificationService()
                
                for signal in strong_signals:
                    message = trend_service.format_signal_notification(signal['signal_data'])
                    await notification_service.send_notification(
                        message,
                        priority="high"
                    )
            
            monitor_logger.info(
                f"Trend analysis completed: {len(strong_signals)} strong signals sent"
            )
            
        except Exception as e:
            logger.error(f"Trend analysis job failed: {e}")
    
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
            
            okx_service = OKXService()
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
    
    async def _ml_model_retrain_job(self):
        """ML模型重训练任务"""
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
        """网格交易机会分析任务"""
        try:
            monitor_logger.info("Executing scheduled grid opportunities analysis")
            position_service = self._get_position_analysis_service()
            
            # 执行网格机会分析
            grid_analysis = await position_service.analyze_grid_opportunities()
            
            if not grid_analysis.get("error"):
                high_score_count = grid_analysis.get("high_score_count", 0)
                avg_return = grid_analysis.get("avg_annual_return", 0)
                
                # 只有在发现高分机会时才发送通知
                if high_score_count > 0 or avg_return > 20:
                    # 创建简化的市场分析用于通知
                    market_analysis = {
                        'market_sentiment': '分析中',
                        'coin_contracts': [],
                        'spot_opportunities': []
                    }
                    
                    await position_service.send_market_analysis_notification(grid_analysis, market_analysis)
                    monitor_logger.info(f"Grid opportunities notification sent ({high_score_count} high-score opportunities)")
                else:
                    monitor_logger.info(f"Grid opportunities analysis completed (no high-score opportunities)")
            else:
                logger.warning(f"Grid opportunities analysis failed: {grid_analysis.get('error')}")
            
        except Exception as e:
            logger.error(f"Grid opportunities analysis job failed: {e}")
    
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
