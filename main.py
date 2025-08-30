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

# 安全导入数据库模块
try:
    from app.core.database import create_tables, db_manager
    from app.utils.db_monitor import get_db_monitor
    DATABASE_AVAILABLE = True
    logger = get_logger(__name__)
    logger.debug("✅ Database module imported successfully")
except Exception as e:
    logger = get_logger(__name__)
    logger.warning(f"⚠️ Database module import failed: {e}")
    logger.info("💡 Application will run in memory-only mode")
    DATABASE_AVAILABLE = False
    db_manager = None
    create_tables = None
    get_db_monitor = None

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
from app.api.notification_stats import router as notification_stats_router
from app.api.database import router as database_router
from app.api.http_pool import router as http_pool_router
from app.api.trading_pairs import router as trading_pairs_router
from app.api.unified_data import router as unified_data_router
from app.api.ml_config import router as ml_config_router
from app.services.scheduler_service import SchedulerService
from app.services.ml_enhanced_service import MLEnhancedService
from app.services.negative_funding_monitor_service import NegativeFundingMonitorService

# 获取配置和日志
settings = get_settings()
logger = get_logger(__name__)

async def perform_startup_trading_analysis():
    """启动时执行完整的交易决策分析和推送 - 使用Kronos+传统+ML的综合决策服务"""
    try:
        logger.info("🎯 开始启动完整交易决策分析 (Kronos+传统+ML综合)...")
        
        # 使用增强的核心交易服务，集成Kronos分析
        from app.services.core_trading_service import get_core_trading_service, AnalysisType
        from app.services.core_notification_service import get_core_notification_service
        
        core_trading_service = await get_core_trading_service()
        notification_service = await get_core_notification_service()
        
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

# 已移除 perform_startup_kronos_market_scan() 函数
# 原因: 与 perform_startup_trading_analysis() 功能重复
# 核心交易决策分析已经包含了Kronos分析和信号推送功能

async def send_startup_summary_notification(app_state, successful_tasks: int, failed_tasks: int):
    """发送启动完成摘要通知"""
    try:
        from app.services.core_notification_service import get_core_notification_service
        notification_service = await get_core_notification_service()
        
        # 收集各任务结果
        trading_result = getattr(app_state, 'startup_trading_analysis_results', {})
        funding_result = getattr(app_state, 'startup_funding_analysis_results', {})
        news_result = getattr(app_state, 'startup_news_analysis_results', {})
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
        
        # 新闻分析结果 - 暂时注释掉
        # if news_result.get("status") == "success":
        #     news_notifications = news_result.get("notifications_sent", 0)
        #     message += f"📰 新闻分析: {news_notifications} 条重要新闻\n"
        # elif news_result.get("status") == "disabled":
        #     message += f"📴 新闻分析: 已禁用\n"
        
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
            kronos_result.get("summary", {}).get("total_strong_opportunities", 0)
        )
        
        priority = "high" if total_signals > 0 else "medium" if failed_tasks == 0 else "low"
        
        from app.services.core_notification_service import NotificationContent, NotificationType, NotificationPriority
        
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

