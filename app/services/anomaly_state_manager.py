# -*- coding: utf-8 -*-
"""
异常检测状态管理器
Anomaly Detection State Manager for tracking and deduplicating anomalies
"""

from typing import Dict, Set, List
from datetime import datetime, timedelta
from dataclasses import dataclass
import hashlib

from app.core.logging import get_logger
from app.services.ml_enhanced_service import AnomalyDetection

logger = get_logger(__name__)


@dataclass
class AnomalyRecord:
    """异常记录"""
    anomaly_hash: str
    symbol: str
    anomaly_type: str
    timestamp: datetime
    severity: float
    notified_at: datetime


class AnomalyStateManager:
    """异常检测状态管理器"""
    
    def __init__(self):
        self.anomaly_history: Dict[str, AnomalyRecord] = {}
        self.notification_cooldown_minutes = 60  # 同类异常通知冷却时间（分钟）
        
    def generate_anomaly_hash(self, anomaly: AnomalyDetection) -> str:
        """生成异常的唯一标识"""
        # 基于交易对、异常类型和时间窗口生成hash
        time_window = anomaly.timestamp.replace(minute=0, second=0, microsecond=0)  # 按小时分组
        hash_input = f"{anomaly.symbol}_{anomaly.anomaly_type.value}_{time_window}"
        return hashlib.md5(hash_input.encode()).hexdigest()
    
    def is_anomaly_new(self, anomaly: AnomalyDetection) -> bool:
        """检查异常是否为新异常（未通知过）"""
        anomaly_hash = self.generate_anomaly_hash(anomaly)
        
        # 检查是否已经记录过这个异常
        if anomaly_hash in self.anomaly_history:
            record = self.anomaly_history[anomaly_hash]
            
            # 检查冷却时间
            time_since_notification = datetime.now() - record.notified_at
            if time_since_notification.total_seconds() < self.notification_cooldown_minutes * 60:
                logger.debug(f"异常 {anomaly_hash} 仍在冷却期内，跳过通知")
                return False
            
            # 如果超过冷却时间，更新记录
            logger.info(f"异常 {anomaly_hash} 冷却期已过，允许重新通知")
        
        return True
    
    def mark_anomaly_notified(self, anomaly: AnomalyDetection) -> None:
        """标记异常已通知"""
        anomaly_hash = self.generate_anomaly_hash(anomaly)
        
        record = AnomalyRecord(
            anomaly_hash=anomaly_hash,
            symbol=anomaly.symbol,
            anomaly_type=anomaly.anomaly_type.value,
            timestamp=anomaly.timestamp,
            severity=anomaly.severity,
            notified_at=datetime.now()
        )
        
        self.anomaly_history[anomaly_hash] = record
        logger.debug(f"标记异常 {anomaly_hash} 已通知")
    
    def filter_new_anomalies(self, anomalies: List[AnomalyDetection]) -> List[AnomalyDetection]:
        """过滤出新的异常（未通知过的）"""
        new_anomalies = []
        
        for anomaly in anomalies:
            if self.is_anomaly_new(anomaly):
                new_anomalies.append(anomaly)
                self.mark_anomaly_notified(anomaly)
        
        if new_anomalies:
            logger.info(f"过滤出 {len(new_anomalies)} 个新异常，总异常数: {len(anomalies)}")
        
        return new_anomalies
    
    def cleanup_old_records(self, max_age_hours: int = 24) -> None:
        """清理过期的异常记录"""
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        old_hashes = [
            hash_key for hash_key, record in self.anomaly_history.items()
            if record.notified_at < cutoff_time
        ]
        
        for hash_key in old_hashes:
            del self.anomaly_history[hash_key]
        
        if old_hashes:
            logger.info(f"清理了 {len(old_hashes)} 个过期异常记录")
    
    def get_anomaly_stats(self) -> Dict[str, int]:
        """获取异常统计信息"""
        stats = {}
        
        for record in self.anomaly_history.values():
            symbol = record.symbol
            if symbol not in stats:
                stats[symbol] = 0
            stats[symbol] += 1
        
        return stats


# 全局异常状态管理器实例
anomaly_state_manager = AnomalyStateManager()