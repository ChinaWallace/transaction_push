# -*- coding: utf-8 -*-
"""
系统诊断API
System Diagnostics API - 提供系统健康状况和错误诊断接口
"""

from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.utils.system_diagnostics import get_system_diagnostics
from app.utils.error_analyzer import get_error_analyzer

logger = get_logger(__name__)

router = APIRouter(prefix="/api/diagnostics", tags=["系统诊断"])


@router.get("/health-report", summary="获取系统健康报告")
async def get_health_report():
    """
    获取完整的系统健康报告
    
    Returns:
        系统健康状况、错误统计和建议
    """
    try:
        logger.info("📊 获取系统健康报告...")
        
        diagnostics = get_system_diagnostics()
        report = await diagnostics.run_diagnostic_check()
        
        logger.info(f"✅ 系统健康报告生成完成，健康评分: {report.get('overall_health_score', 0):.1f}")
        
        return {
            "success": True,
            "data": report,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"❌ 获取系统健康报告失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取健康报告失败: {str(e)}")


@router.get("/error-statistics", summary="获取错误统计")
async def get_error_statistics():
    """
    获取详细的错误统计信息
    
    Returns:
        按类别分组的错误统计
    """
    try:
        logger.info("📈 获取错误统计信息...")
        
        diagnostics = get_system_diagnostics()
        error_stats = diagnostics.get_error_statistics()
        
        # 格式化统计信息
        formatted_stats = []
        for stat in error_stats:
            formatted_stats.append({
                "category": stat.category,
                "count": stat.count,
                "hourly_rate": stat.hourly_rate,
                "is_increasing": stat.is_increasing,
                "last_occurrence": stat.last_occurrence,
                "severity_distribution": stat.severity_distribution,
                "status": "critical" if stat.hourly_rate > 20 else "warning" if stat.hourly_rate > 10 else "normal"
            })
        
        return {
            "success": True,
            "data": {
                "error_statistics": formatted_stats,
                "total_categories": len(error_stats),
                "high_frequency_errors": [s for s in formatted_stats if s["hourly_rate"] > 10],
                "increasing_errors": [s for s in formatted_stats if s["is_increasing"]]
            },
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"❌ 获取错误统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取错误统计失败: {str(e)}")


@router.get("/system-metrics", summary="获取系统指标")
async def get_system_metrics():
    """
    获取当前系统资源使用情况
    
    Returns:
        CPU、内存、磁盘等系统指标
    """
    try:
        logger.info("💻 获取系统指标...")
        
        diagnostics = get_system_diagnostics()
        metrics = await diagnostics.collect_system_metrics()
        
        # 判断资源使用状态
        cpu_status = "high" if metrics.cpu_percent > 80 else "normal" if metrics.cpu_percent > 60 else "low"
        memory_status = "high" if metrics.memory_percent > 85 else "normal" if metrics.memory_percent > 70 else "low"
        disk_status = "high" if metrics.disk_usage_percent > 90 else "normal" if metrics.disk_usage_percent > 75 else "low"
        
        return {
            "success": True,
            "data": {
                "metrics": {
                    "cpu_percent": metrics.cpu_percent,
                    "cpu_status": cpu_status,
                    "memory_percent": metrics.memory_percent,
                    "memory_available_mb": metrics.memory_available_mb,
                    "memory_status": memory_status,
                    "disk_usage_percent": metrics.disk_usage_percent,
                    "disk_status": disk_status,
                    "network_connections": metrics.network_connections,
                    "active_threads": metrics.active_threads
                },
                "collection_time": metrics.timestamp,
                "overall_status": "critical" if any(s == "high" for s in [cpu_status, memory_status, disk_status]) else "normal"
            },
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"❌ 获取系统指标失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取系统指标失败: {str(e)}")


@router.get("/service-health", summary="获取服务健康状态") 
async def get_service_health():
    """
    获取各个服务的健康状态
    
    Returns:
        服务健康状况和性能指标
    """
    try:
        logger.info("🔧 获取服务健康状态...")
        
        diagnostics = get_system_diagnostics()
        
        # 触发服务健康检查
        await diagnostics._check_critical_services()
        
        # 获取服务状态汇总
        service_summary = {}
        for service_name, health_data in diagnostics.service_health.items():
            if health_data['total_checks'] > 0:
                success_rate = (health_data['successful_checks'] / health_data['total_checks']) * 100
                avg_response_time = health_data['total_response_time'] / health_data['total_checks']
                
                # 计算最近响应时间趋势
                recent_times = list(health_data['response_times'])[-10:]  # 最近10次
                avg_recent_time = sum(recent_times) / len(recent_times) if recent_times else 0
                
                status = 'healthy' if success_rate > 95 and avg_recent_time < 5.0 else \
                        'degraded' if success_rate > 80 else 'unhealthy'
                
                service_summary[service_name] = {
                    'status': status,
                    'success_rate': round(success_rate, 2),
                    'avg_response_time': round(avg_response_time, 3),
                    'recent_avg_response_time': round(avg_recent_time, 3),
                    'error_count': health_data['error_count'],
                    'total_checks': health_data['total_checks'],
                    'last_check': datetime.now()
                }
        
        healthy_services = [s for s, data in service_summary.items() if data['status'] == 'healthy']
        degraded_services = [s for s, data in service_summary.items() if data['status'] == 'degraded']
        unhealthy_services = [s for s, data in service_summary.items() if data['status'] == 'unhealthy']
        
        return {
            "success": True,
            "data": {
                "services": service_summary,
                "summary": {
                    "total_services": len(service_summary),
                    "healthy_count": len(healthy_services),
                    "degraded_count": len(degraded_services),
                    "unhealthy_count": len(unhealthy_services),
                    "overall_status": "healthy" if len(unhealthy_services) == 0 and len(degraded_services) <= 1 else "degraded"
                },
                "healthy_services": healthy_services,
                "degraded_services": degraded_services,
                "unhealthy_services": unhealthy_services
            },
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"❌ 获取服务健康状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取服务健康状态失败: {str(e)}")


