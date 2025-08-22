# -*- coding: utf-8 -*-
"""
Python Trading Analysis Tool - 主程序入口
Main entry point for the Python Trading Analysis Tool
"""

import uvicorn
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.core.logging import get_logger
from datetime import datetime
from app.core.database import create_tables, db_manager
from app.api import trend_router, monitor_router, notification_router
from app.services.scheduler_service import SchedulerService

# 获取配置和日志
settings = get_settings()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("🚀 Starting Python Trading Analysis Tool...")
    
    try:
        # 创建数据库表
        create_tables()
        logger.info("✅ Database tables created successfully")
        
        # 测试数据库连接
        if db_manager.health_check():
            logger.info("✅ Database connection healthy")
        else:
            logger.error("❌ Database connection failed")
        
        # 启动调度器
        scheduler = SchedulerService()
        await scheduler.start()
        logger.info("✅ Scheduler started successfully")
        
        # 将调度器实例存储到应用状态
        app.state.scheduler = scheduler
        
        logger.info("🎉 Application startup completed!")
        
        yield
        
    except Exception as e:
        logger.error(f"❌ Application startup failed: {e}")
        raise
    
    # 关闭时执行
    logger.info("🛑 Shutting down Python Trading Analysis Tool...")
    
    try:
        # 停止调度器
        if hasattr(app.state, 'scheduler'):
            await app.state.scheduler.stop()
            logger.info("✅ Scheduler stopped")
        
        logger.info("👋 Application shutdown completed!")
        
    except Exception as e:
        logger.error(f"❌ Application shutdown error: {e}")


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    
    app = FastAPI(
        title="Python Trading Analysis Tool",
        description="Python 交易分析工具 - 提供趋势分析、费率监控、持仓量变化监控等功能",
        version=settings.app_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan
    )
    
    # 添加CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else ["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 注册路由
    app.include_router(trend_router, prefix="/api/trend", tags=["趋势分析"])
    app.include_router(monitor_router, prefix="/api/monitor", tags=["监控服务"])
    app.include_router(notification_router, prefix="/api/notification", tags=["通知服务"])
    
    # 根路径
    @app.get("/", summary="根路径")
    async def root():
        return {
            "message": "Welcome to Python Trading Analysis Tool",
            "version": settings.app_version,
            "status": "running",
            "docs": "/docs" if settings.debug else "disabled"
        }
    
    # 健康检查
    @app.get("/health", summary="健康检查")
    async def health_check():
        try:
            # 检查数据库连接
            db_healthy = db_manager.health_check()
            
            # TODO: 检查币安API连接
            api_healthy = True  # 暂时设为True
            
            # 检查调度器状态
            scheduler_healthy = hasattr(app.state, 'scheduler') and app.state.scheduler.is_running()
            
            status = "healthy" if all([db_healthy, api_healthy, scheduler_healthy]) else "unhealthy"
            
            return {
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "checks": {
                    "database": "healthy" if db_healthy else "unhealthy",
                    "binance_api": "healthy" if api_healthy else "unhealthy", 
                    "scheduler": "healthy" if scheduler_healthy else "unhealthy"
                }
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            raise HTTPException(status_code=500, detail="Health check failed")
    
    return app


def main():
    """主函数"""
    try:
        logger.info(f"🚀 Starting server on {settings.host}:{settings.port}")
        logger.info(f"📋 Debug mode: {settings.debug}")
        logger.info(f"📊 Log level: {settings.log_level}")
        
        # 创建应用
        app = create_app()
        
        # 启动服务器
        if settings.debug:
            # 开发模式：使用import字符串以支持热重载
            uvicorn.run(
                "main:create_app",
                host=settings.host,
                port=settings.port,
                log_level=settings.log_level.lower(),
                reload=True,
                access_log=True,
                factory=True
            )
        else:
            # 生产模式：直接传递app对象
            uvicorn.run(
                app,
                host=settings.host,
                port=settings.port,
                log_level=settings.log_level.lower(),
                access_log=True
            )
        
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped by user")
    except Exception as e:
        logger.error(f"❌ Server startup failed: {e}")
        raise


if __name__ == "__main__":
    main()
