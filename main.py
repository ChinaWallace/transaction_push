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
from app.api.tradingview import router as tradingview_router
from app.api.strategy import router as strategy_router
from app.api.ml_enhanced import router as ml_enhanced_router
from app.api.trading_decision import router as trading_decision_router
from app.api.comprehensive_trading import router as comprehensive_trading_router
from app.api.trading_advice import router as trading_advice_router
from app.api.strategy_trading import router as strategy_trading_router
from app.api.enhanced_trading_advice import router as enhanced_trading_advice_router
from app.api.ml_strategy_optimization import router as ml_strategy_optimization_router
from app.services.scheduler_service import SchedulerService
from app.services.ml_enhanced_service import MLEnhancedService
from app.services.ml_notification_service import MLNotificationService

# 获取配置和日志
settings = get_settings()
logger = get_logger(__name__)


async def perform_startup_trading_analysis():
    """启动时执行交易分析和推送"""
    try:
        logger.info("🎯 开始启动交易决策分析...")
        
        # 导入启动交易服务
        from app.services.startup_trading_service import StartupTradingService
        startup_service = StartupTradingService()
        
        # 执行启动分析
        analysis_results = await startup_service.perform_startup_analysis()
        
        # 记录分析结果
        if analysis_results.get("status") == "disabled":
            logger.info("📴 启动交易推送已禁用")
        elif analysis_results.get("status") == "error":
            logger.error(f"❌ 启动交易分析失败: {analysis_results.get('error')}")
        else:
            successful = analysis_results.get("successful_analyses", 0)
            total = analysis_results.get("total_analyzed", 0)
            notifications = analysis_results.get("notifications_sent", 0)
            strong_signals = len(analysis_results.get("strong_signals", []))
            
            logger.info(f"✅ 启动交易分析完成:")
            logger.info(f"   📊 分析成功: {successful}/{total}")
            logger.info(f"   📢 通知发送: {notifications} 条")
            logger.info(f"   🔥 强信号: {strong_signals} 个")
            
            # 如果有强信号，记录详情
            for signal in analysis_results.get("strong_signals", [])[:3]:
                symbol = signal.get("symbol", "unknown")
                action = signal.get("action", "unknown")
                confidence = signal.get("confidence", 0)
                logger.info(f"   🚀 {symbol}: {action} ({confidence:.1f}%)")
        
        return analysis_results
        
    except Exception as e:
        logger.error(f"❌ 启动交易分析失败: {e}")
        return {"status": "error", "error": str(e)}


