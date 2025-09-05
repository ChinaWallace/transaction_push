# -*- coding: utf-8 -*-
"""
数据库连接池监控工具
Database connection pool monitoring utilities
"""

import time
import logging
from typing import Dict, Any
from contextlib import contextmanager
from sqlalchemy.exc import DisconnectionError, OperationalError
from app.core.database import db_manager, engine

logger = logging.getLogger(__name__)


class DatabaseMonitor:
    """数据库连接池监控器"""
    
    def __init__(self):
        self.db_manager = db_manager
        self.engine = engine
        self._last_check_time = 0
        self._check_interval = 60  # 60秒检查一次
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """获取连接池统计信息"""
        try:
            pool = self.engine.pool
            pool_size = pool.size()
            checked_out = pool.checkedout()
            checked_in = pool.checkedin()
            overflow = pool.overflow()
            
            # 计算总连接数
            total_connections = pool_size + overflow
            
            stats = {
                "pool_size": pool_size,
                "checked_in": checked_in,
                "checked_out": checked_out,
                "overflow": overflow,
                "total_connections": total_connections,
                "available_connections": checked_in,
                "active_connections": checked_out,
                "pool_utilization": round((checked_out / total_connections) * 100, 2) if total_connections > 0 else 0
            }
            
            # 尝试获取无效连接数（如果支持的话）
            try:
                if hasattr(pool, 'invalid'):
                    stats["invalid"] = pool.invalid()
                else:
                    stats["invalid"] = 0
            except:
                stats["invalid"] = 0
                
            return stats
        except Exception as e:
            logger.error(f"获取连接池统计信息失败: {e}")
            return {}
    
    def check_pool_health(self) -> bool:
        """检查连接池健康状态"""
        try:
            stats = self.get_pool_stats()
            
            # 检查连接池是否过载
            pool_utilization = stats.get("pool_utilization", 0)
            if pool_utilization > 90:
                logger.warning(f"连接池使用率过高: {pool_utilization}%")
                return False
            
            # 检查是否有无效连接
            invalid_count = stats.get("invalid", 0)
            if invalid_count > 0:
                logger.warning(f"发现 {invalid_count} 个无效连接")
                return False
            
            # 检查连接池是否有足够的可用连接
            available_connections = stats.get("available_connections", 0)
            total_connections = stats.get("total_connections", 0)
            if total_connections > 0 and available_connections / total_connections < 0.1:  # 可用连接少于10%
                logger.warning(f"可用连接不足: {available_connections}/{total_connections}")
            
            # 执行健康检查查询
            return self.db_manager.health_check()
            
        except Exception as e:
            logger.error(f"连接池健康检查失败: {e}")
            return False
    
    def auto_cleanup(self):
        """自动清理连接池"""
        try:
            current_time = time.time()
            if current_time - self._last_check_time < self._check_interval:
                return
            
            self._last_check_time = current_time
            
            stats = self.get_pool_stats()
            logger.info(f"连接池状态: {stats}")
            
            # 如果连接池使用率过高，尝试清理
            if stats.get("pool_utilization", 0) > 85:
                logger.info("连接池使用率过高，执行清理操作")
                self._cleanup_stale_connections()
            
        except Exception as e:
            logger.error(f"自动清理连接池失败: {e}")
    
    def _cleanup_stale_connections(self):
        """清理陈旧连接"""
        try:
            # 强制回收连接
            self.engine.pool.recreate()
            logger.info("连接池已重新创建")
        except Exception as e:
            logger.error(f"清理陈旧连接失败: {e}")
    
    @contextmanager
    def monitored_session(self):
        """带监控的数据库会话"""
        start_time = time.time()
        session = None
        
        try:
            # 自动清理检查
            self.auto_cleanup()
            
            # 获取会话
            session = self.db_manager.get_session()
            yield session
            
            # 提交事务
            session.commit()
            
        except (DisconnectionError, OperationalError) as e:
            logger.error(f"数据库连接错误: {e}")
            if session:
                session.rollback()
            
            # 尝试重新连接
            try:
                self.db_manager.reconnect()
                logger.info("数据库重新连接成功")
            except Exception as reconnect_error:
                logger.error(f"数据库重新连接失败: {reconnect_error}")
            
            raise
            
        except Exception as e:
            logger.error(f"数据库会话错误: {e}")
            if session:
                session.rollback()
            raise
            
        finally:
            if session:
                try:
                    session.close()
                except Exception as e:
                    logger.error(f"关闭会话失败: {e}")
            
            # 记录会话持续时间
            duration = time.time() - start_time
            if duration > 5:  # 超过5秒的长会话
                logger.warning(f"长时间数据库会话: {duration:.2f}秒")
    
    def force_reconnect(self):
        """强制重新连接数据库"""
        try:
            logger.info("强制重新连接数据库...")
            self.db_manager.reconnect()
            logger.info("数据库强制重新连接成功")
        except Exception as e:
            logger.error(f"强制重新连接失败: {e}")
            raise
    
    def get_connection_info(self) -> Dict[str, Any]:
        """获取连接信息"""
        try:
            stats = self.get_pool_stats()
            health = self.check_pool_health()
            
            return {
                "pool_stats": stats,
                "health_status": health,
                "database_url": self.engine.url.render_as_string(hide_password=True),
                "pool_class": str(type(self.engine.pool).__name__),
                "last_check_time": self._last_check_time,
                "check_interval": self._check_interval
            }
        except Exception as e:
            logger.error(f"获取连接信息失败: {e}")
            return {"error": str(e)}


# 创建全局监控器实例
db_monitor = DatabaseMonitor()


def get_db_monitor() -> DatabaseMonitor:
    """获取数据库监控器实例"""
    return db_monitor