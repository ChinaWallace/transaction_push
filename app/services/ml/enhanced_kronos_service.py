# -*- coding: utf-8 -*-
"""
增强版Kronos集成决策服务
Enhanced Kronos Integrated Decision Service with Volume-Price Analysis
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.ml.kronos_integrated_decision_service import (
    get_kronos_integrated_service, 
    KronosIntegratedDecisionService,
    KronosEnhancedDecision
)
from app.services.exchanges.service_manager import get_exchange_service
from app.services.analysis.detailed_technical_analysis_service import get_detailed_technical_analysis_service
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)


class VolumeSignal(Enum):
    """成交量信号枚举"""
    VOLUME_BREAKOUT = "成交量突破"
    VOLUME_DIVERGENCE = "量价背离"
    VOLUME_CONFIRMATION = "量价确认"
    VOLUME_EXHAUSTION = "成交量衰竭"
    VOLUME_ACCUMULATION = "成交量堆积"


@dataclass
class VolumeAnalysis:
    """成交量分析结果"""
    symbol: str
    current_volume: float
    avg_volume_20: float
    volume_ratio: float
    obv_trend: str
    volume_signal: VolumeSignal
    volume_strength: float
    reasoning: str


@dataclass
class EnhancedKronosDecision:
    """增强版Kronos决策结果"""
    symbol: str
    timestamp: datetime
    
    # 原始Kronos结果
    original_kronos_result: Optional[Any]
    kronos_confidence: float
    kronos_action: str
    
    # 量价分析增强
    volume_analysis: VolumeAnalysis
    volume_price_alignment: float  # 量价一致性评分 0-1
    
    # 最终增强决策
    enhanced_action: str
    enhanced_confidence: float
    confidence_adjustment: float  # 置信度调整幅度
    
    # 详细分析
    technical_factors: Dict[str, Any]
    risk_factors: List[str]
    reasoning: str


class EnhancedKronosService:
    """增强版Kronos服务 - 集成量价分析"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.initialized = False
        
        # 依赖服务
        self.kronos_service: Optional[KronosIntegratedDecisionService] = None
        self.exchange_service = None
        self.technical_service = None
        
        # 量价分析参数
        self.volume_lookback_periods = 20
        self.volume_spike_threshold = 2.0  # 成交量突破阈值
        self.obv_trend_periods = 10
        
    async def initialize(self) -> None:
        """初始化服务"""
        if self.initialized:
            return
            
        try:
            # 初始化依赖服务
            self.kronos_service = await get_kronos_integrated_service()
            self.exchange_service = await get_exchange_service()
            self.technical_service = await get_detailed_technical_analysis_service()
            
            self.initialized = True
            self.logger.info("✅ 增强版Kronos服务初始化完成")
            
        except Exception as e:
            self.logger.error(f"❌ 增强版Kronos服务初始化失败: {e}")
            raise
    
    async def get_enhanced_kronos_decision(
        self, 
        symbol: str, 
        force_update: bool = False
    ) -> Optional[EnhancedKronosDecision]:
        """获取增强版Kronos决策"""
        try:
            if not self.initialized:
                await self.initialize()
            
            # 1. 获取原始Kronos决策
            original_decision = await self.kronos_service.get_kronos_enhanced_decision(
                symbol=symbol, 
                force_update=force_update
            )
            
            if not original_decision:
                self.logger.warning(f"无法获取{symbol}的Kronos决策")
                return None
            
            # 2. 进行量价分析
            volume_analysis = await self._analyze_volume_price_relationship(symbol)
            
            # 3. 计算量价一致性
            volume_price_alignment = await self._calculate_volume_price_alignment(
                original_decision, volume_analysis
            )
            
            # 4. 生成增强决策
            enhanced_decision = await self._generate_enhanced_decision(
                symbol, original_decision, volume_analysis, volume_price_alignment
            )
            
            return enhanced_decision
            
        except Exception as e:
            self.logger.error(f"获取{symbol}增强版Kronos决策失败: {e}")
            return None
    
    async def _analyze_volume_price_relationship(self, symbol: str) -> VolumeAnalysis:
        """分析量价关系"""
        try:
            # 获取历史K线数据
            klines_data = await self.exchange_service.get_klines(
                symbol=symbol,
                interval='1h',
                limit=50
            )
            
            if not klines_data:
                raise TradingToolError(f"无法获取{symbol}的K线数据")
            
            # 提取价格和成交量数据
            closes = [float(k[4]) for k in klines_data]  # 收盘价
            volumes = [float(k[5]) for k in klines_data]  # 成交量
            
            # 计算成交量指标
            current_volume = volumes[-1]
            avg_volume_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)
            volume_ratio = current_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0
            
            # 计算OBV趋势
            obv_values = self._calculate_obv(closes, volumes)
            obv_trend = self._determine_obv_trend(obv_values)
            
            # 判断成交量信号
            volume_signal, volume_strength, reasoning = self._determine_volume_signal(
                closes, volumes, volume_ratio, obv_trend
            )
            
            return VolumeAnalysis(
                symbol=symbol,
                current_volume=current_volume,
                avg_volume_20=avg_volume_20,
                volume_ratio=volume_ratio,
                obv_trend=obv_trend,
                volume_signal=volume_signal,
                volume_strength=volume_strength,
                reasoning=reasoning
            )
            
        except Exception as e:
            self.logger.error(f"分析{symbol}量价关系失败: {e}")
            # 返回默认分析结果
            return VolumeAnalysis(
                symbol=symbol,
                current_volume=0,
                avg_volume_20=0,
                volume_ratio=1.0,
                obv_trend="neutral",
                volume_signal=VolumeSignal.VOLUME_CONFIRMATION,
                volume_strength=0.5,
                reasoning="量价分析数据不足"
            )
    
    def _calculate_obv(self, closes: List[float], volumes: List[float]) -> List[float]:
        """计算OBV指标"""
        if len(closes) != len(volumes) or len(closes) < 2:
            return [0.0]
        
        obv = [volumes[0]]  # 第一个值
        
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]:
                # 价格上涨，OBV加上成交量
                obv.append(obv[-1] + volumes[i])
            elif closes[i] < closes[i-1]:
                # 价格下跌，OBV减去成交量
                obv.append(obv[-1] - volumes[i])
            else:
                # 价格不变，OBV不变
                obv.append(obv[-1])
        
        return obv
    
    def _determine_obv_trend(self, obv_values: List[float]) -> str:
        """判断OBV趋势"""
        if len(obv_values) < self.obv_trend_periods:
            return "neutral"
        
        recent_obv = obv_values[-self.obv_trend_periods:]
        
        # 计算趋势斜率
        x = np.arange(len(recent_obv))
        slope = np.polyfit(x, recent_obv, 1)[0]
        
        # 判断趋势
        if slope > 0:
            return "bullish"  # 上升趋势
        elif slope < 0:
            return "bearish"  # 下降趋势
        else:
            return "neutral"  # 中性
    
    def _determine_volume_signal(
        self, 
        closes: List[float], 
        volumes: List[float], 
        volume_ratio: float,
        obv_trend: str
    ) -> Tuple[VolumeSignal, float, str]:
        """判断成交量信号"""
        
        if len(closes) < 5 or len(volumes) < 5:
            return VolumeSignal.VOLUME_CONFIRMATION, 0.5, "数据不足"
        
        # 价格趋势
        price_change = (closes[-1] - closes[-5]) / closes[-5]
        
        # 成交量突破
        if volume_ratio >= self.volume_spike_threshold:
            if price_change > 0.02:  # 价格上涨超过2%
                return VolumeSignal.VOLUME_BREAKOUT, 0.8, f"成交量放大{volume_ratio:.1f}倍，价格突破"
            elif price_change < -0.02:  # 价格下跌超过2%
                return VolumeSignal.VOLUME_EXHAUSTION, 0.7, f"成交量放大{volume_ratio:.1f}倍，但价格下跌，可能见底"
        
        # 量价背离
        if obv_trend == "bullish" and price_change < -0.01:
            return VolumeSignal.VOLUME_DIVERGENCE, 0.6, "OBV上升但价格下跌，量价背离"
        elif obv_trend == "bearish" and price_change > 0.01:
            return VolumeSignal.VOLUME_DIVERGENCE, 0.6, "OBV下降但价格上涨，量价背离"
        
        # 量价确认
        if (obv_trend == "bullish" and price_change > 0) or (obv_trend == "bearish" and price_change < 0):
            return VolumeSignal.VOLUME_CONFIRMATION, 0.7, "量价趋势一致，相互确认"
        
        # 成交量堆积
        if volume_ratio < 0.5:
            return VolumeSignal.VOLUME_ACCUMULATION, 0.4, f"成交量萎缩至{volume_ratio:.1f}倍，可能在堆积"
        
        # 默认确认信号
        return VolumeSignal.VOLUME_CONFIRMATION, 0.5, "成交量正常"
    
    async def _calculate_volume_price_alignment(
        self, 
        kronos_decision: Any, 
        volume_analysis: VolumeAnalysis
    ) -> float:
        """计算量价一致性评分"""
        try:
            kronos_action = getattr(kronos_decision, 'final_action', '持有')
            volume_signal = volume_analysis.volume_signal
            obv_trend = volume_analysis.obv_trend
            
            alignment_score = 0.5  # 基础分数
            
            # Kronos看多的情况
            if "买入" in kronos_action:
                if volume_signal == VolumeSignal.VOLUME_BREAKOUT:
                    alignment_score += 0.3  # 成交量突破支持买入
                elif volume_signal == VolumeSignal.VOLUME_CONFIRMATION and obv_trend == "bullish":
                    alignment_score += 0.2  # 量价确认支持买入
                elif volume_signal == VolumeSignal.VOLUME_DIVERGENCE:
                    alignment_score -= 0.2  # 量价背离不支持买入
                elif volume_signal == VolumeSignal.VOLUME_EXHAUSTION:
                    alignment_score += 0.1  # 成交量衰竭可能是买入机会
            
            # Kronos看空的情况
            elif "卖出" in kronos_action:
                if volume_signal == VolumeSignal.VOLUME_BREAKOUT and obv_trend == "bearish":
                    alignment_score += 0.3  # 成交量突破支持卖出
                elif volume_signal == VolumeSignal.VOLUME_CONFIRMATION and obv_trend == "bearish":
                    alignment_score += 0.2  # 量价确认支持卖出
                elif volume_signal == VolumeSignal.VOLUME_DIVERGENCE:
                    alignment_score -= 0.2  # 量价背离不支持卖出
            
            # 限制在0-1范围内
            return max(0.0, min(1.0, alignment_score))
            
        except Exception as e:
            self.logger.error(f"计算量价一致性失败: {e}")
            return 0.5
    
    async def _generate_enhanced_decision(
        self,
        symbol: str,
        original_decision: Any,
        volume_analysis: VolumeAnalysis,
        volume_price_alignment: float
    ) -> EnhancedKronosDecision:
        """生成增强决策"""
        try:
            # 提取原始Kronos结果
            original_action = getattr(original_decision, 'final_action', '持有')
            original_confidence = getattr(original_decision, 'final_confidence', 0.5)
            
            # 计算置信度调整
            confidence_adjustment = self._calculate_confidence_adjustment(
                volume_analysis, volume_price_alignment
            )
            
            # 生成增强决策
            enhanced_action, enhanced_confidence = self._enhance_decision(
                original_action, original_confidence, confidence_adjustment, volume_analysis
            )
            
            # 构建技术因素
            technical_factors = {
                'volume_ratio': volume_analysis.volume_ratio,
                'obv_trend': volume_analysis.obv_trend,
                'volume_signal': volume_analysis.volume_signal.value,
                'volume_price_alignment': volume_price_alignment,
                'original_confidence': original_confidence,
                'confidence_adjustment': confidence_adjustment
            }
            
            # 识别风险因素
            risk_factors = self._identify_risk_factors(volume_analysis, volume_price_alignment)
            
            # 构建推理说明
            reasoning = self._build_enhanced_reasoning(
                original_action, enhanced_action, volume_analysis, confidence_adjustment
            )
            
            return EnhancedKronosDecision(
                symbol=symbol,
                timestamp=datetime.now(),
                original_kronos_result=original_decision,
                kronos_confidence=original_confidence,
                kronos_action=original_action,
                volume_analysis=volume_analysis,
                volume_price_alignment=volume_price_alignment,
                enhanced_action=enhanced_action,
                enhanced_confidence=enhanced_confidence,
                confidence_adjustment=confidence_adjustment,
                technical_factors=technical_factors,
                risk_factors=risk_factors,
                reasoning=reasoning
            )
            
        except Exception as e:
            self.logger.error(f"生成{symbol}增强决策失败: {e}")
            raise
    
    def _calculate_confidence_adjustment(
        self, 
        volume_analysis: VolumeAnalysis, 
        volume_price_alignment: float
    ) -> float:
        """计算置信度调整幅度"""
        adjustment = 0.0
        
        # 基于量价一致性调整
        if volume_price_alignment > 0.7:
            adjustment += 0.15  # 高一致性提升置信度
        elif volume_price_alignment < 0.3:
            adjustment -= 0.15  # 低一致性降低置信度
        
        # 基于成交量信号调整
        if volume_analysis.volume_signal == VolumeSignal.VOLUME_BREAKOUT:
            adjustment += 0.1 * volume_analysis.volume_strength
        elif volume_analysis.volume_signal == VolumeSignal.VOLUME_DIVERGENCE:
            adjustment -= 0.1 * volume_analysis.volume_strength
        
        # 基于成交量比率调整
        if volume_analysis.volume_ratio > 2.0:
            adjustment += 0.05  # 成交量大幅放大
        elif volume_analysis.volume_ratio < 0.5:
            adjustment -= 0.05  # 成交量萎缩
        
        return adjustment
    
    def _enhance_decision(
        self,
        original_action: str,
        original_confidence: float,
        confidence_adjustment: float,
        volume_analysis: VolumeAnalysis
    ) -> Tuple[str, float]:
        """增强决策"""
        
        # 调整置信度
        enhanced_confidence = max(0.1, min(0.95, original_confidence + confidence_adjustment))
        
        # 基于量价分析调整动作强度
        enhanced_action = original_action
        
        # 如果量价高度一致且成交量突破，可能升级动作
        if (volume_analysis.volume_signal == VolumeSignal.VOLUME_BREAKOUT and 
            volume_analysis.volume_strength > 0.7):
            
            if original_action == "买入" and enhanced_confidence > 0.8:
                enhanced_action = "强烈买入"
            elif original_action == "卖出" and enhanced_confidence > 0.8:
                enhanced_action = "强烈卖出"
        
        # 如果量价背离严重，可能降级动作
        elif (volume_analysis.volume_signal == VolumeSignal.VOLUME_DIVERGENCE and 
              volume_analysis.volume_strength > 0.6):
            
            if "强烈" in original_action:
                enhanced_action = original_action.replace("强烈", "").strip()
            elif original_action in ["买入", "卖出"]:
                enhanced_action = "谨慎观望"
        
        return enhanced_action, enhanced_confidence
    
    def _identify_risk_factors(
        self, 
        volume_analysis: VolumeAnalysis, 
        volume_price_alignment: float
    ) -> List[str]:
        """识别风险因素"""
        risk_factors = []
        
        if volume_price_alignment < 0.3:
            risk_factors.append("量价背离严重，信号可靠性降低")
        
        if volume_analysis.volume_ratio < 0.3:
            risk_factors.append("成交量极度萎缩，市场参与度不足")
        
        if volume_analysis.volume_signal == VolumeSignal.VOLUME_DIVERGENCE:
            risk_factors.append("出现量价背离，需要谨慎对待")
        
        if volume_analysis.volume_ratio > 5.0:
            risk_factors.append("成交量异常放大，可能存在异常波动")
        
        return risk_factors
    
    def _build_enhanced_reasoning(
        self,
        original_action: str,
        enhanced_action: str,
        volume_analysis: VolumeAnalysis,
        confidence_adjustment: float
    ) -> str:
        """构建增强推理说明"""
        reasoning_parts = []
        
        # 原始Kronos决策
        reasoning_parts.append(f"Kronos AI建议: {original_action}")
        
        # 量价分析结果
        reasoning_parts.append(f"成交量分析: {volume_analysis.reasoning}")
        
        # OBV趋势
        obv_desc = {"bullish": "上升", "bearish": "下降", "neutral": "中性"}
        reasoning_parts.append(f"OBV趋势: {obv_desc.get(volume_analysis.obv_trend, '未知')}")
        
        # 置信度调整说明
        if abs(confidence_adjustment) > 0.05:
            adj_desc = "提升" if confidence_adjustment > 0 else "降低"
            reasoning_parts.append(f"基于量价分析{adj_desc}置信度{abs(confidence_adjustment):.1%}")
        
        # 最终决策变化
        if enhanced_action != original_action:
            reasoning_parts.append(f"综合量价因素调整为: {enhanced_action}")
        
        return " | ".join(reasoning_parts)


# 全局服务实例
_enhanced_kronos_service: Optional[EnhancedKronosService] = None

async def get_enhanced_kronos_service() -> EnhancedKronosService:
    """获取增强版Kronos服务实例"""
    global _enhanced_kronos_service
    if _enhanced_kronos_service is None:
        _enhanced_kronos_service = EnhancedKronosService()
        await _enhanced_kronos_service.initialize()
    return _enhanced_kronos_service