async def perform_startup_ml_analysis(ml_service: MLEnhancedService):
    """启动时执行ML分析和推送（可选）"""
    try:
        logger.info("🤖 开始ML增强分析...")
        ml_notification_service = MLNotificationService()
        
        # 分析配置中的所有交易对（现在只有ETH和SOL）
        symbols_to_analyze = settings.monitored_symbols
        anomaly_alerts_sent = 0  # 限制异常警报数量
        max_anomaly_alerts = 1   # 最多发送1个异常警报
        
        for symbol in symbols_to_analyze:
            try:
                logger.info(f"🔍 ML分析 {symbol}...")
                
                # 1. 执行预测分析
                prediction = await ml_service.predict_signal(symbol)
                logger.info(f"📊 {symbol} ML预测: {prediction.signal.value} (置信度: {prediction.confidence:.3f})")
                
                # 降低ML预测推送门槛
                if (prediction.signal.value in ['buy', 'sell'] and prediction.confidence > 0.6) or \
                   prediction.signal.value in ['strong_buy', 'strong_sell'] or \
                   (prediction.signal.value == 'hold' and prediction.confidence > 0.8):
                    await ml_notification_service.send_ml_prediction_alert(prediction)
                    logger.info(f"📢 已发送 {symbol} ML预测通知")
                
                # 2. 执行异常检测（限制推送数量）
                if anomaly_alerts_sent < max_anomaly_alerts:
                    anomalies = await ml_service.detect_anomalies(symbol)
                    if anomalies:
                        logger.info(f"⚠️ {symbol} 检测到 {len(anomalies)} 个异常")
                        # 只推送最高严重度的异常
                        critical_anomalies = [a for a in anomalies if a.severity > 0.9]
                        if critical_anomalies:
                            await ml_notification_service.send_anomaly_alert(critical_anomalies[:2])  # 最多2个
                            anomaly_alerts_sent += 1
                            logger.info(f"📢 已发送 {symbol} 关键异常警报")
                
            except Exception as e:
                logger.warning(f"❌ ML分析 {symbol} 失败: {e}")
                continue
        
        logger.info("✅ ML增强分析完成")
        
    except Exception as e:
        logger.error(f"❌ ML增强分析失败: {e}")


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
        
        # 添加智能交易机会扫描任务
        from app.services.intelligent_trading_notification_service import IntelligentTradingNotificationService
        intelligent_notification_service = IntelligentTradingNotificationService()
        
        # 每2小时扫描一次交易机会
        scheduler.add_job(
            intelligent_notification_service.scan_and_notify_opportunities,
            'interval',
            hours=1,
            id='intelligent_trading_scan',
            name='智能交易机会扫描'
        )
        logger.info("✅ Intelligent trading notification scheduled")
        
        # 启动时立即执行交易决策分析和推送
        try:
            startup_results = await perform_startup_trading_analysis()
            app.state.startup_analysis_results = startup_results
        except Exception as e:
            logger.warning(f"⚠️ 启动交易分析失败: {e}")
            app.state.startup_analysis_results = {"status": "error", "error": str(e)}
        
        # 初始化ML增强服务（可选）
        if settings.ml_config.get('enable_ml_prediction', False):
            ml_service = MLEnhancedService()
            try:
                await ml_service.initialize_models(settings.monitored_symbols)
                logger.info("✅ ML增强服务初始化成功")
                app.state.ml_service = ml_service
                
                # 启动时执行ML增强分析（在基础分析之后）
                await perform_startup_ml_analysis(ml_service)
                
            except Exception as e:
                logger.warning(f"⚠️ ML增强服务初始化失败: {e}")
                app.state.ml_service = None
        
        # 将服务实例存储到应用状态
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
    app.include_router(tradingview_router, prefix="/api/tradingview", tags=["TradingView功能"])
    app.include_router(strategy_router, prefix="/api/strategy", tags=["策略分析"])
    app.include_router(ml_enhanced_router, prefix="/api/ml", tags=["机器学习增强"])
    app.include_router(trading_decision_router, prefix="/api/trading", tags=["交易决策"])
    app.include_router(comprehensive_trading_router, prefix="/api/comprehensive", tags=["综合交易策略"])
    app.include_router(trading_advice_router, prefix="/api/advice", tags=["实盘交易建议"])
    app.include_router(strategy_trading_router, prefix="/api/strategy", tags=["策略交易"])
    app.include_router(enhanced_trading_advice_router, prefix="/api/enhanced", tags=["增强交易建议"])
    app.include_router(ml_strategy_optimization_router, prefix="/api/ml-optimization", tags=["ML策略优化"])
    
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
            
            # 检查ML服务状态
            ml_healthy = True
            if settings.ml_config.get('enable_ml_prediction', False):
                ml_healthy = hasattr(app.state, 'ml_service') and app.state.ml_service is not None
            
            status = "healthy" if all([db_healthy, api_healthy, scheduler_healthy, ml_healthy]) else "unhealthy"
            
            health_checks = {
                "database": "healthy" if db_healthy else "unhealthy",
                "binance_api": "healthy" if api_healthy else "unhealthy", 
                "scheduler": "healthy" if scheduler_healthy else "unhealthy"
            }
            
            if settings.ml_config.get('enable_ml_prediction', False):
                health_checks["ml_service"] = "healthy" if ml_healthy else "unhealthy"
            
            return {
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "checks": health_checks
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            raise HTTPException(status_code=500, detail="Health check failed")
    
    # 启动分析结果
    @app.get("/startup-analysis", summary="查看启动分析结果")
    async def get_startup_analysis():
        """获取应用启动时的交易分析结果"""
        try:
            if hasattr(app.state, 'startup_analysis_results'):
                results = app.state.startup_analysis_results
                
                # 添加运行时间信息
                if "timestamp" not in results and "summary" in results:
                    results["analysis_time"] = datetime.now().isoformat()
                
                return {
                    "status": "success",
                    "startup_analysis": results,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "status": "no_data",
                    "message": "启动分析结果不可用",
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"获取启动分析结果失败: {e}")
            raise HTTPException(status_code=500, detail="获取启动分析结果失败")
    
    # 快速市场概览
    @app.get("/market-overview", summary="快速市场概览")
    async def get_market_overview():
        """获取当前市场快速概览"""
        try:
            from app.services.startup_trading_service import StartupTradingService
            startup_service = StartupTradingService()
            
            overview = await startup_service.get_quick_market_overview()
            
            return {
                "status": "success",
                "market_overview": overview,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"获取市场概览失败: {e}")
            raise HTTPException(status_code=500, detail="获取市场概览失败")
    
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
