# -*- coding: utf-8 -*-
"""
Python Trading Analysis Tool - 主程序入口
Main entry point for the Python Trading Analysis Tool
"""

import sys
import os
import uvicorn
import asyncio
import tracemalloc
import warnings
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Windows平台优化：避免multiprocessing和SQLAlchemy的兼容性问题
if sys.platform == "win32":
    # 设置环境变量避免SQLAlchemy的WMI查询问题
    os.environ["SQLALCHEMY_WARN_20"] = "1"
    os.environ["PROCESSOR_ARCHITECTURE"] = "AMD64"
    
    # 设置multiprocessing启动方法为spawn（Windows默认）
    import multiprocessing
    try:
        multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        # 如果已经设置过，忽略错误
        pass

# 启用 tracemalloc 以获得更好的 asyncio 调试信息
tracemalloc.start()

# 过滤 asyncio 相关的 RuntimeWarning
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*coroutine.*was never awaited.*")

from app.core.config import get_settings
from app.core.logging import get_logger
from datetime import datetime

# 安全导入数据库模块 - 延迟导入避免multiprocessing问题
DATABASE_AVAILABLE = False
db_manager = None
create_tables = None
get_db_monitor = None

def _safe_import_database():
    """安全导入数据库模块"""
    global DATABASE_AVAILABLE, db_manager, create_tables, get_db_monitor
    
    if DATABASE_AVAILABLE:
        return True
        
    try:
        from app.core.database import create_tables as _create_tables, db_manager as _db_manager
        from app.utils.db_monitor import get_db_monitor as _get_db_monitor
        
        create_tables = _create_tables
        db_manager = _db_manager
        get_db_monitor = _get_db_monitor
        DATABASE_AVAILABLE = True
        
        logger.debug("✅ Database module imported successfully")
        return True
        
    except Exception as e:
        logger.warning(f"⚠️ Database module import failed: {e}")
        logger.info("💡 Application will run in memory-only mode")
        DATABASE_AVAILABLE = False
        return False

# 导入所有模型以确保表定义被注册
import app.models  # 这会导入所有模型定义

# 导入核心整合API路由 - 优先级最高
from app.api.core_trading import router as core_trading_router

# 导入原有API路由 - 保持兼容性
from app.api import (
    trend_router, monitor_router, notification_router,
    tradingview_router, strategy_router, ml_enhanced_router,
    backtest_router
)
from app.api.news import router as news_router
from app.api.kronos import router as kronos_router
from app.api.kronos_integrated import router as kronos_integrated_router
from app.api.funding_monitor import router as funding_monitor_router
from app.api.kronos_market_opportunities import router as kronos_market_opportunities_router
from app.api.kronos_advanced_opportunities import router as kronos_advanced_opportunities_router
from app.api.database import router as database_router
from app.api.http_pool import router as http_pool_router
from app.api.trading_pairs import router as trading_pairs_router
from app.api.unified_data import router as unified_data_router
from app.api.ml_config import router as ml_config_router
from app.api.enhanced_trading import router as enhanced_trading_router
from app.api.tradingview_scanner import router as tradingview_scanner_router
from app.api.tradingview_scheduler import router as tradingview_scheduler_router
from app.services.core.scheduler_service import SchedulerService
from app.services.ml.ml_enhanced_service import MLEnhancedService
from app.services.negative_funding_monitor_service import NegativeFundingMonitorService
from app.schemas.market_anomaly import AnomalyLevel

# 获取配置和日志
settings = get_settings()
logger = get_logger(__name__)

