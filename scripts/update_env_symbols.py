#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动更新.env文件中的币安币种配置
Auto update Binance symbols in .env file
"""

import asyncio
import sys
import os
import re

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.exchanges.exchange_service_manager import get_exchange_service
from app.core.logging import get_logger

logger = get_logger(__name__)


async def get_all_binance_swap_symbols():
    """获取币安所有永续合约币种"""
    try:
        exchange_service = await get_exchange_service()
        
        # 获取所有活跃的永续合约
        symbols = await exchange_service.get_active_symbols(inst_type='SWAP')
        
        # 过滤出USDT永续合约
        usdt_swaps = [symbol for symbol in symbols if symbol.endswith('-USDT-SWAP')]
        
        logger.info(f"获取到 {len(usdt_swaps)} 个USDT永续合约")
        
        # 按字母顺序排序
        usdt_swaps.sort()
        
        return usdt_swaps
        
    except Exception as e:
        logger.error(f"获取币安币种失败: {e}")
        return []


def update_env_file(symbols):
    """更新.env文件中的FUNDING_RATE_ONLY_SYMBOLS配置"""
    env_file_path = '.env'
    
    if not os.path.exists(env_file_path):
        print(f"❌ .env 文件不存在: {env_file_path}")
        return False
    
    try:
        # 读取现有的.env文件
        with open(env_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 获取主要监控币种，避免重复配置
        monitored_symbols = ['SOL-USDT-SWAP', 'ETH-USDT-SWAP']  # 从MONITORED_SYMBOLS获取
        
        # 从费率监控列表中排除主要监控币种
        filtered_symbols = [s for s in symbols if s not in monitored_symbols]
        
        print(f"📋 排除主要监控币种: {monitored_symbols}")
        print(f"📊 费率监控币种: {len(filtered_symbols)} 个 (原始: {len(symbols)} 个)")
        
        # 格式化新的币种列表
        symbols_str = '["' + '","'.join(filtered_symbols) + '"]'
        new_line = f'FUNDING_RATE_ONLY_SYMBOLS={symbols_str}'
        
        # 使用正则表达式替换现有的FUNDING_RATE_ONLY_SYMBOLS配置
        pattern = r'^FUNDING_RATE_ONLY_SYMBOLS=.*$'
        
        if re.search(pattern, content, re.MULTILINE):
            # 如果找到现有配置，则替换
            new_content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
            print("✅ 找到现有配置，正在更新...")
        else:
            # 如果没有找到，则添加到文件末尾
            new_content = content.rstrip() + '\n\n# 币安所有永续合约费率监控（排除主要监控币种）\n' + new_line + '\n'
            print("✅ 未找到现有配置，正在添加...")
        
        # 写回文件
        with open(env_file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"✅ 成功更新 {len(filtered_symbols)} 个币种到 .env 文件")
        return True
        
    except Exception as e:
        print(f"❌ 更新.env文件失败: {e}")
        return False


async def main():
    """主函数"""
    print("🚀 开始更新币安币种配置...")
    
    # 获取所有币种
    print("📡 正在从币安获取所有永续合约币种...")
    symbols = await get_all_binance_swap_symbols()
    
    if not symbols:
        print("❌ 获取币种失败，请检查网络连接和API配置")
        return
    
    print(f"✅ 成功获取 {len(symbols)} 个USDT永续合约")
    
    # 显示前10个币种作为预览
    print("\n📋 币种预览 (前10个):")
    for i, symbol in enumerate(symbols[:10]):
        print(f"  {i+1:2d}. {symbol}")
    
    if len(symbols) > 10:
        print(f"  ... 还有 {len(symbols) - 10} 个币种")
    
    # 更新.env文件
    print(f"\n📝 正在更新 .env 文件...")
    success = update_env_file(symbols)
    
    if success:
        print(f"\n🎉 配置更新完成！")
        print(f"   - 总共配置了 {len(symbols)} 个币种进行费率监控")
        print(f"   - 重启应用后新配置将生效")
        print(f"   - 这些币种将只监控费率，不进行完整技术分析")
    else:
        print(f"\n❌ 配置更新失败，请手动更新")


if __name__ == "__main__":
    asyncio.run(main())
