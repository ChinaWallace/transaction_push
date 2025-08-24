# -*- coding: utf-8 -*-
"""
回测服务
Backtesting Service - 完整的策略回测框架
"""

from typing import Dict, Any, List, Optional, Tuple, Union
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
import asyncio
import numpy as np
import pandas as pd
from decimal import Decimal, ROUND_HALF_UP
import json

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.binance_service import BinanceService
from app.services.okx_service import OKXService
from app.services.trend_analysis_service import TrendAnalysisService
from app.services.ml_enhanced_service import MLEnhancedService
from app.utils.indicators import SuperTrendIndicator
from app.utils.exceptions import TradingToolError, BacktestError

logger = get_logger(__name__)
settings = get_settings()


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    PARTIAL_FILLED = "partial_filled"


class PositionSide(Enum):
    """持仓方向"""
    LONG = "long"
    SHORT = "short"


@dataclass
class BacktestOrder:
    """回测订单"""
    order_id: str
    symbol: str
    side: str  # buy/sell
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None
    filled_price: Optional[float] = None
    filled_quantity: float = 0.0
    commission: float = 0.0


@dataclass
class BacktestPosition:
    """回测持仓"""
    symbol: str
    side: PositionSide
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    entry_time: datetime = field(default_factory=datetime.now)
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)


