# -*- coding: utf-8 -*-
"""
简单的数据库字段映射测试
Simple database field mapping test
"""

import asyncio
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging import get_logger
from app.services.trading.trading_pair_service import TradingPairService

logger = get_logger(__name__)


async def test_database_mapping():
    """测试数据库字段映射"""
    logger.info("🔍 测试数据库字段映射...")
    
    try:
        service = TradingPairService()
        
        # 执行完整的交易对更新流程
        result = await service.fetch_and_update_trading_pairs()
        
        if result.get('success'):
            logger.info(f"✅ 数据库字段映射测试成功:")
            logger.info(f"   总交易对数: {result.get('total_instruments', 0)}")
            logger.info(f"   USDT永续合约: {result.get('usdt_pairs', 0)}")
            logger.info(f"   成功更新数量: {result.get('updated_count', 0)}")
            
            if result.get('updated_count', 0) > 0:
                logger.info("✅ 数据库写入成功，字段映射正常")
                return True
            else:
                logger.warning("⚠️ 数据库写入数量为0，可能存在字段映射问题")
                return False
        else:
            logger.error(f"❌ 数据库字段映射测试失败: {result.get('error')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ 测试异常: {e}")
        return False


async def main():
    """主函数"""
    logger.info("🚀 启动数据库字段映射测试...")
    
    success = await test_database_mapping()
    
    if success:
        logger.info("✅ 数据库字段映射测试通过")
        return 0
    else:
        logger.error("❌ 数据库字段映射测试失败")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("⚠️ 用户中断测试")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ 测试脚本执行异常: {e}")
        sys.exit(1)