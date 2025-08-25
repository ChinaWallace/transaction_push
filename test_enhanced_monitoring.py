#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试增强版监控功能
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta

def test_funding_rate_surge_detection():
    """测试负费率上升检测"""
    
    # 模拟NegativeFundingMonitorService的部分功能
    class MockFundingMonitor:
        def __init__(self):
            self.funding_rate_history = {}
            self.max_history_hours = 24
        
        def _update_funding_rate_history(self, symbol: str, funding_rate: float):
            """更新费率历史数据"""
            current_time = datetime.now()
            
            if symbol not in self.funding_rate_history:
                self.funding_rate_history[symbol] = []
            
            # 添加新数据点
            self.funding_rate_history[symbol].append((current_time, funding_rate))
            
            # 清理超过24小时的历史数据
            cutoff_time = current_time - timedelta(hours=self.max_history_hours)
            self.funding_rate_history[symbol] = [
                (timestamp, rate) for timestamp, rate in self.funding_rate_history[symbol]
                if timestamp > cutoff_time
            ]
        
        def _detect_funding_rate_surge(self, symbol: str, current_rate: float):
            """检测负费率显著上升"""
            if symbol not in self.funding_rate_history or len(self.funding_rate_history[symbol]) < 2:
                return {'is_surge': False, 'surge_info': ''}
            
            history = self.funding_rate_history[symbol]
            
            # 获取1小时前、2小时前、4小时前的费率
            current_time = datetime.now()
            rates_1h_ago = []
            rates_2h_ago = []
            rates_4h_ago = []
            
            for timestamp, rate in history:
                time_diff = (current_time - timestamp).total_seconds() / 3600
                
                if 0.8 <= time_diff <= 1.2:  # 1小时前 (±12分钟)
                    rates_1h_ago.append(rate)
                elif 1.8 <= time_diff <= 2.2:  # 2小时前
                    rates_2h_ago.append(rate)
                elif 3.8 <= time_diff <= 4.2:  # 4小时前
                    rates_4h_ago.append(rate)
            
            surge_info = ""
            is_surge = False
            
            # 检测1小时内的显著变化
            if rates_1h_ago and current_rate < 0:
                avg_1h_ago = sum(rates_1h_ago) / len(rates_1h_ago)
                rate_change_1h = abs(current_rate) - abs(avg_1h_ago)
                
                if rate_change_1h > 0.005:  # 负费率增加超过0.5%
                    surge_info += f"📈1h内负费率上升{rate_change_1h:.3%} "
                    is_surge = True
            
            # 检测2小时内的显著变化
            if rates_2h_ago and current_rate < 0:
                avg_2h_ago = sum(rates_2h_ago) / len(rates_2h_ago)
                rate_change_2h = abs(current_rate) - abs(avg_2h_ago)
                
                if rate_change_2h > 0.008:  # 2小时内负费率增加超过0.8%
                    surge_info += f"📈2h内负费率上升{rate_change_2h:.3%} "
                    is_surge = True
            
            # 检测4小时内的显著变化
            if rates_4h_ago and current_rate < 0:
                avg_4h_ago = sum(rates_4h_ago) / len(rates_4h_ago)
                rate_change_4h = abs(current_rate) - abs(avg_4h_ago)
                
                if rate_change_4h > 0.015:  # 4小时内负费率增加超过1.5%
                    surge_info += f"🚀4h内负费率大幅上升{rate_change_4h:.3%} "
                    is_surge = True
            
            return {
                'is_surge': is_surge,
                'surge_info': surge_info.strip(),
                'current_rate': current_rate,
                'rates_1h_ago': rates_1h_ago,
                'rates_2h_ago': rates_2h_ago,
                'rates_4h_ago': rates_4h_ago
            }
    
    # 测试场景
    monitor = MockFundingMonitor()
    symbol = "TEST-USDT-SWAP"
    
    print("=== 负费率上升检测测试 ===\n")
    
    # 场景1: 模拟4小时内负费率大幅上升
    print("📊 场景1: 4小时内负费率大幅上升")
    base_time = datetime.now()
    
    # 4小时前: -0.5%
    monitor.funding_rate_history[symbol] = [(base_time - timedelta(hours=4), -0.005)]
    # 2小时前: -0.8%
    monitor.funding_rate_history[symbol].append((base_time - timedelta(hours=2), -0.008))
    # 1小时前: -1.2%
    monitor.funding_rate_history[symbol].append((base_time - timedelta(hours=1), -0.012))
    # 现在: -2.5%
    current_rate = -0.025
    
    result = monitor._detect_funding_rate_surge(symbol, current_rate)
    print(f"   当前费率: {current_rate:.3%}")
    print(f"   检测结果: {'✅ 检测到上升' if result['is_surge'] else '❌ 未检测到上升'}")
    print(f"   上升信息: {result['surge_info']}")
    print()
    
    # 场景2: 模拟1小时内轻微上升
    print("📊 场景2: 1小时内轻微上升")
    monitor.funding_rate_history[symbol] = [(base_time - timedelta(hours=1), -0.003)]
    current_rate = -0.009  # 上升0.6%
    
    result = monitor._detect_funding_rate_surge(symbol, current_rate)
    print(f"   当前费率: {current_rate:.3%}")
    print(f"   检测结果: {'✅ 检测到上升' if result['is_surge'] else '❌ 未检测到上升'}")
    print(f"   上升信息: {result['surge_info']}")
    print()
    
    # 场景3: 模拟费率稳定
    print("📊 场景3: 费率稳定")
    monitor.funding_rate_history[symbol] = [
        (base_time - timedelta(hours=4), -0.008),
        (base_time - timedelta(hours=2), -0.007),
        (base_time - timedelta(hours=1), -0.008)
    ]
    current_rate = -0.008  # 基本无变化
    
    result = monitor._detect_funding_rate_surge(symbol, current_rate)
    print(f"   当前费率: {current_rate:.3%}")
    print(f"   检测结果: {'✅ 检测到上升' if result['is_surge'] else '❌ 未检测到上升'}")
    print(f"   上升信息: {result['surge_info'] if result['surge_info'] else '无显著变化'}")
    print()
    
    print("=== 测试总结 ===")
    print("✅ 新功能特点:")
    print("• 30分钟检查一次负费率 (原来1小时)")
    print("• 网格推荐1小时一次，筛选交易量大或涨幅50%的币种")
    print("• 自动检测负费率显著上升 (1h>0.5%, 2h>0.8%, 4h>1.5%)")
    print("• 负费率上升的币种优先显示并获得额外评分")
    print("• 通知消息中突出标注负费率上升趋势")

