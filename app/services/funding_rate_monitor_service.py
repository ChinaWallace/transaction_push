# -*- coding: utf-8 -*-
"""
费率监控服务
Funding Rate Monitor Service - 监控资金费率变化
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.okx_service import OKXService
from app.utils.exceptions import MonitorError

logger = get_logger(__name__)
settings = get_settings()


class FundingRateMonitorService:
    """费率监控服务类"""
    
    def __init__(self):
        self.okx_service = OKXService()
        
    async def get_funding_rates(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """获取资金费率"""
        try:
            if symbols is None:
                symbols = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP']
                
            rates = {}
            for symbol in symbols:
                try:
                    rate_data = await self.okx_service.get_funding_rate(symbol)
                    rates[symbol] = rate_data
                except Exception as e:
                    logger.error(f"获取 {symbol} 费率失败: {e}")
                    
            return rates
            
        except Exception as e:
            logger.error(f"获取费率数据失败: {e}")
            raise MonitorError(f"费率监控失败: {e}")
            
    async def monitor_funding_rates(self) -> Dict[str, Any]:
        """监控费率变化"""
        try:
            rates = await self.get_funding_rates()
            
            # 分析费率变化
            analysis = {
                'timestamp': datetime.now().isoformat(),
                'rates': rates,
                'alerts': []
            }
            
            for symbol, rate_data in rates.items():
                if rate_data and 'fundingRate' in rate_data:
                    funding_rate = float(rate_data['fundingRate'])
                    
                    # 检查异常费率
                    if abs(funding_rate) > 0.001:  # 0.1%
                        analysis['alerts'].append({
                            'symbol': symbol,
                            'rate': funding_rate,
                            'type': 'high_funding_rate',
                            'message': f"{symbol} 费率异常: {funding_rate:.4%}"
                        })
                        
            return analysis
            
        except Exception as e:
            logger.error(f"费率监控失败: {e}")
            raise MonitorError(f"费率监控失败: {e}")


# 导出
__all__ = ["FundingRateMonitorService"]