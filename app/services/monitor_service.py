# -*- coding: utf-8 -*-
"""
监控服务
Monitor service for funding rate, open interest and volume monitoring
"""

import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.config import get_settings
from app.core.logging import get_logger, monitor_logger
from app.services.binance_service import BinanceService
from app.services.notification_service import NotificationService
from app.utils.indicators import VolumeIndicator
from app.utils.exceptions import MonitorError
from app.models.market_data import FundingRate, OpenInterest, VolumeData

logger = get_logger(__name__)
settings = get_settings()


class MonitorService:
    """监控服务类"""
    
    def __init__(self):
        self.binance_service = BinanceService()
        self.notification_service = NotificationService()
        self.monitor_config = settings.monitor_config
        
        # 历史数据缓存（用于比较变化）
        self._previous_open_interest = {}
        self._previous_funding_rates = {}
    
    async def monitor_funding_rate(self, 
                                 symbols: Optional[List[str]] = None,
                                 notify: bool = True) -> Dict[str, Any]:
        """
        监控资金费率
        
        Args:
            symbols: 要监控的交易对列表，如果为None则监控所有活跃交易对
            notify: 是否发送通知
            
        Returns:
            监控结果
        """
        try:
            monitor_logger.info("Starting funding rate monitoring")
            
            # 获取所有资金费率数据
            funding_rates = await self.binance_service.get_funding_rate()
            
            if not funding_rates:
                raise MonitorError("No funding rate data available")
            
            # 如果指定了特定交易对，则过滤
            if symbols:
                funding_rates = [fr for fr in funding_rates if fr['symbol'] in symbols]
            
            # 分析负费率和高费率
            negative_rates = []
            high_positive_rates = []
            
            for rate_data in funding_rates:
                rate = float(rate_data['funding_rate'])
                
                # 负费率（做空支付给做多）
                if rate < 0:
                    negative_rates.append({
                        'symbol': rate_data['symbol'],
                        'funding_rate': rate,
                        'funding_time': rate_data['funding_time'],
                        'mark_price': rate_data.get('mark_price')
                    })
                
                # 高正费率（做多支付给做空，费率 > 0.1%）
                elif rate > 0.001:  # 0.1%
                    high_positive_rates.append({
                        'symbol': rate_data['symbol'],
                        'funding_rate': rate,
                        'funding_time': rate_data['funding_time'],
                        'mark_price': rate_data.get('mark_price')
                    })
            
            # 排序：负费率按从小到大，正费率按从大到小
            negative_rates.sort(key=lambda x: x['funding_rate'])
            high_positive_rates.sort(key=lambda x: x['funding_rate'], reverse=True)
            
            result = {
                'timestamp': datetime.now(),
                'total_symbols': len(funding_rates),
                'negative_rates': negative_rates,
                'high_positive_rates': high_positive_rates,
                'negative_count': len(negative_rates),
                'high_positive_count': len(high_positive_rates)
            }
            
            # 发送通知
            if notify and (negative_rates or high_positive_rates):
                if negative_rates:
                    await self.notification_service.send_funding_rate_alert(
                        negative_rates, "negative_rate"
                    )
                
                if high_positive_rates:
                    await self.notification_service.send_funding_rate_alert(
                        high_positive_rates, "high_rate"
                    )
            
            monitor_logger.info(
                f"Funding rate monitoring completed: {len(negative_rates)} negative, "
                f"{len(high_positive_rates)} high positive rates"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Funding rate monitoring failed: {e}")
            raise MonitorError(f"Funding rate monitoring failed: {e}")
    
    async def monitor_open_interest(self, 
                                  symbols: Optional[List[str]] = None,
                                  notify: bool = True) -> Dict[str, Any]:
        """
        监控持仓量变化
        
        Args:
            symbols: 要监控的交易对列表，如果为None则监控所有活跃交易对
            notify: 是否发送通知
            
        Returns:
            监控结果
        """
        try:
            monitor_logger.info("Starting open interest monitoring")
            
            if symbols is None:
                symbols = await self.binance_service.get_active_symbols()
            
            threshold = self.monitor_config["open_interest_threshold"]
            significant_changes = []
            
            # 并发获取持仓量数据
            tasks = []
            for symbol in symbols:
                task = self.binance_service.get_open_interest_statistics(symbol, period="5m", limit=2)
                tasks.append((symbol, task))
            
            for symbol, task in tasks:
                try:
                    oi_data = await task
                    
                    if len(oi_data) >= 2:
                        current_oi = float(oi_data[0]['open_interest'])
                        previous_oi = float(oi_data[1]['open_interest'])
                        
                        if previous_oi > 0:
                            change_ratio = current_oi / previous_oi
                            
                            # 如果变化超过阈值
                            if change_ratio >= threshold:
                                significant_changes.append({
                                    'symbol': symbol,
                                    'current_oi': current_oi,
                                    'previous_oi': previous_oi,
                                    'change_ratio': change_ratio,
                                    'change_percent': (change_ratio - 1) * 100,
                                    'timestamp': oi_data[0]['timestamp'],
                                    'oi_value': oi_data[0].get('open_interest_value', 0)
                                })
                
                except Exception as e:
                    logger.warning(f"Failed to get open interest for {symbol}: {e}")
                    continue
            
            # 按变化率排序
            significant_changes.sort(key=lambda x: x['change_ratio'], reverse=True)
            
            result = {
                'timestamp': datetime.now(),
                'monitored_symbols': len(symbols),
                'threshold': threshold,
                'significant_changes': significant_changes,
                'alert_count': len(significant_changes)
            }
            
            # 发送通知
            if notify and significant_changes:
                await self.notification_service.send_open_interest_alert(significant_changes)
            
            monitor_logger.info(
                f"Open interest monitoring completed: {len(significant_changes)} symbols with significant changes"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Open interest monitoring failed: {e}")
            raise MonitorError(f"Open interest monitoring failed: {e}")
    
    async def monitor_volume_anomaly(self, 
                                   symbols: Optional[List[str]] = None,
                                   notify: bool = True) -> Dict[str, Any]:
        """
        监控交易量异常（庄神指标）
        
        Args:
            symbols: 要监控的交易对列表，如果为None则监控所有活跃交易对
            notify: 是否发送通知
            
        Returns:
            监控结果
        """
        try:
            monitor_logger.info("Starting volume anomaly monitoring")
            
            if symbols is None:
                symbols = await self.binance_service.get_active_symbols()
            
            volume_multiplier = self.monitor_config["volume_multiplier"]
            anomaly_symbols = []
            
            # 并发获取K线数据
            tasks = []
            for symbol in symbols:
                task = self.binance_service.get_kline_data(symbol, '1h', limit=4)
                tasks.append((symbol, task))
            
            for symbol, task in tasks:
                try:
                    klines = await task
                    
                    if len(klines) >= 3:
                        # 使用庄神指标计算成交量异常
                        enriched_klines = VolumeIndicator.calculate_volume_ratio(klines, periods=3)
                        
                        # 检查最新的K线
                        latest_kline = enriched_klines[-1]
                        volume_ratio = latest_kline.get('volume_ratio')
                        anomaly_type = latest_kline.get('is_volume_anomaly', 'none')
                        price_up = latest_kline.get('price_up') == 'yes'
                        
                        if anomaly_type in ['strong', 'normal'] and volume_ratio and volume_ratio >= volume_multiplier:
                            anomaly_symbols.append({
                                'symbol': symbol,
                                'volume_ratio': volume_ratio,
                                'anomaly_type': anomaly_type,
                                'price_up': price_up,
                                'current_volume': float(latest_kline['volume']),
                                'previous_volume': float(klines[-2]['volume']),
                                'close_price': float(latest_kline['close_price']),
                                'timestamp': latest_kline['close_time']
                            })
                
                except Exception as e:
                    logger.warning(f"Failed to analyze volume for {symbol}: {e}")
                    continue
            
            # 分类和排序
            strong_symbols = [s for s in anomaly_symbols if s['anomaly_type'] == 'strong']
            normal_symbols = [s for s in anomaly_symbols if s['anomaly_type'] == 'normal']
            
            strong_symbols.sort(key=lambda x: x['volume_ratio'], reverse=True)
            normal_symbols.sort(key=lambda x: x['volume_ratio'], reverse=True)
            
            result = {
                'timestamp': datetime.now(),
                'monitored_symbols': len(symbols),
                'volume_multiplier': volume_multiplier,
                'strong_symbols': strong_symbols,
                'normal_symbols': normal_symbols,
                'total_anomalies': len(anomaly_symbols)
            }
            
            # 发送通知
            if notify and anomaly_symbols:
                await self.notification_service.send_volume_alert(anomaly_symbols)
            
            monitor_logger.info(
                f"Volume anomaly monitoring completed: {len(strong_symbols)} strong, "
                f"{len(normal_symbols)} normal anomalies"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Volume anomaly monitoring failed: {e}")
            raise MonitorError(f"Volume anomaly monitoring failed: {e}")
    
    async def run_comprehensive_monitoring(self, 
                                         symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        运行综合监控（所有监控功能）
        
        Args:
            symbols: 要监控的交易对列表
            
        Returns:
            综合监控结果
        """
        try:
            monitor_logger.info("Starting comprehensive monitoring")
            
            # 并发执行所有监控
            tasks = [
                self.monitor_funding_rate(symbols, notify=True),
                self.monitor_open_interest(symbols, notify=True),
                self.monitor_volume_anomaly(symbols, notify=True)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            funding_result = results[0] if not isinstance(results[0], Exception) else {"error": str(results[0])}
            oi_result = results[1] if not isinstance(results[1], Exception) else {"error": str(results[1])}
            volume_result = results[2] if not isinstance(results[2], Exception) else {"error": str(results[2])}
            
            comprehensive_result = {
                'timestamp': datetime.now(),
                'funding_rate_monitoring': funding_result,
                'open_interest_monitoring': oi_result,
                'volume_anomaly_monitoring': volume_result,
                'status': 'completed'
            }
            
            # 统计总体结果
            total_alerts = 0
            if not isinstance(funding_result, dict) or "error" not in funding_result:
                total_alerts += funding_result.get('negative_count', 0) + funding_result.get('high_positive_count', 0)
            if not isinstance(oi_result, dict) or "error" not in oi_result:
                total_alerts += oi_result.get('alert_count', 0)
            if not isinstance(volume_result, dict) or "error" not in volume_result:
                total_alerts += volume_result.get('total_anomalies', 0)
            
            comprehensive_result['total_alerts'] = total_alerts
            
            monitor_logger.info(f"Comprehensive monitoring completed with {total_alerts} total alerts")
            
            return comprehensive_result
            
        except Exception as e:
            logger.error(f"Comprehensive monitoring failed: {e}")
            raise MonitorError(f"Comprehensive monitoring failed: {e}")
    
    async def get_monitor_status(self) -> Dict[str, Any]:
        """获取监控服务状态"""
        try:
            # 检查各个服务的健康状态
            binance_healthy = await self.binance_service.health_check()
            
            enabled_channels = []
            for channel, config in settings.notification_config.items():
                if config.get("enabled", False):
                    enabled_channels.append(channel)
            
            return {
                'timestamp': datetime.now(),
                'status': 'healthy' if binance_healthy else 'degraded',
                'binance_api': 'healthy' if binance_healthy else 'unhealthy',
                'notification_channels': enabled_channels,
                'monitor_config': self.monitor_config,
                'services': {
                    'funding_rate_monitoring': 'enabled',
                    'open_interest_monitoring': 'enabled',
                    'volume_anomaly_monitoring': 'enabled'
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get monitor status: {e}")
            return {
                'timestamp': datetime.now(),
                'status': 'error',
                'error': str(e)
            }
