#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置测试
Configuration tests
"""

import pytest
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings


def test_config_loading():
    """测试配置加载"""
    settings = get_settings()
    
    # 检查基本配置
    assert settings is not None
    assert hasattr(settings, 'monitored_symbols')
    assert hasattr(settings, 'funding_rate_only_symbols')
    
    # 检查监控币种配置
    assert len(settings.monitored_symbols) > 0
    assert isinstance(settings.monitored_symbols, list)
    
    print(f"✅ 配置加载测试通过")
    print(f"   主要监控币种: {len(settings.monitored_symbols)} 个")
    print(f"   费率监控币种: {len(settings.funding_rate_only_symbols)} 个")


def test_no_duplicate_symbols():
    """测试无重复币种配置"""
    settings = get_settings()
    
    # 检查是否有重复
    all_symbols = set(settings.monitored_symbols + settings.funding_rate_only_symbols)
    total_configured = len(settings.monitored_symbols) + len(settings.funding_rate_only_symbols)
    
    assert len(all_symbols) == total_configured, "发现重复币种配置"
    
    print(f"✅ 无重复币种配置测试通过")


if __name__ == "__main__":
    test_config_loading()
    test_no_duplicate_symbols()
    print("🎉 所有配置测试通过")