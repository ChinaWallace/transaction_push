# -*- coding: utf-8 -*-
"""
适配器诊断工具
Adapter diagnostics utility
"""

from typing import Dict, Any, List
from datetime import datetime

from app.core.logging import get_logger
from app.models.unified_exchange_data import DataAdaptationError, FieldMappingError
from .adapter_factory import AdapterFactory

logger = get_logger(__name__)


class AdapterDiagnostics:
    """
    适配器诊断工具类
    Adapter diagnostics utility class
    
    提供适配器系统的健康检查、性能测试和错误诊断功能
    """
    
    def __init__(self):
        self.test_results: Dict[str, Any] = {}
        self.performance_metrics: Dict[str, Any] = {}
    
    async def run_comprehensive_diagnostics(self, exchanges: List[str] = None) -> Dict[str, Any]:
        """
        运行综合诊断
        Run comprehensive diagnostics
        
        Args:
            exchanges: 要测试的交易所列表，None表示测试所有支持的交易所
            
        Returns:
            Dict: 诊断结果
        """
        if exchanges is None:
            exchanges = AdapterFactory.get_supported_exchanges()
        
        logger.info(f"🔍 开始适配器综合诊断，测试交易所: {exchanges}")
        
        diagnostics_result = {
            "timestamp": datetime.now().isoformat(),
            "tested_exchanges": exchanges,
            "overall_status": "unknown",
            "exchange_results": {},
            "summary": {
                "total_exchanges": len(exchanges),
                "healthy_exchanges": 0,
                "unhealthy_exchanges": 0,
                "unsupported_exchanges": 0
            }
        }
        
        for exchange in exchanges:
            logger.info(f"🔍 诊断交易所: {exchange}")
            exchange_result = await self._diagnose_exchange(exchange)
            diagnostics_result["exchange_results"][exchange] = exchange_result
            
            # 更新统计信息
            if exchange_result["status"] == "healthy":
                diagnostics_result["summary"]["healthy_exchanges"] += 1
            elif exchange_result["status"] == "unsupported":
                diagnostics_result["summary"]["unsupported_exchanges"] += 1
            else:
                diagnostics_result["summary"]["unhealthy_exchanges"] += 1
        
        # 确定整体状态
        if diagnostics_result["summary"]["healthy_exchanges"] == len(exchanges):
            diagnostics_result["overall_status"] = "all_healthy"
        elif diagnostics_result["summary"]["healthy_exchanges"] > 0:
            diagnostics_result["overall_status"] = "partially_healthy"
        else:
            diagnostics_result["overall_status"] = "all_unhealthy"
        
        logger.info(f"✅ 适配器综合诊断完成，整体状态: {diagnostics_result['overall_status']}")
        return diagnostics_result
    
    async def _diagnose_exchange(self, exchange_name: str) -> Dict[str, Any]:
        """
        诊断单个交易所适配器
        Diagnose single exchange adapter
        """
        result = {
            "exchange": exchange_name,
            "timestamp": datetime.now().isoformat(),
            "status": "unknown",
            "tests": {},
            "performance": {},
            "errors": []
        }
        
        try:
            # 1. 基础健康检查
            health_check = AdapterFactory.validate_adapter_health(exchange_name)
            result["tests"]["health_check"] = health_check
            
            if health_check["status"] != "healthy":
                result["status"] = health_check["status"]
                if "error" in health_check:
                    result["errors"].append({
                        "type": "health_check_failed",
                        "message": health_check["error"]
                    })
                return result
            
            # 2. 适配器实例化测试
            adapter = AdapterFactory.get_adapter(exchange_name)
            result["tests"]["instantiation"] = {"status": "success"}
            
            # 3. 适配器信息获取测试
            adapter_info = adapter.get_adapter_info()
            result["tests"]["info_retrieval"] = {
                "status": "success",
                "adapter_info": adapter_info
            }
            
            # 4. 缓存功能测试
            cache_test = await self._test_cache_functionality(exchange_name)
            result["tests"]["cache_functionality"] = cache_test
            
            # 5. 错误处理测试
            error_handling_test = await self._test_error_handling(adapter)
            result["tests"]["error_handling"] = error_handling_test
            
            # 6. 性能测试
            performance_test = await self._test_adapter_performance(adapter)
            result["performance"] = performance_test
            
            # 确定最终状态
            all_tests_passed = all(
                test.get("status") == "success" 
                for test in result["tests"].values()
                if isinstance(test, dict)
            )
            
            result["status"] = "healthy" if all_tests_passed else "unhealthy"
            
        except Exception as e:
            result["status"] = "error"
            result["errors"].append({
                "type": "diagnostic_error",
                "message": str(e),
                "error_type": type(e).__name__
            })
            logger.error(f"❌ 诊断交易所 {exchange_name} 时发生错误: {e}")
        
        return result
    
    async def _test_cache_functionality(self, exchange_name: str) -> Dict[str, Any]:
        """测试缓存功能"""
        try:
            # 清空缓存
            AdapterFactory.clear_cache()
            
            # 第一次获取（应该创建新实例）
            start_time = datetime.now()
            adapter1 = AdapterFactory.get_adapter(exchange_name, use_cache=True)
            first_call_time = (datetime.now() - start_time).total_seconds()
            
            # 第二次获取（应该使用缓存）
            start_time = datetime.now()
            adapter2 = AdapterFactory.get_adapter(exchange_name, use_cache=True)
            second_call_time = (datetime.now() - start_time).total_seconds()
            
            # 验证是否是同一个实例
            cache_hit = adapter1 is adapter2
            
            return {
                "status": "success",
                "cache_hit": cache_hit,
                "first_call_time": first_call_time,
                "second_call_time": second_call_time,
                "performance_improvement": first_call_time > second_call_time
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }
    
    async def _test_error_handling(self, adapter) -> Dict[str, Any]:
        """测试错误处理"""
        try:
            # 测试字段映射错误处理
            try:
                adapter._validate_required_fields({}, ["required_field"], "test_data")
                field_mapping_test = {"status": "failed", "reason": "应该抛出FieldMappingError"}
            except FieldMappingError:
                field_mapping_test = {"status": "success"}
            except Exception as e:
                field_mapping_test = {"status": "failed", "error": str(e)}
            
            # 测试错误处理方法
            try:
                test_error = ValueError("测试错误")
                adapter._handle_adaptation_error(test_error, "test_data")
                error_handling_test = {"status": "failed", "reason": "应该抛出DataAdaptationError"}
            except DataAdaptationError:
                error_handling_test = {"status": "success"}
            except Exception as e:
                error_handling_test = {"status": "failed", "error": str(e)}
            
            return {
                "status": "success",
                "field_mapping_error": field_mapping_test,
                "error_handling": error_handling_test
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }
    
    async def _test_adapter_performance(self, adapter) -> Dict[str, Any]:
        """测试适配器性能"""
        try:
            performance_metrics = {
                "instantiation_time": 0,
                "info_retrieval_time": 0,
                "memory_usage": 0
            }
            
            # 测试信息获取性能
            start_time = datetime.now()
            adapter.get_adapter_info()
            performance_metrics["info_retrieval_time"] = (datetime.now() - start_time).total_seconds()
            
            # 估算内存使用（简单估算）
            import sys
            performance_metrics["memory_usage"] = sys.getsizeof(adapter)
            
            return {
                "status": "success",
                "metrics": performance_metrics
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }
    
    def generate_diagnostic_report(self, diagnostics_result: Dict[str, Any]) -> str:
        """
        生成诊断报告
        Generate diagnostic report
        """
        report_lines = [
            "=" * 60,
            "适配器系统诊断报告",
            "Adapter System Diagnostic Report",
            "=" * 60,
            f"诊断时间: {diagnostics_result['timestamp']}",
            f"测试交易所: {', '.join(diagnostics_result['tested_exchanges'])}",
            f"整体状态: {diagnostics_result['overall_status']}",
            "",
            "摘要信息:",
            f"  总交易所数: {diagnostics_result['summary']['total_exchanges']}",
            f"  健康交易所: {diagnostics_result['summary']['healthy_exchanges']}",
            f"  异常交易所: {diagnostics_result['summary']['unhealthy_exchanges']}",
            f"  不支持交易所: {diagnostics_result['summary']['unsupported_exchanges']}",
            "",
            "详细结果:",
        ]
        
        for exchange, result in diagnostics_result["exchange_results"].items():
            report_lines.extend([
                f"  {exchange}:",
                f"    状态: {result['status']}",
            ])
            
            if "tests" in result:
                report_lines.append("    测试结果:")
                for test_name, test_result in result["tests"].items():
                    if isinstance(test_result, dict):
                        status = test_result.get("status", "unknown")
                        report_lines.append(f"      {test_name}: {status}")
            
            if "errors" in result and result["errors"]:
                report_lines.append("    错误信息:")
                for error in result["errors"]:
                    report_lines.append(f"      - {error['message']}")
            
            report_lines.append("")
        
        report_lines.extend([
            "=" * 60,
            "报告结束"
        ])
        
        return "\n".join(report_lines)
    
    async def quick_health_check(self, exchange_name: str) -> bool:
        """
        快速健康检查
        Quick health check
        
        Args:
            exchange_name: 交易所名称
            
        Returns:
            bool: 是否健康
        """
        try:
            health_info = AdapterFactory.validate_adapter_health(exchange_name)
            return health_info["status"] == "healthy"
        except Exception as e:
            logger.error(f"❌ 快速健康检查失败 {exchange_name}: {e}")
            return False


# 便利函数
async def run_adapter_diagnostics(exchanges: List[str] = None) -> Dict[str, Any]:
    """
    运行适配器诊断的便利函数
    Convenience function to run adapter diagnostics
    """
    diagnostics = AdapterDiagnostics()
    return await diagnostics.run_comprehensive_diagnostics(exchanges)


async def quick_check_all_adapters() -> Dict[str, bool]:
    """
    快速检查所有适配器的便利函数
    Convenience function to quickly check all adapters
    """
    diagnostics = AdapterDiagnostics()
    exchanges = AdapterFactory.get_supported_exchanges()
    
    results = {}
    for exchange in exchanges:
        results[exchange] = await diagnostics.quick_health_check(exchange)
    
    return results


def print_diagnostic_report(diagnostics_result: Dict[str, Any]) -> None:
    """
    打印诊断报告的便利函数
    Convenience function to print diagnostic report
    """
    diagnostics = AdapterDiagnostics()
    report = diagnostics.generate_diagnostic_report(diagnostics_result)
    print(report)
    logger.info("📋 适配器诊断报告已生成")


# 初始化日志
logger.info("🔧 适配器诊断工具初始化完成")