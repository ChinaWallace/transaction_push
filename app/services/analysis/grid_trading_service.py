# -*- coding: utf-8 -*-
"""
网格交易机会分析服务
Grid Trading Opportunity Analysis Service

分析市场中适合做多网格交易的机会
"""

import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.exchanges.service_manager import get_exchange_service
from app.services.data.cache_service import get_cache_service
from app.schemas.grid_trading import (
    GridTradingRecommendation, 
    GridTradingMetrics,
    GridTradingRange,
    GridTrendType,
    GridOpportunityLevel,
    GridTradingBatch
)

logger = get_logger(__name__)

# 全局服务实例
_grid_trading_service: Optional['GridTradingService'] = None


class GridTradingService:
    """网格交易机会分析服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.initialized = False
        
        # 依赖服务
        self.exchange_service = None
        self.cache_service = None
        
        # 配置参数
        self.base_capital = 10000  # 基准资金 10000 USDT
        self.min_volume_24h = 50000000  # 最小24h交易量 5000万USDT
        self.min_volatility = 0.02  # 最小波动率 2%
        self.max_volatility = 0.15  # 最大波动率 15%
        self.trend_lookback_days = 7  # 趋势分析回看天数
        
        # 网格配置
        self.default_grid_count = 20  # 默认网格数量
        self.grid_spacing_range = (0.5, 2.0)  # 网格间距范围 0.5%-2%
        
    async def initialize(self) -> None:
        """初始化服务"""
        if self.initialized:
            return
            
        try:
            # 初始化依赖服务
            self.exchange_service = await get_exchange_service()
            self.cache_service = await get_cache_service()
            
            self.initialized = True
            self.logger.info("✅ 网格交易服务初始化完成")
            
        except Exception as e:
            self.logger.error(f"❌ 网格交易服务初始化失败: {e}")
            raise
    
    async def analyze_grid_opportunities(
        self, 
        symbols: Optional[List[str]] = None,
        min_opportunity_level: GridOpportunityLevel = GridOpportunityLevel.MODERATE
    ) -> GridTradingBatch:
        """分析网格交易机会"""
        try:
            if not self.initialized:
                await self.initialize()
            
            # 获取候选交易对
            if not symbols:
                symbols = await self._get_candidate_symbols()
            
            self.logger.info(f"🔍 开始分析 {len(symbols)} 个交易对的网格机会")
            
            # 并发分析所有交易对
            tasks = [
                self._analyze_single_symbol(symbol) 
                for symbol in symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 过滤有效结果
            recommendations = []
            for result in results:
                if isinstance(result, GridTradingRecommendation):
                    if self._meets_opportunity_level(result, min_opportunity_level):
                        recommendations.append(result)
                elif isinstance(result, Exception):
                    self.logger.warning(f"分析失败: {result}")
            
            # 按机会等级排序
            recommendations.sort(
                key=lambda x: self._get_opportunity_score(x), 
                reverse=True
            )
            
            # 统计结果
            excellent_count = sum(1 for r in recommendations if r.opportunity_level == GridOpportunityLevel.EXCELLENT)
            good_count = sum(1 for r in recommendations if r.opportunity_level == GridOpportunityLevel.GOOD)
            
            # 生成市场总结
            market_summary = await self._generate_market_summary(recommendations)
            
            batch = GridTradingBatch(
                recommendations=recommendations[:10],  # 返回前10个最佳机会
                total_count=len(recommendations),
                excellent_count=excellent_count,
                good_count=good_count,
                market_summary=market_summary
            )
            
            self.logger.info(f"✅ 网格机会分析完成: {len(recommendations)} 个机会")
            return batch
            
        except Exception as e:
            self.logger.error(f"❌ 网格机会分析失败: {e}")
            raise
    
    async def _get_candidate_symbols(self) -> List[str]:
        """获取候选交易对 - 优化版本，包含更多高波动机会"""
        try:
            # 获取热门交易对
            tickers = await self.exchange_service.get_all_tickers()
            
            # 高波动性目标币种 - 特别关注
            high_volatility_targets = ['XPL', 'STBL', 'MEME', 'PEPE', 'SHIB', 'DOGE', 'FLOKI', 'BONK']
            
            # 过滤条件：永续合约、USDT结算
            candidates = []
            high_vol_candidates = []
            
            self.logger.info(f"🔍 开始筛选候选交易对，总ticker数量: {len(tickers)}")
            
            for ticker in tickers:
                # 适配器已经将数据转换为统一格式：SYMBOL-USDT-SWAP
                symbol = ticker.get('symbol', '')
                
                # 检查统一格式：SYMBOL-USDT-SWAP
                if symbol.endswith('-USDT-SWAP') and len(symbol) > 10:
                    base_symbol = symbol.replace('-USDT-SWAP', '').upper()
                    unified_symbol = symbol  # 已经是统一格式，直接使用
                    
                    # 获取24小时交易额 (USDT) - 使用正确的字段
                    volume_24h = float(ticker.get('volCcy24h', 0))  # 币安适配后的交易额字段
                    if not volume_24h:
                        volume_24h = float(ticker.get('volume_24h', 0))  # 备用字段
                    
                    # 特殊处理高波动目标币种 - 但仍需要足够的交易量
                    if base_symbol in high_volatility_targets:
                        if volume_24h > 100000000:  # 1亿USDT，高波动币种也需要足够流动性
                            high_vol_candidates.append(unified_symbol)
                            self.logger.info(f"🎯 发现高波动目标: {symbol} -> {unified_symbol}, 24h成交额: {volume_24h/1000000:.1f}M USDT")
                    
                    # 常规筛选 - 严格要求1亿USDT以上
                    elif volume_24h > 100000000:  # 1亿USDT标准
                        candidates.append(unified_symbol)
                        
                    # 对于主流币种，稍微降低门槛但仍要求较高交易量
                    elif base_symbol in ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'MATIC', 'DOT', 'AVAX', 'LINK']:
                        if volume_24h > 80000000:  # 8000万USDT门槛，主流币种稍低
                            candidates.append(unified_symbol)
            
            # 合并候选列表，高波动币种优先
            all_candidates = high_vol_candidates + candidates
            
            # 按交易量排序，但保持高波动币种在前面
            def sort_key(symbol):
                base_symbol = symbol.replace('-USDT-SWAP', '').upper()
                # 从适配后的ticker中找到对应的交易量
                unified_symbol_lookup = f"{base_symbol}-USDT-SWAP"
                volume = float(next(
                    (t.get('volCcy24h', 0) for t in tickers if t.get('symbol') == unified_symbol_lookup), 0
                ))
                if not volume:
                    volume = float(next(
                        (t.get('volume_24h', 0) for t in tickers if t.get('symbol') == unified_symbol_lookup), 0
                    ))
                # 高波动币种加权
                if base_symbol in high_volatility_targets:
                    return volume * 100  # 100倍权重确保优先
                return volume
            
            all_candidates.sort(key=sort_key, reverse=True)
            
            # 去重并确保包含足够的候选币种
            final_candidates = list(dict.fromkeys(all_candidates))[:80]  # 去重并增加到80个候选
            
            self.logger.info(f"📊 筛选出 {len(final_candidates)} 个候选交易对，其中高波动目标 {len(high_vol_candidates)} 个")
            
            return final_candidates
            
        except Exception as e:
            self.logger.error(f"获取候选交易对失败: {e}")
            # 返回包含高波动币种的默认交易对
            return [
                'BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP',
                'XPL-USDT-SWAP', 'STBL-USDT-SWAP', 'DOGE-USDT-SWAP',
                'PEPE-USDT-SWAP', 'SHIB-USDT-SWAP', 'MEME-USDT-SWAP',
                'BNB-USDT-SWAP', 'XRP-USDT-SWAP', 'ADA-USDT-SWAP'
            ]
    
    async def _analyze_single_symbol(self, symbol: str) -> Optional[GridTradingRecommendation]:
        """分析单个交易对的网格机会"""
        try:
            # 转换为币安格式进行数据获取
            binance_symbol = symbol.replace('-USDT-SWAP', 'USDT')
            
            # 获取市场数据
            ticker = await self.exchange_service.get_ticker(binance_symbol)
            if not ticker:
                self.logger.warning(f"未找到 {binance_symbol} 的ticker数据")
                return None
            
            current_price = float(ticker.get('last', 0))
            if current_price <= 0:
                return None
            
            # 获取历史数据用于趋势分析 - 使用币安格式
            klines = await self.exchange_service.get_klines(
                symbol=binance_symbol,
                timeframe='1d',
                limit=30
            )
            
            if not klines or len(klines) < 7:
                return None
            
            # 计算交易指标 - 使用统一格式的symbol
            metrics = await self._calculate_metrics(symbol, ticker, klines)
            
            # 判断是否符合网格交易条件
            if not self._is_suitable_for_grid(metrics):
                return None
            
            # 分析趋势类型
            trend_type = await self._analyze_trend(klines)
            
            # 如果是持续下跌趋势，不推荐做多网格
            if trend_type == GridTrendType.DOWNWARD:
                return None
            
            # 计算机会等级
            opportunity_level = self._calculate_opportunity_level(metrics, trend_type)
            
            # 计算推荐配置
            trading_range = await self._calculate_trading_range(
                current_price, metrics, trend_type
            )
            
            # 计算仓位和资金配置
            position_config = self._calculate_position_config(
                metrics, opportunity_level, trading_range
            )
            
            # 预期收益计算
            expected_returns = self._calculate_expected_returns(
                metrics, trading_range, position_config
            )
            
            # 生成推荐理由和风险提示
            reasoning = self._generate_reasoning(symbol, metrics, trend_type)
            risk_warning = self._generate_risk_warning(
                symbol=symbol,
                volatility=metrics.volatility_24h,
                volume=metrics.volume_24h,
                price_change_24h=metrics.price_change_24h,
                risk_level=self._get_risk_level(metrics),
                metrics=metrics,
                trend_type=trend_type
            )
            
            recommendation = GridTradingRecommendation(
                symbol=symbol,
                current_price=current_price,
                trend_type=trend_type,
                opportunity_level=opportunity_level,
                metrics=metrics,
                recommended_capital=position_config['capital'],
                position_percentage=position_config['percentage'],
                trading_range=trading_range,
                expected_daily_return=expected_returns['daily'],
                expected_monthly_return=expected_returns['monthly'],
                risk_level=self._get_risk_level(metrics),
                reasoning=reasoning,
                risk_warning=risk_warning
            )
            
            return recommendation
            
        except Exception as e:
            self.logger.warning(f"分析 {symbol} 失败: {e}")
            return None
    
    async def _calculate_metrics(
        self, 
        symbol: str, 
        ticker: Dict[str, Any], 
        klines: List[Dict[str, Any]]
    ) -> GridTradingMetrics:
        """计算交易指标"""
        try:
            # 基础数据
            volume_24h = float(ticker.get('volCcy24h', 0))
            price_change_24h = float(ticker.get('sodUtc8', 0)) * 100
            
            # 提取收盘价 - 兼容字典和列表格式
            def get_close_price(kline):
                if isinstance(kline, dict):
                    return float(kline.get('close', 0))
                elif isinstance(kline, (list, tuple)) and len(kline) > 4:
                    return float(kline[4])
                else:
                    return 0
            
            # 计算7天价格变化
            if len(klines) >= 7:
                price_7d_ago = get_close_price(klines[-7])  # 7天前收盘价
                current_price = float(ticker.get('last', 0))
                if price_7d_ago > 0:
                    price_change_7d = ((current_price - price_7d_ago) / price_7d_ago) * 100
                else:
                    price_change_7d = 0
            else:
                price_change_7d = 0
            
            # 计算波动率 (基于最近7天的日收益率标准差)
            if len(klines) >= 7:
                closes = [get_close_price(k) for k in klines[-7:]]
                closes = [c for c in closes if c > 0]  # 过滤无效价格
                
                if len(closes) >= 2:
                    returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                    volatility_24h = np.std(returns) if returns else 0.03
                else:
                    volatility_24h = 0.03
            else:
                volatility_24h = 0.03  # 默认值
            
            # 计算ATR比率
            atr_ratio = await self._calculate_atr_ratio(klines)
            
            # 流动性评分 (基于交易量和价差)
            liquidity_score = min(1.0, volume_24h / 1000000000)  # 10亿为满分
            
            # 交易量排名 (简化处理)
            volume_rank = await self._get_volume_rank(symbol, volume_24h)
            
            return GridTradingMetrics(
                volatility_24h=volatility_24h,
                volume_24h=volume_24h,
                volume_rank=volume_rank,
                price_change_24h=price_change_24h,
                price_change_7d=price_change_7d,
                atr_ratio=atr_ratio,
                liquidity_score=liquidity_score
            )
            
        except Exception as e:
            self.logger.error(f"计算 {symbol} 指标失败: {e}")
            raise
    
    async def _calculate_atr_ratio(self, klines: List[Dict[str, Any]]) -> float:
        """计算ATR比率"""
        try:
            if len(klines) < 2:
                return 0.03  # 默认值
            
            # 提取OHLC数据 - 兼容字典和列表格式
            def get_ohlc(kline):
                if isinstance(kline, dict):
                    return {
                        'high': float(kline.get('high', 0)),
                        'low': float(kline.get('low', 0)),
                        'close': float(kline.get('close', 0))
                    }
                elif isinstance(kline, (list, tuple)) and len(kline) > 4:
                    return {
                        'high': float(kline[2]),
                        'low': float(kline[3]),
                        'close': float(kline[4])
                    }
                else:
                    return {'high': 0, 'low': 0, 'close': 0}
            
            # 计算真实波幅
            true_ranges = []
            for i in range(1, min(len(klines), 15)):
                current = get_ohlc(klines[i])
                prev = get_ohlc(klines[i-1])
                
                if current['high'] > 0 and current['low'] > 0 and prev['close'] > 0:
                    tr = max(
                        current['high'] - current['low'],
                        abs(current['high'] - prev['close']),
                        abs(current['low'] - prev['close'])
                    )
                    true_ranges.append(tr)
            
            if not true_ranges:
                return 0.03
            
            atr = np.mean(true_ranges)
            
            # 获取当前价格
            current_kline = get_ohlc(klines[-1])
            current_price = current_kline['close']
            
            return atr / current_price if current_price > 0 else 0.03
            
        except Exception as e:
            self.logger.warning(f"计算ATR失败: {e}")
            return 0.03
    
    async def _get_volume_rank(self, symbol: str, volume: float) -> int:
        """获取交易量排名 (简化实现)"""
        try:
            # 这里可以实现更精确的排名逻辑
            # 暂时基于交易量大小给出估算排名
            if volume > 2000000000:  # 20亿+
                return 1
            elif volume > 1000000000:  # 10亿+
                return 2
            elif volume > 500000000:  # 5亿+
                return 3
            elif volume > 200000000:  # 2亿+
                return 5
            elif volume > 100000000:  # 1亿+
                return 10
            else:
                return 20
        except:
            return 50
    
    def _is_suitable_for_grid(self, metrics: GridTradingMetrics) -> bool:
        """判断是否适合网格交易 - 优化版本"""
        # 基础条件检查
        basic_suitable = (
            metrics.volume_24h >= 20000000 and  # 降低到2000万USDT
            0.01 <= metrics.volatility_24h <= 0.25 and  # 扩大波动率范围 1%-25%
            metrics.liquidity_score >= 0.2  # 降低流动性要求
        )
        
        # 对于高波动币种，进一步放宽条件
        if metrics.volume_24h >= 10000000 and metrics.volatility_24h >= 0.05:
            # 高波动币种只要交易量超过1000万且波动率超过5%就认为适合
            return True
        
        return basic_suitable
    
    async def _analyze_trend(self, klines: List[Dict[str, Any]]) -> GridTrendType:
        """分析趋势类型"""
        try:
            if len(klines) < 7:
                return GridTrendType.SIDEWAYS
            
            # 取最近7天的收盘价 - 兼容字典和列表格式
            closes = []
            for k in klines[-7:]:
                if isinstance(k, dict):
                    close_price = float(k.get('close', 0))
                elif isinstance(k, (list, tuple)) and len(k) > 4:
                    close_price = float(k[4])
                else:
                    continue
                if close_price > 0:
                    closes.append(close_price)
            
            # 计算线性回归斜率
            x = np.arange(len(closes))
            slope = np.polyfit(x, closes, 1)[0]
            
            # 计算价格变化幅度
            price_change = (closes[-1] - closes[0]) / closes[0]
            
            # 判断趋势
            if slope > 0 and price_change > 0.05:  # 上涨超过5%
                return GridTrendType.UPWARD
            elif slope < 0 and price_change < -0.05:  # 下跌超过5%
                return GridTrendType.DOWNWARD
            else:
                return GridTrendType.SIDEWAYS
                
        except Exception as e:
            self.logger.warning(f"趋势分析失败: {e}")
            return GridTrendType.SIDEWAYS
    
    def _calculate_opportunity_level(
        self, 
        metrics: GridTradingMetrics, 
        trend_type: GridTrendType
    ) -> GridOpportunityLevel:
        """计算机会等级"""
        score = 0
        
        # 波动率评分 (3-8%为最佳)
        if 0.03 <= metrics.volatility_24h <= 0.08:
            score += 30
        elif 0.02 <= metrics.volatility_24h <= 0.12:
            score += 20
        else:
            score += 10
        
        # 交易量评分
        if metrics.volume_rank <= 3:
            score += 25
        elif metrics.volume_rank <= 10:
            score += 20
        elif metrics.volume_rank <= 20:
            score += 15
        else:
            score += 10
        
        # 流动性评分
        score += int(metrics.liquidity_score * 20)
        
        # 趋势评分
        if trend_type == GridTrendType.SIDEWAYS:
            score += 25  # 震荡最适合网格
        elif trend_type == GridTrendType.UPWARD:
            score += 20  # 上涨趋势也不错
        else:
            score += 5   # 下跌趋势不适合做多网格
        
        # 根据总分确定等级
        if score >= 85:
            return GridOpportunityLevel.EXCELLENT
        elif score >= 70:
            return GridOpportunityLevel.GOOD
        elif score >= 55:
            return GridOpportunityLevel.MODERATE
        else:
            return GridOpportunityLevel.POOR
    
    async def _calculate_trading_range(
        self, 
        current_price: float, 
        metrics: GridTradingMetrics, 
        trend_type: GridTrendType
    ) -> GridTradingRange:
        """计算交易区间"""
        try:
            # 基于ATR和趋势类型确定区间
            atr_multiplier = 2.0  # ATR倍数
            range_width = metrics.atr_ratio * atr_multiplier
            
            if trend_type == GridTrendType.UPWARD:
                # 上涨趋势：区间偏上
                lower_bound = current_price * (1 - range_width * 0.6)
                upper_bound = current_price * (1 + range_width * 1.4)
            elif trend_type == GridTrendType.SIDEWAYS:
                # 震荡趋势：区间居中
                lower_bound = current_price * (1 - range_width)
                upper_bound = current_price * (1 + range_width)
            else:
                # 下跌趋势：区间偏下 (但我们已经过滤了下跌趋势)
                lower_bound = current_price * (1 - range_width * 1.4)
                upper_bound = current_price * (1 + range_width * 0.6)
            
            # 计算网格间距
            range_span = upper_bound - lower_bound
            grid_spacing = (range_span / current_price) / self.default_grid_count
            
            # 限制网格间距在合理范围内
            grid_spacing = max(self.grid_spacing_range[0] / 100, 
                             min(self.grid_spacing_range[1] / 100, grid_spacing))
            
            # 重新计算网格数量
            grid_count = int(range_span / (current_price * grid_spacing))
            grid_count = max(10, min(30, grid_count))  # 限制在10-30个网格
            
            # 每格仓位大小
            position_size_per_grid = self.base_capital * 0.3 / grid_count  # 30%资金分配给网格
            
            return GridTradingRange(
                lower_bound=round(lower_bound, 4),
                upper_bound=round(upper_bound, 4),
                grid_count=grid_count,
                grid_spacing=round(grid_spacing * 100, 2),  # 转换为百分比
                position_size_per_grid=round(position_size_per_grid, 2)
            )
            
        except Exception as e:
            self.logger.error(f"计算交易区间失败: {e}")
            # 返回默认配置
            return GridTradingRange(
                lower_bound=current_price * 0.9,
                upper_bound=current_price * 1.1,
                grid_count=20,
                grid_spacing=1.0,
                position_size_per_grid=150
            )
    
    def _calculate_position_config(
        self, 
        metrics: GridTradingMetrics, 
        opportunity_level: GridOpportunityLevel, 
        trading_range: GridTradingRange
    ) -> Dict[str, Any]:
        """计算仓位配置"""
        # 基础仓位比例
        base_percentage = {
            GridOpportunityLevel.EXCELLENT: 0.4,  # 40%
            GridOpportunityLevel.GOOD: 0.3,       # 30%
            GridOpportunityLevel.MODERATE: 0.2,   # 20%
            GridOpportunityLevel.POOR: 0.1        # 10%
        }.get(opportunity_level, 0.2)
        
        # 根据波动率调整
        if metrics.volatility_24h > 0.1:  # 高波动率降低仓位
            base_percentage *= 0.8
        elif metrics.volatility_24h < 0.03:  # 低波动率可以增加仓位
            base_percentage *= 1.2
        
        # 限制最大仓位
        final_percentage = min(0.5, max(0.1, base_percentage))
        recommended_capital = self.base_capital * final_percentage
        
        return {
            'percentage': f"{final_percentage * 100:.0f}",
            'capital': recommended_capital
        }
    
    def _calculate_expected_returns(
        self, 
        metrics: GridTradingMetrics, 
        trading_range: GridTradingRange, 
        position_config: Dict[str, Any]
    ) -> Dict[str, float]:
        """计算预期收益"""
        # 基于波动率和网格间距估算收益
        daily_volatility = metrics.volatility_24h
        grid_spacing_decimal = trading_range.grid_spacing / 100
        
        # 估算每日网格触发次数
        daily_triggers = daily_volatility / grid_spacing_decimal
        daily_triggers = min(10, max(0.5, daily_triggers))  # 限制在合理范围
        
        # 每次触发的预期收益 (扣除手续费)
        profit_per_trigger = grid_spacing_decimal * 0.6  # 60%的网格间距作为净收益
        
        # 计算日收益率
        daily_return = daily_triggers * profit_per_trigger * 100  # 转换为百分比
        daily_return = min(5.0, max(0.1, daily_return))  # 限制在0.1%-5%
        
        # 月收益率 (考虑复利)
        monthly_return = ((1 + daily_return / 100) ** 30 - 1) * 100
        
        return {
            'daily': round(daily_return, 2),
            'monthly': round(monthly_return, 2)
        }
    
    def _get_risk_level(self, metrics: GridTradingMetrics) -> str:
        """获取风险等级"""
        if metrics.volatility_24h > 0.12:
            return "高风险"
        elif metrics.volatility_24h > 0.06:
            return "中风险"
        else:
            return "低风险"
    
    def _generate_reasoning(
        self, 
        symbol: str, 
        metrics: GridTradingMetrics, 
        trend_type: GridTrendType
    ) -> str:
        """生成推荐理由"""
        reasons = []
        
        # 波动率分析
        if 0.03 <= metrics.volatility_24h <= 0.08:
            reasons.append("波动率适中，适合网格交易")
        elif metrics.volatility_24h > 0.08:
            reasons.append("高波动率提供更多套利机会")
        
        # 交易量分析
        if metrics.volume_rank <= 5:
            reasons.append("交易量大，流动性充足")
        elif metrics.volume_rank <= 15:
            reasons.append("交易量较好，流动性良好")
        
        # 趋势分析
        if trend_type == GridTrendType.SIDEWAYS:
            reasons.append("震荡行情，网格策略最佳时机")
        elif trend_type == GridTrendType.UPWARD:
            reasons.append("上涨趋势中，做多网格有额外收益")
        
        # 价格变化分析
        if abs(metrics.price_change_7d) < 10:
            reasons.append("价格相对稳定，风险可控")
        
        return "；".join(reasons) if reasons else "基础条件满足网格交易要求"
    
    def _generate_risk_warning(
        self, 
        symbol: str = "",
        volatility: float = 0.0,
        volume: float = 0.0,
        price_change_24h: float = 0.0,
        risk_level: str = "中风险",
        metrics: Optional[GridTradingMetrics] = None, 
        trend_type: Optional[GridTrendType] = None
    ) -> str:
        """生成风险提示"""
        warnings = []
        
        # 使用传入的参数或从 metrics 中获取
        if metrics:
            volatility = metrics.volatility_24h
            volume = metrics.volume_24h
            price_change_24h = metrics.price_change_24h
        
        # 高波动率警告
        if volatility > 0.1:
            warnings.append("高波动率可能导致快速亏损")
        elif volatility > 0.05:
            warnings.append("中等波动率，注意风险控制")
        
        # 趋势风险警告
        if trend_type == GridTrendType.UPWARD:
            warnings.append("上涨趋势中注意回调风险")
        elif trend_type == GridTrendType.DOWNWARD:
            warnings.append("下跌趋势风险较高，谨慎操作")
        
        # 交易量警告
        if volume < 50000000:  # 小于5000万USDT
            warnings.append("交易量较小，可能存在流动性风险")
        
        # 价格变化警告
        if abs(price_change_24h) > 20:
            warnings.append("近期价格波动较大，注意市场风险")
        
        # 基础风险提示
        base_warning = f"网格交易存在{risk_level}，请合理控制仓位"
        
        if warnings:
            return f"{base_warning}；{('；'.join(warnings))}"
        else:
            return f"{base_warning}，建议分批建仓降低风险"
    
    def _meets_opportunity_level(
        self, 
        recommendation: GridTradingRecommendation, 
        min_level: GridOpportunityLevel
    ) -> bool:
        """检查是否满足最低机会等级"""
        level_values = {
            GridOpportunityLevel.POOR: 1,
            GridOpportunityLevel.MODERATE: 2,
            GridOpportunityLevel.GOOD: 3,
            GridOpportunityLevel.EXCELLENT: 4
        }
        
        return level_values.get(recommendation.opportunity_level, 0) >= level_values.get(min_level, 0)
    
    def _get_opportunity_score(self, recommendation: GridTradingRecommendation) -> float:
        """获取机会评分用于排序"""
        level_scores = {
            GridOpportunityLevel.EXCELLENT: 4.0,
            GridOpportunityLevel.GOOD: 3.0,
            GridOpportunityLevel.MODERATE: 2.0,
            GridOpportunityLevel.POOR: 1.0
        }
        
        base_score = level_scores.get(recommendation.opportunity_level, 1.0)
        
        # 根据预期收益调整评分
        return base_score + (recommendation.expected_daily_return / 100)
    
    async def _generate_market_summary(self, recommendations: List[GridTradingRecommendation]) -> str:
        """生成市场总结"""
        if not recommendations:
            return "当前市场条件不适合网格交易，建议等待更好时机"
        
        # 统计分析
        avg_volatility = np.mean([r.metrics.volatility_24h for r in recommendations])
        avg_expected_return = np.mean([r.expected_daily_return for r in recommendations])
        
        # 趋势分布
        trend_counts = {}
        for rec in recommendations:
            trend = rec.trend_type.value
            trend_counts[trend] = trend_counts.get(trend, 0) + 1
        
        dominant_trend = max(trend_counts.items(), key=lambda x: x[1])[0] if trend_counts else "震荡"
        
        summary = f"市场整体{dominant_trend}，平均波动率{avg_volatility*100:.1f}%，"
        summary += f"网格策略预期日收益{avg_expected_return:.2f}%"
        
        if len(recommendations) >= 5:
            summary += "，多个优质机会可供选择"
        elif len(recommendations) >= 2:
            summary += "，有少量机会值得关注"
        else:
            summary += "，机会有限需谨慎选择"
        
        return summary

    async def analyze_grid_opportunity(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        分析单个交易对的网格交易机会
        Analyze grid trading opportunity for a specific symbol
        
        Args:
            symbol: 交易对符号 (如: STBL-USDT-SWAP)
            
        Returns:
            网格交易机会分析结果
        """
        try:
            self.logger.info(f"🔍 分析 {symbol} 的网格交易机会...")
            
            if not self.initialized:
                await self.initialize()
            
            # 转换为币安格式进行数据获取
            binance_symbol = symbol.replace('-USDT-SWAP', 'USDT')
            
            # 获取市场数据
            ticker = await self.exchange_service.get_ticker(binance_symbol)
            if not ticker:
                self.logger.warning(f"⚠️ 无法获取 {symbol} 的ticker数据")
                return None
            
            # 获取K线数据用于波动率分析
            klines = await self.exchange_service.get_klines(
                symbol=binance_symbol,
                timeframe='1h',
                limit=24  # 24小时数据
            )
            
            if not klines or len(klines) < 10:
                self.logger.warning(f"⚠️ {symbol} K线数据不足")
                return None
            
            # 提取价格数据
            prices = [float(kline.get('close', 0)) for kline in klines if kline.get('close')]
            if not prices:
                return None
                
            current_price = float(ticker.get('last', 0))
            high_24h = float(ticker.get('high24h', current_price))  # 修复字段名
            low_24h = float(ticker.get('low24h', current_price))    # 修复字段名
            volume_24h = float(ticker.get('volCcy24h', 0))  # 24小时成交额(USDT)
            
            # 计算波动率指标 - 修复币安API返回0的问题
            if high_24h == 0 or low_24h == 0:
                # 使用K线数据计算波动率
                if len(prices) >= 10:
                    high_24h = max(prices)
                    low_24h = min(prices)
                    self.logger.info(f"📊 {symbol} 使用K线数据计算波动率: 高 {high_24h:.4f}, 低 {low_24h:.4f}")
                else:
                    self.logger.warning(f"⚠️ {symbol} 无法获取有效的价格数据")
                    return None
            
            price_range = high_24h - low_24h
            volatility = (price_range / current_price) * 100 if current_price > 0 else 0
            
            # 计算小时平均波动
            hourly_volatility = 0
            if len(prices) > 1:
                hourly_changes = []
                for i in range(1, len(prices)):
                    if prices[i-1] > 0:
                        change = abs(prices[i] - prices[i-1]) / prices[i-1]
                        hourly_changes.append(change)
                
                if hourly_changes:
                    hourly_volatility = sum(hourly_changes) / len(hourly_changes) * 100
            
            # 网格交易适合性评估
            risk_level = "LOW"
            expected_return = 0.0
            recommended_grids = 10
            
            if volatility > 15:  # 高波动
                risk_level = "HIGH"
                expected_return = min(volatility * 0.3, 25.0)  # 预期收益率
                recommended_grids = min(int(volatility), 20)
            elif volatility > 8:  # 中等波动
                risk_level = "MEDIUM" 
                expected_return = volatility * 0.4
                recommended_grids = min(int(volatility * 1.2), 15)
            elif volatility > 1.5:  # 降低阈值到1.5%
                risk_level = "LOW"
                expected_return = volatility * 0.6  # 提高低波动的收益预期
                recommended_grids = max(int(volatility * 2), 8)  # 增加网格数量
            else:
                # 波动率太低，不适合网格
                self.logger.info(f"⚠️ {symbol} 波动率 {volatility:.2f}% 过低，不适合网格交易")
                return None
            
            # 价格区间建议
            price_range_suggestion = {
                "lower_bound": low_24h * 0.95,  # 比24h最低价再低5%
                "upper_bound": high_24h * 1.05,  # 比24h最高价再高5%
                "current_price": current_price
            }
            
            opportunity = {
                "symbol": symbol,
                "expected_return": expected_return / 100,  # 转换为小数
                "risk_level": risk_level,
                "recommended_grids": recommended_grids,
                "price_range": price_range_suggestion,
                "volatility_24h": volatility,
                "hourly_volatility": hourly_volatility,
                "volume_24h_usdt": volume_24h,  # 24小时成交额(USDT)
                "analysis_time": datetime.now().isoformat(),
                "suitable_for_grid": True
            }
            
            self.logger.info(f"✅ {symbol} 网格分析完成: 预期收益 {expected_return:.1f}%, 风险 {risk_level}")
            return opportunity
            
        except Exception as e:
            self.logger.error(f"❌ 分析 {symbol} 网格机会失败: {e}")
            return None


async def get_grid_trading_service() -> GridTradingService:
    """获取网格交易服务实例"""
    global _grid_trading_service
    if _grid_trading_service is None:
        _grid_trading_service = GridTradingService()
        await _grid_trading_service.initialize()
    return _grid_trading_service