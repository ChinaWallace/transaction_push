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
        """分析网格交易机会 - 集成Kronos预测"""
        try:
            # 检查是否启用Kronos集成
            settings = get_settings()
            if not settings.kronos_config.get('enable_kronos_prediction', False):
                logger.warning(f"Kronos预测功能已禁用，跳过{symbol}网格分析")
                return StrategyRecommendation(
                    symbol=symbol,
                    strategy_type=StrategyType.GRID,
                    recommended=False,
                    confidence=0,
                    parameters={},
                    expected_daily_return=0,
                    expected_annual_return=0,
                    max_drawdown=0,
                    risk_level='high',
                    capital_requirement=investment,
                    reasoning="Kronos预测功能未启用，无法进行网格分析"
                )
            
            async with self.okx_service as okx:
                # 获取历史数据
                klines = await okx.get_kline_data(symbol, '1H', 200)  # 获取更多数据用于Kronos分析
                current_price = await okx.get_current_price(symbol)
                
                if not klines or not current_price:
                    raise TradingToolError(f"无法获取{symbol}数据")
                
                # 1. 使用Kronos进行预测分析
                kronos_prediction = None
                try:
                    from app.services.kronos_prediction_service import get_kronos_service
                    kronos_service = await get_kronos_service()
                    
                    # 准备数据给Kronos
                    import pandas as pd
                    df = pd.DataFrame(klines)
                    df['close'] = df['close'].astype(float)
                    df['open'] = df['open'].astype(float)
                    df['high'] = df['high'].astype(float)
                    df['low'] = df['low'].astype(float)
                    df['volume'] = df['volume'].astype(float)
                    
                    # 获取Kronos预测
                    kronos_prediction = await kronos_service.get_prediction(symbol, df)
                    
                except Exception as e:
                    logger.warning(f"Kronos预测失败，使用传统分析: {e}")
                
                # 2. 传统波动性分析
                prices = [k['close'] for k in klines]
                volatility = np.std(prices) / np.mean(prices)
                price_range = max(prices) - min(prices)
                avg_price = np.mean(prices)
                
                # 3. 获取资金费率信息 - 考虑负费率收益
                funding_rate = 0
                funding_income_annual = 0
                try:
                    funding_data = await okx.get_funding_rate(symbol)
                    funding_rate = funding_data.get('funding_rate', 0)
                    # 计算年化资金费率收益 (每8小时收取一次，一年365*3=1095次)
                    funding_income_annual = abs(funding_rate) * 1095 if funding_rate < 0 else 0
                except Exception as e:
                    logger.warning(f"获取{symbol}资金费率失败: {e}")
                
                # 4. 结合Kronos预测调整网格参数 - 激进但合理的策略
                if kronos_prediction and kronos_prediction.confidence > 0.5:  # 降低置信度要求
                    # 基于Kronos预测调整网格策略
                    predicted_volatility = kronos_prediction.volatility
                    trend_direction = kronos_prediction.trend_direction
                    price_change_pct = kronos_prediction.price_change_pct
                    
                    # 计算趋势强度
                    recent_prices = prices[-24:]  # 最近24小时价格
                    price_trend = (recent_prices[-1] - recent_prices[0]) / recent_prices[0]
                    trend_strength = abs(price_trend)
                    
                    # 网格交易机会评分 - 重新设计更激进的评分系统
                    grid_opportunity_score = 0
                    
                    # 1. 波动率收益潜力 (40分) - 波动率越高，网格收益越大
                    if predicted_volatility > 0.15:  # 超高波动率 >15%
                        grid_opportunity_score += 40
                        volatility_multiplier = 2.5  # 高波动率奖励
                    elif predicted_volatility > 0.10:  # 高波动率 >10%
                        grid_opportunity_score += 35
                        volatility_multiplier = 2.0
                    elif predicted_volatility > 0.06:  # 中高波动率 >6%
                        grid_opportunity_score += 30
                        volatility_multiplier = 1.5
                    elif predicted_volatility > 0.03:  # 中等波动率 >3%
                        grid_opportunity_score += 25
                        volatility_multiplier = 1.2
                    elif predicted_volatility > 0.015:  # 低波动率 >1.5%
                        grid_opportunity_score += 15
                        volatility_multiplier = 1.0
                    else:  # 极低波动率
                        grid_opportunity_score += 5
                        volatility_multiplier = 0.8
                    
                    # 2. 趋势方向适应性 (25分) - 不同趋势采用不同网格策略
                    if trend_direction == 'sideways':
                        grid_opportunity_score += 25  # 横盘最稳定
                        trend_risk_factor = 1.0
                    elif trend_direction == 'bullish':
                        if trend_strength < 0.10:  # 温和上涨，网格可以跟随
                            grid_opportunity_score += 20
                            trend_risk_factor = 1.1  # 轻微增加风险
                        else:  # 强烈上涨，网格容易被突破但收益也大
                            grid_opportunity_score += 15
                            trend_risk_factor = 1.3
                    elif trend_direction == 'bearish':
                        if trend_strength < 0.08:  # 温和下跌，可以做空网格
                            grid_opportunity_score += 18
                            trend_risk_factor = 1.2
                        else:  # 强烈下跌，风险较高但可以获得负费率收益
                            grid_opportunity_score += 10
                            trend_risk_factor = 1.5
                    
                    # 3. 负费率收益加成 (20分) - 重要的额外收益来源
                    if funding_rate < -0.01:  # 强负费率 < -1%
                        grid_opportunity_score += 20
                        funding_bonus = abs(funding_income_annual)
                    elif funding_rate < -0.005:  # 中等负费率 < -0.5%
                        grid_opportunity_score += 15
                        funding_bonus = abs(funding_income_annual)
                    elif funding_rate < 0:  # 轻微负费率
                        grid_opportunity_score += 10
                        funding_bonus = abs(funding_income_annual)
                    else:  # 正费率或零费率
                        grid_opportunity_score += 0
                        funding_bonus = 0
                    
                    # 4. Kronos预测置信度 (15分)
                    if kronos_prediction.confidence > 0.8:
                        grid_opportunity_score += 15
                    elif kronos_prediction.confidence > 0.7:
                        grid_opportunity_score += 12
                    elif kronos_prediction.confidence > 0.6:
                        grid_opportunity_score += 10
                    elif kronos_prediction.confidence > 0.5:
                        grid_opportunity_score += 8
                    
                    # 降低推荐门槛，只要有60分以上就可以考虑
                    if grid_opportunity_score >= 60:
                        # 根据趋势和波动率动态调整网格参数
                        if trend_direction == 'sideways':
                            # 横盘震荡：对称网格，根据波动率调整区间
                            price_range_factor = min(0.20, max(0.08, predicted_volatility * 2))
                            max_price = current_price * (1 + price_range_factor)
                            min_price = current_price * (1 - price_range_factor)
                        elif trend_direction == 'bullish':
                            # 上涨趋势：网格区间偏上，为突破留空间
                            price_range_factor = min(0.25, max(0.10, predicted_volatility * 2.5))
                            max_price = current_price * (1 + price_range_factor * 1.2)
                            min_price = current_price * (1 - price_range_factor * 0.8)
                        elif trend_direction == 'bearish':
                            # 下跌趋势：网格区间偏下，可获得负费率收益
                            price_range_factor = min(0.25, max(0.10, predicted_volatility * 2.5))
                            max_price = current_price * (1 + price_range_factor * 0.8)
                            min_price = current_price * (1 - price_range_factor * 1.2)
                        
                        # 根据波动率动态调整网格数量 - 波动率越高，网格越密
                        if predicted_volatility > 0.15:  # 超高波动率
                            grid_num = min(30, max(15, int(predicted_volatility * 120)))
                        elif predicted_volatility > 0.08:  # 高波动率
                            grid_num = min(20, max(12, int(predicted_volatility * 150)))
                        elif predicted_volatility > 0.04:  # 中等波动率
                            grid_num = min(15, max(8, int(predicted_volatility * 200)))
                        else:  # 低波动率
                            grid_num = min(10, max(6, int(predicted_volatility * 250)))
                        
                        # 计算网格交易收益预期
                        grid_spacing = (max_price - min_price) / grid_num
                        
                        # 每次网格交易的利润率 (考虑手续费)
                        profit_per_grid = grid_spacing * 0.004  # 0.4%的利润率 (扣除手续费后)
                        
                        # 基于波动率估算每日交易频率
                        # 高波动率 = 更多交易机会，但也要考虑趋势风险
                        base_daily_trades = predicted_volatility * 50 * volatility_multiplier
                        
                        # 根据趋势调整交易频率
                        if trend_direction == 'sideways':
                            daily_trades = base_daily_trades  # 横盘最稳定
                        elif trend_direction in ['bullish', 'bearish']:
                            daily_trades = base_daily_trades * 0.7  # 趋势市场减少频率
                        
                        # 限制每日最大交易次数 (避免过度乐观)
                        daily_trades = min(daily_trades, grid_num * 3)
                        
                        # 计算每日网格收益
                        daily_grid_return = (daily_trades * profit_per_grid) / investment
                        
                        # 加上负费率收益 (如果有的话)
                        daily_funding_return = funding_income_annual / 365 if funding_bonus > 0 else 0
                        
                        # 总的每日预期收益
                        expected_daily_return = daily_grid_return + daily_funding_return
                        
                        # 根据风险调整收益预期
                        risk_adjusted_return = expected_daily_return / trend_risk_factor
                        
                        # 设置合理的收益上限 (避免过度乐观)
                        final_daily_return = min(risk_adjusted_return, 0.025)  # 最高日收益2.5%
                        
                        confidence = min(95, grid_opportunity_score)
                        recommended = True
                        
                        reasoning = f"网格机会评分: {grid_opportunity_score}/100, Kronos预测: {trend_direction}(强度:{trend_strength:.2%}), 置信度: {kronos_prediction.confidence:.1%}, 波动率: {predicted_volatility:.3f}, 资金费率: {funding_rate:.4f}, 预期日收益: {final_daily_return:.2%}"
                        
                        # 更新变量名以保持一致性
                        expected_daily_return = final_daily_return
                        grid_suitability_score = grid_opportunity_score
                        
                    else:
                        recommended = False
                        confidence = 0
                        expected_daily_return = 0
                        grid_suitability_score = grid_opportunity_score
                        reasoning = f"网格机会评分不足: {grid_opportunity_score}/100, 当前市场条件收益潜力有限"
                    
                else:
                    # 没有Kronos预测时，不推荐网格交易
                    confidence_msg = f"({kronos_prediction.confidence:.1%} < 60%)" if kronos_prediction else "预测不可用"
                    logger.warning(f"{symbol} Kronos预测不可用或置信度过低，不推荐网格交易")
                    return StrategyRecommendation(
                        symbol=symbol,
                        strategy_type=StrategyType.GRID,
                        recommended=False,
                        confidence=0,
                        parameters={},
                        expected_daily_return=0,
                        expected_annual_return=0,
                        max_drawdown=0,
                        risk_level='high',
                        capital_requirement=investment,
                        reasoning=f"Kronos预测不可用或置信度过低{confidence_msg}，网格交易需要高置信度的横盘或弱趋势预测"
                    )
                
                return StrategyRecommendation(
                    symbol=symbol,
                    strategy_type=StrategyType.GRID,
                    recommended=recommended,
                    confidence=confidence,
                    parameters={
                        'grid_num': grid_num if recommended else 0,
                        'max_price': max_price if recommended else 0,
                        'min_price': min_price if recommended else 0,
                        'investment': investment,
                        'current_price': current_price,
                        'kronos_confidence': kronos_prediction.confidence if kronos_prediction else 0,
                        'predicted_trend': trend_direction if kronos_prediction else 'unknown',
                        'grid_suitability_score': grid_suitability_score if 'grid_suitability_score' in locals() else 0,
                        'trend_strength': trend_strength if 'trend_strength' in locals() else 0,
                        'predicted_volatility': predicted_volatility if 'predicted_volatility' in locals() else 0,
                        'funding_rate': funding_rate,
                        'funding_income_annual': funding_income_annual,
                        'daily_grid_return': daily_grid_return if 'daily_grid_return' in locals() else 0,
                        'daily_funding_return': daily_funding_return if 'daily_funding_return' in locals() else 0,
                        'volatility_multiplier': volatility_multiplier if 'volatility_multiplier' in locals() else 1,
                        'trend_risk_factor': trend_risk_factor if 'trend_risk_factor' in locals() else 1
                    },
                    expected_daily_return=expected_daily_return,
                    expected_annual_return=expected_daily_return * 365,
                    max_drawdown=0.20 if trend_direction == 'bearish' else 0.15 if recommended else 0.30,
                    risk_level='low' if recommended and confidence > 85 else 'medium' if recommended and confidence > 70 else 'high',
                    capital_requirement=investment,
                    reasoning=reasoning
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