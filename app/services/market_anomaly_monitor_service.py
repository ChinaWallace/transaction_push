
"""
市场异常监控服务
Market Anomaly Monitor Service - 监控波动率、交易量、持仓量异常变动
"""

import asyncio
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.schemas.market_anomaly import (
    AnomalyLevel,
    AnomalySummary,
    MarketAnomalyData,
    TrendDirection,
)
from app.services.exchanges.okx.okx_service import OKXService
from app.services.notification.core_notification_service import (
    get_core_notification_service,
)
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)


@dataclass
class HistoricalData:
    """历史数据结构"""
    timestamps: List[datetime]
    prices: List[float]
    volumes: List[float]
    open_interests: List[float]


class MarketAnomalyMonitorService:
    """市场异常监控服务"""
    
    def __init__(self):
        self.okx_service = OKXService()
        self.notification_service = None
        
        # 异常检测阈值配置
        self.thresholds = {
            'volatility': {
                'extreme': 3.0,    # 3倍标准差
                'high': 2.5,       # 2.5倍标准差
                'medium': 2.0,     # 2倍标准差
                'low': 1.5         # 1.5倍标准差
            },
            'volume': {
                'extreme': 10.0,   # 10倍平均值
                'high': 5.0,       # 5倍平均值
                'medium': 3.0,     # 3倍平均值
                'low': 2.0         # 2倍平均值
            },
            'open_interest': {
                'extreme': 0.3,    # 30%变化
                'high': 0.2,       # 20%变化
                'medium': 0.15,    # 15%变化
                'low': 0.1         # 10%变化
            }
        }
        
        # 缓存历史数据
        self.historical_cache = {}
        self.cache_expiry = timedelta(minutes=30)
        
    async def _ensure_notification_service(self):
        """确保通知服务已初始化"""
        if self.notification_service is None:
            self.notification_service = await get_core_notification_service()    

    async def get_active_symbols(self, limit: int = 100) -> List[str]:
        """获取活跃的交易对列表"""
        try:
            logger.info(f"🔍 获取前{limit}个活跃交易对...")
            
            async with self.okx_service:
                # 获取所有SWAP合约的24小时统计
                tickers_result = await self.okx_service._make_request(
                    'GET', '/api/v5/market/tickers', 
                    params={'instType': 'SWAP'}
                )
                
                # 获取合约规格信息
                instruments_result = await self.okx_service._make_request(
                    'GET', '/api/v5/public/instruments',
                    params={'instType': 'SWAP'}
                )
                
                if not tickers_result or not instruments_result:
                    logger.warning("未获取到交易对数据或合约规格")
                    return []
                
                # 构建合约面值映射
                contract_specs = {}
                for instrument in instruments_result:
                    symbol = instrument.get('instId', '')
                    if symbol.endswith('-USDT-SWAP'):
                        ctVal = float(instrument.get('ctVal', '1') or '1')
                        contract_specs[symbol] = ctVal
                
                # 筛选USDT永续合约并按交易量排序
                usdt_tickers = []
                for ticker in tickers_result:
                    symbol = ticker.get('instId', '')
                    if symbol.endswith('-USDT-SWAP'):
                        try:
                            # 正确计算USDT交易量: vol24h(张数) × ctVal(合约面值) × last_price(价格)
                            vol24h = float(ticker.get('vol24h', '0') or '0')
                            last_price = float(ticker.get('last', '0') or '0')
                            ctVal = contract_specs.get(symbol, 1.0)
                            
                            volume_24h_usdt = vol24h * ctVal * last_price
                            
                            # 过滤交易量太小的币种
                            if volume_24h_usdt > 500000:  # 最小50万USDT交易量
                                usdt_tickers.append({
                                    'symbol': symbol,
                                    'volume_24h': volume_24h_usdt
                                })
                        except (ValueError, TypeError):
                            # 跳过无法转换的数据
                            continue
                
                # 按交易量排序
                usdt_tickers.sort(key=lambda x: x['volume_24h'], reverse=True)
                
                symbols = [ticker['symbol'] for ticker in usdt_tickers[:limit]]
                logger.info(f"✅ 获取到{len(symbols)}个活跃交易对")
                return symbols
                
        except Exception as e:
            logger.error(f"❌ 获取活跃交易对失败: {e}")
            return []
    
    async def get_historical_data(self, symbol: str, days: int = 7) -> Optional[HistoricalData]:
        """获取历史数据"""
        try:
            # 检查缓存
            cache_key = f"{symbol}_{days}d"
            if (cache_key in self.historical_cache and 
                datetime.now() - self.historical_cache[cache_key]['timestamp'] < self.cache_expiry):
                return self.historical_cache[cache_key]['data']
            
            logger.debug(f"📊 获取{symbol}的{days}天历史数据...")
            
            async with self.okx_service:
                # 获取1小时K线数据
                klines = await self.okx_service.get_kline_data(
                    symbol, '1H', limit=days * 24
                )
                
                if not klines or len(klines) < 24:  # 至少需要24小时数据
                    logger.warning(f"⚠️ {symbol}历史数据不足")
                    return None
                
                # 解析数据
                timestamps = []
                prices = []
                volumes = []
                
                for kline in klines:
                    timestamps.append(datetime.fromtimestamp(kline['timestamp'] / 1000))
                    prices.append(float(kline['close']))
                    # 使用volume_currency字段，这是以USDT为单位的成交量
                    volumes.append(float(kline.get('volume_currency', kline.get('volume', 0))))
                
                # 获取持仓量数据（如果是期货合约）
                open_interests = []
                try:
                    oi_data = await self.okx_service.get_open_interest_history(symbol, limit=days * 24)
                    if oi_data:
                        open_interests = [float(item['oi']) for item in oi_data]
                    else:
                        open_interests = [0.0] * len(prices)
                except:
                    open_interests = [0.0] * len(prices)
                
                historical_data = HistoricalData(
                    timestamps=timestamps,
                    prices=prices,
                    volumes=volumes,
                    open_interests=open_interests
                )
                
                # 缓存数据
                self.historical_cache[cache_key] = {
                    'data': historical_data,
                    'timestamp': datetime.now()
                }
                
                return historical_data
                
        except Exception as e:
            logger.error(f"❌ 获取{symbol}历史数据失败: {e}")
            return None
    
    async def get_current_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取当前市场数据"""
        try:
            async with self.okx_service:
                # 获取24小时统计数据
                ticker_result = await self.okx_service._make_request(
                    'GET', '/api/v5/market/ticker',
                    params={'instId': symbol}
                )
                
                if not ticker_result:
                    return None
                
                ticker = ticker_result[0]
                
                # 获取持仓量数据
                oi_data = None
                try:
                    oi_result = await self.okx_service._make_request(
                        'GET', '/api/v5/public/open-interest',
                        params={'instId': symbol}
                    )
                    if oi_result:
                        oi_data = oi_result[0]
                except:
                    pass
                
                # 价格变化处理：使用24小时开盘价计算
                current_price = float(ticker.get('last', '0') or '0')
                open_24h = ticker.get('open24h')
                
                if open_24h and float(open_24h) > 0:
                    open_price = float(open_24h)
                    price_change_24h = (current_price - open_price) / open_price
                else:
                    # 如果没有开盘价，尝试使用K线数据
                    price_change_24h = 0.0
                    try:
                        kline_result = await self.okx_service._make_request(
                            'GET', '/api/v5/market/history-candles',
                            params={
                                'instId': symbol,
                                'bar': '1H',
                                'limit': '25'
                            }
                        )
                        
                        if kline_result and len(kline_result) >= 24:
                            price_24h_ago = float(kline_result[23][4])
                            if price_24h_ago > 0:
                                price_change_24h = (current_price - price_24h_ago) / price_24h_ago
                    except Exception as e:
                        logger.debug(f"获取{symbol}历史价格失败: {e}")
                        price_change_24h = 0.0
                
                return {
                    'symbol': symbol,
                    'current_price': current_price,
                    'price_change_24h': price_change_24h,  # 小数形式（如0.05表示5%）
                    'volume_24h': float(ticker.get('volCcy24h', '0') or '0'),
                    'high_24h': float(ticker.get('high24h', '0') or '0'),
                    'low_24h': float(ticker.get('low24h', '0') or '0'),
                    'open_interest': float(oi_data.get('oi', '0') or '0') if oi_data else 0.0,
                    'oi_change_24h': float(oi_data.get('oiChg', '0') or '0') if oi_data else 0.0,
                    'timestamp': datetime.now()
                }
                
        except Exception as e:
            logger.error(f"❌ 获取{symbol}当前市场数据失败: {e}")
            return None    

    def calculate_volatility(self, prices: List[float], period: int = 24) -> float:
        """计算波动率"""
        if len(prices) < period:
            return 0.0
        
        # 计算收益率
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] != 0:
                returns.append((prices[i] - prices[i-1]) / prices[i-1])
        
        if len(returns) < 2:
            return 0.0
        
        # 计算标准差作为波动率
        return statistics.stdev(returns) * 100  # 转换为百分比
    
    def detect_volatility_anomaly(self, current_volatility: float, 
                                 historical_volatilities: List[float]) -> AnomalyLevel:
        """检测波动率异常"""
        if not historical_volatilities or len(historical_volatilities) < 7:
            return AnomalyLevel.NORMAL
        
        mean_vol = statistics.mean(historical_volatilities)
        std_vol = statistics.stdev(historical_volatilities) if len(historical_volatilities) > 1 else 0
        
        if std_vol == 0:
            return AnomalyLevel.NORMAL
        
        # 计算Z分数
        z_score = abs(current_volatility - mean_vol) / std_vol
        
        if z_score >= self.thresholds['volatility']['extreme']:
            return AnomalyLevel.EXTREME
        elif z_score >= self.thresholds['volatility']['high']:
            return AnomalyLevel.HIGH
        elif z_score >= self.thresholds['volatility']['medium']:
            return AnomalyLevel.MEDIUM
        elif z_score >= self.thresholds['volatility']['low']:
            return AnomalyLevel.LOW
        else:
            return AnomalyLevel.NORMAL
    
    def detect_volume_anomaly(self, current_volume: float, 
                             historical_volumes: List[float]) -> AnomalyLevel:
        """检测交易量异常"""
        if not historical_volumes or len(historical_volumes) < 7:
            return AnomalyLevel.NORMAL
        
        # 过滤掉0值
        valid_volumes = [v for v in historical_volumes if v > 0]
        if not valid_volumes:
            return AnomalyLevel.NORMAL
        
        mean_volume = statistics.mean(valid_volumes)
        
        if mean_volume == 0:
            return AnomalyLevel.NORMAL
        
        # 计算倍数
        volume_ratio = current_volume / mean_volume
        
        if volume_ratio >= self.thresholds['volume']['extreme']:
            return AnomalyLevel.EXTREME
        elif volume_ratio >= self.thresholds['volume']['high']:
            return AnomalyLevel.HIGH
        elif volume_ratio >= self.thresholds['volume']['medium']:
            return AnomalyLevel.MEDIUM
        elif volume_ratio >= self.thresholds['volume']['low']:
            return AnomalyLevel.LOW
        else:
            return AnomalyLevel.NORMAL
    
    def detect_oi_anomaly(self, oi_change_24h: float) -> AnomalyLevel:
        """检测持仓量异常"""
        abs_change = abs(oi_change_24h)
        
        if abs_change >= self.thresholds['open_interest']['extreme']:
            return AnomalyLevel.EXTREME
        elif abs_change >= self.thresholds['open_interest']['high']:
            return AnomalyLevel.HIGH
        elif abs_change >= self.thresholds['open_interest']['medium']:
            return AnomalyLevel.MEDIUM
        elif abs_change >= self.thresholds['open_interest']['low']:
            return AnomalyLevel.LOW
        else:
            return AnomalyLevel.NORMAL
    
    def determine_trend_direction(self, price_change_24h: float, 
                                 price_change_1h: float,
                                 volume_ratio: float,
                                 oi_change: Optional[float] = None) -> TrendDirection:
        """判断趋势方向"""
        # 基于价格变化判断主要趋势
        if price_change_24h > 0.15:  # 上涨超过15%
            if volume_ratio > 2.0:  # 交易量放大
                return TrendDirection.STRONG_UP
            else:
                return TrendDirection.UP
        elif price_change_24h > 0.05:  # 上涨5-15%
            return TrendDirection.UP
        elif price_change_24h < -0.15:  # 下跌超过15%
            if volume_ratio > 2.0:  # 交易量放大
                return TrendDirection.STRONG_DOWN
            else:
                return TrendDirection.DOWN
        elif price_change_24h < -0.05:  # 下跌5-15%
            return TrendDirection.DOWN
        else:
            return TrendDirection.SIDEWAYS
    
    def calculate_anomaly_score(self, volatility_level: AnomalyLevel,
                               volume_level: AnomalyLevel,
                               oi_level: Optional[AnomalyLevel],
                               trend_direction: TrendDirection) -> float:
        """计算综合异常评分"""
        # 异常级别评分
        level_scores = {
            AnomalyLevel.EXTREME: 25,
            AnomalyLevel.HIGH: 20,
            AnomalyLevel.MEDIUM: 15,
            AnomalyLevel.LOW: 10,
            AnomalyLevel.NORMAL: 0
        }
        
        score = 0
        score += level_scores.get(volatility_level, 0)
        score += level_scores.get(volume_level, 0)
        if oi_level:
            score += level_scores.get(oi_level, 0)
        
        # 趋势方向加分
        trend_scores = {
            TrendDirection.STRONG_UP: 20,
            TrendDirection.UP: 15,
            TrendDirection.SIDEWAYS: 5,
            TrendDirection.DOWN: 10,
            TrendDirection.STRONG_DOWN: 15
        }
        
        score += trend_scores.get(trend_direction, 0)
        
        return min(100, score)  # 最高100分
    
    async def analyze_symbol_anomaly(self, symbol: str) -> Optional[MarketAnomalyData]:
        """分析单个币种的异常情况"""
        try:
            logger.debug(f"🔍 分析{symbol}的异常情况...")
            
            # 获取当前市场数据
            current_data = await self.get_current_market_data(symbol)
            if not current_data:
                logger.warning(f"⚠️ 无法获取{symbol}的当前数据")
                return None
            
            # 调试日志：显示原始数据
            logger.debug(f"🔍 {symbol}原始数据: 价格变化={current_data['price_change_24h']}, 交易量={current_data['volume_24h']:.0f}")
            
            # 获取历史数据
            historical_data = await self.get_historical_data(symbol)
            if not historical_data:
                logger.warning(f"⚠️ 无法获取{symbol}的历史数据")
                return None
            
            # 计算当前波动率
            recent_prices = historical_data.prices[-24:]  # 最近24小时
            current_volatility = self.calculate_volatility(recent_prices)
            
            # 计算历史波动率
            historical_volatilities = []
            for i in range(7, len(historical_data.prices), 24):  # 每天计算一次
                day_prices = historical_data.prices[max(0, i-24):i]
                if len(day_prices) >= 12:  # 至少12小时数据
                    vol = self.calculate_volatility(day_prices)
                    historical_volatilities.append(vol)
            
            # 检测异常
            volatility_anomaly = self.detect_volatility_anomaly(
                current_volatility, historical_volatilities
            )
            
            volume_anomaly = self.detect_volume_anomaly(
                current_data['volume_24h'], 
                historical_data.volumes[-7*24:]  # 最近7天
            )
            
            oi_anomaly = None
            if current_data['open_interest'] > 0:
                oi_anomaly = self.detect_oi_anomaly(current_data['oi_change_24h'])
            
            # 计算比值 - 使用最近7天的平均交易量作为基准
            recent_volumes = [v for v in historical_data.volumes[-7*24:] if v > 0]
            if recent_volumes:
                avg_volume_7d = statistics.mean(recent_volumes)
                # 防止异常巨大的比值
                volume_ratio = min(current_data['volume_24h'] / avg_volume_7d, 10000.0) if avg_volume_7d > 0 else 1.0
            else:
                avg_volume_7d = current_data['volume_24h']
                volume_ratio = 1.0
            
            avg_volatility_7d = statistics.mean(historical_volatilities) if historical_volatilities else current_volatility
            volatility_ratio = current_volatility / avg_volatility_7d if avg_volatility_7d > 0 else 1.0
            
            # 判断趋势方向
            trend_direction = self.determine_trend_direction(
                current_data['price_change_24h'],
                0,  # 暂时没有1小时数据
                volume_ratio,
                current_data['oi_change_24h'] if current_data['open_interest'] > 0 else None
            )
            
            # 计算综合异常评分
            anomaly_score = self.calculate_anomaly_score(
                volatility_anomaly, volume_anomaly, oi_anomaly, trend_direction
            )
            
            # 确定综合异常级别
            if anomaly_score >= 80:
                overall_anomaly = AnomalyLevel.EXTREME
            elif anomaly_score >= 60:
                overall_anomaly = AnomalyLevel.HIGH
            elif anomaly_score >= 40:
                overall_anomaly = AnomalyLevel.MEDIUM
            elif anomaly_score >= 20:
                overall_anomaly = AnomalyLevel.LOW
            else:
                overall_anomaly = AnomalyLevel.NORMAL
            
            # 生成推荐和风险评估
            is_recommended, reasons, risk_factors = self._evaluate_recommendation(
                symbol, current_data, volatility_anomaly, volume_anomaly, 
                oi_anomaly, trend_direction, anomaly_score
            )
            
            # 构建结果
            anomaly_data = MarketAnomalyData(
                symbol=symbol,
                symbol_name=symbol.replace('-USDT-SWAP', ''),
                timestamp=datetime.now(),
                current_price=current_data['current_price'],
                price_change_24h=current_data['price_change_24h'],
                price_change_1h=0,  # 暂时没有1小时数据
                volatility_24h=current_volatility,
                volatility_avg_7d=avg_volatility_7d,
                volatility_ratio=volatility_ratio,
                volatility_anomaly_level=volatility_anomaly,
                volume_24h=current_data['volume_24h'],
                volume_avg_7d=avg_volume_7d,
                volume_ratio=volume_ratio,
                volume_anomaly_level=volume_anomaly,
                open_interest=current_data['open_interest'] if current_data['open_interest'] > 0 else None,
                oi_change_24h=current_data['oi_change_24h'] if current_data['open_interest'] > 0 else None,
                oi_avg_7d=None,  # 暂时不计算
                oi_ratio=None,   # 暂时不计算
                oi_anomaly_level=oi_anomaly,
                overall_anomaly_level=overall_anomaly,
                trend_direction=trend_direction,
                anomaly_score=anomaly_score,
                is_recommended=is_recommended,
                recommendation_reason=reasons,
                risk_factors=risk_factors
            )
            
            logger.debug(f"✅ {symbol}异常分析完成: {overall_anomaly.value}, 评分: {anomaly_score}")
            return anomaly_data
            
        except Exception as e:
            logger.error(f"❌ 分析{symbol}异常失败: {e}")
            return None
    
    def _evaluate_recommendation(self, symbol: str, current_data: Dict[str, Any],
                               volatility_anomaly: AnomalyLevel, volume_anomaly: AnomalyLevel,
                               oi_anomaly: Optional[AnomalyLevel], trend_direction: TrendDirection,
                               anomaly_score: float) -> Tuple[bool, List[str], List[str]]:
        """评估是否推荐该币种"""
        reasons = []
        risk_factors = []
        
        
        # 综合评估
        is_recommended = False
        
        # 推荐条件：异常评分足够高且有明确推荐理由
        has_significant_anomaly = (
            volatility_anomaly in [AnomalyLevel.MEDIUM, AnomalyLevel.HIGH, AnomalyLevel.EXTREME] or
            volume_anomaly in [AnomalyLevel.MEDIUM, AnomalyLevel.HIGH, AnomalyLevel.EXTREME] or
            (oi_anomaly and oi_anomaly in [AnomalyLevel.MEDIUM, AnomalyLevel.HIGH, AnomalyLevel.EXTREME])
        )
        
        if (anomaly_score >= 35 and 
            len(reasons) >= 1 and 
            len(risk_factors) <= len(reasons) and
            has_significant_anomaly):
            is_recommended = True
        
        # 特殊情况：强势上涨 + 交易量异常 = 强烈推荐
        if (trend_direction in [TrendDirection.STRONG_UP, TrendDirection.UP] and
            volume_anomaly in [AnomalyLevel.HIGH, AnomalyLevel.EXTREME] and
            current_data['volume_24h'] > 5000000):  # 交易量大于500万
            is_recommended = True
        
        return is_recommended, reasons, risk_factors
    
    async def scan_market_anomalies(self, symbols: Optional[List[str]] = None,
                                   min_anomaly_level: AnomalyLevel = AnomalyLevel.MEDIUM,
                                   only_recommended: bool = True) -> Tuple[List[MarketAnomalyData], int]:
        """扫描市场异常"""
        try:
            logger.info("🔍 开始扫描市场异常...")
            
            # 获取要分析的币种列表
            if symbols is None:
                symbols = await self.get_active_symbols(100)
            
            if not symbols:
                logger.warning("⚠️ 没有可分析的币种")
                return []
            
            logger.info(f"📊 开始分析{len(symbols)}个币种的异常情况...")
            
            # 并发分析所有币种
            tasks = []
            for symbol in symbols:
                task = self.analyze_symbol_anomaly(symbol)
                tasks.append(task)
            
            # 等待所有分析完成
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 过滤结果
            anomalies = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"⚠️ 分析{symbols[i]}失败: {result}")
                    continue
                
                if result is None:
                    continue
                
                # 应用过滤条件
                if self._should_include_anomaly(result, min_anomaly_level, only_recommended):
                    anomalies.append(result)
            
            # 按异常评分排序
            anomalies.sort(key=lambda x: x.anomaly_score, reverse=True)
            
            logger.info(f"✅ 市场异常扫描完成: 检查{len(symbols)}个币种，发现{len(anomalies)}个异常")
            return anomalies, len(symbols)
            
        except Exception as e:
            logger.error(f"❌ 市场异常扫描失败: {e}")
            raise TradingToolError(f"市场异常扫描失败: {e}")
    
    def _should_include_anomaly(self, anomaly: MarketAnomalyData,
                               min_level: AnomalyLevel,
                               only_recommended: bool) -> bool:
        """判断是否应该包含该异常"""
        # 异常级别过滤
        level_order = {
            AnomalyLevel.NORMAL: 0,
            AnomalyLevel.LOW: 1,
            AnomalyLevel.MEDIUM: 2,
            AnomalyLevel.HIGH: 3,
            AnomalyLevel.EXTREME: 4
        }
        
        if level_order.get(anomaly.overall_anomaly_level, 0) < level_order.get(min_level, 0):
            return False
        
        # 推荐过滤
        if only_recommended and not anomaly.is_recommended:
            return False
        
        # 交易量过滤
        if anomaly.volume_24h < 1000000:  # 小于100万USDT
            return False
        
        return True
    
    def generate_summary(self, anomalies: List[MarketAnomalyData], total_symbols_checked: int = None) -> AnomalySummary:
        """生成异常汇总信息"""
        total_checked = total_symbols_checked if total_symbols_checked is not None else len(anomalies)
        recommended_count = sum(1 for a in anomalies if a.is_recommended)
        
        # 按异常级别分类
        by_anomaly_level = {}
        for level in AnomalyLevel:
            count = sum(1 for a in anomalies if a.overall_anomaly_level == level)
            if count > 0:
                by_anomaly_level[level.value] = count
        
        # 按趋势方向分类
        by_trend_direction = {}
        for direction in TrendDirection:
            count = sum(1 for a in anomalies if a.trend_direction == direction)
            if count > 0:
                by_trend_direction[direction.value] = count
        
        # 按异常类型分类（多个异常类型可能同时存在）
        by_anomaly_type = {
            'volatility': sum(1 for a in anomalies if a.volatility_anomaly_level != AnomalyLevel.NORMAL),
            'volume': sum(1 for a in anomalies if a.volume_anomaly_level != AnomalyLevel.NORMAL),
            'open_interest': sum(1 for a in anomalies if a.oi_anomaly_level and a.oi_anomaly_level != AnomalyLevel.NORMAL)
        }
        
        # 最佳机会（推荐且评分高）
        top_opportunities = [
            a.symbol_name for a in sorted(anomalies, key=lambda x: x.anomaly_score, reverse=True)
            if a.is_recommended
        ][:10]
        
        # 高风险币种（异常但不推荐）
        high_risk_symbols = [
            a.symbol_name for a in anomalies
            if a.overall_anomaly_level in [AnomalyLevel.HIGH, AnomalyLevel.EXTREME] and not a.is_recommended
        ][:10]
        
        return AnomalySummary(
            total_symbols_checked=total_checked,
            anomalies_found=len(anomalies),
            recommended_count=recommended_count,
            by_anomaly_level=by_anomaly_level,
            by_trend_direction=by_trend_direction,
            by_anomaly_type=by_anomaly_type,
            top_opportunities=top_opportunities,
            high_risk_symbols=high_risk_symbols
        )
    
    def format_notification_message(self, anomalies: List[MarketAnomalyData],
                                   summary: AnomalySummary) -> str:
        """格式化通知消息"""
        if not anomalies:
            return "📊 当前市场无显著异常\n⏰ 下次检查: 30分钟后"
        
        # 构建消息标题
        message = "🚨 市场异常监控报告\n"
        message += f"⏰ 检测时间: {datetime.now().strftime('%m-%d %H:%M')}\n"
        message += f"📊 总检查币种: {summary.total_symbols_checked}个\n"
        message += f"🔍 发现异常: {summary.anomalies_found}个\n"
        
        # 显示推荐的异常（按评分排序）
        recommended_anomalies = [a for a in anomalies if a.is_recommended][:8]
        
        if recommended_anomalies:
            message += "🏆 重点关注 (TOP8):\n"
            for i, anomaly in enumerate(recommended_anomalies, 1):
                symbol_name = anomaly.symbol_name
                score = anomaly.anomaly_score
                # OKX的price_change_24h已经是小数形式，需要转换为百分比
                price_change = anomaly.price_change_24h * 100
                volume_ratio = anomaly.volume_ratio
                
                # 异常级别图标
                level_icons = {
                    AnomalyLevel.EXTREME: "🔴",
                    AnomalyLevel.HIGH: "🟠", 
                    AnomalyLevel.MEDIUM: "🟡",
                    AnomalyLevel.LOW: "🟢",
                    AnomalyLevel.NORMAL: "⚪"
                }
                level_icon = level_icons.get(anomaly.overall_anomaly_level, "⚪")
                
                # 趋势方向图标
                trend_icons = {
                    TrendDirection.STRONG_UP: "🚀",
                    TrendDirection.UP: "📈",
                    TrendDirection.SIDEWAYS: "➖",
                    TrendDirection.DOWN: "📉",
                    TrendDirection.STRONG_DOWN: "💥"
                }
                trend_icon = trend_icons.get(anomaly.trend_direction, "➖")
                
                message += f"{level_icon} {i}. {symbol_name} (评分: {score:.0f})\n"
                
                # 限制量比显示的最大值，避免显示过大的数字
                display_volume_ratio = min(volume_ratio, 9999.9)
                # 添加当前价格显示
                current_price = anomaly.current_price
                price_str = f"${current_price:.4f}" if current_price >= 1 else f"${current_price:.6f}"
                message += f"   💰 当前价格: {price_str}\n"
                message += f"   {trend_icon} 24h涨跌: {price_change:+.1f}% | 24h量比: {display_volume_ratio:.1f}倍\n"
                
                if anomaly.recommendation_reason:
                    main_reason = anomaly.recommendation_reason[0]
                    message += f"   💡 {main_reason}\n"
                
                # 显示异常类型 - 使用中文说明
                anomaly_types = []
                if anomaly.volatility_anomaly_level != AnomalyLevel.NORMAL:
                    level_name = self._get_anomaly_level_chinese(anomaly.volatility_anomaly_level)
                    anomaly_types.append(f"波动率{level_name}")
                if anomaly.volume_anomaly_level != AnomalyLevel.NORMAL:
                    level_name = self._get_anomaly_level_chinese(anomaly.volume_anomaly_level)
                    anomaly_types.append(f"交易量{level_name}")
                if anomaly.oi_anomaly_level and anomaly.oi_anomaly_level != AnomalyLevel.NORMAL:
                    level_name = self._get_anomaly_level_chinese(anomaly.oi_anomaly_level)
                    anomaly_types.append(f"持仓量{level_name}")
                
                message += "\n"
        
        # 显示统计信息
        if summary.by_trend_direction:
            message += "📈 趋势分布:\n"
            trend_names = {
                'strong_up': '强势上涨',
                'up': '上涨',
                'sideways': '横盘',
                'down': '下跌',
                'strong_down': '强势下跌'
            }
            for trend, count in summary.by_trend_direction.items():
                trend_name = trend_names.get(trend, trend)
                message += f"   • {trend_name}: {count}个\n"
            message += "\n"
         
        return message
    
    def _get_anomaly_level_chinese(self, level: AnomalyLevel) -> str:
        """获取异常级别的中文描述"""
        level_names = {
            AnomalyLevel.EXTREME: "极端异常",
            AnomalyLevel.HIGH: "高度异常", 
            AnomalyLevel.MEDIUM: "中度异常",
            AnomalyLevel.LOW: "轻度异常",
            AnomalyLevel.NORMAL: "正常"
        }
        return level_names.get(level, "未知")
    
    def _get_technical_analysis(self, anomaly: MarketAnomalyData) -> str:
        """获取技术分析描述"""
        analysis_parts = []
        
        # 价格趋势分析
        price_change = anomaly.price_change_24h * 100
        if price_change > 15:
            analysis_parts.append("强势上涨")
        elif price_change > 5:
            analysis_parts.append("温和上涨")
        elif price_change > -5:
            analysis_parts.append("横盘整理")
        elif price_change > -15:
            analysis_parts.append("温和下跌")
        else:
            analysis_parts.append("深度回调")
        
        # 交易量分析
        if anomaly.volume_ratio > 5:
            analysis_parts.append("成交量爆发")
        elif anomaly.volume_ratio > 3:
            analysis_parts.append("成交量放大")
        elif anomaly.volume_ratio > 1.5:
            analysis_parts.append("成交量活跃")
        else:
            analysis_parts.append("成交量萎缩")
        
        # 波动率分析
        if anomaly.volatility_anomaly_level == AnomalyLevel.EXTREME:
            analysis_parts.append("波动剧烈")
        elif anomaly.volatility_anomaly_level == AnomalyLevel.HIGH:
            analysis_parts.append("波动较大")
        
        # 持仓量分析
        if anomaly.oi_change_24h is not None:
            if abs(anomaly.oi_change_24h) > 0.2:  # 20%以上变化
                if anomaly.oi_change_24h > 0:
                    analysis_parts.append("多头增仓")
                else:
                    analysis_parts.append("大量平仓")
        
        return "，".join(analysis_parts) if analysis_parts else "数据不足"
    
    async def run_monitoring_cycle(self) -> Dict[str, Any]:
        """运行一次完整的监控周期"""
        try:
            logger.info("🚨 开始市场异常监控周期...")
            
            # 扫描异常
            anomalies, total_checked = await self.scan_market_anomalies(
                min_anomaly_level=AnomalyLevel.LOW,
                only_recommended=True
            )
            
            # 生成汇总
            summary = self.generate_summary(anomalies, total_checked)
            
            # 发送通知
            if anomalies:
                await self._ensure_notification_service()
                
                notification_message = self.format_notification_message(anomalies, summary)
                
                from app.services.notification.core_notification_service import (
                    NotificationContent,
                    NotificationPriority,
                    NotificationType,
                )
                
                content = NotificationContent(
                    type=NotificationType.SYSTEM_ALERT,
                    priority=NotificationPriority.HIGH if summary.recommended_count > 5 else NotificationPriority.MEDIUM,
                    title="🚨 市场异常监控",
                    message=notification_message
                )
                
                await self.notification_service.send_notification(content)
                
                logger.info(f"✅ 异常监控完成: 发现{len(anomalies)}个异常，推荐{summary.recommended_count}个")
            else:
                logger.info("📊 当前市场无显著异常")
            
            return {
                'success': True,
                'anomalies_found': len(anomalies),
                'recommended_count': summary.recommended_count,
                'summary': summary,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ 市场异常监控周期失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }


# 全局服务实例
_market_anomaly_service = None

async def get_market_anomaly_service() -> MarketAnomalyMonitorService:
    """获取市场异常监控服务实例"""
    global _market_anomaly_service
    if _market_anomaly_service is None:
        _market_anomaly_service = MarketAnomalyMonitorService()
    return _market_anomaly_service