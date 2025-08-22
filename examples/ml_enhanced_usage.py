# -*- coding: utf-8 -*-
"""
ML增强功能使用示例
ML Enhanced Features Usage Examples
"""

import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any

# 假设这些是从应用中导入的服务
# from app.services.ml_enhanced_service import MLEnhancedService
# from app.services.ml_enhanced_monitor_service import MLEnhancedMonitorService
# from app.core.config import get_settings


async def example_ml_prediction():
    """ML信号预测示例"""
    print("=== ML信号预测示例 ===")
    
    # 初始化ML服务
    # ml_service = MLEnhancedService()
    
    # 预测单个交易对
    symbol = "BTCUSDT"
    print(f"正在预测 {symbol} 的交易信号...")
    
    # prediction = await ml_service.predict_signal(symbol)
    
    # 模拟预测结果
    prediction_result = {
        "symbol": symbol,
        "signal": "buy",
        "confidence": 0.75,
        "probability_distribution": {
            "strong_sell": 0.05,
            "sell": 0.10,
            "hold": 0.10,
            "buy": 0.45,
            "strong_buy": 0.30
        },
        "model_accuracy": 0.68,
        "timestamp": datetime.now()
    }
    
    print(f"预测结果：")
    print(f"  信号: {prediction_result['signal']}")
    print(f"  置信度: {prediction_result['confidence']:.2%}")
    print(f"  模型准确率: {prediction_result['model_accuracy']:.2%}")
    print()


async def example_anomaly_detection():
    """异常检测示例"""
    print("=== 异常检测示例 ===")
    
    # ml_service = MLEnhancedService()
    
    symbol = "ETHUSDT"
    print(f"正在检测 {symbol} 的市场异常...")
    
    # anomalies = await ml_service.detect_anomalies(symbol)
    
    # 模拟异常检测结果
    anomalies_result = [
        {
            "symbol": symbol,
            "anomaly_type": "volume_anomaly",
            "severity": 0.85,
            "description": "成交量异常：当前成交量是正常水平的4.2倍",
            "recommendation": "关注市场情绪变化，可能有重要消息或大资金进出",
            "timestamp": datetime.now()
        },
        {
            "symbol": symbol,
            "anomaly_type": "price_anomaly", 
            "severity": 0.72,
            "description": "价格波动异常：检测到异常价格模式",
            "recommendation": "密切关注价格走势，可能存在异常波动",
            "timestamp": datetime.now()
        }
    ]
    
    print(f"检测到 {len(anomalies_result)} 个异常：")
    for i, anomaly in enumerate(anomalies_result, 1):
        print(f"  异常 {i}:")
        print(f"    类型: {anomaly['anomaly_type']}")
        print(f"    严重程度: {anomaly['severity']:.2%}")
        print(f"    描述: {anomaly['description']}")
        print(f"    建议: {anomaly['recommendation']}")
    print()


async def example_parameter_optimization():
    """参数优化示例"""
    print("=== 参数优化示例 ===")
    
    # ml_service = MLEnhancedService()
    
    symbol = "SOLUSDT"
    print(f"正在优化 {symbol} 的策略参数...")
    
    # optimized_params = await ml_service.optimize_parameters(symbol)
    
    # 模拟优化结果
    optimization_result = {
        "symbol": symbol,
        "supertrend": {
            "period": 12,
            "multiplier": 2.8,
            "performance_score": 0.73
        },
        "volume": {
            "threshold_multiplier": 3.5,
            "base_volume": 1250000,
            "volume_std": 450000
        },
        "optimization_timestamp": datetime.now(),
        "data_period": "2024-01-01 to 2024-02-22"
    }
    
    print(f"优化结果：")
    print(f"  SuperTrend参数:")
    print(f"    周期: {optimization_result['supertrend']['period']}")
    print(f"    倍数: {optimization_result['supertrend']['multiplier']}")
    print(f"    性能分数: {optimization_result['supertrend']['performance_score']:.2%}")
    print(f"  成交量参数:")
    print(f"    阈值倍数: {optimization_result['volume']['threshold_multiplier']}")
    print()


async def example_batch_analysis():
    """批量分析示例"""
    print("=== 批量ML分析示例 ===")
    
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"]
    print(f"正在分析 {len(symbols)} 个交易对...")
    
    # 模拟批量分析结果
    batch_results = {
        "BTCUSDT": {
            "prediction": {"signal": "buy", "confidence": 0.72},
            "anomalies": [{"type": "volume_anomaly", "severity": 0.65}]
        },
        "ETHUSDT": {
            "prediction": {"signal": "hold", "confidence": 0.58},
            "anomalies": []
        },
        "SOLUSDT": {
            "prediction": {"signal": "strong_buy", "confidence": 0.85},
            "anomalies": [{"type": "price_anomaly", "severity": 0.45}]
        },
        "DOGEUSDT": {
            "prediction": {"signal": "sell", "confidence": 0.68},
            "anomalies": []
        },
        "XRPUSDT": {
            "prediction": {"signal": "hold", "confidence": 0.62},
            "anomalies": [{"type": "pattern_anomaly", "severity": 0.55}]
        }
    }
    
    summary = {
        "total_symbols": len(symbols),
        "signals_distribution": {
            "strong_buy": 1,
            "buy": 1,
            "hold": 2,
            "sell": 1,
            "strong_sell": 0
        },
        "total_anomalies": 3,
        "average_confidence": 0.69
    }
    
    print("分析摘要：")
    print(f"  总交易对数: {summary['total_symbols']}")
    print(f"  信号分布: {summary['signals_distribution']}")
    print(f"  检测到异常: {summary['total_anomalies']}")
    print(f"  平均置信度: {summary['average_confidence']:.2%}")
    print()
    
    print("详细结果：")
    for symbol, result in batch_results.items():
        prediction = result.get('prediction', {})
        anomalies = result.get('anomalies', [])
        
        print(f"  {symbol}:")
        print(f"    信号: {prediction.get('signal', 'N/A')} (置信度: {prediction.get('confidence', 0):.2%})")
        if anomalies:
            print(f"    异常: {len(anomalies)} 个")
        else:
            print(f"    异常: 无")
    print()


