#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
正确的SuperTrend指标实现
基于标准的SuperTrend算法
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any, Tuple
from app.core.logging import get_logger

logger = get_logger(__name__)


class CorrectSuperTrend:
    """正确的SuperTrend指标实现"""
    
    def __init__(self, atr_period: int = 10, multiplier: float = 3.0):
        self.atr_period = atr_period
        self.multiplier = multiplier
    
    def calculate_atr(self, high: np.array, low: np.array, close: np.array) -> np.array:
        """计算ATR (Average True Range)"""
        # True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
        tr1 = high - low
        tr2 = np.abs(high - np.roll(close, 1))
        tr3 = np.abs(low - np.roll(close, 1))
        
        # 第一个值特殊处理
        tr2[0] = high[0] - low[0]
        tr3[0] = high[0] - low[0]
        
        true_range = np.maximum(tr1, np.maximum(tr2, tr3))
        
        # 计算ATR (使用RMA - Wilder's smoothing)
        atr = np.zeros_like(true_range)
        atr[0] = true_range[0]
        
        for i in range(1, len(true_range)):
            atr[i] = (atr[i-1] * (self.atr_period - 1) + true_range[i]) / self.atr_period
        
        return atr
    
    def calculate(self, high: List[float], low: List[float], close: List[float]) -> Tuple[List[float], List[bool]]:
        """
        计算SuperTrend指标
        
        Args:
            high: 最高价列表
            low: 最低价列表  
            close: 收盘价列表
            
        Returns:
            Tuple[List[float], List[bool]]: (SuperTrend值列表, 趋势方向列表 - True为上涨)
        """
        try:
            if len(high) != len(low) or len(low) != len(close):
                raise ValueError("OHLC数据长度不一致")
            
            if len(high) < self.atr_period:
                raise ValueError(f"数据长度不足，需要至少{self.atr_period}个数据点")
            
            # 转换为numpy数组
            high_arr = np.array(high, dtype=float)
            low_arr = np.array(low, dtype=float)
            close_arr = np.array(close, dtype=float)
            
            # 计算ATR
            atr = self.calculate_atr(high_arr, low_arr, close_arr)
            
            # 计算HL2 (中位价)
            hl2 = (high_arr + low_arr) / 2
            
            # 计算基础上下轨
            upper_basic = hl2 + (self.multiplier * atr)
            lower_basic = hl2 - (self.multiplier * atr)
            
            # 计算最终上下轨
            upper_final = np.zeros_like(upper_basic)
            lower_final = np.zeros_like(lower_basic)
            
            # 初始化
            upper_final[0] = upper_basic[0]
            lower_final[0] = lower_basic[0]
            
            for i in range(1, len(close_arr)):
                # 上轨计算
                if upper_basic[i] < upper_final[i-1] or close_arr[i-1] > upper_final[i-1]:
                    upper_final[i] = upper_basic[i]
                else:
                    upper_final[i] = upper_final[i-1]
                
                # 下轨计算  
                if lower_basic[i] > lower_final[i-1] or close_arr[i-1] < lower_final[i-1]:
                    lower_final[i] = lower_basic[i]
                else:
                    lower_final[i] = lower_final[i-1]
            
            # 计算SuperTrend和趋势方向
            supertrend = np.zeros_like(close_arr)
            trend_up = np.zeros(len(close_arr), dtype=bool)
            
            # 初始化第一个值
            if close_arr[0] <= lower_final[0]:
                supertrend[0] = lower_final[0]
                trend_up[0] = True
            else:
                supertrend[0] = upper_final[0]
                trend_up[0] = False
            
            # 计算后续值
            for i in range(1, len(close_arr)):
                # SuperTrend趋势判断逻辑
                if trend_up[i-1]:
                    # 之前是上涨趋势
                    if close_arr[i] <= lower_final[i]:
                        # 价格跌破下轨，转为下跌趋势
                        supertrend[i] = upper_final[i]
                        trend_up[i] = False
                    else:
                        # 继续上涨趋势
                        supertrend[i] = lower_final[i]
                        trend_up[i] = True
                else:
                    # 之前是下跌趋势
                    if close_arr[i] >= upper_final[i]:
                        # 价格突破上轨，转为上涨趋势
                        supertrend[i] = lower_final[i]
                        trend_up[i] = True
                    else:
                        # 继续下跌趋势
                        supertrend[i] = upper_final[i]
                        trend_up[i] = False
            
            # 转换为列表
            supertrend_values = supertrend.tolist()
            trend_directions = trend_up.tolist()
            
            return supertrend_values, trend_directions
            
        except Exception as e:
            logger.error(f"SuperTrend calculation failed: {e}")
            raise
    
    def calculate_from_klines(self, klines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从K线数据计算SuperTrend"""
        try:
            if not klines:
                return []
            
            # 提取OHLC数据
            def get_price_field(kline, field_name):
                """智能获取价格字段"""
                if f'{field_name}_price' in kline:
                    return float(kline[f'{field_name}_price'])
                elif field_name in kline:
                    return float(kline[field_name])
                else:
                    for key in kline.keys():
                        if field_name.lower() in key.lower():
                            return float(kline[key])
                    raise KeyError(f"Cannot find {field_name} field in kline data")
            
            high = [get_price_field(k, 'high') for k in klines]
            low = [get_price_field(k, 'low') for k in klines]
            close = [get_price_field(k, 'close') for k in klines]
            
            # 计算SuperTrend
            supertrend_values, trend_directions = self.calculate(high, low, close)
            
            # 添加指标数据到K线
            result = []
            for i, kline in enumerate(klines):
                enriched_kline = kline.copy()
                enriched_kline['supertrend_value'] = supertrend_values[i]
                enriched_kline['supertrend_direction'] = 'up' if trend_directions[i] else 'down'
                result.append(enriched_kline)
            
            return result
            
        except Exception as e:
            logger.error(f"SuperTrend calculation from klines failed: {e}")
            raise


def test_supertrend():
    """测试SuperTrend计算"""
    # 模拟一些上涨的价格数据
    test_data = [
        {'high': 100, 'low': 95, 'close': 98},
        {'high': 102, 'low': 97, 'close': 101},
        {'high': 105, 'low': 100, 'close': 104},
        {'high': 107, 'low': 102, 'close': 106},
        {'high': 110, 'low': 105, 'close': 109},
        {'high': 112, 'low': 107, 'close': 111},
        {'high': 115, 'low': 110, 'close': 114},
        {'high': 117, 'low': 112, 'close': 116},
        {'high': 120, 'low': 115, 'close': 119},
        {'high': 122, 'low': 117, 'close': 121},
    ]
    
    st = CorrectSuperTrend(atr_period=5, multiplier=2.0)
    
    high = [d['high'] for d in test_data]
    low = [d['low'] for d in test_data]
    close = [d['close'] for d in test_data]
    
    supertrend_values, trend_directions = st.calculate(high, low, close)
    
    print("测试SuperTrend计算:")
    for i, (h, l, c, st_val, trend) in enumerate(zip(high, low, close, supertrend_values, trend_directions)):
        trend_str = "上涨" if trend else "下跌"
        print(f"第{i+1}根: H={h}, L={l}, C={c}, SuperTrend={st_val:.2f}, 趋势={trend_str}")


if __name__ == "__main__":
    test_supertrend()