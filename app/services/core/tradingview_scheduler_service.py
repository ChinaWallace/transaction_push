# -*- coding: utf-8 -*-
"""
TradingView 定时调度服务
TradingView Scheduler Service

负责TradingView扫描的定时调度，包括启动时执行和每小时执行
"""

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.analysis.tradingview_scanner_service import get_tradingview_scanner_service
from app.utils.exceptions import TradingToolError


class TradingViewSchedulerService:
    """TradingView 定时调度服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.initialized = False
        
        # 调度器
        self.scheduler: Optional[AsyncIOScheduler] = None
        
        # TradingView扫描服务
        self.scanner_service = None
        
        # 执行统计
        self.execution_stats = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "last_execution": None,
            "last_success": None,
            "last_error": None
        }
    
    async def initialize(self) -> None:
        """初始化调度服务"""
        if self.initialized:
            return
        
        try:
            # 初始化TradingView扫描服务
            self.scanner_service = await get_tradingview_scanner_service()
            
            # 创建调度器
            self.scheduler = AsyncIOScheduler(
                timezone="Asia/Shanghai",
                job_defaults={
                    'coalesce': True,  # 合并多个相同的任务
                    'max_instances': 1,  # 同一时间只运行一个实例
                    'misfire_grace_time': 300  # 错过执行时间的宽限期(秒)
                }
            )
            
            # 添加定时任务
            await self._setup_scheduled_jobs()
            
            self.initialized = True
            self.logger.info("✅ TradingView定时调度服务初始化完成")
            
        except Exception as e:
            self.logger.error(f"❌ TradingView定时调度服务初始化失败: {e}")
            raise TradingToolError(f"调度服务初始化失败: {str(e)}") from e
    
    async def _setup_scheduled_jobs(self) -> None:
        """设置定时任务"""
        try:
            # 每小时执行一次TradingView扫描
            self.scheduler.add_job(
                func=self._execute_hourly_scan,
                trigger=CronTrigger(minute=0),  # 每小时的0分执行
                id="tradingview_hourly_scan",
                name="TradingView每小时扫描",
                replace_existing=True
            )
            
            # 每天早上9点执行一次完整扫描
            self.scheduler.add_job(
                func=self._execute_daily_scan,
                trigger=CronTrigger(hour=9, minute=0),
                id="tradingview_daily_scan", 
                name="TradingView每日扫描",
                replace_existing=True
            )
            
            # 启动后延迟5分钟执行一次初始扫描
            startup_time = datetime.now() + timedelta(minutes=5)
            self.scheduler.add_job(
                func=self._execute_startup_scan,
                trigger="date",
                run_date=startup_time,
                id="tradingview_startup_scan",
                name="TradingView启动扫描",
                replace_existing=True
            )
            
            self.logger.info("✅ TradingView定时任务设置完成")
            
        except Exception as e:
            self.logger.error(f"❌ 设置定时任务失败: {e}")
            raise
    
    async def start_scheduler(self) -> None:
        """启动调度器"""
        if not self.initialized:
            await self.initialize()
        
        try:
            if self.scheduler and not self.scheduler.running:
                self.scheduler.start()
                self.logger.info("✅ TradingView调度器已启动")
                
                # 立即执行一次启动扫描
                await self._execute_startup_scan()
            else:
                self.logger.warning("调度器已在运行或未初始化")
                
        except Exception as e:
            self.logger.error(f"❌ 启动调度器失败: {e}")
            raise TradingToolError(f"启动调度器失败: {str(e)}") from e
    
    async def stop_scheduler(self) -> None:
        """停止调度器"""
        try:
            if self.scheduler and self.scheduler.running:
                self.scheduler.shutdown(wait=True)
                self.logger.info("✅ TradingView调度器已停止")
            else:
                self.logger.info("调度器未运行")
                
        except Exception as e:
            self.logger.error(f"❌ 停止调度器失败: {e}")
    
    async def _execute_startup_scan(self) -> None:
        """执行启动扫描"""
        await self._execute_scan("startup", "启动扫描")
    
    async def _execute_hourly_scan(self) -> None:
        """执行每小时扫描"""
        await self._execute_scan("hourly", "每小时扫描")
    
    async def _execute_daily_scan(self) -> None:
        """执行每日扫描"""
        await self._execute_scan("daily", "每日扫描")
    
    async def _execute_scan(self, scan_type: str, scan_name: str) -> None:
        """
        执行扫描任务
        Execute scan task
        
        Args:
            scan_type: 扫描类型
            scan_name: 扫描名称
        """
        execution_start = datetime.now()
        self.execution_stats["total_executions"] += 1
        self.execution_stats["last_execution"] = execution_start
        
        try:
            self.logger.info(f"🚀 开始执行TradingView {scan_name}")
            
            if not self.scanner_service:
                raise TradingToolError("扫描服务未初始化")
            
            # 执行扫描并发送通知
            success = await self.scanner_service.scan_and_notify()
            
            if success:
                self.execution_stats["successful_executions"] += 1
                self.execution_stats["last_success"] = execution_start
                
                execution_time = (datetime.now() - execution_start).total_seconds()
                self.logger.info(f"✅ TradingView {scan_name}执行成功，耗时 {execution_time:.2f}秒")
            else:
                self.execution_stats["failed_executions"] += 1
                self.execution_stats["last_error"] = f"{scan_name}执行失败"
                self.logger.warning(f"⚠️ TradingView {scan_name}执行失败")
                
        except Exception as e:
            self.execution_stats["failed_executions"] += 1
            self.execution_stats["last_error"] = str(e)
            
            execution_time = (datetime.now() - execution_start).total_seconds()
            self.logger.error(f"❌ TradingView {scan_name}执行异常，耗时 {execution_time:.2f}秒: {e}")
    
    async def execute_manual_scan(self) -> Dict[str, Any]:
        """
        手动执行扫描
        Execute manual scan
        
        Returns:
            Dict: 执行结果
        """
        try:
            self.logger.info("🔧 手动执行TradingView扫描")
            
            if not self.scanner_service:
                raise TradingToolError("扫描服务未初始化")
            
            # 执行扫描
            scan_result = await self.scanner_service.scan_strong_symbols()
            
            # 发送通知
            if scan_result.success and scan_result.symbols:
                notification_success = await self.scanner_service.scan_and_notify()
            else:
                notification_success = True  # 没有数据时也算成功
            
            return {
                "success": scan_result.success and notification_success,
                "scan_result": {
                    "total_symbols": scan_result.total_count,
                    "symbols": [s.symbol for s in scan_result.symbols],
                    "scan_time": scan_result.scan_time.isoformat()
                },
                "notification_sent": notification_success,
                "execution_time": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ 手动扫描失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "execution_time": datetime.now().isoformat()
            }
    
    async def get_scheduler_status(self) -> Dict[str, Any]:
        """获取调度器状态"""
        try:
            jobs_info = []
            
            if self.scheduler:
                for job in self.scheduler.get_jobs():
                    jobs_info.append({
                        "id": job.id,
                        "name": job.name,
                        "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                        "trigger": str(job.trigger)
                    })
            
            return {
                "initialized": self.initialized,
                "scheduler_running": self.scheduler.running if self.scheduler else False,
                "jobs": jobs_info,
                "execution_stats": self.execution_stats.copy(),
                "status_time": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ 获取调度器状态失败: {e}")
            return {
                "initialized": self.initialized,
                "error": str(e),
                "status_time": datetime.now().isoformat()
            }
    
    async def scan_and_notify(self) -> Dict[str, Any]:
        """
        执行扫描并通知 - 用于启动时调用
        Execute scan and notify - for startup call
        
        Returns:
            Dict: 执行结果
        """
        try:
            self.logger.info("🚀 执行TradingView扫描并通知")
            
            if not self.scanner_service:
                self.scanner_service = await get_tradingview_scanner_service()
            
            # 执行扫描
            scan_result = await self.scanner_service.scan_strong_symbols()
            
            if not scan_result.success:
                return {
                    "status": "error",
                    "error": scan_result.message,
                    "symbols_count": 0,
                    "execution_time": datetime.now().isoformat()
                }
            
            # 发送通知
            notification_success = False
            if scan_result.symbols:
                # 构建通知消息
                from app.schemas.tradingview import TradingViewNotificationMessage
                notification_message = TradingViewNotificationMessage(
                    symbols=scan_result.symbols,
                    scan_time=scan_result.scan_time
                )
                
                # 发送通知
                if self.scanner_service.notification_service:
                    message_text = notification_message.format_message()
                    await self.scanner_service.notification_service.send_notification(
                        message=message_text
                    )
                    notification_success = True
                    self.logger.info(f"✅ 已发送TradingView扫描通知，包含 {len(scan_result.symbols)} 个标的")
                else:
                    self.logger.warning("通知服务未初始化")
                    notification_success = False
            else:
                notification_success = True  # 没有数据时也算成功
            
            return {
                "status": "success",
                "symbols_count": scan_result.total_count,
                "symbols": [s.symbol for s in scan_result.symbols[:10]],  # 只返回前10个
                "notification_sent": notification_success,
                "execution_time": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ 扫描并通知失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "symbols_count": 0,
                "execution_time": datetime.now().isoformat()
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            scheduler_healthy = (
                self.initialized and 
                self.scheduler is not None and 
                self.scheduler.running
            )
            
            scanner_health = None
            if self.scanner_service:
                scanner_health = await self.scanner_service.health_check()
            
            # 检查最近执行情况
            recent_execution_healthy = True
            if self.execution_stats["last_execution"]:
                time_since_last = datetime.now() - self.execution_stats["last_execution"]
                # 如果超过2小时没有执行，认为不健康
                recent_execution_healthy = time_since_last < timedelta(hours=2)
            
            overall_healthy = (
                scheduler_healthy and 
                scanner_health and scanner_health.get("status") == "healthy" and
                recent_execution_healthy
            )
            
            return {
                "status": "healthy" if overall_healthy else "unhealthy",
                "scheduler_healthy": scheduler_healthy,
                "scanner_healthy": scanner_health.get("status") if scanner_health else "unknown",
                "recent_execution_healthy": recent_execution_healthy,
                "execution_stats": self.execution_stats.copy(),
                "last_check": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "last_check": datetime.now().isoformat()
            }


# 全局服务实例
_tradingview_scheduler_service: Optional[TradingViewSchedulerService] = None


async def get_tradingview_scheduler_service() -> TradingViewSchedulerService:
    """获取TradingView调度服务实例 - 单例模式"""
    global _tradingview_scheduler_service
    if _tradingview_scheduler_service is None:
        _tradingview_scheduler_service = TradingViewSchedulerService()
        await _tradingview_scheduler_service.initialize()
    return _tradingview_scheduler_service