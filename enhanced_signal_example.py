#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强交易信号示例
Enhanced Trading Signal Example - 展示优化后的交易信号格式
"""

from datetime import datetime


def create_enhanced_signal_example():
    """创建增强交易信号示例"""
    
    # 模拟一个强烈卖出信号
    signal_data = {
        'symbol': 'ETH-USDT-SWAP',
        'action': '强烈卖出',
        'confidence': 0.80,  # 80%置信度
        'current_price': 4513.68,
        'stop_loss': 4602.75,
        'take_profit': 4241.75,
        'urgency': 'urgent',
        'timestamp': datetime.now(),
        
        # Kronos分析
        'kronos_confidence': 0.49,
        'kronos_strength': '谨慎观望',
        
        # 技术分析详情
        'technical_confidence': 0.80,
        'technical_summary': 'MA空头排列(偏离MA20: -1.7%) | 布林带下轨附近(超卖) | RSI39(正常) | MACD空头 | SuperTrend强势多头共振 | 成交量缩量(0.3倍)',
        
        # ML预测
        'ml_confidence': 0.55,
        'ml_signal': '持有',
        
        # 交易时间建议
        'trading_timeframe': '日内',
        'holding_period': '2-6小时',
        'optimal_entry_time': '15分钟内',
        
        # 关键因素
        'key_factors': [
            'Kronos强度: 谨慎观望',
            '技术分析: 强烈卖出',
            'ML信号: 持有',
            'SuperTrend多周期共振',
            '布林带超卖区域',
            'MACD空头排列'
        ],
        
        # 置信度分解
        'confidence_breakdown': {
            'kronos': 0.49,
            'technical': 0.80,
            'ml': 0.55,
            'position': 0.50
        },
        
        # 分析理由
        'reasoning': 'Kronos预测: 谨慎观望 (置信度: 0.49) | 技术分析: 强烈卖出 (置信度: 80.00) [MA空头排列, 布林带超卖, RSI正常, MACD空头, SuperTrend共振] | ML预测: 持有 (置信度: 0.55)'
    }
    
    return signal_data


def format_enhanced_notification(signal_data: dict) -> str:
    """
    格式化增强版交易信号通知
    
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
    
    # 交易周期emoji
    timeframe_emoji = {
        '超短线': '⚡',
        '日内': '🕐',
        '短线': '📅',
        '波段': '📈',
        '观望': '👀'
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

📈 分析理由: {signal_data.get('reasoning', 'N/A')}...

🔍 关键因素:
{chr(10).join([f"  • {factor}" for factor in signal_data.get('key_factors', [])])}

📊 技术分析详情: {signal_data.get('technical_summary', '基础分析')}

⏱️ 交易建议:
  • 交易周期: {timeframe_emoji.get(signal_data.get('trading_timeframe', '观望'), '📊')} {signal_data.get('trading_timeframe', 'N/A')}
  • 持有时间: {signal_data.get('holding_period', 'N/A')}
  • 入场时机: {signal_data.get('optimal_entry_time', 'N/A')}

🎯 置信度分解:
  • Kronos AI: {signal_data.get('confidence_breakdown', {}).get('kronos', 0):.1%} (权重55%)
  • 技术分析: {signal_data.get('confidence_breakdown', {}).get('technical', 0):.1%} (权重25%)
  • ML预测: {signal_data.get('confidence_breakdown', {}).get('ml', 0):.1%} (权重15%)
  • 持仓分析: {signal_data.get('confidence_breakdown', {}).get('position', 0):.1%} (权重5%)

💡 操作建议:
  • 风险控制: 严格执行止损，单笔风险不超过2%
  • 仓位管理: 根据置信度调整仓位大小
  • 时机把握: {signal_data.get('optimal_entry_time', '等待合适时机')}
"""
    
    return message.strip()


if __name__ == "__main__":
    print("🎯 增强交易信号示例")
    print("=" * 60)
    
    # 创建示例信号
    signal_data = create_enhanced_signal_example()
    
    # 格式化通知
    notification = format_enhanced_notification(signal_data)
    
    print(notification)
    print("=" * 60)
    
    print("\n✨ 优化亮点:")
    print("1. 🎯 加重Kronos权重至55%，提升AI预测影响力")
    print("2. 📊 详细技术分析：MA、布林带、RSI、MACD、SuperTrend")
    print("3. ⏱️ 交易时间建议：周期、持有时间、入场时机")
    print("4. 🔍 置信度分解：各模块权重和贡献度透明化")
    print("5. 💡 操作建议：风险控制和仓位管理指导")
    print("6. 📈 多维度分析：技术面+基本面+AI预测综合判断")