async def example_enhanced_monitoring():
    """增强监控示例"""
    print("=== ML增强监控示例 ===")
    
    # enhanced_monitor = MLEnhancedMonitorService()
    
    print("正在执行增强监控周期...")
    
    # monitoring_results = await enhanced_monitor.enhanced_monitoring_cycle()
    
    # 模拟监控结果
    monitoring_results = {
        "timestamp": datetime.now(),
        "symbols_analyzed": 5,
        "alerts": [
            {
                "symbol": "BTCUSDT",
                "alert_type": "volume",
                "level": "high",
                "message": "【BTCUSDT】VOLUME警报\nML预测: buy (置信度: 72%)\n检测到异常: 成交量异常放大",
                "confidence_score": 0.78,
                "recommendation": "成交量异常放大，可能有重要消息或大资金进出 | ML模型显示买入信号，可考虑逢低建仓"
            },
            {
                "symbol": "SOLUSDT",
                "alert_type": "ml_signal",
                "level": "high",
                "message": "【SOLUSDT】ML智能警报\n强烈strong_buy信号 (置信度: 85%)",
                "confidence_score": 0.85,
                "recommendation": "ML模型建议关注买入机会，但请结合其他指标确认"
            }
        ],
        "summary": {
            "total_alerts": 2,
            "alert_levels": {"critical": 0, "high": 2, "medium": 0, "low": 0},
            "symbols_with_alerts": ["BTCUSDT", "SOLUSDT"],
            "ml_predictions_count": 5,
            "anomalies_detected": 3,
            "monitoring_health": "warning"
        }
    }
    
    print("监控摘要：")
    print(f"  分析交易对: {monitoring_results['symbols_analyzed']}")
    print(f"  生成警报: {monitoring_results['summary']['total_alerts']}")
    print(f"  ML预测: {monitoring_results['summary']['ml_predictions_count']}")
    print(f"  检测异常: {monitoring_results['summary']['anomalies_detected']}")
    print(f"  监控状态: {monitoring_results['summary']['monitoring_health']}")
    print()
    
    print("重要警报：")
    for alert in monitoring_results['alerts']:
        print(f"  {alert['symbol']} - {alert['level'].upper()}:")
        print(f"    类型: {alert['alert_type']}")
        print(f"    置信度: {alert['confidence_score']:.2%}")
        print(f"    建议: {alert['recommendation'][:50]}...")
    print()


async def example_api_usage():
    """API使用示例"""
    print("=== API使用示例 ===")
    
    print("以下是如何通过HTTP API使用ML增强功能：")
    print()
    
    # 预测API示例
    print("1. 信号预测API:")
    print("   POST /api/ml/predict")
    print("   Body: {\"symbol\": \"BTCUSDT\", \"include_features\": true}")
    print()
    
    # 异常检测API示例
    print("2. 异常检测API:")
    print("   POST /api/ml/anomaly-detection")
    print("   Body: {\"symbol\": \"ETHUSDT\", \"detection_types\": [\"volume_anomaly\", \"price_anomaly\"]}")
    print()
    
    # 参数优化API示例
    print("3. 参数优化API:")
    print("   POST /api/ml/optimize")
    print("   Body: {\"symbol\": \"SOLUSDT\", \"optimization_type\": \"all\"}")
    print()
    
    # 批量分析API示例
    print("4. 批量分析API:")
    print("   POST /api/ml/batch-analysis")
    print("   Body: {")
    print("     \"symbols\": [\"BTCUSDT\", \"ETHUSDT\", \"SOLUSDT\"],")
    print("     \"include_prediction\": true,")
    print("     \"include_anomaly_detection\": true")
    print("   }")
    print()
    
    # 模型状态API示例
    print("5. 模型状态API:")
    print("   GET /api/ml/model-status/BTCUSDT")
    print()
    
    # 配置API示例
    print("6. ML配置API:")
    print("   GET /api/ml/config")
    print()


async def main():
    """主函数 - 运行所有示例"""
    print("🤖 ML增强功能使用示例")
    print("=" * 50)
    print()
    
    # 运行各个示例
    await example_ml_prediction()
    await example_anomaly_detection()
    await example_parameter_optimization()
    await example_batch_analysis()
    await example_enhanced_monitoring()
    await example_api_usage()
    
    print("✅ 所有示例运行完成！")
    print()
    print("💡 提示：")
    print("- 这些示例展示了ML增强功能的主要用法")
    print("- 实际使用时需要先安装依赖：pip install scikit-learn joblib")
    print("- 确保在配置文件中启用ML功能")
    print("- 首次使用需要训练模型，可能需要一些时间")


if __name__ == "__main__":
    asyncio.run(main())