# -*- coding: utf-8 -*-
"""
Kronos 时间框架管理器
Kronos Timeframe Manager

管理短线和中线预测模式，优化不同交易周期的预测效果
"""

from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.error_analyzer import analyze_and_log_error
from app.utils.system_diagnostics import record_system_error

logger = get_logger(__name__)


class TradingMode(Enum):
    """交易模式"""
    SHORT_TERM = "short_term"    # 短线交易 (日内)
    MEDIUM_TERM = "medium_term"  # 中线交易 (持仓几天)
    AUTO = "auto"                # 自动选择


class MarketRegime(Enum):
    """市场状态"""
    TRENDING_UP = "trending_up"      # 上涨趋势
    TRENDING_DOWN = "trending_down"  # 下跌趋势
    SIDEWAYS = "sideways"            # 横盘震荡
    HIGH_VOLATILITY = "high_vol"     # 高波动
    LOW_VOLATILITY = "low_vol"       # 低波动


@dataclass
class TimeframeConfig:
    """时间框架配置"""
    timeframe: str              # K线周期 (1h, 4h等)
    lookback_periods: int       # 回看周期数
    prediction_horizon: int     # 预测时间范围(小时)
    confidence_threshold: float # 置信度阈值
    signal_thresholds: Dict[str, float]  # 信号阈值
    trend_confirmation: Dict[str, float] # 趋势确认参数


@dataclass
class PredictionContext:
    """预测上下文"""
    symbol: str
    trading_mode: TradingMode
    market_regime: MarketRegime
    volatility: float
    trend_strength: float
    timeframe_config: TimeframeConfig
    multi_timeframe_data: Optional[Dict[str, Any]] = None