@router.post("/analyze-error", summary="分析特定错误")
async def analyze_error(
    error_message: str = Query(..., description="错误消息"),
    error_type: Optional[str] = Query(None, description="错误类型"),
    context: Optional[str] = Query(None, description="错误上下文(JSON格式)")
):
    """
    分析特定错误并提供诊断建议
    
    Args:
        error_message: 错误消息
        error_type: 错误类型
        context: 错误上下文
        
    Returns:
        错误分析结果和建议
    """
    try:
        logger.info(f"🔍 分析错误: {error_message[:100]}...")
        
        # 构造模拟异常对象
        class CustomError(Exception):
            def __init__(self, message: str, error_type: str = "CustomError"):
                super().__init__(message)
                self.__class__.__name__ = error_type or "CustomError"
        
        # 解析上下文
        error_context = None
        if context:
            try:
                import json
                error_context = json.loads(context)
            except json.JSONDecodeError:
                error_context = {"raw_context": context}
        
        # 分析错误
        analyzer = get_error_analyzer()
        mock_error = CustomError(error_message, error_type or "UnknownError")
        analysis = analyzer.analyze_error(mock_error, error_context)
        
        # 格式化分析报告
        report = analyzer.format_analysis_report(analysis, include_actions=True)
        
        return {
            "success": True,
            "data": {
                "analysis": {
                    "category": analysis.category.value,
                    "severity": analysis.severity,
                    "description": analysis.description,
                    "is_recoverable": analysis.is_recoverable,
                    "retry_recommended": analysis.retry_recommended,
                    "possible_causes": analysis.possible_causes,
                    "suggested_actions": analysis.suggested_actions
                },
                "formatted_report": report,
                "input": {
                    "error_message": error_message,
                    "error_type": error_type,
                    "context": error_context
                }
            },
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"❌ 错误分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"错误分析失败: {str(e)}")


@router.get("/quick-status", summary="快速状态检查")
async def get_quick_status():
    """
    快速获取系统状态概览
    
    Returns:
        系统状态的简要概览
    """
    try:
        diagnostics = get_system_diagnostics()
        
        # 获取最新指标
        metrics = await diagnostics.collect_system_metrics()
        
        # 简单的健康评估
        health_issues = []
        if metrics.cpu_percent > 80:
            health_issues.append(f"CPU使用率高 ({metrics.cpu_percent:.1f}%)")
        if metrics.memory_percent > 85:
            health_issues.append(f"内存使用率高 ({metrics.memory_percent:.1f}%)")
        if metrics.disk_usage_percent > 90:
            health_issues.append(f"磁盘使用率高 ({metrics.disk_usage_percent:.1f}%)")
        
        # 获取最近错误统计
        error_stats = diagnostics.get_error_statistics()
        recent_errors = sum(stat.hourly_rate for stat in error_stats)
        
        if recent_errors > 20:
            health_issues.append(f"错误率高 ({recent_errors:.1f}/小时)")
        
        # 总体状态
        overall_status = "critical" if len(health_issues) >= 3 else \
                        "warning" if len(health_issues) >= 1 else "healthy"
        
        return {
            "success": True,
            "data": {
                "overall_status": overall_status,
                "cpu_percent": metrics.cpu_percent,
                "memory_percent": metrics.memory_percent,
                "recent_error_rate": recent_errors,
                "health_issues": health_issues,
                "last_check": metrics.timestamp,
                "status_message": "系统正常运行" if overall_status == "healthy" else 
                                f"发现 {len(health_issues)} 个问题"
            },
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"❌ 快速状态检查失败: {e}")
        raise HTTPException(status_code=500, detail=f"状态检查失败: {str(e)}")


@router.delete("/clear-error-history", summary="清空错误历史")
async def clear_error_history():
    """
    清空错误历史记录（用于测试和维护）
    
    Returns:
        清理结果
    """
    try:
        logger.info("🧹 清空错误历史记录...")
        
        diagnostics = get_system_diagnostics()
        
        # 记录清理前的统计
        old_error_count = len(diagnostics.error_history)
        old_metrics_count = len(diagnostics.metrics_history)
        
        # 清空历史记录
        diagnostics.error_history.clear()
        diagnostics.error_counts.clear()
        diagnostics.error_timestamps.clear()
        diagnostics.error_severities.clear()
        
        logger.info(f"✅ 错误历史记录清空完成: 清理了 {old_error_count} 条错误记录")
        
        return {
            "success": True,
            "data": {
                "cleared_error_records": old_error_count,
                "cleared_metrics_records": old_metrics_count,
                "message": "错误历史记录清空完成"
            },
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"❌ 清空错误历史失败: {e}")
        raise HTTPException(status_code=500, detail=f"清空历史失败: {str(e)}")
