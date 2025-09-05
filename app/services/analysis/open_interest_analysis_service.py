# -*- coding: utf-8 -*-
"""
持仓量变动分析服务
Open Interest Analysis Service - 分析持仓量变动并提供趋势确认
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.exchanges.okx.okx_service import OKXService

logger = get_logger(__name__)
settings = get_settings()


class OIChangeLevel(Enum):
    """持仓量变化级别"""
    NORMAL = "normal"           # 正常变化 (<10%)
    MODERATE = "moderate"       # 中等变化 (10-20%)
    SIGNIFICANT = "significant" # 显著变化 (20-40%)
    EXTREME = "extreme"         # 极端变化 (>40%)


class OITrendSignal(Enum):
    """持仓量趋势信号"""
    BULLISH_CONFIRMATION = "bullish_confirmation"     # 看涨确认
    BEARISH_CONFIRMATION = "bearish_confirmation"     # 看跌确认
    TREND_WEAKENING = "trend_weakening"               # 趋势减弱
    TREND_STRENGTHENING = "trend_strengthening"       # 趋势加强
    NEUTRAL = "neutral"                               # 中性


@dataclass
class OpenInterestAnalysis:
    """持仓量分析数据"""
    symbol: str
    current_oi: float
    oi_change_24h: float
    oi_change_percent: float
    change_level: OIChangeLevel
    trend_signal: OITrendSignal
    price_change_24h: float
    signal_strength_boost: float  # 信号强度提升因子
    trend_confirmation_score: float  # 趋势确认分数 (0-1)
    timestamp: datetime
    
    def is_bullish_signal(self) -> bool:
        """判断是否为看涨信号"""
        return self.trend_signal in [OITrendSignal.BULLISH_CONFIRMATION, OITrendSignal.TREND_STRENGTHENING]
    
    def is_bearish_signal(self) -> bool:
        """判断是否为看跌信号"""
        return self.trend_signal in [OITrendSignal.BEARISH_CONFIRMATION, OITrendSignal.TREND_STRENGTHENING]


class OpenInterestAnalysisService:
    """持仓量变动分析服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.okx_service = OKXService()
        
        # 分析配置
        self.analysis_config = {
            'moderate_threshold': 10.0,     # 10%变化
            'significant_threshold': 20.0,  # 20%变化
            'extreme_threshold': 40.0,      # 40%变化
            'min_oi_value': 10000000,       # 最小持仓量1000万USDT
        }
        
        # 信号强度提升配置
        self.strength_boost_config = {
            OIChangeLevel.NORMAL: 0.0,
            OIChangeLevel.MODERATE: 0.03,     # 提升3%
            OIChangeLevel.SIGNIFICANT: 0.06,  # 提升6%
            OIChangeLevel.EXTREME: 0.10,      # 提升10%
        }
        
        # 缓存
        self._oi_cache = {}
        self._cache_expiry = {}
        self._cache_duration = 600  # 10分钟缓存
    
    async def analyze_open_interest(self, symbol: str) -> Optional[OpenInterestAnalysis]:
        """
        分析单个交易对的持仓量变动
        
        Args:
            symbol: 交易对符号
            
        Returns:
            OpenInterestAnalysis: 分析结果
        """
        try:
            # 检查缓存
            cache_key = f"oi_analysis_{symbol}"
            if self._is_cache_valid(cache_key):
                return self._oi_cache.get(cache_key)
            
            # 获取持仓量数据
            oi_data = await self.okx_service.get_open_interest(symbol)
            if not oi_data:
                self.logger.warning(f"⚠️ {symbol} 无法获取持仓量数据")
                return None
            
            current_oi = float(oi_data.get('oi', 0))
            oi_change_24h = float(oi_data.get('oiCcy24h', 0))
            
            # 检查最小持仓量要求
            if current_oi < self.analysis_config['min_oi_value']:
                return None
            
            # 计算变化百分比
            oi_change_percent = (oi_change_24h / current_oi * 100) if current_oi > 0 else 0
            
            # 获取价格变化数据
            price_change_24h = await self._get_price_change_24h(symbol)
            
            # 确定变化级别
            change_level = self._determine_change_level(abs(oi_change_percent))
            
            # 分析趋势信号
            trend_signal = self._analyze_trend_signal(oi_change_percent, price_change_24h)
            
            # 计算信号强度提升
            signal_strength_boost = self._calculate_strength_boost(change_level, trend_signal)
            
            # 计算趋势确认分数
            trend_confirmation_score = self._calculate_trend_confirmation_score(
                oi_change_percent, price_change_24h, change_level
            )
            
            # 创建分析结果
            analysis = OpenInterestAnalysis(
                symbol=symbol,
                current_oi=current_oi,
                oi_change_24h=oi_change_24h,
                oi_change_percent=oi_change_percent,
                change_level=change_level,
                trend_signal=trend_signal,
                price_change_24h=price_change_24h,
                signal_strength_boost=signal_strength_boost,
                trend_confirmation_score=trend_confirmation_score,
                timestamp=datetime.now()
            )
            
            # 更新缓存
            self._oi_cache[cache_key] = analysis
            self._cache_expiry[cache_key] = datetime.now() + timedelta(seconds=self._cache_duration)
            
            # 记录显著变化
            if change_level != OIChangeLevel.NORMAL:
                direction = "📈" if oi_change_percent > 0 else "📉"
                price_dir = "📈" if price_change_24h > 0 else "📉" if price_change_24h < 0 else "➖"
                self.logger.info(
                    f"📊 {symbol} 持仓量分析: {direction} {oi_change_percent:+.2f}% ({change_level.value}) "
                    f"价格: {price_dir} {price_change_24h:+.2f}% "
                    f"信号: {trend_signal.value} 强度提升: +{signal_strength_boost:.1%}"
                )
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"❌ 分析 {symbol} 持仓量失败: {e}")
            return None
    
    async def batch_analyze_open_interest(self, symbols: List[str]) -> Dict[str, Optional[OpenInterestAnalysis]]:
        """
        批量分析持仓量变动
        
        Args:
            symbols: 交易对列表
            
        Returns:
            Dict[str, OpenInterestAnalysis]: 分析结果字典
        """
        try:
            self.logger.info(f"📊 开始批量分析持仓量变动: {len(symbols)} 个交易对")
            
            # 并发分析
            tasks = [self.analyze_open_interest(symbol) for symbol in symbols]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            analysis_results = {}
            significant_count = 0
            
            for i, result in enumerate(results):
                symbol = symbols[i]
                if isinstance(result, Exception):
                    self.logger.error(f"❌ 分析 {symbol} 持仓量失败: {result}")
                    analysis_results[symbol] = None
                else:
                    analysis_results[symbol] = result
                    if result and result.change_level != OIChangeLevel.NORMAL:
                        significant_count += 1
            
            self.logger.info(f"✅ 批量持仓量分析完成: 发现 {significant_count} 个显著变化")
            return analysis_results
            
        except Exception as e:
            self.logger.error(f"❌ 批量分析持仓量失败: {e}")
            return {}
    
    def get_trend_confirmation_boost(self, symbol: str, trend_direction: str) -> float:
        """
        获取基于持仓量的趋势确认提升
        
        Args:
            symbol: 交易对
            trend_direction: 趋势方向 (up/down)
            
        Returns:
            float: 趋势确认提升因子 (0-0.15)
        """
        try:
            cache_key = f"oi_analysis_{symbol}"
            analysis = self._oi_cache.get(cache_key)
            
            if not analysis or analysis.change_level == OIChangeLevel.NORMAL:
                return 0.0
            
            # 根据趋势方向和持仓量变化判断
            if trend_direction.lower() == 'up':
                if analysis.trend_signal == OITrendSignal.BULLISH_CONFIRMATION:
                    return analysis.signal_strength_boost
                elif analysis.trend_signal == OITrendSignal.TREND_STRENGTHENING:
                    return analysis.signal_strength_boost * 0.8
            
            elif trend_direction.lower() == 'down':
                if analysis.trend_signal == OITrendSignal.BEARISH_CONFIRMATION:
                    return analysis.signal_strength_boost
                elif analysis.trend_signal == OITrendSignal.TREND_STRENGTHENING:
                    return analysis.signal_strength_boost * 0.8
            
            # 趋势减弱时给予负向调整
            if analysis.trend_signal == OITrendSignal.TREND_WEAKENING:
                return -analysis.signal_strength_boost * 0.5
            
            return 0.0
            
        except Exception as e:
            self.logger.error(f"❌ 获取 {symbol} 趋势确认提升失败: {e}")
            return 0.0
    
    async def _get_price_change_24h(self, symbol: str) -> float:
        """获取24小时价格变化"""
        try:
            ticker = await self.okx_service.get_ticker(symbol)
            if ticker:
                return float(ticker.get('sodUtc0', 0))  # 24小时涨跌幅
            return 0.0
        except Exception as e:
            self.logger.warning(f"⚠️ 获取 {symbol} 价格变化失败: {e}")
            return 0.0
    
    def _determine_change_level(self, abs_change_percent: float) -> OIChangeLevel:
        """确定变化级别"""
        if abs_change_percent >= self.analysis_config['extreme_threshold']:
            return OIChangeLevel.EXTREME
        elif abs_change_percent >= self.analysis_config['significant_threshold']:
            return OIChangeLevel.SIGNIFICANT
        elif abs_change_percent >= self.analysis_config['moderate_threshold']:
            return OIChangeLevel.MODERATE
        else:
            return OIChangeLevel.NORMAL
    
    def _analyze_trend_signal(self, oi_change_percent: float, price_change_24h: float) -> OITrendSignal:
        """
        分析趋势信号
        
        持仓量增加 + 价格上涨 = 看涨确认
        持仓量增加 + 价格下跌 = 看跌确认（空头增加）
        持仓量减少 + 价格上涨 = 趋势减弱（多头获利了结）
        持仓量减少 + 价格下跌 = 趋势减弱（空头平仓）
        """
        oi_increasing = oi_change_percent > 5.0  # 持仓量增加超过5%
        oi_decreasing = oi_change_percent < -5.0  # 持仓量减少超过5%
        price_rising = price_change_24h > 1.0    # 价格上涨超过1%
        price_falling = price_change_24h < -1.0  # 价格下跌超过1%
        
        if oi_increasing and price_rising:
            return OITrendSignal.BULLISH_CONFIRMATION
        elif oi_increasing and price_falling:
            return OITrendSignal.BEARISH_CONFIRMATION
        elif oi_decreasing and (price_rising or price_falling):
            return OITrendSignal.TREND_WEAKENING
        elif abs(oi_change_percent) > 15.0:  # 大幅持仓量变化
            return OITrendSignal.TREND_STRENGTHENING
        else:
            return OITrendSignal.NEUTRAL
    
    def _calculate_strength_boost(self, change_level: OIChangeLevel, trend_signal: OITrendSignal) -> float:
        """计算信号强度提升"""
        base_boost = self.strength_boost_config.get(change_level, 0.0)
        
        # 根据趋势信号调整
        if trend_signal in [OITrendSignal.BULLISH_CONFIRMATION, OITrendSignal.BEARISH_CONFIRMATION]:
            base_boost *= 1.2  # 趋势确认时额外提升20%
        elif trend_signal == OITrendSignal.TREND_STRENGTHENING:
            base_boost *= 1.1  # 趋势加强时额外提升10%
        elif trend_signal == OITrendSignal.TREND_WEAKENING:
            base_boost *= 0.5  # 趋势减弱时减半
        
        return min(base_boost, 0.15)  # 最大提升15%
    
    def _calculate_trend_confirmation_score(self, oi_change_percent: float, 
                                          price_change_24h: float, 
                                          change_level: OIChangeLevel) -> float:
        """
        计算趋势确认分数
        
        Returns:
            float: 确认分数 (0-1)
        """
        # 基础分数基于变化级别
        level_scores = {
            OIChangeLevel.NORMAL: 0.0,
            OIChangeLevel.MODERATE: 0.3,
            OIChangeLevel.SIGNIFICANT: 0.6,
            OIChangeLevel.EXTREME: 0.9
        }
        
        base_score = level_scores.get(change_level, 0.0)
        
        # 根据持仓量和价格的一致性调整
        if abs(oi_change_percent) > 5.0 and abs(price_change_24h) > 1.0:
            # 持仓量和价格同向变化
            if (oi_change_percent > 0 and price_change_24h > 0) or \
               (oi_change_percent < 0 and price_change_24h < 0):
                base_score *= 1.2
            # 持仓量和价格反向变化（可能是趋势转换信号）
            else:
                base_score *= 0.8
        
        return min(base_score, 1.0)
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """检查缓存是否有效"""
        if cache_key not in self._cache_expiry:
            return False
        return datetime.now() < self._cache_expiry[cache_key]
    
    async def get_analysis_summary(self, symbols: List[str]) -> Dict[str, Any]:
        """获取持仓量分析摘要"""
        try:
            analyses = await self.batch_analyze_open_interest(symbols)
            
            summary = {
                'timestamp': datetime.now(),
                'total_symbols': len(symbols),
                'significant_changes': 0,
                'by_level': {level.value: 0 for level in OIChangeLevel},
                'by_signal': {signal.value: 0 for signal in OITrendSignal},
                'bullish_confirmations': 0,
                'bearish_confirmations': 0,
                'top_changes': []
            }
            
            # 统计分析结果
            valid_analyses = []
            for symbol, analysis in analyses.items():
                if analysis:
                    summary['by_level'][analysis.change_level.value] += 1
                    summary['by_signal'][analysis.trend_signal.value] += 1
                    
                    if analysis.change_level != OIChangeLevel.NORMAL:
                        summary['significant_changes'] += 1
                        valid_analyses.append(analysis)
                    
                    if analysis.trend_signal == OITrendSignal.BULLISH_CONFIRMATION:
                        summary['bullish_confirmations'] += 1
                    elif analysis.trend_signal == OITrendSignal.BEARISH_CONFIRMATION:
                        summary['bearish_confirmations'] += 1
            
            # 排序并获取前5个变化
            valid_analyses.sort(key=lambda x: abs(x.oi_change_percent), reverse=True)
            summary['top_changes'] = [
                {
                    'symbol': a.symbol,
                    'oi_change_percent': a.oi_change_percent,
                    'price_change_24h': a.price_change_24h,
                    'change_level': a.change_level.value,
                    'trend_signal': a.trend_signal.value,
                    'confirmation_score': a.trend_confirmation_score
                }
                for a in valid_analyses[:5]
            ]
            
            return summary
            
        except Exception as e:
            self.logger.error(f"❌ 获取持仓量分析摘要失败: {e}")
            return {
                'timestamp': datetime.now(),
                'error': str(e),
                'total_symbols': len(symbols),
                'significant_changes': 0
            }


# 全局服务实例
_oi_analysis_service = None


def get_oi_analysis_service() -> OpenInterestAnalysisService:
    """获取持仓量分析服务实例"""
    global _oi_analysis_service
    if _oi_analysis_service is None:
        _oi_analysis_service = OpenInterestAnalysisService()
    return _oi_analysis_service