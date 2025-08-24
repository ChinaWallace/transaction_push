# -*- coding: utf-8 -*-
"""
Kronos前置集成决策服务测试
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

from app.services.kronos_integrated_decision_service import (
    KronosIntegratedDecisionService,
    KronosEnhancedDecision,
    KronosSignalStrength
)
from app.services.kronos_prediction_service import KronosPrediction
from app.services.position_analysis_service import PositionRecommendation, PositionRisk


class TestKronosIntegratedDecisionService:
    """Kronos集成决策服务测试类"""
    
    @pytest.fixture
    def service(self):
        """创建服务实例"""
        return KronosIntegratedDecisionService()
    
    @pytest.fixture
    def mock_kronos_prediction(self):
        """模拟Kronos预测结果"""
        import pandas as pd
        # 创建模拟预测数据
        predictions_df = pd.DataFrame({
            'open': [65000.0, 65100.0, 65200.0],
            'high': [65200.0, 65300.0, 65400.0],
            'low': [64800.0, 64900.0, 65000.0],
            'close': [65100.0, 65200.0, 65300.0],
            'volume': [1000000.0, 1100000.0, 1200000.0]
        })
        
        return KronosPrediction(
            symbol="BTC-USDT",
            timestamp=datetime.now(),
            predictions=predictions_df,
            confidence=0.82,
            signal="buy",
            price_change_pct=0.035,  # 3.5%上涨
            volatility=0.08,
            trend_direction="bullish"
        )
    
    @pytest.fixture
    def mock_technical_result(self):
        """模拟技术分析结果"""
        return {
            'overall_signal': 'bullish',
            'confidence': 0.75,
            'trend_strength': 0.8,
            'volatility': 'medium'
        }
    
    @pytest.fixture
    def mock_position_analysis(self):
        """模拟持仓分析结果"""
        return {
            'recommendation': PositionRecommendation.INCREASE,
            'risk_level': PositionRisk.MEDIUM
        }
    
    def test_evaluate_kronos_signal_strength(self, service, mock_kronos_prediction):
        """测试Kronos信号强度评估"""
        # 测试非常强信号
        mock_kronos_prediction.confidence = 0.8
        mock_kronos_prediction.price_change_pct = 0.03  # 3%变化
        strength = service._evaluate_kronos_signal_strength(mock_kronos_prediction)
        assert strength == KronosSignalStrength.VERY_STRONG
        
        # 测试强信号
        mock_kronos_prediction.confidence = 0.65
        mock_kronos_prediction.price_change_pct = 0.02  # 2%变化
        strength = service._evaluate_kronos_signal_strength(mock_kronos_prediction)
        assert strength == KronosSignalStrength.STRONG
        
        # 测试中等信号
        mock_kronos_prediction.confidence = 0.55
        mock_kronos_prediction.price_change_pct = 0.012  # 1.2%变化
        strength = service._evaluate_kronos_signal_strength(mock_kronos_prediction)
        assert strength == KronosSignalStrength.MODERATE
    
    def test_calculate_signal_confluence(self, service, mock_kronos_prediction):
        """测试信号一致性计算"""
        # 测试高一致性
        confluence = service._calculate_signal_confluence(
            mock_kronos_prediction,
            "bullish",
            PositionRecommendation.INCREASE
        )
        assert confluence >= 0.7  # 应该有较高的一致性
        
        # 测试低一致性
        confluence = service._calculate_signal_confluence(
            mock_kronos_prediction,
            "bearish",
            PositionRecommendation.REDUCE
        )
        assert confluence <= 0.6  # 应该有较低的一致性
    
    def test_determine_final_action(self, service, mock_kronos_prediction):
        """测试最终行动决策"""
        # 测试强烈买入信号
        action, confidence = service._determine_final_action(
            mock_kronos_prediction,
            0.85,  # 高Kronos置信度
            "bullish",
            0.75,  # 技术分析置信度
            PositionRecommendation.INCREASE,
            0.9   # 高信号一致性
        )
        
        assert "买入" in action
        assert confidence >= 0.7
    
    def test_calculate_position_size(self, service):
        """测试仓位大小计算"""
        # 测试高置信度
        size = service._calculate_position_size(0.9)
        assert size >= 0.25  # 高置信度应该有较大仓位
        
        # 测试低置信度
        size = service._calculate_position_size(0.5)
        assert size <= 0.1   # 低置信度应该有较小仓位
    
    @pytest.mark.asyncio
    async def test_get_kronos_enhanced_decision_success(self, service):
        """测试成功获取Kronos增强决策"""
        with patch.object(service, '_get_kronos_prediction') as mock_kronos, \
             patch.object(service, '_get_weighted_technical_analysis') as mock_tech, \
             patch.object(service, '_get_kronos_weighted_position_analysis') as mock_pos, \
             patch.object(service, 'okx_service') as mock_okx:
            
            # 设置模拟返回值
            import pandas as pd
            predictions_df = pd.DataFrame({
                'open': [65000.0], 'high': [65200.0], 'low': [64800.0], 
                'close': [65100.0], 'volume': [1000000.0]
            })
            
            mock_kronos.return_value = KronosPrediction(
                symbol="BTC-USDT",
                timestamp=datetime.now(),
                predictions=predictions_df,
                confidence=0.82,
                signal="buy",
                price_change_pct=0.035,
                volatility=0.08,
                trend_direction="bullish"
            )
            
            mock_tech.return_value = {
                'overall_signal': 'bullish',
                'confidence': 0.75
            }
            
            mock_pos.return_value = {
                'recommendation': PositionRecommendation.INCREASE,
                'risk_level': PositionRisk.MEDIUM
            }
            
            mock_okx.get_current_price = AsyncMock(return_value=65000.0)
            
            # 执行测试
            result = await service.get_kronos_enhanced_decision("BTC-USDT")
            
            # 验证结果
            assert result is not None
            assert isinstance(result, KronosEnhancedDecision)
            assert result.symbol == "BTC-USDT"
            assert result.final_confidence > 0
            assert result.position_size > 0
    
    @pytest.mark.asyncio
    async def test_get_kronos_enhanced_decision_no_kronos(self, service):
        """测试没有Kronos预测时的决策"""
        with patch.object(service, '_get_kronos_prediction') as mock_kronos, \
             patch.object(service, '_get_weighted_technical_analysis') as mock_tech, \
             patch.object(service, '_get_kronos_weighted_position_analysis') as mock_pos, \
             patch.object(service, 'okx_service') as mock_okx:
            
            # Kronos预测失败
            mock_kronos.return_value = None
            
            mock_tech.return_value = {
                'overall_signal': 'bullish',
                'confidence': 0.75
            }
            
            mock_pos.return_value = {
                'recommendation': PositionRecommendation.HOLD,
                'risk_level': PositionRisk.LOW
            }
            
            mock_okx.get_current_price = AsyncMock(return_value=65000.0)
            
            # 执行测试
            result = await service.get_kronos_enhanced_decision("BTC-USDT")
            
            # 验证结果 - 应该回退到技术分析
            assert result is not None
            assert result.kronos_prediction is None
            assert result.kronos_confidence == 0.0
            assert result.technical_signal == 'bullish'
    
    @pytest.mark.asyncio
    async def test_batch_analyze_symbols(self, service):
        """测试批量分析交易对"""
        symbols = ["BTC-USDT", "ETH-USDT", "BNB-USDT"]
        
        with patch.object(service, 'get_kronos_enhanced_decision') as mock_decision:
            # 模拟部分成功的结果
            mock_decision.side_effect = [
                KronosEnhancedDecision(
                    symbol="BTC-USDT",
                    timestamp=datetime.now(),
                    kronos_prediction=None,
                    kronos_signal_strength=KronosSignalStrength.STRONG,
                    kronos_confidence=0.8,
                    technical_signal="bullish",
                    technical_confidence=0.75,
                    position_recommendation=PositionRecommendation.INCREASE,
                    position_risk=PositionRisk.MEDIUM,
                    final_action="买入",
                    final_confidence=0.8,
                    signal_confluence=0.85,
                    entry_price=65000.0,
                    stop_loss=63000.0,
                    take_profit=68000.0,
                    position_size=0.2,
                    reasoning="测试决策",
                    market_regime=None
                ),
                None,  # ETH-USDT 失败
                Exception("网络错误")  # BNB-USDT 异常
            ]
            
            # 执行批量分析
            results = await service.batch_analyze_symbols(symbols)
            
            # 验证结果
            assert len(results) == 3
            assert results["BTC-USDT"] is not None
            assert results["ETH-USDT"] is None
            assert results["BNB-USDT"] is None
    
    def test_fallback_to_technical_decision(self, service):
        """测试回退到技术分析决策"""
        # 测试强烈看涨信号
        action, confidence = service._fallback_to_technical_decision("strong_bullish", 0.85)
        assert action == "强烈买入"
        assert confidence == 0.85
        
        # 测试中性信号
        action, confidence = service._fallback_to_technical_decision("neutral", 0.5)
        assert action == "持有观望"
        assert confidence == 0.5
        
        # 测试看跌信号
        action, confidence = service._fallback_to_technical_decision("bearish", 0.7)
        assert action == "卖出"
        assert confidence == 0.7


@pytest.mark.asyncio
async def test_service_initialization():
    """测试服务初始化"""
    service = KronosIntegratedDecisionService()
    
    assert service.settings is not None
    assert service.logger is not None
    assert service.position_service is not None
    assert service.trend_service is not None
    assert service.okx_service is not None
    assert isinstance(service.enable_kronos, bool)


@pytest.mark.asyncio
async def test_get_kronos_integrated_service():
    """测试获取服务实例"""
    from app.services.kronos_integrated_decision_service import get_kronos_integrated_service
    
    service1 = await get_kronos_integrated_service()
    service2 = await get_kronos_integrated_service()
    
    # 应该返回同一个实例（单例模式）
    assert service1 is service2
    assert isinstance(service1, KronosIntegratedDecisionService)


if __name__ == "__main__":
    # 运行简单的功能测试
    async def simple_test():
        print("🧪 运行Kronos集成决策服务简单测试...")
        
        try:
            service = KronosIntegratedDecisionService()
            print("✅ 服务初始化成功")
            
            # 测试信号强度评估
            mock_prediction = KronosPrediction(
                symbol="BTC-USDT",
                timestamp=datetime.now(),
                predicted_price_change=0.06,
                confidence=0.85,
                volatility=0.08,
                trend_direction="bullish"
            )
            
            strength = service._evaluate_kronos_signal_strength(mock_prediction)
            print(f"✅ 信号强度评估: {strength.value}")
            
            # 测试仓位计算
            position_size = service._calculate_position_size(0.8)
            print(f"✅ 仓位计算: {position_size:.1%}")
            
            # 测试信号一致性
            confluence = service._calculate_signal_confluence(
                mock_prediction, "bullish", PositionRecommendation.INCREASE
            )
            print(f"✅ 信号一致性: {confluence:.2f}")
            
            print("🎉 所有基础功能测试通过!")
            
        except Exception as e:
            print(f"❌ 测试失败: {e}")
    
    asyncio.run(simple_test())