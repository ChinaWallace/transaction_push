# -*- coding: utf-8 -*-
"""
核心调度服务
Core Scheduler Service - 统一管理所有定时任务和核心服务调度
整合原有调度功能，管理新的核心服务
"""

import asyncio
from typing import Dict, Any, List, Callable, Optional
from datetime import datetime, timedelta
from enum import Enum
import traceback

from app.core.config import get_settings
from app.core.logging import get_logger, monitor_logger, trading_logger
from app.services.notification.core_notification_service import get_core_notification_service
# Lazy import to avoid circular imports
# from app.services.trading.core_trading_service import get_core_trading_service
from app.services.core_monitoring_service import get_core_monitoring_service
from app.services.core.core_opportunity_service import get_core_opportunity_service
from app.services.core.core_backtest_service import get_core_backtest_service

logger = get_logger(__name__)
settings = get_settings()


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DISABLED = "disabled"


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class ScheduledTask:
    """调度任务"""
    
    def __init__(
        self,
        task_id: str,
        name: str,
        func: Callable,
        interval_minutes: int,
        priority: TaskPriority = TaskPriority.NORMAL,
        enabled: bool = True,
        max_retries: int = 3,
        timeout_minutes: int = 30,
        description: str = ""
    ):
        self.task_id = task_id
        self.name = name
        self.func = func
        self.interval_minutes = interval_minutes
        self.priority = priority
        self.enabled = enabled
        self.max_retries = max_retries
        self.timeout_minutes = timeout_minutes
        self.description = description
        
        # 运行时状态
        self.status = TaskStatus.PENDING
        self.last_run_time = None
        self.next_run_time = datetime.now()
        self.run_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.current_retries = 0
        self.last_error = None
        self.last_duration = 0
        self.is_running = False


