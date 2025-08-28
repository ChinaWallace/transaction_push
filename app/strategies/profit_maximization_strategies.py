# -*- coding: utf-8 -*-
"""
收益最大化策略
Profit Maximization Strategies - 专为币圈高波动环境设计
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import asyncio
import numpy as np

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.okx_service import OKXService
from app.services.kronos_prediction_service import get_kronos_service

logger = get_logger(__name__)
settings = get_settings()


class OpportunityType(Enum):
    """机会类型"""
    BREAKOUT = "突破机会"           # 价格突破关键阻力/支撑
    REVERSAL = "反转机会"           # 趋势反转
    ARBITRAGE = "套利机会"          # 价差套利
    FUNDING_RATE = "费率机会"       # 资金费率套利
    VOLATILITY = "波动率机会"       # 高波动率交易
    NEWS_DRIVEN = "消息驱动"        # 基于消息面
    TECHNICAL_PATTERN = "技术形态"   # 经典技术形态


@dataclass
class ProfitOpportunity:
    """收益机会"""
    symbol: str
    opportunity_type: OpportunityType
    entry_price: float
    target_price: float
    stop_loss: float
    expected_return: float
    risk_reward_ratio: float
    confidence: float
    time_horizon: str  # "5m", "15m", "1h", "4h", "1d"
    reasoning: str
    urgency: str  # "immediate", "within_1h", "within_4h", "today"
    
    # Kronos增强信息
    kronos_support: bool
    kronos_confidence: float
    predicted_volatility: float
    
    # 市场环境
    market_sentiment: str  # "bullish", "bearish", "neutral"
    volume_profile: str    # "high", "medium", "low"
    
    timestamp: datetime


class ProfitMaximizationService:
    """收益最大化服务"""
    
    def __init__(self):
        self.okx_service = OKXService()
        self.kronos_service = None
        
        # 策略配置
        self.min_risk_reward = 2.0      # 最低风险收益比
        self.max_position_risk = 0.02   # 单笔最大风险2%
        self.min_confidence = 0.7       # 最低置信度70%
        
        # 币圈特色配置
        self.crypto_multipliers = {
            'volatility_boost': 1.5,     # 波动率加成
            'breakout_multiplier': 1.8   # 突破倍数
        }
    
    async def scan_all_opportunities(self, symbols: List[str] = None) -> List[ProfitOpportunity]:
        """扫描所有收益机会"""
        if symbols is None:
            symbols = settings.monitored_symbols + settings.funding_rate_only_symbols
        
        logger.info(f"开始扫描 {len(symbols)} 个交易对的收益机会")
        
        opportunities = []
        
        # 并行扫描所有策略
        tasks = []
        for symbol in symbols:
            tasks.extend([
                self._scan_breakout_opportunities(symbol),
                self._scan_reversal_opportunities(symbol),
                self._scan_funding_rate_opportunities(symbol),
                self._scan_volatility_opportunities(symbol),
                self._scan_technical_pattern_opportunities(symbol)
            ])
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                opportunities.extend(result)
            elif isinstance(result, ProfitOpportunity):
                opportunities.append(result)
        
        # 按预期收益排序
        opportunities.sort(key=lambda x: x.expected_return, reverse=True)
        
        logger.info(f"发现 {len(opportunities)} 个收益机会")
        return opportunities[:20]  # 返回前20个最佳机会
    
    async def _scan_breakout_opportunities(self, symbol: str) -> List[ProfitOpportunity]:
        """扫描突破机会"""
        opportunities = []
        
        try:
            # 获取K线数据
            klines = await self.okx_service.get_kline_data(symbol, '1H', 100)
            if not klines:
                return opportunities
            
            current_price = klines[-1]['close']
            
            # 计算关键价位
            highs = [k['high'] for k in klines[-20:]]
            lows = [k['low'] for k in klines[-20:]]
            
            resistance = max(highs)
            support = min(lows)
            
            # 检查突破条件
            if current_price > resistance * 0.998:  # 接近突破阻力
                target_price = resistance * 1.05  # 5%目标
                stop_loss = resistance * 0.98     # 2%止损
                
                expected_return = (target_price - current_price) / current_price
                risk = (current_price - stop_loss) / current_price
                risk_reward = expected_return / risk if risk > 0 else 0
                
                if risk_reward >= self.min_risk_reward:
                    # 获取Kronos支持
                    kronos_support, kronos_conf = await self._get_kronos_support(symbol, 'bullish')
                    
                    opportunities.append(ProfitOpportunity(
                        symbol=symbol,
                        opportunity_type=OpportunityType.BREAKOUT,
                        entry_price=current_price,
                        target_price=target_price,
                        stop_loss=stop_loss,
                        expected_return=expected_return * 100,
                        risk_reward_ratio=risk_reward,
                        confidence=0.75 + (0.15 if kronos_support else 0),
                        time_horizon="1h",
                        reasoning=f"价格接近突破阻力位 {resistance:.4f}，目标 {target_price:.4f}",
                        urgency="within_1h",
                        kronos_support=kronos_support,
                        kronos_confidence=kronos_conf,
                        predicted_volatility=0.05,
                        market_sentiment="bullish",
                        volume_profile="high",
                        timestamp=datetime.now()
                    ))
            
            elif current_price < support * 1.002:  # 接近跌破支撑
                target_price = support * 0.95     # 5%目标
                stop_loss = support * 1.02        # 2%止损
                
                expected_return = (current_price - target_price) / current_price  # 做空收益
                risk = (stop_loss - current_price) / current_price
                risk_reward = expected_return / risk if risk > 0 else 0
                
                if risk_reward >= self.min_risk_reward:
                    kronos_support, kronos_conf = await self._get_kronos_support(symbol, 'bearish')
                    
                    opportunities.append(ProfitOpportunity(
                        symbol=symbol,
                        opportunity_type=OpportunityType.BREAKOUT,
                        entry_price=current_price,
                        target_price=target_price,
                        stop_loss=stop_loss,
                        expected_return=expected_return * 100,
                        risk_reward_ratio=risk_reward,
                        confidence=0.75 + (0.15 if kronos_support else 0),
                        time_horizon="1h",
                        reasoning=f"价格接近跌破支撑位 {support:.4f}，目标 {target_price:.4f}",
                        urgency="within_1h",
                        kronos_support=kronos_support,
                        kronos_confidence=kronos_conf,
                        predicted_volatility=0.05,
                        market_sentiment="bearish",
                        volume_profile="high",
                        timestamp=datetime.now()
                    ))
        
        except Exception as e:
            logger.warning(f"扫描 {symbol} 突破机会失败: {e}")
        
        return opportunities
    

    
    async def _scan_funding_rate_opportunities(self, symbol: str) -> List[ProfitOpportunity]:
        """扫描资金费率套利机会"""
        opportunities = []
        
        try:
            funding_data = await self.okx_service.get_funding_rate(symbol)
            if not funding_data:
                return opportunities
            
            funding_rate = funding_data['funding_rate']
            current_price = await self.okx_service.get_current_price(symbol)
            
            # 负费率机会（做多收费率）
            if funding_rate < -0.001:  # 费率小于-0.1%
                # 计算8小时收益
                hours_to_next = 8  # 假设8小时费率周期
                expected_funding_income = abs(funding_rate) * (hours_to_next / 8)
                
                # 考虑价格风险，设置较小的止损
                stop_loss = current_price * 0.995   # 0.5%止损
                target_price = current_price * 1.002  # 0.2%目标（主要靠费率收益）
                
                total_expected_return = (expected_funding_income + 0.002) * 100  # 费率收益+价格收益
                risk = 0.5  # 0.5%风险
                risk_reward = total_expected_return / risk
                
                if risk_reward >= 1.5:  # 费率套利风险收益比要求较低
                    opportunities.append(ProfitOpportunity(
                        symbol=symbol,
                        opportunity_type=OpportunityType.FUNDING_RATE,
                        entry_price=current_price,
                        target_price=target_price,
                        stop_loss=stop_loss,
                        expected_return=total_expected_return,
                        risk_reward_ratio=risk_reward,
                        confidence=0.85,  # 费率套利相对确定
                        time_horizon="8h",
                        reasoning=f"负费率套利：费率{funding_rate:.3%}，预期收益{expected_funding_income:.3%}",
                        urgency="within_1h",
                        kronos_support=False,  # 费率套利不依赖Kronos
                        kronos_confidence=0.0,
                        predicted_volatility=0.02,
                        market_sentiment="neutral",
                        volume_profile="medium",
                        timestamp=datetime.now()
                    ))
            
            # 高费率机会（做空收费率）
            elif funding_rate > 0.005:  # 费率大于0.5%
                hours_to_next = 8
                expected_funding_income = funding_rate * (hours_to_next / 8)
                
                stop_loss = current_price * 1.005    # 0.5%止损
                target_price = current_price * 0.998  # 0.2%目标
                
                total_expected_return = (expected_funding_income + 0.002) * 100
                risk = 0.5
                risk_reward = total_expected_return / risk
                
                if risk_reward >= 1.5:
                    opportunities.append(ProfitOpportunity(
                        symbol=symbol,
                        opportunity_type=OpportunityType.FUNDING_RATE,
                        entry_price=current_price,
                        target_price=target_price,
                        stop_loss=stop_loss,
                        expected_return=total_expected_return,
                        risk_reward_ratio=risk_reward,
                        confidence=0.85,
                        time_horizon="8h",
                        reasoning=f"高费率套利：费率{funding_rate:.3%}，预期收益{expected_funding_income:.3%}",
                        urgency="within_1h",
                        kronos_support=False,
                        kronos_confidence=0.0,
                        predicted_volatility=0.02,
                        market_sentiment="neutral",
                        volume_profile="medium",
                        timestamp=datetime.now()
                    ))
        
        except Exception as e:
            logger.warning(f"扫描 {symbol} 费率机会失败: {e}")
        
        return opportunities
    
    async def _scan_volatility_opportunities(self, symbol: str) -> List[ProfitOpportunity]:
        """扫描高波动率交易机会"""
        opportunities = []
        
        try:
            klines = await self.okx_service.get_kline_data(symbol, '15m', 96)  # 24小时数据
            if not klines:
                return opportunities
            
            # 计算波动率
            returns = []
            for i in range(1, len(klines)):
                ret = (klines[i]['close'] - klines[i-1]['close']) / klines[i-1]['close']
                returns.append(ret)
            
            volatility = np.std(returns) * np.sqrt(96)  # 年化波动率
            current_price = klines[-1]['close']
            
            # 高波动率机会
            if volatility > 0.8:  # 年化波动率80%以上
                # 计算布林带
                closes = [k['close'] for k in klines[-20:]]
                sma = sum(closes) / len(closes)
                std = np.std(closes)
                
                upper_band = sma + 2 * std
                lower_band = sma - 2 * std
                
                # 接近下轨做多
                if current_price < lower_band * 1.01:
                    target_price = sma  # 回归均值
                    stop_loss = lower_band * 0.98
                    
                    expected_return = (target_price - current_price) / current_price * 100
                    risk = (current_price - stop_loss) / current_price * 100
                    risk_reward = expected_return / risk if risk > 0 else 0
                    
                    if risk_reward >= 2.0:
                        kronos_support, kronos_conf = await self._get_kronos_support(symbol, 'bullish')
                        
                        opportunities.append(ProfitOpportunity(
                            symbol=symbol,
                            opportunity_type=OpportunityType.VOLATILITY,
                            entry_price=current_price,
                            target_price=target_price,
                            stop_loss=stop_loss,
                            expected_return=expected_return,
                            risk_reward_ratio=risk_reward,
                            confidence=0.75 + (0.1 if kronos_support else 0),
                            time_horizon="4h",
                            reasoning=f"高波动率{volatility:.1%}，价格接近下轨{lower_band:.4f}，均值回归机会",
                            urgency="within_1h",
                            kronos_support=kronos_support,
                            kronos_confidence=kronos_conf,
                            predicted_volatility=volatility,
                            market_sentiment="neutral",
                            volume_profile="high",
                            timestamp=datetime.now()
                        ))
                
                # 接近上轨做空
                elif current_price > upper_band * 0.99:
                    target_price = sma
                    stop_loss = upper_band * 1.02
                    
                    expected_return = (current_price - target_price) / current_price * 100
                    risk = (stop_loss - current_price) / current_price * 100
                    risk_reward = expected_return / risk if risk > 0 else 0
                    
                    if risk_reward >= 2.0:
                        kronos_support, kronos_conf = await self._get_kronos_support(symbol, 'bearish')
                        
                        opportunities.append(ProfitOpportunity(
                            symbol=symbol,
                            opportunity_type=OpportunityType.VOLATILITY,
                            entry_price=current_price,
                            target_price=target_price,
                            stop_loss=stop_loss,
                            expected_return=expected_return,
                            risk_reward_ratio=risk_reward,
                            confidence=0.75 + (0.1 if kronos_support else 0),
                            time_horizon="4h",
                            reasoning=f"高波动率{volatility:.1%}，价格接近上轨{upper_band:.4f}，均值回归机会",
                            urgency="within_1h",
                            kronos_support=kronos_support,
                            kronos_confidence=kronos_conf,
                            predicted_volatility=volatility,
                            market_sentiment="neutral",
                            volume_profile="high",
                            timestamp=datetime.now()
                        ))
        
        except Exception as e:
            logger.warning(f"扫描 {symbol} 波动率机会失败: {e}")
        
        return opportunities
    
    async def _scan_reversal_opportunities(self, symbol: str) -> List[ProfitOpportunity]:
        """扫描反转机会"""
        # 简化实现，返回空列表
        return []
    
    async def _scan_technical_pattern_opportunities(self, symbol: str) -> List[ProfitOpportunity]:
        """扫描技术形态机会"""
        # 简化实现，返回空列表
        return []
    
    async def _get_kronos_support(self, symbol: str, direction: str) -> Tuple[bool, float]:
        """获取Kronos预测支持"""
        try:
            if self.kronos_service is None:
                self.kronos_service = await get_kronos_service()
            
            if self.kronos_service:
                prediction = await self.kronos_service.get_cached_prediction(symbol)
                if prediction:
                    predicted_direction = 'bullish' if prediction.price_change_pct > 0 else 'bearish'
                    is_supported = (predicted_direction == direction and prediction.confidence > 0.6)
                    return is_supported, prediction.confidence
        
        except Exception as e:
            logger.debug(f"获取Kronos支持失败 {symbol}: {e}")
        
        return False, 0.0


# 全局服务实例
_profit_service = None

async def get_profit_maximization_service() -> ProfitMaximizationService:
    """获取收益最大化服务实例"""
    global _profit_service
    if _profit_service is None:
        _profit_service = ProfitMaximizationService()
    return _profit_service