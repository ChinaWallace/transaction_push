# -*- coding: utf-8 -*-
"""
调度配置管理API
提供查看和管理调度配置的接口
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)
router = APIRouter(prefix="/scheduler-config", tags=["调度配置管理"])


class TaskIntervalUpdateRequest(BaseModel):
    """任务间隔更新请求"""
    task_name: str = Field(..., description="任务名称")
    task_category: str = Field(default="main_tasks", description="任务类别")
    interval_minutes: int = Field(..., ge=1, le=10080, description="间隔时间(分钟), 1-10080(7天)")


class CacheTimeoutUpdateRequest(BaseModel):
    """缓存超时更新请求"""
    cache_name: str = Field(..., description="缓存名称")
    timeout_seconds: int = Field(..., ge=10, le=86400, description="超时时间(秒), 10秒-24小时")


@router.get("/summary")
async def get_scheduler_summary() -> Dict[str, Any]:
    """获取调度配置摘要"""
    try:
        settings = get_settings()
        
        summary = settings.scheduler_summary
        
        # 添加更多详细信息
        detailed_summary = {
            **summary,
            "configuration_sections": {
                "main_tasks": "主要监控任务",
                "core_scheduler_tasks": "核心调度器任务", 
                "kronos_tasks": "Kronos AI任务",
                "cache_timeouts": "缓存超时配置",
                "notification_cooldowns": "通知冷却时间",
                "http_timeouts": "HTTP超时配置"
            },
            "total_configured_items": (
                len(settings.scheduler_config.get('main_tasks', {})) +
                len(settings.scheduler_config.get('core_scheduler_tasks', {})) +
                len(settings.scheduler_config.get('kronos_tasks', {})) +
                len(settings.scheduler_config.get('cache_timeouts', {})) +
                len(settings.scheduler_config.get('notification_cooldowns', {})) +
                len(settings.scheduler_config.get('http_timeouts', {}))
            ),
            "timestamp": datetime.now()
        }
        
        return {
            "success": True,
            "message": "调度配置摘要获取成功",
            "data": detailed_summary
        }
        
    except Exception as e:
        logger.error(f"获取调度配置摘要失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def get_all_task_intervals() -> Dict[str, Any]:
    """获取所有任务的调度间隔"""
    try:
        settings = get_settings()
        
        all_intervals = settings.all_task_intervals
        
        # 按类别组织数据
        organized_data = {
            "main_tasks": {},
            "core_scheduler_tasks": {},
            "kronos_tasks": {}
        }
        
        for task_key, interval in all_intervals.items():
            category, task_name = task_key.split('.', 1)
            if category in organized_data:
                organized_data[category][task_name] = {
                    "interval_minutes": interval,
                    "interval_hours": round(interval / 60, 2),
                    "description": _get_task_description(task_name)
                }
        
        return {
            "success": True,
            "message": f"获取到{len(all_intervals)}个任务配置",
            "data": {
                "tasks_by_category": organized_data,
                "total_tasks": len(all_intervals),
                "timestamp": datetime.now()
            }
        }
        
    except Exception as e:
        logger.error(f"获取任务间隔配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_category}")
async def get_task_intervals_by_category(
    task_category: str,
    include_descriptions: bool = Query(True, description="是否包含任务描述")
) -> Dict[str, Any]:
    """获取指定类别的任务间隔"""
    try:
        settings = get_settings()
        
        valid_categories = ["main_tasks", "core_scheduler_tasks", "kronos_tasks"]
        if task_category not in valid_categories:
            raise HTTPException(
                status_code=400, 
                detail=f"无效的任务类别。支持的类别: {valid_categories}"
            )
        
        category_tasks = settings.scheduler_config.get(task_category, {})
        
        if include_descriptions:
            formatted_tasks = {}
            for task_name, interval in category_tasks.items():
                formatted_tasks[task_name] = {
                    "interval_minutes": interval,
                    "interval_hours": round(interval / 60, 2),
                    "description": _get_task_description(task_name)
                }
        else:
            formatted_tasks = category_tasks
        
        return {
            "success": True,
            "message": f"获取{task_category}类别任务配置成功",
            "data": {
                "category": task_category,
                "tasks": formatted_tasks,
                "count": len(category_tasks),
                "timestamp": datetime.now()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取{task_category}任务间隔失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/caches")
async def get_cache_timeouts() -> Dict[str, Any]:
    """获取所有缓存超时配置"""
    try:
        settings = get_settings()
        
        cache_timeouts = settings.scheduler_config.get('cache_timeouts', {})
        
        formatted_caches = {}
        for cache_name, timeout_seconds in cache_timeouts.items():
            formatted_caches[cache_name] = {
                "timeout_seconds": timeout_seconds,
                "timeout_minutes": round(timeout_seconds / 60, 2),
                "timeout_hours": round(timeout_seconds / 3600, 2),
                "description": _get_cache_description(cache_name)
            }
        
        return {
            "success": True,
            "message": f"获取到{len(cache_timeouts)}个缓存配置",
            "data": {
                "caches": formatted_caches,
                "count": len(cache_timeouts),
                "timestamp": datetime.now()
            }
        }
        
    except Exception as e:
        logger.error(f"获取缓存配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications")
async def get_notification_cooldowns() -> Dict[str, Any]:
    """获取所有通知冷却时间配置"""
    try:
        settings = get_settings()
        
        cooldowns = settings.scheduler_config.get('notification_cooldowns', {})
        
        formatted_cooldowns = {}
        for notif_type, cooldown_minutes in cooldowns.items():
            formatted_cooldowns[notif_type] = {
                "cooldown_minutes": cooldown_minutes,
                "cooldown_hours": round(cooldown_minutes / 60, 2),
                "description": _get_notification_description(notif_type)
            }
        
        return {
            "success": True,
            "message": f"获取到{len(cooldowns)}个通知冷却配置",
            "data": {
                "notifications": formatted_cooldowns,
                "count": len(cooldowns),
                "timestamp": datetime.now()
            }
        }
        
    except Exception as e:
        logger.error(f"获取通知冷却配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/http-timeouts")
async def get_http_timeouts() -> Dict[str, Any]:
    """获取所有HTTP超时配置"""
    try:
        settings = get_settings()
        
        http_timeouts = settings.scheduler_config.get('http_timeouts', {})
        
        formatted_timeouts = {}
        for timeout_type, timeout_seconds in http_timeouts.items():
            formatted_timeouts[timeout_type] = {
                "timeout_seconds": timeout_seconds,
                "timeout_minutes": round(timeout_seconds / 60, 2),
                "description": _get_http_timeout_description(timeout_type)
            }
        
        return {
            "success": True,
            "message": f"获取到{len(http_timeouts)}个HTTP超时配置",
            "data": {
                "http_timeouts": formatted_timeouts,
                "count": len(http_timeouts),
                "timestamp": datetime.now()
            }
        }
        
    except Exception as e:
        logger.error(f"获取HTTP超时配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task/{task_name}")
async def get_task_interval(
    task_name: str,
    task_category: str = Query("main_tasks", description="任务类别")
) -> Dict[str, Any]:
    """获取指定任务的调度间隔"""
    try:
        settings = get_settings()
        
        interval = settings.get_task_interval(task_name, task_category)
        
        return {
            "success": True,
            "message": f"获取任务{task_name}配置成功",
            "data": {
                "task_name": task_name,
                "task_category": task_category,
                "interval_minutes": interval,
                "interval_hours": round(interval / 60, 2),
                "description": _get_task_description(task_name),
                "timestamp": datetime.now()
            }
        }
        
    except Exception as e:
        logger.error(f"获取任务{task_name}间隔失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/usage-examples")
async def get_usage_examples() -> Dict[str, Any]:
    """获取配置使用示例"""
    try:
        settings = get_settings()
        
        examples = {
            "python_code": {
                "get_task_interval": {
                    "description": "获取任务调度间隔",
                    "code": """
