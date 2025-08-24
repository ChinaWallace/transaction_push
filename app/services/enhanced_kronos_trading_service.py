# -*- coding: utf-8 -*-
"""
增强的交易决策服务 - 集成Kronos预测
结合传统技术分析和Kronos AI预测的综合交易决策系统
"""

import asyncio
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.kronos_prediction_service import get_kronos_service, KronosPrediction
from app.services.trend_analysis_service import TrendAnalysisService
from app.services.okx_service import OKXService
from app.schemas.kronos import TradingSignalWithKronos


@dataclass
class EnhancedTradingSignal:
    """增强的交易信号数据类"""
    symbol: str
    timestamp: datetime
    
    # 传统技术分析
    technical_signal: str
    technical_confidence: float
    supertrend_signals: Dict[str, str]  # 各周期SuperTrend信号
    
    # Kronos预测
    kronos_signal: Optional[str]
    kronos_confidence: Optional[float]
    kronos_price_target: Optional[float]
    kronos_trend_direction: Optional[str]
    
    # 综合决策
    final_signal: str
    final_confidence: float
    signal_strength: str
    
    # 风险管理
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_size: float
    risk_level: str
    
    # 决策依据
    reasoning: str
    confluence_score: float  # 信号一致性评分


class EnhancedKronosTradingService:
    """增强的Kronos交易决策服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.trend_service = TrendAnalysisService()
        self.okx_service = OKXService()
        
    async def get_enhanced_trading_signal(
        self,
        symbol: str,
        force_update: bool = False
    ) -> Optional[EnhancedTradingSignal]:
        """获取增强的交易信号"""
        try:
            # 并行获取技术分析和Kronos预测
            technical_task = self._get_technical_analysis(symbol)
            kronos_task = self._get_kronos_prediction(symbol, force_update)
            
            technical_result, kronos_prediction = await asyncio.gather(
                technical_task, kronos_task, return_exceptions=True
            )
            
            # 处理异常结果
            if isinstance(technical_result, Exception):
                self.logger.error(f"获取{symbol}技术分析失败: {technical_result}")
                technical_result = None
                
            if isinstance(kronos_prediction, Exception):
                self.logger.error(f"获取{symbol}Kronos预测失败: {kronos_prediction}")
                kronos_prediction = None
            
            # 如果两个都失败了，返回None
            if technical_result is None and kronos_prediction is None:
                self.logger.warning(f"无法获取{symbol}的任何分析结果")
                return None
            
            # 生成综合信号
            enhanced_signal = await self._generate_enhanced_signal(
                symbol, technical_result, kronos_prediction
            )
            
            return enhanced_signal
            
        except Exception as e:
            self.logger.error(f"生成{symbol}增强交易信号失败: {e}")
            return None
    
    async def _get_technical_analysis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取技术分析结果"""
        try:
            # 获取多周期SuperTrend分析
            analysis_result = await self.trend_service.analyze_symbol_trend(symbol)
            
            if analysis_result is None:
                return None
            
            return {
                'signal': analysis_result.get('signal_type', 'hold'),
                'confidence': analysis_result.get('confidence', 0.5),
                'supertrend_signals': analysis_result.get('supertrend_signals', {}),
                'signal_combination': analysis_result.get('signal_combination', ''),
                'strategy_advice': analysis_result.get('strategy_advice', ''),
                'current_price': analysis_result.get('current_price', 0.0)
            }
            
        except Exception as e:
            self.logger.error(f"获取{symbol}技术分析失败: {e}")
            return None
    
    async def _get_kronos_prediction(
        self,
        symbol: str,
        force_update: bool = False
    ) -> Optional[KronosPrediction]:
        """获取Kronos预测结果"""
        try:
            kronos_service = await get_kronos_service()
            
            if kronos_service.predictor is None:
                self.logger.warning("Kronos预测器未初始化")
                return None
            
            # 获取历史数据
            historical_data = await self.okx_service.get_kline_data(
                symbol=symbol,
                timeframe='1h',
                limit=250  # 获取足够的历史数据
            )
            
            if historical_data is None or len(historical_data) < 200:
                self.logger.warning(f"{symbol}历史数据不足")
                return None
            
            # 生成预测
            prediction = await kronos_service.get_prediction(
                symbol=symbol,
                historical_data=historical_data,
                force_update=force_update
            )
            
            return prediction
            
        except Exception as e:
            self.logger.error(f"获取{symbol}Kronos预测失败: {e}")
            return None
    
    async def _generate_enhanced_signal(
        self,
        symbol: str,
        technical_result: Optional[Dict[str, Any]],
        kronos_prediction: Optional[KronosPrediction]
    ) -> EnhancedTradingSignal:
        """生成综合增强信号"""
        try:
            current_time = datetime.now()
            
            # 提取技术分析信息
            technical_signal = 'hold'
            technical_confidence = 0.5
            supertrend_signals = {}
            current_price = 0.0
            
            if technical_result:
                technical_signal = technical_result.get('signal', 'hold')
                technical_confidence = technical_result.get('confidence', 0.5)
                supertrend_signals = technical_result.get('supertrend_signals', {})
                current_price = technical_result.get('current_price', 0.0)
            
            # 提取Kronos预测信息
            kronos_signal = None
            kronos_confidence = None
            kronos_price_target = None
            kronos_trend_direction = None
            
            if kronos_prediction:
                kronos_signal = kronos_prediction.signal
                kronos_confidence = kronos_prediction.confidence
                kronos_trend_direction = kronos_prediction.trend_direction
                
                # 计算价格目标
                if current_price > 0:
                    predicted_change = kronos_prediction.price_change_pct
                    kronos_price_target = current_price * (1 + predicted_change)
            
            # 计算信号一致性评分
            confluence_score = self._calculate_confluence_score(
                technical_signal, kronos_signal, technical_confidence, kronos_confidence
            )
            
            # 生成最终信号
            final_signal, final_confidence = self._generate_final_signal(
                technical_signal, technical_confidence,
                kronos_signal, kronos_confidence,
                confluence_score
            )
            
            # 确定信号强度
            signal_strength = self._determine_signal_strength(final_confidence, confluence_score)
            
            # 计算风险管理参数
            risk_params = self._calculate_risk_management(
                current_price, final_signal, final_confidence,
                kronos_prediction.volatility if kronos_prediction else 0.1
            )
            
            # 生成决策依据
            reasoning = self._generate_reasoning(
                technical_result, kronos_prediction, confluence_score, final_signal
            )
            
            # 创建增强信号对象
            enhanced_signal = EnhancedTradingSignal(
                symbol=symbol,
                timestamp=current_time,
                technical_signal=technical_signal,
                technical_confidence=technical_confidence,
                supertrend_signals=supertrend_signals,
                kronos_signal=kronos_signal,
                kronos_confidence=kronos_confidence,
                kronos_price_target=kronos_price_target,
                kronos_trend_direction=kronos_trend_direction,
                final_signal=final_signal,
                final_confidence=final_confidence,
                signal_strength=signal_strength,
                stop_loss=risk_params['stop_loss'],
                take_profit=risk_params['take_profit'],
                position_size=risk_params['position_size'],
                risk_level=risk_params['risk_level'],
                reasoning=reasoning,
                confluence_score=confluence_score
            )
            
            return enhanced_signal
            
        except Exception as e:
            self.logger.error(f"生成{symbol}综合信号失败: {e}")
            # 返回默认的保守信号
            return EnhancedTradingSignal(
                symbol=symbol,
                timestamp=datetime.now(),
                technical_signal='hold',
                technical_confidence=0.5,
                supertrend_signals={},
                kronos_signal=None,
                kronos_confidence=None,
                kronos_price_target=None,
                kronos_trend_direction=None,
                final_signal='hold',
                final_confidence=0.5,
                signal_strength='弱',
                stop_loss=None,
                take_profit=None,
                position_size=0.1,
                risk_level='高',
                reasoning='分析失败，建议观望',
                confluence_score=0.0
            )
    
    def _calculate_confluence_score(
        self,
        technical_signal: str,
        kronos_signal: Optional[str],
        technical_confidence: float,
        kronos_confidence: Optional[float]
    ) -> float:
        """计算信号一致性评分"""
        if kronos_signal is None:
            return technical_confidence * 0.5  # 只有技术分析时降低评分
        
        # 信号方向一致性
        signal_alignment = 0.0
        
        # 将信号转换为数值进行比较
        signal_values = {
            'strong_sell': -2, 'sell': -1, 'hold': 0, 'buy': 1, 'strong_buy': 2
        }
        
        tech_value = signal_values.get(technical_signal, 0)
        kronos_value = signal_values.get(kronos_signal, 0)
        
        # 计算信号一致性
        if tech_value * kronos_value > 0:  # 同向信号
            signal_alignment = 1.0
        elif tech_value == 0 or kronos_value == 0:  # 一个是hold
            signal_alignment = 0.5
        else:  # 反向信号
            signal_alignment = 0.0
        
        # 综合置信度
        avg_confidence = (technical_confidence + (kronos_confidence or 0.5)) / 2
        
        # 最终一致性评分
        confluence_score = signal_alignment * avg_confidence
        
        return min(1.0, max(0.0, confluence_score))
    
    def _generate_final_signal(
        self,
        technical_signal: str,
        technical_confidence: float,
        kronos_signal: Optional[str],
        kronos_confidence: Optional[float],
        confluence_score: float
    ) -> Tuple[str, float]:
        """生成最终交易信号"""
        if kronos_signal is None:
            # 只有技术分析时，降低置信度
            return technical_signal, technical_confidence * 0.8
        
        # 信号权重配置
        technical_weight = 0.4  # 技术分析权重
        kronos_weight = 0.6     # Kronos预测权重
        
        # 如果一致性评分很高，增强信号
        if confluence_score > 0.8:
            # 高一致性时，选择更强的信号
            signal_strength = {
                'strong_sell': -2, 'sell': -1, 'hold': 0, 'buy': 1, 'strong_buy': 2
            }
            
            tech_strength = signal_strength.get(technical_signal, 0)
            kronos_strength = signal_strength.get(kronos_signal, 0)
            
            # 加权平均
            final_strength = (tech_strength * technical_weight + 
                            kronos_strength * kronos_weight)
            
            # 转换回信号
            if final_strength >= 1.5:
                final_signal = 'strong_buy'
            elif final_strength >= 0.5:
                final_signal = 'buy'
            elif final_strength <= -1.5:
                final_signal = 'strong_sell'
            elif final_strength <= -0.5:
                final_signal = 'sell'
            else:
                final_signal = 'hold'
            
            # 高一致性时提升置信度
            final_confidence = min(0.95, confluence_score * 1.2)
            
        else:
            # 低一致性时保守处理
            if confluence_score < 0.3:
                final_signal = 'hold'
                final_confidence = 0.5
            else:
                # 选择置信度更高的信号
                if technical_confidence > (kronos_confidence or 0):
                    final_signal = technical_signal
                    final_confidence = technical_confidence * 0.9
                else:
                    final_signal = kronos_signal
                    final_confidence = (kronos_confidence or 0.5) * 0.9
        
        return final_signal, final_confidence
    
    def _determine_signal_strength(self, confidence: float, confluence_score: float) -> str:
        """确定信号强度"""
        combined_score = (confidence + confluence_score) / 2
        
        if combined_score >= 0.8:
            return '强烈'
        elif combined_score >= 0.6:
            return '中等'
        elif combined_score >= 0.4:
            return '较弱'
        else:
            return '弱'
    
    def _calculate_risk_management(
        self,
        current_price: float,
        signal: str,
        confidence: float,
        volatility: float
    ) -> Dict[str, Any]:
        """计算风险管理参数"""
        if current_price <= 0:
            return {
                'stop_loss': None,
                'take_profit': None,
                'position_size': 0.1,
                'risk_level': '高'
            }
        
        # 基于波动率计算止损止盈
        volatility = max(0.02, min(0.2, volatility))  # 限制在2%-20%之间
        
        # 止损距离：1.5倍波动率
        stop_loss_pct = volatility * 1.5
        
        # 止盈距离：基于信号强度调整
        if signal in ['strong_buy', 'strong_sell']:
            take_profit_pct = volatility * 3.0
        elif signal in ['buy', 'sell']:
            take_profit_pct = volatility * 2.0
        else:
            take_profit_pct = volatility * 1.0
        
        # 计算具体价格
        if signal in ['buy', 'strong_buy']:
            stop_loss = current_price * (1 - stop_loss_pct)
            take_profit = current_price * (1 + take_profit_pct)
        elif signal in ['sell', 'strong_sell']:
            stop_loss = current_price * (1 + stop_loss_pct)
            take_profit = current_price * (1 - take_profit_pct)
        else:
            stop_loss = None
            take_profit = None
        
        # 仓位大小：基于置信度和波动率
        base_position = 0.2  # 基础仓位20%
        confidence_multiplier = confidence
        volatility_multiplier = max(0.5, 1 - volatility)  # 高波动率降低仓位
        
        position_size = base_position * confidence_multiplier * volatility_multiplier
        position_size = max(0.05, min(0.5, position_size))  # 限制在5%-50%之间
        
        # 风险等级
        if volatility > 0.15 or confidence < 0.5:
            risk_level = '高'
        elif volatility > 0.08 or confidence < 0.7:
            risk_level = '中等'
        else:
            risk_level = '低'
        
        return {
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'position_size': position_size,
            'risk_level': risk_level
        }
    
    def _generate_reasoning(
        self,
        technical_result: Optional[Dict[str, Any]],
        kronos_prediction: Optional[KronosPrediction],
        confluence_score: float,
        final_signal: str
    ) -> str:
        """生成决策依据说明"""
        reasoning_parts = []
        
        # 技术分析部分
        if technical_result:
            tech_signal = technical_result.get('signal', 'hold')
            strategy_advice = technical_result.get('strategy_advice', '')
            reasoning_parts.append(f"技术分析显示{tech_signal}信号")
            if strategy_advice:
                reasoning_parts.append(strategy_advice)
        
        # Kronos预测部分
        if kronos_prediction:
            price_change = kronos_prediction.price_change_pct * 100
            trend_direction = kronos_prediction.trend_direction
            reasoning_parts.append(
                f"Kronos AI预测24小时内价格变化{price_change:.1f}%，趋势{trend_direction}"
            )
        
        # 一致性评分
        if confluence_score > 0.8:
            reasoning_parts.append("多重信号高度一致，可信度较高")
        elif confluence_score > 0.5:
            reasoning_parts.append("信号存在一定一致性")
        else:
            reasoning_parts.append("信号存在分歧，建议谨慎操作")
        
        # 最终建议
        signal_advice = {
            'strong_buy': '强烈建议买入',
            'buy': '建议买入',
            'hold': '建议观望',
            'sell': '建议卖出',
            'strong_sell': '强烈建议卖出'
        }
        
        reasoning_parts.append(signal_advice.get(final_signal, '建议观望'))
        
        return '，'.join(reasoning_parts)
    
    async def get_batch_enhanced_signals(
        self,
        symbols: List[str],
        force_update: bool = False
    ) -> Dict[str, Optional[EnhancedTradingSignal]]:
        """批量获取增强交易信号"""
        results = {}
        
        # 并发处理多个信号
        tasks = []
        for symbol in symbols:
            task = self.get_enhanced_trading_signal(symbol, force_update)
            tasks.append((symbol, task))
        
        # 等待所有任务完成
        for symbol, task in tasks:
            try:
                signal = await task
                results[symbol] = signal
            except Exception as e:
                self.logger.error(f"获取{symbol}增强信号失败: {e}")
                results[symbol] = None
        
        return results
    
    def convert_to_api_format(self, signal: EnhancedTradingSignal) -> TradingSignalWithKronos:
        """转换为API响应格式"""
        return TradingSignalWithKronos(
            symbol=signal.symbol,
            timestamp=signal.timestamp,
            technical_signal=signal.technical_signal,
            technical_confidence=signal.technical_confidence,
            kronos_signal=signal.kronos_signal,
            kronos_confidence=signal.kronos_confidence,
            kronos_price_target=signal.kronos_price_target,
            final_signal=signal.final_signal,
            final_confidence=signal.final_confidence,
            signal_strength=signal.signal_strength,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            position_size=signal.position_size,
            reasoning=signal.reasoning,
            risk_level=signal.risk_level
        )


# 全局服务实例
enhanced_kronos_trading_service = EnhancedKronosTradingService()


async def get_enhanced_kronos_trading_service() -> EnhancedKronosTradingService:
    """获取增强Kronos交易服务实例"""
    return enhanced_kronos_trading_service