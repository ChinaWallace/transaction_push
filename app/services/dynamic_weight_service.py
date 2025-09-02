# -*- coding: utf-8 -*-
"""
动态权重管理服务
Dynamic Weight Management Service - 根据市场波动性动态调整各模块权重
"""

import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.okx_service import OKXService
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class MarketRegime(Enum):
    """市场状态"""
    LOW_VOLATILITY = "low_volatility"       # 低波动
    NORMAL_VOLATILITY = "normal_volatility" # 正常波动
    HIGH_VOLATILITY = "high_volatility"     # 高波动
    EXTREME_VOLATILITY = "extreme_volatility" # 极端波动


class TrendStrength(Enum):
    """趋势强度"""
    WEAK = "weak"           # 弱趋势
    MODERATE = "moderate"   # 中等趋势
    STRONG = "strong"       # 强趋势


@dataclass
class MarketCondition:
    """市场状况"""
    symbol: str
    volatility_level: MarketRegime
    trend_strength: TrendStrength
    volatility_score: float  # 波动性分数 (0-1)
    trend_score: float       # 趋势强度分数 (0-1)
    volume_activity: float   # 成交量活跃度 (0-1)
    timestamp: datetime


@dataclass
class DynamicWeights:
    """动态权重配置"""
    kronos_weight: float      # Kronos AI权重
    technical_weight: float   # 技术分析权重
    ml_weight: float         # ML预测权重
    position_weight: float   # 持仓分析权重
    market_regime: MarketRegime
    confidence_multiplier: float  # 置信度乘数
    reasoning: str           # 权重调整原因
    timestamp: datetime
    
    def normalize_weights(self):
        """标准化权重，确保总和为1"""
        total = self.kronos_weight + self.technical_weight + self.ml_weight + self.position_weight
        if total > 0:
            self.kronos_weight /= total
            self.technical_weight /= total
            self.ml_weight /= total
            self.position_weight /= total


