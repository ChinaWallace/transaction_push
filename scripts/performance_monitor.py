# -*- coding: utf-8 -*-
"""
性能监控脚本
Performance Monitor Script - 监控系统性能并生成报告
"""

import asyncio
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import sys
sys.path.append(str(Path(__file__).parent.parent))

from app.core.logging import get_logger
from app.services.exchanges.factory import ExchangeFactory
from app.services.exchanges.optimizations.websocket_optimizer import get_websocket_optimizer
from app.services.exchanges.optimizations.memory_optimizer import get_memory_optimizer
from tests.performance.test_exchange_performance import ExchangePerformanceTester

logger = get_logger(__name__)


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, output_dir: str = "performance_reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        self.tester = ExchangePerformanceTester()
        self.start_time = datetime.now()
        
        logger.info(f"📊 性能监控器初始化，报告输出目录: {self.output_dir}")
    
    async def run_comprehensive_test(self, exchange_name: str = None, 
                                   duration_minutes: int = 10) -> Dict[str, Any]:
        """运行综合性能测试"""
        logger.info(f"🚀 开始综合性能测试: {duration_minutes} 分钟")
        
        try:
            # 初始化交易所工厂
            await ExchangeFactory.initialize_factory()
            
            # 获取交易所实例
            if exchange_name:
                exchange = await ExchangeFactory.get_exchange(exchange_name)
            else:
                exchange = await ExchangeFactory.get_exchange()
            
            # 获取优化器
            ws_optimizer = await get_websocket_optimizer()
            memory_optimizer = await get_memory_optimizer()
            
            # 测试结果收集
            results = {
                'test_info': {
                    'exchange': exchange_name or 'default',
                    'start_time': self.start_time.isoformat(),
                    'duration_minutes': duration_minutes,
                    'test_types': []
                },
                'tests': {},
                'optimizers': {},
                'summary': {}
            }
            
            # 1. 并发API调用测试
            logger.info("🧪 执行并发API调用测试")
            concurrent_result = await self.tester.test_concurrent_api_calls(
                exchange=exchange,
                concurrent_count=15,
                iterations=20
            )
            results['tests']['concurrent_api'] = concurrent_result
            results['test_info']['test_types'].append('concurrent_api')
            
            # 2. WebSocket性能测试
            logger.info("🧪 执行WebSocket性能测试")
            websocket_result = await self.tester.test_websocket_performance(
                exchange=exchange,
                subscription_count=30,
                test_duration=min(60, duration_minutes * 60 // 4)  # 最多1分钟或总时长的1/4
            )
            results['tests']['websocket'] = websocket_result
            results['test_info']['test_types'].append('websocket')
            
            # 3. 内存使用测试
            logger.info("🧪 执行内存使用测试")
            memory_result = await self.tester.test_memory_usage(
                exchange=exchange,
                operations=300
            )
            results['tests']['memory_usage'] = memory_result
            results['test_info']['test_types'].append('memory_usage')
            
            # 4. 连接稳定性测试
            logger.info("🧪 执行连接稳定性测试")
            stability_result = await self.tester.test_connection_stability(
                exchange=exchange,
                test_duration=min(120, duration_minutes * 60 // 2)  # 最多2分钟或总时长的1/2
            )
            results['tests']['connection_stability'] = stability_result
            results['test_info']['test_types'].append('connection_stability')
            
            # 5. 收集优化器状态
            results['optimizers']['websocket'] = ws_optimizer.get_optimization_status()
            results['optimizers']['memory'] = memory_optimizer.get_memory_status()
            
            # 6. 生成测试摘要
            results['summary'] = self._generate_summary(results['tests'])
            results['test_info']['end_time'] = datetime.now().isoformat()
            results['test_info']['actual_duration'] = (datetime.now() - self.start_time).total_seconds()
            
            logger.info("✅ 综合性能测试完成")
            return results
            
        except Exception as e:
            logger.error(f"❌ 综合性能测试异常: {e}")
            return {'error': str(e), 'timestamp': datetime.now().isoformat()}
        
        finally:
            # 清理资源
            await ExchangeFactory.cleanup_all()
    
    async def run_stress_test(self, exchange_name: str = None, 
                            duration_minutes: int = 30) -> Dict[str, Any]:
        """运行压力测试"""
        logger.info(f"💪 开始压力测试: {duration_minutes} 分钟")
        
        try:
            # 初始化交易所工厂
            await ExchangeFactory.initialize_factory()
            
            # 获取交易所实例
            if exchange_name:
                exchange = await ExchangeFactory.get_exchange(exchange_name)
            else:
                exchange = await ExchangeFactory.get_exchange()
            
            # 获取优化器
            memory_optimizer = await get_memory_optimizer()
            
            # 压力测试配置
            stress_config = {
                'high_concurrent_calls': 50,
                'high_iterations': 100,
                'many_subscriptions': 100,
                'long_duration': duration_minutes * 60,
                'heavy_operations': 2000
            }
            
            results = {
                'test_info': {
                    'test_type': 'stress_test',
                    'exchange': exchange_name or 'default',
                    'start_time': self.start_time.isoformat(),
                    'duration_minutes': duration_minutes,
                    'config': stress_config
                },
                'tests': {},
                'memory_snapshots': [],
                'summary': {}
            }
            
            # 记录初始内存状态
            initial_memory = memory_optimizer.get_memory_status()
            results['memory_snapshots'].append({
                'phase': 'initial',
                'timestamp': datetime.now().isoformat(),
                'status': initial_memory
            })
            
            # 1. 高并发API调用压力测试
            logger.info("💥 执行高并发API调用压力测试")
            high_concurrent_result = await self.tester.test_concurrent_api_calls(
                exchange=exchange,
                concurrent_count=stress_config['high_concurrent_calls'],
                iterations=stress_config['high_iterations']
            )
            results['tests']['high_concurrent_api'] = high_concurrent_result
            
            # 记录中间内存状态
            mid_memory = memory_optimizer.get_memory_status()
            results['memory_snapshots'].append({
                'phase': 'after_concurrent_test',
                'timestamp': datetime.now().isoformat(),
                'status': mid_memory
            })
            
            # 2. 大量WebSocket订阅压力测试
            logger.info("💥 执行大量WebSocket订阅压力测试")
            many_subscriptions_result = await self.tester.test_websocket_performance(
                exchange=exchange,
                subscription_count=stress_config['many_subscriptions'],
                test_duration=min(300, stress_config['long_duration'] // 3)  # 最多5分钟
            )
            results['tests']['many_subscriptions'] = many_subscriptions_result
            
            # 3. 重度内存使用测试
            logger.info("💥 执行重度内存使用测试")
            heavy_memory_result = await self.tester.test_memory_usage(
                exchange=exchange,
                operations=stress_config['heavy_operations']
            )
            results['tests']['heavy_memory_usage'] = heavy_memory_result
            
            # 记录最终内存状态
            final_memory = memory_optimizer.get_memory_status()
            results['memory_snapshots'].append({
                'phase': 'final',
                'timestamp': datetime.now().isoformat(),
                'status': final_memory
            })
            
            # 生成压力测试摘要
            results['summary'] = self._generate_stress_summary(results)
            results['test_info']['end_time'] = datetime.now().isoformat()
            results['test_info']['actual_duration'] = (datetime.now() - self.start_time).total_seconds()
            
            logger.info("✅ 压力测试完成")
            return results
            
        except Exception as e:
            logger.error(f"❌ 压力测试异常: {e}")
            return {'error': str(e), 'timestamp': datetime.now().isoformat()}
        
        finally:
            # 清理资源
            await ExchangeFactory.cleanup_all()
    
    async def run_monitoring_session(self, duration_minutes: int = 60) -> Dict[str, Any]:
        """运行监控会话"""
        logger.info(f"👁️ 开始监控会话: {duration_minutes} 分钟")
        
        try:
            # 获取优化器
            ws_optimizer = await get_websocket_optimizer()
            memory_optimizer = await get_memory_optimizer()
            
            # 监控数据收集
            monitoring_data = {
                'session_info': {
                    'start_time': self.start_time.isoformat(),
                    'duration_minutes': duration_minutes,
                    'monitoring_interval': 30  # 30秒间隔
                },
                'snapshots': [],
                'alerts': [],
                'summary': {}
            }
            
            # 监控循环
            end_time = self.start_time + timedelta(minutes=duration_minutes)
            snapshot_count = 0
            
            while datetime.now() < end_time:
                snapshot_count += 1
                current_time = datetime.now()
                
                # 收集当前状态
                snapshot = {
                    'timestamp': current_time.isoformat(),
                    'sequence': snapshot_count,
                    'websocket_optimizer': ws_optimizer.get_optimization_status(),
                    'memory_optimizer': memory_optimizer.get_memory_status()
                }
                
                monitoring_data['snapshots'].append(snapshot)
                
                # 检查告警
                memory_status = snapshot['memory_optimizer']
                if 'recent_alerts' in memory_status and memory_status['recent_alerts']:
                    for alert in memory_status['recent_alerts']:
                        if alert not in monitoring_data['alerts']:
                            monitoring_data['alerts'].append(alert)
                
                # 记录进度
                elapsed_minutes = (current_time - self.start_time).total_seconds() / 60
                logger.info(f"📊 监控进度: {elapsed_minutes:.1f}/{duration_minutes} 分钟")
                
                # 等待下一个监控间隔
                await asyncio.sleep(30)
            
            # 生成监控摘要
            monitoring_data['summary'] = self._generate_monitoring_summary(monitoring_data)
            monitoring_data['session_info']['end_time'] = datetime.now().isoformat()
            monitoring_data['session_info']['actual_duration'] = (datetime.now() - self.start_time).total_seconds()
            monitoring_data['session_info']['total_snapshots'] = len(monitoring_data['snapshots'])
            
            logger.info("✅ 监控会话完成")
            return monitoring_data
            
        except Exception as e:
            logger.error(f"❌ 监控会话异常: {e}")
            return {'error': str(e), 'timestamp': datetime.now().isoformat()}
    
    def _generate_summary(self, test_results: Dict[str, Any]) -> Dict[str, Any]:
        """生成测试摘要"""
        summary = {
            'overall_status': 'unknown',
            'performance_score': 0,
            'key_metrics': {},
            'recommendations': []
        }
        
        try:
            scores = []
            
            # 分析并发API测试
            if 'concurrent_api' in test_results:
                api_result = test_results['concurrent_api']
                api_score = min(100, api_result.get('success_rate', 0) * 100)
                scores.append(api_score)
                
                summary['key_metrics']['api_success_rate'] = api_result.get('success_rate', 0)
                summary['key_metrics']['api_qps'] = api_result.get('calls_per_second', 0)
                
                if api_result.get('success_rate', 0) < 0.9:
                    summary['recommendations'].append("API成功率偏低，建议检查网络连接和API限制")
            
            # 分析WebSocket测试
            if 'websocket' in test_results:
                ws_result = test_results['websocket']
                if 'error' not in ws_result:
                    ws_score = min(100, ws_result.get('subscription_success_rate', 0) * 100)
                    scores.append(ws_score)
                    
                    summary['key_metrics']['websocket_subscription_rate'] = ws_result.get('subscription_success_rate', 0)
                    summary['key_metrics']['websocket_msg_per_sec'] = ws_result.get('messages_per_second', 0)
                    
                    if ws_result.get('subscription_success_rate', 0) < 0.8:
                        summary['recommendations'].append("WebSocket订阅成功率偏低，建议优化连接参数")
            
            # 分析内存使用
            if 'memory_usage' in test_results:
                mem_result = test_results['memory_usage']
                # 内存增长越少分数越高
                mem_increase = mem_result.get('memory_increase_mb', 0)
                mem_score = max(0, 100 - mem_increase)  # 每MB扣1分
                scores.append(mem_score)
                
                summary['key_metrics']['memory_increase_mb'] = mem_increase
                summary['key_metrics']['memory_per_operation_kb'] = mem_result.get('memory_per_operation_kb', 0)
                
                if mem_increase > 50:
                    summary['recommendations'].append("内存增长较大，建议检查内存泄漏")
            
            # 分析连接稳定性
            if 'connection_stability' in test_results:
                stab_result = test_results['connection_stability']
                stab_score = min(100, stab_result.get('api_success_rate', 0) * 100)
                scores.append(stab_score)
                
                summary['key_metrics']['connection_success_rate'] = stab_result.get('connection_success_rate', 0)
                summary['key_metrics']['api_stability_rate'] = stab_result.get('api_success_rate', 0)
                
                if stab_result.get('api_success_rate', 0) < 0.95:
                    summary['recommendations'].append("连接稳定性有待提升，建议优化重连机制")
            
            # 计算总体分数
            if scores:
                summary['performance_score'] = sum(scores) / len(scores)
                
                if summary['performance_score'] >= 90:
                    summary['overall_status'] = 'excellent'
                elif summary['performance_score'] >= 80:
                    summary['overall_status'] = 'good'
                elif summary['performance_score'] >= 70:
                    summary['overall_status'] = 'fair'
                else:
                    summary['overall_status'] = 'poor'
            
            # 通用建议
            if not summary['recommendations']:
                summary['recommendations'].append("系统性能表现良好，继续保持")
        
        except Exception as e:
            logger.error(f"❌ 生成测试摘要异常: {e}")
            summary['error'] = str(e)
        
        return summary
    
    def _generate_stress_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """生成压力测试摘要"""
        summary = {
            'stress_level': 'unknown',
            'stability_score': 0,
            'memory_impact': {},
            'performance_degradation': {},
            'recommendations': []
        }
        
        try:
            # 分析内存影响
            snapshots = results.get('memory_snapshots', [])
            if len(snapshots) >= 2:
                initial = snapshots[0]['status']['current_memory']['rss_mb']
                final = snapshots[-1]['status']['current_memory']['rss_mb']
                
                memory_increase = final - initial
                memory_increase_percent = (memory_increase / initial) * 100 if initial > 0 else 0
                
                summary['memory_impact'] = {
                    'initial_mb': initial,
                    'final_mb': final,
                    'increase_mb': memory_increase,
                    'increase_percent': memory_increase_percent
                }
                
                if memory_increase_percent > 50:
                    summary['recommendations'].append("压力测试下内存增长显著，需要优化内存管理")
            
            # 分析性能表现
            tests = results.get('tests', {})
            
            # 高并发API测试
            if 'high_concurrent_api' in tests:
                api_result = tests['high_concurrent_api']
                summary['performance_degradation']['api_success_rate'] = api_result.get('success_rate', 0)
                
                if api_result.get('success_rate', 0) < 0.7:
                    summary['recommendations'].append("高并发下API成功率下降明显，建议增加限流保护")
            
            # WebSocket压力测试
            if 'many_subscriptions' in tests:
                ws_result = tests['many_subscriptions']
                if 'error' not in ws_result:
                    summary['performance_degradation']['websocket_subscription_rate'] = ws_result.get('subscription_success_rate', 0)
                    
                    if ws_result.get('subscription_success_rate', 0) < 0.6:
                        summary['recommendations'].append("大量订阅下WebSocket性能下降，建议优化连接管理")
            
            # 计算稳定性分数
            stability_factors = []
            
            if 'api_success_rate' in summary['performance_degradation']:
                stability_factors.append(summary['performance_degradation']['api_success_rate'] * 100)
            
            if 'websocket_subscription_rate' in summary['performance_degradation']:
                stability_factors.append(summary['performance_degradation']['websocket_subscription_rate'] * 100)
            
            if summary['memory_impact'].get('increase_percent', 0) < 30:
                stability_factors.append(80)  # 内存增长合理
            elif summary['memory_impact'].get('increase_percent', 0) < 50:
                stability_factors.append(60)  # 内存增长较多
            else:
                stability_factors.append(30)  # 内存增长过多
            
            if stability_factors:
                summary['stability_score'] = sum(stability_factors) / len(stability_factors)
                
                if summary['stability_score'] >= 80:
                    summary['stress_level'] = 'excellent'
                elif summary['stability_score'] >= 70:
                    summary['stress_level'] = 'good'
                elif summary['stability_score'] >= 60:
                    summary['stress_level'] = 'fair'
                else:
                    summary['stress_level'] = 'poor'
            
            if not summary['recommendations']:
                summary['recommendations'].append("系统在压力测试下表现稳定")
        
        except Exception as e:
            logger.error(f"❌ 生成压力测试摘要异常: {e}")
            summary['error'] = str(e)
        
        return summary
    
    def _generate_monitoring_summary(self, monitoring_data: Dict[str, Any]) -> Dict[str, Any]:
        """生成监控摘要"""
        summary = {
            'monitoring_health': 'unknown',
            'trends': {},
            'alerts_summary': {},
            'recommendations': []
        }
        
        try:
            snapshots = monitoring_data.get('snapshots', [])
            alerts = monitoring_data.get('alerts', [])
            
            if not snapshots:
                return summary
            
            # 分析内存趋势
            memory_values = []
            for snapshot in snapshots:
                mem_status = snapshot.get('memory_optimizer', {})
                current_mem = mem_status.get('current_memory', {})
                if 'rss_mb' in current_mem:
                    memory_values.append(current_mem['rss_mb'])
            
            if memory_values:
                initial_mem = memory_values[0]
                final_mem = memory_values[-1]
                max_mem = max(memory_values)
                avg_mem = sum(memory_values) / len(memory_values)
                
                summary['trends']['memory'] = {
                    'initial_mb': initial_mem,
                    'final_mb': final_mem,
                    'max_mb': max_mem,
                    'average_mb': avg_mem,
                    'trend': 'increasing' if final_mem > initial_mem * 1.1 else 'decreasing' if final_mem < initial_mem * 0.9 else 'stable'
                }
            
            # 分析告警
            if alerts:
                alert_types = {}
                severity_counts = {'warning': 0, 'critical': 0}
                
                for alert in alerts:
                    alert_type = alert.get('type', 'unknown')
                    severity = alert.get('severity', 'unknown')
                    
                    alert_types[alert_type] = alert_types.get(alert_type, 0) + 1
                    if severity in severity_counts:
                        severity_counts[severity] += 1
                
                summary['alerts_summary'] = {
                    'total_alerts': len(alerts),
                    'alert_types': alert_types,
                    'severity_counts': severity_counts
                }
                
                if severity_counts['critical'] > 0:
                    summary['recommendations'].append(f"发现 {severity_counts['critical']} 个严重告警，需要立即处理")
                elif severity_counts['warning'] > 5:
                    summary['recommendations'].append(f"警告告警较多 ({severity_counts['warning']} 个)，建议优化系统配置")
            
            # 评估监控健康度
            health_score = 100
            
            if summary['trends'].get('memory', {}).get('trend') == 'increasing':
                health_score -= 20
            
            if alerts:
                health_score -= min(30, len(alerts) * 5)  # 每个告警扣5分，最多扣30分
            
            if health_score >= 90:
                summary['monitoring_health'] = 'excellent'
            elif health_score >= 80:
                summary['monitoring_health'] = 'good'
            elif health_score >= 70:
                summary['monitoring_health'] = 'fair'
            else:
                summary['monitoring_health'] = 'poor'
            
            if not summary['recommendations']:
                summary['recommendations'].append("系统监控状态良好，运行稳定")
        
        except Exception as e:
            logger.error(f"❌ 生成监控摘要异常: {e}")
            summary['error'] = str(e)
        
        return summary
    
    def save_report(self, results: Dict[str, Any], report_type: str = "performance"):
        """保存性能报告"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{report_type}_report_{timestamp}.json"
            filepath = self.output_dir / filename
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False, default=str)
            
            logger.info(f"📄 性能报告已保存: {filepath}")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"❌ 保存性能报告异常: {e}")
            return None


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="性能监控脚本")
    parser.add_argument("--test-type", choices=["comprehensive", "stress", "monitoring"], 
                       default="comprehensive", help="测试类型")
    parser.add_argument("--exchange", choices=["okx", "binance"], 
                       help="指定交易所")
    parser.add_argument("--duration", type=int, default=10, 
                       help="测试持续时间（分钟）")
    parser.add_argument("--output-dir", default="performance_reports", 
                       help="报告输出目录")
    
    args = parser.parse_args()
    
    # 创建性能监控器
    monitor = PerformanceMonitor(args.output_dir)
    
    try:
        if args.test_type == "comprehensive":
            logger.info("🚀 开始综合性能测试")
            results = await monitor.run_comprehensive_test(
                exchange_name=args.exchange,
                duration_minutes=args.duration
            )
            report_path = monitor.save_report(results, "comprehensive")
            
        elif args.test_type == "stress":
            logger.info("💪 开始压力测试")
            results = await monitor.run_stress_test(
                exchange_name=args.exchange,
                duration_minutes=args.duration
            )
            report_path = monitor.save_report(results, "stress")
            
        elif args.test_type == "monitoring":
            logger.info("👁️ 开始监控会话")
            results = await monitor.run_monitoring_session(
                duration_minutes=args.duration
            )
            report_path = monitor.save_report(results, "monitoring")
        
        # 输出摘要
        if 'summary' in results:
            summary = results['summary']
            logger.info("📊 测试摘要:")
            
            if 'overall_status' in summary:
                logger.info(f"  总体状态: {summary['overall_status']}")
            
            if 'performance_score' in summary:
                logger.info(f"  性能分数: {summary['performance_score']:.1f}")
            
            if 'stability_score' in summary:
                logger.info(f"  稳定性分数: {summary['stability_score']:.1f}")
            
            if 'monitoring_health' in summary:
                logger.info(f"  监控健康度: {summary['monitoring_health']}")
            
            if 'recommendations' in summary and summary['recommendations']:
                logger.info("  建议:")
                for rec in summary['recommendations']:
                    logger.info(f"    - {rec}")
        
        if report_path:
            logger.info(f"✅ 测试完成，报告已保存: {report_path}")
        else:
            logger.warning("⚠️ 测试完成，但报告保存失败")
    
    except Exception as e:
        logger.error(f"❌ 性能监控异常: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())