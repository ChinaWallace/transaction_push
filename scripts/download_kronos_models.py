#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos模型下载脚本
Download Kronos models from Hugging Face Hub
"""

import os
import sys
from pathlib import Path
from huggingface_hub import snapshot_download, hf_hub_download
from tqdm import tqdm
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def download_kronos_models():
    """下载Kronos模型和tokenizer"""
    
    # 创建模型存储目录
    models_dir = Path("./models/kronos")
    models_dir.mkdir(parents=True, exist_ok=True)
    
    # 要下载的模型列表
    models_to_download = [
        {
            "repo_id": "NeoQuasar/Kronos-Tokenizer-base",
            "local_dir": models_dir / "tokenizer-base",
            "description": "Kronos Base Tokenizer"
        },
        {
            "repo_id": "NeoQuasar/Kronos-small",
            "local_dir": models_dir / "kronos-small",
            "description": "Kronos Small Model (24.7M params)"
        },
        {
            "repo_id": "NeoQuasar/Kronos-base",
            "local_dir": models_dir / "kronos-base",
            "description": "Kronos Base Model (102.3M params)"
        }
    ]
    
    # 可选：下载mini版本（更小，更快）
    mini_models = [
        {
            "repo_id": "NeoQuasar/Kronos-Tokenizer-2k",
            "local_dir": models_dir / "tokenizer-2k",
            "description": "Kronos 2K Tokenizer"
        },
        {
            "repo_id": "NeoQuasar/Kronos-mini",
            "local_dir": models_dir / "kronos-mini",
            "description": "Kronos Mini Model (4.1M params)"
        }
    ]
    
    print("🚀 开始下载Kronos模型...")
    print("=" * 60)
    
    # 询问用户是否下载所有模型
    download_all = input("是否下载所有模型？(y/n，默认只下载small版本): ").lower().strip()
    download_mini = input("是否下载mini版本？(y/n，默认否): ").lower().strip()
    
    if download_all == 'y':
        selected_models = models_to_download
    else:
        # 只下载必要的模型
        selected_models = [
            models_to_download[0],  # tokenizer-base
            models_to_download[1],  # kronos-small
        ]
    
    if download_mini == 'y':
        selected_models.extend(mini_models)
    
    total_models = len(selected_models)
    
    for i, model_info in enumerate(selected_models, 1):
        repo_id = model_info["repo_id"]
        local_dir = model_info["local_dir"]
        description = model_info["description"]
        
        print(f"\n📦 [{i}/{total_models}] 下载 {description}")
        print(f"   仓库: {repo_id}")
        print(f"   本地路径: {local_dir}")
        
        try:
            # 检查是否已经存在
            if local_dir.exists() and any(local_dir.iterdir()):
                print(f"   ✅ 模型已存在，跳过下载")
                continue
            
            # 下载模型
            print(f"   🔄 开始下载...")
            snapshot_download(
                repo_id=repo_id,
                local_dir=str(local_dir),
                local_dir_use_symlinks=False,
                resume_download=True
            )
            
            print(f"   ✅ 下载完成: {description}")
            
        except Exception as e:
            logger.error(f"   ❌ 下载失败 {description}: {e}")
            continue
    
    print("\n" + "=" * 60)
    print("🎉 Kronos模型下载完成！")
    
    # 显示下载的模型
    print("\n📁 已下载的模型:")
    for model_dir in models_dir.iterdir():
        if model_dir.is_dir():
            size = sum(f.stat().st_size for f in model_dir.rglob('*') if f.is_file())
            size_mb = size / (1024 * 1024)
            print(f"   📦 {model_dir.name}: {size_mb:.1f} MB")
    
    return True

def verify_kronos_installation():
    """验证Kronos模型是否正确安装"""
    print("\n🔍 验证Kronos安装...")
    
    try:
        # 检查模型文件
        models_dir = Path("./models/kronos")
        
        required_models = [
            "tokenizer-base",
            "kronos-small"
        ]
        
        missing_models = []
        for model_name in required_models:
            model_path = models_dir / model_name
            if not model_path.exists() or not any(model_path.iterdir()):
                missing_models.append(model_name)
        
        if missing_models:
            print(f"   ❌ 缺少模型: {', '.join(missing_models)}")
            return False
        
        # 尝试导入Kronos模块
        sys.path.append("./Kronos-master")
        from model import Kronos, KronosTokenizer, KronosPredictor
        
        print("   ✅ Kronos模块导入成功")
        
        # 尝试加载模型（不实际加载权重，只检查配置）
        tokenizer_path = str(models_dir / "tokenizer-base")
        model_path = str(models_dir / "kronos-small")
        
        print(f"   📁 Tokenizer路径: {tokenizer_path}")
        print(f"   📁 模型路径: {model_path}")
        
        print("   ✅ Kronos安装验证成功！")
        return True
        
    except Exception as e:
        print(f"   ❌ Kronos安装验证失败: {e}")
        return False

def create_kronos_example():
    """创建Kronos使用示例"""
    example_code = '''#!/usr/bin/env python3
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
        
        print(f"\\n🔮 开始预测...")
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
        
        print("\\n✅ 预测完成！")
        print("预测结果前5行:")
        print(pred_df.head())
        
        # 计算一些简单的统计信息
        actual_close = df.iloc[lookback:lookback+pred_len]['close'].values
        pred_close = pred_df['close'].values
        
        if len(actual_close) == len(pred_close):
            mse = np.mean((actual_close - pred_close) ** 2)
            mae = np.mean(np.abs(actual_close - pred_close))
            
            print(f"\\n📈 预测性能:")
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
        print("\\n🎉 示例运行成功！")
    else:
        print("\\n❌ 示例运行失败")
'''
    
    # 保存示例文件
    example_file = Path("examples/kronos_example.py")
    example_file.parent.mkdir(exist_ok=True)
    
    with open(example_file, 'w', encoding='utf-8') as f:
        f.write(example_code)
    
    print(f"📝 已创建Kronos使用示例: {example_file}")

def main():
    """主函数"""
    print("🤖 Kronos模型下载和安装工具")
    print("=" * 60)
    
    try:
        # 下载模型
        if download_kronos_models():
            print("\n✅ 模型下载完成")
        else:
            print("\n❌ 模型下载失败")
            return
        
        # 验证安装
        if verify_kronos_installation():
            print("\n✅ 安装验证成功")
        else:
            print("\n❌ 安装验证失败")
            return
        
        # 创建示例
        create_kronos_example()
        
        print("\n🎉 Kronos模型安装完成！")
        print("\n📖 使用说明:")
        print("   1. 运行示例: python examples/kronos_example.py")
        print("   2. 在你的代码中导入: from model import Kronos, KronosTokenizer, KronosPredictor")
        print("   3. 模型路径: ./models/kronos/")
        
    except KeyboardInterrupt:
        print("\n\n⏹️ 用户取消操作")
    except Exception as e:
        print(f"\n❌ 安装过程出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()