from app.core.config import get_settings
settings = get_settings()

# 获取主要任务间隔
interval = settings.get_task_interval('negative_funding_monitor')

# 获取核心调度器任务间隔  
interval = settings.get_task_interval('core_monitoring', 'core_scheduler_tasks')

# 获取Kronos任务间隔
interval = settings.get_task_interval('prediction_update', 'kronos_tasks')
                    """.strip()
                },
                "get_cache_timeout": {
                    "description": "获取缓存超时时间",
                    "code": """
# 获取缓存超时时间（秒）
timeout = settings.get_cache_timeout('volume_anomaly_cache')
timeout = settings.get_cache_timeout('market_anomaly_cache')
                    """.strip()
                },
                "get_notification_cooldown": {
                    "description": "获取通知冷却时间",
                    "code": """
# 获取通知冷却时间（分钟）
cooldown = settings.get_notification_cooldown('trading_signal')
cooldown = settings.get_notification_cooldown('market_anomaly')
                    """.strip()
                },
                "scheduler_usage": {
                    "description": "在调度器中使用",
                    "code": f"""
# 在main.py中使用
scheduler.add_job(
    negative_funding_service.run_monitoring_cycle,
    'interval',
    minutes=settings.get_task_interval('negative_funding_monitor'),  # {settings.get_task_interval('negative_funding_monitor')} 分钟
    id='negative_funding_monitor'
)
                    """.strip()
                }
            },
            "current_values": {
                "sample_task_intervals": {
                    "negative_funding_monitor": f"{settings.get_task_interval('negative_funding_monitor')} 分钟",
                    "market_anomaly_monitor": f"{settings.get_task_interval('market_anomaly_monitor')} 分钟",
                    "volume_anomaly_monitor": f"{settings.get_task_interval('volume_anomaly_monitor')} 分钟"
                },
                "sample_cache_timeouts": {
                    "volume_anomaly_cache": f"{settings.get_cache_timeout('volume_anomaly_cache')} 秒",
                    "market_anomaly_cache": f"{settings.get_cache_timeout('market_anomaly_cache')} 秒"
                },
                "sample_notification_cooldowns": {
                    "trading_signal": f"{settings.get_notification_cooldown('trading_signal')} 分钟",
                    "market_anomaly": f"{settings.get_notification_cooldown('market_anomaly')} 分钟"
                }
            }
        }
        
        return {
            "success": True,
            "message": "配置使用示例获取成功",
            "data": examples
        }
        
    except Exception as e:
        logger.error(f"获取使用示例失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _get_task_description(task_name: str) -> str:
    """获取任务描述"""
    descriptions = {
        "negative_funding_monitor": "负费率监控 - 监控负费率套利机会",
        "trend_analysis": "趋势分析 - 分析市场趋势变化",
        "kronos_position_analysis": "Kronos持仓分析 - AI驱动的持仓风险分析",
        "market_anomaly_monitor": "市场异常监控 - 监控价格、交易量等异常",
        "volume_anomaly_monitor": "交易量异常监控 - 专门监控交易量异常",
        "open_interest_monitor": "持仓量监控 - 监控期货持仓量变化",
        "grid_opportunities": "网格机会扫描 - 扫描网格交易机会",
        "profit_opportunities": "收益机会扫描 - 扫描高收益交易机会",
        "health_check": "健康检查 - 系统健康状态检查",
        "daily_report": "每日报告 - 生成每日系统报告",
        "core_monitoring": "核心监控 - 综合监控系统状态",
        "opportunity_scan": "机会扫描 - 扫描各种交易机会",
        "position_analysis": "持仓分析 - 分析当前持仓状况",
        "prediction_update": "Kronos预测更新 - 更新AI预测数据",
        "market_scan": "市场强信号扫描 - 扫描强交易信号",
        "profit_scan": "收益机会扫描 - 扫描高收益机会",
        "grid_trading_scan": "网格交易扫描 - 扫描网格交易机会"
    }
    return descriptions.get(task_name, f"{task_name} - 暂无描述")


def _get_cache_description(cache_name: str) -> str:
    """获取缓存描述"""
    descriptions = {
        "volume_anomaly_cache": "交易量异常数据缓存",
        "market_anomaly_cache": "市场异常数据缓存",
        "price_data_cache": "价格数据缓存",
        "funding_rate_cache": "费率数据缓存",
        "exchange_data_cache": "交易所数据缓存"
    }
    return descriptions.get(cache_name, f"{cache_name} - 暂无描述")


def _get_notification_description(notif_type: str) -> str:
    """获取通知类型描述"""
    descriptions = {
        "trading_signal": "交易信号通知冷却",
        "market_anomaly": "市场异常通知冷却", 
        "system_alert": "系统告警通知冷却",
        "profit_opportunity": "收益机会通知冷却",
        "emergency_alert": "紧急告警通知冷却"
    }
    return descriptions.get(notif_type, f"{notif_type} - 暂无描述")


def _get_http_timeout_description(timeout_type: str) -> str:
    """获取HTTP超时类型描述"""
    descriptions = {
        "exchange_api_timeout": "交易所API请求超时",
        "notification_timeout": "通知发送超时",
        "database_timeout": "数据库查询超时", 
        "model_prediction_timeout": "AI模型预测超时"
    }
    return descriptions.get(timeout_type, f"{timeout_type} - 暂无描述")
