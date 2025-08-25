# -*- coding: utf-8 -*-
"""
Kronos高级机会API
提供套利、动量、巨鲸追踪等高级交易机会接口
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Optional, Any
from datetime import datetime

from app.core.logging import get_logger
from app.services.kronos_arbitrage_scanner_service import get_kronos_arbitrage_scanner
from app.services.kronos_momentum_scanner_service import get_kronos_momentum_scanner
from app.services.kronos_whale_tracker_service import get_kronos_whale_tracker

router = APIRouter()
logger = get_logger(__name__)


@router.get("/arbitrage-scan", summary="Kronos套利机会扫描")
async def scan_arbitrage_opportunities():
    """扫描Kronos套利机会"""
    try:
        scanner = await get_kronos_arbitrage_scanner()
        result = await scanner.scan_arbitrage_opportunities()
        
        return {
            "status": "success",
            "data": result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"套利扫描API失败: {e}")
        raise HTTPException(status_code=500, detail=f"套利扫描失败: {str(e)}")


@router.get("/momentum-scan", summary="Kronos动量机会扫描")
async def scan_momentum_opportunities():
    """扫描Kronos动量交易机会"""
    try:
        scanner = await get_kronos_momentum_scanner()
        result = await scanner.scan_momentum_opportunities()
        
        return {
            "status": "success",
            "data": result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"动量扫描API失败: {e}")
        raise HTTPException(status_code=500, detail=f"动量扫描失败: {str(e)}")


@router.get("/whale-tracking", summary="Kronos巨鲸活动追踪")
async def track_whale_activities():
    """追踪巨鲸活动"""
    try:
        tracker = await get_kronos_whale_tracker()
        result = await tracker.track_whale_activities()
        
        return {
            "status": "success",
            "data": result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"巨鲸追踪API失败: {e}")
        raise HTTPException(status_code=500, detail=f"巨鲸追踪失败: {str(e)}")


@router.get("/comprehensive-scan", summary="Kronos综合机会扫描")
async def comprehensive_opportunities_scan():
    """综合扫描所有Kronos高级交易机会"""
    try:
        logger.info("🚀 开始Kronos综合机会扫描...")
        
        # 并行执行所有扫描
        import asyncio
        
        arbitrage_scanner = await get_kronos_arbitrage_scanner()
        momentum_scanner = await get_kronos_momentum_scanner()
        whale_tracker = await get_kronos_whale_tracker()
        
        # 并行执行
        arbitrage_task = arbitrage_scanner.scan_arbitrage_opportunities()
        momentum_task = momentum_scanner.scan_momentum_opportunities()
        whale_task = whale_tracker.track_whale_activities()
        
        arbitrage_result, momentum_result, whale_result = await asyncio.gather(
            arbitrage_task, momentum_task, whale_task, return_exceptions=True
        )
        
        # 处理结果
        results = {
            "arbitrage": arbitrage_result if not isinstance(arbitrage_result, Exception) else {"status": "error", "error": str(arbitrage_result)},
            "momentum": momentum_result if not isinstance(momentum_result, Exception) else {"status": "error", "error": str(momentum_result)},
            "whale": whale_result if not isinstance(whale_result, Exception) else {"status": "error", "error": str(whale_result)}
        }
        
        # 统计总体结果
        total_opportunities = 0
        total_opportunities += results["arbitrage"].get("opportunities_found", 0) if results["arbitrage"].get("status") == "success" else 0
        total_opportunities += results["momentum"].get("signals_found", 0) if results["momentum"].get("status") == "success" else 0
        total_opportunities += results["whale"].get("whale_signals", 0) if results["whale"].get("status") == "success" else 0
        
        logger.info(f"✅ Kronos综合扫描完成: 总计发现 {total_opportunities} 个机会")
        
        return {
            "status": "success",
            "data": {
                "total_opportunities": total_opportunities,
                "scan_results": results,
                "summary": {
                    "arbitrage_opportunities": results["arbitrage"].get("opportunities_found", 0),
                    "momentum_signals": results["momentum"].get("signals_found", 0),
                    "whale_signals": results["whale"].get("whale_signals", 0),
                    "strong_momentum_signals": results["momentum"].get("strong_signals", 0),
                    "important_whale_signals": results["whale"].get("important_signals", 0)
                }
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"综合扫描API失败: {e}")
        raise HTTPException(status_code=500, detail=f"综合扫描失败: {str(e)}")


@router.get("/status", summary="Kronos高级服务状态")
async def get_advanced_services_status():
    """获取Kronos高级服务状态"""
    try:
        # 检查各服务状态
        arbitrage_scanner = await get_kronos_arbitrage_scanner()
        momentum_scanner = await get_kronos_momentum_scanner()
        whale_tracker = await get_kronos_whale_tracker()
        
        status = {
            "arbitrage_scanner": {
                "available": True,
                "last_scan": arbitrage_scanner.last_scan_time.isoformat() if arbitrage_scanner.last_scan_time else None,
                "scan_interval_minutes": arbitrage_scanner.scan_interval.total_seconds() / 60
            },
            "momentum_scanner": {
                "available": True,
                "last_scan": momentum_scanner.last_scan_time.isoformat() if momentum_scanner.last_scan_time else None,
                "scan_interval_minutes": momentum_scanner.scan_interval.total_seconds() / 60
            },
            "whale_tracker": {
                "available": True,
                "last_scan": whale_tracker.last_scan_time.isoformat() if whale_tracker.last_scan_time else None,
                "scan_interval_minutes": whale_tracker.scan_interval.total_seconds() / 60,
                "whale_threshold_usd": whale_tracker.whale_threshold
            }
        }
        
        return {
            "status": "success",
            "data": status,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"获取服务状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")