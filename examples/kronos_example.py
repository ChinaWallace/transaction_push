#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos模型使用示例
Example usage of Kronos model for financial prediction
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path

# 添加Kronos模块路径
sys.path.append("./Kronos-master")

def load_kronos_model():
    """加载Kronos模型和tokenizer"""
    from model import Kronos, KronosTokenizer, KronosPredictor
    
    # 模型路径
    tokenizer_path = "./models/kronos/tokenizer-base"
    model_path = "./models/kronos/kronos-small"
    
    print("🤖 加载Kronos模型...")
    
    # 加载tokenizer和模型
    tokenizer = KronosTokenizer.from_pretrained(tokenizer_path)
    model = Kronos.from_pretrained(model_path)
    
    # 创建预测器
    predictor = KronosPredictor(
        model=model, 
        tokenizer=tokenizer, 
        device="cpu",  # 使用CPU，如果有GPU可以改为"cuda:0"
        max_context=512
    )
    
    print("✅ Kronos模型加载成功！")
    return predictor

def create_sample_data():
    """创建示例K线数据"""
    # 生成模拟的K线数据
    np.random.seed(42)
    
    # 生成100个时间点的数据
    n_points = 100
    base_price = 50000  # 基础价格（类似BTC）
    
    # 生成价格序列
    price_changes = np.random.normal(0, 0.02, n_points)  # 2%的日波动
    prices = [base_price]
    
    for change in price_changes[1:]:
        new_price = prices[-1] * (1 + change)
        prices.append(new_price)
    
    # 生成OHLCV数据
    data = []
    for i, close_price in enumerate(prices):
        # 生成开盘价（基于前一个收盘价）
        if i == 0:
            open_price = close_price
        else:
            open_price = prices[i-1]
        
        # 生成高低价
        high_price = max(open_price, close_price) * (1 + abs(np.random.normal(0, 0.01)))
        low_price = min(open_price, close_price) * (1 - abs(np.random.normal(0, 0.01)))
        
        # 生成成交量
        volume = np.random.uniform(1000, 10000)
        amount = volume * close_price
        
        data.append({
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume,
            'amount': amount
        })
    
    # 创建DataFrame
    df = pd.DataFrame(data)
    
    # 创建时间戳
    timestamps = pd.date_range(start='2024-01-01', periods=n_points, freq='1H')
    
    return df, timestamps

def predict_with_kronos():
    """使用Kronos进行预测"""
    try:
        # 加载模型
        predictor = load_kronos_model()
        
        # 创建示例数据
        df, timestamps = create_sample_data()
        
        print(f"📊 示例数据形状: {df.shape}")
        print("前5行数据:")
        print(df.head())
        
        # 设置预测参数
        lookback = 80  # 使用80个历史点
        pred_len = 20  # 预测20个未来点
        
        # 准备输入数据
        x_df = df.iloc[:lookback][['open', 'high', 'low', 'close', 'volume', 'amount']]
        x_timestamp = timestamps[:lookback]
        y_timestamp = timestamps[lookback:lookback+pred_len]
        
        print(f"\n🔮 开始预测...")
        print(f"   历史数据长度: {len(x_df)}")
        print(f"   预测长度: {pred_len}")
        
        # 执行预测
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=pred_len,
            T=1.0,          # 温度参数
            top_p=0.9,      # 核采样概率
            sample_count=1  # 采样次数
        )
        
        print("\n✅ 预测完成！")
        print("预测结果前5行:")
        print(pred_df.head())
        
        # 计算一些简单的统计信息
        actual_close = df.iloc[lookback:lookback+pred_len]['close'].values
        pred_close = pred_df['close'].values
        
        if len(actual_close) == len(pred_close):
            mse = np.mean((actual_close - pred_close) ** 2)
            mae = np.mean(np.abs(actual_close - pred_close))
            
            print(f"\n📈 预测性能:")
            print(f"   均方误差 (MSE): {mse:.2f}")
            print(f"   平均绝对误差 (MAE): {mae:.2f}")
        
        return pred_df
        
    except Exception as e:
        print(f"❌ 预测失败: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    print("🚀 Kronos模型预测示例")
    print("=" * 50)
    
    # 执行预测
    result = predict_with_kronos()
    
    if result is not None:
        print("\n🎉 示例运行成功！")
    else:
        print("\n❌ 示例运行失败")
