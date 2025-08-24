# -*- coding: utf-8 -*-
"""
Kronos前置集成决策示例
演示如何使用Kronos前置集成服务进行交易决策
"""

import asyncio
import sys
import os
from datetime import datetime
from typing import List

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.kronos_integrated_decision_service import (
    get_kronos_integrated_service,
    KronosEnhancedDecision,
    KronosSignalStrength
)
from app.core.logging import get_logger

logger = get_logger(__name__)


async def demo_single_symbol_analysis():
    """演示单个交易对的Kronos集成分析"""
    print("\n" + "="*60)
    print("🎯 单个交易对Kronos集成决策演示")
    print("="*60)
    
    try:
        service = await get_kronos_integrated_service()
        symbol = "BTC-USDT"
        
        print(f"📊 正在分析 {symbol}...")
        decision = await service.get_kronos_enhanced_decision(symbol, force_update=True)
        
        if decision:
            print(f"\n✅ {symbol} 分析完成:")
            print(f"   🤖 Kronos置信度: {decision.kronos_confidence:.2f}")
            print(f"   💪 信号强度: {decision.kronos_signal_strength.value}")
            print(f"   📈 技术信号: {decision.technical_signal}")
            print(f"   💼 持仓建议: {decision.position_recommendation.value}")
            print(f"   🎯 最终行动: {decision.final_action}")
            print(f"   🔥 综合置信度: {decision.final_confidence:.2f}")
            print(f"   🤝 信号一致性: {decision.signal_confluence:.2f}")
            print(f"   🌊 市场状态: {decision.market_regime.value}")
            print(f"   💰 建议仓位: {decision.position_size:.1%}")
            
            if decision.entry_price:
                print(f"   📍 入场价格: ${decision.entry_price:.2f}")
            if decision.stop_loss:
                print(f"   🛑 止损价格: ${decision.stop_loss:.2f}")
            if decision.take_profit:
                print(f"   🎯 止盈价格: ${decision.take_profit:.2f}")
            
            print(f"\n💡 决策依据:")
            print(f"   {decision.reasoning}")
        else:
            print(f"❌ 无法获取 {symbol} 的分析结果")
            
    except Exception as e:
        print(f"❌ 单个交易对分析失败: {e}")


async def demo_batch_analysis():
    """演示批量交易对的Kronos集成分析"""
    print("\n" + "="*60)
    print("📊 批量交易对Kronos集成决策演示")
    print("="*60)
    
    try:
        service = await get_kronos_integrated_service()
        symbols = ["BTC-USDT", "ETH-USDT", "BNB-USDT", "SOL-USDT", "ADA-USDT"]
        
        print(f"🔄 正在批量分析 {len(symbols)} 个交易对...")
        results = await service.batch_analyze_symbols(symbols, force_update=True)
        
        successful_count = sum(1 for r in results.values() if r is not None)
        print(f"\n📈 批量分析完成: {successful_count}/{len(symbols)} 个成功")
        
        # 按置信度排序显示结果
        valid_results = [(symbol, decision) for symbol, decision in results.items() if decision]
        valid_results.sort(key=lambda x: x[1].final_confidence, reverse=True)
        
        print(f"\n🏆 分析结果 (按置信度排序):")
        print("-" * 80)
        print(f"{'交易对':<12} {'最终行动':<12} {'置信度':<8} {'Kronos':<8} {'一致性':<8} {'仓位':<8}")
        print("-" * 80)
        
        for symbol, decision in valid_results:
            print(f"{symbol:<12} {decision.final_action:<12} "
                  f"{decision.final_confidence:.2f}    "
                  f"{decision.kronos_confidence:.2f}    "
                  f"{decision.signal_confluence:.2f}    "
                  f"{decision.position_size:.1%}")
        
        # 显示强信号
        strong_signals = [
            (symbol, decision) for symbol, decision in valid_results
            if decision.kronos_signal_strength in [KronosSignalStrength.STRONG, KronosSignalStrength.VERY_STRONG]
            and decision.final_confidence >= 0.7
        ]
        
        if strong_signals:
            print(f"\n🔥 发现 {len(strong_signals)} 个强信号:")
            for symbol, decision in strong_signals:
                print(f"   🚀 {symbol}: {decision.final_action} "
                      f"(置信度: {decision.final_confidence:.2f}, "
                      f"强度: {decision.kronos_signal_strength.value})")
        else:
            print("\n⚠️ 当前没有发现强信号")
            
    except Exception as e:
        print(f"❌ 批量分析失败: {e}")


