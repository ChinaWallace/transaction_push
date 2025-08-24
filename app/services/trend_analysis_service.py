# -*- coding: utf-8 -*-
"""
趋势分析服务
Trend analysis service with SuperTrend multi-timeframe analysis
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import asyncio

from app.core.logging import get_logger, trading_logger
from app.services.binance_service import BinanceService
from app.services.okx_service import OKXService
from app.utils.indicators import SuperTrendIndicator
from app.utils.exceptions import IndicatorCalculationError, DataNotFoundError
from app.models.signal import TrendSignal, SuperTrendData

logger = get_logger(__name__)


class SignalLevel(Enum):
    """信号级别枚举"""
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"
    WATCH = "watch"


class TrendDirection(Enum):
    """趋势方向枚举"""
    UP = "up"
    DOWN = "down"
    UNCLEAR = "unclear"


@dataclass
class SignalCombination:
    """信号组合"""
    combination_id: str
    name: str
    strategy: str
    level: SignalLevel
    description: str


class TrendAnalysisService:
    """趋势分析服务类"""
    
    # 信号组合定义（基于Java项目的策略）
    SIGNAL_COMBINATIONS = {
        "1": SignalCombination(
            combination_id="1",
            name="强势多头共振",
            strategy="坚决做多，分批建仓",
            level=SignalLevel.STRONG,
            description="多周期共振做多信号，建议立即建仓"
        ),
        "2": SignalCombination(
            combination_id="2", 
            name="回调中多头",
            strategy="等待回调结束再做多",
            level=SignalLevel.MEDIUM,
            description="15分钟回调中，建议等待短线企稳再介入"
        ),
        "3": SignalCombination(
            combination_id="3",
            name="短线反弹",
            strategy="快进快出短多单",
            level=SignalLevel.MEDIUM,
            description="主趋势尚未上转，短多注意止盈"
        ),
        "4": SignalCombination(
            combination_id="4",
            name="背离多头",
            strategy="快进快出或控制仓位",
            level=SignalLevel.MEDIUM,
            description="中期方向背离，短线多单谨慎介入"
        ),
        "5": SignalCombination(
            combination_id="5",
            name="强势空头共振",
            strategy="做空为主，顺势操作",
            level=SignalLevel.STRONG,
            description="多周期共振做空信号，建议空单建仓"
        ),
        "6": SignalCombination(
            combination_id="6",
            name="短线反弹",
            strategy="反弹做空，设好止损",
            level=SignalLevel.MEDIUM,
            description="短线反弹，空单择机进场"
        ),
        "7": SignalCombination(
            combination_id="7",
            name="反转尝试",
            strategy="多单试探介入",
            level=SignalLevel.WEAK,
            description="1h向上尝试反转，日线空需谨慎"
        ),
        "8": SignalCombination(
            combination_id="8",
            name="底部反转",
            strategy="尝试底部建仓",
            level=SignalLevel.MEDIUM,
            description="潜在底部反转，建议轻仓入场观察"
        ),
        "9": SignalCombination(
            combination_id="9",
            name="回调确认",
            strategy="等待趋势重转，再介入",
            level=SignalLevel.WATCH,
            description="回调未止，暂不入场"
        ),
        "10": SignalCombination(
            combination_id="10",
            name="信号混乱",
            strategy="不建议操作，观望为主",
            level=SignalLevel.WATCH,
            description="信号混乱，建议暂不交易"
        )
    }
    
    def __init__(self, exchange: str = 'okx'):
        self.exchange = exchange.lower()
        if self.exchange == 'okx':
            self.exchange_service = OKXService()
        else:
            self.exchange_service = BinanceService()
        self.supertrend_indicator = SuperTrendIndicator(period=10, multiplier=3.0)
        self.timeframes = ['1d', '4h', '1h', '15m']
    
    async def analyze_symbol(self, symbol: str, 
                           custom_data: Optional[Dict[str, List[dict]]] = None) -> Dict[str, Any]:
        """
        分析单个交易对的趋势信号 - 别名方法
        
        Args:
            symbol: 交易对符号
            custom_data: 自定义数据
            
        Returns:
            趋势分析结果
        """
        return await self.analyze_multi_timeframe_signal(symbol, custom_data)
    
    async def analyze_multi_timeframe_signal(self, symbol: str, 
                                           custom_data: Optional[Dict[str, List[dict]]] = None) -> Dict[str, Any]:
        """
        多周期趋势信号分析
        
        Args:
            symbol: 交易对
            custom_data: 自定义数据，格式为 {timeframe: klines}
            
        Returns:
            分析结果
        """
        try:
            # 获取多周期数据
            if custom_data:
                timeframe_data = custom_data
            else:
                timeframe_data = await self.exchange_service.get_multi_timeframe_klines(
                    symbol, self.timeframes, limit=100
                )
            
            # 计算各周期的SuperTrend
            trends = {}
            for timeframe in self.timeframes:
                if timeframe in timeframe_data:
                    klines = timeframe_data[timeframe]
                    if klines:
                        # 计算SuperTrend
                        enriched_klines = self.supertrend_indicator.calculate_from_klines(klines)
                        
                        # 获取最新趋势
                        latest_kline = enriched_klines[-1]
                        supertrend_dir = latest_kline.get('supertrend_direction')
                        
                        # 调试日志
                        logger.info(f"SuperTrend for {symbol} {timeframe}: direction={supertrend_dir}, close={latest_kline.get('close_price', latest_kline.get('close'))}, supertrend={latest_kline.get('supertrend_value')}")
                        
                        if supertrend_dir is not None:
                            # supertrend_direction 现在是字符串 'up' 或 'down'
                            trends[timeframe] = TrendDirection.UP if supertrend_dir == 'up' else TrendDirection.DOWN
                        else:
                            trends[timeframe] = TrendDirection.UNCLEAR
                    else:
                        trends[timeframe] = TrendDirection.UNCLEAR
                else:
                    trends[timeframe] = TrendDirection.UNCLEAR
            
            # 判断信号组合
            signal_combination = self._determine_signal_combination(trends)
            
            # 计算置信度
            confidence_score = self._calculate_confidence_score(trends, signal_combination)
            
            # 获取当前价格 - 智能字段名处理
            current_price = None
            if '15m' in timeframe_data and timeframe_data['15m']:
                latest_kline = timeframe_data['15m'][-1]
                # 尝试多种可能的字段名
                if 'close_price' in latest_kline:
                    current_price = float(latest_kline['close_price'])
                elif 'close' in latest_kline:
                    current_price = float(latest_kline['close'])
                else:
                    # 寻找包含close的字段
                    for key in latest_kline.keys():
                        if 'close' in key.lower():
                            current_price = float(latest_kline[key])
                            break
            
            # 构建结果
            result = {
                'symbol': symbol,
                'timestamp': datetime.now(),
                'trends': {
                    'daily': trends.get('1d', TrendDirection.UNCLEAR).value,
                    'h4': trends.get('4h', TrendDirection.UNCLEAR).value,
                    'h1': trends.get('1h', TrendDirection.UNCLEAR).value,
                    'm15': trends.get('15m', TrendDirection.UNCLEAR).value
                },
                'signal_combination': signal_combination,
                'signal_level': signal_combination.level.value,
                'strategy_advice': signal_combination.strategy,
                'confidence_score': confidence_score,
                'current_price': current_price,
                'should_notify': signal_combination.level != SignalLevel.WATCH
            }
            
            trading_logger.info(f"Trend analysis completed for {symbol}: {signal_combination.name} ({signal_combination.level.value})")
            
            return result
            
        except Exception as e:
            logger.error(f"Multi-timeframe analysis failed for {symbol}: {e}")
            raise IndicatorCalculationError(f"Trend analysis failed: {e}")
    
    def _determine_signal_combination(self, trends: Dict[str, TrendDirection]) -> SignalCombination:
        """
        根据趋势组合判断信号类型
        
        Args:
            trends: 各周期趋势字典
            
        Returns:
            信号组合
        """
        daily = trends.get('1d', TrendDirection.UNCLEAR)
        h4 = trends.get('4h', TrendDirection.UNCLEAR)
        h1 = trends.get('1h', TrendDirection.UNCLEAR)
        m15 = trends.get('15m', TrendDirection.UNCLEAR)
        
        
        # 根据Java项目的逻辑判断信号组合
        if (daily == TrendDirection.UP and h4 == TrendDirection.UP and 
            h1 == TrendDirection.UP and m15 == TrendDirection.UP):
            return self.SIGNAL_COMBINATIONS["1"]  # 强势多头共振
        
        elif (daily == TrendDirection.UP and h4 == TrendDirection.UP and 
              h1 == TrendDirection.UP and m15 == TrendDirection.DOWN):
            return self.SIGNAL_COMBINATIONS["2"]  # 回调中多头
        
        elif (daily == TrendDirection.UP and h4 == TrendDirection.UP and 
              h1 == TrendDirection.DOWN and m15 == TrendDirection.UP):
            return self.SIGNAL_COMBINATIONS["3"]  # 短线反弹
        
        elif (daily == TrendDirection.UP and h4 == TrendDirection.DOWN and 
              h1 == TrendDirection.UP and m15 == TrendDirection.UP):
            return self.SIGNAL_COMBINATIONS["4"]  # 背离多头
        
        elif (daily == TrendDirection.DOWN and h4 == TrendDirection.DOWN and 
              h1 == TrendDirection.DOWN and m15 == TrendDirection.DOWN):
            return self.SIGNAL_COMBINATIONS["5"]  # 强势空头共振
        
        elif (daily == TrendDirection.DOWN and h4 == TrendDirection.DOWN and 
              h1 == TrendDirection.DOWN and m15 == TrendDirection.UP):
            return self.SIGNAL_COMBINATIONS["6"]  # 短线反弹
        
        elif (daily == TrendDirection.DOWN and h4 == TrendDirection.DOWN and 
              h1 == TrendDirection.UP and m15 == TrendDirection.UP):
            return self.SIGNAL_COMBINATIONS["7"]  # 反转尝试
        
        elif (daily == TrendDirection.DOWN and h4 == TrendDirection.UP and 
              h1 == TrendDirection.UP and m15 == TrendDirection.UP):
            return self.SIGNAL_COMBINATIONS["8"]  # 底部反转
        
        elif (daily == TrendDirection.UP and h4 == TrendDirection.UP and 
              h1 == TrendDirection.DOWN and m15 == TrendDirection.DOWN):
            return self.SIGNAL_COMBINATIONS["9"]  # 回调确认
        
        else:
            return self.SIGNAL_COMBINATIONS["10"]  # 信号混乱
    
    def _calculate_confidence_score(self, trends: Dict[str, TrendDirection], 
                                  signal_combination: SignalCombination) -> float:
        """
        计算信号置信度分数
        
        Args:
            trends: 趋势字典
            signal_combination: 信号组合
            
        Returns:
            置信度分数 (0-1)
        """
        # 统计明确趋势的数量
        clear_trends = sum(1 for trend in trends.values() if trend != TrendDirection.UNCLEAR)
        total_trends = len(trends)
        
        # 基础置信度
        base_confidence = clear_trends / total_trends if total_trends > 0 else 0
        
        # 根据信号级别调整
        level_multiplier = {
            SignalLevel.STRONG: 1.0,
            SignalLevel.MEDIUM: 0.8,
            SignalLevel.WEAK: 0.6,
            SignalLevel.WATCH: 0.4
        }
        
        multiplier = level_multiplier.get(signal_combination.level, 0.5)
        confidence_score = base_confidence * multiplier
        
        return round(confidence_score, 4)
    
    async def analyze_batch_symbols(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量分析多个交易对
        
        Args:
            symbols: 交易对列表
            
        Returns:
            分析结果字典
        """
        try:
            tasks = []
            for symbol in symbols:
                task = self.analyze_multi_timeframe_signal(symbol)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            analysis_results = {}
            for i, result in enumerate(results):
                symbol = symbols[i]
                if isinstance(result, Exception):
                    logger.error(f"Analysis failed for {symbol}: {result}")
                    analysis_results[symbol] = {
                        'error': str(result),
                        'symbol': symbol,
                        'timestamp': datetime.now()
                    }
                else:
                    analysis_results[symbol] = result
            
            return analysis_results
            
        except Exception as e:
            logger.error(f"Batch analysis failed: {e}")
            raise
    
    async def analyze_historical_signals(self, symbol: str, days: int = 30) -> List[Dict[str, Any]]:
        """
        分析历史信号变化
        
        Args:
            symbol: 交易对
            days: 回溯天数
            
        Returns:
            历史信号列表
        """
        try:
            # 获取历史数据
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)
            
            # 获取15分钟数据作为主时间轴
            klines_15m = await self.exchange_service.get_kline_data(
                symbol, '15m', limit=96 * days, start_time=start_time, end_time=end_time
            )
            
            if not klines_15m:
                raise DataNotFoundError(f"No historical data found for {symbol}")
            
            historical_signals = []
            previous_signal = None
            
            # 每20个15分钟周期分析一次（5小时间隔）
            for i in range(100, len(klines_15m), 20):
                current_time = klines_15m[i]['close_time']
                
                try:
                    # 构建当前时间点的数据切片
                    timeframe_data = await self._build_historical_data_slice(
                        symbol, current_time, i, klines_15m
                    )
                    
                    # 分析当前信号
                    current_result = await self.analyze_multi_timeframe_signal(
                        symbol, timeframe_data
                    )
                    
                    # 检测信号变化
                    if self._is_signal_changed(previous_signal, current_result):
                        historical_signals.append({
                            'timestamp': current_time,
                            'signal_data': current_result,
                            'change_type': 'new' if previous_signal is None else 'change',
                            'previous_signal': previous_signal['signal_combination'].name if previous_signal else None,
                            'current_signal': current_result['signal_combination'].name
                        })
                    
                    previous_signal = current_result
                    
                except Exception as e:
                    logger.warning(f"Failed to analyze historical point {current_time}: {e}")
                    continue
            
            trading_logger.info(f"Historical analysis completed for {symbol}: {len(historical_signals)} signal changes")
            return historical_signals
            
        except Exception as e:
            logger.error(f"Historical analysis failed for {symbol}: {e}")
            raise
    
    async def _build_historical_data_slice(self, symbol: str, current_time: datetime, 
                                         index: int, klines_15m: List[dict]) -> Dict[str, List[dict]]:
        """构建历史数据切片"""
        # 这里简化处理，实际应该根据时间戳获取各周期对应的历史数据
        # 为了演示，我们假设有相应的数据
        return {
            '1d': klines_15m[max(0, index-96):index+1:96],  # 取每96个点作为日线近似
            '4h': klines_15m[max(0, index-16):index+1:16],  # 取每16个点作为4小时近似
            '1h': klines_15m[max(0, index-4):index+1:4],    # 取每4个点作为1小时近似
            '15m': klines_15m[max(0, index-20):index+1]      # 最近20个15分钟点
        }
    
    def _is_signal_changed(self, previous: Optional[Dict[str, Any]], 
                          current: Dict[str, Any]) -> bool:
        """检测信号是否发生变化"""
        if previous is None:
            return True
        
        return (previous['signal_combination'].combination_id != 
                current['signal_combination'].combination_id)
    
    def format_signal_notification(self, signal_data: Dict[str, Any]) -> str:
        """格式化信号通知消息"""
        symbol = signal_data['symbol']
        trends = signal_data['trends']
        combination = signal_data['signal_combination']
        price = signal_data.get('current_price', 'N/A')
        confidence = signal_data.get('confidence_score', 0)
        timestamp = signal_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        
        # 趋势图标和中文描述映射
        trend_mapping = {
            'up': {'icon': '📈', 'text': '上涨'},
            'down': {'icon': '📉', 'text': '下跌'},
            'unclear': {'icon': '➖', 'text': '不明'}
        }
        
        # 级别图标映射
        level_icons = {
            'strong': '🔵',
            'medium': '🟡', 
            'weak': '🟠',
            'watch': '⚪'
        }
        
        # 获取趋势描述
        daily_trend = trend_mapping.get(trends['daily'], {'icon': '➖', 'text': '不明'})
        h4_trend = trend_mapping.get(trends['h4'], {'icon': '➖', 'text': '不明'})
        h1_trend = trend_mapping.get(trends['h1'], {'icon': '➖', 'text': '不明'})
        m15_trend = trend_mapping.get(trends['m15'], {'icon': '➖', 'text': '不明'})
        
        message = f"""📊 【交易信号 - {symbol}】

🕐 多周期趋势分析：
├ 日线：{daily_trend['icon']} {daily_trend['text']}
├ 4小时：{h4_trend['icon']} {h4_trend['text']}
├ 1小时：{h1_trend['icon']} {h1_trend['text']}
└ 15分钟：{m15_trend['icon']} {m15_trend['text']}

{level_icons.get(signal_data['signal_level'], '⚪')} {combination.name}

{self._get_signal_emoji(combination.name)} {combination.description}

💡 策略建议：{combination.strategy}

💰 当前价格：${price}
📊 置信度：{confidence:.1%}

⏰ 分析时间：{timestamp}

📝 注：多周期共振信号更可靠，请结合风险管理操作！"""
        
        return message
    
    def _get_signal_emoji(self, signal_name: str) -> str:
        """根据信号名称获取对应的emoji"""
        emoji_map = {
            '强势多头共振': '✅',
            '回调中多头': '🔄',
            '短线反弹': '⚠️',
            '背离多头': '🚨',
            '强势空头共振': '⛔',
            '反转尝试': '🔄',
            '底部反转': '🔁',
            '回调确认': '🔍',
            '信号混乱': '❔'
        }
        return emoji_map.get(signal_name, '📈')
