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
from app.utils.db_monitor import get_db_monitor

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
from app.services.scheduler_service import SchedulerService
from app.services.ml_enhanced_service import MLEnhancedService
from app.services.ml_notification_service import MLNotificationService
from app.services.negative_funding_monitor_service import NegativeFundingMonitorService

# 获取配置和日志
settings = get_settings()
logger = get_logger(__name__)

async def perform_startup_trading_analysis():
    """启动时执行交易分析和推送 - 使用核心交易服务"""
    try:
        logger.info("🎯 开始启动交易决策分析 (核心服务)...")
        
        # 导入核心交易服务
        from app.services.core_trading_service import get_core_trading_service, AnalysisType, SignalStrength
        
        core_trading_service = await get_core_trading_service()
        
        # 主要分析的交易对
        major_symbols = ["ETH-USDT-SWAP", "SOL-USDT-SWAP"]
        
        # 执行批量分析
        analysis_results = await core_trading_service.batch_analyze_symbols(
            symbols=major_symbols,
            analysis_type=AnalysisType.INTEGRATED,
            max_concurrent=3
        )
        
        # 处理分析结果
        successful_analyses = sum(1 for result in analysis_results.values() if result is not None)
        strong_signals = []
        notifications_sent = 0
        
        for symbol, signal in analysis_results.items():
            if signal and signal.signal_strength in [SignalStrength.STRONG, SignalStrength.VERY_STRONG]:
                strong_signals.append({
                    "symbol": symbol,
                    "action": signal.final_action,
                    "confidence": signal.final_confidence,
                    "strength": signal.signal_strength.value,
                    "source": "core_integrated",
                    "kronos_confidence": signal.kronos_result.kronos_confidence if signal.kronos_result else 0,
                    "kronos_signal_strength": signal.kronos_result.kronos_signal_strength.value if signal.kronos_result else "未知"
                })
                
                # 发送强信号通知
                try:
                    success = await core_trading_service.send_trading_signal_notification(signal)
                    if success:
                        notifications_sent += 1
                except Exception as e:
                    logger.warning(f"发送 {symbol} 信号通知失败: {e}")
        
        # 构建返回结果
        startup_results = {
            "status": "success",
            "total_analyzed": len(major_symbols),
            "successful_analyses": successful_analyses,
            "notifications_sent": notifications_sent,
            "strong_signals": strong_signals,
            "analysis_method": "core_integrated_service"
        }
        
        # 记录分析结果
        logger.info(f"✅ 启动交易分析完成 (核心服务):")
        logger.info(f"   📊 分析成功: {successful_analyses}/{len(major_symbols)}")
        logger.info(f"   📢 通知发送: {notifications_sent} 条")
        logger.info(f"   🔥 强信号: {len(strong_signals)} 个")
        
        # 记录强信号详情
        for signal in strong_signals[:3]:
            symbol = signal["symbol"]
            action = signal["action"]
            confidence = signal["confidence"]
            strength = signal["strength"]
            kronos_conf = signal.get("kronos_confidence", 0)
            
            if kronos_conf > 0:
                logger.info(f"   🤖 {symbol}: {action} (综合: {confidence:.2f}, Kronos: {kronos_conf:.2f}, 强度: {strength})")
            else:
                logger.info(f"   🚀 {symbol}: {action} (置信度: {confidence:.2f}, 强度: {strength})")
        
        return startup_results
        
    except Exception as e:
        logger.error(f"❌ 启动交易分析失败 (核心服务): {e}")
        return {"status": "error", "error": str(e)}