class KronosTimeframeManager:
    """Kronos 时间框架管理器"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.kronos_config = self.settings.kronos_config
        
        # 加载配置
        self._load_timeframe_configs()
        
        # 缓存
        self._market_regime_cache: Dict[str, Tuple[MarketRegime, datetime]] = {}
        self._volatility_cache: Dict[str, Tuple[float, datetime]] = {}
        
        # 缓存过期时间
        self.cache_duration = timedelta(minutes=15)
    
    def _load_timeframe_configs(self):
        """加载时间框架配置"""
        # 短线配置
        short_config = self.kronos_config.get('short_term', {})
        self.short_term_config = TimeframeConfig(
            timeframe=short_config.get('timeframe', '1H'),
            lookback_periods=short_config.get('lookback_periods', 48),
            prediction_horizon=short_config.get('prediction_horizon', 6),
            confidence_threshold=short_config.get('confidence_threshold', 0.35),
            signal_thresholds=short_config.get('signal_thresholds', {
                'strong_buy': 0.75, 'buy': 0.60, 'hold': 0.45,
                'sell': 0.60, 'strong_sell': 0.75
            }),
            trend_confirmation=short_config.get('trend_confirmation', {
                'bullish_threshold': 0.80,
                'bearish_threshold': 0.80,
                'price_change_threshold': 0.08
            })
        )
        
        # 中线配置
        medium_config = self.kronos_config.get('medium_term', {})
        self.medium_term_config = TimeframeConfig(
            timeframe=medium_config.get('timeframe', '4H'),
            lookback_periods=medium_config.get('lookback_periods', 72),
            prediction_horizon=medium_config.get('prediction_horizon', 24),
            confidence_threshold=medium_config.get('confidence_threshold', 0.30),
            signal_thresholds=medium_config.get('signal_thresholds', {
                'strong_buy': 0.70, 'buy': 0.55, 'hold': 0.40,
                'sell': 0.55, 'strong_sell': 0.70
            }),
            trend_confirmation=medium_config.get('trend_confirmation', {
                'bullish_threshold': 0.70,
                'bearish_threshold': 0.70,
                'price_change_threshold': 0.06
            })
        )
        
        # 多时间框架配置
        self.multi_timeframe_config = self.kronos_config.get('multi_timeframe_analysis', {})
        
        self.logger.info("✅ Kronos 时间框架配置加载完成")
        self.logger.info(f"📊 短线配置: {self.short_term_config.timeframe} K线, {self.short_term_config.prediction_horizon}小时预测")
        self.logger.info(f"📊 中线配置: {self.medium_term_config.timeframe} K线, {self.medium_term_config.prediction_horizon}小时预测")
    
    async def get_optimal_config(
        self, 
        symbol: str, 
        preferred_mode: Optional[TradingMode] = None
    ) -> PredictionContext:
        """获取最优预测配置"""
        try:
            # 1. 确定交易模式
            if preferred_mode:
                trading_mode = preferred_mode
            elif self.kronos_config.get('auto_mode_selection', True):
                trading_mode = await self._auto_select_mode(symbol)
            else:
                default_mode = self.kronos_config.get('default_mode', 'short_term')
                trading_mode = TradingMode(default_mode)
            
            # 2. 分析市场状态
            market_regime = await self._analyze_market_regime(symbol)
            volatility = await self._calculate_volatility(symbol)
            trend_strength = await self._calculate_trend_strength(symbol)
            
            # 3. 选择时间框架配置
            if trading_mode == TradingMode.SHORT_TERM:
                timeframe_config = self.short_term_config
            else:
                timeframe_config = self.medium_term_config
            
            # 4. 根据市场状态调整配置
            adjusted_config = self._adjust_config_for_market(
                timeframe_config, market_regime, volatility
            )
            
            # 5. 准备多时间框架数据
            multi_timeframe_data = None
            if self.multi_timeframe_config.get('enabled', True):
                multi_timeframe_data = await self._prepare_multi_timeframe_data(symbol)
            
            context = PredictionContext(
                symbol=symbol,
                trading_mode=trading_mode,
                market_regime=market_regime,
                volatility=volatility,
                trend_strength=trend_strength,
                timeframe_config=adjusted_config,
                multi_timeframe_data=multi_timeframe_data
            )
            
            self.logger.info(f"🎯 {symbol} 最优配置: {trading_mode.value}, {market_regime.value}, 波动率{volatility:.3f}")
            return context
            
        except Exception as e:
            self.logger.error(f"❌ 获取 {symbol} 最优配置失败: {e}")
            # 返回默认短线配置
            return PredictionContext(
                symbol=symbol,
                trading_mode=TradingMode.SHORT_TERM,
                market_regime=MarketRegime.SIDEWAYS,
                volatility=0.05,
                trend_strength=0.5,
                timeframe_config=self.short_term_config
            )
    
    async def _auto_select_mode(self, symbol: str) -> TradingMode:
        """自动选择交易模式"""
        try:
            # 获取市场数据进行分析
            from app.services.exchanges.service_manager import get_exchange_service
            exchange_service = await get_exchange_service()
            
            # 获取不同周期的数据
            daily_data = await exchange_service.get_kline_data(symbol, '1D', 7)  # 7天日线
            hourly_data = await exchange_service.get_kline_data(symbol, '1H', 24)  # 24小时线
            
            if not daily_data or not hourly_data:
                return TradingMode.SHORT_TERM  # 默认短线
            
            # 计算波动率
            daily_volatility = self._calculate_data_volatility(daily_data)
            hourly_volatility = self._calculate_data_volatility(hourly_data)
            
            # 计算趋势强度
            trend_strength = self._calculate_data_trend_strength(daily_data)
            
            # 决策逻辑
            if daily_volatility > 0.15:  # 高波动环境
                return TradingMode.SHORT_TERM  # 适合短线
            elif trend_strength > 0.7:  # 强趋势环境
                return TradingMode.MEDIUM_TERM  # 适合中线
            elif hourly_volatility > daily_volatility * 2:  # 短期波动明显
                return TradingMode.SHORT_TERM
            else:
                return TradingMode.MEDIUM_TERM  # 默认中线
                
        except Exception as e:
            # 记录到系统诊断
            record_system_error(e, {'symbol': symbol, 'operation': 'auto_select_mode'})
            
            # 使用错误分析器提供详细的错误诊断
            analysis = analyze_and_log_error(
                error=e,
                context={'symbol': symbol, 'operation': 'auto_select_mode'},
                operation_name=f"自动选择 {symbol} 交易模式"
            )
            
            # 如果是可恢复的错误，记录建议
            if analysis.is_recoverable:
                self.logger.info(f"💡 {symbol} 自动模式选择失败但可恢复，使用默认短线模式")
            
            return TradingMode.SHORT_TERM
    
    async def _analyze_market_regime(self, symbol: str) -> MarketRegime:
        """分析市场状态"""
        # 检查缓存
        if symbol in self._market_regime_cache:
            regime, timestamp = self._market_regime_cache[symbol]
            if datetime.now() - timestamp < self.cache_duration:
                return regime
        
        try:
            from app.services.exchanges.service_manager import get_exchange_service
            exchange_service = await get_exchange_service()
            
            # 获取数据
            klines = await exchange_service.get_kline_data(symbol, '1H', 48)  # 48小时数据
            if not klines or len(klines) < 20:
                return MarketRegime.SIDEWAYS
            
            # 计算价格变化 - 修复数据格式问题
            # klines 现在是字典格式，不是列表格式
            prices = [float(k['close']) for k in klines]  # 收盘价
            price_changes = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
            
            # 计算趋势
            recent_change = (prices[-1] - prices[0]) / prices[0]
            volatility = sum(abs(change) for change in price_changes) / len(price_changes)
            
            # 判断市场状态
            if abs(recent_change) < 0.02:  # 2%以内为横盘
                regime = MarketRegime.SIDEWAYS
            elif recent_change > 0.05:  # 5%以上为上涨趋势
                regime = MarketRegime.TRENDING_UP
            elif recent_change < -0.05:  # -5%以下为下跌趋势
                regime = MarketRegime.TRENDING_DOWN
            elif volatility > 0.1:  # 高波动
                regime = MarketRegime.HIGH_VOLATILITY
            else:
                regime = MarketRegime.LOW_VOLATILITY
            
            # 更新缓存
            self._market_regime_cache[symbol] = (regime, datetime.now())
            return regime
            
        except Exception as e:
            # 使用错误分析器提供详细的错误诊断
            analysis = analyze_and_log_error(
                error=e,
                context={'symbol': symbol, 'operation': 'analyze_market_regime'},
                operation_name=f"分析 {symbol} 市场状态"
            )
            
            # 如果是可恢复的网络错误，使用缓存数据
            if analysis.is_recoverable and symbol in self._market_regime_cache:
                cached_regime, _ = self._market_regime_cache[symbol]
                self.logger.info(f"🔄 {symbol} 市场状态分析失败，使用缓存数据: {cached_regime.value}")
                return cached_regime
            
            return MarketRegime.SIDEWAYS
    
    async def _calculate_volatility(self, symbol: str) -> float:
        """计算波动率"""
        # 检查缓存
        if symbol in self._volatility_cache:
            volatility, timestamp = self._volatility_cache[symbol]
            if datetime.now() - timestamp < self.cache_duration:
                return volatility
        
        try:
            from app.services.exchanges.service_manager import get_exchange_service
            exchange_service = await get_exchange_service()
            
            klines = await exchange_service.get_kline_data(symbol, '1H', 24)
            if not klines or len(klines) < 2:
                return 0.05  # 默认波动率
            
            volatility = self._calculate_data_volatility(klines)
            
            # 更新缓存
            self._volatility_cache[symbol] = (volatility, datetime.now())
            return volatility
            
        except Exception as e:
            # 改进异常日志，提供更详细的错误信息
            error_type = type(e).__name__
            error_msg = str(e)
            self.logger.warning(f"⚠️ 计算 {symbol} 波动率失败 [{error_type}]: {error_msg}")
            self.logger.debug(f"🔍 波动率计算失败详情 - 交易对: {symbol}, 异常类型: {error_type}, 异常信息: {error_msg}")
            return 0.05
    
    def _calculate_data_volatility(self, klines: List[Dict[str, Any]]) -> float:
        """从K线数据计算波动率"""
        if len(klines) < 2:
            return 0.05
        
        # 提取收盘价数据 - 修复数据格式问题
        prices = self._extract_close_prices(klines)
        
        if len(prices) < 2:
            return 0.05
        
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        
        # 计算标准差
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        volatility = variance ** 0.5
        
        return volatility
    
    def _extract_close_prices(self, klines: List[Dict[str, Any]]) -> List[float]:
        """提取收盘价数据 - 兼容不同数据格式"""
        prices = []
        for k in klines:
            try:
                if isinstance(k, dict):
                    # 字典格式: {'close': 45000.0, ...}
                    prices.append(float(k['close']))
                elif isinstance(k, (list, tuple)) and len(k) >= 5:
                    # 列表格式: [timestamp, open, high, low, close, volume]
                    prices.append(float(k[4]))
                else:
                    self.logger.warning(f"⚠️ 未知的K线数据格式: {type(k)} - {k}")
                    continue
            except (KeyError, ValueError, IndexError) as e:
                self.logger.warning(f"⚠️ 提取收盘价失败: {k}, 错误: {e}")
                continue
        return prices
    
    async def _calculate_trend_strength(self, symbol: str) -> float:
        """计算趋势强度"""
        try:
            from app.services.exchanges.service_manager import get_exchange_service
            exchange_service = await get_exchange_service()
            
            klines = await exchange_service.get_kline_data(symbol, '4H', 24)  # 4天数据
            if not klines:
                return 0.5
            
            return self._calculate_data_trend_strength(klines)
            
        except Exception as e:
            # 改进异常日志，提供更详细的错误信息
            error_type = type(e).__name__
            error_msg = str(e)
            self.logger.warning(f"⚠️ 计算 {symbol} 趋势强度失败 [{error_type}]: {error_msg}")
            self.logger.debug(f"🔍 趋势强度计算失败详情 - 交易对: {symbol}, 异常类型: {error_type}, 异常信息: {error_msg}")
            return 0.5
    
    def _calculate_data_trend_strength(self, klines: List[Dict[str, Any]]) -> float:
        """从K线数据计算趋势强度"""
        if len(klines) < 10:
            return 0.5
        
        # 提取收盘价数据
        prices = self._extract_close_prices(klines)
        
        if len(prices) < 10:
            return 0.5
        
        # 计算移动平均线
        short_ma = sum(prices[-5:]) / 5  # 5期均线
        long_ma = sum(prices[-10:]) / 10  # 10期均线
        
        # 计算趋势强度
        if long_ma == 0:
            return 0.5
        
        trend_strength = abs(short_ma - long_ma) / long_ma
        return min(1.0, trend_strength * 10)  # 归一化到0-1
    
    def _extract_close_prices(self, klines: List[Dict[str, Any]]) -> List[float]:
        """从K线数据中提取收盘价，支持多种数据格式"""
        prices = []
        for k in klines:
            try:
                if isinstance(k, dict):
                    # 字典格式：{'close': value, ...}
                    prices.append(float(k['close']))
                elif isinstance(k, (list, tuple)) and len(k) > 4:
                    # 数组格式：[timestamp, open, high, low, close, volume]
                    prices.append(float(k[4]))
                else:
                    self.logger.warning(f"⚠️ 不支持的K线数据格式: {type(k)} - {k}")
                    continue
            except (KeyError, ValueError, IndexError) as e:
                self.logger.warning(f"⚠️ K线数据解析失败: {k}, 错误: {e}")
                continue
        return prices
    
    def _adjust_config_for_market(
        self, 
        config: TimeframeConfig, 
        market_regime: MarketRegime, 
        volatility: float
    ) -> TimeframeConfig:
        """根据市场状态调整配置"""
        # 创建配置副本
        adjusted_config = TimeframeConfig(
            timeframe=config.timeframe,
            lookback_periods=config.lookback_periods,
            prediction_horizon=config.prediction_horizon,
            confidence_threshold=config.confidence_threshold,
            signal_thresholds=config.signal_thresholds.copy(),
            trend_confirmation=config.trend_confirmation.copy()
        )
        
        # 根据市场状态调整
        if market_regime == MarketRegime.HIGH_VOLATILITY:
            # 高波动环境：提高置信度要求
            adjusted_config.confidence_threshold *= 1.2
            for key in adjusted_config.signal_thresholds:
                adjusted_config.signal_thresholds[key] *= 1.1
        
        elif market_regime == MarketRegime.TRENDING_UP:
            # 上涨趋势：提高卖出信号要求
            adjusted_config.trend_confirmation['bullish_threshold'] = max(
                0.8, adjusted_config.trend_confirmation['bullish_threshold']
            )
            adjusted_config.signal_thresholds['sell'] *= 1.2
            adjusted_config.signal_thresholds['strong_sell'] *= 1.2
        
        elif market_regime == MarketRegime.TRENDING_DOWN:
            # 下跌趋势：提高买入信号要求
            adjusted_config.trend_confirmation['bearish_threshold'] = max(
                0.8, adjusted_config.trend_confirmation['bearish_threshold']
            )
            adjusted_config.signal_thresholds['buy'] *= 1.2
            adjusted_config.signal_thresholds['strong_buy'] *= 1.2
        
        elif market_regime == MarketRegime.LOW_VOLATILITY:
            # 低波动环境：降低置信度要求
            adjusted_config.confidence_threshold *= 0.9
            for key in adjusted_config.signal_thresholds:
                adjusted_config.signal_thresholds[key] *= 0.95
        
        # 根据波动率微调
        if volatility > 0.15:  # 极高波动
            adjusted_config.confidence_threshold *= 1.3
        elif volatility < 0.02:  # 极低波动
            adjusted_config.confidence_threshold *= 0.8
        
        return adjusted_config
    
    async def _prepare_multi_timeframe_data(self, symbol: str) -> Dict[str, Any]:
        """准备多时间框架数据"""
        try:
            from app.services.exchanges.service_manager import get_exchange_service
            exchange_service = await get_exchange_service()
            
            timeframes = self.multi_timeframe_config.get('timeframes', ['15M', '1H', '4H', '1D'])
            weight_distribution = self.multi_timeframe_config.get('weight_distribution', {})
            
            multi_data = {
                'timeframes': timeframes,
                'weights': weight_distribution,
                'data': {}
            }
            
            # 获取各时间框架数据
            for tf in timeframes:
                try:
                    if tf == '15M':
                        periods = 96  # 24小时
                    elif tf == '1H':
                        periods = 48  # 48小时
                    elif tf == '4H':
                        periods = 72  # 12天
                    elif tf == '1D':
                        periods = 30  # 30天
                    else:
                        periods = 48
                    
                    klines = await exchange_service.get_kline_data(symbol, tf, periods)
                    if klines:
                        multi_data['data'][tf] = {
                            'klines': klines,
                            'volatility': self._calculate_data_volatility(klines),
                            'trend_strength': self._calculate_data_trend_strength(klines)
                        }
                except Exception as e:
                    # 改进异常日志，提供更详细的错误信息
                    error_type = type(e).__name__
                    error_msg = str(e)
                    self.logger.warning(f"⚠️ 获取 {symbol} {tf} 数据失败 [{error_type}]: {error_msg}")
                    self.logger.debug(f"🔍 多时间框架数据获取失败详情 - 交易对: {symbol}, 时间框架: {tf}, 异常类型: {error_type}, 异常信息: {error_msg}")
            
            return multi_data
            
        except Exception as e:
            self.logger.warning(f"⚠️ 准备 {symbol} 多时间框架数据失败: {e}")
            return {}
    
    def validate_signal_with_trend(
        self, 
        signal: str, 
        confidence: float, 
        context: PredictionContext
    ) -> Tuple[str, float]:
        """使用趋势过滤验证信号"""
        try:
            trend_config = context.timeframe_config.trend_confirmation
            
            # 在强势趋势中验证反向信号
            if context.market_regime == MarketRegime.TRENDING_UP:
                if signal in ['卖出', '强烈卖出']:
                    required_confidence = trend_config['bullish_threshold']
                    if confidence < required_confidence:
                        self.logger.info(f"🔍 上涨趋势中卖出信号置信度不足: {confidence:.2f} < {required_confidence:.2f}")
                        return '持有观望', confidence * 0.8
            
            elif context.market_regime == MarketRegime.TRENDING_DOWN:
                if signal in ['买入', '强烈买入']:
                    required_confidence = trend_config['bearish_threshold']
                    if confidence < required_confidence:
                        self.logger.info(f"🔍 下跌趋势中买入信号置信度不足: {confidence:.2f} < {required_confidence:.2f}")
                        return '持有观望', confidence * 0.8
            
            return signal, confidence
            
        except Exception as e:
            self.logger.warning(f"⚠️ 趋势验证失败: {e}")
            return signal, confidence
    
    def get_config_summary(self, context: PredictionContext) -> Dict[str, Any]:
        """获取配置摘要"""
        return {
            'trading_mode': context.trading_mode.value,
            'market_regime': context.market_regime.value,
            'timeframe': context.timeframe_config.timeframe,
            'prediction_horizon': f"{context.timeframe_config.prediction_horizon}小时",
            'confidence_threshold': context.timeframe_config.confidence_threshold,
            'volatility': f"{context.volatility:.3f}",
            'trend_strength': f"{context.trend_strength:.3f}",
            'multi_timeframe_enabled': context.multi_timeframe_data is not None
        }


# 全局实例
_timeframe_manager: Optional[KronosTimeframeManager] = None


def get_kronos_timeframe_manager() -> KronosTimeframeManager:
    """获取 Kronos 时间框架管理器实例"""
    global _timeframe_manager
    if _timeframe_manager is None:
        _timeframe_manager = KronosTimeframeManager()
    return _timeframe_manager