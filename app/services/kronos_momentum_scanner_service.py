# -*- coding: utf-8 -*-
"""
Kronos动量扫描服务
使用Kronos AI识别强动量交易机会，包括突破、反转等
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


class MomentumType(Enum):
    """动量类型"""
    BREAKOUT = "突破"
    REVERSAL = "反转"
    ACCELERATION = "加速"
    DIVERGENCE = "背离"


@dataclass
class KronosMomentumSignal:
    """Kronos动量信号"""
    symbol: str
    momentum_type: MomentumType
    direction: str  # "看涨", "看跌"
    strength: float  # 信号强度 0-1
    kronos_confidence: float
    
    # 价格信息
    current_price: float
    target_price: float
    stop_loss: float
    
    # 动量指标
    momentum_score: float
    volume_confirmation: bool
    
    # 执行建议
    entry_timing: str  # "立即", "等待回调", "突破确认"
    position_size: float
    holding_period: int  # 预期持有时间(小时)


class KronosMomentumScanner:
    """Kronos动量扫描器"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.last_scan_time = None
        self.scan_interval = timedelta(minutes=10)  # 10分钟扫描一次
    
    async def scan_momentum_opportunities(self) -> Dict[str, Any]:
        """扫描动量交易机会"""
        try:
            # 检查扫描间隔
            if (self.last_scan_time and 
                datetime.now() - self.last_scan_time < self.scan_interval):
                return {"status": "skipped", "reason": "未到扫描间隔"}
            
            self.logger.info("⚡ 开始Kronos动量机会扫描...")
            
            signals = []
            
            # 获取市场数据
            async with OKXService() as okx:
                # 扫描所有监控币种
                symbols = self.settings.monitored_symbols
                
                # 获取更多潜在机会币种
                tickers = await okx.get_tickers()
                volume_sorted = sorted(
                    [t for t in tickers if 'USDT-SWAP' in t['instId']],
                    key=lambda x: float(x.get('vol24h', 0)),
                    reverse=True
                )
                
                # 扩展到前20个高成交量币种
                extended_symbols = list(set(symbols + [t['instId'] for t in volume_sorted[:20]]))
                
                # 批量分析
                for symbol in extended_symbols:
                    try:
                        momentum_signals = await self._analyze_symbol_momentum(symbol, okx)
                        signals.extend(momentum_signals)
                    except Exception as e:
                        self.logger.warning(f"分析{symbol}动量失败: {e}")
                        continue
            
            # 按信号强度排序
            signals.sort(key=lambda x: x.strength * x.kronos_confidence, reverse=True)
            
            # 发送强信号通知
            strong_signals = [s for s in signals if s.strength > 0.5 and s.kronos_confidence > 0.4]
            if strong_signals:
                await self._send_momentum_notifications(strong_signals[:5])
            
            self.last_scan_time = datetime.now()
            
            return {
                "status": "success",
                "signals_found": len(signals),
                "strong_signals": len(strong_signals),
                "top_signals": signals[:10],
                "scan_time": self.last_scan_time.isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"动量扫描失败: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _analyze_symbol_momentum(self, symbol: str, okx: OKXService) -> List[KronosMomentumSignal]:
        """分析单个币种的动量"""
        signals = []
        
        try:
            # 获取K线数据
            klines = await okx.get_klines(symbol, '15m', limit=100)
            if not klines or len(klines) < 50:
                return signals
            
            df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = df.astype({'open': float, 'high': float, 'low': float, 'close': float, 'volume': float})
            
            # 获取Kronos预测
            kronos_service = await get_kronos_integrated_service()
            kronos_decision = await kronos_service.get_kronos_enhanced_decision(symbol, force_update=False)
            
            if not kronos_decision or kronos_decision.kronos_confidence < 0.35:
                return signals
            
            current_price = df['close'].iloc[-1]
            
            # 1. 检测突破信号
            breakout_signal = await self._detect_breakout(df, symbol, kronos_decision, current_price)
            if breakout_signal:
                signals.append(breakout_signal)
            
            # 2. 检测反转信号
            reversal_signal = await self._detect_reversal(df, symbol, kronos_decision, current_price)
            if reversal_signal:
                signals.append(reversal_signal)
            
            # 3. 检测加速信号
            acceleration_signal = await self._detect_acceleration(df, symbol, kronos_decision, current_price)
            if acceleration_signal:
                signals.append(acceleration_signal)
            
        except Exception as e:
            self.logger.warning(f"分析{symbol}动量异常: {e}")
        
        return signals
    
    async def _detect_breakout(self, df: pd.DataFrame, symbol: str, 
                             kronos_decision, current_price: float) -> Optional[KronosMomentumSignal]:
        """检测突破信号"""
        try:
            # 计算阻力支撑位
            high_20 = df['high'].rolling(20).max().iloc[-1]
            low_20 = df['low'].rolling(20).min().iloc[-1]
            
            # 计算成交量确认
            volume_ma = df['volume'].rolling(10).mean().iloc[-1]
            current_volume = df['volume'].iloc[-1]
            volume_confirmation = current_volume > volume_ma * 1.5
            
            # 检测向上突破
            if (current_price > high_20 * 1.002 and  # 突破阻力位
                kronos_decision.kronos_prediction and
                kronos_decision.kronos_prediction.trend_direction == 'bullish'):
                
                target_price = current_price * (1 + (kronos_decision.kronos_prediction.price_change_pct if kronos_decision.kronos_prediction else 0.05))
                stop_loss = high_20 * 0.995
                
                return KronosMomentumSignal(
                    symbol=symbol,
                    momentum_type=MomentumType.BREAKOUT,
                    direction="看涨",
                    strength=min(0.9, (current_price - high_20) / high_20 * 50),
                    kronos_confidence=kronos_decision.kronos_confidence,
                    current_price=current_price,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    momentum_score=0.8,
                    volume_confirmation=volume_confirmation,
                    entry_timing="突破确认",
                    position_size=25000,
                    holding_period=12
                )
            
            # 检测向下突破
            elif (current_price < low_20 * 0.998 and
                  kronos_decision.kronos_prediction and
                  kronos_decision.kronos_prediction.trend_direction == 'bearish'):
                
                target_price = current_price * (1 + (kronos_decision.kronos_prediction.price_change_pct if kronos_decision.kronos_prediction else -0.05))
                stop_loss = low_20 * 1.005
                
                return KronosMomentumSignal(
                    symbol=symbol,
                    momentum_type=MomentumType.BREAKOUT,
                    direction="看跌",
                    strength=min(0.9, (low_20 - current_price) / low_20 * 50),
                    kronos_confidence=kronos_decision.kronos_confidence,
                    current_price=current_price,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    momentum_score=0.8,
                    volume_confirmation=volume_confirmation,
                    entry_timing="突破确认",
                    position_size=25000,
                    holding_period=12
                )
                
        except Exception as e:
            self.logger.warning(f"检测{symbol}突破信号失败: {e}")
        
        return None
    
    async def _detect_reversal(self, df: pd.DataFrame, symbol: str,
                             kronos_decision, current_price: float) -> Optional[KronosMomentumSignal]:
        """检测反转信号"""
        try:
            # 计算RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]
            
            # 计算价格变化
            price_change_5 = (current_price - df['close'].iloc[-6]) / df['close'].iloc[-6]
            
            # 检测超卖反转
            if (current_rsi < 30 and
                price_change_5 < -0.05 and  # 5期内下跌超过5%
                kronos_decision.kronos_prediction and
                kronos_decision.kronos_prediction.trend_direction == 'bullish' and
                kronos_decision.kronos_confidence > 0.4):
                
                target_price = current_price * 1.08
                stop_loss = current_price * 0.95
                
                return KronosMomentumSignal(
                    symbol=symbol,
                    momentum_type=MomentumType.REVERSAL,
                    direction="看涨",
                    strength=(30 - current_rsi) / 30 * 0.8,
                    kronos_confidence=kronos_decision.kronos_confidence,
                    current_price=current_price,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    momentum_score=0.7,
                    volume_confirmation=True,
                    entry_timing="等待回调",
                    position_size=20000,
                    holding_period=24
                )
            
            # 检测超买反转
            elif (current_rsi > 70 and
                  price_change_5 > 0.05 and
                  kronos_decision.kronos_prediction and
                  kronos_decision.kronos_prediction.trend_direction == 'bearish' and
                  kronos_decision.kronos_confidence > 0.4):
                
                target_price = current_price * 0.92
                stop_loss = current_price * 1.05
                
                return KronosMomentumSignal(
                    symbol=symbol,
                    momentum_type=MomentumType.REVERSAL,
                    direction="看跌",
                    strength=(current_rsi - 70) / 30 * 0.8,
                    kronos_confidence=kronos_decision.kronos_confidence,
                    current_price=current_price,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    momentum_score=0.7,
                    volume_confirmation=True,
                    entry_timing="等待回调",
                    position_size=20000,
                    holding_period=24
                )
                
        except Exception as e:
            self.logger.warning(f"检测{symbol}反转信号失败: {e}")
        
        return None
    
    async def _detect_acceleration(self, df: pd.DataFrame, symbol: str,
                                 kronos_decision, current_price: float) -> Optional[KronosMomentumSignal]:
        """检测加速信号"""
        try:
            # 计算价格动量
            returns = df['close'].pct_change()
            momentum_3 = returns.rolling(3).sum().iloc[-1]
            momentum_10 = returns.rolling(10).sum().iloc[-1]
            
            # 检测加速上涨
            if (momentum_3 > 0.03 and  # 3期涨幅超过3%
                momentum_3 > momentum_10 * 2 and  # 短期动量强于长期
                kronos_decision.kronos_prediction and
                kronos_decision.kronos_prediction.trend_direction == 'bullish' and
                kronos_decision.kronos_confidence > 0.45):
                
                target_price = current_price * (1 + min(0.15, momentum_3 * 2))
                stop_loss = current_price * 0.97
                
                return KronosMomentumSignal(
                    symbol=symbol,
                    momentum_type=MomentumType.ACCELERATION,
                    direction="看涨",
                    strength=min(0.95, momentum_3 * 10),
                    kronos_confidence=kronos_decision.kronos_confidence,
                    current_price=current_price,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    momentum_score=0.9,
                    volume_confirmation=True,
                    entry_timing="立即",
                    position_size=30000,
                    holding_period=6
                )
            
            # 检测加速下跌
            elif (momentum_3 < -0.03 and
                  abs(momentum_3) > abs(momentum_10) * 2 and
                  kronos_decision.kronos_prediction and
                  kronos_decision.kronos_prediction.trend_direction == 'bearish' and
                  kronos_decision.kronos_confidence > 0.45):
                
                target_price = current_price * (1 + max(-0.15, momentum_3 * 2))
                stop_loss = current_price * 1.03
                
                return KronosMomentumSignal(
                    symbol=symbol,
                    momentum_type=MomentumType.ACCELERATION,
                    direction="看跌",
                    strength=min(0.95, abs(momentum_3) * 10),
                    kronos_confidence=kronos_decision.kronos_confidence,
                    current_price=current_price,
                    target_price=target_price,
                    stop_loss=stop_loss,
                    momentum_score=0.9,
                    volume_confirmation=True,
                    entry_timing="立即",
                    position_size=30000,
                    holding_period=6
                )
                
        except Exception as e:
            self.logger.warning(f"检测{symbol}加速信号失败: {e}")
        
        return None
    
    async def _send_momentum_notifications(self, signals: List[KronosMomentumSignal]):
        """发送动量信号通知"""
        try:
            if not signals:
                return
            
            notification_service = NotificationService()
            
            # 构建通知消息
            message_parts = ["⚡ 【Kronos动量交易信号】\n"]
            
            for i, signal in enumerate(signals[:3], 1):
                symbol_name = signal.symbol.replace('-USDT-SWAP', '')
                type_name = signal.momentum_type.value
                
                message_parts.append(f"""
{i}. {symbol_name} - {type_name}{signal.direction}
├ 信号强度: {signal.strength:.1%}
├ Kronos置信度: {signal.kronos_confidence:.1%}
├ 当前价格: ${signal.current_price:.4f}
├ 目标价格: ${signal.target_price:.4f}
├ 止损价格: ${signal.stop_loss:.4f}
├ 入场时机: {signal.entry_timing}
└ 建议仓位: ${signal.position_size:,.0f}
""")
            
            message_parts.append(f"\n⚠️ 动量交易风险较高，请严格止损")
            
            full_message = "".join(message_parts)
            
            await notification_service.send_notification(
                full_message,
                priority="high"
            )
            
            self.logger.info(f"📢 已发送动量信号通知: {len(signals)} 个信号")
            
        except Exception as e:
            self.logger.error(f"发送动量通知失败: {e}")


# 全局服务实例
_kronos_momentum_scanner = None

async def get_kronos_momentum_scanner() -> KronosMomentumScanner:
    """获取Kronos动量扫描服务实例"""
    global _kronos_momentum_scanner
    if _kronos_momentum_scanner is None:
        _kronos_momentum_scanner = KronosMomentumScanner()
    return _kronos_momentum_scanner