class DynamicWeightService:
    """动态权重管理服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.okx_service = OKXService()
        
        # 基础权重配置
        self.base_weights = {
            'kronos': 0.50,
            'technical': 0.35,
            'ml': 0.10,
            'position': 0.05
        }
        
        # 波动性阈值配置
        self.volatility_config = {
            'low_threshold': 0.02,      # 2%日波动率
            'normal_threshold': 0.05,   # 5%日波动率
            'high_threshold': 0.10,     # 10%日波动率
        }
        
        # 权重调整策略
        self.weight_strategies = {
            MarketRegime.LOW_VOLATILITY: {
                'kronos': 0.60,      # 低波动期增加AI权重
                'technical': 0.25,   # 降低技术分析权重
                'ml': 0.10,
                'position': 0.05,
                'confidence_multiplier': 1.1,  # 提升置信度
                'reasoning': '低波动期：增加AI预测权重，技术指标可能滞后'
            },
            MarketRegime.NORMAL_VOLATILITY: {
                'kronos': 0.50,      # 正常权重
                'technical': 0.35,
                'ml': 0.10,
                'position': 0.05,
                'confidence_multiplier': 1.0,
                'reasoning': '正常波动期：使用标准权重配置'
            },
            MarketRegime.HIGH_VOLATILITY: {
                'kronos': 0.40,      # 高波动期降低AI权重
                'technical': 0.45,   # 增加技术分析权重
                'ml': 0.10,
                'position': 0.05,
                'confidence_multiplier': 0.9,  # 降低置信度
                'reasoning': '高波动期：增加技术分析权重，AI预测可能不稳定'
            },
            MarketRegime.EXTREME_VOLATILITY: {
                'kronos': 0.30,      # 极端波动期大幅降低AI权重
                'technical': 0.55,   # 大幅增加技术分析权重
                'ml': 0.10,
                'position': 0.05,
                'confidence_multiplier': 0.8,  # 显著降低置信度
                'reasoning': '极端波动期：主要依赖技术分析，AI预测不可靠'
            }
        }
        
        # 缓存
        self._market_condition_cache = {}
        self._weight_cache = {}
        self._cache_expiry = {}
        self._cache_duration = 900  # 15分钟缓存
    
    async def analyze_market_condition(self, symbol: str) -> Optional[MarketCondition]:
        """
        分析市场状况
        
        Args:
            symbol: 交易对符号
            
        Returns:
            MarketCondition: 市场状况分析
        """
        try:
            # 检查缓存
            cache_key = f"market_condition_{symbol}"
            if self._is_cache_valid(cache_key):
                return self._market_condition_cache.get(cache_key)
            
            # 获取K线数据（24小时，1小时周期）
            klines = await self.okx_service.get_kline_data(
                symbol=symbol,
                timeframe='1h',
                limit=24
            )
            
            if not klines or len(klines) < 20:
                self.logger.warning(f"⚠️ {symbol} K线数据不足，无法分析市场状况")
                return None
            
            # 计算波动性指标
            volatility_score = self._calculate_volatility_score(klines)
            volatility_level = self._determine_volatility_level(volatility_score)
            
            # 计算趋势强度
            trend_score = self._calculate_trend_strength(klines)
            trend_strength = self._determine_trend_strength(trend_score)
            
            # 计算成交量活跃度
            volume_activity = self._calculate_volume_activity(klines)
            
            # 创建市场状况
            condition = MarketCondition(
                symbol=symbol,
                volatility_level=volatility_level,
                trend_strength=trend_strength,
                volatility_score=volatility_score,
                trend_score=trend_score,
                volume_activity=volume_activity,
                timestamp=datetime.now()
            )
            
            # 更新缓存
            self._market_condition_cache[cache_key] = condition
            self._cache_expiry[cache_key] = datetime.now() + timedelta(seconds=self._cache_duration)
            
            self.logger.debug(
                f"📊 {symbol} 市场状况: 波动性={volatility_level.value} ({volatility_score:.3f}) "
                f"趋势={trend_strength.value} ({trend_score:.3f}) 成交量活跃度={volume_activity:.3f}"
            )
            
            return condition
            
        except Exception as e:
            self.logger.error(f"❌ 分析 {symbol} 市场状况失败: {e}")
            return None
    
    async def get_dynamic_weights(self, symbol: str) -> DynamicWeights:
        """
        获取动态权重配置
        
        Args:
            symbol: 交易对符号
            
        Returns:
            DynamicWeights: 动态权重配置
        """
        try:
            # 检查缓存
            cache_key = f"dynamic_weights_{symbol}"
            if self._is_cache_valid(cache_key):
                return self._weight_cache.get(cache_key)
            
            # 分析市场状况
            market_condition = await self.analyze_market_condition(symbol)
            
            if not market_condition:
                # 使用默认权重
                weights = DynamicWeights(
                    kronos_weight=self.base_weights['kronos'],
                    technical_weight=self.base_weights['technical'],
                    ml_weight=self.base_weights['ml'],
                    position_weight=self.base_weights['position'],
                    market_regime=MarketRegime.NORMAL_VOLATILITY,
                    confidence_multiplier=1.0,
                    reasoning='无法获取市场数据，使用默认权重',
                    timestamp=datetime.now()
                )
                return weights
            
            # 根据市场状况获取权重策略
            strategy = self.weight_strategies.get(
                market_condition.volatility_level,
                self.weight_strategies[MarketRegime.NORMAL_VOLATILITY]
            )
            
            # 创建动态权重
            weights = DynamicWeights(
                kronos_weight=strategy['kronos'],
                technical_weight=strategy['technical'],
                ml_weight=strategy['ml'],
                position_weight=strategy['position'],
                market_regime=market_condition.volatility_level,
                confidence_multiplier=strategy['confidence_multiplier'],
                reasoning=strategy['reasoning'],
                timestamp=datetime.now()
            )
            
            # 根据趋势强度和成交量活跃度微调权重
            weights = self._fine_tune_weights(weights, market_condition)
            
            # 标准化权重
            weights.normalize_weights()
            
            # 更新缓存
            self._weight_cache[cache_key] = weights
            self._cache_expiry[cache_key] = datetime.now() + timedelta(seconds=self._cache_duration)
            
            self.logger.info(
                f"⚖️ {symbol} 动态权重: Kronos={weights.kronos_weight:.2f} "
                f"技术={weights.technical_weight:.2f} ML={weights.ml_weight:.2f} "
                f"持仓={weights.position_weight:.2f} ({weights.market_regime.value})"
            )
            
            return weights
            
        except Exception as e:
            self.logger.error(f"❌ 获取 {symbol} 动态权重失败: {e}")
            # 返回默认权重
            return DynamicWeights(
                kronos_weight=self.base_weights['kronos'],
                technical_weight=self.base_weights['technical'],
                ml_weight=self.base_weights['ml'],
                position_weight=self.base_weights['position'],
                market_regime=MarketRegime.NORMAL_VOLATILITY,
                confidence_multiplier=1.0,
                reasoning='获取动态权重失败，使用默认权重',
                timestamp=datetime.now()
            )
    
    async def batch_get_dynamic_weights(self, symbols: List[str]) -> Dict[str, DynamicWeights]:
        """
        批量获取动态权重
        
        Args:
            symbols: 交易对列表
            
        Returns:
            Dict[str, DynamicWeights]: 权重配置字典
        """
        try:
            self.logger.info(f"⚖️ 开始批量获取动态权重: {len(symbols)} 个交易对")
            
            # 并发获取权重
            tasks = [self.get_dynamic_weights(symbol) for symbol in symbols]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            weight_results = {}
            for i, result in enumerate(results):
                symbol = symbols[i]
                if isinstance(result, Exception):
                    self.logger.error(f"❌ 获取 {symbol} 动态权重失败: {result}")
                    # 使用默认权重
                    weight_results[symbol] = DynamicWeights(
                        kronos_weight=self.base_weights['kronos'],
                        technical_weight=self.base_weights['technical'],
                        ml_weight=self.base_weights['ml'],
                        position_weight=self.base_weights['position'],
                        market_regime=MarketRegime.NORMAL_VOLATILITY,
                        confidence_multiplier=1.0,
                        reasoning='获取失败，使用默认权重',
                        timestamp=datetime.now()
                    )
                else:
                    weight_results[symbol] = result
            
            self.logger.info(f"✅ 批量动态权重获取完成")
            return weight_results
            
        except Exception as e:
            self.logger.error(f"❌ 批量获取动态权重失败: {e}")
            return {}
    
    def _calculate_volatility_score(self, klines: List[Dict]) -> float:
        """计算波动性分数"""
        try:
            # 计算每小时收益率
            returns = []
            for i in range(1, len(klines)):
                prev_close = float(klines[i-1].get('close', 0))
                curr_close = float(klines[i].get('close', 0))
                if prev_close > 0:
                    returns.append((curr_close - prev_close) / prev_close)
            
            if not returns:
                return 0.0
            
            # 计算标准差（波动率）
            volatility = np.std(returns) * np.sqrt(24)  # 年化波动率
            
            # 标准化到0-1范围
            normalized_volatility = min(volatility / 0.5, 1.0)  # 50%作为最大值
            
            return normalized_volatility
            
        except Exception as e:
            self.logger.error(f"计算波动性分数失败: {e}")
            return 0.0
    
    def _determine_volatility_level(self, volatility_score: float) -> MarketRegime:
        """确定波动性级别"""
        if volatility_score >= 0.8:
            return MarketRegime.EXTREME_VOLATILITY
        elif volatility_score >= 0.5:
            return MarketRegime.HIGH_VOLATILITY
        elif volatility_score >= 0.2:
            return MarketRegime.NORMAL_VOLATILITY
        else:
            return MarketRegime.LOW_VOLATILITY
    
    def _calculate_trend_strength(self, klines: List[Dict]) -> float:
        """计算趋势强度"""
        try:
            if len(klines) < 10:
                return 0.0
            
            # 计算价格序列
            prices = [float(kline.get('close', 0)) for kline in klines]
            
            # 计算线性回归斜率
            x = np.arange(len(prices))
            slope, _ = np.polyfit(x, prices, 1)
            
            # 计算R²（拟合度）
            y_pred = slope * x + np.mean(prices)
            ss_res = np.sum((prices - y_pred) ** 2)
            ss_tot = np.sum((prices - np.mean(prices)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            
            # 趋势强度 = |斜率| * R²
            trend_strength = abs(slope / np.mean(prices)) * r_squared if np.mean(prices) > 0 else 0
            
            # 标准化到0-1范围
            return min(trend_strength * 100, 1.0)
            
        except Exception as e:
            self.logger.error(f"计算趋势强度失败: {e}")
            return 0.0
    
    def _determine_trend_strength(self, trend_score: float) -> TrendStrength:
        """确定趋势强度级别"""
        if trend_score >= 0.7:
            return TrendStrength.STRONG
        elif trend_score >= 0.4:
            return TrendStrength.MODERATE
        else:
            return TrendStrength.WEAK
    
    def _calculate_volume_activity(self, klines: List[Dict]) -> float:
        """计算成交量活跃度"""
        try:
            volumes = [float(kline.get('volume', 0)) for kline in klines]
            
            if not volumes:
                return 0.0
            
            # 计算成交量变异系数
            mean_volume = np.mean(volumes)
            std_volume = np.std(volumes)
            
            if mean_volume > 0:
                cv = std_volume / mean_volume
                # 标准化到0-1范围
                return min(cv, 1.0)
            
            return 0.0
            
        except Exception as e:
            self.logger.error(f"计算成交量活跃度失败: {e}")
            return 0.0
    
    def _fine_tune_weights(self, weights: DynamicWeights, condition: MarketCondition) -> DynamicWeights:
        """根据趋势强度和成交量活跃度微调权重"""
        try:
            # 强趋势时增加技术分析权重
            if condition.trend_strength == TrendStrength.STRONG:
                weights.technical_weight *= 1.1
                weights.kronos_weight *= 0.95
            
            # 高成交量活跃度时增加技术分析权重
            if condition.volume_activity > 0.7:
                weights.technical_weight *= 1.05
                weights.kronos_weight *= 0.98
            
            # 低成交量活跃度时增加AI权重
            elif condition.volume_activity < 0.3:
                weights.kronos_weight *= 1.05
                weights.technical_weight *= 0.98
            
            return weights
            
        except Exception as e:
            self.logger.error(f"微调权重失败: {e}")
            return weights
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """检查缓存是否有效"""
        if cache_key not in self._cache_expiry:
            return False
        return datetime.now() < self._cache_expiry[cache_key]
    
    async def get_weight_summary(self, symbols: List[str]) -> Dict[str, Any]:
        """获取权重配置摘要"""
        try:
            weights_dict = await self.batch_get_dynamic_weights(symbols)
            
            summary = {
                'timestamp': datetime.now(),
                'total_symbols': len(symbols),
                'regime_distribution': {regime.value: 0 for regime in MarketRegime},
                'average_weights': {
                    'kronos': 0.0,
                    'technical': 0.0,
                    'ml': 0.0,
                    'position': 0.0
                },
                'confidence_multipliers': [],
                'regime_examples': {}
            }
            
            # 统计权重分布
            valid_weights = []
            for symbol, weights in weights_dict.items():
                if weights:
                    summary['regime_distribution'][weights.market_regime.value] += 1
                    valid_weights.append(weights)
                    summary['confidence_multipliers'].append(weights.confidence_multiplier)
                    
                    # 记录每种市场状态的示例
                    regime_key = weights.market_regime.value
                    if regime_key not in summary['regime_examples']:
                        summary['regime_examples'][regime_key] = []
                    if len(summary['regime_examples'][regime_key]) < 3:
                        summary['regime_examples'][regime_key].append({
                            'symbol': symbol,
                            'kronos_weight': weights.kronos_weight,
                            'technical_weight': weights.technical_weight,
                            'reasoning': weights.reasoning
                        })
            
            # 计算平均权重
            if valid_weights:
                summary['average_weights']['kronos'] = np.mean([w.kronos_weight for w in valid_weights])
                summary['average_weights']['technical'] = np.mean([w.technical_weight for w in valid_weights])
                summary['average_weights']['ml'] = np.mean([w.ml_weight for w in valid_weights])
                summary['average_weights']['position'] = np.mean([w.position_weight for w in valid_weights])
            
            return summary
            
        except Exception as e:
            self.logger.error(f"❌ 获取权重摘要失败: {e}")
            return {
                'timestamp': datetime.now(),
                'error': str(e),
                'total_symbols': len(symbols)
            }


# 全局服务实例
_dynamic_weight_service = None


def get_dynamic_weight_service() -> DynamicWeightService:
    """获取动态权重服务实例"""
    global _dynamic_weight_service
    if _dynamic_weight_service is None:
        _dynamic_weight_service = DynamicWeightService()
    return _dynamic_weight_service