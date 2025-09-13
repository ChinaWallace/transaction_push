# -*- coding: utf-8 -*-
"""
交易所服务管理器
Exchange Service Manager - 管理交易所服务的启动、停止和切换
"""

import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from app.core.logging import get_logger
from app.core.config import get_settings
from app.utils.exceptions import TradingToolError
from .factory import ExchangeFactory
from .base.exchange_interface import ExchangeInterface
from .exchange_service_manager import get_exchange_service

logger = get_logger(__name__)


class ExchangeServiceManager:
    """
    交易所服务管理器
    Exchange Service Manager
    
    负责管理交易所服务的生命周期：
    1. 启动和停止服务
    2. 动态切换交易所
    3. 服务健康监控
    4. 配置变更响应
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # 服务状态
        self._current_exchange: Optional[str] = None
        self._current_service: Optional[ExchangeInterface] = None
        self._is_running = False
        self._startup_time: Optional[datetime] = None
        
        # 切换锁，确保同时只有一个切换操作
        self._switch_lock = asyncio.Lock()
        
        # 服务统计
        self._service_stats = {
            'total_switches': 0,
            'successful_switches': 0,
            'failed_switches': 0,
            'last_switch_time': None,
            'uptime_seconds': 0
        }
    
    async def start_services(self) -> Dict[str, Any]:
        """
        启动交易所服务
        Start exchange services
        
        Returns:
            Dict[str, Any]: 启动结果 / Startup result
        """
        try:
            self.logger.info("🚀 启动交易所服务管理器...")
            
            # 初始化交易所工厂
            await ExchangeFactory.initialize_factory()
            
            # 获取当前配置的交易所
            exchange_name = self.settings.exchange_provider
            self.logger.info(f"📋 配置的交易所: {exchange_name}")
            
            # 启动交易所服务
            service = await ExchangeFactory.get_exchange(exchange_name)
            
            # 更新状态
            self._current_exchange = exchange_name
            self._current_service = service
            self._is_running = True
            self._startup_time = datetime.now()
            
            self.logger.info(f"✅ 交易所服务启动成功: {exchange_name}")
            
            return {
                'status': 'success',
                'exchange': exchange_name,
                'startup_time': self._startup_time,
                'supported_exchanges': ExchangeFactory.get_supported_exchanges()
            }
            
        except Exception as e:
            self.logger.error(f"❌ 交易所服务启动失败: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'startup_time': datetime.now()
            }
    
    async def stop_services(self) -> Dict[str, Any]:
        """
        停止交易所服务
        Stop exchange services
        
        Returns:
            Dict[str, Any]: 停止结果 / Stop result
        """
        try:
            self.logger.info("🛑 停止交易所服务...")
            
            # 清理所有交易所实例
            await ExchangeFactory.cleanup_all()
            
            # 重置状态
            uptime = 0
            if self._startup_time:
                uptime = (datetime.now() - self._startup_time).total_seconds()
            
            self._current_exchange = None
            self._current_service = None
            self._is_running = False
            self._service_stats['uptime_seconds'] += uptime
            
            self.logger.info(f"✅ 交易所服务停止成功，运行时间: {uptime:.1f}秒")
            
            return {
                'status': 'success',
                'uptime_seconds': uptime,
                'stop_time': datetime.now()
            }
            
        except Exception as e:
            self.logger.error(f"❌ 交易所服务停止失败: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'stop_time': datetime.now()
            }
    
    async def switch_exchange(self, new_exchange: str, force: bool = False) -> Dict[str, Any]:
        """
        切换交易所
        Switch exchange
        
        Args:
            new_exchange: 新交易所名称 / New exchange name
            force: 是否强制切换 / Whether to force switch
            
        Returns:
            Dict[str, Any]: 切换结果 / Switch result
        """
        async with self._switch_lock:
            try:
                self.logger.info(f"🔄 开始切换交易所: {self._current_exchange} -> {new_exchange}")
                
                # 记录切换统计
                self._service_stats['total_switches'] += 1
                switch_start_time = datetime.now()
                
                # 检查是否需要切换
                if self._current_exchange == new_exchange and not force:
                    self.logger.info(f"💡 已经是目标交易所: {new_exchange}")
                    return {
                        'status': 'no_change',
                        'current_exchange': new_exchange,
                        'message': '已经是目标交易所'
                    }
                
                # 验证新交易所是否支持
                supported_exchanges = ExchangeFactory.get_supported_exchanges()
                if new_exchange not in supported_exchanges:
                    raise TradingToolError(f"不支持的交易所: {new_exchange}")
                
                # 执行切换
                old_exchange = self._current_exchange
                
                # 1. 获取新的交易所实例
                new_service = await ExchangeFactory.switch_exchange(new_exchange)
                
                # 2. 更新当前服务引用
                self._current_service = new_service
                self._current_exchange = new_exchange
                
                # 3. 清理旧的交易所实例（可选）
                if old_exchange and old_exchange != new_exchange:
                    try:
                        await ExchangeFactory.cleanup_exchange(old_exchange)
                        self.logger.info(f"🧹 清理旧交易所实例: {old_exchange}")
                    except Exception as e:
                        self.logger.warning(f"⚠️ 清理旧交易所实例失败: {e}")
                
                # 4. 验证新服务是否正常工作
                try:
                    # 简单的健康检查
                    if hasattr(new_service, 'health_check'):
                        health_result = await new_service.health_check()
                        if not health_result.get('overall_status') in ['healthy', 'degraded']:
                            raise TradingToolError("新交易所服务健康检查失败")
                    
                    self.logger.info(f"✅ 新交易所服务健康检查通过: {new_exchange}")
                    
                except Exception as e:
                    self.logger.warning(f"⚠️ 新交易所服务健康检查失败: {e}")
                    # 继续执行，但记录警告
                
                # 更新统计
                switch_duration = (datetime.now() - switch_start_time).total_seconds()
                self._service_stats['successful_switches'] += 1
                self._service_stats['last_switch_time'] = datetime.now()
                
                self.logger.info(f"✅ 交易所切换成功: {old_exchange} -> {new_exchange} ({switch_duration:.2f}秒)")
                
                return {
                    'status': 'success',
                    'old_exchange': old_exchange,
                    'new_exchange': new_exchange,
                    'switch_duration_seconds': switch_duration,
                    'switch_time': datetime.now()
                }
                
            except Exception as e:
                # 切换失败统计
                self._service_stats['failed_switches'] += 1
                
                self.logger.error(f"❌ 交易所切换失败: {e}")
                
                return {
                    'status': 'error',
                    'error': str(e),
                    'old_exchange': self._current_exchange,
                    'target_exchange': new_exchange,
                    'switch_time': datetime.now()
                }
    
    async def reload_configuration(self) -> Dict[str, Any]:
        """
        重新加载配置并相应调整服务
        Reload configuration and adjust services accordingly
        
        Returns:
            Dict[str, Any]: 重新加载结果 / Reload result
        """
        try:
            self.logger.info("🔄 重新加载交易所配置...")
            
            # 重新获取设置
            self.settings = get_settings()
            
            # 检查交易所配置是否发生变化
            configured_exchange = self.settings.exchange_provider
            
            if self._current_exchange != configured_exchange:
                self.logger.info(f"🔄 检测到交易所配置变化: {self._current_exchange} -> {configured_exchange}")
                
                # 执行切换
                switch_result = await self.switch_exchange(configured_exchange)
                
                return {
                    'status': 'configuration_changed',
                    'switch_result': switch_result,
                    'reload_time': datetime.now()
                }
            else:
                self.logger.info("💡 交易所配置无变化")
                
                # 重新加载工厂配置
                await ExchangeFactory.reload_configuration()
                
                return {
                    'status': 'no_change',
                    'current_exchange': configured_exchange,
                    'reload_time': datetime.now()
                }
                
        except Exception as e:
            self.logger.error(f"❌ 重新加载配置失败: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'reload_time': datetime.now()
            }
    
    def get_current_exchange(self) -> Optional[str]:
        """
        获取当前交易所名称
        Get current exchange name
        
        Returns:
            Optional[str]: 当前交易所名称 / Current exchange name
        """
        return self._current_exchange
    
    def get_current_service(self) -> Optional[ExchangeInterface]:
        """
        获取当前交易所服务实例
        Get current exchange service instance
        
        Returns:
            Optional[ExchangeInterface]: 当前交易所服务实例 / Current exchange service instance
        """
        return self._current_service
    
    def is_running(self) -> bool:
        """
        检查服务是否正在运行
        Check if services are running
        
        Returns:
            bool: 服务是否运行 / Whether services are running
        """
        return self._is_running
    
    def get_service_status(self) -> Dict[str, Any]:
        """
        获取服务状态信息
        Get service status information
        
        Returns:
            Dict[str, Any]: 服务状态信息 / Service status information
        """
        uptime = 0
        if self._startup_time and self._is_running:
            uptime = (datetime.now() - self._startup_time).total_seconds()
        
        return {
            'is_running': self._is_running,
            'current_exchange': self._current_exchange,
            'startup_time': self._startup_time,
            'uptime_seconds': uptime,
            'statistics': self._service_stats.copy(),
            'supported_exchanges': ExchangeFactory.get_supported_exchanges(),
            'factory_status': ExchangeFactory.get_factory_status(),
            'timestamp': datetime.now()
        }
    
    @asynccontextmanager
    async def service_context(self):
        """
        服务上下文管理器
        Service context manager
        
        自动管理服务的启动和停止
        """
        try:
            # 启动服务
            start_result = await self.start_services()
            if start_result['status'] != 'success':
                raise TradingToolError(f"服务启动失败: {start_result.get('error')}")
            
            yield self
            
        finally:
            # 停止服务
            await self.stop_services()


# 全局服务管理器实例
_service_manager: Optional[ExchangeServiceManager] = None


async def get_exchange_service_manager() -> ExchangeServiceManager:
    """
    获取交易所服务管理器实例
    Get exchange service manager instance
    
    Returns:
        ExchangeServiceManager: 服务管理器实例 / Service manager instance
    """
    global _service_manager
    if _service_manager is None:
        _service_manager = ExchangeServiceManager()
    return _service_manager


async def start_exchange_services() -> Dict[str, Any]:
    """
    启动交易所服务
    Start exchange services
    
    Returns:
        Dict[str, Any]: 启动结果 / Startup result
    """
    manager = await get_exchange_service_manager()
    return await manager.start_services()


async def stop_exchange_services() -> Dict[str, Any]:
    """
    停止交易所服务
    Stop exchange services
    
    Returns:
        Dict[str, Any]: 停止结果 / Stop result
    """
    manager = await get_exchange_service_manager()
    return await manager.stop_services()


async def switch_exchange(new_exchange: str, force: bool = False) -> Dict[str, Any]:
    """
    切换交易所
    Switch exchange
    
    Args:
        new_exchange: 新交易所名称 / New exchange name
        force: 是否强制切换 / Whether to force switch
        
    Returns:
        Dict[str, Any]: 切换结果 / Switch result
    """
    manager = await get_exchange_service_manager()
    return await manager.switch_exchange(new_exchange, force)


async def get_current_exchange_service() -> Optional[ExchangeInterface]:
    """
    获取当前交易所服务实例
    Get current exchange service instance
    
    Returns:
        Optional[ExchangeInterface]: 当前交易所服务实例 / Current exchange service instance
    """
    manager = await get_exchange_service_manager()
    return manager.get_current_service()


def get_exchange_service_status() -> Dict[str, Any]:
    """
    获取交易所服务状态
    Get exchange service status
    
    Returns:
        Dict[str, Any]: 服务状态信息 / Service status information
    """
    global _service_manager
    if _service_manager is None:
        return {
            'is_running': False,
            'current_exchange': None,
            'message': '服务管理器未初始化'
        }
    
    return _service_manager.get_service_status()