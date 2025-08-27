#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试增强的交易信号分析
Enhanced Trading Signal Analysis Test
"""

import asyncio
import sys
import os
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.core_trading_service import get_core_trading_service, AnalysisType
from app.core.logging import get_logger

logger = get_logger(__name__)


def format_trading_signal_notification(signal_data: dict) -> str:
    """
    格式化交易信号通知 - 增强版
    
    Args:
        signal_data: 信号数据
    
    Returns:
        str: 格式化的通知消息
    """
    symbol = signal_data['symbol']
    action = signal_data['action']
    confidence = signal_data['confidence']
    
    # 信号emoji映射
    signal_emoji = {
        '强烈买入': '🚀',
        '买入': '📈',
        '持有': '⏸️',
        '观望': '👀',
        '卖出': '📉',
        '强烈卖出': '🔻'
    }
    
    # 紧急程度emoji
    urgency_emoji = {
        'immediate': '🔥',
        'urgent': '⚡',
        'normal': '📊',
        'low': '💤'
    }
    
    # 构建消息
    message = f"""
{urgency_emoji.get(signal_data.get('urgency', 'normal'), '📊')} 🎯 {symbol} 交易信号

📊 交易动作: {action}
🎲 置信度: {confidence:.1%}
💰 当前价格: ${signal_data.get('current_price', 0):.4f}
🛡️ 止损价格: ${signal_data.get('stop_loss', 0):.4f}
🎯 止盈价格: ${signal_data.get('take_profit', 0):.4f}

⏰ 信号时间: {signal_data.get('timestamp', datetime.now()).strftime('%H:%M:%S')}

📈 分析理由: {signal_data.get('reasoning', 'N/A')}

🔍 关键因素:
{chr(10).join([f"  • {factor}" for factor in signal_data.get('key_factors', [])])}

📊 技术分析详情: {signal_data.get('technical_summary', '基础分析')}

⏱️ 交易建议:
  • 交易周期: {signal_data.get('trading_timeframe', 'N/A')}
  • 持有时间: {signal_data.get('holding_period', 'N/A')}
  • 入场时机: {signal_data.get('optimal_entry_time', 'N/A')}

🎯 置信度分解:
{chr(10).join([f"  • {k}: {v:.1%}" for k, v in signal_data.get('confidence_breakdown', {}).items()])}
"""
    
    return message.strip()


async def test_enhanced_trading_signal():
    """测试增强的交易信号分析"""
    
    print("🚀 开始测试增强的交易信号分析...")
    
    try:
        # 获取核心交易服务
        trading_service = await get_core_trading_service()
        
        # 测试ETH-USDT-SWAP信号分析
        symbol = "ETH-USDT-SWAP"
        print(f"\n📊 分析 {symbol} 交易信号...")
        
        # 执行综合分析
        signal = await trading_service.analyze_trading_signal(
            symbol=symbol,
            analysis_type=AnalysisType.INTEGRATED,
            force_update=True
        )
        
        if signal:
            print(f"✅ 信号分析完成!")
            print(f"📈 交易动作: {signal.final_action}")
            print(f"🎯 置信度: {signal.final_confidence:.1%}")
            print(f"💪 信号强度: {signal.signal_strength.value}")
            print(f"⏱️ 交易周期: {signal.trading_timeframe}")
            print(f"🕐 持有时间: {signal.holding_period}")
            print(f"⚡ 入场时机: {signal.optimal_entry_time}")
            
            # 显示详细分析
            print(f"\n🔍 分析详情:")
            print(f"理由: {signal.reasoning}")
            
            if signal.key_factors:
                print(f"\n关键因素:")
                for factor in signal.key_factors:
                    print(f"  • {factor}")
            
            if signal.confidence_breakdown:
                print(f"\n置信度分解:")
                for source, conf in signal.confidence_breakdown.items():
                    print(f"  • {source}: {conf:.1%}")
            
            if signal.technical_indicators:
                print(f"\n📊 技术指标详情:")
                
                # MA分析
                if 'moving_averages' in signal.technical_indicators:
                    ma_info = signal.technical_indicators['moving_averages']
                    print(f"  MA趋势: {ma_info.get('trend', 'N/A')}")
                    print(f"  价格相对MA20: {ma_info.get('price_vs_ma20', 0):.1f}%")
                
                # RSI分析
                if 'rsi' in signal.technical_indicators:
                    rsi_info = signal.technical_indicators['rsi']
                    print(f"  RSI: {rsi_info.get('value', 0):.1f} ({rsi_info.get('signal', 'N/A')})")
                
                # 布林带分析
                if 'bollinger_bands' in signal.technical_indicators:
                    bb_info = signal.technical_indicators['bollinger_bands']
                    print(f"  布林带: {bb_info.get('position', 'N/A')} ({bb_info.get('signal', 'N/A')})")
                
                # MACD分析
                if 'macd' in signal.technical_indicators:
                    macd_info = signal.technical_indicators['macd']
                    print(f"  MACD: {macd_info.get('trend', 'N/A')}")
                
                # SuperTrend分析
                if 'supertrend' in signal.technical_indicators:
                    st_info = signal.technical_indicators['supertrend']
                    print(f"  SuperTrend: {st_info.get('strength', 'N/A')}")
                    print(f"  多周期信号: {st_info.get('signals', {})}")
            
            # 生成通知格式
            print(f"\n📱 通知格式预览:")
            print("=" * 50)
            
            signal_data = {
                'symbol': signal.symbol,
                'action': signal.final_action,
                'confidence': signal.final_confidence,
                'current_price': signal.entry_price,
                'stop_loss': signal.stop_loss_price,
                'take_profit': signal.take_profit_price,
                'reasoning': signal.reasoning,
                'key_factors': signal.key_factors,
                'urgency': signal.urgency,
                'timestamp': signal.timestamp,
                'technical_summary': trading_service._build_technical_summary(signal.technical_indicators),
                'trading_timeframe': signal.trading_timeframe,
                'holding_period': signal.holding_period,
                'optimal_entry_time': signal.optimal_entry_time,
                'confidence_breakdown': signal.confidence_breakdown,
                'signal_strength': signal.signal_strength.value
            }
            
            notification_text = format_trading_signal_notification(signal_data)
            print(notification_text)
            print("=" * 50)
            
        else:
            print("❌ 未能生成有效信号")
        
        # 测试SOL-USDT-SWAP
        print(f"\n📊 分析 SOL-USDT-SWAP 交易信号...")
        
        sol_signal = await trading_service.analyze_trading_signal(
            symbol="SOL-USDT-SWAP",
            analysis_type=AnalysisType.INTEGRATED,
            force_update=True
        )
        
        if sol_signal:
            print(f"✅ SOL信号: {sol_signal.final_action} (置信度: {sol_signal.final_confidence:.1%})")
            print(f"⏱️ 交易建议: {sol_signal.trading_timeframe} - {sol_signal.holding_period}")
        
        print(f"\n🎉 测试完成!")
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        print(f"❌ 测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(test_enhanced_trading_signal())