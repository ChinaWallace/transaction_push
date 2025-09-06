#!/usr/bin/env python3
"""
验证交易对有效性的脚本
使用现有的OKX服务来检查配置中的交易对是否有效
"""

import asyncio
import sys
import os
from typing import List, Dict, Set

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.exchanges.exchange_service_manager import get_exchange_service
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class SymbolValidator:
    """交易对验证器"""
    
    def __init__(self):
        self.settings = get_settings()
        self.exchange_service = None  # 将在需要时异步初始化
    
    async def validate_symbol(self, symbol: str) -> Dict[str, any]:
        """验证单个交易对"""
        try:
            # 确保交易所服务已初始化
            if self.exchange_service is None:
                self.exchange_service = await get_exchange_service()
            
            # 尝试获取1小时K线数据，只要1条
            async with self.exchange_service as exchange:
                klines = await exchange.get_kline_data(symbol, '1H', limit=1)
                
                if klines and len(klines) > 0:
                    return {
                        'symbol': symbol,
                        'status': 'valid',
                        'message': f'成功获取数据，最新价格: {klines[0][4]}'
                    }
                else:
                    return {
                        'symbol': symbol,
                        'status': 'invalid',
                        'message': '无法获取K线数据'
                    }
                    
        except Exception as e:
            return {
                'symbol': symbol,
                'status': 'error',
                'message': f'验证异常: {str(e)}'
            }
    
    async def validate_symbols_batch(self, symbols: List[str], batch_size: int = 5) -> List[Dict[str, any]]:
        """批量验证交易对，使用小批次避免频率限制"""
        results = []
        
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            print(f"🔍 验证批次 {i//batch_size + 1}: {batch}")
            
            # 并发验证当前批次
            tasks = [self.validate_symbol(symbol) for symbol in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            for j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    results.append({
                        'symbol': batch[j],
                        'status': 'error',
                        'message': f'验证异常: {str(result)}'
                    })
                else:
                    results.append(result)
            
            # 批次间等待，避免频率限制
            if i + batch_size < len(symbols):
                await asyncio.sleep(2)
        
        return results
    
    def get_all_configured_symbols(self) -> Set[str]:
        """获取配置中的所有交易对"""
        symbols = set()
        
        # 主要监控币种
        symbols.update(self.settings.monitored_symbols)
        
        # 费率监控币种
        symbols.update(self.settings.funding_rate_only_symbols)
        
        return symbols

async def main():
    """主函数"""
    print("🚀 开始验证配置中的交易对...")
    
    validator = SymbolValidator()
    
    # 获取所有配置的交易对
    all_symbols = validator.get_all_configured_symbols()
    symbols_list = sorted(list(all_symbols))
    
    print(f"📊 总共需要验证 {len(symbols_list)} 个交易对")
    print("-" * 80)
    
    # 批量验证
    results = await validator.validate_symbols_batch(symbols_list, batch_size=3)
    
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
    print("\n" + "="*80)
    print(f"✅ 有效交易对 ({len(valid_symbols)}):")
    for result in valid_symbols:
        print(f"  {result['symbol']:<20} - {result['message']}")
    
    print(f"\n❌ 无效交易对 ({len(invalid_symbols)}):")
    for result in invalid_symbols:
        print(f"  {result['symbol']:<20} - {result['message']}")
    
    print(f"\n⚠️  验证异常 ({len(error_symbols)}):")
    for result in error_symbols:
        print(f"  {result['symbol']:<20} - {result['message']}")
    
    # 生成清理建议
    if invalid_symbols:
        print("\n" + "="*80)
        print("🧹 建议清理的无效交易对:")
        invalid_list = [result['symbol'] for result in invalid_symbols]
        
        print("\n📝 需要从以下配置中移除:")
        print("app/core/config.py:")
        print("  - funding_rate_only_symbols 列表")
        print("  - monitored_symbols 列表")
        
        print("\napp/services/kronos_market_opportunity_service.py:")
        print("  - main_symbols 列表")
        
        print(f"\n🗑️  要移除的交易对: {invalid_list}")
        
        # 生成具体的清理命令
        print("\n💡 可以使用以下Python代码片段来清理:")
        print("```python")
        print("# 要移除的无效交易对")
        print(f"invalid_symbols = {invalid_list}")
        print("# 从配置列表中移除这些交易对")
        print("```")
    
    # 统计信息
    print(f"\n📈 验证统计:")
    print(f"  总数: {len(results)}")
    print(f"  有效: {len(valid_symbols)} ({len(valid_symbols)/len(results)*100:.1f}%)")
    print(f"  无效: {len(invalid_symbols)} ({len(invalid_symbols)/len(results)*100:.1f}%)")
    print(f"  异常: {len(error_symbols)} ({len(error_symbols)/len(results)*100:.1f}%)")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  验证被用户中断")
    except Exception as e:
        print(f"\n💥 验证过程出现异常: {e}")
        logger.error(f"验证脚本异常: {e}", exc_info=True)