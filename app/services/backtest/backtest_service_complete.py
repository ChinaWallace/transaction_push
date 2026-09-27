# -*- coding: utf-8 -*-
"""
完整回测服务 - 兼容性包装器
Complete Backtest Service - Compatibility wrapper for CoreBacktestService
"""

from typing import Dict, Any, List
from datetime import datetime
from enum import Enum
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.exceptions import BacktestError

logger = get_logger(__name__)
settings = get_settings()


class OptimizationMethod(Enum):
    """优化方法枚举"""
    GRID_SEARCH = "grid_search"
    RANDOM_SEARCH = "random_search"
    BAYESIAN = "bayesian"


@dataclass
class StrategyParameter:
    """策略参数"""
    name: str
    min_value: float
    max_value: float
    step: float = 0.01
    default: float = None


@dataclass
class RiskManagementConfig:
    """风险管理配置"""
    max_position_size: float = 0.1
    stop_loss: float = 0.05
    take_profit: float = 0.1
    max_drawdown: float = 0.2


@dataclass
class PortfolioConfig:
    """投资组合配置"""
    initial_capital: float = 10000.0
    max_positions: int = 5
    position_sizing: str = "equal"


class CompleteBacktestService:
    """完整回测服务类 - 兼容性实现"""
    
    def __init__(self):
        self.logger = logger
        
    async def run_backtest(self, 
                          symbol: str,
                          strategy: str,
                          start_date: datetime,
                          end_date: datetime,
                          parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        raise BacktestError('Legacy backtest/optimization is not implemented; use scripts/market_advisory.py replay or a validated Freqtrade backtest.')
            
    async def optimize_strategy(self,
                               symbol: str,
                               strategy: str,
                               parameters: List[StrategyParameter],
                               method: OptimizationMethod = OptimizationMethod.GRID_SEARCH) -> Dict[str, Any]:
        raise BacktestError('Legacy backtest/optimization is not implemented; use scripts/market_advisory.py replay or a validated Freqtrade backtest.')


class AdvancedBacktestEngine:
    """高级回测引擎 - 兼容性实现"""
    
    def __init__(self):
        self.logger = logger
        
    async def run_advanced_backtest(self, config: Dict[str, Any]) -> Dict[str, Any]:
        raise BacktestError('Legacy backtest/optimization is not implemented; use scripts/market_advisory.py replay or a validated Freqtrade backtest.')


class StrategyOptimizer:
    """策略优化器 - 兼容性实现"""
    
    def __init__(self):
        self.logger = logger
        
    async def optimize(self, parameters: List[StrategyParameter]) -> Dict[str, Any]:
        raise BacktestError('Legacy backtest/optimization is not implemented; use scripts/market_advisory.py replay or a validated Freqtrade backtest.')


# 导出
__all__ = [
    "CompleteBacktestService",
    "AdvancedBacktestEngine", 
    "StrategyOptimizer",
    "StrategyParameter",
    "OptimizationMethod",
    "RiskManagementConfig",
    "PortfolioConfig"
]

