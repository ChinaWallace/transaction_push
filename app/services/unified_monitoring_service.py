# -*- coding: utf-8 -*-
"""
统一监控服务
Unified Monitoring Service - 整合主要币种分析和费率监控
"""

import asyncio
from typing import Dict, Any, List
from datetime import datetime

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.enhanced_notification_service import EnhancedNotificationService
from app.services.funding_rate_monitor_service import FundingRateMonitorService
from app.services.detailed_technical_analysis_service import DetailedTechnicalAnalysisService
from app.services.unified_trading_service import UnifiedTradingService

logger = get_logger(__name__)
settings = get_settings()


class UnifiedMonitoringService:
    """统一监控服务类"""
    
    def __init__(self):
        self.enhanced_notification = EnhancedNotificationService()
        self.funding_rate_monitor = FundingRateMonitorService()
        self.detailed_analysis = DetailedTechnicalAnalysisService()
        self.unified_trading = UnifiedTradingService()
        
        # 监控配置
        self.main_symbols = settings.monitored_symbols  # 主要监控的6个币种
        self.funding_rate_symbols = settings.funding_rate_only_symbols  # 只监控费率的币种
    
    async def run_complete_monitoring_cycle(self) -> Dict[str, Any]:
        """运行完整的监控周期"""
        logger.info("🚀 开始完整监控周期")
        
        cycle_results = {
            'timestamp': datetime.now(),
            'main_analysis_results': {},
            'funding_rate_results': {},
            'notifications_sent': 0,
            'status': 'success'
        }
        
        try:
            # 1. 主要币种完整分析
            logger.info(f"📊 开始分析主要币种: {self.main_symbols}")
            main_results = await self._analyze_main_symbols()
            cycle_results['main_analysis_results'] = main_results
            
            # 2. 费率监控
            logger.info(f"💰 开始费率监控: {len(self.funding_rate_symbols)}个币种")
            funding_results = await self.funding_rate_monitor.monitor_funding_rates(
                self.funding_rate_symbols
            )
            cycle_results['funding_rate_results'] = funding_results
            
            # 3. 统计通知数量
            main_notifications = main_results.get('notifications_sent', 0)
            funding_notifications = len(funding_results.get('alerts', []))
            cycle_results['notifications_sent'] = main_notifications + funding_notifications
            
            # 4. 记录监控摘要
            await self._log_monitoring_summary(cycle_results)
            
            logger.info("✅ 完整监控周期完成")
            return cycle_results
            
        except Exception as e:
            logger.error(f"❌ 监控周期失败: {e}")
            cycle_results['status'] = 'error'
            cycle_results['error'] = str(e)
            return cycle_results
    
    async def _analyze_main_symbols(self) -> Dict[str, Any]:
        """分析主要币种"""
        results = {
            'analyzed_symbols': [],
            'trading_signals': [],
            'notifications_sent': 0,
            'analysis_summary': {
                'strong_buy': 0,
                'buy': 0,
                'hold': 0,
                'sell': 0,
                'strong_sell': 0
            }
        }
        
        try:
            # 并行分析所有主要币种
            tasks = [self._analyze_single_main_symbol(symbol) for symbol in self.main_symbols]
            analysis_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(analysis_results):
                symbol = self.main_symbols[i]
                
                if isinstance(result, Exception):
                    logger.warning(f"分析 {symbol} 失败: {result}")
                    continue
                
                if result:
                    results['analyzed_symbols'].append(symbol)
                    results['trading_signals'].append(result)
                    
                    # 统计信号类型
                    signal_type = result.get('signal', 'hold')
                    if signal_type in results['analysis_summary']:
                        results['analysis_summary'][signal_type] += 1
                    
                    # 如果发送了通知，计数
                    if result.get('notification_sent', False):
                        results['notifications_sent'] += 1
            
            return results
            
        except Exception as e:
            logger.error(f"主要币种分析失败: {e}")
            results['error'] = str(e)
            return results
    
    async def _analyze_single_main_symbol(self, symbol: str) -> Dict[str, Any]:
        """分析单个主要币种"""
        try:
            # 获取交易建议
            recommendation = await self.unified_trading.get_trading_recommendation(symbol)
            
            if not recommendation:
                return None
            
            result = {
                'symbol': symbol,
                'signal': recommendation.action.value,
                'confidence': recommendation.confidence,
                'current_price': recommendation.current_price,
                'reasoning': recommendation.reasoning,
                'timestamp': datetime.now(),
                'notification_sent': False
            }
            
            # 发送通知（如果符合条件）
            notification_sent = await self.enhanced_notification.send_trading_signal(recommendation)
            result['notification_sent'] = notification_sent
            
            if notification_sent:
                trading_logger.info(f"📢 已发送 {symbol} 交易信号通知")
            
            return result
            
        except Exception as e:
            logger.error(f"分析 {symbol} 失败: {e}")
            return None
    
    async def _log_monitoring_summary(self, cycle_results: Dict[str, Any]) -> None:
        """记录监控摘要"""
        try:
            main_results = cycle_results.get('main_analysis_results', {})
            funding_results = cycle_results.get('funding_rate_results', {})
            
            # 主要币种分析摘要
            analysis_summary = main_results.get('analysis_summary', {})
            analyzed_count = len(main_results.get('analyzed_symbols', []))
            
            trading_logger.info(f"📊 主要币种分析完成:")
            trading_logger.info(f"   分析币种: {analyzed_count}/{len(self.main_symbols)}")
            
            for signal_type, count in analysis_summary.items():
                if count > 0:
                    signal_text = {
                        'strong_buy': '强烈买入',
                        'buy': '买入',
                        'hold': '持有',
                        'sell': '卖出',
                        'strong_sell': '强烈卖出'
                    }.get(signal_type, signal_type)
                    trading_logger.info(f"   {signal_text}: {count}个")
            
            # 费率监控摘要
            funding_summary = funding_results.get('summary', {})
            funding_alerts = len(funding_results.get('alerts', []))
            
            trading_logger.info(f"💰 费率监控完成:")
            trading_logger.info(f"   监控币种: {funding_results.get('monitored_symbols', 0)}")
            trading_logger.info(f"   费率警报: {funding_alerts}个")
            
            if funding_summary:
                if funding_summary.get('extremely_negative_count', 0) > 0:
                    trading_logger.info(f"   极高负费率: {funding_summary['extremely_negative_count']}个")
                if funding_summary.get('high_negative_count', 0) > 0:
                    trading_logger.info(f"   高负费率: {funding_summary['high_negative_count']}个")
            
            # 总体摘要
            total_notifications = cycle_results.get('notifications_sent', 0)
            trading_logger.info(f"📢 本轮监控发送通知: {total_notifications}条")
            
        except Exception as e:
            logger.error(f"记录监控摘要失败: {e}")
    
    async def get_monitoring_status(self) -> Dict[str, Any]:
        """获取监控状态"""
        try:
            # 获取增强通知服务状态
            notification_stats = await self.enhanced_notification.get_notification_stats()
            
            # 获取当前费率数据
            current_rates = await self.funding_rate_monitor.get_current_funding_rates(
                self.funding_rate_symbols[:5]  # 只获取前5个作为示例
            )
            
            status = {
                'timestamp': datetime.now(),
                'main_symbols': {
                    'count': len(self.main_symbols),
                    'symbols': self.main_symbols
                },
                'funding_rate_symbols': {
                    'count': len(self.funding_rate_symbols),
                    'sample_symbols': self.funding_rate_symbols[:5]
                },
                'notification_stats': notification_stats,
                'sample_funding_rates': current_rates,
                'service_status': {
                    'enhanced_notification': 'active',
                    'funding_rate_monitor': 'active',
                    'detailed_analysis': 'active',
                    'unified_trading': 'active'
                }
            }
            
            return status
            
        except Exception as e:
            logger.error(f"获取监控状态失败: {e}")
            return {
                'timestamp': datetime.now(),
                'error': str(e),
                'service_status': 'error'
            }
    
    async def force_send_pending_notifications(self) -> Dict[str, Any]:
        """强制发送待推送的通知"""
        try:
            # 发送待推送的普通信号
            result = await self.enhanced_notification.force_send_pending_signals()
            
            return {
                'timestamp': datetime.now(),
                'pending_signals_sent': result,
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"强制发送通知失败: {e}")
            return {
                'timestamp': datetime.now(),
                'status': 'error',
                'error': str(e)
            }
    
    async def cleanup_services(self) -> None:
        """清理服务状态"""
        try:
            # 清理通知历史
            await self.enhanced_notification.cleanup_old_history()
            
            # 清理费率警报历史
            self.funding_rate_monitor.cleanup_alert_history()
            
            logger.info("✅ 服务清理完成")
            
        except Exception as e:
            logger.error(f"服务清理失败: {e}")


# 全局监控服务实例
unified_monitoring_service = UnifiedMonitoringService()