class CoreSchedulerService:
    """核心调度服务类 - 统一任务调度管理"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # 核心服务实例
        self.notification_service = None
        self.trading_service = None
        self.monitoring_service = None
        self.opportunity_service = None
        self.backtest_service = None
        
        # 任务管理
        self.tasks: Dict[str, ScheduledTask] = {}
        self.running = False
        self.scheduler_task = None
        
        # 核心币种推送状态
        self.startup_push_completed = False
        
        # 性能统计
        self.stats = {
            'total_tasks_run': 0,
            'total_successes': 0,
            'total_failures': 0,
            'average_duration': 0,
            'last_cycle_time': None
        }
        
        # 初始化所有定时任务
        self._initialize_tasks()
    
    def _initialize_tasks(self):
        """初始化所有定时任务"""
        
        # 1. 监控任务 - 最高优先级
        self.register_task(
            task_id="core_monitoring",
            name="核心监控",
            func=self._run_core_monitoring,
            interval_minutes=30,  # 每30分钟监控一次
            priority=TaskPriority.CRITICAL,
            description="综合监控费率、系统健康等"
        )
        
        # 2. 机会扫描任务 - 高优先级
        self.register_task(
            task_id="opportunity_scan",
            name="机会扫描",
            func=self._run_opportunity_scan,
            interval_minutes=60,  # 每小时扫描一次
            priority=TaskPriority.HIGH,
            description="扫描交易机会、网格机会等"
        )
        
        # 3. 持仓分析任务 - 正常优先级
        self.register_task(
            task_id="position_analysis",
            name="持仓分析",
            func=self._run_position_analysis,
            interval_minutes=120,  # 每2小时分析一次
            priority=TaskPriority.NORMAL,
            description="分析当前持仓状况"
        )
        
        # 4. 核心币种推送任务 - 高优先级
        self.register_task(
            task_id="core_symbols_push",
            name="核心币种推送",
            func=self._run_core_symbols_push,
            interval_minutes=60,  # 每小时推送一次
            priority=TaskPriority.HIGH,
            description="推送核心币种操作建议"
        )
        
        # 5. 系统报告任务 - 低优先级
        self.register_task(
            task_id="daily_report",
            name="每日报告",
            func=self._run_daily_report,
            interval_minutes=1440,  # 每24小时一次
            priority=TaskPriority.LOW,
            description="生成每日系统报告"
        )
        
        # 6. 健康检查任务 - 高优先级
        self.register_task(
            task_id="health_check",
            name="健康检查",
            func=self._run_health_check,
            interval_minutes=15,  # 每15分钟检查一次
            priority=TaskPriority.HIGH,
            description="系统健康状态检查"
        )
    
    def register_task(
        self,
        task_id: str,
        name: str,
        func: Callable,
        interval_minutes: int,
        priority: TaskPriority = TaskPriority.NORMAL,
        enabled: bool = True,
        max_retries: int = 3,
        timeout_minutes: int = 30,
        description: str = ""
    ) -> bool:
        """
        注册定时任务
        
        Args:
            task_id: 任务ID
            name: 任务名称
            func: 任务函数
            interval_minutes: 执行间隔（分钟）
            priority: 优先级
            enabled: 是否启用
            max_retries: 最大重试次数
            timeout_minutes: 超时时间（分钟）
            description: 任务描述
            
        Returns:
            是否注册成功
        """
        try:
            if task_id in self.tasks:
                self.logger.warning(f"任务 {task_id} 已存在，将被覆盖")
            
            task = ScheduledTask(
                task_id=task_id,
                name=name,
                func=func,
                interval_minutes=interval_minutes,
                priority=priority,
                enabled=enabled,
                max_retries=max_retries,
                timeout_minutes=timeout_minutes,
                description=description
            )
            
            self.tasks[task_id] = task
            self.logger.info(f"✅ 已注册任务: {name} (间隔: {interval_minutes}分钟)")
            
            return True
            
        except Exception as e:
            self.logger.error(f"注册任务失败 {task_id}: {e}")
            return False
    
    async def start_scheduler(self):
        """启动调度器"""
        if self.running:
            self.logger.warning("调度器已经在运行")
            return
        
        self.running = True
        self.logger.info("🚀 启动核心调度器...")
        
        # 初始化核心服务
        await self._initialize_core_services()
        
        # 启动调度循环
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        
        self.logger.info("✅ 核心调度器启动成功")
    
    async def stop_scheduler(self):
        """停止调度器"""
        if not self.running:
            return
        
        self.running = False
        self.logger.info("🛑 停止核心调度器...")
        
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("✅ 核心调度器已停止")
    
    async def _initialize_core_services(self):
        """初始化核心服务"""
        try:
            self.logger.info("🔧 初始化核心服务...")
            
            # 并行初始化服务
            # Lazy import to avoid circular imports
            from app.services.trading.core_trading_service import get_core_trading_service
            
            services = await asyncio.gather(
                get_core_notification_service(),
                get_core_trading_service(),
                get_core_monitoring_service(),
                get_core_opportunity_service(),
                get_core_backtest_service(),
                return_exceptions=True
            )
            
            self.notification_service = services[0] if not isinstance(services[0], Exception) else None
            self.trading_service = services[1] if not isinstance(services[1], Exception) else None
            self.monitoring_service = services[2] if not isinstance(services[2], Exception) else None
            self.opportunity_service = services[3] if not isinstance(services[3], Exception) else None
            self.backtest_service = services[4] if not isinstance(services[4], Exception) else None
            
            # 记录初始化结果
            service_status = {
                'notification': self.notification_service is not None,
                'trading': self.trading_service is not None,
                'monitoring': self.monitoring_service is not None,
                'opportunity': self.opportunity_service is not None,
                'backtest': self.backtest_service is not None
            }
            
            successful_services = sum(service_status.values())
            self.logger.info(f"✅ 核心服务初始化完成: {successful_services}/5 个服务成功")
            
            for service_name, success in service_status.items():
                if not success:
                    self.logger.warning(f"⚠️ {service_name}服务初始化失败")
            
        except Exception as e:
            self.logger.error(f"初始化核心服务失败: {e}")
    
    async def _scheduler_loop(self):
        """调度器主循环"""
        self.logger.info("📅 调度器主循环开始")
        
        while self.running:
            try:
                cycle_start = datetime.now()
                
                # 获取需要执行的任务
                pending_tasks = self._get_pending_tasks()
                
                if pending_tasks:
                    # 按优先级排序
                    pending_tasks.sort(key=lambda t: t.priority.value, reverse=True)
                    
                    # 并行执行任务（根据优先级分组）
                    await self._execute_tasks_by_priority(pending_tasks)
                
                # 更新统计信息
                (datetime.now() - cycle_start).total_seconds()
                self.stats['last_cycle_time'] = cycle_start
                
                # 等待下一个检查周期（1分钟）
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"调度器循环异常: {e}")
                await asyncio.sleep(60)
        
        self.logger.info("📅 调度器主循环结束")
    
    def _get_pending_tasks(self) -> List[ScheduledTask]:
        """获取需要执行的任务"""
        now = datetime.now()
        pending_tasks = []
        
        for task in self.tasks.values():
            if not task.enabled or task.is_running:
                continue
            
            if now >= task.next_run_time:
                pending_tasks.append(task)
        
        return pending_tasks
    
    async def _execute_tasks_by_priority(self, tasks: List[ScheduledTask]):
        """按优先级执行任务"""
        # 分组执行任务
        critical_tasks = [t for t in tasks if t.priority == TaskPriority.CRITICAL]
        high_tasks = [t for t in tasks if t.priority == TaskPriority.HIGH]
        normal_tasks = [t for t in tasks if t.priority == TaskPriority.NORMAL]
        low_tasks = [t for t in tasks if t.priority == TaskPriority.LOW]
        
        # 按优先级顺序执行
        for task_group in [critical_tasks, high_tasks, normal_tasks, low_tasks]:
            if task_group:
                # 同优先级任务并行执行（最多3个）
                for i in range(0, len(task_group), 3):
                    batch = task_group[i:i+3]
                    await asyncio.gather(
                        *[self._execute_single_task(task) for task in batch],
                        return_exceptions=True
                    )
    
    async def _execute_single_task(self, task: ScheduledTask):
        """执行单个任务"""
        task.is_running = True
        task.status = TaskStatus.RUNNING
        start_time = datetime.now()
        
        try:
            self.logger.info(f"⏰ 开始执行任务: {task.name}")
            
            # 设置超时
            timeout = task.timeout_minutes * 60
            result = await asyncio.wait_for(task.func(), timeout=timeout)
            
            # 任务成功
            task.status = TaskStatus.COMPLETED
            task.success_count += 1
            task.current_retries = 0
            task.last_error = None
            
            # 更新下次执行时间
            task.next_run_time = datetime.now() + timedelta(minutes=task.interval_minutes)
            
            duration = (datetime.now() - start_time).total_seconds()
            task.last_duration = duration
            
            self.logger.info(f"✅ 任务完成: {task.name} (耗时 {duration:.1f}秒)")
            
            # 更新统计
            self.stats['total_successes'] += 1
            
        except asyncio.TimeoutError:
            self.logger.error(f"⏰ 任务超时: {task.name} (超过 {task.timeout_minutes} 分钟)")
            await self._handle_task_failure(task, "任务执行超时")
            
        except Exception as e:
            error_msg = f"任务执行失败: {str(e)}"
            self.logger.error(f"❌ {task.name} - {error_msg}")
            self.logger.debug(f"错误详情: {traceback.format_exc()}")
            await self._handle_task_failure(task, error_msg)
            
        finally:
            task.is_running = False
            task.last_run_time = start_time
            task.run_count += 1
            self.stats['total_tasks_run'] += 1
    
    async def _handle_task_failure(self, task: ScheduledTask, error_msg: str):
        """处理任务失败"""
        task.status = TaskStatus.FAILED
        task.failure_count += 1
        task.current_retries += 1
        task.last_error = error_msg
        
        # 检查是否需要重试
        if task.current_retries <= task.max_retries:
            # 延迟重试（指数退避）
            retry_delay = min(300, 60 * (2 ** (task.current_retries - 1)))  # 最多5分钟
            task.next_run_time = datetime.now() + timedelta(seconds=retry_delay)
            self.logger.info(f"🔄 任务 {task.name} 将在 {retry_delay} 秒后重试 ({task.current_retries}/{task.max_retries})")
        else:
            # 重试次数用完，等待下一个正常周期
            task.next_run_time = datetime.now() + timedelta(minutes=task.interval_minutes)
            task.current_retries = 0
            self.logger.error(f"❌ 任务 {task.name} 重试次数用完，等待下一个周期")
            
            # 发送任务失败通知
            await self._send_task_failure_notification(task, error_msg)
        
        # 更新统计
        self.stats['total_failures'] += 1
    
    async def _send_task_failure_notification(self, task: ScheduledTask, error_msg: str):
        """发送任务失败通知"""
        try:
            if self.notification_service:
                from app.services.notification.core_notification_service import NotificationContent, NotificationType, NotificationPriority
                
                content = NotificationContent(
                    type=NotificationType.SYSTEM_ALERT,
                    priority=NotificationPriority.HIGH,
                    title=f"⚠️ 任务执行失败 - {task.name}",
                    message=f"任务: {task.name}\n错误: {error_msg}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    metadata={'task_id': task.task_id, 'error': error_msg}
                )
                
                await self.notification_service.send_notification(content)
            
        except Exception as e:
            self.logger.error(f"发送任务失败通知失败: {e}")
    
    # ========== 核心任务实现 ==========
    
    async def _run_core_monitoring(self) -> Dict[str, Any]:
        """运行核心监控任务"""
        if not self.monitoring_service:
            raise Exception("监控服务未初始化")
        
        monitor_logger.info("🔍 执行核心监控任务")
        result = await self.monitoring_service.run_comprehensive_monitoring_cycle()
        
        monitor_logger.info(
            f"监控任务完成: 发现 {result.get('total_opportunities', 0)} 个机会, "
            f"发送 {result.get('total_notifications', 0)} 个通知"
        )
        
        return result
    
    async def _run_opportunity_scan(self) -> Dict[str, Any]:
        """运行机会扫描任务"""
        if not self.opportunity_service:
            raise Exception("机会服务未初始化")
        
        trading_logger.info("🎯 执行机会扫描任务")
        result = await self.opportunity_service.scan_all_opportunities(force_scan=True)
        
        trading_logger.info(
            f"机会扫描完成: 发现 {result.get('total_opportunities', 0)} 个机会, "
            f"高质量机会 {result.get('high_quality_opportunities', 0)} 个"
        )
        
        return result
    
    async def _run_position_analysis(self) -> Dict[str, Any]:
        """运行持仓分析任务"""
        if not self.trading_service:
            raise Exception("交易服务未初始化")
        
        trading_logger.info("💼 执行持仓分析任务")
        result = await self.trading_service.get_comprehensive_position_analysis()
        
        if result:
            trading_logger.info(
                f"持仓分析完成: {result.total_positions} 个持仓, "
                f"总盈亏 {result.total_pnl_percent:.1f}%, "
                f"风险等级 {result.risk_level}"
            )
            
            # 发送持仓分析通知（如果有重要信息）
            if result.urgent_actions or result.total_pnl_percent < -10:
                analysis_data = {
                    'total_positions': result.total_positions,
                    'total_pnl_percent': result.total_pnl_percent,
                    'risk_level': result.risk_level,
                    'urgent_actions': result.urgent_actions,
                    'recommendations': result.recommendations
                }
                
                if self.notification_service:
                    await self.notification_service.send_position_analysis(analysis_data)
        
        return {'status': 'success', 'result': result}
    
    async def _run_core_symbols_push(self) -> Dict[str, Any]:
        """运行核心币种推送任务"""
        if not self.trading_service:
            raise Exception("交易服务未初始化")
        
        trading_logger.info("📊 执行核心币种推送任务")
        
        try:
            # 获取核心币种分析
            signals = await self.trading_service.get_core_symbols_analysis()
            
            if signals and len(signals) > 0:
                # 发送核心币种报告
                success = await self.trading_service.send_core_symbols_report()
                
                trading_logger.info(
                    f"核心币种推送完成: 分析 {len(signals)} 个币种, "
                    f"成功 {len(signals)} 个, "
                    f"通知发送: {'成功' if success else '失败'}"
                )
                
                return {
                    'status': 'success',
                    'total_symbols': len(signals),
                    'successful_analyses': len(signals),
                    'notification_sent': success,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                trading_logger.warning("核心币种分析失败或无有效结果")
                return {
                    'status': 'warning',
                    'message': '核心币种分析失败或无有效结果',
                    'timestamp': datetime.now()
                }
                
        except Exception as e:
            trading_logger.error(f"核心币种推送任务失败: {e}")
            raise
    
    async def _run_daily_report(self) -> Dict[str, Any]:
        """运行每日报告任务"""
        monitor_logger.info("📊 生成每日系统报告")
        
        try:
            # 收集各项统计数据
            report_data = {
                'date': datetime.now().date(),
                'scheduler_stats': self.get_scheduler_stats(),
                'monitoring_summary': None,
                'opportunity_summary': None
            }
            
            # 获取监控摘要
            if self.monitoring_service:
                try:
                    report_data['monitoring_summary'] = await self.monitoring_service.get_monitoring_summary()
                except Exception as e:
                    self.logger.warning(f"获取监控摘要失败: {e}")
            
            # 获取机会摘要
            if self.opportunity_service:
                try:
                    report_data['opportunity_summary'] = await self.opportunity_service.get_opportunity_summary()
                except Exception as e:
                    self.logger.warning(f"获取机会摘要失败: {e}")
            
            # 发送每日报告通知
            if self.notification_service:
                await self._send_daily_report_notification(report_data)
            
            monitor_logger.info("✅ 每日报告生成完成")
            return report_data
            
        except Exception as e:
            monitor_logger.error(f"生成每日报告失败: {e}")
            raise
    
    async def _run_health_check(self) -> Dict[str, Any]:
        """运行健康检查任务"""
        monitor_logger.info("🏥 执行系统健康检查")
        
        health_status = {
            'timestamp': datetime.now(),
            'overall_healthy': True,
            'services': {},
            'tasks': {},
            'issues': []
        }
        
        # 检查核心服务状态
        services = {
            'notification': self.notification_service,
            'trading': self.trading_service,
            'monitoring': self.monitoring_service,
            'opportunity': self.opportunity_service,
            'backtest': self.backtest_service
        }
        
        for service_name, service in services.items():
            is_healthy = service is not None
            health_status['services'][service_name] = is_healthy
            
            if not is_healthy:
                health_status['overall_healthy'] = False
                health_status['issues'].append(f"{service_name}服务未初始化")
        
        # 检查任务状态
        failed_tasks = []
        for task in self.tasks.values():
            if task.enabled and task.status == TaskStatus.FAILED:
                failed_tasks.append(task.name)
        
        if failed_tasks:
            health_status['overall_healthy'] = False
            health_status['issues'].extend([f"任务失败: {name}" for name in failed_tasks])
        
        health_status['tasks'] = {
            'total': len(self.tasks),
            'enabled': len([t for t in self.tasks.values() if t.enabled]),
            'failed': len(failed_tasks),
            'running': len([t for t in self.tasks.values() if t.is_running])
        }
        
        # 如果有严重问题，发送警报
        if not health_status['overall_healthy']:
            await self._send_health_alert(health_status)
        
        return health_status
    
    async def _send_health_alert(self, health_status: Dict[str, Any]):
        """发送健康检查警报"""
        try:
            if self.notification_service:
                from app.services.notification.core_notification_service import NotificationContent, NotificationType, NotificationPriority
                
                issues_text = "\n".join(health_status['issues'])
                
                content = NotificationContent(
                    type=NotificationType.SYSTEM_ALERT,
                    priority=NotificationPriority.HIGH,
                    title="🚨 系统健康检查警报",
                    message=f"发现系统问题:\n{issues_text}\n\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    metadata=health_status
                )
                
                await self.notification_service.send_notification(content)
            
        except Exception as e:
            self.logger.error(f"发送健康检查警报失败: {e}")
    
    async def _send_daily_report_notification(self, report_data: Dict[str, Any]):
        """发送每日报告通知"""
        try:
            if self.notification_service:
                from app.services.notification.core_notification_service import NotificationContent, NotificationType, NotificationPriority
                
                # 构建报告消息
                stats = report_data['scheduler_stats']
                message = f"📊 **每日系统报告** - {report_data['date']}\n\n"
                message += f"🔧 **调度器统计**\n"
                message += f"• 总任务执行: {stats['total_tasks_run']}\n"
                message += f"• 成功: {stats['total_successes']}\n"
                message += f"• 失败: {stats['total_failures']}\n"
                message += f"• 成功率: {stats.get('success_rate', 0):.1f}%\n\n"
                
                if report_data.get('monitoring_summary'):
                    message += f"🔍 **监控摘要**\n"
                    # 添加监控摘要信息
                
                if report_data.get('opportunity_summary'):
                    message += f"🎯 **机会摘要**\n"
                    # 添加机会摘要信息
                
                content = NotificationContent(
                    type=NotificationType.SYSTEM_ALERT,
                    priority=NotificationPriority.NORMAL,
                    title="📊 每日系统报告",
                    message=message,
                    metadata=report_data
                )
                
                await self.notification_service.send_notification(content)
            
        except Exception as e:
            self.logger.error(f"发送每日报告通知失败: {e}")
    
    # ========== 启动时核心币种推送 ==========
    
    async def run_startup_core_symbols_push(self) -> bool:
        """执行启动时核心币种推送"""
        try:
            self.logger.info("🚀 执行启动时核心币种推送...")
            
            # 确保交易服务已初始化
            if not self.trading_service:
                await self._initialize_core_services()
            
            if not self.trading_service:
                self.logger.error("❌ 交易服务未初始化，无法执行核心币种推送")
                return False
            
            # 执行核心币种推送任务
            result = await self._run_core_symbols_push()
            
            if result.get('status') == 'success':
                self.startup_push_completed = True
                self.logger.info("✅ 启动时核心币种推送完成")
                return True
            else:
                self.logger.warning(f"⚠️ 启动时核心币种推送失败: {result.get('message', '未知错误')}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 启动时核心币种推送异常: {e}")
            return False
    
    # ========== 状态查询方法 ==========
    
    def get_scheduler_stats(self) -> Dict[str, Any]:
        """获取调度器统计信息"""
        total_tasks = len(self.tasks)
        enabled_tasks = len([t for t in self.tasks.values() if t.enabled])
        running_tasks = len([t for t in self.tasks.values() if t.is_running])
        failed_tasks = len([t for t in self.tasks.values() if t.status == TaskStatus.FAILED])
        
        success_rate = 0
        if self.stats['total_tasks_run'] > 0:
            success_rate = (self.stats['total_successes'] / self.stats['total_tasks_run']) * 100
        
        return {
            'total_tasks': total_tasks,
            'enabled_tasks': enabled_tasks,
            'running_tasks': running_tasks,
            'failed_tasks': failed_tasks,
            'total_tasks_run': self.stats['total_tasks_run'],
            'total_successes': self.stats['total_successes'],
            'total_failures': self.stats['total_failures'],
            'success_rate': success_rate,
            'last_cycle_time': self.stats['last_cycle_time'],
            'scheduler_running': self.running,
            'startup_push_completed': self.startup_push_completed
        }
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取特定任务状态"""
        if task_id not in self.tasks:
            return None
        
        task = self.tasks[task_id]
        return {
            'task_id': task.task_id,
            'name': task.name,
            'status': task.status.value,
            'enabled': task.enabled,
            'is_running': task.is_running,
            'last_run_time': task.last_run_time,
            'next_run_time': task.next_run_time,
            'run_count': task.run_count,
            'success_count': task.success_count,
            'failure_count': task.failure_count,
            'last_error': task.last_error,
            'last_duration': task.last_duration,
            'interval_minutes': task.interval_minutes,
            'priority': task.priority.name,
            'description': task.description
        }
    
    def get_all_tasks_status(self) -> Dict[str, Dict[str, Any]]:
        """获取所有任务状态"""
        return {
            task_id: self.get_task_status(task_id)
            for task_id in self.tasks.keys()
        }


# 全局单例实例
_core_scheduler_service: Optional[CoreSchedulerService] = None

async def get_core_scheduler_service() -> CoreSchedulerService:
    """获取核心调度服务实例"""
    global _core_scheduler_service
    if _core_scheduler_service is None:
        _core_scheduler_service = CoreSchedulerService()
    return _core_scheduler_service