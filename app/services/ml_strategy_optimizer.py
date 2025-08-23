# -*- coding: utf-8 -*-
"""
ML策略优化器
ML Strategy Optimizer - 使用机器学习持续优化交易策略
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import asyncio
import numpy as np
import pandas as pd
import json
from pathlib import Path

# 机器学习库
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.metrics import mean_squared_error, mean_absolute_error
from sklearn.preprocessing import StandardScaler
import joblib

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.okx_service import OKXService
from app.services.ml_enhanced_service import MLEnhancedService
from app.utils.exceptions import MLModelError

logger = get_logger(__name__)
settings = get_settings()


class OptimizationTarget(Enum):
    """优化目标"""
    PROFIT = "profit"
    SHARPE_RATIO = "sharpe_ratio"
    WIN_RATE = "win_rate"
    MAX_DRAWDOWN = "max_drawdown"
    RISK_ADJUSTED_RETURN = "risk_adjusted_return"


@dataclass
class StrategyPerformance:
    """策略表现"""
    symbol: str
    strategy_name: str
    period_start: datetime
    period_end: datetime
    
    # 收益指标
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    
    # 交易指标
    total_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    
    # 风险指标
    volatility: float
    var_95: float  # 95% VaR
    
    # 参数
    parameters: Dict[str, Any]


@dataclass
class OptimizationResult:
    """优化结果"""
    symbol: str
    optimization_target: OptimizationTarget
    
    # 最优参数
    best_parameters: Dict[str, Any]
    best_score: float
    
    # 性能对比
    original_performance: StrategyPerformance
    optimized_performance: StrategyPerformance
    improvement_percent: float
    
    # 稳定性测试
    stability_score: float
    confidence_interval: Tuple[float, float]
    
    # 优化历史
    optimization_history: List[Dict[str, Any]]
    
    timestamp: datetime


class MLStrategyOptimizer:
    """ML策略优化器类"""
    
    def __init__(self):
        self.okx_service = OKXService()
        self.ml_service = MLEnhancedService()
        
        # 优化器配置
        self.optimization_config = settings.ml_config.get('strategy_optimization', {})
        
        # 模型存储
        self.models_dir = Path("models/strategy_optimization")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        # 性能记录
        self.performance_history = {}
        
        # 优化器
        self.parameter_optimizers = {}
    
    async def optimize_strategy_parameters(self, 
                                         symbol: str,
                                         strategy_name: str = "supertrend_ml",
                                         optimization_target: OptimizationTarget = OptimizationTarget.SHARPE_RATIO,
                                         lookback_days: int = 30) -> OptimizationResult:
        """
        优化策略参数
        
        Args:
            symbol: 交易对
            strategy_name: 策略名称
            optimization_target: 优化目标
            lookback_days: 回测天数
            
        Returns:
            优化结果
        """
        try:
            logger.info(f"开始优化 {symbol} 的 {strategy_name} 策略参数")
            
            # 获取历史数据
            historical_data = await self._get_optimization_data(symbol, lookback_days)
            
            # 获取当前参数
            current_params = await self._get_current_parameters(symbol, strategy_name)
            
            # 计算当前性能
            original_performance = await self._calculate_strategy_performance(
                historical_data, current_params, strategy_name
            )
            
            # 执行参数优化
            optimization_results = await self._run_parameter_optimization(
                historical_data, strategy_name, optimization_target
            )
            
            best_params = optimization_results['best_params']
            best_score = optimization_results['best_score']
            
            # 计算优化后性能
            optimized_performance = await self._calculate_strategy_performance(
                historical_data, best_params, strategy_name
            )
            
            # 稳定性测试
            stability_score, confidence_interval = await self._test_parameter_stability(
                historical_data, best_params, strategy_name
            )
            
            # 计算改进幅度
            improvement = self._calculate_improvement(
                original_performance, optimized_performance, optimization_target
            )
            
            result = OptimizationResult(
                symbol=symbol,
                optimization_target=optimization_target,
                best_parameters=best_params,
                best_score=best_score,
                original_performance=original_performance,
                optimized_performance=optimized_performance,
                improvement_percent=improvement,
                stability_score=stability_score,
                confidence_interval=confidence_interval,
                optimization_history=optimization_results['history'],
                timestamp=datetime.now()
            )
            
            # 保存优化结果
            await self._save_optimization_result(result)
            
            trading_logger.info(f"{symbol} 策略优化完成，改进: {improvement:.2f}%")
            
            return result
            
        except Exception as e:
            logger.error(f"策略参数优化失败 {symbol}: {e}")
            raise MLModelError(f"策略优化失败: {e}")
    
    async def adaptive_parameter_update(self, 
                                      symbol: str,
                                      performance_threshold: float = 0.1) -> Dict[str, Any]:
        """
        自适应参数更新
        
        Args:
            symbol: 交易对
            performance_threshold: 性能下降阈值
            
        Returns:
            更新结果
        """
        try:
            # 获取最近性能
            recent_performance = await self._get_recent_performance(symbol)
            
            # 检查是否需要重新优化
            if self._should_reoptimize(recent_performance, performance_threshold):
                logger.info(f"{symbol} 性能下降，触发自适应优化")
                
                # 执行快速优化
                optimization_result = await self.optimize_strategy_parameters(
                    symbol, lookback_days=14  # 使用较短的回测期
                )
                
                # 应用新参数
                await self._apply_optimized_parameters(symbol, optimization_result.best_parameters)
                
                return {
                    'status': 'updated',
                    'trigger': 'performance_decline',
                    'old_params': recent_performance.get('parameters', {}),
                    'new_params': optimization_result.best_parameters,
                    'expected_improvement': optimization_result.improvement_percent
                }
            else:
                return {
                    'status': 'no_update_needed',
                    'current_performance': recent_performance
                }
                
        except Exception as e:
            logger.error(f"自适应参数更新失败 {symbol}: {e}")
            return {'status': 'error', 'message': str(e)}
    
    async def batch_optimize_strategies(self, 
                                      symbols: List[str],
                                      max_concurrent: int = 3) -> Dict[str, OptimizationResult]:
        """
        批量优化策略
        
        Args:
            symbols: 交易对列表
            max_concurrent: 最大并发数
            
        Returns:
            优化结果字典
        """
        results = {}
        
        # 分批处理
        for i in range(0, len(symbols), max_concurrent):
            batch = symbols[i:i + max_concurrent]
            
            # 并行优化
            tasks = [
                self.optimize_strategy_parameters(symbol)
                for symbol in batch
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for j, result in enumerate(batch_results):
                symbol = batch[j]
                if isinstance(result, Exception):
                    logger.error(f"优化 {symbol} 失败: {result}")
                    results[symbol] = None
                else:
                    results[symbol] = result
        
        return results
    
    async def _get_optimization_data(self, symbol: str, days: int) -> pd.DataFrame:
        """获取优化用的历史数据"""
        try:
            async with self.okx_service as okx:
                # 获取小时K线数据
                limit = min(24 * days, 1000)
                klines = await okx.get_kline_data(symbol, '1H', limit)
                
                if not klines:
                    raise MLModelError(f"无法获取 {symbol} 历史数据")
                
                # 转换为DataFrame
                df = pd.DataFrame(klines)
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                
                # 计算技术指标
                df = await self._add_technical_indicators(df)
                
                return df
                
        except Exception as e:
            logger.error(f"获取优化数据失败 {symbol}: {e}")
            raise MLModelError(f"数据获取失败: {e}")
    
    async def _add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加技术指标"""
        # 移动平均线
        df['sma_5'] = df['close'].rolling(window=5).mean()
        df['sma_20'] = df['close'].rolling(window=20).mean()
        df['ema_12'] = df['close'].ewm(span=12).mean()
        df['ema_26'] = df['close'].ewm(span=26).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # MACD
        df['macd'] = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        
        # 布林带
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = true_range.rolling(window=14).mean()
        
        # 成交量指标
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        return df
    
    async def _get_current_parameters(self, symbol: str, strategy_name: str) -> Dict[str, Any]:
        """获取当前策略参数"""
        # 默认SuperTrend参数
        default_params = {
            'supertrend_period': 10,
            'supertrend_multiplier': 3.0,
            'rsi_period': 14,
            'rsi_overbought': 70,
            'rsi_oversold': 30,
            'volume_threshold': 1.5,
            'stop_loss_pct': 0.03,
            'take_profit_pct': 0.09
        }
        
        # 尝试从配置文件加载
        try:
            params_file = self.models_dir / f"{symbol}_{strategy_name}_params.json"
            if params_file.exists():
                with open(params_file, 'r') as f:
                    saved_params = json.load(f)
                default_params.update(saved_params)
        except Exception as e:
            logger.warning(f"加载参数失败，使用默认值: {e}")
        
        return default_params
    
    async def _calculate_strategy_performance(self, 
                                            data: pd.DataFrame,
                                            parameters: Dict[str, Any],
                                            strategy_name: str) -> StrategyPerformance:
        """计算策略表现"""
        try:
            # 生成交易信号
            signals = await self._generate_strategy_signals(data, parameters, strategy_name)
            
            # 计算收益
            returns = self._calculate_returns(data, signals, parameters)
            
            # 计算性能指标
            total_return = (returns + 1).prod() - 1
            annualized_return = (1 + total_return) ** (365 / len(returns)) - 1
            
            # 最大回撤
            cumulative = (returns + 1).cumprod()
            running_max = cumulative.expanding().max()
            drawdown = (cumulative - running_max) / running_max
            max_drawdown = drawdown.min()
            
            # 夏普比率
            volatility = returns.std() * np.sqrt(365)
            sharpe_ratio = annualized_return / volatility if volatility > 0 else 0
            
            # 交易统计
            trades = self._analyze_trades(signals, data, parameters)
            
            return StrategyPerformance(
                symbol=data.index[0].strftime('%Y-%m-%d') if len(data) > 0 else 'Unknown',
                strategy_name=strategy_name,
                period_start=data.index[0] if len(data) > 0 else datetime.now(),
                period_end=data.index[-1] if len(data) > 0 else datetime.now(),
                
                total_return=total_return,
                annualized_return=annualized_return,
                max_drawdown=max_drawdown,
                sharpe_ratio=sharpe_ratio,
                
                total_trades=trades['total_trades'],
                win_rate=trades['win_rate'],
                avg_win=trades['avg_win'],
                avg_loss=trades['avg_loss'],
                profit_factor=trades['profit_factor'],
                
                volatility=volatility,
                var_95=np.percentile(returns, 5),
                
                parameters=parameters
            )
            
        except Exception as e:
            logger.error(f"计算策略表现失败: {e}")
            raise MLModelError(f"性能计算失败: {e}")
    
    async def _generate_strategy_signals(self, 
                                       data: pd.DataFrame,
                                       parameters: Dict[str, Any],
                                       strategy_name: str) -> pd.Series:
        """生成策略信号"""
        if strategy_name == "supertrend_ml":
            return self._generate_supertrend_signals(data, parameters)
        else:
            raise ValueError(f"未知策略: {strategy_name}")
    
    def _generate_supertrend_signals(self, data: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
        """生成SuperTrend信号"""
        period = params.get('supertrend_period', 10)
        multiplier = params.get('supertrend_multiplier', 3.0)
        
        # 计算SuperTrend
        hl2 = (data['high'] + data['low']) / 2
        atr = data['atr']
        
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)
        
        # SuperTrend计算
        supertrend = pd.Series(index=data.index, dtype=float)
        trend = pd.Series(index=data.index, dtype=int)
        
        for i in range(1, len(data)):
            if data['close'].iloc[i] > upper_band.iloc[i-1]:
                trend.iloc[i] = 1
                supertrend.iloc[i] = lower_band.iloc[i]
            elif data['close'].iloc[i] < lower_band.iloc[i-1]:
                trend.iloc[i] = -1
                supertrend.iloc[i] = upper_band.iloc[i]
            else:
                trend.iloc[i] = trend.iloc[i-1]
                if trend.iloc[i] == 1:
                    supertrend.iloc[i] = max(lower_band.iloc[i], supertrend.iloc[i-1])
                else:
                    supertrend.iloc[i] = min(upper_band.iloc[i], supertrend.iloc[i-1])
        
        # 生成交易信号
        signals = pd.Series(0, index=data.index)
        
        # SuperTrend信号
        st_signals = trend.diff()
        
        # RSI过滤
        rsi_period = params.get('rsi_period', 14)
        rsi_ob = params.get('rsi_overbought', 70)
        rsi_os = params.get('rsi_oversold', 30)
        
        # 成交量过滤
        vol_threshold = params.get('volume_threshold', 1.5)
        volume_filter = data['volume_ratio'] > vol_threshold
        
        # 组合信号
        buy_signals = (st_signals > 0) & (data['rsi'] < rsi_ob) & volume_filter
        sell_signals = (st_signals < 0) & (data['rsi'] > rsi_os) & volume_filter
        
        signals[buy_signals] = 1
        signals[sell_signals] = -1
        
        return signals
    
    def _calculate_returns(self, data: pd.DataFrame, signals: pd.Series, params: Dict[str, Any]) -> pd.Series:
        """计算收益率"""
        returns = pd.Series(0.0, index=data.index)
        position = 0
        entry_price = 0
        
        stop_loss_pct = params.get('stop_loss_pct', 0.03)
        take_profit_pct = params.get('take_profit_pct', 0.09)
        
        for i in range(1, len(data)):
            current_price = data['close'].iloc[i]
            signal = signals.iloc[i]
            
            # 开仓
            if signal != 0 and position == 0:
                position = signal
                entry_price = current_price
            
            # 平仓检查
            elif position != 0:
                price_change = (current_price - entry_price) / entry_price
                
                # 止损止盈
                if position == 1:  # 多头
                    if price_change <= -stop_loss_pct or price_change >= take_profit_pct:
                        returns.iloc[i] = price_change
                        position = 0
                    elif signal == -1:  # 反向信号
                        returns.iloc[i] = price_change
                        position = 0
                else:  # 空头
                    if price_change >= stop_loss_pct or price_change <= -take_profit_pct:
                        returns.iloc[i] = -price_change
                        position = 0
                    elif signal == 1:  # 反向信号
                        returns.iloc[i] = -price_change
                        position = 0
        
        return returns
    
    def _analyze_trades(self, signals: pd.Series, data: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
        """分析交易统计"""
        trades = []
        position = 0
        entry_price = 0
        entry_time = None
        
        stop_loss_pct = params.get('stop_loss_pct', 0.03)
        take_profit_pct = params.get('take_profit_pct', 0.09)
        
        for i in range(len(data)):
            current_price = data['close'].iloc[i]
            signal = signals.iloc[i]
            
            if signal != 0 and position == 0:
                position = signal
                entry_price = current_price
                entry_time = data.index[i]
            elif position != 0:
                price_change = (current_price - entry_price) / entry_price
                exit_trade = False
                
                if position == 1:
                    if price_change <= -stop_loss_pct or price_change >= take_profit_pct or signal == -1:
                        trades.append(price_change)
                        exit_trade = True
                else:
                    if price_change >= stop_loss_pct or price_change <= -take_profit_pct or signal == 1:
                        trades.append(-price_change)
                        exit_trade = True
                
                if exit_trade:
                    position = 0
        
        if not trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'profit_factor': 0
            }
        
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t < 0]
        
        return {
            'total_trades': len(trades),
            'win_rate': len(wins) / len(trades) if trades else 0,
            'avg_win': np.mean(wins) if wins else 0,
            'avg_loss': np.mean(losses) if losses else 0,
            'profit_factor': sum(wins) / abs(sum(losses)) if losses else float('inf')
        }
    
    async def _run_parameter_optimization(self, 
                                        data: pd.DataFrame,
                                        strategy_name: str,
                                        target: OptimizationTarget) -> Dict[str, Any]:
        """运行参数优化"""
        # 定义参数搜索空间
        param_grid = {
            'supertrend_period': [7, 10, 14, 21],
            'supertrend_multiplier': [2.0, 2.5, 3.0, 3.5, 4.0],
            'rsi_period': [10, 14, 21],
            'volume_threshold': [1.2, 1.5, 2.0],
            'stop_loss_pct': [0.02, 0.03, 0.04],
            'take_profit_pct': [0.06, 0.09, 0.12]
        }
        
        best_score = float('-inf')
        best_params = {}
        history = []
        
        # 网格搜索
        from itertools import product
        
        param_combinations = []
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        
        for combination in product(*values):
            param_dict = dict(zip(keys, combination))
            param_combinations.append(param_dict)
        
        # 限制搜索数量
        if len(param_combinations) > 100:
            import random
            param_combinations = random.sample(param_combinations, 100)
        
        for params in param_combinations:
            try:
                performance = await self._calculate_strategy_performance(data, params, strategy_name)
                
                # 根据目标选择评分
                if target == OptimizationTarget.SHARPE_RATIO:
                    score = performance.sharpe_ratio
                elif target == OptimizationTarget.PROFIT:
                    score = performance.total_return
                elif target == OptimizationTarget.WIN_RATE:
                    score = performance.win_rate
                elif target == OptimizationTarget.MAX_DRAWDOWN:
                    score = -performance.max_drawdown  # 负值，因为要最小化回撤
                else:
                    score = performance.sharpe_ratio  # 默认
                
                history.append({
                    'params': params.copy(),
                    'score': score,
                    'performance': performance
                })
                
                if score > best_score:
                    best_score = score
                    best_params = params.copy()
                    
            except Exception as e:
                logger.warning(f"参数组合评估失败: {params}, 错误: {e}")
                continue
        
        return {
            'best_params': best_params,
            'best_score': best_score,
            'history': history
        }
    
    async def _test_parameter_stability(self, 
                                      data: pd.DataFrame,
                                      params: Dict[str, Any],
                                      strategy_name: str) -> Tuple[float, Tuple[float, float]]:
        """测试参数稳定性"""
        try:
            # 滑动窗口测试
            window_size = len(data) // 3
            scores = []
            
            for i in range(3):
                start_idx = i * window_size
                end_idx = start_idx + window_size
                window_data = data.iloc[start_idx:end_idx]
                
                if len(window_data) < 50:  # 数据太少跳过
                    continue
                
                performance = await self._calculate_strategy_performance(
                    window_data, params, strategy_name
                )
                scores.append(performance.sharpe_ratio)
            
            if not scores:
                return 0.0, (0.0, 0.0)
            
            # 计算稳定性分数（标准差的倒数）
            stability_score = 1.0 / (np.std(scores) + 0.001)  # 避免除零
            
            # 置信区间
            mean_score = np.mean(scores)
            std_score = np.std(scores)
            confidence_interval = (
                mean_score - 1.96 * std_score,
                mean_score + 1.96 * std_score
            )
            
            return stability_score, confidence_interval
            
        except Exception as e:
            logger.warning(f"稳定性测试失败: {e}")
            return 0.0, (0.0, 0.0)
    
    def _calculate_improvement(self, 
                             original: StrategyPerformance,
                             optimized: StrategyPerformance,
                             target: OptimizationTarget) -> float:
        """计算改进幅度"""
        if target == OptimizationTarget.SHARPE_RATIO:
            if original.sharpe_ratio == 0:
                return 100.0 if optimized.sharpe_ratio > 0 else 0.0
            return ((optimized.sharpe_ratio - original.sharpe_ratio) / abs(original.sharpe_ratio)) * 100
        elif target == OptimizationTarget.PROFIT:
            if original.total_return == 0:
                return 100.0 if optimized.total_return > 0 else 0.0
            return ((optimized.total_return - original.total_return) / abs(original.total_return)) * 100
        elif target == OptimizationTarget.WIN_RATE:
            if original.win_rate == 0:
                return 100.0 if optimized.win_rate > 0 else 0.0
            return ((optimized.win_rate - original.win_rate) / original.win_rate) * 100
        else:
            return 0.0
    
    async def _save_optimization_result(self, result: OptimizationResult) -> None:
        """保存优化结果"""
        try:
            # 保存参数
            params_file = self.models_dir / f"{result.symbol}_optimized_params.json"
            with open(params_file, 'w') as f:
                json.dump(result.best_parameters, f, indent=2)
            
            # 保存优化历史
            history_file = self.models_dir / f"{result.symbol}_optimization_history.json"
            history_data = {
                'timestamp': result.timestamp.isoformat(),
                'target': result.optimization_target.value,
                'improvement': result.improvement_percent,
                'stability_score': result.stability_score,
                'best_score': result.best_score
            }
            
            # 读取现有历史
            existing_history = []
            if history_file.exists():
                try:
                    with open(history_file, 'r') as f:
                        existing_history = json.load(f)
                except Exception:
                    pass
            
            existing_history.append(history_data)
            
            # 只保留最近10次记录
            if len(existing_history) > 10:
                existing_history = existing_history[-10:]
            
            with open(history_file, 'w') as f:
                json.dump(existing_history, f, indent=2)
                
        except Exception as e:
            logger.warning(f"保存优化结果失败: {e}")
    
    async def _get_recent_performance(self, symbol: str) -> Dict[str, Any]:
        """获取最近性能"""
        try:
            history_file = self.models_dir / f"{symbol}_optimization_history.json"
            if history_file.exists():
                with open(history_file, 'r') as f:
                    history = json.load(f)
                return history[-1] if history else {}
            return {}
        except Exception:
            return {}
    
    def _should_reoptimize(self, recent_performance: Dict[str, Any], threshold: float) -> bool:
        """判断是否需要重新优化"""
        if not recent_performance:
            return True
        
        # 检查时间间隔
        last_optimization = recent_performance.get('timestamp')
        if last_optimization:
            last_time = datetime.fromisoformat(last_optimization)
            if datetime.now() - last_time < timedelta(days=7):
                return False
        
        # 检查性能下降
        stability_score = recent_performance.get('stability_score', 0)
        return stability_score < threshold
    
    async def _apply_optimized_parameters(self, symbol: str, params: Dict[str, Any]) -> None:
        """应用优化后的参数"""
        try:
            params_file = self.models_dir / f"{symbol}_current_params.json"
            with open(params_file, 'w') as f:
                json.dump(params, f, indent=2)
            
            logger.info(f"已应用 {symbol} 的优化参数")
            
        except Exception as e:
            logger.error(f"应用优化参数失败: {e}")