# -*- coding: utf-8 -*-
"""
完整回测服务
Complete Backtesting Service - 高级回测功能和策略优化
"""

from typing import Dict, Any, List, Optional, Tuple, Union, Callable
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
import asyncio
import numpy as np
import pandas as pd
from decimal import Decimal, ROUND_HALF_UP
import json
import itertools
from concurrent.futures import ThreadPoolExecutor
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import pickle

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.backtest_service import BacktestService, BacktestEngine, BacktestMetrics, BacktestTrade
from app.services.trend_analysis_service import TrendAnalysisService
from app.services.ml_enhanced_service import MLEnhancedService
from app.utils.indicators import SuperTrendIndicator, calculate_support_resistance
from app.utils.exceptions import TradingToolError, BacktestError

logger = get_logger(__name__)
settings = get_settings()


class OptimizationMethod(Enum):
    """优化方法"""
    GRID_SEARCH = "grid_search"
    RANDOM_SEARCH = "random_search"
    GENETIC_ALGORITHM = "genetic_algorithm"
    BAYESIAN_OPTIMIZATION = "bayesian_optimization"


class RiskMetric(Enum):
    """风险指标类型"""
    MAX_DRAWDOWN = "max_drawdown"
    SHARPE_RATIO = "sharpe_ratio"
    SORTINO_RATIO = "sortino_ratio"
    VAR_95 = "var_95"
    CALMAR_RATIO = "calmar_ratio"


@dataclass
class StrategyParameter:
    """策略参数定义"""
    name: str
    min_value: Union[int, float]
    max_value: Union[int, float]
    step: Union[int, float]
    param_type: type = float
    description: str = ""


@dataclass
class OptimizationResult:
    """优化结果"""
    best_params: Dict[str, Any]
    best_score: float
    optimization_metric: str
    all_results: List[Dict[str, Any]]
    optimization_time: float
    total_combinations: int


@dataclass
class RiskManagementConfig:
    """风险管理配置"""
    max_position_size: float = 0.1  # 最大仓位比例
    max_daily_drawdown: float = 0.05  # 最大日回撤
    max_total_drawdown: float = 0.20  # 最大总回撤
    position_size_method: str = "fixed"  # fixed, kelly, volatility
    stop_loss_method: str = "technical"  # fixed, technical, volatility
    take_profit_method: str = "technical"  # fixed, technical, risk_reward
    risk_reward_ratio: float = 2.0  # 风险收益比
    enable_position_sizing: bool = True
    enable_dynamic_stops: bool = True


@dataclass
class PortfolioConfig:
    """投资组合配置"""
    symbols: List[str]
    weights: Optional[Dict[str, float]] = None  # 权重分配
    rebalance_frequency: str = "weekly"  # daily, weekly, monthly
    max_correlation: float = 0.8  # 最大相关性
    min_symbols: int = 3  # 最少交易对数量
    max_symbols: int = 10  # 最多交易对数量


