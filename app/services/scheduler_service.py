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
    
    def _get_monitor_service(self):
        """获取监控服务实例"""
        if self._monitor_service is None:
            from app.services.monitor_service import MonitorService
            self._monitor_service = MonitorService()
        return self._monitor_service
    
    def _get_trend_service(self):
        """获取趋势分析服务实例"""
        if self._trend_service is None:
            from app.services.trend_analysis_service import TrendAnalysisService
            self._trend_service = TrendAnalysisService()
        return self._trend_service
    
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
            
            # 监控主要交易对
            major_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT"]
            result = await monitor_service.monitor_open_interest(major_symbols, notify=True)
            
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
            
            # 分析主要交易对的趋势
            major_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT"]
            
            results = await trend_service.analyze_batch_symbols(major_symbols)
            
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
            from app.services.binance_service import BinanceService
            
            db_healthy = db_manager.health_check()
            
            binance_service = BinanceService()
            api_healthy = await binance_service.health_check()
            
            # 如果有严重问题，发送警报
            if not db_healthy or not api_healthy:
                from app.services.notification_service import NotificationService
                notification_service = NotificationService()
                
                error_message = f"""🚨 系统健康检查警报

⏰ 检查时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

❌ 发现问题：
• 数据库：{'正常' if db_healthy else '异常'}
• 币安API：{'正常' if api_healthy else '异常'}

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