async def perform_startup_core_symbols_push():
    """启动时执行核心币种操作建议推送"""
    try:
        logger.info("📊 开始启动时核心币种操作建议推送...")
        
        # 启动交易所服务管理器
        from app.services.exchanges.service_manager import start_exchange_services
        startup_result = await start_exchange_services()
        
        if startup_result['status'] == 'success':
            logger.info(f"✅ 交易所服务启动成功: {startup_result['exchange']}")
        else:
            logger.error(f"❌ 交易所服务启动失败: {startup_result.get('error')}")
            # 继续执行，但记录错误
        
        # 使用全局单例获取核心调度服务
        from app.services.core.core_scheduler_service import get_core_scheduler_service
        
        scheduler_service = await get_core_scheduler_service()
        
        # 确保服务已初始化
        if not scheduler_service.trading_service:
            await scheduler_service._initialize_core_services()
        
        # 执行启动时核心币种推送
        success = await scheduler_service.run_startup_core_symbols_push()
        
        if success:
            logger.info("✅ 启动时核心币种推送完成")
            return {
                "status": "success",
                "message": "启动时核心币种推送完成",
                "timestamp": datetime.now().isoformat(),
                "push_type": "启动推送"
            }
        else:
            logger.warning("⚠️ 启动时核心币种推送失败")
            return {
                "status": "failed", 
                "message": "启动时核心币种推送失败",
                "timestamp": datetime.now().isoformat()
            }
            
    except Exception as e:
        logger.error(f"❌ 启动时核心币种推送异常: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

async def perform_startup_trading_analysis():
    """启动时执行完整的交易决策分析和推送 - 保持兼容性"""
    try:
        logger.info("🎯 启动交易分析 (兼容性保持) - 已由核心币种推送任务处理")
        
        # 不再重复调用核心币种推送，避免重复推送
        # 核心币种推送已经在 core_symbols_push 任务中处理
        
        return {
            "status": "success",
            "message": "交易分析任务已整合到核心币种推送中",
            "analysis_results": [],
            "notifications_sent": 0,  # 实际推送由 core_symbols_push 任务处理
            "timestamp": datetime.now().isoformat()
        }
            
    except Exception as e:
        logger.error(f"❌ 启动交易分析异常: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# 保留原有的详细分析功能作为备用
async def perform_detailed_startup_trading_analysis():
    """启动时执行详细的交易决策分析和推送 - 备用功能"""
    try:
        logger.info("🎯 开始启动详细交易决策分析 (Kronos+传统+ML综合)...")
        
        # 启动交易所服务管理器
        from app.services.exchanges.service_manager import start_exchange_services
        startup_result = await start_exchange_services()
        
        if startup_result['status'] == 'success':
            logger.info(f"✅ 交易所服务启动成功: {startup_result['exchange']}")
        else:
            logger.error(f"❌ 交易所服务启动失败: {startup_result.get('error')}")
            # 继续执行，但记录错误
        
        # 使用增强的核心交易服务，集成Kronos分析
        try:
            from app.services.trading.core_trading_service import get_core_trading_service, AnalysisType
            from app.services.notification.core_notification_service import get_core_notification_service
        except ImportError as e:
            logger.error(f"❌ 导入核心服务失败: {e}")
            return {
                "status": "error",
                "error": f"导入失败: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
        
        core_trading_service = await get_core_trading_service()
        await get_core_notification_service()
        
        # 主要分析的交易对
        major_symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP", "XRP-USDT-SWAP"]
        
        # 执行完整的交易决策分析
        analysis_results = []
        notifications_sent = 0
        
        for symbol in major_symbols:
            try:
                logger.info(f"🔍 综合分析 {symbol} (Kronos+技术+ML)...")
                
                # 使用集成分析 - 包含Kronos、传统技术分析、ML预测
                trading_signal = await core_trading_service.analyze_symbol(
                    symbol=symbol,
                    analysis_type=AnalysisType.INTEGRATED,  # 使用综合分析
                    force_update=True
                )
                
                if not trading_signal:
                    logger.warning(f"⚠️ {symbol} 分析失败，跳过")
                    continue
                
                # 日内短线交易优化：大幅降低推送阈值，专注5-15分钟级别信号
                # 检查是否是短线信号 (非HOLD且置信度>35% 适合日内短线交易)
                if (trading_signal.final_action.upper() not in ['HOLD', '持有', '观望', '等待'] and 
                    trading_signal.final_confidence > 0.35):
                    
                    # 转换置信度格式
                    confidence_percent = trading_signal.final_confidence * 100 if trading_signal.final_confidence <= 1 else trading_signal.final_confidence
                    
                    analysis_results.append({
                        "symbol": symbol,
                        "action": trading_signal.final_action,
                        "confidence": confidence_percent,
                        "signal_strength": trading_signal.signal_strength.value if hasattr(trading_signal.signal_strength, 'value') else str(trading_signal.signal_strength),
                        "reasoning": trading_signal.reasoning,
                        "kronos_confidence": trading_signal.confidence_breakdown.get('kronos', 0) * 100,
                        "technical_confidence": trading_signal.confidence_breakdown.get('technical', 0) * 100,
                        "ml_confidence": trading_signal.confidence_breakdown.get('ml', 0) * 100,
                        "trading_signal": trading_signal
                    })
                    
                    # 使用核心交易服务的推送方法
                    try:
                        # 增强通知内容，包含技术指标详情
                        if hasattr(trading_signal, 'technical_result') and trading_signal.technical_result:
                            # 从技术分析结果中提取指标信息
                            recommendation = trading_signal.technical_result.get('recommendation')
                            if recommendation and hasattr(recommendation, 'reasoning'):
                                # 将技术指标信息添加到信号中
                                trading_signal.technical_indicators = getattr(trading_signal, 'technical_indicators', {})
                                trading_signal.technical_indicators['analysis_details'] = recommendation.reasoning
                        
                        success = await core_trading_service.send_trading_signal_notification(trading_signal)
                        if success:
                            notifications_sent += 1
                            logger.info(f"✅ 发送 {symbol} 综合交易信号通知成功")
                        else:
                            logger.warning(f"❌ 发送 {symbol} 综合交易信号通知失败")
                        
                    except Exception as e:
                        logger.warning(f"发送 {symbol} 交易信号通知失败: {e}")
                
                else:
                    confidence_percent = trading_signal.final_confidence * 100 if trading_signal.final_confidence <= 1 else trading_signal.final_confidence
                    
                    # 详细打印所有分析结果，包括不符合推送条件的
                    symbol_name = symbol.replace('-USDT-SWAP', '')
                    logger.info(f"📊 {symbol_name}: {trading_signal.final_action} (综合置信度: {confidence_percent:.1f}%) - 不符合推送条件")
                    
                    # 打印各模块的详细分析结果
                    kronos_conf = trading_signal.confidence_breakdown.get('kronos', 0) * 100
                    technical_conf = trading_signal.confidence_breakdown.get('technical', 0) * 100
                    ml_conf = trading_signal.confidence_breakdown.get('ml', 0) * 100
                    
                    logger.info(f"   🔍 详细分析: 🤖 Kronos: {kronos_conf:.1f}% | 📊 技术: {technical_conf:.1f}% | 🧠 ML: {ml_conf:.1f}%")
                    
                    # 打印决策依据
                    if hasattr(trading_signal, 'reasoning') and trading_signal.reasoning:
                        logger.info(f"   💭 决策依据: {trading_signal.reasoning}")
                    
                    # 打印关键因素
                    if hasattr(trading_signal, 'key_factors') and trading_signal.key_factors:
                        factors = trading_signal.key_factors[:3]
                        logger.info(f"   📈 关键因素: {', '.join(factors)}")
                    
                    # 打印Kronos预测详情（如果有）
                    if hasattr(trading_signal, 'kronos_result') and trading_signal.kronos_result:
                        kronos_result = trading_signal.kronos_result
                        if hasattr(kronos_result, 'kronos_prediction') and kronos_result.kronos_prediction:
                            pred = kronos_result.kronos_prediction
                            price_change = pred.price_change_pct * 100
                            logger.info(f"   🤖 Kronos预测: 价格变化 {price_change:+.2f}%, 置信度 {pred.confidence:.2f}")
                    
                    # 打印技术分析详情（如果有）
                    if hasattr(trading_signal, 'technical_result') and trading_signal.technical_result:
                        tech_result = trading_signal.technical_result
                        tech_action = tech_result.get('action', 'Unknown')
                        tech_confidence = tech_result.get('confidence', 0) * 100
                        logger.info(f"   📊 技术分析: {tech_action} (置信度: {tech_confidence:.1f}%)")
                    
                    logger.info(f"   ⚠️ 未推送原因: 置信度{confidence_percent:.1f}% < 35% 或 行动为观望类型 (日内短线阈值)")
                    
            except Exception as e:
                logger.warning(f"❌ 分析 {symbol} 失败: {e}")
                continue
        
        # 构建返回结果
        startup_results = {
            "status": "success",
            "total_analyzed": len(major_symbols),
            "successful_analyses": len(analysis_results),
            "notifications_sent": notifications_sent,
            "strong_signals": analysis_results,
            "analysis_method": "core_trading_service_with_kronos_integration"
        }
        
        # 记录分析结果
        logger.info(f"✅ 启动完整交易决策分析完成 (Kronos+技术+ML):")
        logger.info(f"   📊 分析交易对: {len(major_symbols)} 个")
        logger.info(f"   🎯 发现强信号: {len(analysis_results)} 个")
        logger.info(f"   📢 通知发送: {notifications_sent} 条")
        logger.info(f"   🔧 分析方法: Kronos AI + 增强技术分析 + 机器学习")
        
        # 记录强信号详情
        for i, signal in enumerate(analysis_results[:3], 1):
            symbol = signal["symbol"].replace('-USDT-SWAP', '')
            action = signal["action"]
            confidence = signal["confidence"]
            signal_strength = signal["signal_strength"]
            kronos_conf = signal.get('kronos_confidence', 0)
            technical_conf = signal.get('technical_confidence', 0)
            ml_conf = signal.get('ml_confidence', 0)
            
            logger.info(f"   {i}. 🎯 {symbol}: {action} (综合: {confidence:.1f}%)")
            logger.info(f"      🤖 Kronos: {kronos_conf:.1f}% | 📊 技术: {technical_conf:.1f}% | 🧠 ML: {ml_conf:.1f}%")
            logger.info(f"      🔥 信号强度: {signal_strength}")
            
            # 显示技术指标亮点
            if len(signal.get('key_factors', [])) > 0:
                factors = signal['key_factors'][:3]
                logger.info(f"      📈 关键因素: {', '.join(factors)}")
        
        return startup_results
        
    except Exception as e:
        logger.error(f"❌ 启动完整交易决策分析失败: {e}")
        return {"status": "error", "error": str(e)}

async def send_startup_summary_notification(app_state, successful_tasks: int, failed_tasks: int):
    """发送启动完成摘要通知"""
    try:
        from app.services.notification.core_notification_service import get_core_notification_service
        notification_service = await get_core_notification_service()
        
        # 收集各任务结果
        trading_result = getattr(app_state, 'startup_trading_analysis_results', {})
        funding_result = getattr(app_state, 'startup_funding_analysis_results', {})
        getattr(app_state, 'startup_news_analysis_results', {})
        kronos_result = getattr(app_state, 'startup_kronos_market_scan_results', {})
        
        # 构建摘要消息
        message = f"🚀 **交易分析工具启动完成**\n\n"
        message += f"📊 任务执行: {successful_tasks} 成功, {failed_tasks} 失败\n\n"
        
        # 完整交易决策分析结果
        if trading_result.get("status") == "success":
            strong_signals = len(trading_result.get("strong_signals", []))
            notifications = trading_result.get("notifications_sent", 0)
            message += f"🎯 完整交易分析: {strong_signals} 个强信号, {notifications} 条通知\n"
        
        # 负费率分析结果
        if funding_result.get("status") == "success":
            opportunities = funding_result.get("opportunities_count", 0)
            message += f"💰 负费率机会: {opportunities} 个套利机会\n"
        
        # 市场异常分析结果
        market_anomaly_result = task_results.get("market_anomaly_analysis", {})
        if market_anomaly_result.get("status") == "success":
            anomalies_found = market_anomaly_result.get("anomalies_found", 0)
            recommended_count = market_anomaly_result.get("recommended_count", 0)
            message += f"🚨 市场异常: {anomalies_found} 个异常, {recommended_count} 个推荐\n"
        

        
        # Kronos市场扫描 - 已整合到核心交易分析中
        if kronos_result.get("status") == "success":
            kronos_opportunities = kronos_result.get("summary", {}).get("total_strong_opportunities", 0)
            message += f"🤖 Kronos扫描: {kronos_opportunities} 个AI机会 (已整合)\n"
        else:
            message += f"🤖 Kronos扫描: 已整合到核心分析\n"
        
        message += f"\n⏰ 启动时间: {datetime.now().strftime('%H:%M:%S')}"
        message += f"\n🔄 系统已就绪，开始监控市场..."
        
        # 确定通知优先级
        total_signals = (
            len(trading_result.get("strong_signals", [])) +
            funding_result.get("opportunities_count", 0) +
            kronos_result.get("summary", {}).get("total_strong_opportunities", 0) +
            market_anomaly_result.get("recommended_count", 0)
        )
        
        priority = "high" if total_signals > 0 else "medium" if failed_tasks == 0 else "low"
        
        from app.services.notification.core_notification_service import NotificationContent, NotificationType, NotificationPriority
        
        # 转换优先级字符串为枚举
        priority_map = {
            "high": NotificationPriority.HIGH,
            "medium": NotificationPriority.NORMAL,
            "low": NotificationPriority.LOW
        }
        
        content = NotificationContent(
            type=NotificationType.SYSTEM_ALERT,
            priority=priority_map.get(priority, NotificationPriority.NORMAL),
            title=f"🚀 系统启动完成 ({successful_tasks}/{successful_tasks + failed_tasks})",
            message=message,
            metadata={
                'successful_tasks': successful_tasks,
                'failed_tasks': failed_tasks,
                'total_signals': total_signals
            }
        )
        
        await notification_service.send_notification(content)
        
        logger.info(f"✅ 启动摘要通知已发送 (优先级: {priority})")
        
    except Exception as e:
        logger.warning(f"⚠️ 发送启动摘要通知失败: {e}")

async def perform_startup_funding_analysis():
    """启动时执行负费率分析和推送"""
    try:
        logger.info("💰 开始负费率吃利息机会分析...")
        
        # 创建负费率监控服务
        funding_monitor = NegativeFundingMonitorService()
        
        # 执行增强版监控检查（包含详细的价格预测和仓位建议）
        result = await funding_monitor.run_monitoring_cycle(enable_enhanced_analysis=True)
        
        if result['success']:
            opportunities = result['opportunities']
            logger.info(f"✅ 负费率分析完成: 发现 {len(opportunities)} 个吃利息机会")
            
            if opportunities:
                # 记录最佳机会
                best = opportunities[0]
                symbol_name = best['symbol'].replace('-USDT-SWAP', '')
                daily_rate = best['daily_rate_percent']
                daily_income = best['daily_income_10k']
                
                logger.info(f"🎯 最佳机会: {symbol_name}")
                logger.info(f"   💰 日化收益: {daily_rate:.3f}%")
                logger.info(f"   💵 1万U日收益: ${daily_income:.2f}")
                logger.info(f"   📊 评分: {best['score']}/100")
                
                # 记录前3个机会
                for i, opp in enumerate(opportunities[:3], 1):
                    symbol = opp['symbol'].replace('-USDT-SWAP', '')
                    rate = opp['funding_rate_percent']
                    daily = opp['daily_rate_percent']
                    logger.info(f"   {i}. {symbol}: {rate:.3f}% → 日化 {daily:.3f}%")
            else:
                logger.info("📊 当前市场无负费率机会")
            
            return {
                "status": "success",
                "opportunities_count": len(opportunities),
                "opportunities": opportunities[:5],  # 返回前5个
                "analysis_time": result['analysis_time'],
                "duration": result['duration_seconds']
            }
        else:
            error_msg = result.get('error', '未知错误')
            logger.error(f"❌ 负费率分析失败: {error_msg}")
            return {"status": "error", "error": error_msg}
            
    except Exception as e:
        logger.error(f"❌ 负费率分析异常: {e}")
        return {"status": "error", "error": str(e)}

async def perform_startup_market_anomaly_analysis():
    """启动时执行市场异常分析和推送"""
    try:
        logger.info("🚨 开始市场异常监控分析...")
        
        from app.services.market_anomaly_monitor_service import get_market_anomaly_service
        
        # 获取市场异常监控服务
        market_anomaly_service = await get_market_anomaly_service()
        
        # 执行监控周期
        result = await market_anomaly_service.run_monitoring_cycle()
        
        if result['success']:
            anomalies_found = result['anomalies_found']
            recommended_count = result['recommended_count']
            
            logger.info(f"✅ 市场异常分析完成: 发现 {anomalies_found} 个异常")
            logger.info(f"⭐ 推荐关注: {recommended_count} 个币种")
            
            if recommended_count > 0:
                logger.info("🏆 发现推荐的异常机会，已发送通知")
            else:
                logger.info("📊 当前市场无显著异常")
            
            return {
                "status": "success",
                "anomalies_found": anomalies_found,
                "recommended_count": recommended_count,
                "timestamp": result['timestamp']
            }
        else:
            error_msg = result.get('error', '未知错误')
            logger.error(f"❌ 市场异常分析失败: {error_msg}")
            return {"status": "error", "error": error_msg}
            
    except Exception as e:
        logger.error(f"❌ 市场异常分析异常: {e}")
        return {"status": "error", "error": str(e)}

async def perform_startup_grid_trading_analysis():
    """启动时执行网格交易机会分析和推送"""
    try:
        logger.info("🔲 开始网格交易机会分析...")
        
        from app.services.core.grid_scheduler_extension import get_grid_scheduler_extension
        
        # 获取网格交易调度器扩展
        grid_extension = await get_grid_scheduler_extension()
        
        # 执行启动时网格交易推荐
        success = await grid_extension.run_startup_grid_recommendations()
        
        if success:
            logger.info("✅ 网格交易机会分析完成")
            return {
                "status": "success",
                "message": "网格交易机会分析完成",
                "timestamp": datetime.now().isoformat()
            }
        else:
            logger.warning("⚠️ 网格交易机会分析失败")
            return {
                "status": "warning",
                "message": "网格交易机会分析失败",
                "timestamp": datetime.now().isoformat()
            }
            
    except Exception as e:
        logger.error(f"❌ 网格交易机会分析异常: {e}")
        return {"status": "error", "error": str(e)}

async def perform_startup_news_analysis():
    """启动时执行新闻分析和推送"""
    try:
        logger.info("📰 开始启动新闻分析...")
        
        from app.services.data.news_monitor_service import get_news_monitor_service
        
        # 获取新闻监控服务
        news_monitor = await get_news_monitor_service()
        
        # 执行一次监控周期
        result = await news_monitor.run_monitoring_cycle()
        
        if result['status'] == 'success':
            news_count = result.get('news_count', 0)
            analysis_count = result.get('analysis_count', 0)
            notifications_sent = result.get('notifications_sent', 0)
            
            logger.info(f"✅ 启动新闻分析完成:")
            logger.info(f"   📰 获取新闻: {news_count} 条")
            logger.info(f"   🔍 分析新闻: {analysis_count} 条")
            logger.info(f"   📢 发送通知: {notifications_sent} 条")
            
            return {
                "status": "success",
                "news_count": news_count,
                "analysis_count": analysis_count,
                "notifications_sent": notifications_sent,
                "duration": result.get('duration_seconds', 0),
                "message": result.get('message', '分析完成')
            }
        elif result['status'] == 'disabled':
            logger.info("📴 新闻分析已禁用")
            return {"status": "disabled", "message": "新闻分析已禁用"}
        else:
            error_msg = result.get('message', '未知错误')
            logger.error(f"❌ 启动新闻分析失败: {error_msg}")
            return {"status": "error", "error": error_msg}
            
    except Exception as e:
        logger.error(f"❌ 启动新闻分析异常: {e}")
        return {"status": "error", "error": str(e)}

async def perform_startup_ml_analysis(ml_service: MLEnhancedService):
    """启动时执行ML分析和推送（可选）"""
    try:
        logger.info("🤖 开始ML增强分析...")
        # ML通知功能已整合到核心通知服务中
        from app.services.notification.core_notification_service import get_core_notification_service
        notification_service = await get_core_notification_service()
        
        # 导入异常状态管理器
        from app.services.ml.anomaly_state_manager import anomaly_state_manager
        
        # 清理过期的异常记录
        anomaly_state_manager.cleanup_old_records(max_age_hours=24)
        
        # 分析配置中的所有交易对
        symbols_to_analyze = settings.monitored_symbols
        all_detected_anomalies = []  # 收集所有币种检测到的异常
        
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
                    # 使用核心通知服务发送ML预测通知
                    await notification_service.send_ml_prediction_notification({
                        'symbol': symbol,
                        'signal': prediction.signal.value,
                        'confidence': prediction.confidence,
                        'timestamp': datetime.now()
                    })
                    logger.info(f"📢 已发送 {symbol} ML预测通知")
                
                # 2. 执行异常检测
                anomalies = await ml_service.detect_anomalies(symbol)
                if anomalies:
                    logger.info(f"⚠️ {symbol} 检测到 {len(anomalies)} 个异常")
                    # 过滤出严重程度足够的异常
                    significant_anomalies = [
                        a for a in anomalies 
                        if a.severity > 0.5  # 严重程度大于50%
                    ]
                    
                    if significant_anomalies:
                        all_detected_anomalies.extend(significant_anomalies)
                        logger.info(f"📊 {symbol} 发现 {len(significant_anomalies)} 个显著异常")
                
            except Exception as e:
                logger.warning(f"❌ ML分析 {symbol} 失败: {e}")
                continue
        
        # 3. 使用状态管理器过滤出真正的新异常
        if all_detected_anomalies:
            new_anomalies = anomaly_state_manager.filter_new_anomalies(all_detected_anomalies)
            
            if new_anomalies:
                # 按严重程度排序，只推送最严重的前5个
                new_anomalies.sort(key=lambda x: x.severity, reverse=True)
                top_anomalies = new_anomalies[:5]
                
                # 使用核心通知服务发送异常警报
                await notification_service.send_anomaly_notification({
                    'anomalies': [{'symbol': a.symbol, 'severity': a.severity, 'description': str(a)} for a in top_anomalies],
                    'count': len(top_anomalies),
                    'timestamp': datetime.now()
                })
                logger.info(f"📢 已发送 {len(top_anomalies)} 个新异常警报，涉及币种: {list(set(a.symbol for a in top_anomalies))}")
            else:
                logger.info("✅ 所有检测到的异常都已通知过，跳过推送")
        else:
            logger.info("✅ 未检测到任何异常")
        
        # 4. 输出异常统计信息
        stats = anomaly_state_manager.get_anomaly_stats()
        if stats:
            logger.info(f"📊 异常统计: {stats}")
        
        logger.info("✅ ML增强分析完成")
        
    except Exception as e:
        logger.error(f"❌ ML增强分析失败: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("🚀 Starting Python Trading Analysis Tool...")
    
    # 存储需要清理的资源
    
    try:
        # 安全导入数据库模块
        database_imported = _safe_import_database()
        
        if not database_imported:
            logger.warning("⚠️ Database module not available - running in memory mode")
            app.state.database_available = False
        else:
            # 尝试创建数据库表 - 允许失败
            try:
                if create_tables:
                    create_tables()
                    logger.info("✅ Database tables created successfully")
                else:
                    logger.warning("⚠️ create_tables function not available")
            except Exception as e:
                logger.warning(f"⚠️ Database table creation failed: {e}")
                logger.info("💡 Application will continue without database persistence")
            
            # 测试数据库连接和连接池 - 允许在数据库不可用时继续运行
            try:
                # 验证数据库管理器是否可用
                logger.debug("🔍 开始数据库健康检查...")
                
                # 检查 db_manager 是否已正确导入和初始化
                if db_manager is None:
                    logger.warning("⚠️ Database manager is None - running in memory mode")
                    app.state.database_available = False
                else:
                    logger.debug("✅ Database manager is available, performing health check...")
                    if get_db_monitor:
                        db_monitor = get_db_monitor()
                        
                        if db_manager.health_check():
                            logger.info("✅ Database connection healthy")
                            
                            # 显示连接池状态
                            pool_stats = db_monitor.get_pool_stats()
                            logger.info(f"📊 Connection pool stats: {pool_stats}")
                            
                            app.state.database_available = True
                            app.state.db_monitor = db_monitor
                        else:
                            logger.warning("⚠️ Database connection failed - running in memory mode")
                            app.state.database_available = False
                    else:
                        logger.warning("⚠️ get_db_monitor function not available - running in memory mode")
                        app.state.database_available = False
                        
            except Exception as e:
                logger.warning(f"⚠️ Database health check failed: {e} - running in memory mode")
                app.state.database_available = False
        
        # 启动统一调度器（包含核心币种推送任务）
        scheduler = SchedulerService()
        await scheduler.start()
        logger.info("✅ 统一调度器启动成功（包含核心币种推送任务）")
        
        if settings.kronos_config.get('enable_kronos_prediction', False):
            logger.info("✅ Kronos预测已启用，核心信号分析由调度器统一管理")
        else:
            logger.info("📴 Kronos预测已禁用")
        
        # 添加负费率监控定时任务
        funding_monitor = NegativeFundingMonitorService()
        
        # 每60分钟检查一次负费率机会（使用增强版分析）
        async def funding_monitor_task():
            """负费率监控任务包装器"""
            try:
                logger.debug("🔄 开始执行负费率监控任务...")
                result = await funding_monitor.run_monitoring_cycle(enable_enhanced_analysis=True)
                if result.get('success'):
                    logger.debug("✅ 负费率监控任务执行成功")
                else:
                    logger.warning(f"⚠️ 负费率监控任务执行异常: {result.get('error', '未知错误')}")
            except Exception as e:
                logger.error(f"❌ 负费率监控任务执行失败: {e}")
        
        scheduler.add_job(
            funding_monitor_task,
            'interval',
            minutes=60,
            id='negative_funding_monitor',
            name='负费率吃利息机会监控（增强版）',
            max_instances=1  # 确保同时只有一个实例运行
        )
        logger.info("✅ Negative funding rate monitor scheduled")
        

        
        # 将负费率监控服务存储到应用状态
        app.state.funding_monitor = funding_monitor
        
        # 添加市场异常监控定时任务
        from app.services.market_anomaly_monitor_service import get_market_anomaly_service
        
        market_anomaly_service = await get_market_anomaly_service()
        
        # 每60分钟检查一次市场异常
        async def market_anomaly_task():
            """市场异常监控任务包装器"""
            try:
                logger.debug("🔄 开始执行市场异常监控任务...")
                result = await market_anomaly_service.run_monitoring_cycle()
                if result.get('success'):
                    anomalies_count = result.get('anomalies_found', 0)
                    recommended_count = result.get('recommended_count', 0)
                    logger.debug(f"✅ 市场异常监控任务执行成功: {anomalies_count}个异常, {recommended_count}个推荐")
                else:
                    logger.warning(f"⚠️ 市场异常监控任务执行异常: {result.get('error', '未知错误')}")
            except Exception as e:
                logger.error(f"❌ 市场异常监控任务执行失败: {e}")
        
        scheduler.add_job(
            market_anomaly_task,
            'interval',
            minutes=60,
            id='market_anomaly_monitor',
            name='市场异常监控（波动率+交易量+持仓量）',
            max_instances=1  # 确保同时只有一个实例运行
        )
        logger.info("✅ Market anomaly monitor scheduled")
        
        # 将市场异常监控服务存储到应用状态
        app.state.market_anomaly_service = market_anomaly_service
        
        # 添加TradingView扫描器定时任务
        from app.services.core.tradingview_scheduler_service import get_tradingview_scheduler_service
        
        tradingview_scheduler_service = await get_tradingview_scheduler_service()
        
        # 启动时立即执行一次TradingView扫描
        try:
            logger.info("📊 启动时立即执行TradingView强势币种扫描...")
            startup_scan_result = await tradingview_scheduler_service.scan_and_notify()
            app.state.startup_tradingview_scan = startup_scan_result
            
            if startup_scan_result.get("status") == "success":
                symbols_count = startup_scan_result.get("symbols_count", 0)
                logger.info(f"✅ 启动TradingView扫描完成: 发现 {symbols_count} 个强势币种")
            else:
                logger.warning(f"⚠️ 启动TradingView扫描异常: {startup_scan_result.get('error', '未知')}")
        except Exception as e:
            logger.warning(f"⚠️ 启动TradingView扫描失败: {e}")
            app.state.startup_tradingview_scan = {"status": "error", "error": str(e)}
        
        # 每60分钟执行一次TradingView扫描
        scheduler.add_job(
            tradingview_scheduler_service.scan_and_notify,
            'interval',
            minutes=60,
            id='tradingview_scanner',
            name='TradingView强势币种扫描',
            max_instances=1  # 确保同时只有一个实例运行
        )
        logger.info("✅ TradingView扫描器定时任务已启动 (每60分钟)")
        
        # 将服务存储到应用状态
        app.state.tradingview_scheduler_service = tradingview_scheduler_service
        
        # 初始化网格交易调度器扩展
        try:
            from app.services.core.grid_scheduler_extension import get_grid_scheduler_extension
            
            grid_extension = await get_grid_scheduler_extension()
            app.state.grid_scheduler_extension = grid_extension
            
            logger.info("✅ 网格交易调度器扩展初始化成功")
            
        except Exception as e:
            logger.warning(f"⚠️ 网格交易调度器扩展初始化失败: {e}")
            app.state.grid_scheduler_extension = None
        
        # 添加Kronos持仓分析定时任务 - 币安交易所跳过
        if settings.kronos_config.get('enable_kronos_prediction', False):
            # 检查交易所类型，币安跳过持仓分析
            if settings.exchange_provider.lower() == 'binance':
                logger.info("📴 币安交易所跳过Kronos持仓分析功能")
                app.state.startup_position_analysis = {
                    "status": "skipped", 
                    "message": "币安交易所暂不支持持仓分析",
                    "exchange_provider": "binance"
                }
                app.state.kronos_position_service = None
            else:
                from app.services.analysis.kronos_position_analysis_service import get_kronos_position_service
                
                # 使用全局单例实例，确保状态一致
                kronos_position_service = await get_kronos_position_service()
                
                # 启动时立即执行一次Kronos持仓分析
                try:
                    logger.info("🤖 启动时立即执行Kronos持仓分析...")
                    startup_position_result = await kronos_position_service.run_startup_analysis()
                    app.state.startup_position_analysis = startup_position_result
                    
                    if startup_position_result.get("status") == "success":
                        positions_count = startup_position_result.get("positions_analyzed", 0)
                        logger.info(f"✅ 启动Kronos持仓分析完成: 分析了 {positions_count} 个持仓")
                    elif startup_position_result.get("status") == "no_positions":
                        logger.info("📊 当前无持仓，跳过Kronos持仓分析")
                    else:
                        logger.warning(f"⚠️ 启动Kronos持仓分析异常: {startup_position_result.get('reason', '未知')}")
                except Exception as e:
                    logger.warning(f"⚠️ 启动Kronos持仓分析失败: {e}")
                    app.state.startup_position_analysis = {"status": "error", "error": str(e)}
                
                # 检查是否已经存在相同的定时任务，避免重复添加
                existing_job = scheduler.get_job('kronos_position_analysis')
                if existing_job:
                    logger.warning("⚠️ Kronos持仓分析任务已存在，跳过重复添加")
                else:
                    # 每60分钟执行一次Kronos持仓分析和推送
                    scheduler.add_job(
                        kronos_position_service.run_scheduled_analysis,
                        'interval',
                        minutes=60,
                        id='kronos_position_analysis',
                        name='Kronos持仓分析和风险评估',
                        max_instances=1  # 确保同时只有一个实例运行
                    )
                    logger.info("✅ Kronos持仓分析定时任务已启动 (每60分钟)")
                
                # 将服务存储到应用状态
                app.state.kronos_position_service = kronos_position_service
        
        # 🚀 启动时按优先级顺序执行分析任务 - 核心币种操作建议优先
        logger.info("🚀 开始按优先级顺序执行启动分析任务...")
        
        # 第一优先级：核心币种操作建议推送 (最重要)
        logger.info("📊 第一优先级：执行核心币种操作建议推送...")
        core_symbols_result = await perform_startup_core_symbols_push()
        setattr(app.state, 'startup_core_symbols_push_results', core_symbols_result)
        
        if core_symbols_result["status"] == "success":
            logger.info("✅ 核心币种推送完成，继续执行其他任务")
        else:
            logger.warning(f"⚠️ 核心币种推送失败: {core_symbols_result.get('error', '未知错误')}")
        
        # 第二优先级：并发执行其他分析任务
        logger.info("🔄 第二优先级：并发执行其他分析任务...")
        startup_tasks = []
        
        # 1. 兼容性交易分析任务
        startup_tasks.append(("trading_analysis", perform_startup_trading_analysis()))
        
        # 2. 负费率分析任务 (现在在核心币种推送之后)
        startup_tasks.append(("funding_analysis", perform_startup_funding_analysis()))
        
        # 3. 市场异常监控分析任务
        startup_tasks.append(("market_anomaly_analysis", perform_startup_market_anomaly_analysis()))
        
        # 4. 网格交易机会推荐任务
        startup_tasks.append(("grid_trading_analysis", perform_startup_grid_trading_analysis()))
        

        
        # 并发执行所有启动任务
        task_names = [name for name, _ in startup_tasks]
        task_coroutines = [task for _, task in startup_tasks]
        
        logger.info(f"📊 准备并发执行 {len(task_coroutines)} 个启动任务: {task_names}")
        
        # 使用 asyncio.gather 并发执行，允许部分失败
        startup_results = await asyncio.gather(*task_coroutines, return_exceptions=True)
        
        # 处理并发执行结果 (不包括核心币种推送，已单独执行)
        successful_tasks = 1 if core_symbols_result["status"] == "success" else 0  # 核心币种推送结果
        failed_tasks = 0 if core_symbols_result["status"] == "success" else 1
        
        for i, (task_name, result) in enumerate(zip(task_names, startup_results)):
            if isinstance(result, Exception):
                logger.warning(f"⚠️ 启动任务 {task_name} 失败: {result}")
                setattr(app.state, f"startup_{task_name}_results", {"status": "error", "error": str(result)})
                failed_tasks += 1
            else:
                logger.info(f"✅ 启动任务 {task_name} 完成")
                setattr(app.state, f"startup_{task_name}_results", result)
                successful_tasks += 1
        
        # 记录执行总结 (包括核心币种推送)
        total_tasks = len(task_coroutines) + 1  # +1 for core_symbols_push
        logger.info(f"🎯 启动任务执行完成: {successful_tasks}/{total_tasks} 成功, {failed_tasks} 失败")
        logger.info(f"📊 核心币种操作建议已优先执行，负费率机会分析随后执行")
        
        # 设置默认状态 (兼容性)
        if not hasattr(app.state, 'startup_news_analysis_results'):
            app.state.startup_news_analysis_results = {"status": "disabled"}
        if not hasattr(app.state, 'startup_kronos_market_scan_results'):
            app.state.startup_kronos_market_scan_results = {"status": "disabled"}
        
        logger.info("📊 启动摘要通知已禁用 - 系统状态信息不推送")
        
        # 初始化Kronos预测服务（可选）
        if settings.kronos_config.get('enable_kronos_prediction', False):
            try:
                from app.services.ml.kronos_prediction_service import get_kronos_service
                kronos_service = await get_kronos_service()
                logger.info("✅ Kronos预测服务初始化成功")
                app.state.kronos_service = kronos_service
            except Exception as e:
                logger.warning(f"⚠️ Kronos预测服务初始化失败: {e}")
                logger.info("💡 Kronos服务将在首次调用时尝试重新初始化")
                app.state.kronos_service = None
        
        # 初始化ML增强服务（可选）
        if settings.ml_config.get('enable_ml_prediction', False):
            ml_service = MLEnhancedService()
            try:
                await ml_service.initialize_models(settings.monitored_symbols)
                logger.info("✅ ML增强服务初始化成功")
                app.state.ml_service = ml_service
                
            except Exception as e:
                logger.warning(f"⚠️ ML增强服务初始化失败: {e}")
                app.state.ml_service = None
        
        # 启动配置监控服务
        try:
            from app.services.exchanges.config_monitor import start_config_monitoring
            config_monitor_result = await start_config_monitoring()
            
            if config_monitor_result['status'] == 'success':
                logger.info("✅ 配置监控服务启动成功")
            else:
                logger.warning(f"⚠️ 配置监控服务启动失败: {config_monitor_result.get('error')}")
        except Exception as e:
            logger.warning(f"⚠️ 配置监控服务启动异常: {e}")
        
        # 将服务实例存储到应用状态
        app.state.scheduler = scheduler
        
        # 启动适配器监控服务
        try:
            logger.info("🔍 启动适配器监控服务...")
            from app.services.monitoring.adapter_monitoring_service import start_adapter_monitoring
            await start_adapter_monitoring()
            logger.info("✅ 适配器监控服务启动成功")
        except Exception as e:
            logger.warning(f"⚠️ 适配器监控服务启动失败: {e}")
        
        logger.info("🎉 Application startup completed!")
        
        yield
        
        # 应用关闭时的清理工作
        logger.info("🛑 Shutting down application...")
        
        # 0. 停止适配器监控服务
        try:
            logger.info("🔍 停止适配器监控服务...")
            from app.services.monitoring.adapter_monitoring_service import stop_adapter_monitoring
            await stop_adapter_monitoring()
            logger.info("✅ 适配器监控服务已停止")
        except Exception as e:
            logger.warning(f"⚠️ 停止适配器监控服务失败: {e}")
        
        # 1. 停止调度器
        try:
            if hasattr(app.state, 'scheduler') and app.state.scheduler:
                await app.state.scheduler.stop()
                logger.info("✅ General scheduler stopped")
        except Exception as e:
            logger.warning(f"⚠️ Error stopping general scheduler: {e}")
        
        # 1.1 停止核心币种推送调度器
        try:
            # 核心币种推送任务已整合到统一调度器中，无需单独停止
            pass
        except Exception as e:
            logger.warning(f"⚠️ Error stopping core scheduler: {e}")
        
        # 2. 清理核心HTTP客户端
        try:
            from app.utils.http_manager import cleanup_http_resources
            await cleanup_http_resources()
            logger.info("✅ Core HTTP client cleaned up")
        except Exception as e:
            logger.warning(f"⚠️ Error cleaning up core HTTP client: {e}")
        
        # 3. 停止配置监控服务
        try:
            from app.services.exchanges.config_monitor import stop_config_monitoring
            config_stop_result = await stop_config_monitoring()
            if config_stop_result['status'] == 'success':
                logger.info("✅ 配置监控服务停止完成")
            else:
                logger.warning(f"⚠️ 配置监控服务停止失败: {config_stop_result.get('error')}")
        except Exception as e:
            logger.warning(f"⚠️ Error stopping config monitoring: {e}")
        
        # 4. 清理交易所服务
        try:
            from app.services.exchanges.service_manager import stop_exchange_services
            stop_result = await stop_exchange_services()
            if stop_result['status'] == 'success':
                logger.info("✅ 交易所服务清理完成")
            else:
                logger.warning(f"⚠️ 交易所服务清理失败: {stop_result.get('error')}")
        except Exception as e:
            logger.warning(f"⚠️ Error cleaning up exchange services: {e}")
        
        # 5. 清理交易所服务连接
        try:
            from app.services.exchanges.factory import cleanup_all_exchanges
            await cleanup_all_exchanges()
            logger.info("✅ 交易所连接清理完成")
        except Exception as e:
            logger.warning(f"⚠️ Error cleaning up exchange connections: {e}")
        
        # 6. 通用 HTTP 连接清理（兼容性）
        try:
            import gc
            import aiohttp
            
            # 收集所有剩余的 aiohttp.ClientSession 对象并关闭
            cleaned_count = 0
            for obj in gc.get_objects():
                if isinstance(obj, aiohttp.ClientSession) and not obj.closed:
                    try:
                        await obj.close()
                        cleaned_count += 1
                    except Exception as e:
                        logger.debug(f"⚠️ Error closing remaining session: {e}")
            
            if cleaned_count > 0:
                await asyncio.sleep(0.2)
                logger.info(f"✅ Cleaned up {cleaned_count} remaining HTTP sessions")
            
        except Exception as e:
            logger.warning(f"⚠️ Error in general HTTP cleanup: {e}")
        
        # 4. 清理数据库连接
        try:
            if hasattr(app.state, 'database_available') and app.state.database_available and db_manager:
                if hasattr(db_manager, 'close_all_connections'):
                    await db_manager.close_all_connections()
                    logger.info("✅ Database connections closed")
        except Exception as e:
            logger.warning(f"⚠️ Error closing database connections: {e}")
        
        # 5. 清理其他服务
        try:
            # 清理 Kronos 服务
            if hasattr(app.state, 'kronos_service') and app.state.kronos_service:
                # Kronos 服务通常不需要特殊清理
                pass
            
            # 清理 ML 服务
            if hasattr(app.state, 'ml_service') and app.state.ml_service:
                # ML 服务通常不需要特殊清理
                pass
                
            logger.info("✅ Services cleaned up")
        except Exception as e:
            logger.warning(f"⚠️ Error cleaning up services: {e}")
        
        logger.info("🎯 Application shutdown completed")
        
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
        
        # 清理HTTP连接池
        try:
            from app.utils.http_manager import cleanup_http_resources
            await cleanup_http_resources()
            logger.info("✅ HTTP connection pool cleaned up")
        except Exception as e:
            logger.error(f"⚠️ HTTP cleanup error: {e}")
        
        # 清理数据库连接
        try:
            if db_manager and hasattr(db_manager, 'close_all_connections'):
                db_manager.close_all_connections()
                logger.info("✅ Database connections closed")
        except Exception as e:
            logger.error(f"⚠️ Database cleanup error: {e}")
        
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
    
    # 注册路由 - 核心整合API优先
    app.include_router(core_trading_router, tags=["核心交易"])
    
    # 增强交易分析API
    app.include_router(enhanced_trading_router, prefix="/api/enhanced", tags=["增强交易分析"])
    
    # 原有路由 - 保持兼容性
    app.include_router(trend_router, prefix="/api/trend", tags=["趋势分析"])
    app.include_router(monitor_router, prefix="/api/monitor", tags=["监控服务"])
    app.include_router(notification_router, prefix="/api/notification", tags=["通知服务"])
    app.include_router(tradingview_router, prefix="/api/tradingview", tags=["TradingView功能"])
    app.include_router(strategy_router, prefix="/api/strategy", tags=["策略分析"])
    app.include_router(ml_enhanced_router, prefix="/api/ml", tags=["机器学习增强"])
    app.include_router(backtest_router, prefix="/api", tags=["回测分析"])
    app.include_router(funding_monitor_router, prefix="/api/funding", tags=["负费率监控"])
    
    # 市场异常监控API
    from app.api.market_anomaly import router as market_anomaly_router
    app.include_router(market_anomaly_router, prefix="/api/market-anomaly", tags=["市场异常监控"])
    
    app.include_router(kronos_router, prefix="/api/kronos", tags=["Kronos AI预测"])
    app.include_router(kronos_integrated_router, prefix="/api/kronos-integrated", tags=["Kronos集成决策"])
    app.include_router(kronos_market_opportunities_router, prefix="/api/kronos-opportunities", tags=["Kronos市场机会"])
    app.include_router(kronos_advanced_opportunities_router, prefix="/api/kronos-advanced", tags=["Kronos高级机会"])

    app.include_router(database_router, prefix="/api/database", tags=["数据库管理"])
    app.include_router(http_pool_router, prefix="/api/http-pool", tags=["HTTP连接池管理"])
    app.include_router(trading_pairs_router, prefix="/api/trading-pairs", tags=["交易对管理"])
    app.include_router(unified_data_router, prefix="/api", tags=["统一数据服务"])
    app.include_router(ml_config_router, prefix="/api/ml-config", tags=["ML配置管理"])
    app.include_router(news_router, prefix="/api/news", tags=["新闻分析"])
    
    # TradingView扫描器API
    app.include_router(tradingview_scanner_router, prefix="/api/tradingview", tags=["TradingView扫描器"])
    app.include_router(tradingview_scheduler_router, prefix="/api/tradingview", tags=["TradingView调度器"])
    
    # 交易所管理API
    from app.api.exchange_management import router as exchange_management_router
    app.include_router(exchange_management_router, tags=["交易所管理"])
    
    # 系统诊断API
    from app.api.system_diagnostics import router as system_diagnostics_router
    app.include_router(system_diagnostics_router, tags=["系统诊断"])
    
    # 网格交易API
    from app.api.grid_trading import router as grid_trading_router
    app.include_router(grid_trading_router, tags=["网格交易"])
    

    
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
            # 检查数据库连接和连接池
            db_healthy = False
            pool_stats = {}
            if DATABASE_AVAILABLE and db_manager and get_db_monitor:
                db_healthy = db_manager.health_check()
                db_monitor = get_db_monitor()
                pool_stats = db_monitor.get_pool_stats() if db_healthy else {}
            
            # 检查适配器状态
            adapter_status = {"status": "unknown", "details": {}}
            try:
                from app.services.monitoring.adapter_monitoring_service import get_adapter_monitoring_service
                monitoring_service = get_adapter_monitoring_service()
                adapter_overall_status = await monitoring_service.get_overall_status()
                adapter_status = {
                    "status": adapter_overall_status["status"],
                    "total_exchanges": adapter_overall_status.get("total_exchanges", 0),
                    "status_breakdown": adapter_overall_status.get("status_breakdown", {}),
                    "monitoring_active": adapter_overall_status.get("monitoring_active", False)
                }
            except Exception as e:
                logger.warning(f"⚠️ 获取适配器状态失败: {e}")
                adapter_status = {"status": "error", "error": str(e)}
            
            api_healthy = True
            
            # 检查调度器状态
            scheduler_healthy = hasattr(app.state, 'scheduler') and app.state.scheduler.is_running()
            
            # 检查ML服务状态
            ml_healthy = True
            if settings.ml_config.get('enable_ml_prediction', False):
                ml_healthy = hasattr(app.state, 'ml_service') and app.state.ml_service is not None
            
            # 适配器健康状态
            adapter_healthy = adapter_status["status"] in ["healthy", "degraded"]
            
            status = "healthy" if all([db_healthy, api_healthy, scheduler_healthy, ml_healthy, adapter_healthy]) else "unhealthy"
            
            health_checks = {
                "database": "healthy" if db_healthy else "unhealthy",
                "connection_pool": pool_stats,
                "binance_api": "healthy" if api_healthy else "unhealthy", 
                "scheduler": "healthy" if scheduler_healthy else "unhealthy",
                "data_adapters": adapter_status
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
    
    # 适配器监控相关端点
    @app.get("/adapters/status", summary="获取所有适配器状态")
    async def get_adapters_status():
        """获取所有数据适配器的状态信息"""
        try:
            from app.services.monitoring.adapter_monitoring_service import get_adapter_monitoring_service
            monitoring_service = get_adapter_monitoring_service()
            return await monitoring_service.get_all_statuses()
        except Exception as e:
            logger.error(f"❌ 获取适配器状态失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取适配器状态失败: {str(e)}")
    
    @app.get("/adapters/status/{exchange}", summary="获取特定交易所适配器状态")
    async def get_adapter_status(exchange: str):
        """获取特定交易所数据适配器的状态信息"""
        try:
            from app.services.monitoring.adapter_monitoring_service import get_adapter_monitoring_service
            monitoring_service = get_adapter_monitoring_service()
            return await monitoring_service.get_exchange_status(exchange)
        except Exception as e:
            logger.error(f"❌ 获取 {exchange} 适配器状态失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取适配器状态失败: {str(e)}")
    
    @app.get("/adapters/performance", summary="获取适配器性能统计")
    async def get_adapters_performance():
        """获取数据适配器的性能统计信息"""
        try:
            from app.services.monitoring.adapter_monitoring_service import get_adapter_monitoring_service
            monitoring_service = get_adapter_monitoring_service()
            return await monitoring_service.get_performance_summary()
        except Exception as e:
            logger.error(f"❌ 获取适配器性能统计失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取性能统计失败: {str(e)}")
    
    @app.get("/adapters/errors", summary="获取适配器错误统计")
    async def get_adapters_errors():
        """获取数据适配器的错误统计信息"""
        try:
            from app.services.monitoring.adapter_monitoring_service import get_adapter_monitoring_service
            monitoring_service = get_adapter_monitoring_service()
            return await monitoring_service.get_error_summary()
        except Exception as e:
            logger.error(f"❌ 获取适配器错误统计失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取错误统计失败: {str(e)}")
    
    @app.post("/adapters/diagnostics", summary="运行适配器诊断")
    async def run_adapters_diagnostics(exchange: str = None):
        """运行数据适配器的综合诊断"""
        try:
            from app.services.monitoring.adapter_monitoring_service import get_adapter_monitoring_service
            monitoring_service = get_adapter_monitoring_service()
            return await monitoring_service.run_comprehensive_diagnostics(exchange)
        except Exception as e:
            logger.error(f"❌ 运行适配器诊断失败: {e}")
            raise HTTPException(status_code=500, detail=f"诊断失败: {str(e)}")
    
    @app.get("/adapters/monitoring/config", summary="获取监控配置")
    async def get_monitoring_config():
        """获取适配器监控配置"""
        try:
            from app.services.monitoring.adapter_monitoring_service import get_adapter_monitoring_service
            monitoring_service = get_adapter_monitoring_service()
            return monitoring_service.get_monitoring_config()
        except Exception as e:
            logger.error(f"❌ 获取监控配置失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")
    
    @app.put("/adapters/monitoring/config", summary="更新监控配置")
    async def update_monitoring_config(config: dict):
        """更新适配器监控配置"""
        try:
            from app.services.monitoring.adapter_monitoring_service import get_adapter_monitoring_service
            monitoring_service = get_adapter_monitoring_service()
            monitoring_service.update_monitoring_config(config)
            return {"status": "success", "message": "监控配置已更新"}
        except Exception as e:
            logger.error(f"❌ 更新监控配置失败: {e}")
            raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")

    # 启动分析结果
    @app.get("/startup-analysis", summary="查看启动分析结果")
    async def get_startup_analysis():
        """获取应用启动时的交易分析结果"""
        try:
            trading_results = None
            funding_results = None
            kronos_results = None
            
            if hasattr(app.state, 'startup_analysis_results'):
                trading_results = app.state.startup_analysis_results
                
            if hasattr(app.state, 'startup_funding_results'):
                funding_results = app.state.startup_funding_results
                
            if hasattr(app.state, 'startup_kronos_results'):
                kronos_results = app.state.startup_kronos_results
            
            return {
                "status": "success",
                "startup_analysis": {
                    "trading_analysis": trading_results,
                    "funding_analysis": funding_results,
                    "kronos_market_scan": kronos_results
                },
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"获取启动分析结果失败: {e}")
            raise HTTPException(status_code=500, detail="获取启动分析结果失败")
    
    # Kronos市场机会快速测试
    @app.get("/kronos-opportunities-test", summary="Kronos市场机会快速测试")
    async def test_kronos_opportunities():
        """快速测试Kronos市场机会扫描功能"""
        try:
            from app.services.ml.kronos_market_opportunity_service import get_kronos_market_opportunity_service
            
            market_service = await get_kronos_market_opportunity_service()
            
            # 获取扫描状态
            status = await market_service.get_scan_status()
            
            # 执行快速强信号扫描（强制模式）
            strong_result = await market_service.scan_strong_trading_opportunities(force_scan=True)
            
            return {
                "status": "success",
                "scan_status": status,
                "test_scan_result": strong_result,
                "message": "Kronos市场机会扫描测试完成",
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Kronos机会测试失败: {e}")
            raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")
    
    # 负费率机会快速查看
    @app.get("/funding-opportunities", summary="快速查看负费率机会")
    async def get_funding_opportunities():
        """快速查看当前负费率吃利息机会"""
        try:
            if hasattr(app.state, 'funding_monitor'):
                # 使用缓存的监控服务进行快速检查
                funding_monitor = app.state.funding_monitor
                
                # 快速检查前20个热门币种
                hot_symbols = await funding_monitor.get_top_volume_symbols(limit=20)
                
                # 使用配置的交易所服务获取费率数据
                from app.services.exchanges.factory import get_default_exchange
                exchange_service = await get_default_exchange()
                funding_rates = await exchange_service.get_batch_funding_rates(hot_symbols[:15])
                
                # 只分析负费率币种
                negative_rates = [r for r in funding_rates if r['funding_rate'] < 0]
                
                if negative_rates:
                    opportunities = []
                    for rate_data in negative_rates:
                        daily_rate = rate_data['funding_rate'] * 3
                        opportunities.append({
                            'symbol': rate_data['symbol'].replace('-USDT-SWAP', ''),
                            'funding_rate_percent': rate_data['funding_rate'] * 100,
                            'daily_rate_percent': abs(daily_rate * 100),
                            'daily_income_10k': abs(daily_rate * 10000),
                            'annual_rate_percent': abs(daily_rate * 365 * 100)
                        })
                    
                    opportunities.sort(key=lambda x: x['funding_rate_percent'])
                    
                    return {
                        "status": "success",
                        "message": f"发现 {len(opportunities)} 个负费率机会",
                        "opportunities": opportunities[:8],
                        "timestamp": datetime.now().isoformat()
                    }
                else:
                    return {
                        "status": "success",
                        "message": "当前无负费率机会",
                        "opportunities": [],
                        "timestamp": datetime.now().isoformat()
                    }
            else:
                return {
                    "status": "error",
                    "message": "负费率监控服务未启动",
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"获取负费率机会失败: {e}")
            raise HTTPException(status_code=500, detail="获取负费率机会失败")
    
    # 手动触发负费率监控
    @app.post("/test-funding-monitor", summary="手动触发负费率监控")
    async def test_funding_monitor():
        """手动触发负费率监控，用于测试推送功能"""
        try:
            if hasattr(app.state, 'funding_monitor'):
                funding_monitor = app.state.funding_monitor
                logger.info("🧪 手动触发负费率监控测试...")
                
                # 运行完整的监控周期
                result = await funding_monitor.run_monitoring_cycle(enable_enhanced_analysis=True)
                
                if result['success']:
                    return {
                        "status": "success",
                        "message": f"监控完成，发现 {result.get('negative_funding_count', 0)} 个负费率机会",
                        "data": {
                            "total_symbols_checked": result.get('total_symbols_checked', 0),
                            "opportunities_count": result.get('negative_funding_count', 0),
                            "duration_seconds": result.get('duration_seconds', 0),
                            "analysis_time": result.get('analysis_time')
                        },
                        "timestamp": datetime.now().isoformat()
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"监控失败: {result.get('error', '未知错误')}",
                        "timestamp": datetime.now().isoformat()
                    }
            else:
                return {
                    "status": "error",
                    "message": "负费率监控服务未启动",
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"手动触发负费率监控失败: {e}")
            raise HTTPException(status_code=500, detail=f"监控失败: {str(e)}")
    
    # 市场异常快速查看
    @app.get("/market-anomalies", summary="快速查看市场异常")
    async def get_market_anomalies():
        """快速查看当前市场异常情况"""
        try:
            if hasattr(app.state, 'market_anomaly_service'):
                service = app.state.market_anomaly_service
                logger.info("🔍 快速查看市场异常...")
                
                # 扫描异常（只返回推荐的）
                anomalies, total_checked = await service.scan_market_anomalies(
                    min_anomaly_level=AnomalyLevel.MEDIUM,
                    only_recommended=True
                )
                
                if anomalies:
                    # 构建简化的响应
                    top_anomalies = anomalies[:8]  # 只返回前8个
                    anomaly_list = []
                    
                    for anomaly in top_anomalies:
                        anomaly_list.append({
                            'symbol': anomaly.symbol_name,
                            'score': anomaly.anomaly_score,
                            'trend': anomaly.trend_direction.value,
                            'price_change_24h': f"{anomaly.price_change_24h * 100:+.1f}%",
                            'volume_ratio': f"{anomaly.volume_ratio:.1f}x",
                            'anomaly_level': anomaly.overall_anomaly_level.value,
                            'main_reason': anomaly.recommendation_reason[0] if anomaly.recommendation_reason else "",
                            'current_price': anomaly.current_price
                        })
                    
                    return {
                        "status": "success",
                        "message": f"发现 {len(anomalies)} 个市场异常",
                        "anomalies": anomaly_list,
                        "summary": {
                            "total_anomalies": len(anomalies),
                            "strong_uptrend": sum(1 for a in anomalies if a.trend_direction.value in ['strong_up', 'up']),
                            "high_volume": sum(1 for a in anomalies if a.volume_ratio > 2.0)
                        },
                        "timestamp": datetime.now().isoformat()
                    }
                else:
                    return {
                        "status": "success",
                        "message": "当前无显著市场异常",
                        "anomalies": [],
                        "summary": {
                            "total_anomalies": 0,
                            "strong_uptrend": 0,
                            "high_volume": 0
                        },
                        "timestamp": datetime.now().isoformat()
                    }
            else:
                return {
                    "status": "error",
                    "message": "市场异常监控服务未启动",
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"获取市场异常失败: {e}")
            raise HTTPException(status_code=500, detail="获取市场异常失败")
    
    # 手动触发市场异常监控
    @app.post("/test-market-anomaly-monitor", summary="手动触发市场异常监控")
    async def test_market_anomaly_monitor():
        """手动触发市场异常监控，用于测试推送功能"""
        try:
            if hasattr(app.state, 'market_anomaly_service'):
                service = app.state.market_anomaly_service
                logger.info("🧪 手动触发市场异常监控测试...")
                
                # 运行完整的监控周期
                result = await service.run_monitoring_cycle()
                
                if result['success']:
                    return {
                        "status": "success",
                        "message": f"监控完成，发现 {result.get('anomalies_found', 0)} 个异常，推荐 {result.get('recommended_count', 0)} 个",
                        "data": {
                            "anomalies_found": result.get('anomalies_found', 0),
                            "recommended_count": result.get('recommended_count', 0),
                            "notification_sent": result.get('anomalies_found', 0) > 0
                        },
                        "timestamp": result.get('timestamp')
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"监控失败: {result.get('error', '未知错误')}",
                        "timestamp": result.get('timestamp')
                    }
            else:
                return {
                    "status": "error",
                    "message": "市场异常监控服务未启动",
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"手动触发市场异常监控失败: {e}")
            raise HTTPException(status_code=500, detail=f"监控失败: {str(e)}")
    
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
    
    # Kronos持仓分析报告
    @app.get("/kronos-position-analysis", summary="Kronos持仓分析报告")
    async def get_kronos_position_analysis():
        """获取基于Kronos预测的持仓分析报告"""
        try:
            # 检查交易所类型，币安跳过持仓分析
            if settings.exchange_provider.lower() == 'binance':
                return {
                    "status": "skipped",
                    "message": "币安交易所暂不支持持仓分析功能",
                    "exchange_provider": "binance",
                    "timestamp": datetime.now().isoformat()
                }
            
            from app.services.ml.kronos_integrated_decision_service import get_kronos_integrated_service
            
            kronos_service = await get_kronos_integrated_service()
            
            # 分析主要持仓币种
            symbols = ["ETH-USDT-SWAP", "SOL-USDT-SWAP"]
            analysis_results = {}
            
            for symbol in symbols:
                decision = await kronos_service.get_kronos_enhanced_decision(symbol, force_update=True)
                if decision:
                    analysis_results[symbol] = {
                        "symbol": symbol.replace("-USDT-SWAP", ""),
                        "kronos_confidence": decision.kronos_confidence,
                        "signal_strength": decision.kronos_signal_strength.value,
                        "final_action": decision.final_action,
                        "final_confidence": decision.final_confidence,
                        "reasoning": decision.reasoning,
                        "kronos_analysis": getattr(decision, 'kronos_analysis', {}),
                        "position_recommendation": decision.position_recommendation.value if decision.position_recommendation else "无建议",
                        "risk_level": decision.position_risk.value if decision.position_risk else "未知"
                    }
            
            return {
                "status": "success",
                "message": f"Kronos持仓分析完成，分析了 {len(analysis_results)} 个币种",
                "analysis_results": analysis_results,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"获取Kronos持仓分析失败: {e}")
            raise HTTPException(status_code=500, detail="获取Kronos持仓分析失败")
    
    # 实时Kronos持仓分析 (基于实际持仓)
    @app.get("/kronos-live-position-analysis", summary="实时Kronos持仓分析")
    async def get_kronos_live_position_analysis():
        """获取基于实际持仓的Kronos分析报告"""
        try:
            # 检查交易所类型，币安跳过持仓分析
            if settings.exchange_provider.lower() == 'binance':
                return {
                    "status": "skipped",
                    "message": "币安交易所暂不支持实时持仓分析功能",
                    "exchange_provider": "binance",
                    "timestamp": datetime.now().isoformat()
                }
            
            from app.services.analysis.kronos_position_analysis_service import get_kronos_position_service
            
            kronos_position_service = await get_kronos_position_service()
            
            # 执行实时分析
            analysis_result = await kronos_position_service.get_manual_analysis()
            
            return {
                "status": "success",
                "message": "实时Kronos持仓分析完成",
                "analysis_result": analysis_result,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"获取实时Kronos持仓分析失败: {e}")
            raise HTTPException(status_code=500, detail="获取实时Kronos持仓分析失败")
    
    @app.get("/test-technical-config", summary="测试技术分析配置")
    async def test_technical_config():
        """测试技术分析配置是否正确"""
        try:
            from app.core.technical_analysis_config import get_technical_config
            
            config_manager = get_technical_config()
            config = config_manager.get_config()
            
            # 验证权重
            total_weight = sum(config.indicator_weights.values())
            
            return {
                "status": "success",
                "weights": config.indicator_weights,
                "total_weight": total_weight,
                "is_valid": total_weight == 100,
                "rsi_params": {
                    "period": config.rsi_period,
                    "overbought": config.rsi_overbought,
                    "oversold": config.rsi_oversold
                },
                "macd_params": {
                    "fast": config.macd_fast,
                    "slow": config.macd_slow,
                    "signal": config.macd_signal
                }
            }
            
        except Exception as e:
            logger.error(f"测试技术分析配置失败: {e}")
            return {"status": "error", "message": str(e)}
    
    @app.post("/test-enhanced-analysis", summary="测试增强的综合分析")
    async def test_enhanced_analysis(symbol: str = "BTC-USDT-SWAP"):
        """测试Kronos+技术分析+ML的综合分析"""
        try:
            from app.services.trading.core_trading_service import get_core_trading_service, AnalysisType
            
            core_trading_service = await get_core_trading_service()
            
            # 执行综合分析
            trading_signal = await core_trading_service.analyze_symbol(
                symbol=symbol,
                analysis_type=AnalysisType.INTEGRATED,
                force_update=True
            )
            
            if not trading_signal:
                return {"status": "error", "message": f"分析 {symbol} 失败"}
            
            # 构建详细的分析结果
            result = {
                "status": "success",
                "symbol": symbol,
                "analysis_time": trading_signal.timestamp.isoformat(),
                "final_decision": {
                    "action": trading_signal.final_action,
                    "confidence": trading_signal.final_confidence,
                    "signal_strength": trading_signal.signal_strength.value if hasattr(trading_signal.signal_strength, 'value') else str(trading_signal.signal_strength)
                },
                "analysis_breakdown": {
                    "kronos": {
                        "confidence": trading_signal.confidence_breakdown.get('kronos', 0),
                        "action": trading_signal.kronos_result.final_action if trading_signal.kronos_result else None,
                        "available": trading_signal.kronos_result is not None
                    },
                    "technical": {
                        "confidence": trading_signal.confidence_breakdown.get('technical', 0),
                        "action": trading_signal.technical_result.get('action') if trading_signal.technical_result else None,
                        "available": trading_signal.technical_result is not None
                    },
                    "ml": {
                        "confidence": trading_signal.confidence_breakdown.get('ml', 0),
                        "signal": trading_signal.ml_result.get('signal') if trading_signal.ml_result else None,
                        "available": trading_signal.ml_result is not None
                    }
                },
                "technical_indicators": trading_signal.technical_indicators,
                "key_factors": trading_signal.key_factors,
                "reasoning": trading_signal.reasoning,
                "entry_price": trading_signal.entry_price
            }
            
            # 测试推送通知
            notification_sent = await core_trading_service.send_trading_signal_notification(trading_signal)
            result["notification_sent"] = notification_sent
            
            return result
            
        except Exception as e:
            logger.error(f"测试增强分析失败: {e}")
            return {"status": "error", "message": str(e)}
    
    
    @app.post("/debug-funding-notification", summary="调试负费率通知")
    async def debug_funding_notification():
        """调试负费率通知消息格式"""
        try:
            from app.services.negative_funding_monitor_service import NegativeFundingMonitorService
            
            funding_monitor = NegativeFundingMonitorService()
            
            # 执行一次监控检查
            result = await funding_monitor.run_monitoring_cycle(enable_enhanced_analysis=True)
            
            if result['success']:
                notification_message = result.get('notification_message', '')
                opportunities = result.get('opportunities', [])
                
                return {
                    "status": "success",
                    "message_length": len(notification_message),
                    "opportunities_count": len(opportunities),
                    "notification_message": notification_message,
                    "first_100_chars": notification_message[:100],
                    "last_100_chars": notification_message[-100:] if len(notification_message) > 100 else notification_message,
                    "opportunities_summary": [
                        {
                            "symbol": opp.get('symbol_name', ''),
                            "rate": opp.get('funding_rate_percent', 0),
                            "score": opp.get('score', 0)
                        } for opp in opportunities[:3]
                    ]
                }
            else:
                return {
                    "status": "error",
                    "message": "监控检查失败",
                    "error": result.get('error', '未知错误')
                }
                
        except Exception as e:
            logger.error(f"调试负费率通知失败: {e}")
            return {
                "status": "error", 
                "message": str(e),
                "traceback": str(e.__traceback__)
            }
    
    # TradingView扫描器测试端点
    @app.post("/test-tradingview-scanner", summary="测试TradingView扫描器")
    async def test_tradingview_scanner():
        """测试TradingView扫描器功能"""
        try:
            if hasattr(app.state, 'tradingview_scheduler_service'):
                scheduler_service = app.state.tradingview_scheduler_service
                logger.info("🧪 手动测试TradingView扫描器...")
                
                # 执行手动扫描
                result = await scheduler_service.scan_and_notify()
                
                return {
                    "status": "success",
                    "message": f"TradingView扫描完成，发现 {result.get('symbols_count', 0)} 个强势币种",
                    "data": {
                        "symbols_count": result.get('symbols_count', 0),
                        "symbols": result.get('symbols', []),
                        "notification_sent": result.get('notification_sent', False),
                        "execution_time": result.get('execution_time')
                    },
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "status": "error",
                    "message": "TradingView调度服务未启动",
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"测试TradingView扫描器失败: {e}")
            raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")
    
    # TradingView扫描器状态查看
    @app.get("/tradingview-scanner-status", summary="查看TradingView扫描器状态")
    async def get_tradingview_scanner_status():
        """获取TradingView扫描器状态信息"""
        try:
            if hasattr(app.state, 'tradingview_scheduler_service'):
                scheduler_service = app.state.tradingview_scheduler_service
                
                # 获取调度器状态
                status = await scheduler_service.get_scheduler_status()
                
                # 获取健康检查
                health = await scheduler_service.health_check()
                
                return {
                    "status": "success",
                    "scheduler_status": status,
                    "health_check": health,
                    "startup_scan_result": getattr(app.state, 'startup_tradingview_scan', None),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "status": "error",
                    "message": "TradingView调度服务未启动",
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"获取TradingView扫描器状态失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")

    # 核心币种推送相关API
    @app.post("/api/core-symbols/push", summary="手动触发核心币种推送")
    async def manual_core_symbols_push():
        """手动触发核心币种操作建议推送"""
        try:
            logger.info("🧪 手动触发核心币种推送...")
            
            # 执行核心币种推送
            result = await perform_startup_core_symbols_push()
            
            if result["status"] == "success":
                return {
                    "status": "success",
                    "message": "核心币种推送完成",
                    "data": result,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "status": "error",
                    "message": f"核心币种推送失败: {result.get('error', '未知错误')}",
                    "data": result,
                    "timestamp": datetime.now().isoformat()
                }
                
        except Exception as e:
            logger.error(f"手动核心币种推送失败: {e}")
            raise HTTPException(status_code=500, detail=f"推送失败: {str(e)}")

    @app.get("/api/core-symbols/status", summary="查看核心币种推送状态")
    async def get_core_symbols_status():
        """获取核心币种推送状态信息"""
        try:
            # 获取启动推送状态
            startup_push_status = getattr(app.state, 'startup_core_symbols_push_results', {})
            
            # 检查统一调度器状态
            scheduler_running = hasattr(app.state, 'scheduler') and app.state.scheduler.is_running()
            
            return {
                "status": "success",
                "startup_push_completed": True,
                "startup_push_result": startup_push_status,
                "scheduler_running": scheduler_running,
                "integration_status": "核心币种推送已整合到统一调度器",
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"获取核心币种推送状态失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")

    @app.post("/api/core-symbols/scheduler/start", summary="启动核心币种定时推送")
    async def start_core_symbols_scheduler():
        """启动核心币种定时推送调度器"""
        try:
            # 检查统一调度器状态
            if hasattr(app.state, 'scheduler') and app.state.scheduler.is_running():
                return {
                    "status": "success",
                    "message": "核心币种推送任务已在统一调度器中运行",
                    "scheduler_info": {
                        "running": True,
                        "integration_status": "已整合到统一调度器"
                    },
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "status": "error",
                    "message": "统一调度器未运行",
                    "timestamp": datetime.now().isoformat()
                }
            
        except Exception as e:
            logger.error(f"检查核心币种调度器状态失败: {e}")
            raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")

    @app.post("/api/core-symbols/scheduler/stop", summary="停止核心币种定时推送")
    async def stop_core_symbols_scheduler():
        """停止核心币种定时推送调度器"""
        try:
            return {
                "status": "info",
                "message": "核心币种推送任务已整合到统一调度器中，无法单独停止",
                "note": "如需停止，请停止整个应用或使用统一调度器管理接口",
                "timestamp": datetime.now().isoformat()
            }
                
        except Exception as e:
            logger.error(f"停止核心币种调度器失败: {e}")
            raise HTTPException(status_code=500, detail=f"停止失败: {str(e)}")
    
    # 网格交易相关测试端点
    @app.post("/test-grid-trading", summary="测试网格交易推荐")
    async def test_grid_trading():
        """手动测试网格交易机会推荐"""
        try:
            if hasattr(app.state, 'grid_scheduler_extension') and app.state.grid_scheduler_extension:
                grid_extension = app.state.grid_scheduler_extension
                logger.info("🧪 手动测试网格交易推荐...")
                
                # 执行网格交易推荐
                success = await grid_extension.run_startup_grid_recommendations()
                
                if success:
                    return {
                        "status": "success",
                        "message": "网格交易推荐测试完成",
                        "timestamp": datetime.now().isoformat()
                    }
                else:
                    return {
                        "status": "warning",
                        "message": "网格交易推荐测试失败",
                        "timestamp": datetime.now().isoformat()
                    }
            else:
                return {
                    "status": "error",
                    "message": "网格交易调度器扩展未初始化",
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"测试网格交易推荐失败: {e}")
            raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")
    
    @app.get("/grid-trading-status", summary="查看网格交易推荐状态")
    async def get_grid_trading_status():
        """获取网格交易推荐状态信息"""
        try:
            if hasattr(app.state, 'grid_scheduler_extension') and app.state.grid_scheduler_extension:
                grid_extension = app.state.grid_scheduler_extension
                
                return {
                    "status": "success",
                    "extension_initialized": True,
                    "startup_analysis_result": getattr(app.state, 'startup_grid_trading_analysis_results', None),
                    "message": "网格交易调度器扩展运行正常",
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "status": "error",
                    "extension_initialized": False,
                    "message": "网格交易调度器扩展未初始化",
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"获取网格交易状态失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")
    
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
