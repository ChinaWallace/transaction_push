# -*- coding: utf-8 -*-
"""
交易所管理API
Exchange Management API - 提供交易所切换和管理功能
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from datetime import datetime

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.exchanges.service_manager import (
    get_exchange_service_manager,
    switch_exchange,
    get_exchange_service_status,
    start_exchange_services,
    stop_exchange_services
)
from app.services.exchanges.config_monitor import (
    get_configuration_monitor,
    get_config_monitoring_status
)
from app.services.exchanges.factory import ExchangeFactory

logger = get_logger(__name__)
router = APIRouter(prefix="/api/exchange", tags=["交易所管理"])


class SwitchExchangeRequest(BaseModel):
    """切换交易所请求"""
    exchange: str = Field(..., description="目标交易所名称 (okx, binance)")
    force: bool = Field(default=False, description="是否强制切换")
    update_config: bool = Field(default=False, description="是否同时更新配置文件")


class ExchangeStatusResponse(BaseModel):
    """交易所状态响应"""
    is_running: bool
    current_exchange: Optional[str]
    startup_time: Optional[datetime]
    uptime_seconds: float
    supported_exchanges: List[str]
    statistics: Dict[str, Any]
    factory_status: Dict[str, Any]


@router.get("/status", response_model=Dict[str, Any])
async def get_exchange_status():
    """
    获取交易所服务状态
    Get exchange service status
    """
    try:
        status = get_exchange_service_status()
        return {
            "status": "success",
            "data": status,
            "timestamp": datetime.now()
        }
    except Exception as e:
        logger.error(f"获取交易所状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/supported")
async def get_supported_exchanges():
    """
    获取支持的交易所列表
    Get list of supported exchanges
    """
    try:
        supported = ExchangeFactory.get_supported_exchanges()
        return {
            "status": "success",
            "supported_exchanges": supported,
            "count": len(supported),
            "timestamp": datetime.now()
        }
    except Exception as e:
        logger.error(f"获取支持的交易所列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/switch")
async def switch_exchange_endpoint(
    request: SwitchExchangeRequest,
    background_tasks: BackgroundTasks
):
    """
    切换交易所
    Switch exchange
    """
    try:
        logger.info(f"🔄 API请求切换交易所: {request.exchange}")
        
        # 验证交易所名称
        supported_exchanges = ExchangeFactory.get_supported_exchanges()
        if request.exchange not in supported_exchanges:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的交易所: {request.exchange}。支持的交易所: {supported_exchanges}"
            )
        
        # 执行切换
        switch_result = await switch_exchange(request.exchange, request.force)
        
        # 如果需要更新配置文件
        if request.update_config and switch_result['status'] == 'success':
            background_tasks.add_task(
                _update_exchange_config,
                request.exchange
            )
        
        return {
            "status": "success",
            "switch_result": switch_result,
            "config_updated": request.update_config,
            "timestamp": datetime.now()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"切换交易所失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restart")
async def restart_exchange_services():
    """
    重启交易所服务
    Restart exchange services
    """
    try:
        logger.info("🔄 API请求重启交易所服务")
        
        # 停止服务
        stop_result = await stop_exchange_services()
        
        # 启动服务
        start_result = await start_exchange_services()
        
        return {
            "status": "success",
            "stop_result": stop_result,
            "start_result": start_result,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"重启交易所服务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload-config")
async def reload_exchange_config():
    """
    重新加载交易所配置
    Reload exchange configuration
    """
    try:
        logger.info("🔄 API请求重新加载交易所配置")
        
        manager = await get_exchange_service_manager()
        reload_result = await manager.reload_configuration()
        
        return {
            "status": "success",
            "reload_result": reload_result,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"重新加载配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """
    交易所服务健康检查
    Exchange service health check
    """
    try:
        manager = await get_exchange_service_manager()
        current_service = manager.get_current_service()
        
        if current_service is None:
            return {
                "status": "unhealthy",
                "message": "没有活跃的交易所服务",
                "timestamp": datetime.now()
            }
        
        # 执行健康检查
        if hasattr(current_service, 'health_check'):
            health_result = await current_service.health_check()
            return {
                "status": "success",
                "health_result": health_result,
                "timestamp": datetime.now()
            }
        else:
            # 简单检查服务状态
            service_status = current_service.get_service_status()
            return {
                "status": "success",
                "service_status": service_status,
                "message": "服务运行正常（简单检查）",
                "timestamp": datetime.now()
            }
            
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now()
        }


@router.get("/statistics")
async def get_exchange_statistics():
    """
    获取交易所服务统计信息
    Get exchange service statistics
    """
    try:
        # 获取工厂统计
        factory_stats = ExchangeFactory.get_initialization_statistics()
        
        # 获取服务管理器状态
        service_status = get_exchange_service_status()
        
        return {
            "status": "success",
            "factory_statistics": factory_stats,
            "service_statistics": service_status.get('statistics', {}),
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"获取统计信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _update_exchange_config(exchange: str):
    """
    更新配置文件中的交易所设置
    Update exchange setting in configuration file
    
    Args:
        exchange: 交易所名称 / Exchange name
    """
    try:
        logger.info(f"🔧 更新配置文件中的交易所设置: {exchange}")
        
        # 这里可以实现配置文件更新逻辑
        # 由于使用环境变量，这里主要是记录日志
        logger.info(f"💡 请手动更新 .env 文件中的 EXCHANGE_PROVIDER={exchange}")
        
        # 如果需要，可以在这里实现自动更新 .env 文件的逻辑
        # 但需要注意文件权限和并发访问问题
        
    except Exception as e:
        logger.error(f"更新配置文件失败: {e}")


# 配置监控任务
class ConfigurationMonitor:
    """配置监控器"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self._last_config_hash = None
        self._monitoring = False
    
    async def start_monitoring(self):
        """开始监控配置变化"""
        if self._monitoring:
            return
        
        self._monitoring = True
        self.logger.info("🔍 开始监控配置变化...")
        
        # 这里可以实现配置文件监控逻辑
        # 例如使用 watchdog 库监控 .env 文件变化
        
    async def stop_monitoring(self):
        """停止监控配置变化"""
        self._monitoring = False
        self.logger.info("🛑 停止监控配置变化")
    
    async def check_configuration_changes(self):
        """检查配置变化"""
        try:
            settings = get_settings()
            current_exchange = settings.exchange_provider
            
            # 获取当前服务状态
            status = get_exchange_service_status()
            running_exchange = status.get('current_exchange')
            
            if current_exchange != running_exchange:
                self.logger.info(f"🔄 检测到配置变化: {running_exchange} -> {current_exchange}")
                
                # 自动切换交易所
                switch_result = await switch_exchange(current_exchange)
                
                if switch_result['status'] == 'success':
                    self.logger.info(f"✅ 自动切换交易所成功: {current_exchange}")
                else:
                    self.logger.error(f"❌ 自动切换交易所失败: {switch_result.get('error')}")
                
                return switch_result
            
            return None
            
        except Exception as e:
            self.logger.error(f"检查配置变化失败: {e}")
            return None


