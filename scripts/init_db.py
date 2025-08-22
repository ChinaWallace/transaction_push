# -*- coding: utf-8 -*-
"""
数据库初始化脚本
Database initialization script
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import create_tables, db_manager
from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)
settings = get_settings()


def init_database():
    """初始化数据库"""
    try:
        logger.info("🚀 Starting database initialization...")
        
        # 测试数据库连接
        if not db_manager.health_check():
            logger.error("❌ Database connection failed")
            return False
        
        logger.info("✅ Database connection successful")
        
        # 创建数据库表
        create_tables()
        logger.info("✅ Database tables created successfully")
        
        logger.info("🎉 Database initialization completed!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        return False


if __name__ == "__main__":
    success = init_database()
    sys.exit(0 if success else 1)
