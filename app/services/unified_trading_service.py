# -*- coding: utf-8 -*-
"""
统一交易服务
提供统一的交易决策和执行接口
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.exceptions import TradingToolError
from app.services.trading_decision_service import TradingAction, RiskLevel

# 全局服务实例
_unified_trading_service = None


# TradingAction 和 RiskLevel 从 trading_decision_service 导入


@dataclass
class UnifiedTradingRecommendation:
    """统一交易建议"""
    symbol: str
    action: TradingAction
    confidence: float
    reasoning: str
    entry_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    position_size: float = 0.1
    timestamp: datetime = None
    
    # 智能通知服务需要的额外属性
    risk_reward_ratio: float = 2.0
    expected_profit_usdt: float = 100.0
    position_size_usdt: float = 1000.0
    leverage: float = 1.0
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    risk_level: RiskLevel = RiskLevel.MEDIUM
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        
        # 设置默认的止损和止盈价格
        if self.stop_loss_price is None:
            self.stop_loss_price = self.stop_loss
        if self.take_profit_price is None:
            self.take_profit_price = self.target_price


class UnifiedTradingService:
    """统一交易服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
    async def get_trading_recommendation(
        self,
        symbol: str,
        market_data: Optional[Dict] = None
    ) -> Optional[UnifiedTradingRecommendation]:
        """获取交易建议"""
        try:
            # 获取市场数据进行简单分析
            from app.services.okx_service import OKXService
            okx_service = OKXService()
            
            # 获取K线数据进行简单技术分析
            kline_data = await okx_service.get_kline_data(
                symbol=symbol,
                timeframe='1h',
                limit=24  # 24小时数据
            )
            
            if not kline_data or len(kline_data) < 10:
                # 数据不足，返回持有
                return UnifiedTradingRecommendation(
                    symbol=symbol,
                    action=TradingAction.HOLD,
                    confidence=50.0,
                    reasoning="数据不足，建议持有观望",
                    entry_price=None,
                    target_price=None,
                    stop_loss=None,
                    risk_reward_ratio=1.0,
                    expected_profit_usdt=0.0,
                    position_size_usdt=1000.0,
                    leverage=1.0,
                    risk_level=RiskLevel.MEDIUM
                )
            
            # 简单的技术分析
            df = pd.DataFrame(kline_data)
            # 数据已经是正确的格式，不需要转换
            
            current_price = float(df['close'].iloc[-1])
            
            # 计算简单移动平均线
            df['sma_5'] = df['close'].rolling(5).mean()
            df['sma_10'] = df['close'].rolling(10).mean()
            
            # 计算RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
            
            # 简单的交易逻辑
            sma_5 = df['sma_5'].iloc[-1]
            sma_10 = df['sma_10'].iloc[-1]
            
            action = TradingAction.HOLD
            confidence = 60.0
            reasoning = "技术分析: "
            
            # 判断趋势
            if pd.notna(sma_5) and pd.notna(sma_10):
                if sma_5 > sma_10 and current_rsi < 70:
                    action = TradingAction.BUY
                    confidence = min(80.0, 60 + (sma_5 - sma_10) / sma_10 * 1000)
                    reasoning += f"短期均线上穿长期均线，RSI={current_rsi:.1f}"
                elif sma_5 < sma_10 and current_rsi > 30:
                    action = TradingAction.SELL
                    confidence = min(80.0, 60 + (sma_10 - sma_5) / sma_5 * 1000)
                    reasoning += f"短期均线下穿长期均线，RSI={current_rsi:.1f}"
                else:
                    reasoning += f"均线交叉不明显，RSI={current_rsi:.1f}，建议观望"
            
            # 计算交易参数
            if action == TradingAction.BUY:
                entry_price = current_price
                target_price = current_price * 1.03  # 3%目标
                stop_loss = current_price * 0.98     # 2%止损
                risk_reward_ratio = (target_price - entry_price) / (entry_price - stop_loss)
                expected_profit = 1000 * 0.03  # 假设1000 USDT仓位
            elif action == TradingAction.SELL:
                entry_price = current_price
                target_price = current_price * 0.97  # 3%目标
                stop_loss = current_price * 1.02     # 2%止损
                risk_reward_ratio = (entry_price - target_price) / (stop_loss - entry_price)
                expected_profit = 1000 * 0.03  # 假设1000 USDT仓位
            else:
                entry_price = current_price
                target_price = current_price
                stop_loss = current_price
                risk_reward_ratio = 1.0
                expected_profit = 0.0
            
            return UnifiedTradingRecommendation(
                symbol=symbol,
                action=action,
                confidence=confidence,
                reasoning=reasoning,
                entry_price=entry_price,
                target_price=target_price,
                stop_loss=stop_loss,
                risk_reward_ratio=risk_reward_ratio,
                expected_profit_usdt=expected_profit,
                position_size_usdt=1000.0,
                leverage=1.0,
                stop_loss_price=stop_loss,
                take_profit_price=target_price,
                risk_level=RiskLevel.MEDIUM if confidence < 70 else RiskLevel.LOW
            )
            
        except Exception as e:
            self.logger.error(f"获取{symbol}交易建议失败: {e}")
            return None
    
    async def batch_recommendations(
        self,
        symbols: List[str]
    ) -> Dict[str, Optional[UnifiedTradingRecommendation]]:
        """批量获取交易建议"""
        results = {}
        
        for symbol in symbols:
            try:
                recommendation = await self.get_trading_recommendation(symbol)
                results[symbol] = recommendation
            except Exception as e:
                self.logger.error(f"获取{symbol}批量建议失败: {e}")
                results[symbol] = None
        
        return results


async def get_unified_trading_service() -> UnifiedTradingService:
    """获取统一交易服务实例"""
    global _unified_trading_service
    if _unified_trading_service is None:
        _unified_trading_service = UnifiedTradingService()
    return _unified_trading_service