# 全局配置监控器实例
_config_monitor: Optional[ConfigurationMonitor] = None


async def get_configuration_monitor() -> ConfigurationMonitor:
    """获取配置监控器实例"""
    global _config_monitor
    if _config_monitor is None:
        _config_monitor = ConfigurationMonitor()
    return _config_monitor


@router.post("/monitor/start")
async def start_config_monitoring():
    """
    开始配置监控
    Start configuration monitoring
    """
    try:
        monitor = await get_configuration_monitor()
        await monitor.start_monitoring()
        
        return {
            "status": "success",
            "message": "配置监控已启动",
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"启动配置监控失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/monitor/stop")
async def stop_config_monitoring():
    """
    停止配置监控
    Stop configuration monitoring
    """
    try:
        monitor = await get_configuration_monitor()
        await monitor.stop_monitoring()
        
        return {
            "status": "success",
            "message": "配置监控已停止",
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"停止配置监控失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/monitor/check")
async def check_config_changes():
    """
    手动检查配置变化
    Manually check configuration changes
    """
    try:
        monitor = await get_configuration_monitor()
        change_result = await monitor.manual_check()
        
        return {
            "status": "success",
            "check_result": change_result,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"检查配置变化失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monitor/status")
async def get_config_monitor_status():
    """
    获取配置监控状态
    Get configuration monitor status
    """
    try:
        status = get_config_monitoring_status()
        return {
            "status": "success",
            "monitor_status": status,
            "timestamp": datetime.now()
        }
    except Exception as e:
        logger.error(f"获取配置监控状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monitor/history")
async def get_config_change_history(limit: int = 20):
    """
    获取配置变更历史
    Get configuration change history
    """
    try:
        monitor = await get_configuration_monitor()
        history = monitor.get_change_history(limit)
        
        return {
            "status": "success",
            "change_history": history,
            "count": len(history),
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"获取配置变更历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))