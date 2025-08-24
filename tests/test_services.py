#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务测试
Service tests
"""

import pytest
import asyncio
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.okx_service import OKXService
from app.services.negative_funding_monitor_service import NegativeFundingMonitorService


@pytest.mark.asyncio
async def test_okx_service_connection():
    """测试OKX服务连接"""
    okx_service = OKXService()
    
    # 测试获取币种列表
    symbols = await okx_service.get_active_symbols(inst_type='SWAP')
    
    assert len(symbols) > 0, "应该能获取到币种列表"
    assert 'ETH-USDT-SWAP' in symbols, "应该包含ETH-USDT-SWAP"
    
    print(f"✅ OKX服务连接测试通过，获取到 {len(symbols)} 个币种")


@pytest.mark.asyncio
async def test_funding_monitor_service():
    """测试负费率监控服务"""
    monitor = NegativeFundingMonitorService()
    
    # 测试获取热门币种
    hot_symbols = await monitor.get_top_volume_symbols(limit=5)
    
    assert len(hot_symbols) > 0, "应该能获取到热门币种"
    assert all(symbol.endswith('-USDT-SWAP') for symbol in hot_symbols), "应该都是USDT永续合约"
    
    print(f"✅ 负费率监控服务测试通过，获取到 {len(hot_symbols)} 个热门币种")


if __name__ == "__main__":
    asyncio.run(test_okx_service_connection())
    asyncio.run(test_funding_monitor_service())
    print("🎉 所有服务测试通过")