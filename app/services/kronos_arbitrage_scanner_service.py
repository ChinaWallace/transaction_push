# -*- coding: utf-8 -*-
"""
Kronos套利机会扫描服务
使用Kronos AI识别跨交易所、跨时间周期的套利机会
"""

import asyncio
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import pandas as pd
import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger, trading_logger
from app.services.kronos_integrated_decision_service import get_kronos_integrated_service
from app.services.okx_service import OKXService
from app.services.notification_service import NotificationService
from app.utils.exceptions import TradingToolError


class ArbitrageType(Enum):
    """套利类型"""
    FUNDING_RATE = "资金费率套利"
    PRICE_SPREAD = "价差套利" 
    TEMPORAL = "时间套利"
    CROSS_EXCHANGE = "跨交易所套利"


@dataclass
class KronosArbitrageOpportunity:
    """Kronos套利机会"""
    symbol: str
    arbitrage_type: ArbitrageType
    expected_profit: float  # 预期利润率
    kronos_confidence: float  # Kronos置信度
    
    # 套利参数
    entry_price: float
    exit_price: Optional[float] = None
    holding_period: Optional[int] = None  # 持有时间(小时)
    
    # 风险评估
    risk_score: float = 0.0
    max_drawdown: float = 0.0
    
    # 执行建议
    position_size: float = 0.0
    execution_priority: str = "medium"