async def perform_startup_kronos_analysis():
    """启动时执行专门的Kronos集成分析"""
    try:
        logger.info("🤖 开始专门的Kronos集成分析...")
        
        from app.services.kronos_integrated_decision_service import get_kronos_integrated_service
        
        # 获取Kronos集成服务
        kronos_service = await get_kronos_integrated_service()
        
        # 主要交易对列表 - 只分析ETH和SOL
        major_symbols = [
            "ETH-USDT", "SOL-USDT"
        ]
        
        # 批量Kronos分析
        kronos_results = await kronos_service.batch_analyze_symbols(major_symbols, force_update=True)
        
        # 筛选强信号
        strong_kronos_signals = []
        for symbol, decision in kronos_results.items():
            if decision and decision.kronos_confidence >= 0.7:
                if decision.kronos_signal_strength.value in ["强", "极强"]:
                    strong_kronos_signals.append({
                        "symbol": symbol,
                        "action": decision.final_action,
                        "kronos_confidence": decision.kronos_confidence,
                        "signal_strength": decision.kronos_signal_strength.value,
                        "final_confidence": decision.final_confidence,
                        "reasoning": decision.reasoning
                    })
        
        # 记录结果
        successful_count = sum(1 for r in kronos_results.values() if r is not None)
        logger.info(f"✅ Kronos专门分析完成: {successful_count}/{len(major_symbols)} 个成功")
        logger.info(f"🔥 发现 {len(strong_kronos_signals)} 个强Kronos信号")
        
        # 记录强信号详情
        for signal in strong_kronos_signals[:3]:
            symbol = signal["symbol"]
            action = signal["action"]
            kronos_conf = signal["kronos_confidence"]
            strength = signal["signal_strength"]
            logger.info(f"   🚀 {symbol}: {action} (Kronos: {kronos_conf:.2f}, 强度: {strength})")
        
        return {
            "status": "success",
            "total_analyzed": len(major_symbols),
            "successful_analyses": successful_count,
            "strong_signals": strong_kronos_signals,
            "all_results": kronos_results
        }
        
    except Exception as e:
        logger.error(f"❌ Kronos专门分析失败: {e}")
        return {"status": "error", "error": str(e)}

async def perform_startup_funding_analysis():
    """启动时执行负费率分析和推送"""
    try:
        logger.info("💰 开始负费率吃利息机会分析...")
        
        # 创建负费率监控服务
        funding_monitor = NegativeFundingMonitorService()
        
        # 执行监控检查
        result = await funding_monitor.run_monitoring_cycle()
        
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

