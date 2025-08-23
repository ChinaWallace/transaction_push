# -*- coding: utf-8 -*-
"""
策略交易服务
Strategy Trading Service - 提供网格、马丁格尔等策略交易功能
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import asyncio
import numpy as np

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.okx_service import OKXService
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class StrategyType(Enum):
    """策略类型枚举"""
    GRID = "grid"
    DCA = "dca"  # 定投策略


@dataclass
class GridStrategy:
    """网格策略配置"""
    symbol: str
    grid_num: int           # 网格数量
    max_price: float        # 最高价格
    min_price: float        # 最低价格
    investment: float       # 投资金额
    profit_per_grid: float  # 每格利润


@dataclass
class DCAStrategy:
    """定投策略配置"""
    symbol: str
    side: str              # 买入/卖出方向
    investment: float      # 投资金额
    price_ratio: float     # 价格变动比例
    take_profit_ratio: float  # 止盈比例





@dataclass
class StrategyRecommendation:
    """策略建议"""
    symbol: str
    strategy_type: StrategyType
    recommended: bool
    confidence: float
    
    # 策略参数
    parameters: Dict[str, Any]
    
    # 预期收益
    expected_daily_return: float
    expected_annual_return: float
    max_drawdown: float
    
    # 风险评估
    risk_level: str
    capital_requirement: float
    
    # 建议理由
    reasoning: str


class StrategyTradingService:
    """策略交易服务类"""
    
    def __init__(self):
        self.okx_service = OKXService()
    
    async def analyze_grid_opportunity(self, symbol: str, 
                                     investment: float = 1000) -> StrategyRecommendation:
        """分析网格交易机会"""
        try:
            async with self.okx_service as okx:
                # 获取历史数据分析波动性
                klines = await okx.get_kline_data(symbol, '1H', 168)  # 7天数据
                current_price = await okx.get_current_price(symbol)
                
                if not klines or not current_price:
                    raise TradingToolError(f"无法获取{symbol}数据")
                
                # 分析价格波动
                prices = [k['close'] for k in klines]
                volatility = np.std(prices) / np.mean(prices)
                
                # 计算价格区间
                price_range = max(prices) - min(prices)
                avg_price = np.mean(prices)
                
                # 建议网格参数
                grid_num = min(20, max(5, int(price_range / avg_price * 100)))  # 根据波动性调整网格数
                
                # 设置价格区间 (当前价格 ±15%)
                max_price = current_price * 1.15
                min_price = current_price * 0.85
                
                # 计算预期收益
                profit_per_grid = (max_price - min_price) / grid_num * 0.002  # 0.2%利润每格
                daily_trades = volatility * 24  # 根据波动性估算每日交易次数
                expected_daily_return = daily_trades * profit_per_grid / investment
                
                # 判断是否推荐 - 重点推荐波动大的币种
                recommended = volatility > 0.03  # 波动性>3%才推荐
                confidence = min(95, max(30, (volatility - 0.02) * 2000))
                
                return StrategyRecommendation(
                    symbol=symbol,
                    strategy_type=StrategyType.GRID,
                    recommended=recommended,
                    confidence=confidence,
                    parameters={
                        'grid_num': grid_num,
                        'max_price': max_price,
                        'min_price': min_price,
                        'investment': investment,
                        'current_price': current_price
                    },
                    expected_daily_return=expected_daily_return,
                    expected_annual_return=expected_daily_return * 365,
                    max_drawdown=0.15,  # 最大15%回撤
                    risk_level='medium' if recommended else 'high',
                    capital_requirement=investment,
                    reasoning=f"波动性: {volatility:.3f}, 网格数: {grid_num}, 预期日收益: {expected_daily_return:.3f}%"
                )
                
        except Exception as e:
            logger.error(f"分析网格机会失败: {e}")
            raise TradingToolError(f"分析网格机会失败: {e}")
    
    async def analyze_dca_opportunity(self, symbol: str, 
                                    investment: float = 1000) -> StrategyRecommendation:
        """分析定投策略机会"""
        try:
            async with self.okx_service as okx:
                # 获取历史数据分析趋势
                klines = await okx.get_kline_data(symbol, '4H', 168)  # 4小时K线，28天数据
                current_price = await okx.get_current_price(symbol)
                
                if not klines or not current_price:
                    raise TradingToolError(f"无法获取{symbol}数据")
                
                # 分析趋势
                prices = [k['close'] for k in klines]
                
                # 计算移动平均线
                ma_short = np.mean(prices[-12:])  # 短期均线
                ma_long = np.mean(prices[-48:])   # 长期均线
                
                # 判断趋势方向
                trend_bullish = ma_short > ma_long * 1.02
                trend_bearish = ma_short < ma_long * 0.98
                
                # 计算波动性
                volatility = np.std(prices[-24:]) / np.mean(prices[-24:])
                
                # 建议参数
                side = 'buy' if trend_bullish else 'sell' if trend_bearish else 'buy'
                price_ratio = max(0.03, min(0.1, volatility * 2))  # 3%-10%价格变动
                take_profit_ratio = price_ratio * 2  # 止盈是触发的2倍
                
                # 预期收益计算
                expected_daily_return = volatility * 0.5 if trend_bullish or trend_bearish else 0
                
                # 判断是否推荐
                recommended = (trend_bullish or trend_bearish) and volatility > 0.02
                confidence = 70 if recommended else 30
                
                return StrategyRecommendation(
                    symbol=symbol,
                    strategy_type=StrategyType.DCA,
                    recommended=recommended,
                    confidence=confidence,
                    parameters={
                        'side': side,
                        'investment': investment,
                        'price_ratio': price_ratio,
                        'take_profit_ratio': take_profit_ratio,
                        'current_price': current_price
                    },
                    expected_daily_return=expected_daily_return,
                    expected_annual_return=expected_daily_return * 365,
                    max_drawdown=0.2,  # 最大20%回撤
                    risk_level='medium' if recommended else 'high',
                    capital_requirement=investment,
                    reasoning=f"趋势: {'看涨' if trend_bullish else '看跌' if trend_bearish else '震荡'}, 波动性: {volatility:.3f}"
                )
                
        except Exception as e:
            logger.error(f"分析定投机会失败: {e}")
            raise TradingToolError(f"分析定投机会失败: {e}")
    
    async def create_grid_strategy(self, strategy: GridStrategy) -> Dict[str, Any]:
        """创建网格策略"""
        try:
            async with self.okx_service as okx:
                result = await okx.place_grid_order(
                    symbol=strategy.symbol,
                    grid_num=strategy.grid_num,
                    max_price=strategy.max_price,
                    min_price=strategy.min_price,
                    investment=strategy.investment
                )
                
                logger.info(f"网格策略创建成功: {result}")
                return result
                
        except Exception as e:
            logger.error(f"创建网格策略失败: {e}")
            raise TradingToolError(f"创建网格策略失败: {e}")
    
    async def create_dca_strategy(self, strategy: DCAStrategy) -> Dict[str, Any]:
        """创建定投策略"""
        try:
            async with self.okx_service as okx:
                result = await okx.place_dca_order(
                    symbol=strategy.symbol,
                    side=strategy.side,
                    investment=strategy.investment,
                    price_ratio=strategy.price_ratio,
                    take_profit_ratio=strategy.take_profit_ratio
                )
                
                logger.info(f"定投策略创建成功: {result}")
                return result
                
        except Exception as e:
            logger.error(f"创建定投策略失败: {e}")
            raise TradingToolError(f"创建定投策略失败: {e}")
    
    async def get_active_strategies(self) -> List[Dict[str, Any]]:
        """获取活跃策略"""
        try:
            async with self.okx_service as okx:
                strategies = await okx.get_trading_bot_orders()
                
                # 添加详细信息
                for strategy in strategies:
                    strategy['profit_rate_percent'] = strategy.get('profit_rate', 0) * 100
                    strategy['status_text'] = self._get_status_text(strategy.get('state', ''))
                
                return strategies
                
        except Exception as e:
            logger.error(f"获取活跃策略失败: {e}")
            return []
    
    async def stop_strategy(self, algo_id: str, strategy_type: str) -> bool:
        """停止策略"""
        try:
            async with self.okx_service as okx:
                result = await okx.stop_trading_bot(algo_id, strategy_type)
                
                if result:
                    logger.info(f"策略停止成功: {algo_id}")
                
                return result
                
        except Exception as e:
            logger.error(f"停止策略失败: {e}")
            return False
    
    async def get_strategy_recommendations(self, symbols: List[str], 
                                        investment: float = 1000) -> List[StrategyRecommendation]:
        """获取策略建议"""
        recommendations = []
        
        for symbol in symbols:
            try:
                # 并行分析网格和定投机会
                grid_task = self.analyze_grid_opportunity(symbol, investment)
                dca_task = self.analyze_dca_opportunity(symbol, investment)
                
                grid_rec, dca_rec = await asyncio.gather(grid_task, dca_task, return_exceptions=True)
                
                if not isinstance(grid_rec, Exception):
                    recommendations.append(grid_rec)
                
                if not isinstance(dca_rec, Exception):
                    recommendations.append(dca_rec)
                    
            except Exception as e:
                logger.warning(f"分析{symbol}策略失败: {e}")
                continue
        
        # 按推荐度和置信度排序
        recommendations.sort(key=lambda x: (x.recommended, x.confidence), reverse=True)
        
        return recommendations
    
    def _get_status_text(self, state: str) -> str:
        """获取状态文本"""
        status_map = {
            'starting': '启动中',
            'running': '运行中',
            'stopping': '停止中',
            'stopped': '已停止',
            'pause': '暂停',
            'effective': '生效'
        }
        return status_map.get(state, state)