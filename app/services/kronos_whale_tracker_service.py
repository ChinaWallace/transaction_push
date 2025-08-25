# -*- coding: utf-8 -*-
"""
Kronos巨鲸追踪服务
使用Kronos AI分析大额交易和持仓变化，识别巨鲸动向
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


class WhaleActivityType(Enum):
    """巨鲸活动类型"""
    LARGE_BUY = "大额买入"
    LARGE_SELL = "大额卖出"
    POSITION_BUILD = "建仓"
    POSITION_REDUCE = "减仓"
    UNUSUAL_VOLUME = "异常成交量"


@dataclass
class KronosWhaleSignal:
    """Kronos巨鲸信号"""
    symbol: str
    activity_type: WhaleActivityType
    direction: str  # "看涨", "看跌", "中性"
    confidence: float
    kronos_confidence: float
    
    # 交易信息
    volume_usd: float  # 成交金额
    price_impact: float  # 价格影响
    timestamp: datetime
    
    # 分析结果
    whale_score: float  # 巨鲸评分
    market_impact: str  # 市场影响程度
    follow_suggestion: str  # 跟随建议
    
    # 执行参数
    entry_price: float
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    position_size: float = 0.0


class KronosWhaleTracker:
    """Kronos巨鲸追踪器"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.last_scan_time = None
        self.scan_interval = timedelta(minutes=5)  # 5分钟扫描一次
        self.whale_threshold = 100000  # 10万美元以上算大额交易
    
    async def track_whale_activities(self) -> Dict[str, Any]:
        """追踪巨鲸活动"""
        try:
            # 检查扫描间隔
            if (self.last_scan_time and 
                datetime.now() - self.last_scan_time < self.scan_interval):
                return {"status": "skipped", "reason": "未到扫描间隔"}
            
            self.logger.info("🐋 开始Kronos巨鲸活动追踪...")
            
            whale_signals = []
            
            async with OKXService() as okx:
                # 获取所有监控币种的数据
                symbols = self.settings.monitored_symbols
                
                # 扩展到更多高成交量币种
                tickers = await okx.get_tickers()
                volume_sorted = sorted(
                    [t for t in tickers if 'USDT-SWAP' in t['instId']],
                    key=lambda x: float(x.get('volCcy24h', 0)),
                    reverse=True
                )
                
                extended_symbols = list(set(symbols + [t['instId'] for t in volume_sorted[:15]]))
                
                # 分析每个币种的巨鲸活动
                for symbol in extended_symbols:
                    try:
                        signals = await self._analyze_whale_activity(symbol, okx)
                        whale_signals.extend(signals)
                    except Exception as e:
                        self.logger.warning(f"分析{symbol}巨鲸活动失败: {e}")
                        continue
            
            # 按巨鲸评分排序
            whale_signals.sort(key=lambda x: x.whale_score * x.kronos_confidence, reverse=True)
            
            # 发送重要巨鲸信号通知
            important_signals = [s for s in whale_signals if s.whale_score > 0.5 and s.volume_usd > 200000]
            if important_signals:
                await self._send_whale_notifications(important_signals[:3])
            
            self.last_scan_time = datetime.now()
            
            return {
                "status": "success",
                "whale_signals": len(whale_signals),
                "important_signals": len(important_signals),
                "top_signals": whale_signals[:10],
                "scan_time": self.last_scan_time.isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"巨鲸追踪失败: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _analyze_whale_activity(self, symbol: str, okx: OKXService) -> List[KronosWhaleSignal]:
        """分析单个币种的巨鲸活动"""
        signals = []
        
        try:
            # 获取最近的交易数据
            trades = await okx.get_recent_trades(symbol, limit=100)
            if not trades:
                return signals
            
            # 获取当前价格
            ticker = await okx.get_ticker(symbol)
            if not ticker:
                return signals
            
            current_price = float(ticker['last'])
            
            # 获取Kronos预测
            kronos_service = await get_kronos_integrated_service()
            kronos_decision = await kronos_service.get_kronos_enhanced_decision(symbol, force_update=False)
            
            if not kronos_decision or kronos_decision.kronos_confidence < 0.3:
                return signals
            
            # 分析大额交易
            large_trades = []
            for trade in trades:
                trade_value = float(trade['sz']) * float(trade['px'])
                if trade_value > self.whale_threshold:
                    large_trades.append({
                        'side': trade['side'],
                        'size': float(trade['sz']),
                        'price': float(trade['px']),
                        'value': trade_value,
                        'timestamp': trade['ts']
                    })
            
            if not large_trades:
                return signals
            
            # 分析交易模式
            recent_large_trades = large_trades[:10]  # 最近10笔大额交易
            
            # 计算买卖比例
            buy_volume = sum(t['value'] for t in recent_large_trades if t['side'] == 'buy')
            sell_volume = sum(t['value'] for t in recent_large_trades if t['side'] == 'sell')
            total_volume = buy_volume + sell_volume
            
            if total_volume == 0:
                return signals
            
            buy_ratio = buy_volume / total_volume
            
            # 检测巨鲸建仓信号
            if buy_ratio > 0.65 and buy_volume > 500000:  # 65%以上是买入且超过50万美元
                whale_signal = await self._create_whale_signal(
                    symbol, WhaleActivityType.POSITION_BUILD, "看涨",
                    buy_volume, current_price, kronos_decision
                )
                if whale_signal:
                    signals.append(whale_signal)
            
            # 检测巨鲸减仓信号
            elif buy_ratio < 0.35 and sell_volume > 500000:  # 65%以上是卖出
                whale_signal = await self._create_whale_signal(
                    symbol, WhaleActivityType.POSITION_REDUCE, "看跌",
                    sell_volume, current_price, kronos_decision
                )
                if whale_signal:
                    signals.append(whale_signal)
            
            # 检测异常成交量
            avg_trade_size = total_volume / len(recent_large_trades)
            if avg_trade_size > 800000:  # 平均单笔超过80万美元
                direction = "看涨" if buy_ratio > 0.5 else "看跌"
                whale_signal = await self._create_whale_signal(
                    symbol, WhaleActivityType.UNUSUAL_VOLUME, direction,
                    total_volume, current_price, kronos_decision
                )
                if whale_signal:
                    signals.append(whale_signal)
                    
        except Exception as e:
            self.logger.warning(f"分析{symbol}巨鲸活动异常: {e}")
        
        return signals
    
    async def _create_whale_signal(self, symbol: str, activity_type: WhaleActivityType,
                                 direction: str, volume_usd: float, current_price: float,
                                 kronos_decision) -> Optional[KronosWhaleSignal]:
        """创建巨鲸信号"""
        try:
            # 计算价格影响（简化估算）
            price_impact = min(0.05, volume_usd / 10000000)  # 每1000万美元影响0.5%
            
            # 计算巨鲸评分
            whale_score = min(1.0, (volume_usd / 1000000) * 0.2)  # 基础评分
            
            # Kronos一致性加分
            if ((direction == "看涨" and kronos_decision.predicted_direction == "上涨") or
                (direction == "看跌" and kronos_decision.predicted_direction == "下跌")):
                whale_score *= 1.5
                confidence = 0.8
            else:
                confidence = 0.5
            
            # 设置目标价和止损
            if direction == "看涨":
                target_price = current_price * (1 + min(0.1, price_impact * 3))
                stop_loss = current_price * 0.97
                follow_suggestion = "跟随买入"
            else:
                target_price = current_price * (1 - min(0.1, price_impact * 3))
                stop_loss = current_price * 1.03
                follow_suggestion = "跟随卖出"
            
            # 确定市场影响程度
            if volume_usd > 5000000:
                market_impact = "重大影响"
            elif volume_usd > 2000000:
                market_impact = "中等影响"
            else:
                market_impact = "轻微影响"
            
            # 计算建议仓位
            position_size = min(50000, volume_usd * 0.05)  # 巨鲸交易金额的5%
            
            return KronosWhaleSignal(
                symbol=symbol,
                activity_type=activity_type,
                direction=direction,
                confidence=confidence,
                kronos_confidence=kronos_decision.kronos_confidence,
                volume_usd=volume_usd,
                price_impact=price_impact,
                timestamp=datetime.now(),
                whale_score=min(1.0, whale_score),
                market_impact=market_impact,
                follow_suggestion=follow_suggestion,
                entry_price=current_price,
                target_price=target_price,
                stop_loss=stop_loss,
                position_size=position_size
            )
            
        except Exception as e:
            self.logger.warning(f"创建{symbol}巨鲸信号失败: {e}")
            return None
    
    async def _send_whale_notifications(self, signals: List[KronosWhaleSignal]):
        """发送巨鲸信号通知"""
        try:
            if not signals:
                return
            
            notification_service = NotificationService()
            
            # 构建通知消息
            message_parts = ["🐋 【Kronos巨鲸追踪警报】\n"]
            
            for i, signal in enumerate(signals[:3], 1):
                symbol_name = signal.symbol.replace('-USDT-SWAP', '')
                activity_name = signal.activity_type.value
                
                message_parts.append(f"""
{i}. {symbol_name} - {activity_name}
├ 方向: {signal.direction}
├ 交易金额: ${signal.volume_usd:,.0f}
├ 巨鲸评分: {signal.whale_score:.1%}
├ Kronos置信度: {signal.kronos_confidence:.1%}
├ 价格影响: {signal.price_impact:.2%}
├ 市场影响: {signal.market_impact}
├ 跟随建议: {signal.follow_suggestion}
├ 目标价格: ${signal.target_price:.4f}
└ 建议仓位: ${signal.position_size:,.0f}
""")
            
            message_parts.append(f"\n⚠️ 巨鲸动向仅供参考，请结合其他指标判断")
            
            full_message = "".join(message_parts)
            
            await notification_service.send_notification(
                full_message,
                priority="high"
            )
            
            self.logger.info(f"📢 已发送巨鲸追踪通知: {len(signals)} 个信号")
            
        except Exception as e:
            self.logger.error(f"发送巨鲸通知失败: {e}")


# 全局服务实例
_kronos_whale_tracker = None

async def get_kronos_whale_tracker() -> KronosWhaleTracker:
    """获取Kronos巨鲸追踪服务实例"""
    global _kronos_whale_tracker
    if _kronos_whale_tracker is None:
        _kronos_whale_tracker = KronosWhaleTracker()
    return _kronos_whale_tracker