class AdvancedBacktestEngine(BacktestEngine):
    """高级回测引擎"""
    
    def __init__(self, risk_config: RiskManagementConfig = None):
        super().__init__()
        self.risk_config = risk_config or RiskManagementConfig()
        self.portfolio_history: List[Dict[str, Any]] = []
        self.risk_events: List[Dict[str, Any]] = []
        self.performance_attribution: Dict[str, Any] = {}
        
    async def run_portfolio_backtest(
        self,
        portfolio_config: PortfolioConfig,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float = 100000.0,
        interval: str = "1h",
        strategy_configs: Dict[str, Any] = None,
        rebalance_threshold: float = 0.05
    ) -> Dict[str, Any]:
        """运行投资组合回测"""
        try:
            logger.info(f"🚀 开始投资组合回测: {portfolio_config.symbols}")
            
            # 初始化回测
            await self.initialize_backtest(start_date, end_date, initial_balance, portfolio_config.symbols)
            
            # 获取所有交易对数据
            symbol_data = {}
            for symbol in portfolio_config.symbols:
                try:
                    data = await self.get_market_data(symbol, start_date, end_date, interval)
                    if not data.empty:
                        symbol_data[symbol] = data
                        logger.info(f"📊 已加载 {symbol} 数据: {len(data)} 条记录")
                except Exception as e:
                    logger.error(f"❌ 获取 {symbol} 数据失败: {e}")
                    continue
            
            if len(symbol_data) < portfolio_config.min_symbols:
                raise BacktestError(f"可用交易对不足，需要至少 {portfolio_config.min_symbols} 个")
            
            # 计算初始权重
            weights = self._calculate_portfolio_weights(portfolio_config, symbol_data)
            
            # 获取重新平衡时间点
            rebalance_dates = self._get_rebalance_dates(
                start_date, end_date, portfolio_config.rebalance_frequency
            )
            
            # 按时间顺序执行回测
            all_timestamps = self._get_all_timestamps(symbol_data)
            next_rebalance = 0
            
            for i, timestamp in enumerate(all_timestamps):
                self.current_time = timestamp
                
                # 检查是否需要重新平衡
                if (next_rebalance < len(rebalance_dates) and 
                    timestamp >= rebalance_dates[next_rebalance]):
                    
                    # 执行投资组合重新平衡
                    await self._rebalance_portfolio(
                        symbol_data, weights, timestamp, rebalance_threshold
                    )
                    next_rebalance += 1
                
                # 为每个交易对执行策略
                portfolio_value = await self._execute_portfolio_strategy(
                    symbol_data, weights, timestamp, strategy_configs
                )
                
                # 记录投资组合历史
                self.portfolio_history.append({
                    'timestamp': timestamp,
                    'total_value': portfolio_value,
                    'positions': dict(self.positions),
                    'weights': weights.copy()
                })
                
                # 风险检查
                await self._check_portfolio_risk(portfolio_value)
                
                if i % 100 == 0:
                    logger.info(f"📈 已处理 {i}/{len(all_timestamps)} 个时间点")
            
            # 计算投资组合指标
            portfolio_metrics = await self._calculate_portfolio_metrics()
            
            # 生成投资组合报告
            portfolio_report = await self._generate_portfolio_report(
                portfolio_metrics, symbol_data, portfolio_config
            )
            
            logger.info(f"✅ 投资组合回测完成")
            
            return {
                "status": "success",
                "portfolio_metrics": portfolio_metrics,
                "individual_metrics": self.calculate_metrics(),
                "portfolio_history": self.portfolio_history,
                "risk_events": self.risk_events,
                "performance_attribution": self.performance_attribution,
                "trades": [self._trade_to_dict(trade) for trade in self.trades],
                "report": portfolio_report,
                "config": {
                    "portfolio_config": portfolio_config.__dict__,
                    "risk_config": self.risk_config.__dict__,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "initial_balance": initial_balance
                }
            }
            
        except Exception as e:
            logger.error(f"❌ 投资组合回测失败: {e}")
            raise BacktestError(f"投资组合回测失败: {str(e)}")
    
    def _calculate_portfolio_weights(
        self,
        portfolio_config: PortfolioConfig,
        symbol_data: Dict[str, pd.DataFrame]
    ) -> Dict[str, float]:
        """计算投资组合权重"""
        try:
            if portfolio_config.weights:
                # 使用指定权重
                return portfolio_config.weights
            
            # 等权重分配
            num_symbols = len(symbol_data)
            equal_weight = 1.0 / num_symbols
            
            weights = {}
            for symbol in symbol_data.keys():
                weights[symbol] = equal_weight
            
            return weights
            
        except Exception as e:
            logger.error(f"❌ 计算投资组合权重失败: {e}")
            # 返回等权重
            num_symbols = len(symbol_data)
            return {symbol: 1.0/num_symbols for symbol in symbol_data.keys()}
    
    def _get_rebalance_dates(
        self,
        start_date: datetime,
        end_date: datetime,
        frequency: str
    ) -> List[datetime]:
        """获取重新平衡日期"""
        rebalance_dates = []
        current = start_date
        
        if frequency == "daily":
            delta = timedelta(days=1)
        elif frequency == "weekly":
            delta = timedelta(weeks=1)
        elif frequency == "monthly":
            delta = timedelta(days=30)
        else:
            delta = timedelta(weeks=1)  # 默认周频率
        
        while current <= end_date:
            rebalance_dates.append(current)
            current += delta
        
        return rebalance_dates
    
    def _get_all_timestamps(self, symbol_data: Dict[str, pd.DataFrame]) -> List[datetime]:
        """获取所有时间戳并排序"""
        all_timestamps = set()
        for data in symbol_data.values():
            all_timestamps.update(data.index)
        return sorted(all_timestamps)
    
    async def _rebalance_portfolio(
        self,
        symbol_data: Dict[str, pd.DataFrame],
        weights: Dict[str, float],
        timestamp: datetime,
        threshold: float
    ):
        """重新平衡投资组合"""
        try:
            # 计算当前投资组合价值
            total_value = self.balance
            for symbol, position in self.positions.items():
                if timestamp in symbol_data[symbol].index:
                    current_price = float(symbol_data[symbol].loc[timestamp, 'close'])
                    position_value = position.size * current_price
                    total_value += position_value
            
            # 计算目标仓位
            target_positions = {}
            for symbol, weight in weights.items():
                if timestamp in symbol_data[symbol].index:
                    current_price = float(symbol_data[symbol].loc[timestamp, 'close'])
                    target_value = total_value * weight
                    target_size = target_value / current_price
                    target_positions[symbol] = target_size
            
            # 执行重新平衡
            for symbol, target_size in target_positions.items():
                current_position = self.positions.get(symbol)
                current_size = current_position.size if current_position else 0.0
                
                # 计算差额
                size_diff = target_size - current_size
                
                # 检查是否超过重新平衡阈值
                if abs(size_diff) / target_size > threshold:
                    if size_diff > 0:
                        # 需要买入
                        await self._create_market_order(
                            symbol=symbol,
                            side="buy",
                            quantity=size_diff,
                            price=float(symbol_data[symbol].loc[timestamp, 'close'])
                        )
                    else:
                        # 需要卖出
                        await self._create_market_order(
                            symbol=symbol,
                            side="sell",
                            quantity=abs(size_diff),
                            price=float(symbol_data[symbol].loc[timestamp, 'close'])
                        )
            
            logger.info(f"🔄 投资组合重新平衡完成: {timestamp}")
            
        except Exception as e:
            logger.error(f"❌ 重新平衡失败: {e}")
    
    async def _execute_portfolio_strategy(
        self,
        symbol_data: Dict[str, pd.DataFrame],
        weights: Dict[str, float],
        timestamp: datetime,
        strategy_configs: Dict[str, Any]
    ) -> float:
        """执行投资组合策略"""
        try:
            total_value = self.balance
            
            for symbol in symbol_data.keys():
                if timestamp not in symbol_data[symbol].index:
                    continue
                
                try:
                    # 获取历史数据窗口
                    current_idx = symbol_data[symbol].index.get_loc(timestamp)
                    if current_idx < 50:
                        continue
                    
                    window_data = symbol_data[symbol].iloc[:current_idx + 1]
                    current_price = float(symbol_data[symbol].loc[timestamp, 'close'])
                    
                    # 执行策略分析
                    signal_data = await self._analyze_with_strategy(
                        symbol, window_data, strategy_configs
                    )
                    
                    # 调整信号强度（基于投资组合权重）
                    if signal_data:
                        symbol_weight = weights.get(symbol, 0.0)
                        signal_data['confidence'] *= symbol_weight
                        
                        # 执行策略信号
                        await self.execute_strategy_signal(
                            symbol, signal_data, window_data, current_price
                        )
                    
                    # 更新持仓止损止盈
                    await self._update_position_stops(symbol, window_data, current_price)
                    
                    # 累计投资组合价值
                    position = self.positions.get(symbol)
                    if position:
                        total_value += position.size * current_price
                    
                except Exception as e:
                    logger.error(f"❌ 处理 {symbol} 策略失败: {e}")
                    continue
            
            return total_value
            
        except Exception as e:
            logger.error(f"❌ 执行投资组合策略失败: {e}")
            return self.balance
    
    async def _check_portfolio_risk(self, portfolio_value: float):
        """检查投资组合风险"""
        try:
            # 计算当前回撤
            if self.portfolio_history:
                peak_value = max(h['total_value'] for h in self.portfolio_history)
                current_drawdown = (peak_value - portfolio_value) / peak_value
                
                # 检查最大回撤限制
                if current_drawdown > self.risk_config.max_total_drawdown:
                    # 触发风险控制，强制平仓
                    await self._emergency_liquidation("max_drawdown_exceeded")
                    
                    self.risk_events.append({
                        'timestamp': self.current_time,
                        'event_type': 'max_drawdown_exceeded',
                        'drawdown': current_drawdown,
                        'action': 'emergency_liquidation'
                    })
                    
                    logger.warning(f"⚠️ 触发最大回撤风控: {current_drawdown:.2%}")
            
            # 检查日回撤
            if len(self.portfolio_history) >= 24:  # 24小时数据
                daily_start_value = self.portfolio_history[-24]['total_value']
                daily_drawdown = (daily_start_value - portfolio_value) / daily_start_value
                
                if daily_drawdown > self.risk_config.max_daily_drawdown:
                    # 暂停交易
                    self.risk_events.append({
                        'timestamp': self.current_time,
                        'event_type': 'daily_drawdown_exceeded',
                        'drawdown': daily_drawdown,
                        'action': 'trading_suspended'
                    })
                    
                    logger.warning(f"⚠️ 触发日回撤风控: {daily_drawdown:.2%}")
            
        except Exception as e:
            logger.error(f"❌ 风险检查失败: {e}")
    
    async def _emergency_liquidation(self, reason: str):
        """紧急清仓"""
        try:
            logger.warning(f"🚨 执行紧急清仓: {reason}")
            
            for symbol in list(self.positions.keys()):
                await self._close_position(symbol, f"emergency_{reason}")
            
        except Exception as e:
            logger.error(f"❌ 紧急清仓失败: {e}")
    
    async def _calculate_portfolio_metrics(self) -> Dict[str, Any]:
        """计算投资组合指标"""
        try:
            if not self.portfolio_history:
                return {}
            
            # 提取投资组合价值序列
            values = [h['total_value'] for h in self.portfolio_history]
            timestamps = [h['timestamp'] for h in self.portfolio_history]
            
            # 计算收益率序列
            returns = []
            for i in range(1, len(values)):
                ret = (values[i] - values[i-1]) / values[i-1]
                returns.append(ret)
            
            returns_array = np.array(returns)
            
            # 基础指标
            total_return = (values[-1] - values[0]) / values[0]
            annualized_return = (1 + total_return) ** (252 / len(values)) - 1
            
            # 波动率
            volatility = np.std(returns_array) * np.sqrt(252)
            
            # 最大回撤
            max_drawdown = 0
            peak = values[0]
            for value in values:
                if value > peak:
                    peak = value
                drawdown = (peak - value) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
            
            # 夏普比率
            sharpe_ratio = (np.mean(returns_array) * 252) / (np.std(returns_array) * np.sqrt(252)) if np.std(returns_array) > 0 else 0
            
            # Sortino比率
            negative_returns = returns_array[returns_array < 0]
            downside_deviation = np.std(negative_returns) * np.sqrt(252) if len(negative_returns) > 0 else 0
            sortino_ratio = (np.mean(returns_array) * 252) / downside_deviation if downside_deviation > 0 else 0
            
            # Calmar比率
            calmar_ratio = annualized_return / max_drawdown if max_drawdown > 0 else 0
            
            # VaR和CVaR
            var_95 = np.percentile(returns_array, 5)
            cvar_95 = np.mean(returns_array[returns_array <= var_95])
            
            # 胜率统计
            positive_returns = len(returns_array[returns_array > 0])
            win_rate = positive_returns / len(returns_array) if len(returns_array) > 0 else 0
            
            return {
                'total_return': total_return,
                'annualized_return': annualized_return,
                'volatility': volatility,
                'max_drawdown': max_drawdown,
                'sharpe_ratio': sharpe_ratio,
                'sortino_ratio': sortino_ratio,
                'calmar_ratio': calmar_ratio,
                'var_95': var_95,
                'cvar_95': cvar_95,
                'win_rate': win_rate,
                'total_periods': len(values),
                'risk_events_count': len(self.risk_events),
                'start_value': values[0],
                'end_value': values[-1],
                'peak_value': max(values)
            }
            
        except Exception as e:
            logger.error(f"❌ 计算投资组合指标失败: {e}")
            return {}
    
    async def _generate_portfolio_report(
        self,
        portfolio_metrics: Dict[str, Any],
        symbol_data: Dict[str, pd.DataFrame],
        portfolio_config: PortfolioConfig
    ) -> Dict[str, Any]:
        """生成投资组合报告"""
        try:
            # 按交易对贡献分析
            symbol_contribution = {}
            for symbol in symbol_data.keys():
                symbol_trades = [t for t in self.trades if t.symbol == symbol]
                if symbol_trades:
                    symbol_pnl = sum(t.pnl for t in symbol_trades)
                    symbol_contribution[symbol] = {
                        'total_pnl': symbol_pnl,
                        'trade_count': len(symbol_trades),
                        'contribution_percent': symbol_pnl / portfolio_metrics.get('total_return', 1) * 100
                    }
            
            # 风险分析
            risk_analysis = {
                'risk_events': self.risk_events,
                'max_drawdown_periods': self._analyze_drawdown_periods(),
                'correlation_analysis': await self._analyze_correlations(symbol_data),
                'position_concentration': self._analyze_position_concentration()
            }
            
            # 时间序列分析
            time_series_analysis = {
                'monthly_returns': self._calculate_monthly_returns(),
                'rolling_metrics': self._calculate_rolling_metrics(),
                'performance_periods': self._analyze_performance_periods()
            }
            
            return {
                'summary': portfolio_metrics,
                'symbol_contribution': symbol_contribution,
                'risk_analysis': risk_analysis,
                'time_series_analysis': time_series_analysis,
                'portfolio_composition': {
                    'symbols': list(symbol_data.keys()),
                    'weights': portfolio_config.weights,
                    'rebalance_frequency': portfolio_config.rebalance_frequency
                }
            }
            
        except Exception as e:
            logger.error(f"❌ 生成投资组合报告失败: {e}")
            return {}
    
    def _analyze_drawdown_periods(self) -> List[Dict[str, Any]]:
        """分析回撤期间"""
        if not self.portfolio_history:
            return []
        
        values = [h['total_value'] for h in self.portfolio_history]
        timestamps = [h['timestamp'] for h in self.portfolio_history]
        
        drawdown_periods = []
        peak_value = values[0]
        peak_time = timestamps[0]
        in_drawdown = False
        drawdown_start = None
        
        for i, (value, timestamp) in enumerate(zip(values, timestamps)):
            if value > peak_value:
                if in_drawdown:
                    # 回撤结束
                    drawdown_periods.append({
                        'start': drawdown_start,
                        'end': timestamp,
                        'duration_days': (timestamp - drawdown_start).days,
                        'max_drawdown': (peak_value - min(values[peak_idx:i])) / peak_value,
                        'recovery_time': (timestamp - peak_time).days
                    })
                    in_drawdown = False
                
                peak_value = value
                peak_time = timestamp
                peak_idx = i
            elif not in_drawdown and value < peak_value * 0.99:  # 1%以上回撤才记录
                in_drawdown = True
                drawdown_start = timestamp
        
        return drawdown_periods
    
    async def _analyze_correlations(self, symbol_data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """分析交易对相关性"""
        try:
            # 计算收益率相关性矩阵
            returns_data = {}
            
            for symbol, data in symbol_data.items():
                returns = data['close'].pct_change().dropna()
                returns_data[symbol] = returns
            
            if len(returns_data) < 2:
                return {}
            
            # 创建收益率DataFrame
            returns_df = pd.DataFrame(returns_data)
            correlation_matrix = returns_df.corr()
            
            # 找出高相关性对
            high_correlations = []
            symbols = list(returns_data.keys())
            
            for i in range(len(symbols)):
                for j in range(i+1, len(symbols)):
                    corr = correlation_matrix.loc[symbols[i], symbols[j]]
                    if abs(corr) > 0.7:  # 高相关性阈值
                        high_correlations.append({
                            'pair': f"{symbols[i]}-{symbols[j]}",
                            'correlation': corr
                        })
            
            return {
                'correlation_matrix': correlation_matrix.to_dict(),
                'high_correlations': high_correlations,
                'average_correlation': correlation_matrix.values[np.triu_indices_from(correlation_matrix.values, k=1)].mean()
            }
            
        except Exception as e:
            logger.error(f"❌ 相关性分析失败: {e}")
            return {}
    
    def _analyze_position_concentration(self) -> Dict[str, Any]:
        """分析仓位集中度"""
        if not self.portfolio_history:
            return {}
        
        # 计算平均仓位集中度
        concentration_scores = []
        
        for record in self.portfolio_history:
            positions = record.get('positions', {})
            if positions:
                # 计算Herfindahl指数（集中度指标）
                total_value = sum(pos.size * pos.current_price for pos in positions.values())
                if total_value > 0:
                    weights_squared = [(pos.size * pos.current_price / total_value) ** 2 for pos in positions.values()]
                    herfindahl_index = sum(weights_squared)
                    concentration_scores.append(herfindahl_index)
        
        if concentration_scores:
            return {
                'average_concentration': np.mean(concentration_scores),
                'max_concentration': max(concentration_scores),
                'concentration_trend': 'increasing' if concentration_scores[-1] > concentration_scores[0] else 'decreasing'
            }
        
        return {}
    
    def _calculate_monthly_returns(self) -> Dict[str, float]:
        """计算月度收益率"""
        if not self.portfolio_history:
            return {}
        
        monthly_returns = {}
        
        # 按月分组
        monthly_data = {}
        for record in self.portfolio_history:
            month_key = record['timestamp'].strftime('%Y-%m')
            if month_key not in monthly_data:
                monthly_data[month_key] = []
            monthly_data[month_key].append(record['total_value'])
        
        # 计算每月收益率
        for month, values in monthly_data.items():
            if len(values) > 1:
                monthly_return = (values[-1] - values[0]) / values[0]
                monthly_returns[month] = monthly_return
        
        return monthly_returns
    
    def _calculate_rolling_metrics(self, window_days: int = 30) -> Dict[str, List[float]]:
        """计算滚动指标"""
        if not self.portfolio_history or len(self.portfolio_history) < window_days:
            return {}
        
        values = [h['total_value'] for h in self.portfolio_history]
        
        rolling_sharpe = []
        rolling_volatility = []
        rolling_max_drawdown = []
        
        for i in range(window_days, len(values)):
            window_values = values[i-window_days:i]
            
            # 计算收益率
            returns = [(window_values[j] - window_values[j-1]) / window_values[j-1] 
                      for j in range(1, len(window_values))]
            
            if returns:
                # 滚动夏普比率
                mean_return = np.mean(returns)
                std_return = np.std(returns)
                sharpe = (mean_return / std_return) * np.sqrt(252) if std_return > 0 else 0
                rolling_sharpe.append(sharpe)
                
                # 滚动波动率
                volatility = std_return * np.sqrt(252)
                rolling_volatility.append(volatility)
                
                # 滚动最大回撤
                peak = max(window_values)
                trough = min(window_values)
                max_dd = (peak - trough) / peak if peak > 0 else 0
                rolling_max_drawdown.append(max_dd)
        
        return {
            'rolling_sharpe': rolling_sharpe,
            'rolling_volatility': rolling_volatility,
            'rolling_max_drawdown': rolling_max_drawdown
        }
    
    def _analyze_performance_periods(self) -> Dict[str, Any]:
        """分析不同时期的表现"""
        if not self.portfolio_history:
            return {}
        
        # 按季度分析
        quarterly_performance = {}
        
        for record in self.portfolio_history:
            quarter_key = f"{record['timestamp'].year}-Q{(record['timestamp'].month-1)//3 + 1}"
            if quarter_key not in quarterly_performance:
                quarterly_performance[quarter_key] = []
            quarterly_performance[quarter_key].append(record['total_value'])
        
        # 计算每季度表现
        quarterly_results = {}
        for quarter, values in quarterly_performance.items():
            if len(values) > 1:
                quarterly_return = (values[-1] - values[0]) / values[0]
                quarterly_results[quarter] = {
                    'return': quarterly_return,
                    'volatility': np.std([(values[i] - values[i-1]) / values[i-1] 
                                        for i in range(1, len(values))]) if len(values) > 1 else 0
                }
        
        return {
            'quarterly_performance': quarterly_results,
            'best_quarter': max(quarterly_results.items(), key=lambda x: x[1]['return']) if quarterly_results else None,
            'worst_quarter': min(quarterly_results.items(), key=lambda x: x[1]['return']) if quarterly_results else None
        }


class StrategyOptimizer:
    """策略优化器"""
    
    def __init__(self, backtest_engine: AdvancedBacktestEngine):
        self.engine = backtest_engine
        self.optimization_results: List[OptimizationResult] = []
    
    async def optimize_strategy(
        self,
        symbol: str,
        strategy_parameters: List[StrategyParameter],
        start_date: datetime,
        end_date: datetime,
        optimization_method: OptimizationMethod = OptimizationMethod.GRID_SEARCH,
        optimization_metric: str = "sharpe_ratio",
        max_iterations: int = 1000,
        initial_balance: float = 10000.0
    ) -> OptimizationResult:
        """优化策略参数"""
        try:
            start_time = datetime.now()
            logger.info(f"🎯 开始策略优化: {symbol} ({optimization_method.value})")
            
            if optimization_method == OptimizationMethod.GRID_SEARCH:
                result = await self._grid_search_optimization(
                    symbol, strategy_parameters, start_date, end_date,
                    optimization_metric, initial_balance
                )
            elif optimization_method == OptimizationMethod.RANDOM_SEARCH:
                result = await self._random_search_optimization(
                    symbol, strategy_parameters, start_date, end_date,
                    optimization_metric, max_iterations, initial_balance
                )
            elif optimization_method == OptimizationMethod.GENETIC_ALGORITHM:
                result = await self._genetic_algorithm_optimization(
                    symbol, strategy_parameters, start_date, end_date,
                    optimization_metric, max_iterations, initial_balance
                )
            else:
                raise BacktestError(f"不支持的优化方法: {optimization_method}")
            
            optimization_time = (datetime.now() - start_time).total_seconds()
            result.optimization_time = optimization_time
            
            self.optimization_results.append(result)
            
            logger.info(f"✅ 策略优化完成，最佳得分: {result.best_score:.4f}")
            return result
            
        except Exception as e:
            logger.error(f"❌ 策略优化失败: {e}")
            raise BacktestError(f"策略优化失败: {str(e)}")
    
    async def _grid_search_optimization(
        self,
        symbol: str,
        parameters: List[StrategyParameter],
        start_date: datetime,
        end_date: datetime,
        metric: str,
        initial_balance: float
    ) -> OptimizationResult:
        """网格搜索优化"""
        try:
            # 生成参数组合
            param_ranges = []
            for param in parameters:
                if param.param_type == int:
                    values = list(range(int(param.min_value), int(param.max_value) + 1, int(param.step)))
                else:
                    values = np.arange(param.min_value, param.max_value + param.step, param.step).tolist()
                param_ranges.append(values)
            
            all_combinations = list(itertools.product(*param_ranges))
            total_combinations = len(all_combinations)
            
            logger.info(f"📊 网格搜索: {total_combinations} 种参数组合")
            
            # 并行执行回测
            results = []
            batch_size = min(10, total_combinations)  # 批量处理以控制内存使用
            
            for i in range(0, total_combinations, batch_size):
                batch_combinations = all_combinations[i:i+batch_size]
                batch_results = await self._run_batch_backtests(
                    symbol, parameters, batch_combinations, start_date, end_date, initial_balance
                )
                results.extend(batch_results)
                
                logger.info(f"📈 已完成 {min(i+batch_size, total_combinations)}/{total_combinations} 组合")
            
            # 找到最佳结果
            best_result = max(results, key=lambda x: x.get(metric, 0))
            
            return OptimizationResult(
                best_params=best_result['params'],
                best_score=best_result.get(metric, 0),
                optimization_metric=metric,
                all_results=results,
                optimization_time=0,  # 将在调用函数中设置
                total_combinations=total_combinations
            )
            
        except Exception as e:
            logger.error(f"❌ 网格搜索优化失败: {e}")
            raise
    
    async def _random_search_optimization(
        self,
        symbol: str,
        parameters: List[StrategyParameter],
        start_date: datetime,
        end_date: datetime,
        metric: str,
        max_iterations: int,
        initial_balance: float
    ) -> OptimizationResult:
        """随机搜索优化"""
        try:
            logger.info(f"🎲 随机搜索: {max_iterations} 次迭代")
            
            results = []
            
            for i in range(max_iterations):
                # 随机生成参数组合
                random_params = []
                for param in parameters:
                    if param.param_type == int:
                        value = np.random.randint(param.min_value, param.max_value + 1)
                    else:
                        value = np.random.uniform(param.min_value, param.max_value)
                    random_params.append(value)
                
                # 执行回测
                param_dict = {param.name: value for param, value in zip(parameters, random_params)}
                
                try:
                    backtest_result = await self._run_single_backtest(
                        symbol, param_dict, start_date, end_date, initial_balance
                    )
                    backtest_result['params'] = param_dict
                    results.append(backtest_result)
                    
                except Exception as e:
                    logger.warning(f"⚠️ 回测失败 (第{i+1}次): {e}")
                    continue
                
                if (i + 1) % 100 == 0:
                    logger.info(f"📈 已完成 {i+1}/{max_iterations} 次迭代")
            
            if not results:
                raise BacktestError("没有成功的回测结果")
            
            # 找到最佳结果
            best_result = max(results, key=lambda x: x.get(metric, 0))
            
            return OptimizationResult(
                best_params=best_result['params'],
                best_score=best_result.get(metric, 0),
                optimization_metric=metric,
                all_results=results,
                optimization_time=0,
                total_combinations=max_iterations
            )
            
        except Exception as e:
            logger.error(f"❌ 随机搜索优化失败: {e}")
            raise
    
    async def _genetic_algorithm_optimization(
        self,
        symbol: str,
        parameters: List[StrategyParameter],
        start_date: datetime,
        end_date: datetime,
        metric: str,
        max_generations: int,
        initial_balance: float,
        population_size: int = 50,
        mutation_rate: float = 0.1
    ) -> OptimizationResult:
        """遗传算法优化"""
        try:
            logger.info(f"🧬 遗传算法优化: {max_generations} 代，种群大小 {population_size}")
            
            # 初始化种群
            population = []
            for _ in range(population_size):
                individual = []
                for param in parameters:
                    if param.param_type == int:
                        value = np.random.randint(param.min_value, param.max_value + 1)
                    else:
                        value = np.random.uniform(param.min_value, param.max_value)
                    individual.append(value)
                population.append(individual)
            
            all_results = []
            best_scores = []
            
            for generation in range(max_generations):
                # 评估种群
                generation_results = []
                
                for individual in population:
                    param_dict = {param.name: value for param, value in zip(parameters, individual)}
                    
                    try:
                        result = await self._run_single_backtest(
                            symbol, param_dict, start_date, end_date, initial_balance
                        )
                        result['params'] = param_dict
                        result['individual'] = individual
                        generation_results.append(result)
                        
                    except Exception as e:
                        # 对于失败的个体，给予很低的得分
                        result = {
                            'params': param_dict,
                            'individual': individual,
                            metric: -999999
                        }
                        generation_results.append(result)
                
                all_results.extend(generation_results)
                
                # 选择最佳个体
                generation_results.sort(key=lambda x: x.get(metric, -999999), reverse=True)
                best_scores.append(generation_results[0].get(metric, -999999))
                
                # 选择、交叉、变异生成下一代
                if generation < max_generations - 1:
                    population = self._evolve_population(
                        generation_results, parameters, population_size, mutation_rate
                    )
                
                logger.info(f"🧬 第 {generation+1} 代完成，最佳得分: {best_scores[-1]:.4f}")
            
            # 找到全局最佳结果
            best_result = max(all_results, key=lambda x: x.get(metric, -999999))
            
            return OptimizationResult(
                best_params=best_result['params'],
                best_score=best_result.get(metric, 0),
                optimization_metric=metric,
                all_results=all_results,
                optimization_time=0,
                total_combinations=len(all_results)
            )
            
        except Exception as e:
            logger.error(f"❌ 遗传算法优化失败: {e}")
            raise
    
    def _evolve_population(
        self,
        evaluated_population: List[Dict[str, Any]],
        parameters: List[StrategyParameter],
        population_size: int,
        mutation_rate: float
    ) -> List[List[float]]:
        """进化种群"""
        # 选择top 50%作为父代
        parents = evaluated_population[:population_size // 2]
        new_population = []
        
        # 保留最佳个体（精英策略）
        elite_count = max(1, population_size // 10)
        for i in range(elite_count):
            new_population.append(parents[i]['individual'])
        
        # 生成子代
        while len(new_population) < population_size:
            # 随机选择两个父代
            parent1 = np.random.choice(len(parents))
            parent2 = np.random.choice(len(parents))
            
            # 交叉
            child = self._crossover(
                parents[parent1]['individual'],
                parents[parent2]['individual']
            )
            
            # 变异
            child = self._mutate(child, parameters, mutation_rate)
            
            new_population.append(child)
        
        return new_population
    
    def _crossover(self, parent1: List[float], parent2: List[float]) -> List[float]:
        """交叉操作"""
        crossover_point = np.random.randint(1, len(parent1))
        child = parent1[:crossover_point] + parent2[crossover_point:]
        return child
    
    def _mutate(
        self,
        individual: List[float],
        parameters: List[StrategyParameter],
        mutation_rate: float
    ) -> List[float]:
        """变异操作"""
        mutated = individual.copy()
        
        for i in range(len(mutated)):
            if np.random.random() < mutation_rate:
                param = parameters[i]
                if param.param_type == int:
                    mutated[i] = np.random.randint(param.min_value, param.max_value + 1)
                else:
                    mutated[i] = np.random.uniform(param.min_value, param.max_value)
        
        return mutated
    
    async def _run_batch_backtests(
        self,
        symbol: str,
        parameters: List[StrategyParameter],
        combinations: List[Tuple],
        start_date: datetime,
        end_date: datetime,
        initial_balance: float
    ) -> List[Dict[str, Any]]:
        """批量运行回测"""
        results = []
        
        for combination in combinations:
            param_dict = {param.name: value for param, value in zip(parameters, combination)}
            
            try:
                result = await self._run_single_backtest(
                    symbol, param_dict, start_date, end_date, initial_balance
                )
                result['params'] = param_dict
                results.append(result)
                
            except Exception as e:
                logger.warning(f"⚠️ 回测失败 {param_dict}: {e}")
                continue
        
        return results
    
    async def _run_single_backtest(
        self,
        symbol: str,
        params: Dict[str, Any],
        start_date: datetime,
        end_date: datetime,
        initial_balance: float
    ) -> Dict[str, Any]:
        """运行单次回测"""
        try:
            # 创建新的回测引擎实例
            engine = AdvancedBacktestEngine()
            
            # 设置策略参数
            strategy_configs = {
                'strategy_type': 'supertrend',
                'use_ml': False,  # 优化时暂时关闭ML以提高速度
                **params
            }
            
            # 运行回测
            result = await engine.run_backtest(
                symbols=[symbol],
                start_date=start_date,
                end_date=end_date,
                initial_balance=initial_balance,
                interval="1h",
                strategy_configs=strategy_configs
            )
            
            # 提取关键指标
            metrics = result.get('metrics')
            if not metrics:
                return {'sharpe_ratio': -999999, 'total_pnl_percent': -999999}
            
            return {
                'sharpe_ratio': getattr(metrics, 'sharpe_ratio', 0),
                'total_pnl_percent': getattr(metrics, 'total_pnl_percent', 0),
                'max_drawdown_percent': getattr(metrics, 'max_drawdown_percent', 100),
                'win_rate': getattr(metrics, 'win_rate', 0),
                'total_trades': getattr(metrics, 'total_trades', 0),
                'profit_factor': getattr(metrics, 'profit_factor', 0)
            }
            
        except Exception as e:
            logger.error(f"❌ 单次回测失败: {e}")
            return {'sharpe_ratio': -999999, 'total_pnl_percent': -999999}


class CompleteBacktestService:
    """完整回测服务"""
    
    def __init__(self):
        self.basic_service = BacktestService()
        self.advanced_engine = AdvancedBacktestEngine()
        self.optimizer = StrategyOptimizer(self.advanced_engine)
        self.visualization_enabled = True
    
    async def run_comprehensive_backtest(
        self,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """运行综合回测"""
        try:
            backtest_type = config.get('type', 'single')
            
            if backtest_type == 'single':
                return await self._run_single_symbol_comprehensive(config)
            elif backtest_type == 'portfolio':
                return await self._run_portfolio_comprehensive(config)
            elif backtest_type == 'optimization':
                return await self._run_optimization_comprehensive(config)
            elif backtest_type == 'strategy_comparison':
                return await self._run_strategy_comparison_comprehensive(config)
            else:
                raise BacktestError(f"不支持的回测类型: {backtest_type}")
                
        except Exception as e:
            logger.error(f"❌ 综合回测失败: {e}")
            raise BacktestError(f"综合回测失败: {str(e)}")
    
    async def _run_single_symbol_comprehensive(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """运行单交易对综合回测"""
        symbol = config['symbol']
        start_date = datetime.fromisoformat(config['start_date'])
        end_date = datetime.fromisoformat(config['end_date'])
        
        # 运行基础回测
        basic_result = await self.basic_service.run_single_strategy_backtest(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            **config.get('basic_params', {})
        )
        
        # 运行高级分析
        risk_config = RiskManagementConfig(**config.get('risk_config', {}))
        advanced_engine = AdvancedBacktestEngine(risk_config)
        
        advanced_result = await advanced_engine.run_backtest(
            symbols=[symbol],
            start_date=start_date,
            end_date=end_date,
            **config.get('advanced_params', {})
        )
        
        # 生成可视化
        if self.visualization_enabled:
            charts = await self._generate_charts(basic_result, advanced_result)
        else:
            charts = {}
        
        return {
            'type': 'single_comprehensive',
            'basic_result': basic_result,
            'advanced_result': advanced_result,
            'charts': charts,
            'recommendations': self._generate_recommendations(basic_result, advanced_result)
        }
    
    async def _run_portfolio_comprehensive(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """运行投资组合综合回测"""
        portfolio_config = PortfolioConfig(**config['portfolio_config'])
        risk_config = RiskManagementConfig(**config.get('risk_config', {}))
        
        advanced_engine = AdvancedBacktestEngine(risk_config)
        
        result = await advanced_engine.run_portfolio_backtest(
            portfolio_config=portfolio_config,
            start_date=datetime.fromisoformat(config['start_date']),
            end_date=datetime.fromisoformat(config['end_date']),
            **config.get('params', {})
        )
        
        # 生成投资组合特定的可视化
        if self.visualization_enabled:
            charts = await self._generate_portfolio_charts(result)
        else:
            charts = {}
        
        return {
            'type': 'portfolio_comprehensive',
            'result': result,
            'charts': charts,
            'recommendations': self._generate_portfolio_recommendations(result)
        }
    
    async def _run_optimization_comprehensive(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """运行策略优化综合回测"""
        symbol = config['symbol']
        
        # 定义优化参数
        parameters = []
        for param_config in config['parameters']:
            parameters.append(StrategyParameter(**param_config))
        
        # 运行优化
        optimization_result = await self.optimizer.optimize_strategy(
            symbol=symbol,
            strategy_parameters=parameters,
            start_date=datetime.fromisoformat(config['start_date']),
            end_date=datetime.fromisoformat(config['end_date']),
            optimization_method=OptimizationMethod(config.get('method', 'grid_search')),
            **config.get('optimization_params', {})
        )
        
        # 使用最佳参数运行详细回测
        best_params_result = await self.basic_service.run_single_strategy_backtest(
            symbol=symbol,
            start_date=datetime.fromisoformat(config['start_date']),
            end_date=datetime.fromisoformat(config['end_date']),
            strategy_params=optimization_result.best_params,
            **config.get('backtest_params', {})
        )
        
        # 生成优化结果可视化
        if self.visualization_enabled:
            charts = await self._generate_optimization_charts(optimization_result)
        else:
            charts = {}
        
        return {
            'type': 'optimization_comprehensive',
            'optimization_result': optimization_result,
            'best_params_backtest': best_params_result,
            'charts': charts,
            'recommendations': self._generate_optimization_recommendations(optimization_result)
        }
    
    async def _run_strategy_comparison_comprehensive(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """运行策略比较综合回测"""
        symbol = config['symbol']
        strategies = config['strategies']
        
        # 运行策略比较
        comparison_result = await self.basic_service.compare_strategies(
            symbol=symbol,
            strategies=strategies,
            start_date=datetime.fromisoformat(config['start_date']),
            end_date=datetime.fromisoformat(config['end_date']),
            **config.get('params', {})
        )
        
        # 生成比较图表
        if self.visualization_enabled:
            charts = await self._generate_comparison_charts(comparison_result)
        else:
            charts = {}
        
        return {
            'type': 'strategy_comparison_comprehensive',
            'comparison_result': comparison_result,
            'charts': charts,
            'recommendations': self._generate_comparison_recommendations(comparison_result)
        }
    
    async def _generate_charts(
        self,
        basic_result: Dict[str, Any],
        advanced_result: Dict[str, Any]
    ) -> Dict[str, str]:
        """生成图表"""
        charts = {}
        
        try:
            # 设置绘图样式
            plt.style.use('seaborn-v0_8')
            
            # 权益曲线
            fig, ax = plt.subplots(figsize=(12, 6))
            if basic_result.get('balance_history'):
                timestamps, balances = zip(*basic_result['balance_history'])
                ax.plot(timestamps, balances, label='账户余额', linewidth=2)
                ax.set_title('权益曲线')
                ax.set_xlabel('时间')
                ax.set_ylabel('账户余额')
                ax.legend()
                ax.grid(True, alpha=0.3)
                
                # 保存图表
                chart_path = f"logs/cache/equity_curve_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                Path(chart_path).parent.mkdir(parents=True, exist_ok=True)
                plt.savefig(chart_path, dpi=150, bbox_inches='tight')
                charts['equity_curve'] = chart_path
                plt.close()
            
            # 回撤分析
            if advanced_result.get('balance_history'):
                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
                
                timestamps, balances = zip(*advanced_result['balance_history'])
                
                # 权益曲线
                ax1.plot(timestamps, balances, label='投资组合价值', linewidth=2)
                ax1.set_title('投资组合表现')
                ax1.set_ylabel('价值')
                ax1.legend()
                ax1.grid(True, alpha=0.3)
                
                # 回撤曲线
                peak = np.maximum.accumulate(balances)
                drawdown = (np.array(balances) - peak) / peak * 100
                ax2.fill_between(timestamps, drawdown, 0, alpha=0.3, color='red', label='回撤')
                ax2.plot(timestamps, drawdown, color='red', linewidth=1)
                ax2.set_title('回撤分析')
                ax2.set_xlabel('时间')
                ax2.set_ylabel('回撤 (%)')
                ax2.legend()
                ax2.grid(True, alpha=0.3)
                
                chart_path = f"logs/cache/portfolio_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                plt.savefig(chart_path, dpi=150, bbox_inches='tight')
                charts['portfolio_analysis'] = chart_path
                plt.close()
            
        except Exception as e:
            logger.error(f"❌ 生成图表失败: {e}")
        
        return charts
    
    async def _generate_portfolio_charts(self, result: Dict[str, Any]) -> Dict[str, str]:
        """生成投资组合图表"""
        charts = {}
        
        try:
            portfolio_history = result.get('portfolio_history', [])
            if not portfolio_history:
                return charts
            
            # 投资组合权重变化
            fig, ax = plt.subplots(figsize=(12, 6))
            
            timestamps = [h['timestamp'] for h in portfolio_history[::24]]  # 每天一个数据点
            weights_data = {}
            
            for h in portfolio_history[::24]:
                for symbol, weight in h.get('weights', {}).items():
                    if symbol not in weights_data:
                        weights_data[symbol] = []
                    weights_data[symbol].append(weight)
            
            # 绘制权重变化
            for symbol, weights in weights_data.items():
                ax.plot(timestamps[:len(weights)], weights, label=symbol, linewidth=2, marker='o', markersize=3)
            
            ax.set_title('投资组合权重变化')
            ax.set_xlabel('时间')
            ax.set_ylabel('权重')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            chart_path = f"logs/cache/portfolio_weights_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            Path(chart_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            charts['portfolio_weights'] = chart_path
            plt.close()
            
        except Exception as e:
            logger.error(f"❌ 生成投资组合图表失败: {e}")
        
        return charts
    
    async def _generate_optimization_charts(self, optimization_result: OptimizationResult) -> Dict[str, str]:
        """生成优化结果图表"""
        charts = {}
        
        try:
            results = optimization_result.all_results
            if not results:
                return charts
            
            # 参数vs性能散点图
            param_names = list(optimization_result.best_params.keys())
            
            if len(param_names) >= 2:
                fig, ax = plt.subplots(figsize=(10, 8))
                
                x_param = param_names[0]
                y_param = param_names[1]
                
                x_values = [r['params'][x_param] for r in results if 'params' in r]
                y_values = [r['params'][y_param] for r in results if 'params' in r]
                scores = [r.get(optimization_result.optimization_metric, 0) for r in results if 'params' in r]
                
                scatter = ax.scatter(x_values, y_values, c=scores, cmap='viridis', alpha=0.6)
                ax.set_xlabel(x_param)
                ax.set_ylabel(y_param)
                ax.set_title(f'参数优化结果 ({optimization_result.optimization_metric})')
                
                # 标记最佳点
                best_x = optimization_result.best_params[x_param]
                best_y = optimization_result.best_params[y_param]
                ax.scatter([best_x], [best_y], color='red', s=100, marker='*', label='最佳参数')
                
                plt.colorbar(scatter, ax=ax, label=optimization_result.optimization_metric)
                ax.legend()
                ax.grid(True, alpha=0.3)
                
                chart_path = f"logs/cache/optimization_scatter_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                Path(chart_path).parent.mkdir(parents=True, exist_ok=True)
                plt.savefig(chart_path, dpi=150, bbox_inches='tight')
                charts['optimization_scatter'] = chart_path
                plt.close()
            
        except Exception as e:
            logger.error(f"❌ 生成优化图表失败: {e}")
        
        return charts
    
    async def _generate_comparison_charts(self, comparison_result: Dict[str, Any]) -> Dict[str, str]:
        """生成策略比较图表"""
        charts = {}
        
        try:
            individual_results = comparison_result.get('individual_results', {})
            comparison = comparison_result.get('comparison', {})
            
            if not individual_results:
                return charts
            
            # 策略性能比较条形图
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
            
            strategies = list(individual_results.keys())
            metrics = ['total_pnl_percent', 'win_rate', 'sharpe_ratio', 'max_drawdown_percent']
            metric_labels = ['总收益率 (%)', '胜率', '夏普比率', '最大回撤 (%)']
            
            axes = [ax1, ax2, ax3, ax4]
            
            for i, (metric, label, ax) in enumerate(zip(metrics, metric_labels, axes)):
                values = []
                for strategy in strategies:
                    result = individual_results[strategy]
                    if 'error' not in result:
                        metric_value = getattr(result.get('metrics'), metric, 0)
                        values.append(metric_value)
                    else:
                        values.append(0)
                
                bars = ax.bar(strategies, values, alpha=0.7)
                ax.set_title(label)
                ax.set_ylabel(label)
                
                # 旋转x轴标签
                ax.tick_params(axis='x', rotation=45)
                
                # 为条形图添加数值标签
                for bar, value in zip(bars, values):
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           f'{value:.2f}', ha='center', va='bottom')
            
            plt.tight_layout()
            
            chart_path = f"logs/cache/strategy_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            Path(chart_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(chart_path, dpi=150, bbox_inches='tight')
            charts['strategy_comparison'] = chart_path
            plt.close()
            
        except Exception as e:
            logger.error(f"❌ 生成策略比较图表失败: {e}")
        
        return charts
    
    def _generate_recommendations(
        self,
        basic_result: Dict[str, Any],
        advanced_result: Dict[str, Any]
    ) -> List[str]:
        """生成回测建议"""
        recommendations = []
        
        try:
            basic_metrics = basic_result.get('metrics')
            if basic_metrics:
                # 基于胜率的建议
                win_rate = getattr(basic_metrics, 'win_rate', 0)
                if win_rate < 0.4:
                    recommendations.append("⚠️ 胜率较低，建议优化入场条件或调整策略参数")
                elif win_rate > 0.7:
                    recommendations.append("✅ 胜率表现良好，策略具有较强的盈利能力")
                
                # 基于夏普比率的建议
                sharpe = getattr(basic_metrics, 'sharpe_ratio', 0)
                if sharpe < 1.0:
                    recommendations.append("📈 夏普比率偏低，建议优化风险收益比")
                elif sharpe > 2.0:
                    recommendations.append("🎯 夏普比率优秀，策略风险调整后收益良好")
                
                # 基于最大回撤的建议
                max_dd = getattr(basic_metrics, 'max_drawdown_percent', 0)
                if max_dd > 20:
                    recommendations.append("🛑 最大回撤过大，建议增强止损机制")
                elif max_dd < 5:
                    recommendations.append("🔒 回撤控制良好，风险管理有效")
                
                # 基于交易频率的建议
                total_trades = getattr(basic_metrics, 'total_trades', 0)
                if total_trades < 10:
                    recommendations.append("📊 交易次数较少，可能错过较多机会，建议降低入场门槛")
                elif total_trades > 100:
                    recommendations.append("⚡ 交易频率较高，注意交易成本对收益的影响")
            
            # 基于高级分析的建议
            advanced_metrics = advanced_result.get('portfolio_metrics', {})
            if advanced_metrics:
                annual_return = advanced_metrics.get('annualized_return', 0)
                if annual_return > 0.2:
                    recommendations.append("🚀 年化收益率表现优异，策略具有很强的盈利潜力")
                elif annual_return < 0:
                    recommendations.append("📉 年化收益率为负，建议重新评估策略有效性")
        
        except Exception as e:
            logger.error(f"❌ 生成建议失败: {e}")
            recommendations.append("❌ 无法生成详细建议，请检查回测结果")
        
        return recommendations
    
    def _generate_portfolio_recommendations(self, result: Dict[str, Any]) -> List[str]:
        """生成投资组合建议"""
        recommendations = []
        
        try:
            portfolio_metrics = result.get('portfolio_metrics', {})
            risk_events = result.get('risk_events', [])
            
            # 基于投资组合指标的建议
            if portfolio_metrics:
                sharpe = portfolio_metrics.get('sharpe_ratio', 0)
                if sharpe > 1.5:
                    recommendations.append("📈 投资组合夏普比率优秀，风险调整后收益良好")
                elif sharpe < 0.5:
                    recommendations.append("⚠️ 投资组合夏普比率偏低，建议优化资产配置")
                
                max_dd = portfolio_metrics.get('max_drawdown', 0)
                if max_dd > 0.3:
                    recommendations.append("🛑 投资组合最大回撤过大，建议增强风险控制")
                
                correlation = result.get('report', {}).get('risk_analysis', {}).get('correlation_analysis', {})
                avg_corr = correlation.get('average_correlation', 0)
                if avg_corr > 0.7:
                    recommendations.append("🔗 投资组合相关性较高，建议增加多样化资产")
                elif avg_corr < 0.3:
                    recommendations.append("✅ 投资组合分散化良好，降低了系统性风险")
            
            # 基于风险事件的建议
            if risk_events:
                recommendations.append(f"⚠️ 回测期间发生 {len(risk_events)} 次风险事件，建议审查风险管理策略")
            else:
                recommendations.append("✅ 回测期间未触发风险事件，风险控制机制运行良好")
        
        except Exception as e:
            logger.error(f"❌ 生成投资组合建议失败: {e}")
        
        return recommendations
    
    def _generate_optimization_recommendations(self, optimization_result: OptimizationResult) -> List[str]:
        """生成优化建议"""
        recommendations = []
        
        try:
            best_score = optimization_result.best_score
            metric = optimization_result.optimization_metric
            
            recommendations.append(f"🎯 最优参数组合在 {metric} 指标上达到 {best_score:.4f}")
            
            # 分析参数敏感性
            all_results = optimization_result.all_results
            if len(all_results) > 10:
                scores = [r.get(metric, 0) for r in all_results]
                score_std = np.std(scores)
                score_mean = np.mean(scores)
                
                if score_std / abs(score_mean) > 0.5:
                    recommendations.append("⚠️ 策略对参数变化较为敏感，建议进行稳健性测试")
                else:
                    recommendations.append("✅ 策略对参数变化相对稳健")
                
                # 检查是否存在明显更优的参数区域
                top_10_percent = sorted(all_results, key=lambda x: x.get(metric, 0), reverse=True)[:len(all_results)//10]
                if len(top_10_percent) > 1:
                    recommendations.append("💡 发现多个高性能参数组合，建议进一步细化搜索范围")
        
        except Exception as e:
            logger.error(f"❌ 生成优化建议失败: {e}")
        
        return recommendations
    
    def _generate_comparison_recommendations(self, comparison_result: Dict[str, Any]) -> List[str]:
        """生成策略比较建议"""
        recommendations = []
        
        try:
            comparison = comparison_result.get('comparison', {})
            summary = comparison.get('summary', {})
            
            if summary:
                best_return_strategy = summary.get('best_return_strategy')
                best_sharpe_strategy = summary.get('best_sharpe_strategy')
                
                if best_return_strategy:
                    recommendations.append(f"📈 {best_return_strategy} 在总收益率方面表现最佳")
                
                if best_sharpe_strategy and best_sharpe_strategy != best_return_strategy:
                    recommendations.append(f"⚖️ {best_sharpe_strategy} 在风险调整收益方面表现最佳")
                    recommendations.append("💡 建议综合考虑收益和风险，选择适合的策略")
                elif best_sharpe_strategy == best_return_strategy:
                    recommendations.append(f"🎯 {best_return_strategy} 在收益和风险平衡方面都表现最佳")
                
                rankings = comparison.get('rankings', {})
                if 'max_drawdown_percent' in rankings:
                    best_dd_strategy = rankings['max_drawdown_percent'][0]['strategy']
                    recommendations.append(f"🛡️ {best_dd_strategy} 在风险控制方面表现最佳")
        
        except Exception as e:
            logger.error(f"❌ 生成策略比较建议失败: {e}")
        
        return recommendations
    
    async def export_results(
        self,
        results: Dict[str, Any],
        export_format: str = "json",
        file_path: str = None
    ) -> str:
        """导出回测结果"""
        try:
            if not file_path:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                file_path = f"logs/cache/backtest_results_{timestamp}.{export_format}"
            
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            
            if export_format == "json":
                # 处理不可序列化的对象
                serializable_results = self._make_serializable(results)
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(serializable_results, f, ensure_ascii=False, indent=2)
                    
            elif export_format == "pickle":
                with open(file_path, 'wb') as f:
                    pickle.dump(results, f)
                    
            elif export_format == "excel":
                # 导出到Excel（需要openpyxl）
                await self._export_to_excel(results, file_path)
            else:
                raise BacktestError(f"不支持的导出格式: {export_format}")
            
            logger.info(f"📁 回测结果已导出到: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"❌ 导出回测结果失败: {e}")
            raise BacktestError(f"导出失败: {str(e)}")
    
    def _make_serializable(self, obj: Any) -> Any:
        """将对象转换为可序列化格式"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, (BacktestMetrics, BacktestTrade)):
            return obj.__dict__
        elif isinstance(obj, dict):
            return {key: self._make_serializable(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._make_serializable(item) for item in obj]
        elif hasattr(obj, '__dict__'):
            return self._make_serializable(obj.__dict__)
        else:
            return obj
    
    async def _export_to_excel(self, results: Dict[str, Any], file_path: str):
        """导出到Excel文件"""
        try:
            import pandas as pd
            
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                # 基础指标
                if 'metrics' in results:
                    metrics = results['metrics']
                    metrics_df = pd.DataFrame([metrics.__dict__ if hasattr(metrics, '__dict__') else metrics])
                    metrics_df.to_excel(writer, sheet_name='指标汇总', index=False)
                
                # 交易记录
                if 'trades' in results:
                    trades_df = pd.DataFrame(results['trades'])
                    if not trades_df.empty:
                        trades_df.to_excel(writer, sheet_name='交易记录', index=False)
                
                # 余额历史
                if 'balance_history' in results:
                    balance_df = pd.DataFrame(results['balance_history'], columns=['时间', '余额'])
                    balance_df.to_excel(writer, sheet_name='余额历史', index=False)
                
        except ImportError:
            logger.warning("⚠️ 未安装openpyxl，无法导出Excel格式")
            raise BacktestError("需要安装openpyxl库来导出Excel格式")
        except Exception as e:
            logger.error(f"❌ 导出Excel失败: {e}")
            raise