async def perform_startup_ml_analysis(ml_service: MLEnhancedService):
    """启动时执行ML分析和推送（可选）"""
    try:
        logger.info("🤖 开始ML增强分析...")
        ml_notification_service = MLNotificationService()
        
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
                    await ml_notification_service.send_ml_prediction_alert(prediction)
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
                
                await ml_notification_service.send_anomaly_alert(top_anomalies)
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
        # 尝试创建数据库表 - 允许失败
        try:
            create_tables()
            logger.info("✅ Database tables created successfully")
        except Exception as e:
            logger.warning(f"⚠️ Database table creation failed: {e}")
            logger.info("💡 Application will continue without database persistence")
        
        # 测试数据库连接和连接池 - 允许在数据库不可用时继续运行
        try:
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
        except Exception as e:
            logger.warning(f"⚠️ Database health check failed: {e} - running in memory mode")
            app.state.database_available = False
        
        # 启动调度器
        scheduler = SchedulerService()
        await scheduler.start()
        logger.info("✅ Scheduler started successfully")
        
        # 添加智能交易机会扫描任务
        from app.services.intelligent_trading_notification_service import IntelligentTradingNotificationService
        intelligent_notification_service = IntelligentTradingNotificationService()
        
        # 使用新的Kronos市场机会扫描服务
        if settings.kronos_config.get('enable_kronos_prediction', False):
            from app.services.kronos_market_opportunity_service import get_kronos_market_opportunity_service
            
            async def kronos_strong_opportunities_scan():
                """Kronos强交易机会扫描 - 每30分钟"""
                try:
                    logger.info("🤖 开始Kronos强交易机会扫描...")
                    market_service = await get_kronos_market_opportunity_service()
                    
                    result = await market_service.scan_strong_trading_opportunities(force_scan=False)
                    
                    if result.get("status") == "success":
                        opportunities = result.get("opportunities_found", 0)
                        notifications = result.get("notifications_sent", 0)
                        logger.info(f"✅ Kronos强机会扫描完成: 发现 {opportunities} 个机会，发送 {notifications} 条通知")
                    elif result.get("status") == "skipped":
                        logger.debug("📊 Kronos强机会扫描跳过（未到间隔时间）")
                    else:
                        logger.warning(f"⚠️ Kronos强机会扫描异常: {result.get('message', '未知')}")
                        
                except Exception as e:
                    logger.error(f"❌ Kronos强机会扫描失败: {e}")
            
            async def kronos_grid_opportunities_scan():
                """Kronos网格交易机会扫描 - 每2小时"""
                try:
                    logger.info("🎯 开始Kronos网格交易机会扫描...")
                    market_service = await get_kronos_market_opportunity_service()
                    
                    result = await market_service.scan_grid_trading_opportunities(force_scan=False)
                    
                    if result.get("status") == "success":
                        opportunities = result.get("grid_opportunities", 0)
                        notifications = result.get("notifications_sent", 0)
                        logger.info(f"✅ Kronos网格扫描完成: 发现 {opportunities} 个网格机会，发送 {notifications} 条通知")
                    elif result.get("status") == "skipped":
                        logger.debug("📊 Kronos网格扫描跳过（未到间隔时间）")
                    else:
                        logger.warning(f"⚠️ Kronos网格扫描异常: {result.get('message', '未知')}")
                        
                except Exception as e:
                    logger.error(f"❌ Kronos网格扫描失败: {e}")
            
            # 添加强交易机会扫描任务（每30分钟）
            scheduler.add_job(
                kronos_strong_opportunities_scan,
                'interval',
                minutes=30,
                id='kronos_strong_opportunities_scan',
                name='Kronos强交易机会扫描'
            )
            logger.info("✅ Kronos强交易机会扫描已启动（30分钟间隔）")
            
            # 添加网格交易机会扫描任务（每2小时）
            scheduler.add_job(
                kronos_grid_opportunities_scan,
                'interval',
                hours=2,
                id='kronos_grid_opportunities_scan',
                name='Kronos网格交易机会扫描'
            )
            logger.info("✅ Kronos网格交易机会扫描已启动（2小时间隔）")

            # 添加Kronos动量扫描任务（每10分钟）
            from app.services.kronos_momentum_scanner_service import get_kronos_momentum_scanner
            
            async def kronos_momentum_scan():
                """Kronos动量机会扫描"""
                try:
                    scanner = await get_kronos_momentum_scanner()
                    result = await scanner.scan_momentum_opportunities()
                    
                    if result.get("status") == "success":
                        signals = result.get("signals_found", 0)
                        strong_signals = result.get("strong_signals", 0)
                        logger.info(f"✅ Kronos动量扫描完成: 发现 {signals} 个信号，{strong_signals} 个强信号")
                    elif result.get("status") == "skipped":
                        logger.debug("📊 Kronos动量扫描跳过（未到间隔时间）")
                    else:
                        logger.warning(f"⚠️ Kronos动量扫描异常: {result.get('error', '未知错误')}")
                except Exception as e:
                    logger.error(f"❌ Kronos动量扫描失败: {e}")
            
            scheduler.add_job(
                kronos_momentum_scan,
                'interval',
                minutes=10,
                id='kronos_momentum_scan',
                name='Kronos动量机会扫描'
            )
            logger.info("✅ Kronos动量机会扫描已启动（10分钟间隔）")

        else:
            logger.info("📴 Kronos预测已禁用，跳过所有Kronos扫描任务")
        
        # 添加负费率监控定时任务
        funding_monitor = NegativeFundingMonitorService()
        
        # 每30分钟检查一次负费率机会
        scheduler.add_job(
            funding_monitor.run_monitoring_cycle,
            'interval',
            minutes=30,
            id='negative_funding_monitor',
            name='负费率吃利息机会监控'
        )
        logger.info("✅ Negative funding rate monitor scheduled")
        
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
                # 每30分钟执行一次Kronos持仓分析和推送
                scheduler.add_job(
                    kronos_position_service.run_scheduled_analysis,
                    'interval',
                    minutes=30,
                    id='kronos_position_analysis',
                    name='Kronos持仓分析和风险评估',
                    max_instances=1  # 确保同时只有一个实例运行
                )
                logger.info("✅ Kronos持仓分析定时任务已启动 (每30分钟)")
            
            # 将服务存储到应用状态
            app.state.kronos_position_service = kronos_position_service
        
        # 启动时交易决策分析 - 使用新的核心服务
        try:
            startup_results = await perform_startup_trading_analysis()
            app.state.startup_analysis_results = startup_results
        except Exception as e:
            logger.warning(f"⚠️ 启动交易分析失败: {e}")
            app.state.startup_analysis_results = {"status": "error", "error": str(e)}
        
        # 启动时执行负费率分析和推送
        try:
            funding_results = await perform_startup_funding_analysis()
            app.state.startup_funding_results = funding_results
        except Exception as e:
            logger.warning(f"⚠️ 启动负费率分析失败: {e}")
            app.state.startup_funding_results = {"status": "error", "error": str(e)}
        
        # 启动时执行Kronos市场机会扫描
        if settings.kronos_config.get('enable_kronos_prediction', False):
            try:
                # 执行启动时的市场机会扫描
                from app.services.kronos_market_opportunity_service import get_kronos_market_opportunity_service
                
                market_service = await get_kronos_market_opportunity_service()
                
                # 并行执行强信号和网格机会扫描
                import asyncio
                strong_task = market_service.scan_strong_trading_opportunities(force_scan=True)
                grid_task = market_service.scan_grid_trading_opportunities(force_scan=True)
                
                strong_result, grid_result = await asyncio.gather(strong_task, grid_task)
                
                # 汇总启动扫描结果
                startup_scan_results = {
                    "status": "success",
                    "scan_time": datetime.now(),
                    "strong_opportunities": strong_result,
                    "grid_opportunities": grid_result,
                    "summary": {
                        "total_strong_opportunities": strong_result.get("opportunities_found", 0),
                        "total_grid_opportunities": grid_result.get("grid_opportunities", 0),
                        "total_notifications": (
                            strong_result.get("notifications_sent", 0) + 
                            grid_result.get("notifications_sent", 0)
                        )
                    }
                }
                
                app.state.startup_kronos_results = startup_scan_results
                
                # 记录启动扫描结果
                strong_count = startup_scan_results["summary"]["total_strong_opportunities"]
                grid_count = startup_scan_results["summary"]["total_grid_opportunities"]
                total_notifications = startup_scan_results["summary"]["total_notifications"]
                
                logger.info(f"🤖 Kronos启动市场扫描完成:")
                logger.info(f"   🚀 强交易机会: {strong_count} 个")
                logger.info(f"   🎯 网格机会: {grid_count} 个")
                logger.info(f"   📢 发送通知: {total_notifications} 条")
                
                # 如果有机会发现，发送启动摘要通知
                if strong_count > 0 or grid_count > 0:
                    from app.services.notification_service import NotificationService
                    notification_service = NotificationService()
                    
                    message = f"🤖 **Kronos启动市场扫描完成**\n\n"
                    
                    if strong_count > 0:
                        message += f"🚀 发现 {strong_count} 个强交易机会\n"
                        # 显示前3个强机会
                        top_strong = strong_result.get("top_opportunities", [])[:3]
                        for i, opp in enumerate(top_strong, 1):
                            symbol = opp.get("symbol", "").replace("-USDT-SWAP", "")
                            direction = opp.get("direction", "")
                            score = opp.get("opportunity_score", 0)
                            message += f"   {i}. {symbol} {direction} (评分: {score:.0f})\n"
                        message += "\n"
                    
                    if grid_count > 0:
                        message += f"🎯 发现 {grid_count} 个网格交易机会\n"
                        # 显示前3个网格机会
                        top_grid = grid_result.get("top_grid_opportunities", [])[:3]
                        for i, opp in enumerate(top_grid, 1):
                            symbol = opp.get("symbol", "").replace("-USDT-SWAP", "")
                            score = opp.get("opportunity_score", 0)
                            message += f"   {i}. {symbol} 网格 (评分: {score:.0f})\n"
                        message += "\n"
                    
                    message += f"⏰ 扫描时间: {datetime.now().strftime('%H:%M:%S')}\n"
                    message += f"💡 仅推送Kronos AI识别的高质量机会"
                    
                    await notification_service.send_notification(
                        title=f"🤖 Kronos启动扫描: {strong_count + grid_count}个机会",
                        message=message,
                        notification_type="kronos_startup_scan",
                        priority="high" if strong_count > 0 else "medium"
                    )
                        
            except Exception as e:
                logger.warning(f"⚠️ Kronos启动市场扫描失败: {e}")
                app.state.startup_kronos_results = {"status": "error", "error": str(e)}
        else:
            logger.info("📴 Kronos预测已禁用，跳过启动市场扫描")
            app.state.startup_kronos_results = {"status": "disabled"}
        
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
            if hasattr(app.state, 'database_available') and app.state.database_available:
                from app.core.database import db_manager
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
            from app.core.database import db_manager
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
                funding_rates = await funding_monitor.get_batch_funding_rates(hot_symbols[:15], batch_size=5)
                
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