def test_grid_symbol_filtering():
    """测试网格交易币种筛选"""
    print("\n=== 网格交易币种筛选测试 ===")
    
    # 模拟市场数据
    mock_tickers = [
        {'instId': 'BTC-USDT-SWAP', 'volCcy24h': '50000000', 'chg': '0.02'},  # 高交易量，低涨幅
        {'instId': 'PEPE-USDT-SWAP', 'volCcy24h': '8000000', 'chg': '0.65'},  # 中等交易量，高涨幅
        {'instId': 'SHIB-USDT-SWAP', 'volCcy24h': '15000000', 'chg': '0.35'},  # 高交易量，中等涨幅
        {'instId': 'DOGE-USDT-SWAP', 'volCcy24h': '25000000', 'chg': '0.15'},  # 高交易量，中等涨幅
        {'instId': 'WIF-USDT-SWAP', 'volCcy24h': '3000000', 'chg': '0.80'},   # 低交易量，高涨幅
        {'instId': 'BONK-USDT-SWAP', 'volCcy24h': '12000000', 'chg': '0.45'}, # 中等交易量，中等涨幅
    ]
    
    # 模拟筛选逻辑
    hot_symbols = ['BTC-USDT-SWAP', 'PEPE-USDT-SWAP', 'SHIB-USDT-SWAP', 
                   'DOGE-USDT-SWAP', 'WIF-USDT-SWAP', 'BONK-USDT-SWAP']
    
    filtered_symbols = []
    for ticker in mock_tickers:
        symbol = ticker['instId']
        if symbol in hot_symbols:
            volume_24h = float(ticker['volCcy24h'])
            change_24h = abs(float(ticker['chg']))
            
            # 筛选条件：涨幅超过50% 或 交易量前10
            if change_24h > 0.50 or symbol in hot_symbols[:3]:  # 前3个作为交易量前10
                filtered_symbols.append({
                    'symbol': symbol,
                    'volume_24h': volume_24h,
                    'change_24h': change_24h,
                    'reason': '涨幅>50%' if change_24h > 0.50 else '交易量前10'
                })
    
    # 按涨幅和交易量排序
    filtered_symbols.sort(key=lambda x: x['change_24h'] + x['volume_24h']/10000000, reverse=True)
    
    print(f"📊 筛选出 {len(filtered_symbols)} 个高潜力币种:")
    for i, s in enumerate(filtered_symbols, 1):
        symbol_name = s['symbol'].replace('-USDT-SWAP', '')
        print(f"   {i}. {symbol_name}: 涨幅 {s['change_24h']:.1%}, 交易量 {s['volume_24h']/1000000:.1f}M ({s['reason']})")

if __name__ == "__main__":
    test_funding_rate_surge_detection()
    test_grid_symbol_filtering()