async def perform_startup_news_analysis():
    """启动时执行新闻分析和推送"""
    try:
        logger.info("📰 开始启动新闻分析...")
        
        from app.services.news_monitor_service import get_news_monitor_service
        
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
        from app.services.core_notification_service import get_core_notification_service
        notification_service = await get_core_notification_service()
        
        # 导入异常状态管理器
        from app.services.anomaly_state_manager import anomaly_state_manager
        
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
    cleanup_tasks = []
    
    try:
        # 检查数据库模块是否可用
        if not DATABASE_AVAILABLE:
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
        
        # 启动调度器
        scheduler = SchedulerService()
        await scheduler.start()
        logger.info("✅ Scheduler started successfully")
        
        # 暂时禁用智能交易机会扫描任务 - 避免重复推送
        # from app.services.intelligent_trading_notification_service import IntelligentTradingNotificationService
        # intelligent_notification_service = IntelligentTradingNotificationService()
        logger.info("📴 智能交易机会扫描已禁用 - 使用核心交易服务的详细推送")
        
        # ❌ 已移除重复的Kronos市场机会扫描服务 - 已整合到调度器的趋势分析任务中
        # 原因: 避免与调度器中的_trend_analysis_job重复分析相同币种
        # 新的整合方案: 调度器中的趋势分析任务已增强为"Kronos核心信号分析"，每15分钟执行
        
        # if settings.kronos_config.get('enable_kronos_prediction', False):
        #     from app.services.kronos_market_opportunity_service import get_kronos_market_opportunity_service
        #     
        #     async def kronos_strong_opportunities_scan():
        #         """Kronos强交易机会扫描 - 每30分钟 (已移除，避免重复)"""
        #         # 此功能已整合到调度器的_trend_analysis_job中
        #         pass
        #     
        #     # 移除重复的扫描任务
        #     # scheduler.add_job(kronos_strong_opportunities_scan, ...)
        #     
        #     logger.info("🔄 Kronos强交易机会扫描已整合到调度器趋势分析任务中")
        # else:
        #     logger.info("📴 Kronos预测已禁用")
        
        # 📝 优化说明: 
        # 1. 原来的市场扫描任务(每30分钟) + 趋势分析任务(每15分钟) = 重复分析
        # 2. 现在统一为调度器中的"Kronos核心信号分析"任务(每15分钟)
        # 3. 提供更详细的技术分析和精准的交易建议
        
        if settings.kronos_config.get('enable_kronos_prediction', False):
            logger.info("✅ Kronos预测已启用，核心信号分析由调度器统一管理")
        else:
            logger.info("📴 Kronos预测已禁用")
        
        # 添加负费率监控定时任务
        funding_monitor = NegativeFundingMonitorService()
        
        # 每20分钟检查一次负费率机会（使用增强版分析）
        scheduler.add_job(
            lambda: funding_monitor.run_monitoring_cycle(enable_enhanced_analysis=True),
            'interval',
            minutes=20,
            id='negative_funding_monitor',
            name='负费率吃利息机会监控（增强版）'
        )
        logger.info("✅ Negative funding rate monitor scheduled")
        
        # 添加新闻监控定时任务 - 暂时注释掉
        # if settings.news_config.get('enable_news_analysis', True):
        #     from app.services.news_monitor_service import get_news_monitor_service
        #     
        #     news_monitor = await get_news_monitor_service()
        #     
        #     # 获取新闻监控间隔配置
        #     news_interval = settings.news_config.get('fetch_interval_minutes', 30)
        #     
        #     scheduler.add_job(
        #         news_monitor.run_monitoring_cycle,
        #         'interval',
        #         minutes=news_interval,
        #         id='news_monitor',
        #         name='新闻分析监控'
        #     )
        #     logger.info(f"✅ News analysis monitor scheduled (every {news_interval} minutes)")
        #     
        #     # 将新闻监控服务存储到应用状态
        #     app.state.news_monitor = news_monitor
        # else:
        #     logger.info("📴 News analysis monitoring disabled")
        
        # 将负费率监控服务存储到应用状态
        app.state.funding_monitor = funding_monitor
        
        # 添加Kronos持仓分析定时任务
        if settings.kronos_config.get('enable_kronos_prediction', False):
            from app.services.kronos_position_analysis_service import get_kronos_position_service
            
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
        
        # 🚀 启动时并发执行所有分析任务 - 异步优化
        logger.info("🚀 开始并发执行启动分析任务...")
        startup_tasks = []
        
        # 1. 核心交易决策分析任务
        startup_tasks.append(("trading_analysis", perform_startup_trading_analysis()))
        
        # 2. 负费率分析任务
        startup_tasks.append(("funding_analysis", perform_startup_funding_analysis()))
        
        # 3. 新闻分析任务 (如果启用) - 暂时注释掉
        # if settings.news_config.get('enable_news_analysis', True):
        #     startup_tasks.append(("news_analysis", perform_startup_news_analysis()))
        
        # 4. Kronos市场机会扫描任务 - 已整合到核心交易决策分析中，避免重复推送
        # 原因: perform_startup_trading_analysis() 已经包含了Kronos分析功能
        # 不再需要单独的市场扫描任务
        logger.info("🔄 Kronos市场扫描已整合到核心交易决策分析中，避免重复推送")
        
        # 并发执行所有启动任务
        task_names = [name for name, _ in startup_tasks]
        task_coroutines = [task for _, task in startup_tasks]
        
        logger.info(f"📊 准备并发执行 {len(task_coroutines)} 个启动任务: {task_names}")
        
        # 使用 asyncio.gather 并发执行，允许部分失败
        startup_results = await asyncio.gather(*task_coroutines, return_exceptions=True)
        
        # 处理并发执行结果
        successful_tasks = 0
        failed_tasks = 0
        
        for i, (task_name, result) in enumerate(zip(task_names, startup_results)):
            if isinstance(result, Exception):
                logger.warning(f"⚠️ 启动任务 {task_name} 失败: {result}")
                setattr(app.state, f"startup_{task_name}_results", {"status": "error", "error": str(result)})
                failed_tasks += 1
            else:
                logger.info(f"✅ 启动任务 {task_name} 完成")
                setattr(app.state, f"startup_{task_name}_results", result)
                successful_tasks += 1
        
        # 记录并发执行总结
        total_tasks = len(task_coroutines)
        logger.info(f"🎯 启动任务并发执行完成: {successful_tasks}/{total_tasks} 成功, {failed_tasks} 失败")
        
        # 设置默认状态 (兼容性)
        if not hasattr(app.state, 'startup_news_analysis_results'):
            app.state.startup_news_analysis_results = {"status": "disabled"}
        if not hasattr(app.state, 'startup_kronos_market_scan_results'):
            app.state.startup_kronos_market_scan_results = {"status": "disabled"}
        
        # 🚫 不再发送启动完成摘要通知 - 根据用户要求过滤系统状态信息
        # await send_startup_summary_notification(app.state, successful_tasks, failed_tasks)
        logger.info("📊 启动摘要通知已禁用 - 系统状态信息不推送")
        
        # 初始化Kronos预测服务（可选）
        if settings.kronos_config.get('enable_kronos_prediction', False):
            try:
                from app.services.kronos_prediction_service import get_kronos_service
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
                
                # 启动时ML增强分析 - 已停用避免异常检测报告推送
                # await perform_startup_ml_analysis(ml_service)
                logger.info("⚠️ 启动时ML异常检测已停用避免重复推送")
                
            except Exception as e:
                logger.warning(f"⚠️ ML增强服务初始化失败: {e}")
                app.state.ml_service = None
        
        # 将服务实例存储到应用状态
        app.state.scheduler = scheduler
        
        logger.info("🎉 Application startup completed!")
        
        yield
        
        # 应用关闭时的清理工作
        logger.info("🛑 Shutting down application...")
        
        # 1. 停止调度器
        try:
            if hasattr(app.state, 'scheduler') and app.state.scheduler:
                await app.state.scheduler.shutdown()
                logger.info("✅ Scheduler stopped")
        except Exception as e:
            logger.warning(f"⚠️ Error stopping scheduler: {e}")
        
        # 2. 清理核心HTTP客户端
        try:
            from app.core.http_client import cleanup_http_resources
            await cleanup_http_resources()
            logger.info("✅ Core HTTP client cleaned up")
        except Exception as e:
            logger.warning(f"⚠️ Error cleaning up core HTTP client: {e}")
        
        # 3. 清理 OKX 服务连接
        try:
            from app.services.okx_service import cleanup_all_sessions
            await cleanup_all_sessions()
            logger.info("✅ OKX HTTP connections cleaned up")
        except Exception as e:
            logger.warning(f"⚠️ Error cleaning up OKX connections: {e}")
        
        # 4. 通用 HTTP 连接清理（兼容性）
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
            if db_manager:
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
    
    # 原有路由 - 保持兼容性
    app.include_router(trend_router, prefix="/api/trend", tags=["趋势分析"])
    app.include_router(monitor_router, prefix="/api/monitor", tags=["监控服务"])
    app.include_router(notification_router, prefix="/api/notification", tags=["通知服务"])
    app.include_router(tradingview_router, prefix="/api/tradingview", tags=["TradingView功能"])
    app.include_router(strategy_router, prefix="/api/strategy", tags=["策略分析"])
    app.include_router(ml_enhanced_router, prefix="/api/ml", tags=["机器学习增强"])
    app.include_router(backtest_router, prefix="/api", tags=["回测分析"])
    app.include_router(funding_monitor_router, prefix="/api/funding", tags=["负费率监控"])
    app.include_router(kronos_router, prefix="/api/kronos", tags=["Kronos AI预测"])
    app.include_router(kronos_integrated_router, prefix="/api/kronos-integrated", tags=["Kronos集成决策"])
    app.include_router(kronos_market_opportunities_router, prefix="/api/kronos-opportunities", tags=["Kronos市场机会"])
    app.include_router(kronos_advanced_opportunities_router, prefix="/api/kronos-advanced", tags=["Kronos高级机会"])
    app.include_router(notification_stats_router)
    app.include_router(database_router, prefix="/api/database", tags=["数据库管理"])
    app.include_router(http_pool_router, prefix="/api/http-pool", tags=["HTTP连接池管理"])
    app.include_router(trading_pairs_router, prefix="/api/trading-pairs", tags=["交易对管理"])
    app.include_router(unified_data_router, prefix="/api", tags=["统一数据服务"])
    app.include_router(ml_config_router, prefix="/api/ml-config", tags=["ML配置管理"])
    app.include_router(news_router, prefix="/api/news", tags=["新闻分析"])
    
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
                "connection_pool": pool_stats,
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
            from app.services.kronos_market_opportunity_service import get_kronos_market_opportunity_service
            
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
                
                # 使用OKX服务获取费率数据
                async with funding_monitor.okx_service:
                    funding_rates = await funding_monitor.okx_service.get_batch_funding_rates(hot_symbols[:15])
                
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
            from app.services.kronos_integrated_decision_service import get_kronos_integrated_service
            
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
            from app.services.kronos_position_analysis_service import get_kronos_position_service
            
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
    
    # 调试交易信号分析
    @app.get("/debug-trading-signals", summary="调试交易信号分析")
    async def debug_trading_signals():
        """调试交易信号分析，帮助诊断为什么没有推送交易信号"""
        try:
            from app.services.intelligent_trading_notification_service import get_intelligent_notification_service
            
            intelligent_service = await get_intelligent_notification_service()
            debug_results = await intelligent_service.debug_signal_analysis()
            
            return {
                "status": "success",
                "message": "交易信号调试分析完成",
                "debug_results": debug_results
            }
        except Exception as e:
            logger.error(f"调试交易信号分析失败: {e}")
            raise HTTPException(status_code=500, detail="调试交易信号分析失败")
    
    # 强制扫描交易机会
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
            from app.services.core_trading_service import get_core_trading_service, AnalysisType
            
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
    
    @app.post("/force-scan-opportunities", summary="强制扫描交易机会")
    async def force_scan_opportunities():
        """强制扫描交易机会并推送通知"""
        try:
            from app.services.intelligent_trading_notification_service import get_intelligent_notification_service
            
            intelligent_service = await get_intelligent_notification_service()
            scan_results = await intelligent_service.scan_and_notify_opportunities(force_scan=True)
            
            return {
                "status": "success",
                "message": "强制扫描交易机会完成",
                "scan_results": scan_results
            }
        except Exception as e:
            logger.error(f"强制扫描交易机会失败: {e}")
            raise HTTPException(status_code=500, detail="强制扫描交易机会失败")
    
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
