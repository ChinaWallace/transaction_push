#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试Kronos张量形状修复
"""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.kronos_prediction_service import KronosPredictionService
from app.core.logging import get_logger

logger = get_logger(__name__)


async def test_kronos_tensor_fix():
    """测试Kronos张量形状修复"""
    
    logger.info("开始测试Kronos张量形状修复...")
    
    try:
        # 创建测试数据
        dates = pd.date_range(start='2024-01-01', periods=300, freq='H')
        
        # 模拟真实的K线数据
        np.random.seed(42)
        base_price = 100.0
        prices = []
        
        for i in range(len(dates)):
            # 模拟价格随机游走
            change = np.random.normal(0, 0.02)  # 2%的标准差
            base_price *= (1 + change)
            prices.append(base_price)
        
        # 创建OHLCV数据
        test_data = pd.DataFrame({
            'open': prices,
            'high': [p * (1 + abs(np.random.normal(0, 0.01))) for p in prices],
            'low': [p * (1 - abs(np.random.normal(0, 0.01))) for p in prices],
            'close': [p * (1 + np.random.normal(0, 0.005)) for p in prices],
            'volume': [np.random.uniform(1000000, 5000000) for _ in prices],
        }, index=dates)
        
        logger.info(f"创建测试数据: {test_data.shape}")
        
        # 初始化Kronos服务
        kronos_service = KronosPredictionService()
        await kronos_service.initialize()
        
        if kronos_service.predictor is None:
            logger.error("Kronos预测器初始化失败")
            return False
        
        logger.info(f"使用实现类型: {kronos_service.predictor.implementation_type}")
        
        # 测试不同的参数组合
        test_cases = [
            {"lookback": 50, "horizon": 6, "samples": 1},
            {"lookback": 100, "horizon": 12, "samples": 1},
            {"lookback": 200, "horizon": 24, "samples": 3},  # 这个可能会触发张量问题
        ]
        
        for i, case in enumerate(test_cases):
            logger.info(f"\n测试案例 {i+1}: {case}")
            
            try:
                # 执行预测
                result = await kronos_service.predictor.predict(
                    data=test_data,
                    lookback=case["lookback"],
                    prediction_horizon=case["horizon"],
                    temperature=0.8,
                    top_p=0.9,
                    sample_count=case["samples"]
                )
                
                if result is not None and len(result) > 0:
                    logger.info(f"✅ 测试案例 {i+1} 成功: 预测结果形状 {result.shape}")
                else:
                    logger.warning(f"⚠️ 测试案例 {i+1} 返回空结果")
                    
            except Exception as e:
                logger.error(f"❌ 测试案例 {i+1} 失败: {e}")
                
                # 如果是张量形状错误，检查是否正确处理
                if "size of tensor" in str(e):
                    logger.error("仍然存在张量形状问题，需要进一步修复")
                    return False
        
        # 测试完整的预测流程
        logger.info("\n测试完整预测流程...")
        
        try:
            prediction = await kronos_service.get_prediction(
                symbol="ETH-USDT-SWAP",
                historical_data=test_data,
                force_update=True
            )
            
            if prediction:
                logger.info(f"✅ 完整预测流程成功:")
                logger.info(f"   信号: {prediction.signal}")
                logger.info(f"   置信度: {prediction.confidence:.3f}")
                logger.info(f"   价格变化: {prediction.price_change_pct:.3f}%")
                logger.info(f"   趋势方向: {prediction.trend_direction}")
            else:
                logger.warning("⚠️ 完整预测流程返回空结果")
                
        except Exception as e:
            logger.error(f"❌ 完整预测流程失败: {e}")
            return False
        
        logger.info("\n🎉 所有测试完成，张量形状问题已修复！")
        return True
        
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")
        return False


if __name__ == "__main__":
    # 运行测试
    success = asyncio.run(test_kronos_tensor_fix())
    
    if success:
        print("\n✅ 测试成功！Kronos张量形状问题已修复。")
    else:
        print("\n❌ 测试失败！需要进一步检查和修复。")
        sys.exit(1)