async def demo_strong_signals_detection():
    """演示强信号检测功能"""
    print("\n" + "="*60)
    print("🔥 强Kronos信号检测演示")
    print("="*60)
    
    try:
        service = await get_kronos_integrated_service()
        
        # 扩大搜索范围
        symbols = [
            "BTC-USDT", "ETH-USDT", "BNB-USDT", "ADA-USDT", "SOL-USDT",
            "XRP-USDT", "DOT-USDT", "DOGE-USDT", "AVAX-USDT", "MATIC-USDT",
            "LINK-USDT", "UNI-USDT", "LTC-USDT", "BCH-USDT", "ATOM-USDT"
        ]
        
        print(f"🔍 在 {len(symbols)} 个交易对中搜索强信号...")
        results = await service.batch_analyze_symbols(symbols, force_update=True)
        
        # 筛选强信号
        strong_signals = []
        for symbol, decision in results.items():
            if decision and decision.kronos_confidence >= 0.7:
                if decision.kronos_signal_strength in [
                    KronosSignalStrength.STRONG,
                    KronosSignalStrength.VERY_STRONG
                ] and decision.final_confidence >= 0.75:
                    strong_signals.append((symbol, decision))
        
        # 按置信度排序
        strong_signals.sort(key=lambda x: x[1].final_confidence, reverse=True)
        
        print(f"\n🎯 发现 {len(strong_signals)} 个强信号:")
        
        if strong_signals:
            print("-" * 90)
            print(f"{'排名':<4} {'交易对':<12} {'行动':<12} {'置信度':<8} {'强度':<8} {'一致性':<8} {'仓位':<8}")
            print("-" * 90)
            
            for i, (symbol, decision) in enumerate(strong_signals, 1):
                print(f"{i:<4} {symbol:<12} {decision.final_action:<12} "
                      f"{decision.final_confidence:.2f}    "
                      f"{decision.kronos_signal_strength.value:<8} "
                      f"{decision.signal_confluence:.2f}    "
                      f"{decision.position_size:.1%}")
            
            # 显示最佳机会的详细信息
            if strong_signals:
                print(f"\n🏆 最佳机会详情:")
                best_symbol, best_decision = strong_signals[0]
                print(f"   交易对: {best_symbol}")
                print(f"   行动: {best_decision.final_action}")
                print(f"   置信度: {best_decision.final_confidence:.2f}")
                print(f"   Kronos预测: {best_decision.kronos_prediction.predicted_price_change*100:+.2f}%" if best_decision.kronos_prediction else "N/A")
                print(f"   建议仓位: {best_decision.position_size:.1%}")
                print(f"   市场状态: {best_decision.market_regime.value}")
                print(f"   决策依据: {best_decision.reasoning}")
        else:
            print("⚠️ 当前市场条件下没有发现符合条件的强信号")
            print("💡 建议:")
            print("   - 降低置信度阈值重新搜索")
            print("   - 等待市场条件改善")
            print("   - 关注技术分析信号")
            
    except Exception as e:
        print(f"❌ 强信号检测失败: {e}")


async def demo_market_regime_analysis():
    """演示市场状态分析"""
    print("\n" + "="*60)
    print("🌊 市场状态分析演示")
    print("="*60)
    
    try:
        service = await get_kronos_integrated_service()
        
        # 主要市场指标交易对
        major_symbols = ["BTC-USDT", "ETH-USDT", "BNB-USDT"]
        
        print(f"📊 分析主要交易对的市场状态...")
        results = await service.batch_analyze_symbols(major_symbols, force_update=True)
        
        # 统计市场状态
        regime_stats = {}
        valid_results = [r for r in results.values() if r is not None]
        
        for decision in valid_results:
            regime = decision.market_regime.value
            if regime not in regime_stats:
                regime_stats[regime] = []
            regime_stats[regime].append(decision)
        
        print(f"\n📈 市场状态分布:")
        print("-" * 50)
        
        for regime, decisions in regime_stats.items():
            count = len(decisions)
            percentage = count / len(valid_results) * 100
            avg_confidence = sum(d.kronos_confidence for d in decisions) / count
            print(f"{regime:<15} {count}个 ({percentage:.1f}%) - 平均置信度: {avg_confidence:.2f}")
        
        # 确定主导市场状态
        if regime_stats:
            dominant_regime = max(regime_stats.items(), key=lambda x: len(x[1]))
            print(f"\n🎯 主导市场状态: {dominant_regime[0]}")
            
            # 根据市场状态给出建议
            regime_name = dominant_regime[0]
            if regime_name == "上涨趋势":
                print("💡 交易建议: 适合做多，关注回调买入机会")
            elif regime_name == "下跌趋势":
                print("💡 交易建议: 适合做空，关注反弹卖出机会")
            elif regime_name == "震荡整理":
                print("💡 交易建议: 区间交易，高抛低吸")
            elif regime_name == "高波动":
                print("💡 交易建议: 控制仓位，设置严格止损")
            elif regime_name == "平静":
                print("💡 交易建议: 等待突破信号，准备仓位")
        
        print(f"\n📋 详细分析:")
        print("-" * 70)
        print(f"{'交易对':<12} {'市场状态':<12} {'Kronos置信度':<12} {'最终行动':<12}")
        print("-" * 70)
        
        for symbol, decision in results.items():
            if decision:
                print(f"{symbol:<12} {decision.market_regime.value:<12} "
                      f"{decision.kronos_confidence:.2f}        "
                      f"{decision.final_action:<12}")
                
    except Exception as e:
        print(f"❌ 市场状态分析失败: {e}")


async def main():
    """主函数 - 运行所有演示"""
    print("🚀 Kronos前置集成决策系统演示")
    print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # 运行所有演示
        await demo_single_symbol_analysis()
        await demo_batch_analysis()
        await demo_strong_signals_detection()
        await demo_market_regime_analysis()
        
        print("\n" + "="*60)
        print("✅ 所有演示完成!")
        print("="*60)
        
        print("\n💡 Kronos前置集成的优势:")
        print("   🎯 将AI预测前置到所有决策流程")
        print("   🤝 多信号融合，提高决策准确性")
        print("   ⚡ 实时市场状态感知")
        print("   🛡️ 智能风险管理")
        print("   📊 全面的决策依据分析")
        
        print("\n🔧 使用建议:")
        print("   1. 优先关注强信号和高置信度决策")
        print("   2. 结合市场状态调整交易策略")
        print("   3. 严格执行风险管理参数")
        print("   4. 定期更新预测以获得最新信号")
        
    except Exception as e:
        print(f"❌ 演示运行失败: {e}")
        logger.error(f"Kronos集成演示失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())