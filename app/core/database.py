# -*- coding: utf-8 -*-
"""
数据库连接和会话管理
Database connection and session management
"""

from sqlalchemy import create_engine, MetaData
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from typing import Generator
import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 创建数据库引擎
engine = create_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "charset": "utf8mb4",
        "autocommit": False
    } if "mysql" in settings.database_url else {}
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建基础模型类
Base = declarative_base()

# 元数据
metadata = MetaData()


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话
    Dependency for getting database session
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def create_tables():
    """创建数据库表"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        raise


def drop_tables():
    """删除数据库表"""
    try:
        Base.metadata.drop_all(bind=engine)
        logger.info("Database tables dropped successfully")
    except Exception as e:
        logger.error(f"Error dropping database tables: {e}")
        raise


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self):
        self.engine = engine
        self.session = SessionLocal
    
    def get_session(self) -> Session:
        """获取数据库会话"""
        return self.session()
    
    def close_session(self, session: Session):
        """关闭数据库会话"""
        try:
            session.close()
        except Exception as e:
            logger.error(f"Error closing database session: {e}")
    
    def execute_query(self, query: str, params: dict = None):
        """执行查询"""
        session = self.get_session()
        try:
            result = session.execute(query, params or {})
            session.commit()
            return result
        except Exception as e:
            session.rollback()
            logger.error(f"Error executing query: {e}")
            raise
        finally:
            self.close_session(session)
    
    def health_check(self) -> bool:
        """数据库健康检查"""
        try:
            session = self.get_session()
            session.execute("SELECT 1")
            self.close_session(session)
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False


# 创建数据库管理器实例
db_manager = DatabaseManager()
