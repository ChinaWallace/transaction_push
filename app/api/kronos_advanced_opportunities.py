'''
Author: caiyinghan 455202662@qq.com
Date: 2025-08-25 14:03:55
LastEditors: caiyinghan 455202662@qq.com
LastEditTime: 2025-08-28 11:22:50
FilePath: \transaction_push\app\api\kronos_advanced_opportunities.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
# -*- coding: utf-8 -*-
"""
Kronos高级机会API
提供核心交易机会接口
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Optional, Any
from datetime import datetime

from app.core.logging import get_logger
from app.services.core_opportunity_service import get_core_opportunity_service

router = APIRouter()
logger = get_logger(__name__)


@router.get("/comprehensive-scan", summary="Kronos综合机会扫描")
async def comprehensive_opportunities_scan():
    """综合扫描所有Kronos高级交易机会"""
    try:
        logger.info("🚀 开始Kronos综合机会扫描...")
        
        # 获取核心机会服务
        opportunity_service = await get_core_opportunity_service()
        
        # 执行综合扫描
        scan_result = await opportunity_service.scan_all_opportunities(force_scan=True)
        
        logger.info(f"✅ Kronos综合扫描完成: 总计发现 {scan_result.get('total_opportunities', 0)} 个机会")
        
        return {
            "status": "success",
            "data": scan_result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"综合扫描API失败: {e}")
        raise HTTPException(status_code=500, detail=f"综合扫描失败: {str(e)}")


@router.get("/status", summary="Kronos高级服务状态")
async def get_advanced_services_status():
    """获取Kronos高级服务状态"""
    try:
        # 获取核心机会服务
        opportunity_service = await get_core_opportunity_service()
        
        # 获取服务摘要
        summary = await opportunity_service.get_opportunity_summary()
        
        status = {
            "core_opportunity_service": {
                "available": True,
                "last_scan_times": opportunity_service.last_scan_times,
                "opportunity_config": opportunity_service.opportunity_config,
                "daily_notification_counts": opportunity_service.daily_notification_counts
            },
            "summary": summary
        }
        
        return {
            "status": "success",
            "data": status,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"获取服务状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")