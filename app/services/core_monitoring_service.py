# -*- coding: utf-8 -*-
"""
核心监控服务
Core Monitoring Service - 统一管理费率监控、异常检测和系统监控
整合负费率监控、市场异常检测、系统健康检查等功能
"""

import asyncio
from typing import Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.binance_service import BinanceService
from app.services.notification.core_notification_service import get_core_notification_service
from app.services.negative_funding_monitor_service import NegativeFundingMonitorService
from app.services.monitoring.funding_rate_monitor_service import FundingRateMonitorService

logger = get_logger(__name__)
settings = get_settings()


class MonitoringType(Enum):
    """监控类型"""
    FUNDING_RATE = "funding_rate"
    NEGATIVE_FUNDING = "negative_funding"
    MARKET_ANOMALY = "market_anomaly"
    SYSTEM_HEALTH = "system_health"
    VOLUME_SPIKE = "volume_spike"


class AlertLevel(Enum):
    """警报级别"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class FundingRateOpportunity:
    """费率机会"""
    symbol: str
    current_rate: float
    predicted_rate: float
    opportunity_type: str  # "negative", "extremely_negative", "positive_high"


@dataclass
class OpenInterestData:
    """持仓量数据"""
    symbol: str
    current_oi: float
    change_24h: float
    change_percent: float
    timestamp: datetime
    annual_return: float
    risk_level: str
    description: str
    next_funding_time: datetime
    recommended_action: str
    position_size_usdt: float


@dataclass
class MonitoringResult:
    """监控结果"""
    monitoring_type: MonitoringType
    timestamp: datetime
    total_checked: int
    opportunities_found: int
    alerts_triggered: int
    opportunities: List[FundingRateOpportunity]
    summary: Dict[str, Any]
    notifications_sent: int


class CoreMonitoringService:
    """核心监控服务类 - 统一监控管理"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.binance_service = BinanceService()
        self.notification_service = None
        
        # 整合原有监控服务
        self.negative_funding_service = NegativeFundingMonitorService()
        self.funding_rate_service = FundingRateMonitorService()
        
        # 监控配置
        self.monitoring_config = {
            'negative_funding': {
                'enabled': True,
                'check_interval_minutes': 60,  # 每小时检查一次
                'threshold': -0.0001,  # 任何负费率
                'min_annual_return': 5.0,  # 最低年化收益5%
                'max_notifications_per_day': 10
            },
            'funding_rate': {
                'enabled': True,
                'check_interval_minutes': 30,  # 每30分钟检查一次
                'high_positive_threshold': 0.005,  # 0.5%正费率
                'extremely_negative_threshold': -0.001,  # -0.1%极负费率
                'max_notifications_per_day': 20
            },
            'system_health': {
                'enabled': True,
                'check_interval_minutes': 15,  # 每15分钟检查一次
                'alert_on_api_failure': True,
                'alert_on_db_failure': True
            }
        }
        
        # 监控历史和统计
        self.monitoring_history = {}
        self.daily_notification_counts = {}
        self.last_check_times = {}
        
        # 缓存
        self.symbols_cache = None
        self.symbols_cache_time = None
        self.cache_valid_minutes = 60
    
    async def run_comprehensive_monitoring_cycle(self) -> Dict[str, Any]:
        """运行综合监控周期 - 主要入口"""
        try:
            cycle_start = datetime.now()
            self.logger.info("🚀 开始综合监控周期")
            
            # 重置每日计数（如果需要）
            self._reset_daily_counts_if_needed()
            
            results = {
                'cycle_start': cycle_start,
                'monitoring_results': {},
                'total_opportunities': 0,
                'total_notifications': 0,
                'status': 'success'
            }
            
            # 并行执行各种监控
            monitoring_tasks = []
            
            # 负费率监控和费率监控已由专门的NegativeFundingMonitorService处理
            
            # 系统健康检查
            if self.monitoring_config['system_health']['enabled']:
                if self._should_check('system_health'):
                    monitoring_tasks.append(self._run_system_health_check())
            
            # 执行所有监控任务
            if monitoring_tasks:
                task_results = await asyncio.gather(*monitoring_tasks, return_exceptions=True)
                
                # 处理结果
                for i, result in enumerate(task_results):
                    if isinstance(result, Exception):
                        self.logger.error(f"监控任务失败: {result}")
                    elif result:
                        monitoring_type = result.get('type', f'task_{i}')
                        results['monitoring_results'][monitoring_type] = result
                        results['total_opportunities'] += result.get('opportunities_found', 0)
                        results['total_notifications'] += result.get('notifications_sent', 0)
            
            # 记录监控摘要
            cycle_duration = (datetime.now() - cycle_start).total_seconds()
            results['cycle_duration_seconds'] = cycle_duration
            
            self.logger.info(
                f"✅ 综合监控周期完成: "
                f"发现 {results['total_opportunities']} 个机会, "
                f"发送 {results['total_notifications']} 个通知 "
                f"(耗时 {cycle_duration:.1f}秒)"
            )
            
            return results
            
        except Exception as e:
            self.logger.error(f"综合监控周期失败: {e}")
            return {
                'cycle_start': datetime.now(),
                'status': 'error',
                'error': str(e),
                'total_opportunities': 0,
                'total_notifications': 0
            }
    
    def _should_check(self, monitoring_type: str) -> bool:
        """检查是否应该执行监控"""
        config = self.monitoring_config.get(monitoring_type, {})
        interval_minutes = config.get('check_interval_minutes', 60)
        
        last_check = self.last_check_times.get(monitoring_type)
        if last_check is None:
            return True
        
        time_since_last = datetime.now() - last_check
        return time_since_last >= timedelta(minutes=interval_minutes)
    
    def _reset_daily_counts_if_needed(self):
        """重置每日计数（如果需要）"""
        today = datetime.now().date()
        
        for monitoring_type in self.daily_notification_counts:
            last_date = self.daily_notification_counts[monitoring_type].get('date')
            if last_date != today:
                self.daily_notification_counts[monitoring_type] = {
                    'date': today,
                    'count': 0
                }
    
    async def _run_negative_funding_monitoring(self) -> Dict[str, Any]:
        """运行负费率监控"""
        try:
            self.logger.info("💰 开始负费率监控...")
            
            # 使用原有的负费率监控服务
            result = await self.negative_funding_service.run_monitoring_cycle()
            
            if not result.get('success'):
                return {
                    'type': 'negative_funding',
                    'status': 'error',
                    'error': result.get('error', '未知错误'),
                    'opportunities_found': 0,
                    'notifications_sent': 0
                }
            
            opportunities = result.get('opportunities', [])
            
            # 转换为统一格式
            unified_opportunities = []
            for opp in opportunities:
                unified_opp = FundingRateOpportunity(
                    symbol=opp.get('symbol', ''),
                    current_rate=opp.get('funding_rate', 0),
                    predicted_rate=opp.get('funding_rate', 0),  # 负费率监控没有预测费率
                    opportunity_type="negative_funding",
                    annual_return=opp.get('daily_return_rate', 0) * 365,
                    risk_level=opp.get('risk_level', 'medium'),
                    description=opp.get('description', ''),
                    next_funding_time=datetime.now() + timedelta(hours=8),  # 默认8小时后
                    recommended_action="做多获取费率收益",
                    position_size_usdt=opp.get('suggested_investment', 1000)
                )
                unified_opportunities.append(unified_opp)
            
            # 发送通知
            notifications_sent = 0
            if opportunities and self._can_send_notification('negative_funding'):
                notifications_sent = await self._send_funding_rate_notification(
                    unified_opportunities, "negative_funding"
                )
            
            # 更新检查时间
            self.last_check_times['negative_funding'] = datetime.now()
            
            return {
                'type': 'negative_funding',
                'status': 'success',
                'opportunities_found': len(opportunities),
                'notifications_sent': notifications_sent,
                'opportunities': unified_opportunities,
                'duration_seconds': result.get('duration_seconds', 0),
                'symbols_checked': result.get('total_symbols_checked', 0)
            }
            
        except Exception as e:
            self.logger.error(f"负费率监控失败: {e}")
            return {
                'type': 'negative_funding',
                'status': 'error',
                'error': str(e),
                'opportunities_found': 0,
                'notifications_sent': 0
            }
    
    async def _run_funding_rate_monitoring(self) -> Dict[str, Any]:
        """运行费率监控"""
        try:
            self.logger.info("📊 开始费率监控...")
            
            # 获取活跃交易对
            symbols = await self._get_active_symbols()
            if not symbols:
                return {
                    'type': 'funding_rate',
                    'status': 'error',
                    'error': '无法获取交易对列表',
                    'opportunities_found': 0,
                    'notifications_sent': 0
                }
            
            # 使用原有的费率监控服务
            result = await self.funding_rate_service.monitor_funding_rates(symbols)
            
            alerts = result.get('alerts', [])
            opportunities = []
            
            # 转换警报为机会
            for alert in alerts:
                if alert.severity in ['high', 'critical']:
                    opportunity = FundingRateOpportunity(
                        symbol=alert.symbol,
                        current_rate=alert.current_rate,
                        predicted_rate=alert.predicted_rate,
                        opportunity_type=alert.alert_type,
                        annual_return=abs(alert.current_rate) * 365 * 3,  # 假设每天3次费率
                        risk_level=alert.severity,
                        description=alert.description,
                        next_funding_time=datetime.now() + timedelta(hours=8),
                        recommended_action=self._get_funding_rate_action(alert.alert_type),
                        position_size_usdt=1000
                    )
                    opportunities.append(opportunity)
            
            # 发送通知
            notifications_sent = 0
            if opportunities and self._can_send_notification('funding_rate'):
                notifications_sent = await self._send_funding_rate_notification(
                    opportunities, "funding_rate"
                )
            
            # 更新检查时间
            self.last_check_times['funding_rate'] = datetime.now()
            
            return {
                'type': 'funding_rate',
                'status': 'success',
                'opportunities_found': len(opportunities),
                'notifications_sent': notifications_sent,
                'opportunities': opportunities,
                'symbols_checked': len(symbols),
                'alerts_total': len(alerts)
            }
            
        except Exception as e:
            self.logger.error(f"费率监控失败: {e}")
            return {
                'type': 'funding_rate',
                'status': 'error',
                'error': str(e),
                'opportunities_found': 0,
                'notifications_sent': 0
            }
    
    async def _run_system_health_check(self) -> Dict[str, Any]:
        """运行系统健康检查"""
        try:
            self.logger.info("🔍 开始系统健康检查...")
            
            health_status = {
                'database': True,
                'binance_api': True,
                'notification_service': True,
                'kronos_service': True
            }
            
            issues = []
            
            # 检查 Binance API
            try:
                async with self.binance_service as exchange:
                    test_result = await exchange.health_check()
                    health_status['binance_api'] = test_result
                    if not test_result:
                        issues.append("Binance API连接异常")
            except Exception as e:
                health_status['binance_api'] = False
                issues.append(f"Binance API检查失败: {e}")
            
            # 检查数据库
            try:
                from app.core.database import db_manager
                health_status['database'] = db_manager.health_check()
                if not health_status['database']:
                    issues.append("数据库连接异常")
            except Exception as e:
                health_status['database'] = False
                issues.append(f"数据库检查失败: {e}")
            
            # 检查通知服务
            try:
                if not self.notification_service:
                    self.notification_service = await get_core_notification_service()
                health_status['notification_service'] = True
            except Exception as e:
                health_status['notification_service'] = False
                issues.append(f"通知服务异常: {e}")
            
            # 发送健康检查警报（如果有问题）
            notifications_sent = 0
            if issues:
                notifications_sent = await self._send_system_health_alert(health_status, issues)
            
            # 更新检查时间
            self.last_check_times['system_health'] = datetime.now()
            
            return {
                'type': 'system_health',
                'status': 'success' if not issues else 'warning',
                'health_status': health_status,
                'issues': issues,
                'notifications_sent': notifications_sent,
                'all_healthy': len(issues) == 0
            }
            
        except Exception as e:
            self.logger.error(f"系统健康检查失败: {e}")
            return {
                'type': 'system_health',
                'status': 'error',
                'error': str(e),
                'notifications_sent': 0
            }
    
    async def _get_active_symbols(self) -> List[str]:
        """获取活跃交易对（带缓存）"""
        now = datetime.now()
        
        # 检查缓存是否有效
        if (self.symbols_cache and self.symbols_cache_time and
            (now - self.symbols_cache_time).total_seconds() < self.cache_valid_minutes * 60):
            return self.symbols_cache
        
        try:
            # 获取所有永续合约
            async with self.binance_service as exchange:
                instruments = await exchange.get_raw_instruments('SWAP')
            
            if instruments:
                symbols = [
                    f"{inst['baseAsset']}-USDT-SWAP" for inst in instruments
                    if inst.get('status') == 'TRADING' and inst.get('quoteAsset') == 'USDT'
                ]
                
                # 更新缓存
                self.symbols_cache = symbols
                self.symbols_cache_time = now
                
                self.logger.info(f"获取到 {len(symbols)} 个活跃交易对")
                return symbols
            
            return []
            
        except Exception as e:
            self.logger.error(f"获取活跃交易对失败: {e}")
            return self.symbols_cache or []
    
    def _can_send_notification(self, monitoring_type: str) -> bool:
        """检查是否可以发送通知"""
        config = self.monitoring_config.get(monitoring_type, {})
        max_per_day = config.get('max_notifications_per_day', 10)
        
        today = datetime.now().date()
        
        if monitoring_type not in self.daily_notification_counts:
            self.daily_notification_counts[monitoring_type] = {
                'date': today,
                'count': 0
            }
        
        daily_count = self.daily_notification_counts[monitoring_type]
        
        # 检查日期和计数
        if daily_count['date'] != today:
            daily_count['date'] = today
            daily_count['count'] = 0
        
        return daily_count['count'] < max_per_day
    
    def _get_funding_rate_action(self, alert_type: str) -> str:
        """获取费率操作建议"""
        action_map = {
            'high_negative': '做多获取费率收益',
            'extremely_negative': '做多获取费率收益（强烈推荐）',
            'positive_high': '做空获取费率收益'
        }
        return action_map.get(alert_type, '观察')
    
    async def _send_funding_rate_notification(
        self,
        opportunities: List[FundingRateOpportunity],
        monitoring_type: str
    ) -> int:
        """发送费率机会通知"""
        try:
            if not self.notification_service:
                self.notification_service = await get_core_notification_service()
            
            # 构建通知数据
            funding_data = {
                'opportunities': [
                    {
                        'symbol': opp.symbol,
                        'funding_rate': opp.current_rate,
                        'annual_return': opp.annual_return,
                        'description': opp.description,
                        'recommended_action': opp.recommended_action
                    }
                    for opp in opportunities
                ],
                'monitoring_type': monitoring_type,
                'total_opportunities': len(opportunities),
                'is_urgent': any(opp.opportunity_type == 'extremely_negative' for opp in opportunities)
            }
            
            # 发送通知
            success = await self.notification_service.send_funding_rate_alert(funding_data)
            
            if success:
                # 更新发送计数
                today = datetime.now().date()
                if monitoring_type not in self.daily_notification_counts:
                    self.daily_notification_counts[monitoring_type] = {
                        'date': today,
                        'count': 0
                    }
                self.daily_notification_counts[monitoring_type]['count'] += 1
                
                self.logger.info(f"✅ {monitoring_type}通知发送成功: {len(opportunities)}个机会")
                return 1
            
            return 0
            
        except Exception as e:
            self.logger.error(f"发送费率通知失败: {e}")
            return 0
    
    async def _send_system_health_alert(
        self,
        health_status: Dict[str, bool],
        issues: List[str]
    ) -> int:
        """发送系统健康警报"""
        try:
            if not self.notification_service:
                self.notification_service = await get_core_notification_service()
            
            # 构建警报数据
            alert_data = {
                'health_status': health_status,
                'issues': issues,
                'timestamp': datetime.now(),
                'severity': 'high' if len(issues) > 1 else 'medium'
            }
            
            # 使用系统警报类型
            from app.services.notification.core_notification_service import NotificationContent, NotificationType, NotificationPriority
            
            content = NotificationContent(
                type=NotificationType.SYSTEM_ALERT,
                priority=NotificationPriority.HIGH,
                title="🚨 系统健康检查警报",
                message=f"发现 {len(issues)} 个系统问题:\n" + "\n".join(f"• {issue}" for issue in issues),
                metadata=alert_data
            )
            
            success = await self.notification_service.send_notification(content)
            
            if any(success.values()):
                self.logger.info(f"✅ 系统健康警报发送成功: {len(issues)}个问题")
                return 1
            
            return 0
            
        except Exception as e:
            self.logger.error(f"发送系统健康警报失败: {e}")
            return 0
    
    async def get_monitoring_summary(self) -> Dict[str, Any]:
        """获取监控摘要"""
        try:
            now = datetime.now()
            today = now.date()
            
            summary = {
                'timestamp': now,
                'monitoring_status': {},
                'daily_statistics': {},
                'last_check_times': self.last_check_times.copy(),
                'system_status': 'healthy'
            }
            
            # 检查各监控状态
            for monitoring_type, config in self.monitoring_config.items():
                if config.get('enabled'):
                    last_check = self.last_check_times.get(monitoring_type)
                    interval_minutes = config.get('check_interval_minutes', 60)
                    
                    if last_check:
                        time_since_last = (now - last_check).total_seconds() / 60
                        status = 'normal' if time_since_last < interval_minutes * 2 else 'delayed'
                    else:
                        status = 'not_started'
                    
                    summary['monitoring_status'][monitoring_type] = {
                        'status': status,
                        'last_check': last_check,
                        'interval_minutes': interval_minutes
                    }
            
            # 统计今日通知数量
            for monitoring_type, count_data in self.daily_notification_counts.items():
                if count_data.get('date') == today:
                    summary['daily_statistics'][monitoring_type] = count_data['count']
            
            # 检查系统状态
            delayed_monitors = [
                mt for mt, status in summary['monitoring_status'].items()
                if status['status'] == 'delayed'
            ]
            
            if delayed_monitors:
                summary['system_status'] = 'warning'
                summary['issues'] = [f"{mt}监控延迟" for mt in delayed_monitors]
            
            return summary
            
        except Exception as e:
            self.logger.error(f"获取监控摘要失败: {e}")
            return {
                'timestamp': datetime.now(),
                'system_status': 'error',
                'error': str(e)
            }
    
    async def monitor_open_interest(self, symbols: List[str], notify: bool = True) -> Dict[str, Any]:
        """监控持仓量变化"""
        try:
            self.logger.info(f"开始监控持仓量变化: {symbols}")
            
            results = {}
            significant_changes = []
            
            for symbol in symbols:
                try:
                    # 获取持仓量数据
                    binance_symbol = symbol.replace('-USDT-SWAP', 'USDT').replace('-USDT', 'USDT')
                    oi_data = await self.binance_service.get_open_interest_statistics(binance_symbol, period="1h", limit=24)
                    
                    if oi_data:
                        current_oi = float(oi_data[-1].get('sumOpenInterestValue') or oi_data[-1].get('sumOpenInterest') or 0)
                        start_oi = float(oi_data[0].get('sumOpenInterestValue') or oi_data[0].get('sumOpenInterest') or current_oi)
                        change_24h = current_oi - start_oi
                        
                        # 计算变化百分比
                        if current_oi > 0:
                            change_percent = (change_24h / current_oi) * 100
                        else:
                            change_percent = 0
                        
                        oi_info = OpenInterestData(
                            symbol=symbol,
                            current_oi=current_oi,
                            change_24h=change_24h,
                            change_percent=change_percent,
                            timestamp=datetime.now(),
                            annual_return=0.0,  # 持仓量监控不涉及年化收益
                            risk_level="medium",
                            description=f"持仓量变化 {change_percent:+.2f}%",
                            next_funding_time=datetime.now() + timedelta(hours=8),
                            recommended_action="观察" if abs(change_percent) < 20 else "关注",
                            position_size_usdt=0.0
                        )
                        
                        results[symbol] = {
                            'current_oi': current_oi,
                            'change_24h': change_24h,
                            'change_percent': change_percent,
                            'status': 'normal'
                        }
                        
                        # 检查是否有显著变化 (>20%)
                        if abs(change_percent) > 20:
                            results[symbol]['status'] = 'significant_change'
                            significant_changes.append(oi_info)
                            
                        self.logger.info(f"{symbol} 持仓量: {current_oi:,.0f}, 24h变化: {change_percent:.2f}%")
                        
                    else:
                        results[symbol] = {
                            'error': 'No data available',
                            'status': 'error'
                        }
                        
                except Exception as e:
                    self.logger.error(f"获取{symbol}持仓量数据失败: {e}")
                    results[symbol] = {
                        'error': str(e),
                        'status': 'error'
                    }
            
            # 发送通知
            if notify and significant_changes:
                await self._send_open_interest_notification(significant_changes)
            
            summary = {
                'timestamp': datetime.now(),
                'total_symbols': len(symbols),
                'successful': len([r for r in results.values() if r.get('status') != 'error']),
                'significant_changes': len(significant_changes),
                'results': results
            }
            
            self.logger.info(f"持仓量监控完成: {summary['successful']}/{summary['total_symbols']} 成功")
            return summary
            
        except Exception as e:
            self.logger.error(f"持仓量监控失败: {e}")
            return {
                'timestamp': datetime.now(),
                'error': str(e),
                'results': {}
            }
    
    async def _send_open_interest_notification(self, changes: List[OpenInterestData]) -> None:
        """发送持仓量变化通知"""
        try:
            if not self.notification_service:
                return
                
            from app.services.notification.core_notification_service import NotificationContent, NotificationType, NotificationPriority
            
            # 构建通知消息
            message = "📊 持仓量显著变化监控\n\n"
            
            for change in changes:
                direction = "📈" if change.change_percent > 0 else "📉"
                message += f"{direction} {change.symbol}\n"
                message += f"   当前持仓量: {change.current_oi:,.0f}\n"
                message += f"   24h变化: {change.change_percent:+.2f}%\n\n"
            
            content = NotificationContent(
                type=NotificationType.SYSTEM_ALERT,
                priority=NotificationPriority.NORMAL,
                title=f"📊 持仓量变化监控 ({len(changes)}个异常)",
                message=message,
                metadata={
                    'changes': [
                        {
                            'symbol': c.symbol,
                            'current_oi': c.current_oi,
                            'change_percent': c.change_percent
                        } for c in changes
                    ]
                }
            )
            
            await self.notification_service.send_notification(content)
            self.logger.info(f"已发送持仓量变化通知: {len(changes)}个异常")
            
        except Exception as e:
            self.logger.error(f"发送持仓量变化通知失败: {e}")


# 全局服务实例
_core_monitoring_service = None


async def get_core_monitoring_service() -> CoreMonitoringService:
    """获取核心监控服务实例"""
    global _core_monitoring_service
    if _core_monitoring_service is None:
        _core_monitoring_service = CoreMonitoringService()
    return _core_monitoring_service
