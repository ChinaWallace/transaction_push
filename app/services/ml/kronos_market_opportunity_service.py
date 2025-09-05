# -*- coding: utf-8 -*-
"""
Kronos市场机会服务
基于Kronos预测识别市场交易机会
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum
from dataclasses import dataclass
import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.ml.kronos_prediction_service import get_kronos_service, KronosPrediction
from app.services.exchanges.okx.okx_service import OKXService

# 全局服务实例
_kronos_market_opportunity_service = None


class OpportunityType(Enum):
    """机会类型"""
    STRONG_BUY = "强买入机会"
    BUY = "买入机会"
    STRONG_SELL = "强卖出机会"
    SELL = "卖出机会"
    NEUTRAL = "中性"


@dataclass
class MarketOpportunity:
    """市场机会"""
    symbol: str
    opportunity_type: OpportunityType
    confidence: float
    expected_return: float
    risk_level: str
    entry_price: float
    target_price: float
    stop_loss: float
    reasoning: str
    timestamp: datetime
    kronos_prediction: Optional[KronosPrediction] = None


class KronosMarketOpportunityService:
    """Kronos市场机会服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.okx_service = OKXService()
        
        # 配置参数
        self.kronos_config = self.settings.kronos_config
        self.target_symbols = self.kronos_config.get('target_symbols', [])
        
        # 机会识别阈值
        self.strong_signal_threshold = 0.7
        self.moderate_signal_threshold = 0.5
        self.min_expected_return = 0.02  # 最小期望收益2%
        
    async def scan_market_opportunities(
        self,
        force_update: bool = False
    ) -> List[MarketOpportunity]:
        """扫描市场机会"""
        try:
            self.logger.info("开始扫描Kronos市场机会...")
            
            opportunities = []
            kronos_service = await get_kronos_service()
            
            if not kronos_service:
                self.logger.warning("Kronos服务不可用，无法扫描市场机会")
                return opportunities
            
            # 并发获取所有目标币种的预测
            tasks = []
            for symbol in self.target_symbols:
                task = self._analyze_symbol_opportunity(symbol, kronos_service, force_update)
                tasks.append(task)
            
            # 等待所有分析完成
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self.logger.error(f"分析{self.target_symbols[i]}机会失败: {result}")
                elif result:
                    opportunities.append(result)
            
            # 按置信度排序
            opportunities.sort(key=lambda x: x.confidence, reverse=True)
            
            self.logger.info(f"扫描完成，发现{len(opportunities)}个市场机会")
            return opportunities
            
        except Exception as e:
            self.logger.error(f"扫描市场机会失败: {e}")
            return []
    
    async def _analyze_symbol_opportunity(
        self,
        symbol: str,
        kronos_service,
        force_update: bool = False
    ) -> Optional[MarketOpportunity]:
        """分析单个币种的机会"""
        try:
            # 获取历史数据
            historical_data = await self.okx_service.get_kline_data(symbol, "1H", 200)
            if not historical_data:
                return None
            
            # 转换为DataFrame
            df = self._convert_kline_to_dataframe(historical_data)
            if df is None or len(df) < 50:
                return None
            
            # 获取Kronos预测
            prediction = await kronos_service.get_prediction(symbol, df, force_update)
            if not prediction:
                return None
            
            # 分析机会
            opportunity = self._evaluate_opportunity(symbol, prediction)
            return opportunity
            
        except Exception as e:
            self.logger.error(f"分析{symbol}机会失败: {e}")
            return None
    
    def _evaluate_opportunity(
        self,
        symbol: str,
        prediction: KronosPrediction
    ) -> Optional[MarketOpportunity]:
        """评估交易机会"""
        try:
            confidence = prediction.confidence
            price_change_pct = prediction.price_change_pct
            current_price = prediction.current_price
            predicted_price = prediction.predicted_price
            
            # 判断机会类型
            opportunity_type = OpportunityType.NEUTRAL
            
            if confidence >= self.strong_signal_threshold:
                if price_change_pct >= 0.05:  # 预测上涨5%以上
                    opportunity_type = OpportunityType.STRONG_BUY
                elif price_change_pct <= -0.05:  # 预测下跌5%以上
                    opportunity_type = OpportunityType.STRONG_SELL
                elif price_change_pct >= 0.02:  # 预测上涨2%以上
                    opportunity_type = OpportunityType.BUY
                elif price_change_pct <= -0.02:  # 预测下跌2%以上
                    opportunity_type = OpportunityType.SELL
            elif confidence >= self.moderate_signal_threshold:
                if price_change_pct >= 0.03:  # 预测上涨3%以上
                    opportunity_type = OpportunityType.BUY
                elif price_change_pct <= -0.03:  # 预测下跌3%以上
                    opportunity_type = OpportunityType.SELL
            
            # 如果没有明显机会，返回None
            if opportunity_type == OpportunityType.NEUTRAL:
                return None
            
            # 计算期望收益
            expected_return = abs(price_change_pct)
            if expected_return < self.min_expected_return:
                return None
            
            # 计算风险管理参数
            if opportunity_type in [OpportunityType.STRONG_BUY, OpportunityType.BUY]:
                entry_price = current_price
                target_price = predicted_price
                stop_loss = current_price * 0.97  # 3%止损
            else:  # 卖出机会
                entry_price = current_price
                target_price = predicted_price
                stop_loss = current_price * 1.03  # 3%止损
            
            # 评估风险等级
            risk_level = self._assess_risk_level(confidence, expected_return)
            
            # 生成推理说明
            reasoning = self._generate_reasoning(
                symbol, prediction, opportunity_type, confidence, expected_return
            )
            
            return MarketOpportunity(
                symbol=symbol,
                opportunity_type=opportunity_type,
                confidence=confidence,
                expected_return=expected_return,
                risk_level=risk_level,
                entry_price=entry_price,
                target_price=target_price,
                stop_loss=stop_loss,
                reasoning=reasoning,
                timestamp=datetime.now(),
                kronos_prediction=prediction
            )
            
        except Exception as e:
            self.logger.error(f"评估{symbol}机会失败: {e}")
            return None
    
    def _assess_risk_level(self, confidence: float, expected_return: float) -> str:
        """评估风险等级"""
        risk_score = expected_return / confidence  # 收益风险比
        
        if risk_score > 0.15:
            return "高风险"
        elif risk_score > 0.08:
            return "中等风险"
        else:
            return "低风险"
    
    def _generate_reasoning(
        self,
        symbol: str,
        prediction: KronosPrediction,
        opportunity_type: OpportunityType,
        confidence: float,
        expected_return: float
    ) -> str:
        """生成推理说明"""
        direction = "上涨" if prediction.price_change_pct > 0 else "下跌"
        change_pct = abs(prediction.price_change_pct) * 100
        
        reasoning = (
            f"Kronos模型预测{symbol}在未来{prediction.prediction_horizon}小时内"
            f"{direction}{change_pct:.1f}%，置信度{confidence:.1%}。"
            f"当前价格{prediction.current_price:.4f}，"
            f"预测价格{prediction.predicted_price:.4f}，"
            f"期望收益{expected_return:.1%}。"
        )
        
        if opportunity_type in [OpportunityType.STRONG_BUY, OpportunityType.STRONG_SELL]:
            reasoning += "这是一个高置信度的强信号机会。"
        else:
            reasoning += "这是一个中等置信度的交易机会。"
        
        return reasoning
    
    def _convert_kline_to_dataframe(self, kline_data: List[Dict]) -> Optional[pd.DataFrame]:
        """转换K线数据为DataFrame"""
        try:
            if not kline_data:
                return None
            
            df_data = []
            for item in kline_data:
                df_data.append({
                    'timestamp': pd.to_datetime(item['timestamp'], unit='ms'),
                    'open': float(item['open']),
                    'high': float(item['high']),
                    'low': float(item['low']),
                    'close': float(item['close']),
                    'volume': float(item['volume'])
                })
            
            df = pd.DataFrame(df_data)
            df = df.sort_values('timestamp').reset_index(drop=True)
            df.set_index('timestamp', inplace=True)
            
            return df
            
        except Exception as e:
            self.logger.error(f"转换K线数据失败: {e}")
            return None
    
    async def get_top_opportunities(
        self,
        limit: int = 5,
        min_confidence: float = 0.6
    ) -> List[MarketOpportunity]:
        """获取顶级交易机会"""
        try:
            all_opportunities = await self.scan_market_opportunities()
            
            # 过滤低置信度机会
            filtered_opportunities = [
                opp for opp in all_opportunities 
                if opp.confidence >= min_confidence
            ]
            
            # 返回前N个机会
            return filtered_opportunities[:limit]
            
        except Exception as e:
            self.logger.error(f"获取顶级机会失败: {e}")
            return []
    
    def get_scan_status(self) -> Dict[str, Any]:
        """获取扫描状态"""
        return {
            'target_symbols': self.target_symbols,
            'symbol_count': len(self.target_symbols),
            'thresholds': {
                'strong_signal': self.strong_signal_threshold,
                'moderate_signal': self.moderate_signal_threshold,
                'min_expected_return': self.min_expected_return
            },
            'last_scan': datetime.now().isoformat()
        }


async def get_kronos_market_opportunity_service() -> KronosMarketOpportunityService:
    """获取Kronos市场机会服务实例"""
    global _kronos_market_opportunity_service
    if _kronos_market_opportunity_service is None:
        _kronos_market_opportunity_service = KronosMarketOpportunityService()
    return _kronos_market_opportunity_service