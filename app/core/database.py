# -*- coding: utf-8 -*-
"""
数据库连接和会话管理
Database connection and session management with connection pooling
"""

from sqlalchemy import create_engine, MetaData, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, scoped_session
from sqlalchemy.pool import QueuePool, StaticPool
from typing import Generator, Optional
from contextlib import contextmanager
import logging
import threading
from sqlalchemy.exc import DisconnectionError, OperationalError

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 数据库连接池配置
def get_database_config():
    """获取数据库连接池配置"""
    pool_config = settings.database_config["pool_config"]
    
    if "mysql" in settings.database_url:
        return {
            # MySQL连接池配置
            "poolclass": QueuePool,
            "pool_size": pool_config["pool_size"],
            "max_overflow": pool_config["max_overflow"],
            "pool_pre_ping": pool_config["pool_pre_ping"],
            "pool_recycle": pool_config["pool_recycle"],
            "pool_timeout": pool_config["pool_timeout"],
            "echo": settings.database_echo,
            "connect_args": {
                "charset": "utf8mb4",
                "autocommit": False,
                "connect_timeout": pool_config["connect_timeout"],
                "read_timeout": pool_config["read_timeout"],
                "write_timeout": pool_config["write_timeout"],
            }
        }
    else:
        # SQLite配置
        return {
            "poolclass": StaticPool,
            "pool_pre_ping": pool_config["pool_pre_ping"],
            "pool_recycle": pool_config["pool_recycle"],
            "echo": settings.database_echo,
            "connect_args": {"check_same_thread": False}
        }

# 创建数据库引擎 - 带故障转移
def create_database_engine():
    """创建数据库引擎，支持MySQL到SQLite的故障转移"""
    try:
        # 首先尝试使用配置的数据库URL
        engine = create_engine(
            settings.database_url,
            **get_database_config()
        )
        
        # 测试连接
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        logger.info(f"✅ Database engine created successfully: {settings.database_url.split('@')[0]}@***")
        return engine
        
    except Exception as e:
        logger.warning(f"⚠️ Primary database connection failed: {e}")
        
        # 如果主数据库连接失败，尝试使用SQLite作为后备
        if "mysql" in settings.database_url.lower():
            logger.info("🔄 Falling back to SQLite database...")
            try:
                sqlite_url = "sqlite:///./trading_data.db"
                sqlite_config = {
                    "poolclass": StaticPool,
                    "pool_pre_ping": True,
                    "pool_recycle": 3600,
                    "echo": settings.database_echo,
                    "connect_args": {"check_same_thread": False}
                }
                
                fallback_engine = create_engine(sqlite_url, **sqlite_config)
                
                # 测试SQLite连接
                with fallback_engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                
                logger.info("✅ SQLite fallback database connected successfully")
                return fallback_engine
                
            except Exception as sqlite_error:
                logger.error(f"❌ SQLite fallback also failed: {sqlite_error}")
                raise
        else:
            # 如果已经是SQLite或其他数据库，直接抛出异常
            raise

try:
    engine = create_database_engine()
except Exception as e:
    logger.error(f"❌ All database connections failed: {e}")
    logger.warning("⚠️ Application will run without database persistence")
    engine = None

# 添加连接池事件监听器
@event.listens_for(engine, "connect")
def set_mysql_pragma(dbapi_connection, connection_record):
    """设置MySQL连接参数"""
    if "mysql" in settings.database_url:
        with dbapi_connection.cursor() as cursor:
            # 设置会话级别的参数
            cursor.execute("SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO'")
            cursor.execute("SET SESSION time_zone = '+08:00'")

@event.listens_for(engine, "checkout")
def receive_checkout(dbapi_connection, connection_record, connection_proxy):
    """连接检出时的处理"""
    logger.debug("数据库连接已检出")

@event.listens_for(engine, "checkin")
def receive_checkin(dbapi_connection, connection_record):
    """连接检入时的处理"""
    logger.debug("数据库连接已检入")

# 创建线程安全的会话工厂
if engine:
    SessionLocal = scoped_session(
        sessionmaker(
            autocommit=False, 
            autoflush=False, 
            bind=engine,
            expire_on_commit=False  # 避免在commit后对象过期
        )
    )
else:
    SessionLocal = None

# 创建基础模型类
Base = declarative_base()

# 元数据
metadata = MetaData()


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话 - 使用连接池
    Dependency for getting database session with connection pooling
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()  # 自动提交成功的事务
    except Exception as e:
        logger.error(f"Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()
        # 清理scoped_session的线程本地存储
        SessionLocal.remove()

@contextmanager
def get_db_session():
    """
    上下文管理器方式获取数据库会话
    Context manager for database session
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()
        SessionLocal.remove()


def create_tables():
    """创建数据库表"""
    if not engine:
        logger.warning("⚠️ No database engine available, skipping table creation")
        return
        
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
    """数据库管理器 - 使用连接池"""
    
    def __init__(self):
        self.engine = engine
        self.session_factory = SessionLocal
        self._lock = threading.Lock()
        self.available = engine is not None and SessionLocal is not None
    
    def get_session(self) -> Session:
        """获取数据库会话"""
        if not self.available:
            raise RuntimeError("Database not available")
        return self.session_factory()
    
    @contextmanager
    def session_scope(self):
        """提供事务性会话作用域"""
        if not self.available:
            raise RuntimeError("Database not available")
            
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database transaction error: {e}")
            raise
        finally:
            session.close()
            self.session_factory.remove()
    
    def close_session(self, session: Session):
        """关闭数据库会话"""
        try:
            session.close()
            self.session_factory.remove()
        except Exception as e:
            logger.error(f"Error closing database session: {e}")
    
    def execute_query(self, query: str, params: dict = None):
        """执行查询 - 使用连接池"""
        with self.session_scope() as session:
            result = session.execute(text(query), params or {})
            return result
    
    def health_check(self) -> bool:
        """数据库健康检查"""
        if not self.available:
            return False
            
        try:
            with self.session_scope() as session:
                session.execute(text("SELECT 1"))
                return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
    
    def get_pool_status(self) -> dict:
        """获取连接池状态"""
        if not self.available or not self.engine:
            return {"status": "unavailable"}
            
        pool = self.engine.pool
        return {
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "invalid": pool.invalid()
        }
    
    def close_all_connections(self):
        """关闭所有连接"""
        if not self.available or not self.engine:
            logger.info("📊 No database connections to close")
            return
            
        try:
            self.engine.dispose()
            logger.info("所有数据库连接已关闭")
        except Exception as e:
            logger.error(f"关闭数据库连接时出错: {e}")
    
    def reconnect(self):
        """重新连接数据库"""
        try:
            self.close_all_connections()
            # 重新创建引擎
            global engine
            engine = create_engine(
                settings.database_url,
                **get_database_config()
            )
            self.engine = engine
            # 重新绑定session工厂
            self.session_factory.configure(bind=engine)
            logger.info("数据库重新连接成功")
        except Exception as e:
            logger.error(f"数据库重新连接失败: {e}")
            raise


# 创建数据库管理器实例
try:
    db_manager = DatabaseManager()
    if db_manager.available:
        logger.info("✅ Database manager initialized successfully")
    else:
        logger.warning("⚠️ Database manager initialized but database not available")
except Exception as e:
    logger.error(f"❌ Failed to create database manager: {e}")
    db_manager = None
