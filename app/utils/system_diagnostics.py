# -*- coding: utf-8 -*-
"""
系统诊断工具
System Diagnostics - 监控和诊断系统健康状况
"""

import asyncio
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from collections import defaultdict, deque

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

from app.core.logging import get_logger
from app.utils.error_analyzer import get_error_analyzer, ErrorCategory

logger = get_logger(__name__)


@dataclass
class SystemMetrics:
    """系统指标"""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_available_mb: float
    disk_usage_percent: float
    network_connections: int
    active_threads: int


@dataclass
class ErrorStats:
    """错误统计"""
    category: str
    count: int
    last_occurrence: datetime
    severity_distribution: Dict[str, int]
    is_increasing: bool
    hourly_rate: float


@dataclass
class ServiceHealthStatus:
    """服务健康状态"""
    service_name: str
    is_healthy: bool
    last_check: datetime
    error_count: int
    success_rate: float
    avg_response_time: float
    status_message: str


class SystemDiagnostics:
    """系统诊断工具"""
    
    def __init__(self, max_history_size: int = 1000):
        self.logger = get_logger(__name__)
        self.error_analyzer = get_error_analyzer()
        
        # 历史数据存储
        self.max_history_size = max_history_size
        self.metrics_history = deque(maxlen=max_history_size)
        self.error_history = deque(maxlen=max_history_size)
        
        # 错误统计
        self.error_counts = defaultdict(int)
        self.error_timestamps = defaultdict(list)
        self.error_severities = defaultdict(lambda: defaultdict(int))
        
        # 服务健康状态
        self.service_health = {}
        
        # 性能基线
        self.performance_baseline = {
            'cpu_threshold': 80.0,
            'memory_threshold': 85.0,
            'disk_threshold': 90.0,
            'error_rate_threshold': 10.0,  # 每小时错误数
            'response_time_threshold': 5.0  # 秒
        }
    
    async def collect_system_metrics(self) -> SystemMetrics:
        """收集系统指标"""
        try:
            if not PSUTIL_AVAILABLE:
                # 如果psutil不可用，返回模拟数据
                self.logger.warning("⚠️ psutil库不可用，返回模拟系统指标")
                return SystemMetrics(
                    timestamp=datetime.now(),
                    cpu_percent=0.0,
                    memory_percent=0.0,
                    memory_available_mb=1024.0,
                    disk_usage_percent=0.0,
                    network_connections=0,
                    active_threads=1
                )
            
            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # 内存使用情况
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_available_mb = memory.available / (1024 * 1024)
            
            # 磁盘使用情况
            try:
                # Windows和Linux的磁盘路径不同
                import os
                disk_path = 'C:\\' if os.name == 'nt' else '/'
                disk_usage = psutil.disk_usage(disk_path)
                disk_usage_percent = disk_usage.percent
            except Exception:
                disk_usage_percent = 0.0
            
            # 网络连接数
            try:
                network_connections = len(psutil.net_connections())
            except Exception:
                network_connections = 0
            
            # 活跃线程数
            try:
                active_threads = psutil.Process().num_threads()
            except Exception:
                active_threads = 1
            
            metrics = SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_available_mb=memory_available_mb,
                disk_usage_percent=disk_usage_percent,
                network_connections=network_connections,
                active_threads=active_threads
            )
            
            # 存储到历史记录
            self.metrics_history.append(metrics)
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"❌ 收集系统指标失败: {e}")
            return SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=0.0,
                memory_percent=0.0,
                memory_available_mb=0.0,
                disk_usage_percent=0.0,
                network_connections=0,
                active_threads=0
            )
    
    def record_error(self, error: Exception, context: Optional[Dict[str, Any]] = None):
        """记录错误信息"""
        try:
            # 分析错误
            analysis = self.error_analyzer.analyze_error(error, context)
            
            # 更新错误统计
            category_key = analysis.category.value
            self.error_counts[category_key] += 1
            self.error_timestamps[category_key].append(datetime.now())
            self.error_severities[category_key][analysis.severity] += 1
            
            # 记录到历史
            error_record = {
                'timestamp': datetime.now(),
                'category': analysis.category.value,
                'severity': analysis.severity,
                'error_type': type(error).__name__,
                'error_message': str(error),
                'context': context or {},
                'is_recoverable': analysis.is_recoverable
            }
            
            self.error_history.append(error_record)
            
            # 清理过期的时间戳记录（保留最近24小时）
            cutoff_time = datetime.now() - timedelta(hours=24)
            for category in self.error_timestamps:
                self.error_timestamps[category] = [
                    ts for ts in self.error_timestamps[category] 
                    if ts > cutoff_time
                ]
            
        except Exception as e:
            self.logger.error(f"❌ 记录错误信息失败: {e}")
    
    def get_error_statistics(self) -> List[ErrorStats]:
        """获取错误统计信息"""
        stats = []
        current_time = datetime.now()
        
        for category, count in self.error_counts.items():
            timestamps = self.error_timestamps[category]
            
            # 计算最近一小时的错误率
            hour_ago = current_time - timedelta(hours=1)
            recent_errors = [ts for ts in timestamps if ts > hour_ago]
            hourly_rate = len(recent_errors)
            
            # 检查是否呈上升趋势
            half_hour_ago = current_time - timedelta(minutes=30)
            recent_half_hour = [ts for ts in timestamps if ts > half_hour_ago]
            previous_half_hour = [ts for ts in timestamps if hour_ago < ts <= half_hour_ago]
            
            is_increasing = len(recent_half_hour) > len(previous_half_hour)
            
            # 最后出现时间
            last_occurrence = max(timestamps) if timestamps else current_time
            
            # 严重程度分布
            severity_dist = dict(self.error_severities[category])
            
            stats.append(ErrorStats(
                category=category,
                count=count,
                last_occurrence=last_occurrence,
                severity_distribution=severity_dist,
                is_increasing=is_increasing,
                hourly_rate=hourly_rate
            ))
        
        return sorted(stats, key=lambda x: x.hourly_rate, reverse=True)
    
    def update_service_health(self, service_name: str, is_healthy: bool, 
                            response_time: float = 0.0, error_message: str = ""):
        """更新服务健康状态"""
        current_time = datetime.now()
        
        if service_name not in self.service_health:
            self.service_health[service_name] = {
                'total_checks': 0,
                'successful_checks': 0,
                'total_response_time': 0.0,
                'error_count': 0,
                'response_times': deque(maxlen=100)  # 保留最近100次响应时间
            }
        
        health_data = self.service_health[service_name]
        health_data['total_checks'] += 1
        health_data['response_times'].append(response_time)
        health_data['total_response_time'] += response_time
        
        if is_healthy:
            health_data['successful_checks'] += 1
        else:
            health_data['error_count'] += 1
        
        # 计算成功率和平均响应时间
        success_rate = (health_data['successful_checks'] / health_data['total_checks']) * 100
        avg_response_time = health_data['total_response_time'] / health_data['total_checks']
        
        # 创建状态记录
        status = ServiceHealthStatus(
            service_name=service_name,
            is_healthy=is_healthy,
            last_check=current_time,
            error_count=health_data['error_count'],
            success_rate=success_rate,
            avg_response_time=avg_response_time,
            status_message=error_message if not is_healthy else "正常"
        )
        
        return status
    
    def get_system_health_report(self) -> Dict[str, Any]:
        """获取系统健康报告"""
        try:
            # 获取最新的系统指标
            latest_metrics = self.metrics_history[-1] if self.metrics_history else None
            
            # 获取错误统计
            error_stats = self.get_error_statistics()
            
            # 计算健康评分
            health_score = self._calculate_health_score(latest_metrics, error_stats)
            
            # 生成警告和建议
            warnings, suggestions = self._generate_health_insights(latest_metrics, error_stats)
            
            # 服务状态汇总
            service_summary = {}
            for service_name, health_data in self.service_health.items():
                if health_data['total_checks'] > 0:
                    success_rate = (health_data['successful_checks'] / health_data['total_checks']) * 100
                    avg_response_time = health_data['total_response_time'] / health_data['total_checks']
                    
                    service_summary[service_name] = {
                        'success_rate': success_rate,
                        'avg_response_time': avg_response_time,
                        'error_count': health_data['error_count'],
                        'status': 'healthy' if success_rate > 95 else 'degraded' if success_rate > 80 else 'unhealthy'
                    }
            
            return {
                'timestamp': datetime.now(),
                'overall_health_score': health_score,
                'system_metrics': asdict(latest_metrics) if latest_metrics else None,
                'error_statistics': [asdict(stat) for stat in error_stats[:10]],  # 前10个错误类型
                'service_health': service_summary,
                'warnings': warnings,
                'suggestions': suggestions,
                'metrics_history_count': len(self.metrics_history),
                'error_history_count': len(self.error_history)
            }
            
        except Exception as e:
            self.logger.error(f"❌ 生成系统健康报告失败: {e}")
            return {
                'timestamp': datetime.now(),
                'error': f"报告生成失败: {str(e)}",
                'overall_health_score': 0
            }
    
    def _calculate_health_score(self, metrics: Optional[SystemMetrics], 
                              error_stats: List[ErrorStats]) -> float:
        """计算系统健康评分 (0-100)"""
        score = 100.0
        
        if metrics:
            # CPU使用率影响 (最多扣除20分)
            if metrics.cpu_percent > self.performance_baseline['cpu_threshold']:
                cpu_penalty = min(20, (metrics.cpu_percent - self.performance_baseline['cpu_threshold']) / 2)
                score -= cpu_penalty
            
            # 内存使用率影响 (最多扣除25分)
            if metrics.memory_percent > self.performance_baseline['memory_threshold']:
                memory_penalty = min(25, (metrics.memory_percent - self.performance_baseline['memory_threshold']) / 2)
                score -= memory_penalty
            
            # 磁盘使用率影响 (最多扣除15分)
            if metrics.disk_usage_percent > self.performance_baseline['disk_threshold']:
                disk_penalty = min(15, (metrics.disk_usage_percent - self.performance_baseline['disk_threshold']) / 2)
                score -= disk_penalty
        
        # 错误率影响 (最多扣除40分)
        total_error_rate = sum(stat.hourly_rate for stat in error_stats)
        if total_error_rate > self.performance_baseline['error_rate_threshold']:
            error_penalty = min(40, total_error_rate / 2)
            score -= error_penalty
        
        return max(0.0, score)
    
    def _generate_health_insights(self, metrics: Optional[SystemMetrics], 
                                error_stats: List[ErrorStats]) -> tuple[List[str], List[str]]:
        """生成健康洞察 - 警告和建议"""
        warnings = []
        suggestions = []
        
        if metrics:
            # 系统资源警告
            if metrics.cpu_percent > self.performance_baseline['cpu_threshold']:
                warnings.append(f"CPU使用率过高: {metrics.cpu_percent:.1f}%")
                suggestions.append("检查CPU密集型任务，考虑优化算法或增加计算资源")
            
            if metrics.memory_percent > self.performance_baseline['memory_threshold']:
                warnings.append(f"内存使用率过高: {metrics.memory_percent:.1f}%")
                suggestions.append("检查内存泄漏，优化数据结构，考虑增加内存")
            
            if metrics.disk_usage_percent > self.performance_baseline['disk_threshold']:
                warnings.append(f"磁盘使用率过高: {metrics.disk_usage_percent:.1f}%")
                suggestions.append("清理临时文件，归档旧数据，扩展存储空间")
        
        # 错误统计警告
        for stat in error_stats:
            if stat.hourly_rate > self.performance_baseline['error_rate_threshold']:
                warnings.append(f"{stat.category}错误频发: {stat.hourly_rate:.1f}/小时")
                
                if stat.category == ErrorCategory.NETWORK.value:
                    suggestions.append("检查网络连接稳定性，验证代理配置")
                elif stat.category == ErrorCategory.API_RATE_LIMIT.value:
                    suggestions.append("降低API请求频率，实施更智能的限流策略")
                elif stat.category == ErrorCategory.TIMEOUT.value:
                    suggestions.append("增加超时时间，检查网络质量")
                elif stat.category == ErrorCategory.AUTHENTICATION.value:
                    suggestions.append("验证API密钥配置，检查权限设置")
            
            if stat.is_increasing:
                warnings.append(f"{stat.category}错误呈上升趋势")
                suggestions.append(f"重点关注{stat.category}类型错误的根本原因")
        
        return warnings, suggestions
    
    async def run_diagnostic_check(self) -> Dict[str, Any]:
        """运行完整的诊断检查"""
        self.logger.info("🔍 开始系统诊断检查...")
        
        try:
            # 收集系统指标
            metrics = await self.collect_system_metrics()
            
            # 生成健康报告
            health_report = self.get_system_health_report()
            
            # 检查关键服务状态
            await self._check_critical_services()
            
            # 记录诊断结果
            health_score = health_report['overall_health_score']
            if health_score < 60:
                self.logger.error(f"❌ 系统健康状况不佳: {health_score:.1f}/100")
            elif health_score < 80:
                self.logger.warning(f"⚠️ 系统健康状况一般: {health_score:.1f}/100")
            else:
                self.logger.info(f"✅ 系统健康状况良好: {health_score:.1f}/100")
            
            return health_report
            
        except Exception as e:
            self.logger.error(f"❌ 诊断检查失败: {e}")
            return {
                'timestamp': datetime.now(),
                'error': f"诊断失败: {str(e)}",
                'overall_health_score': 0
            }
    
    async def _check_critical_services(self):
        """检查关键服务状态"""
        try:
            # 检查交易所服务
            from app.services.exchanges.service_manager import get_exchange_service
            start_time = time.time()
            try:
                exchange_service = await get_exchange_service()
                if hasattr(exchange_service, 'health_check'):
                    await exchange_service.health_check()
                response_time = time.time() - start_time
                self.update_service_health('exchange_service', True, response_time)
            except Exception as e:
                response_time = time.time() - start_time
                self.update_service_health('exchange_service', False, response_time, str(e))
            
            # 检查数据库连接
            # TODO: 添加数据库健康检查
            
        except Exception as e:
            self.logger.error(f"❌ 关键服务检查失败: {e}")


# 全局诊断实例
_system_diagnostics: Optional[SystemDiagnostics] = None


def get_system_diagnostics() -> SystemDiagnostics:
    """获取系统诊断实例"""
    global _system_diagnostics
    if _system_diagnostics is None:
        _system_diagnostics = SystemDiagnostics()
    return _system_diagnostics


def record_system_error(error: Exception, context: Optional[Dict[str, Any]] = None):
    """记录系统错误到诊断工具"""
    diagnostics = get_system_diagnostics()
    diagnostics.record_error(error, context)
