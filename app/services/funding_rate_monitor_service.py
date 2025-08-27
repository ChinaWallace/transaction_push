# -*- coding: utf-8 -*-
"""
费率监控服务
Funding Rate Monitor Service - 专门监控费率是否高负
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
import asyncio

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.okx_service import OKXService
from app.services.notification_service import NotificationService

logger = get_logger(__name__)
settings = get_settings()


@dataclass
class FundingRateAlert:
    """费率警报"""
    symbol: str
    current_rate: float
    predicted_rate: float
    alert_type: str  # 'high_negative', 'extremely_negative'
    severity: str   # 'medium', 'high', 'critical'
    description: str
    timestamp: datetime


class FundingRateMonitorService:
    """费率监控服务类"""
    
    def __init__(self):
        self.okx_service = OKXService()
        self.notification_service = NotificationService()
        
        # 费率阈值配置 - 极敏感设置，捕捉任何负费率机会
        self.rate_thresholds = {
            'high_negative': -0.00001,   # 任何负费率都触发警报（极敏感）
            'extremely_negative': -0.001, # -0.1% 极高负费率
            'positive_high': 0.005,      # +0.5% 高正费率
        }
        
        # 通知历史（避免重复推送）
        self.alert_history = {}
        self.alert_cooldown = timedelta(hours=4)  # 4小时冷却期
    
    async def monitor_funding_rates(self, symbols: List[str] = None) -> Dict[str, Any]:
        """
        监控费率 - 优化版本，自动扫描所有永续合约
        
        Args:
            symbols: 要监控的交易对列表，如果为None则扫描所有永续合约
            
        Returns:
            监控结果
        """
        if symbols is None:
            # 获取所有永续合约交易对
            logger.info("获取所有永续合约交易对...")
            instruments = await self.okx_service.get_all_instruments('SWAP')
            
            if not instruments:
                logger.error("获取交易对列表失败")
                return {
                    'timestamp': datetime.now(),
                    'monitored_symbols': 0,
                    'alerts': [],
                    'summary': {'error': '获取交易对列表失败'},
                    'error': '获取交易对列表失败'
                }
            
            # 过滤活跃的交易对
            symbols = [
                inst['instId'] for inst in instruments 
                if inst.get('state') == 'live'
            ]
            logger.info(f"找到 {len(symbols)} 个活跃的永续合约")
        
        logger.info(f"开始监控 {len(symbols)} 个币种的费率")
        
        results = {
            'timestamp': datetime.now(),
            'monitored_symbols': len(symbols),
            'alerts': [],
            'summary': {
                'high_negative_count': 0,
                'extremely_negative_count': 0,
                'positive_high_count': 0,
                'normal_count': 0
            }
        }
        
        try:
            # 🚀 优化：使用批量获取费率数据（减少API调用次数）
            logger.info(f"批量获取 {len(symbols)} 个币种的费率数据...")
            all_funding_rates = await self.okx_service.get_batch_funding_rates(symbols)
            
            if not all_funding_rates:
                logger.error("获取费率数据失败")
                results['error'] = "获取费率数据失败"
                return results
            
            # 转换为字典便于查找
            funding_rate_dict = {
                rate_data['symbol']: rate_data 
                for rate_data in all_funding_rates
            }
            
            logger.info(f"成功获取 {len(funding_rate_dict)}/{len(symbols)} 个币种的费率数据")
            
            # 检查目标币种的费率
            alerts = []
            for symbol in symbols:
                if symbol in funding_rate_dict:
                    rate_data = funding_rate_dict[symbol]
                    alert = self._check_funding_rate_alert(symbol, rate_data)
                    
                    if alert:
                        alerts.append(alert)
                        
                        # 统计
                        if alert.alert_type == 'extremely_negative':
                            results['summary']['extremely_negative_count'] += 1
                        elif alert.alert_type == 'high_negative':
                            results['summary']['high_negative_count'] += 1
                        elif alert.alert_type == 'positive_high':
                            results['summary']['positive_high_count'] += 1
                    else:
                        results['summary']['normal_count'] += 1
                else:
                    logger.warning(f"未找到 {symbol} 的费率数据")
                    results['summary']['normal_count'] += 1
            
            results['alerts'] = alerts
            
            # 发送警报通知
            if alerts:
                await self._send_funding_rate_alerts(alerts)
            
            logger.info(f"费率监控完成: {len(alerts)} 个警报，耗时大幅减少")
            return results
            
        except Exception as e:
            logger.error(f"费率监控失败: {e}")
            results['error'] = str(e)
            return results
    
    def _check_funding_rate_alert(self, symbol: str, rate_data: Dict[str, Any]) -> Optional[FundingRateAlert]:
        """
        检查费率是否需要警报 - 优化版本，直接使用已获取的数据
        
        Args:
            symbol: 交易对符号
            rate_data: 费率数据字典
            
        Returns:
            费率警报对象或None
        """
        try:
            current_rate = rate_data.get('funding_rate', 0)
            predicted_rate = rate_data.get('predicted_rate', current_rate)  # 如果没有预测费率，使用当前费率
            
            # 检查是否需要警报
            alert_type = None
            severity = None
            description = None
            
            if current_rate <= self.rate_thresholds['extremely_negative']:
                alert_type = 'extremely_negative'
                severity = 'critical'
                description = f"极高负费率 {current_rate:.4%}，做多成本极低"
            elif current_rate <= self.rate_thresholds['high_negative']:
                alert_type = 'high_negative'
                severity = 'high'
                description = f"高负费率 {current_rate:.4%}，做多有费率收益"
            elif current_rate >= self.rate_thresholds['positive_high']:
                alert_type = 'positive_high'
                severity = 'medium'
                description = f"高正费率 {current_rate:.4%}，做空有费率收益"
            
            if alert_type:
                # 检查冷却期
                if self._should_send_alert(symbol, alert_type):
                    alert = FundingRateAlert(
                        symbol=symbol,
                        current_rate=current_rate,
                        predicted_rate=predicted_rate,
                        alert_type=alert_type,
                        severity=severity,
                        description=description,
                        timestamp=datetime.now()
                    )
                    
                    # 记录警报历史
                    self.alert_history[f"{symbol}_{alert_type}"] = datetime.now()
                    
                    return alert
            
            return None
            
        except Exception as e:
            logger.error(f"检查 {symbol} 费率失败: {e}")
            return None
    
    async def _check_symbol_funding_rate(self, symbol: str) -> Optional[FundingRateAlert]:
        """检查单个币种的费率 - 保留用于单独调用"""
        try:
            # 获取费率数据
            funding_rate_data = await self.okx_service.get_funding_rate(symbol)
            
            if not funding_rate_data:
                return None
            
            # 使用新的检查方法
            return self._check_funding_rate_alert(symbol, funding_rate_data)
            
        except Exception as e:
            logger.error(f"检查 {symbol} 费率失败: {e}")
            return None
    
    def _should_send_alert(self, symbol: str, alert_type: str) -> bool:
        """检查是否应该发送警报"""
        key = f"{symbol}_{alert_type}"
        
        if key not in self.alert_history:
            return True
        
        last_alert_time = self.alert_history[key]
        return datetime.now() - last_alert_time > self.alert_cooldown
    
    async def _send_funding_rate_alerts(self, alerts: List[FundingRateAlert]) -> None:
        """发送费率警报通知"""
        try:
            # 按严重程度分组
            critical_alerts = [a for a in alerts if a.severity == 'critical']
            high_alerts = [a for a in alerts if a.severity == 'high']
            medium_alerts = [a for a in alerts if a.severity == 'medium']
            
            # 发送极高负费率警报（单独发送）
            for alert in critical_alerts:
                await self._send_single_alert(alert)
            
            # 批量发送其他警报
            if high_alerts or medium_alerts:
                await self._send_batch_alerts(high_alerts + medium_alerts)
                
        except Exception as e:
            logger.error(f"发送费率警报失败: {e}")
    
    async def _send_single_alert(self, alert: FundingRateAlert) -> None:
        """发送单个费率警报"""
        try:
            title = f"💰 极高负费率警报 - {alert.symbol}"
            
            message_parts = [
                f"🎯 交易对: {alert.symbol}",
                f"💸 当前费率: {alert.current_rate:.4%}",
                f"🔮 预测费率: {alert.predicted_rate:.4%}",
                "",
                f"💡 {alert.description}",
                "",
                "🚀 机会说明:",
                "  • 做多可获得费率收益",
                "  • 费率每8小时结算一次",
                "  • 极负费率通常不会持续太久",
                "",
                f"⏰ 检测时间: {alert.timestamp.strftime('%H:%M:%S')}",
                "",
                "⚠️ 费率机会稍纵即逝，请及时关注！"
            ]
            
            message = "\n".join(message_parts)
            
            await self.notification_service.send_notification(
                message=f"{title}\n\n{message}",
                priority="high"
            )
            
            logger.info(f"已发送极高负费率警报: {alert.symbol}")
            
        except Exception as e:
            logger.error(f"发送单个费率警报失败: {e}")
    
    async def _send_batch_alerts(self, alerts: List[FundingRateAlert]) -> None:
        """批量发送费率警报"""
        try:
            title = f"💰 费率监控警报 ({len(alerts)}个)"
            
            message_parts = [
                f"⏰ 监控时间: {datetime.now().strftime('%H:%M')}",
                f"📊 发现 {len(alerts)} 个费率机会:",
                ""
            ]
            
            # 按费率排序（负费率在前）
            sorted_alerts = sorted(alerts, key=lambda x: x.current_rate)
            
            for i, alert in enumerate(sorted_alerts, 1):
                rate_emoji = "💸" if alert.current_rate < 0 else "💰"
                opportunity = "做多收费率" if alert.current_rate < 0 else "做空收费率"
                
                message_parts.append(
                    f"{i}. {rate_emoji} {alert.symbol}: {alert.current_rate:.4%}"
                )
                message_parts.append(
                    f"   机会: {opportunity} | {alert.description.split('，')[1] if '，' in alert.description else alert.description}"
                )
                message_parts.append("")
            
            message_parts.extend([
                "💡 费率说明:",
                "  • 负费率: 做多收取费率，做空支付费率",
                "  • 正费率: 做空收取费率，做多支付费率",
                "  • 费率每8小时结算一次",
                "",
                "⚠️ 费率会动态变化，请及时关注市场！"
            ])
            
            message = "\n".join(message_parts)
            
            await self.notification_service.send_notification(
                message=f"{title}\n\n{message}",
                priority="medium"
            )
            
            logger.info(f"已发送批量费率警报: {len(alerts)}个")
            
        except Exception as e:
            logger.error(f"发送批量费率警报失败: {e}")
    
    async def get_current_funding_rates(self, symbols: List[str] = None) -> Dict[str, Dict[str, Any]]:
        """获取当前费率数据 - 优化版本，使用批量API"""
        if symbols is None:
            symbols = settings.funding_rate_only_symbols
        
        results = {}
        
        try:
            # 🚀 优化：使用批量获取费率数据
            all_funding_rates = await self.okx_service.get_batch_funding_rates(symbols)
            
            if not all_funding_rates:
                logger.error("获取费率数据失败")
                return {}
            
            # 转换为字典便于查找
            funding_rate_dict = {
                rate_data['symbol']: rate_data 
                for rate_data in all_funding_rates
            }
            
            # 处理目标币种
            for symbol in symbols:
                if symbol in funding_rate_dict:
                    rate_data = funding_rate_dict[symbol]
                    processed_data = self._process_funding_rate_data(symbol, rate_data)
                    if processed_data:
                        results[symbol] = processed_data
                else:
                    logger.warning(f"未找到 {symbol} 的费率数据")
            
            logger.info(f"批量获取费率数据完成: {len(results)}/{len(symbols)} 个币种")
            return results
            
        except Exception as e:
            logger.error(f"获取费率数据失败: {e}")
            return {}
    
    def _process_funding_rate_data(self, symbol: str, rate_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        处理费率数据 - 优化版本，直接处理已获取的数据
        
        Args:
            symbol: 交易对符号
            rate_data: 原始费率数据
            
        Returns:
            处理后的费率数据
        """
        try:
            current_rate = rate_data.get('funding_rate', 0)
            predicted_rate = rate_data.get('predicted_rate', current_rate)
            
            # 分类费率
            if current_rate <= -0.05:
                category = "极高负费率"
                opportunity = "做多极佳"
            elif current_rate <= -0.01:
                category = "高负费率"
                opportunity = "做多有利"
            elif current_rate >= 0.05:
                category = "高正费率"
                opportunity = "做空有利"
            elif current_rate >= 0.01:
                category = "正费率"
                opportunity = "做空收益"
            else:
                category = "正常费率"
                opportunity = "无明显优势"
            
            return {
                'current_rate': current_rate,
                'predicted_rate': predicted_rate,
                'category': category,
                'opportunity': opportunity,
                'annual_rate': current_rate * 365 * 3,  # 年化费率（每天3次）
                'next_funding_time': rate_data.get('next_funding_time', ''),
                'timestamp': datetime.now()
            }
            
        except Exception as e:
            logger.error(f"处理 {symbol} 费率数据失败: {e}")
            return None
    
    async def _get_symbol_funding_rate(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取单个币种的费率数据 - 保留用于单独调用"""
        try:
            funding_rate_data = await self.okx_service.get_funding_rate(symbol)
            
            if not funding_rate_data:
                return None
            
            # 使用新的处理方法
            return self._process_funding_rate_data(symbol, funding_rate_data)
            
        except Exception as e:
            logger.error(f"获取 {symbol} 费率数据失败: {e}")
            return None
    
    def cleanup_alert_history(self, hours: int = 24) -> None:
        """清理警报历史"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        old_keys = [
            key for key, time in self.alert_history.items()
            if time < cutoff_time
        ]
        
        for key in old_keys:
            del self.alert_history[key]
        
        logger.info(f"清理了 {len(old_keys)} 个旧费率警报记录")