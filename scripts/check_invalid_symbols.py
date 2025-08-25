#!/usr/bin/env python3
"""
检查无效交易对的脚本
用于识别无法获取历史数据的交易对
"""

import asyncio
import aiohttp
from typing import List, Dict
import json

class SymbolChecker:
    """交易对有效性检查器"""
    
    def __init__(self):
        self.base_url = "https://www.okx.com/api/v5"
        self.session = None
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
    
    async def check_symbol(self, symbol: str) -> Dict[str, any]:
        """检查单个交易对是否有效"""
        try:
            # 转换格式：BTC-USDT-SWAP -> BTC-USDT-SWAP
            inst_id = symbol
            
            # 尝试获取K线数据
            url = f"{self.base_url}/market/candles"
            params = {
                'instId': inst_id,
                'bar': '1H',
                'limit': '1'
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('code') == '0' and data.get('data'):
                        return {
                            'symbol': symbol,
                            'status': 'valid',
                            'message': '可以获取数据'
                        }
                    else:
                        return {
                            'symbol': symbol,
                            'status': 'invalid',
                            'message': f"API返回错误: {data.get('msg', '未知错误')}"
                        }
                else:
                    return {
                        'symbol': symbol,
                        'status': 'invalid',
                        'message': f"HTTP错误: {response.status}"
                    }
                    
        except Exception as e:
            return {
                'symbol': symbol,
                'status': 'error',
                'message': f"请求异常: {str(e)}"
            }
    
    async def check_symbols_batch(self, symbols: List[str]) -> List[Dict[str, any]]:
        """批量检查交易对"""
        tasks = [self.check_symbol(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    'symbol': symbols[i],
                    'status': 'error',
                    'message': f"检查异常: {str(result)}"
                })
            else:
                processed_results.append(result)
        
        return processed_results

async def main():
    """主函数"""
    # 需要检查的交易对列表
    symbols_to_check = [
        # 一些可能有问题的老币种
        'REN-USDT-SWAP', 'KNC-USDT-SWAP', 'ZRX-USDT-SWAP', 'BAL-USDT-SWAP',
        'TFUEL-USDT-SWAP', 'SC-USDT-SWAP', 'STORJ-USDT-SWAP',
        'LOOKS-USDT-SWAP', 'SLERF-USDT-SWAP', 'MYRO-USDT-SWAP',
        
        # 一些新币种也检查一下
        'BOME-USDT-SWAP', 'WIF-USDT-SWAP', 'BONK-USDT-SWAP',
        'POPCAT-USDT-SWAP', 'FLOKI-USDT-SWAP',
        
        # 确认一些主流币种
        'BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP'
    ]
    
    print("🔍 开始检查交易对有效性...")
    print(f"📊 总共需要检查 {len(symbols_to_check)} 个交易对")
    print("-" * 60)
    
    async with SymbolChecker() as checker:
        results = await checker.check_symbols_batch(symbols_to_check)
    
    # 分类结果
    valid_symbols = []
    invalid_symbols = []
    error_symbols = []
    
    for result in results:
        if result['status'] == 'valid':
            valid_symbols.append(result)
        elif result['status'] == 'invalid':
            invalid_symbols.append(result)
        else:
            error_symbols.append(result)
    
    # 输出结果
    print(f"✅ 有效交易对 ({len(valid_symbols)}):")
    for result in valid_symbols:
        print(f"  {result['symbol']}: {result['message']}")
    
    print(f"\n❌ 无效交易对 ({len(invalid_symbols)}):")
    for result in invalid_symbols:
        print(f"  {result['symbol']}: {result['message']}")
    
    print(f"\n⚠️  检查异常 ({len(error_symbols)}):")
    for result in error_symbols:
        print(f"  {result['symbol']}: {result['message']}")
    
    # 生成清理建议
    if invalid_symbols:
        print("\n🧹 建议从配置中移除以下无效交易对:")
        invalid_list = [result['symbol'] for result in invalid_symbols]
        print(f"  {invalid_list}")
        
        # 生成配置清理代码
        print("\n📝 可以使用以下代码清理配置:")
        print("```python")
        print("# 在 app/core/config.py 中移除以下交易对:")
        for symbol in invalid_list:
            print(f"# '{symbol}',")
        print("```")

if __name__ == "__main__":
    asyncio.run(main())