class KronosArbitrageScanner:
    """Kronos套利机会扫描器"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.last_scan_time = None
        self.scan_interval = timedelta(minutes=15)  # 15分钟扫描一次
    
    async def scan_arbitrage_opportunities(self) -> Dict[str, Any]:
        """扫描套利机会"""
        try:
            # 检查扫描间隔
            if (self.last_scan_time and 
                datetime.now() - self.last_scan_time < self.scan_interval):
                return {"status": "skipped", "reason": "未到扫描间隔"}
            
            self.logger.info("🔍 开始Kronos套利机会扫描...")
            
            opportunities = []
            
            # 1. 资金费率套利扫描
            funding_opportunities = await self._scan_funding_arbitrage()
            opportunities.extend(funding_opportunities)
            
            # 2. 价差套利扫描  
            spread_opportunities = await self._scan_price_spread_arbitrage()
            opportunities.extend(spread_opportunities)
            
            # 3. 时间套利扫描
            temporal_opportunities = await self._scan_temporal_arbitrage()
            opportunities.extend(temporal_opportunities)
            
            # 按预期收益排序
            opportunities.sort(key=lambda x: x.expected_profit, reverse=True)
            
            # 发送通知
            if opportunities:
                await self._send_arbitrage_notifications(opportunities[:5])
            
            self.last_scan_time = datetime.now()
            
            return {
                "status": "success",
                "opportunities_found": len(opportunities),
                "top_opportunities": opportunities[:10],
                "scan_time": self.last_scan_time.isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"套利扫描失败: {e}")
            return {"status": "error", "error": str(e)} 
   
    async def _scan_funding_arbitrage(self) -> List[KronosArbitrageOpportunity]:
        """扫描资金费率套利机会"""
        opportunities = []
        
        try:
            async with OKXService() as okx:
                # 获取所有永续合约的资金费率
                funding_rates = await okx.get_funding_rates()
                
                # 使用Kronos分析资金费率趋势
                kronos_service = await get_kronos_integrated_service()
                
                for rate_data in funding_rates:
                    symbol = rate_data['symbol']
                    funding_rate = float(rate_data['funding_rate'])
                    
                    # 只关注高费率机会(>0.1%)
                    if abs(funding_rate) > 0.001:
                        # 获取Kronos对该币种的预测
                        kronos_decision = await kronos_service.get_kronos_enhanced_decision(
                            symbol, force_update=False
                        )
                        
                        if kronos_decision and kronos_decision.kronos_confidence > 0.4:
                            # 计算套利机会
                            daily_rate = funding_rate * 3  # 每日3次费率
                            annual_rate = daily_rate * 365
                            
                            opportunity = KronosArbitrageOpportunity(
                                symbol=symbol,
                                arbitrage_type=ArbitrageType.FUNDING_RATE,
                                expected_profit=annual_rate,
                                kronos_confidence=kronos_decision.kronos_confidence,
                                entry_price=kronos_decision.current_price,
                                holding_period=8,  # 8小时持有
                                risk_score=1 - kronos_decision.kronos_confidence,
                                position_size=min(10000, 50000 * abs(funding_rate)),
                                execution_priority="high" if abs(funding_rate) > 0.002 else "medium"
                            )
                            
                            opportunities.append(opportunity)
                            
        except Exception as e:
            self.logger.error(f"资金费率套利扫描失败: {e}")
        
        return opportunities
    
    async def _scan_price_spread_arbitrage(self) -> List[KronosArbitrageOpportunity]:
        """扫描价差套利机会"""
        opportunities = []
        
        try:
            # 获取现货和合约价格差异
            async with OKXService() as okx:
                symbols = self.settings.monitored_symbols
                
                for symbol in symbols:
                    # 获取现货和合约价格
                    spot_symbol = symbol.replace('-SWAP', '')
                    
                    spot_ticker = await okx.get_ticker(spot_symbol)
                    swap_ticker = await okx.get_ticker(symbol)
                    
                    if spot_ticker and swap_ticker:
                        spot_price = float(spot_ticker['last'])
                        swap_price = float(swap_ticker['last'])
                        
                        # 计算价差
                        spread = (swap_price - spot_price) / spot_price
                        
                        # 价差超过0.5%时考虑套利
                        if abs(spread) > 0.005:
                            # 使用Kronos评估套利可行性
                            kronos_service = await get_kronos_integrated_service()
                            kronos_decision = await kronos_service.get_kronos_enhanced_decision(
                                symbol, force_update=False
                            )
                            
                            if kronos_decision and kronos_decision.kronos_confidence > 0.35:
                                opportunity = KronosArbitrageOpportunity(
                                    symbol=symbol,
                                    arbitrage_type=ArbitrageType.PRICE_SPREAD,
                                    expected_profit=abs(spread) * 0.8,  # 80%的价差收益
                                    kronos_confidence=kronos_decision.kronos_confidence,
                                    entry_price=min(spot_price, swap_price),
                                    exit_price=max(spot_price, swap_price),
                                    holding_period=1,  # 1小时内完成
                                    risk_score=0.3,  # 相对低风险
                                    position_size=20000,
                                    execution_priority="high" if abs(spread) > 0.01 else "medium"
                                )
                                
                                opportunities.append(opportunity)
                                
        except Exception as e:
            self.logger.error(f"价差套利扫描失败: {e}")
        
        return opportunities
    
    async def _scan_temporal_arbitrage(self) -> List[KronosArbitrageOpportunity]:
        """扫描时间套利机会"""
        opportunities = []
        
        try:
            kronos_service = await get_kronos_integrated_service()
            symbols = self.settings.monitored_symbols
            
            for symbol in symbols:
                # 获取Kronos的时间序列预测
                kronos_decision = await kronos_service.get_kronos_enhanced_decision(
                    symbol, force_update=True
                )
                
                if (kronos_decision and 
                    kronos_decision.kronos_confidence > 0.5 and
                    kronos_decision.predicted_direction in ['上涨', '下跌']):
                    
                    # 计算时间套利机会
                    expected_move = kronos_decision.expected_return
                    
                    if abs(expected_move) > 0.02:  # 预期变动超过2%
                        opportunity = KronosArbitrageOpportunity(
                            symbol=symbol,
                            arbitrage_type=ArbitrageType.TEMPORAL,
                            expected_profit=abs(expected_move) * 0.7,
                            kronos_confidence=kronos_decision.kronos_confidence,
                            entry_price=kronos_decision.current_price,
                            holding_period=24,  # 24小时内
                            risk_score=1 - kronos_decision.kronos_confidence,
                            position_size=30000,
                            execution_priority="high" if abs(expected_move) > 0.05 else "medium"
                        )
                        
                        opportunities.append(opportunity)
                        
        except Exception as e:
            self.logger.error(f"时间套利扫描失败: {e}")
        
        return opportunities
    
    async def _send_arbitrage_notifications(self, opportunities: List[KronosArbitrageOpportunity]):
        """发送套利机会通知"""
        try:
            if not opportunities:
                return
            
            notification_service = NotificationService()
            
            # 构建通知消息
            message_parts = ["🤖 【Kronos套利机会扫描】\n"]
            
            for i, opp in enumerate(opportunities[:3], 1):
                symbol_name = opp.symbol.replace('-USDT-SWAP', '')
                type_name = opp.arbitrage_type.value
                
                message_parts.append(f"""
{i}. {symbol_name} - {type_name}
├ 预期收益: {opp.expected_profit:.2%}
├ Kronos置信度: {opp.kronos_confidence:.1%}
├ 风险评分: {opp.risk_score:.2f}
├ 建议仓位: ${opp.position_size:,.0f}
└ 执行优先级: {opp.execution_priority}
""")
            
            message_parts.append(f"\n⚠️ 套利有风险，请谨慎操作")
            
            full_message = "".join(message_parts)
            
            await notification_service.send_notification(
                full_message,
                priority="high" if any(o.execution_priority == "high" for o in opportunities) else "medium"
            )
            
            self.logger.info(f"📢 已发送套利机会通知: {len(opportunities)} 个机会")
            
        except Exception as e:
            self.logger.error(f"发送套利通知失败: {e}")


# 全局服务实例
_kronos_arbitrage_scanner = None

async def get_kronos_arbitrage_scanner() -> KronosArbitrageScanner:
    """获取Kronos套利扫描服务实例"""
    global _kronos_arbitrage_scanner
    if _kronos_arbitrage_scanner is None:
        _kronos_arbitrage_scanner = KronosArbitrageScanner()
    return _kronos_arbitrage_scanner