@dataclass
class BacktestTrade:
    """回测交易记录"""
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percent: float
    entry_time: datetime
    exit_time: datetime
    duration_hours: float
    commission: float
    reason: str  # 平仓原因：stop_loss, take_profit, signal_change, manual
    strategy_signals: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestMetrics:
    """回测指标"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_pnl_percent: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_percent: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_trade_duration_hours: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    total_commission: float = 0.0
    start_balance: float = 0.0
    end_balance: float = 0.0
    peak_balance: float = 0.0


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self):
        self.binance_service = BinanceService()
        self.okx_service = OKXService()
        self.trend_service = TrendAnalysisService()
        self.ml_service = MLEnhancedService()
        
        # 回测状态
        self.current_time: Optional[datetime] = None
        self.balance: float = 0.0
        self.initial_balance: float = 0.0
        self.positions: Dict[str, BacktestPosition] = {}
        self.orders: List[BacktestOrder] = []
        self.trades: List[BacktestTrade] = []
        self.balance_history: List[Tuple[datetime, float]] = []
        
        # 配置参数
        self.commission_rate: float = 0.0004  # 0.04% 手续费
        self.slippage: float = 0.0001  # 0.01% 滑点
        
    async def initialize_backtest(
        self,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float = 10000.0,
        symbols: List[str] = None
    ):
        """初始化回测"""
        self.current_time = start_date
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.positions.clear()
        self.orders.clear()
        self.trades.clear()
        self.balance_history = [(start_date, initial_balance)]
        
        logger.info(f"回测初始化完成: {start_date} - {end_date}, 初始资金: {initial_balance}")
    
    async def get_market_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1h"
    ) -> pd.DataFrame:
        """获取历史市场数据"""
        try:
            # 优先使用币安数据
            klines = await self.binance_service.get_historical_klines(
                symbol=symbol,
                interval=interval,
                start_str=start_date.strftime("%Y-%m-%d %H:%M:%S"),
                end_str=end_date.strftime("%Y-%m-%d %H:%M:%S")
            )
            
            if not klines:
                # 备用OKX数据
                klines = await self.okx_service.get_historical_klines(
                    symbol=symbol,
                    interval=interval,
                    start_date=start_date,
                    end_date=end_date
                )
            
            if not klines:
                raise BacktestError(f"无法获取 {symbol} 的历史数据")
            
            # 转换为DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'count', 'taker_buy_volume',
                'taker_buy_quote_volume', 'ignore'
            ])
            
            # 数据类型转换
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            return df[['open', 'high', 'low', 'close', 'volume']]
            
        except Exception as e:
            logger.error(f"获取市场数据失败 {symbol}: {e}")
            raise BacktestError(f"获取市场数据失败: {str(e)}")
    
    def calculate_dynamic_stop_loss(
        self,
        symbol: str,
        entry_price: float,
        position_side: PositionSide,
        market_data: pd.DataFrame,
        lookback_periods: int = 20
    ) -> Tuple[float, List[float], List[float]]:
        """
        基于技术分析计算动态止损位
        返回: (止损价格, 支撑位列表, 压力位列表)
        """
        try:
            # 计算支撑位和压力位
            support_levels, resistance_levels = calculate_support_resistance(
                market_data, 
                lookback_periods=lookback_periods
            )
            
            if position_side == PositionSide.LONG:
                # 多头持仓：使用最近的支撑位作为止损
                valid_supports = [s for s in support_levels if s < entry_price]
                if valid_supports:
                    # 选择最接近当前价格的支撑位
                    stop_loss_price = max(valid_supports)
                    # 确保止损不超过5%
                    max_stop_loss = entry_price * 0.95
                    stop_loss_price = max(stop_loss_price, max_stop_loss)
                else:
                    # 没有有效支撑位，使用固定百分比
                    stop_loss_price = entry_price * 0.97
            else:
                # 空头持仓：使用最近的压力位作为止损
                valid_resistances = [r for r in resistance_levels if r > entry_price]
                if valid_resistances:
                    # 选择最接近当前价格的压力位
                    stop_loss_price = min(valid_resistances)
                    # 确保止损不超过5%
                    max_stop_loss = entry_price * 1.05
                    stop_loss_price = min(stop_loss_price, max_stop_loss)
                else:
                    # 没有有效压力位，使用固定百分比
                    stop_loss_price = entry_price * 1.03
            
            return stop_loss_price, support_levels, resistance_levels
            
        except Exception as e:
            logger.error(f"计算动态止损失败 {symbol}: {e}")
            # 回退到固定止损
            if position_side == PositionSide.LONG:
                return entry_price * 0.97, [], []
            else:
                return entry_price * 1.03, [], []
    
    def calculate_dynamic_take_profit(
        self,
        symbol: str,
        entry_price: float,
        position_side: PositionSide,
        support_levels: List[float],
        resistance_levels: List[float],
        risk_reward_ratio: float = 2.0
    ) -> float:
        """
        基于技术分析计算动态止盈位
        """
        try:
            if position_side == PositionSide.LONG:
                # 多头持仓：使用压力位作为止盈目标
                valid_resistances = [r for r in resistance_levels if r > entry_price]
                if valid_resistances:
                    # 选择第一个或第二个压力位
                    sorted_resistances = sorted(valid_resistances)
                    if len(sorted_resistances) >= 2:
                        take_profit_price = sorted_resistances[1]  # 第二个压力位
                    else:
                        take_profit_price = sorted_resistances[0]  # 第一个压力位
                    
                    # 确保风险收益比合理
                    min_take_profit = entry_price * (1 + 0.03 * risk_reward_ratio)
                    take_profit_price = max(take_profit_price, min_take_profit)
                else:
                    # 没有压力位，使用风险收益比计算
                    take_profit_price = entry_price * (1 + 0.03 * risk_reward_ratio)
            else:
                # 空头持仓：使用支撑位作为止盈目标
                valid_supports = [s for s in support_levels if s < entry_price]
                if valid_supports:
                    # 选择第一个或第二个支撑位
                    sorted_supports = sorted(valid_supports, reverse=True)
                    if len(sorted_supports) >= 2:
                        take_profit_price = sorted_supports[1]  # 第二个支撑位
                    else:
                        take_profit_price = sorted_supports[0]  # 第一个支撑位
                    
                    # 确保风险收益比合理
                    max_take_profit = entry_price * (1 - 0.03 * risk_reward_ratio)
                    take_profit_price = min(take_profit_price, max_take_profit)
                else:
                    # 没有支撑位，使用风险收益比计算
                    take_profit_price = entry_price * (1 - 0.03 * risk_reward_ratio)
            
            return take_profit_price
            
        except Exception as e:
            logger.error(f"计算动态止盈失败 {symbol}: {e}")
            # 回退到固定止盈
            if position_side == PositionSide.LONG:
                return entry_price * 1.06
            else:
                return entry_price * 0.94
    
    async def execute_strategy_signal(
        self,
        symbol: str,
        signal_data: Dict[str, Any],
        market_data: pd.DataFrame,
        current_price: float
    ) -> Optional[BacktestOrder]:
        """执行策略信号"""
        try:
            action = signal_data.get('action', 'hold')
            confidence = signal_data.get('confidence', 0.0)
            
            # 检查是否已有持仓
            existing_position = self.positions.get(symbol)
            
            if action in ['strong_buy', 'buy'] and confidence > 0.6:
                # 买入信号
                if existing_position and existing_position.side == PositionSide.SHORT:
                    # 先平空头
                    await self._close_position(symbol, "signal_change")
                
                if not existing_position or existing_position.side != PositionSide.LONG:
                    # 开多头
                    position_size = self._calculate_position_size(
                        current_price, 
                        confidence,
                        signal_data.get('risk_level', 'medium')
                    )
                    
                    order = await self._create_market_order(
                        symbol=symbol,
                        side="buy",
                        quantity=position_size,
                        price=current_price
                    )
                    
                    return order
            
            elif action in ['strong_sell', 'sell'] and confidence > 0.6:
                # 卖出信号
                if existing_position and existing_position.side == PositionSide.LONG:
                    # 先平多头
                    await self._close_position(symbol, "signal_change")
                
                if not existing_position or existing_position.side != PositionSide.SHORT:
                    # 开空头
                    position_size = self._calculate_position_size(
                        current_price, 
                        confidence,
                        signal_data.get('risk_level', 'medium')
                    )
                    
                    order = await self._create_market_order(
                        symbol=symbol,
                        side="sell",
                        quantity=position_size,
                        price=current_price
                    )
                    
                    return order
            
            elif action == 'hold' and existing_position:
                # 持有信号，检查是否需要调整止损止盈
                await self._update_position_stops(symbol, market_data, current_price)
            
            return None
            
        except Exception as e:
            logger.error(f"执行策略信号失败 {symbol}: {e}")
            return None
    
    def _calculate_position_size(
        self,
        price: float,
        confidence: float,
        risk_level: str
    ) -> float:
        """计算仓位大小"""
        # 基础风险百分比
        base_risk_percent = {
            'very_low': 0.01,   # 1%
            'low': 0.02,        # 2%
            'medium': 0.03,     # 3%
            'high': 0.05,       # 5%
            'very_high': 0.08   # 8%
        }.get(risk_level, 0.03)
        
        # 根据信号置信度调整
        confidence_multiplier = min(confidence * 1.5, 1.0)
        risk_percent = base_risk_percent * confidence_multiplier
        
        # 计算仓位大小（基于账户余额的百分比）
        risk_amount = self.balance * risk_percent
        position_size = risk_amount / price
        
        return position_size
    
    async def _create_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float
    ) -> BacktestOrder:
        """创建市价订单"""
        order_id = f"{symbol}_{side}_{int(self.current_time.timestamp())}"
        
        # 考虑滑点
        if side == "buy":
            filled_price = price * (1 + self.slippage)
        else:
            filled_price = price * (1 - self.slippage)
        
        # 计算手续费
        commission = quantity * filled_price * self.commission_rate
        
        order = BacktestOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=price,
            status=OrderStatus.FILLED,
            created_at=self.current_time,
            filled_at=self.current_time,
            filled_price=filled_price,
            filled_quantity=quantity,
            commission=commission
        )
        
        # 更新账户余额
        if side == "buy":
            self.balance -= (quantity * filled_price + commission)
        else:
            self.balance += (quantity * filled_price - commission)
        
        # 创建或更新持仓
        await self._update_position_from_order(order)
        
        self.orders.append(order)
        logger.info(f"执行订单: {symbol} {side} {quantity:.6f} @ {filled_price:.4f}")
        
        return order
    
    async def _update_position_from_order(self, order: BacktestOrder):
        """根据订单更新持仓"""
        symbol = order.symbol
        existing_position = self.positions.get(symbol)
        
        if order.side == "buy":
            if existing_position and existing_position.side == PositionSide.SHORT:
                # 平空头仓位
                if existing_position.size <= order.filled_quantity:
                    # 完全平仓
                    await self._close_position_completely(symbol, order)
                else:
                    # 部分平仓
                    existing_position.size -= order.filled_quantity
                    existing_position.unrealized_pnl = (
                        existing_position.entry_price - order.filled_price
                    ) * existing_position.size
            else:
                # 开多头或加仓
                if existing_position and existing_position.side == PositionSide.LONG:
                    # 加仓
                    total_cost = (existing_position.size * existing_position.entry_price + 
                                order.filled_quantity * order.filled_price)
                    total_size = existing_position.size + order.filled_quantity
                    existing_position.entry_price = total_cost / total_size
                    existing_position.size = total_size
                else:
                    # 开新多头仓位
                    await self._create_new_position(order, PositionSide.LONG)
        
        else:  # sell
            if existing_position and existing_position.side == PositionSide.LONG:
                # 平多头仓位
                if existing_position.size <= order.filled_quantity:
                    # 完全平仓
                    await self._close_position_completely(symbol, order)
                else:
                    # 部分平仓
                    existing_position.size -= order.filled_quantity
                    existing_position.unrealized_pnl = (
                        order.filled_price - existing_position.entry_price
                    ) * existing_position.size
            else:
                # 开空头或加仓
                if existing_position and existing_position.side == PositionSide.SHORT:
                    # 加仓
                    total_cost = (existing_position.size * existing_position.entry_price + 
                                order.filled_quantity * order.filled_price)
                    total_size = existing_position.size + order.filled_quantity
                    existing_position.entry_price = total_cost / total_size
                    existing_position.size = total_size
                else:
                    # 开新空头仓位
                    await self._create_new_position(order, PositionSide.SHORT)
    
    async def _create_new_position(self, order: BacktestOrder, side: PositionSide):
        """创建新持仓"""
        symbol = order.symbol
        
        # 获取市场数据用于计算止损止盈
        try:
            # 这里需要当前的市场数据，简化处理
            market_data = pd.DataFrame()  # 实际应该传入当前的市场数据
            
            # 计算动态止损止盈
            stop_loss_price, support_levels, resistance_levels = self.calculate_dynamic_stop_loss(
                symbol, order.filled_price, side, market_data
            )
            
            take_profit_price = self.calculate_dynamic_take_profit(
                symbol, order.filled_price, side, support_levels, resistance_levels
            )
            
            position = BacktestPosition(
                symbol=symbol,
                side=side,
                size=order.filled_quantity,
                entry_price=order.filled_price,
                current_price=order.filled_price,
                entry_time=order.filled_at,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                support_levels=support_levels,
                resistance_levels=resistance_levels
            )
            
            self.positions[symbol] = position
            logger.info(f"创建新持仓: {symbol} {side.value} {order.filled_quantity:.6f} @ {order.filled_price:.4f}")
            logger.info(f"止损: {stop_loss_price:.4f}, 止盈: {take_profit_price:.4f}")
            
        except Exception as e:
            logger.error(f"创建持仓失败 {symbol}: {e}")
    
    async def _close_position_completely(self, symbol: str, order: BacktestOrder):
        """完全平仓"""
        position = self.positions.get(symbol)
        if not position:
            return
        
        # 计算盈亏
        if position.side == PositionSide.LONG:
            pnl = (order.filled_price - position.entry_price) * position.size
        else:
            pnl = (position.entry_price - order.filled_price) * position.size
        
        pnl_percent = (pnl / (position.entry_price * position.size)) * 100
        
        # 创建交易记录
        trade = BacktestTrade(
            trade_id=f"{symbol}_{int(self.current_time.timestamp())}",
            symbol=symbol,
            side=position.side.value,
            entry_price=position.entry_price,
            exit_price=order.filled_price,
            quantity=position.size,
            pnl=pnl - order.commission,
            pnl_percent=pnl_percent,
            entry_time=position.entry_time,
            exit_time=order.filled_at,
            duration_hours=(order.filled_at - position.entry_time).total_seconds() / 3600,
            commission=order.commission,
            reason="manual"  # 这里应该传入具体原因
        )
        
        self.trades.append(trade)
        del self.positions[symbol]
        
        logger.info(f"平仓完成: {symbol} PnL: {pnl:.2f} ({pnl_percent:.2f}%)")
    
    async def _close_position(self, symbol: str, reason: str):
        """平仓"""
        position = self.positions.get(symbol)
        if not position:
            return
        
        # 创建平仓订单
        if position.side == PositionSide.LONG:
            side = "sell"
        else:
            side = "buy"
        
        order = await self._create_market_order(
            symbol=symbol,
            side=side,
            quantity=position.size,
            price=position.current_price
        )
        
        # 更新交易记录的平仓原因
        if self.trades and self.trades[-1].symbol == symbol:
            self.trades[-1].reason = reason
    
    async def _update_position_stops(
        self,
        symbol: str,
        market_data: pd.DataFrame,
        current_price: float
    ):
        """更新持仓的止损止盈"""
        position = self.positions.get(symbol)
        if not position:
            return
        
        # 更新当前价格和未实现盈亏
        position.current_price = current_price
        
        if position.side == PositionSide.LONG:
            position.unrealized_pnl = (current_price - position.entry_price) * position.size
        else:
            position.unrealized_pnl = (position.entry_price - current_price) * position.size
        
        # 检查是否触发止损止盈
        if position.side == PositionSide.LONG:
            if current_price <= position.stop_loss_price:
                await self._close_position(symbol, "stop_loss")
                return
            elif current_price >= position.take_profit_price:
                await self._close_position(symbol, "take_profit")
                return
        else:
            if current_price >= position.stop_loss_price:
                await self._close_position(symbol, "stop_loss")
                return
            elif current_price <= position.take_profit_price:
                await self._close_position(symbol, "take_profit")
                return
        
        # 动态调整止损（移动止损）
        if len(market_data) >= 20:  # 确保有足够数据
            new_stop_loss, _, _ = self.calculate_dynamic_stop_loss(
                symbol, position.entry_price, position.side, market_data
            )
            
            # 只有在止损更有利时才更新
            if position.side == PositionSide.LONG and new_stop_loss > position.stop_loss_price:
                position.stop_loss_price = new_stop_loss
                logger.info(f"更新止损: {symbol} -> {new_stop_loss:.4f}")
            elif position.side == PositionSide.SHORT and new_stop_loss < position.stop_loss_price:
                position.stop_loss_price = new_stop_loss
                logger.info(f"更新止损: {symbol} -> {new_stop_loss:.4f}")
    
    def calculate_metrics(self) -> BacktestMetrics:
        """计算回测指标"""
        if not self.trades:
            return BacktestMetrics(start_balance=self.initial_balance, end_balance=self.balance)
        
        # 基础统计
        total_trades = len(self.trades)
        winning_trades = len([t for t in self.trades if t.pnl > 0])
        losing_trades = len([t for t in self.trades if t.pnl < 0])
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # 盈亏统计
        total_pnl = sum(t.pnl for t in self.trades)
        total_pnl_percent = (total_pnl / self.initial_balance) * 100
        
        wins = [t.pnl for t in self.trades if t.pnl > 0]
        losses = [t.pnl for t in self.trades if t.pnl < 0]
        
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        
        # 计算最大回撤
        balance_values = [b[1] for b in self.balance_history]
        peak_balance = max(balance_values)
        max_drawdown = peak_balance - min(balance_values)
        max_drawdown_percent = (max_drawdown / peak_balance) * 100 if peak_balance > 0 else 0
        
        # 风险指标
        returns = []
        for i in range(1, len(balance_values)):
            ret = (balance_values[i] - balance_values[i-1]) / balance_values[i-1]
            returns.append(ret)
        
        if returns:
            returns_array = np.array(returns)
            sharpe_ratio = np.mean(returns_array) / np.std(returns_array) * np.sqrt(252) if np.std(returns_array) > 0 else 0
            
            negative_returns = returns_array[returns_array < 0]
            sortino_ratio = np.mean(returns_array) / np.std(negative_returns) * np.sqrt(252) if len(negative_returns) > 0 and np.std(negative_returns) > 0 else 0
        else:
            sharpe_ratio = 0
            sortino_ratio = 0
        
        # 盈亏比
        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 0
        
        # 其他指标
        avg_trade_duration = np.mean([t.duration_hours for t in self.trades]) if self.trades else 0
        total_commission = sum(t.commission for t in self.trades)
        
        # 连续盈亏
        consecutive_wins = 0
        consecutive_losses = 0
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        
        for trade in self.trades:
            if trade.pnl > 0:
                consecutive_wins += 1
                consecutive_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
            else:
                consecutive_losses += 1
                consecutive_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        
        return BacktestMetrics(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_pnl=total_pnl,
            total_pnl_percent=total_pnl_percent,
            max_drawdown=max_drawdown,
            max_drawdown_percent=max_drawdown_percent,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_trade_duration_hours=avg_trade_duration,
            max_consecutive_wins=max_consecutive_wins,
            max_consecutive_losses=max_consecutive_losses,
            total_commission=total_commission,
            start_balance=self.initial_balance,
            end_balance=self.balance,
            peak_balance=peak_balance
        )
    
    async def run_backtest(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        initial_balance: float = 10000.0,
        interval: str = "1h",
        strategy_configs: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        运行完整回测
        
        Args:
            symbols: 交易对列表
            start_date: 开始日期
            end_date: 结束日期
            initial_balance: 初始资金
            interval: 时间间隔
            strategy_configs: 策略配置
            
        Returns:
            回测结果
        """
        try:
            # 初始化回测
            await self.initialize_backtest(start_date, end_date, initial_balance, symbols)
            
            logger.info(f"🚀 开始回测: {symbols} ({start_date} - {end_date})")
            
            # 为每个交易对获取历史数据
            symbol_data = {}
            for symbol in symbols:
                try:
                    data = await self.get_market_data(symbol, start_date, end_date, interval)
                    if not data.empty:
                        symbol_data[symbol] = data
                        logger.info(f"📊 已加载 {symbol} 数据: {len(data)} 条记录")
                    else:
                        logger.warning(f"⚠️ {symbol} 无历史数据")
                except Exception as e:
                    logger.error(f"❌ 获取 {symbol} 数据失败: {e}")
                    continue
            
            if not symbol_data:
                raise BacktestError("未能获取任何历史数据")
            
            # 获取所有时间戳并排序
            all_timestamps = set()
            for data in symbol_data.values():
                all_timestamps.update(data.index)
            
            sorted_timestamps = sorted(all_timestamps)
            
            # 按时间顺序执行回测
            processed_count = 0
            for timestamp in sorted_timestamps:
                self.current_time = timestamp
                
                # 为每个交易对执行策略
                for symbol, data in symbol_data.items():
                    if timestamp not in data.index:
                        continue
                    
                    try:
                        # 获取当前时间点的历史数据窗口
                        current_idx = data.index.get_loc(timestamp)
                        if current_idx < 50:  # 需要足够的历史数据
                            continue
                        
                        window_data = data.iloc[:current_idx + 1]
                        current_price = float(data.loc[timestamp, 'close'])
                        
                        # 执行趋势分析策略
                        signal_data = await self._analyze_with_strategy(
                            symbol, window_data, strategy_configs
                        )
                        
                        # 执行策略信号
                        if signal_data:
                            await self.execute_strategy_signal(
                                symbol, signal_data, window_data, current_price
                            )
                        
                        # 更新已有持仓
                        await self._update_position_stops(symbol, window_data, current_price)
                        
                    except Exception as e:
                        logger.error(f"❌ 处理 {symbol} 在 {timestamp} 时失败: {e}")
                        continue
                
                # 更新账户余额历史
                total_balance = self.balance + sum(
                    pos.unrealized_pnl for pos in self.positions.values()
                )
                self.balance_history.append((timestamp, total_balance))
                
                processed_count += 1
                if processed_count % 100 == 0:
                    logger.info(f"📈 已处理 {processed_count}/{len(sorted_timestamps)} 个时间点")
            
            # 强制平仓所有持仓
            for symbol in list(self.positions.keys()):
                await self._close_position(symbol, "backtest_end")
            
            # 计算最终指标
            metrics = self.calculate_metrics()
            
            # 生成详细报告
            report = await self._generate_detailed_report(metrics, symbol_data)
            
            logger.info(f"✅ 回测完成: 总交易 {metrics.total_trades} 笔, 胜率 {metrics.win_rate:.1%}, 总收益 {metrics.total_pnl_percent:.2f}%")
            
            return {
                "status": "success",
                "metrics": metrics,
                "trades": [self._trade_to_dict(trade) for trade in self.trades],
                "balance_history": self.balance_history,
                "positions_history": [],  # 可以记录持仓历史
                "report": report,
                "config": {
                    "symbols": symbols,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "initial_balance": initial_balance,
                    "interval": interval,
                    "commission_rate": self.commission_rate,
                    "slippage": self.slippage
                }
            }
            
        except Exception as e:
            logger.error(f"❌ 回测执行失败: {e}")
            raise BacktestError(f"回测执行失败: {str(e)}")
    
    async def _analyze_with_strategy(
        self,
        symbol: str,
        data: pd.DataFrame,
        strategy_configs: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """使用策略分析当前市场数据"""
        try:
            # 默认使用SuperTrend和ML增强分析
            configs = strategy_configs or {}
            
            # SuperTrend分析
            trend_result = await self.trend_service.analyze_symbol_with_data(symbol, data)
            
            # ML增强分析（如果启用）
            ml_result = None
            if configs.get('use_ml', True):
                try:
                    ml_result = await self.ml_service.enhanced_analysis(symbol, data)
                except Exception as e:
                    logger.warning(f"⚠️ ML分析失败 {symbol}: {e}")
            
            # 合并分析结果
            combined_signal = self._combine_signals(trend_result, ml_result, configs)
            
            return combined_signal
            
        except Exception as e:
            logger.error(f"❌ 策略分析失败 {symbol}: {e}")
            return None
    
    def _combine_signals(
        self,
        trend_result: Dict[str, Any],
        ml_result: Optional[Dict[str, Any]],
        configs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """合并多个策略信号"""
        try:
            # 基础信号来自趋势分析
            base_action = trend_result.get('action', 'hold')
            base_confidence = trend_result.get('confidence', 0.5)
            
            # ML增强权重
            ml_weight = configs.get('ml_weight', 0.3)
            trend_weight = 1.0 - ml_weight
            
            final_confidence = base_confidence * trend_weight
            final_action = base_action
            
            # 如果有ML结果，进行信号合并
            if ml_result:
                ml_action = ml_result.get('action', 'hold')
                ml_confidence = ml_result.get('confidence', 0.5)
                
                # 简单的信号合并逻辑
                if ml_action == base_action:
                    # 信号一致，增强置信度
                    final_confidence = min(base_confidence * trend_weight + ml_confidence * ml_weight, 1.0)
                elif ml_action == 'hold':
                    # ML建议持有，降低置信度
                    final_confidence = base_confidence * trend_weight
                else:
                    # 信号冲突，大幅降低置信度
                    final_confidence = base_confidence * trend_weight * 0.5
                    if final_confidence < 0.6:
                        final_action = 'hold'
            
            return {
                'action': final_action,
                'confidence': final_confidence,
                'risk_level': trend_result.get('risk_level', 'medium'),
                'signals': {
                    'trend': trend_result,
                    'ml': ml_result
                }
            }
            
        except Exception as e:
            logger.error(f"❌ 信号合并失败: {e}")
            return {
                'action': 'hold',
                'confidence': 0.0,
                'risk_level': 'high'
            }
    
    def _trade_to_dict(self, trade: BacktestTrade) -> Dict[str, Any]:
        """将交易记录转换为字典"""
        return {
            'trade_id': trade.trade_id,
            'symbol': trade.symbol,
            'side': trade.side,
            'entry_price': trade.entry_price,
            'exit_price': trade.exit_price,
            'quantity': trade.quantity,
            'pnl': trade.pnl,
            'pnl_percent': trade.pnl_percent,
            'entry_time': trade.entry_time.isoformat(),
            'exit_time': trade.exit_time.isoformat(),
            'duration_hours': trade.duration_hours,
            'commission': trade.commission,
            'reason': trade.reason,
            'strategy_signals': trade.strategy_signals
        }
    
    async def _generate_detailed_report(
        self,
        metrics: BacktestMetrics,
        symbol_data: Dict[str, pd.DataFrame]
    ) -> Dict[str, Any]:
        """生成详细的回测报告"""
        try:
            # 按交易对分析
            symbol_analysis = {}
            for symbol in symbol_data.keys():
                symbol_trades = [t for t in self.trades if t.symbol == symbol]
                if symbol_trades:
                    symbol_pnl = sum(t.pnl for t in symbol_trades)
                    symbol_win_rate = len([t for t in symbol_trades if t.pnl > 0]) / len(symbol_trades)
                    symbol_analysis[symbol] = {
                        'total_trades': len(symbol_trades),
                        'total_pnl': symbol_pnl,
                        'win_rate': symbol_win_rate,
                        'avg_trade_duration': np.mean([t.duration_hours for t in symbol_trades])
                    }
            
            # 按月度分析
            monthly_analysis = {}
            for trade in self.trades:
                month_key = trade.entry_time.strftime('%Y-%m')
                if month_key not in monthly_analysis:
                    monthly_analysis[month_key] = {'trades': 0, 'pnl': 0.0}
                monthly_analysis[month_key]['trades'] += 1
                monthly_analysis[month_key]['pnl'] += trade.pnl
            
            # 风险分析
            returns = []
            for i in range(1, len(self.balance_history)):
                prev_balance = self.balance_history[i-1][1]
                curr_balance = self.balance_history[i][1]
                if prev_balance > 0:
                    returns.append((curr_balance - prev_balance) / prev_balance)
            
            risk_metrics = {}
            if returns:
                returns_array = np.array(returns)
                risk_metrics = {
                    'volatility': np.std(returns_array) * np.sqrt(252),
                    'var_95': np.percentile(returns_array, 5),
                    'skewness': float(pd.Series(returns_array).skew()),
                    'kurtosis': float(pd.Series(returns_array).kurtosis())
                }
            
            return {
                'symbol_analysis': symbol_analysis,
                'monthly_analysis': monthly_analysis,
                'risk_metrics': risk_metrics,
                'summary': {
                    'total_return': metrics.total_pnl_percent,
                    'annual_return': self._calculate_annual_return(),
                    'max_drawdown': metrics.max_drawdown_percent,
                    'sharpe_ratio': metrics.sharpe_ratio,
                    'win_rate': metrics.win_rate
                }
            }
            
        except Exception as e:
            logger.error(f"❌ 生成报告失败: {e}")
            return {}
    
    def _calculate_annual_return(self) -> float:
        """计算年化收益率"""
        if not self.balance_history or len(self.balance_history) < 2:
            return 0.0
        
        start_balance = self.balance_history[0][1]
        end_balance = self.balance_history[-1][1]
        start_date = self.balance_history[0][0]
        end_date = self.balance_history[-1][0]
        
        days = (end_date - start_date).days
        if days == 0:
            return 0.0
        
        total_return = (end_balance - start_balance) / start_balance
        annual_return = (1 + total_return) ** (365.25 / days) - 1
        
        return annual_return * 100


class BacktestService:
    """回测服务主类"""
    
    def __init__(self):
        self.engine = BacktestEngine()
        self.results_cache = {}
    
    async def run_single_strategy_backtest(
        self,
        symbol: str,
        strategy_type: str = "supertrend",
        start_date: datetime = None,
        end_date: datetime = None,
        timeframe: str = "1h",
        initial_balance: float = 10000.0,
        strategy_params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """运行单一策略的回测"""
        try:
            # 设置默认日期
            if not end_date:
                end_date = datetime.now()
            if not start_date:
                start_date = end_date - timedelta(days=30)
            
            # 策略配置
            strategy_configs = {
                'strategy_type': strategy_type,
                'use_ml': strategy_params.get('use_ml', True) if strategy_params else True,
                'ml_weight': strategy_params.get('ml_weight', 0.3) if strategy_params else 0.3
            }
            
            # 运行回测
            results = await self.engine.run_backtest(
                symbols=[symbol],
                start_date=start_date,
                end_date=end_date,
                initial_balance=initial_balance,
                interval=timeframe,
                strategy_configs=strategy_configs
            )
            
            # 缓存结果
            cache_key = f"{symbol}_{strategy_type}_{start_date.date()}_{end_date.date()}"
            self.results_cache[cache_key] = results
            
            return results
            
        except Exception as e:
            logger.error(f"❌ 单一策略回测失败: {e}")
            raise BacktestError(f"回测失败: {str(e)}")
    
    async def run_multi_symbol_backtest(
        self,
        symbols: List[str],
        start_date: datetime = None,
        end_date: datetime = None,
        timeframe: str = "1h",
        initial_balance: float = 10000.0,
        strategy_configs: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """运行多交易对回测"""
        try:
            # 设置默认日期
            if not end_date:
                end_date = datetime.now()
            if not start_date:
                start_date = end_date - timedelta(days=30)
            
            # 运行回测
            results = await self.engine.run_backtest(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                initial_balance=initial_balance,
                interval=timeframe,
                strategy_configs=strategy_configs or {}
            )
            
            return results
            
        except Exception as e:
            logger.error(f"❌ 多交易对回测失败: {e}")
            raise BacktestError(f"回测失败: {str(e)}")
    
    async def compare_strategies(
        self,
        symbol: str,
        strategies: List[Dict[str, Any]],
        start_date: datetime = None,
        end_date: datetime = None,
        timeframe: str = "1h",
        initial_balance: float = 10000.0
    ) -> Dict[str, Any]:
        """比较多个策略的性能"""
        try:
            results = {}
            
            for strategy in strategies:
                strategy_name = strategy.get('name', 'unknown')
                try:
                    result = await self.run_single_strategy_backtest(
                        symbol=symbol,
                        strategy_type=strategy.get('type', 'supertrend'),
                        start_date=start_date,
                        end_date=end_date,
                        timeframe=timeframe,
                        initial_balance=initial_balance,
                        strategy_params=strategy.get('params', {})
                    )
                    results[strategy_name] = result
                except Exception as e:
                    logger.error(f"❌ 策略 {strategy_name} 回测失败: {e}")
                    results[strategy_name] = {'error': str(e)}
            
            # 生成策略比较报告
            comparison_report = self._generate_strategy_comparison(results)
            
            return {
                'individual_results': results,
                'comparison': comparison_report
            }
            
        except Exception as e:
            logger.error(f"❌ 策略比较失败: {e}")
            raise BacktestError(f"策略比较失败: {str(e)}")
    
    def _generate_strategy_comparison(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """生成策略比较报告"""
        try:
            comparison = {
                'summary': [],
                'rankings': {},
                'metrics_comparison': {}
            }
            
            valid_results = {k: v for k, v in results.items() if 'error' not in v}
            
            if not valid_results:
                return comparison
            
            # 提取关键指标
            metrics_keys = ['total_pnl_percent', 'win_rate', 'sharpe_ratio', 'max_drawdown_percent']
            
            for metric in metrics_keys:
                comparison['rankings'][metric] = []
                
                for strategy_name, result in valid_results.items():
                    metric_value = getattr(result.get('metrics'), metric, 0)
                    comparison['rankings'][metric].append({
                        'strategy': strategy_name,
                        'value': metric_value
                    })
                
                # 根据指标特性排序
                if metric == 'max_drawdown_percent':
                    comparison['rankings'][metric].sort(key=lambda x: x['value'])  # 最大回撤越小越好
                else:
                    comparison['rankings'][metric].sort(key=lambda x: x['value'], reverse=True)  # 其他指标越大越好
            
            # 生成总结
            best_return = max(valid_results.items(), key=lambda x: getattr(x[1].get('metrics'), 'total_pnl_percent', 0))
            best_sharpe = max(valid_results.items(), key=lambda x: getattr(x[1].get('metrics'), 'sharpe_ratio', 0))
            
            comparison['summary'] = {
                'best_return_strategy': best_return[0],
                'best_return_value': getattr(best_return[1].get('metrics'), 'total_pnl_percent', 0),
                'best_sharpe_strategy': best_sharpe[0],
                'best_sharpe_value': getattr(best_sharpe[1].get('metrics'), 'sharpe_ratio', 0),
                'total_strategies': len(valid_results)
            }
            
            return comparison
            
        except Exception as e:
            logger.error(f"❌ 生成策略比较报告失败: {e}")
            return {}
    
    def get_cached_results(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """获取缓存的回测结果"""
        return self.results_cache.get(cache_key)
    
    def clear_cache(self):
        """清空结果缓存"""
        self.results_cache.clear()
        logger.info("🗑️ 已清空回测结果缓存")