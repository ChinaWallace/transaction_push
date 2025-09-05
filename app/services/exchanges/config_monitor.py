# -*- coding: utf-8 -*-
"""
配置监控服务
Configuration Monitor Service - 监控配置变化并自动调整交易所服务
"""

import asyncio
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.exchanges.service_manager import get_exchange_service_manager

logger = get_logger(__name__)


class ConfigurationMonitor:
    """
    配置监控服务
    Configuration Monitor Service
    
    监控配置文件变化并自动调整交易所服务：
    1. 监控 .env 文件变化
    2. 检测交易所配置变化
    3. 自动切换交易所服务
    4. 记录配置变更历史
    """
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.settings = get_settings()
        
        # 监控状态
        self._is_monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._last_config_hash: Optional[str] = None
        self._last_exchange_provider: Optional[str] = None
        
        # 监控配置
        self.check_interval = 30  # 检查间隔（秒）
        self.config_file_path = Path(".env")
        
        # 变更历史
        self._change_history: List[Dict[str, Any]] = []
        self._max_history_size = 100
        
        # 初始化配置状态
        self._update_config_state()
    
    def _update_config_state(self):
        """更新配置状态"""
        try:
            # 计算配置文件哈希
            if self.config_file_path.exists():
                with open(self.config_file_path, 'rb') as f:
                    content = f.read()
                    self._last_config_hash = hashlib.md5(content).hexdigest()
            
            # 记录当前交易所配置
            self._last_exchange_provider = self.settings.exchange_provider
            
        except Exception as e:
            self.logger.warning(f"⚠️ 更新配置状态失败: {e}")
    
    async def start_monitoring(self) -> Dict[str, Any]:
        """
        开始监控配置变化
        Start monitoring configuration changes
        
        Returns:
            Dict[str, Any]: 启动结果 / Start result
        """
        if self._is_monitoring:
            return {
                'status': 'already_running',
                'message': '配置监控已在运行'
            }
        
        try:
            self.logger.info("🔍 启动配置监控服务...")
            
            self._is_monitoring = True
            self._monitor_task = asyncio.create_task(
                self._monitoring_loop(),
                name="config_monitor"
            )
            
            self.logger.info("✅ 配置监控服务启动成功")
            
            return {
                'status': 'success',
                'message': '配置监控服务启动成功',
                'check_interval': self.check_interval,
                'config_file': str(self.config_file_path),
                'start_time': datetime.now()
            }
            
        except Exception as e:
            self._is_monitoring = False
            self.logger.error(f"❌ 启动配置监控服务失败: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'start_time': datetime.now()
            }
    
    async def stop_monitoring(self) -> Dict[str, Any]:
        """
        停止监控配置变化
        Stop monitoring configuration changes
        
        Returns:
            Dict[str, Any]: 停止结果 / Stop result
        """
        if not self._is_monitoring:
            return {
                'status': 'not_running',
                'message': '配置监控未在运行'
            }
        
        try:
            self.logger.info("🛑 停止配置监控服务...")
            
            self._is_monitoring = False
            
            if self._monitor_task and not self._monitor_task.done():
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass
            
            self.logger.info("✅ 配置监控服务停止成功")
            
            return {
                'status': 'success',
                'message': '配置监控服务停止成功',
                'stop_time': datetime.now()
            }
            
        except Exception as e:
            self.logger.error(f"❌ 停止配置监控服务失败: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'stop_time': datetime.now()
            }
    
    async def _monitoring_loop(self):
        """监控循环"""
        self.logger.info(f"🔄 配置监控循环启动，检查间隔: {self.check_interval}秒")
        
        while self._is_monitoring:
            try:
                # 检查配置变化
                change_result = await self._check_configuration_changes()
                
                if change_result and change_result['status'] == 'changed':
                    self.logger.info("🔄 检测到配置变化，处理中...")
                    
                    # 记录变更历史
                    self._record_change(change_result)
                
                # 等待下次检查
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                self.logger.info("📴 配置监控循环被取消")
                break
            except Exception as e:
                self.logger.error(f"❌ 配置监控循环异常: {e}")
                # 继续监控，不因单次错误而停止
                await asyncio.sleep(self.check_interval)
        
        self.logger.info("🏁 配置监控循环结束")
    
    async def _check_configuration_changes(self) -> Optional[Dict[str, Any]]:
        """
        检查配置变化
        Check configuration changes
        
        Returns:
            Optional[Dict[str, Any]]: 变化结果 / Change result
        """
        try:
            # 1. 检查配置文件哈希变化
            current_hash = None
            if self.config_file_path.exists():
                with open(self.config_file_path, 'rb') as f:
                    content = f.read()
                    current_hash = hashlib.md5(content).hexdigest()
            
            file_changed = current_hash != self._last_config_hash
            
            # 2. 重新加载设置
            if file_changed:
                self.settings = get_settings()
            
            # 3. 检查交易所配置变化
            current_exchange = self.settings.exchange_provider
            exchange_changed = current_exchange != self._last_exchange_provider
            
            if not file_changed and not exchange_changed:
                return None
            
            self.logger.info(f"🔄 配置变化检测:")
            self.logger.info(f"   📄 文件变化: {file_changed}")
            self.logger.info(f"   🏢 交易所变化: {exchange_changed} ({self._last_exchange_provider} -> {current_exchange})")
            
            # 4. 如果交易所配置发生变化，执行切换
            switch_result = None
            if exchange_changed:
                switch_result = await self._handle_exchange_change(current_exchange)
            
            # 5. 更新状态
            self._last_config_hash = current_hash
            self._last_exchange_provider = current_exchange
            
            return {
                'status': 'changed',
                'file_changed': file_changed,
                'exchange_changed': exchange_changed,
                'old_exchange': self._last_exchange_provider if exchange_changed else None,
                'new_exchange': current_exchange if exchange_changed else None,
                'switch_result': switch_result,
                'timestamp': datetime.now()
            }
            
        except Exception as e:
            self.logger.error(f"❌ 检查配置变化失败: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now()
            }
    
    async def _handle_exchange_change(self, new_exchange: str) -> Dict[str, Any]:
        """
        处理交易所变化
        Handle exchange change
        
        Args:
            new_exchange: 新交易所名称 / New exchange name
            
        Returns:
            Dict[str, Any]: 切换结果 / Switch result
        """
        try:
            self.logger.info(f"🔄 处理交易所配置变化: {new_exchange}")
            
            # 获取服务管理器
            manager = await get_exchange_service_manager()
            
            # 执行交易所切换
            switch_result = await manager.switch_exchange(new_exchange)
            
            if switch_result['status'] == 'success':
                self.logger.info(f"✅ 自动切换交易所成功: {new_exchange}")
            else:
                self.logger.error(f"❌ 自动切换交易所失败: {switch_result.get('error')}")
            
            return switch_result
            
        except Exception as e:
            self.logger.error(f"❌ 处理交易所变化失败: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now()
            }
    
    def _record_change(self, change_result: Dict[str, Any]):
        """
        记录配置变更历史
        Record configuration change history
        
        Args:
            change_result: 变更结果 / Change result
        """
        try:
            # 添加到历史记录
            self._change_history.append(change_result)
            
            # 限制历史记录大小
            if len(self._change_history) > self._max_history_size:
                self._change_history = self._change_history[-self._max_history_size:]
            
            self.logger.debug(f"📝 记录配置变更历史，当前记录数: {len(self._change_history)}")
            
        except Exception as e:
            self.logger.warning(f"⚠️ 记录配置变更历史失败: {e}")
    
    def get_monitoring_status(self) -> Dict[str, Any]:
        """
        获取监控状态
        Get monitoring status
        
        Returns:
            Dict[str, Any]: 监控状态 / Monitoring status
        """
        return {
            'is_monitoring': self._is_monitoring,
            'check_interval': self.check_interval,
            'config_file_path': str(self.config_file_path),
            'config_file_exists': self.config_file_path.exists(),
            'last_config_hash': self._last_config_hash,
            'last_exchange_provider': self._last_exchange_provider,
            'current_exchange_provider': self.settings.exchange_provider,
            'change_history_count': len(self._change_history),
            'monitor_task_running': self._monitor_task is not None and not self._monitor_task.done(),
            'timestamp': datetime.now()
        }
    
    def get_change_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取配置变更历史
        Get configuration change history
        
        Args:
            limit: 返回记录数限制 / Record limit
            
        Returns:
            List[Dict[str, Any]]: 变更历史 / Change history
        """
        return self._change_history[-limit:] if self._change_history else []
    
    async def manual_check(self) -> Dict[str, Any]:
        """
        手动检查配置变化
        Manually check configuration changes
        
        Returns:
            Dict[str, Any]: 检查结果 / Check result
        """
        try:
            self.logger.info("🔍 手动检查配置变化...")
            
            change_result = await self._check_configuration_changes()
            
            if change_result is None:
                return {
                    'status': 'no_change',
                    'message': '配置无变化',
                    'timestamp': datetime.now()
                }
            else:
                # 记录变更历史
                if change_result['status'] == 'changed':
                    self._record_change(change_result)
                
                return change_result
                
        except Exception as e:
            self.logger.error(f"❌ 手动检查配置变化失败: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now()
            }


# 全局配置监控器实例
_config_monitor: Optional[ConfigurationMonitor] = None


async def get_configuration_monitor() -> ConfigurationMonitor:
    """
    获取配置监控器实例
    Get configuration monitor instance
    
    Returns:
        ConfigurationMonitor: 配置监控器实例 / Configuration monitor instance
    """
    global _config_monitor
    if _config_monitor is None:
        _config_monitor = ConfigurationMonitor()
    return _config_monitor


async def start_config_monitoring() -> Dict[str, Any]:
    """
    启动配置监控
    Start configuration monitoring
    
    Returns:
        Dict[str, Any]: 启动结果 / Start result
    """
    monitor = await get_configuration_monitor()
    return await monitor.start_monitoring()


async def stop_config_monitoring() -> Dict[str, Any]:
    """
    停止配置监控
    Stop configuration monitoring
    
    Returns:
        Dict[str, Any]: 停止结果 / Stop result
    """
    monitor = await get_configuration_monitor()
    return await monitor.stop_monitoring()


def get_config_monitoring_status() -> Dict[str, Any]:
    """
    获取配置监控状态
    Get configuration monitoring status
    
    Returns:
        Dict[str, Any]: 监控状态 / Monitoring status
    """
    global _config_monitor
    if _config_monitor is None:
        return {
            'is_monitoring': False,
            'message': '配置监控器未初始化'
        }
    
    return _config_monitor.get_monitoring_status()