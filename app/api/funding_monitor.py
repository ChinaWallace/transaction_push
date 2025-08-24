#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
负费率监控API
Negative Funding Rate Monitor API
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List, Dict, Any
from datetime import datetime
import asyncio

from app.services.negative_funding_monitor_service import NegativeFundingMonitorService
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()

# 全局监控服务实例
monitor_service = NegativeFundingMonitorService()


@router.get("/check", summary="立即检查负费率机会")
async def check_negative_funding():
    """立即检查负费率机会"""
    try:
        result = await monitor_service.run_monitoring_cycle()
        
        if result['success']:
            return {
                "status": "success",
                "message": f"检查完成，发现 {result['negative_funding_count']} 个负费率机会",
                "data": {
                    "total_symbols_checked": result['total_symbols_checked'],
                    "negative_funding_count": result['negative_funding_count'],
                    "opportunities": result['opportunities'][:10],  # 只返回前10个
                    "analysis_time": result['analysis_time'],
                    "duration_seconds": result['duration_seconds']
                }
            }
        else:
            raise HTTPException(status_code=500, detail=result.get('error', '检查失败'))
            
    except Exception as e:
        logger.error(f"负费率检查API异常: {e}")
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")


@router.get("/opportunities", summary="获取当前负费率机会")
async def get_current_opportunities():
    """获取当前负费率机会（快速版本，只检查缓存的币种）"""
    try:
        # 使用较少的币种进行快速检查
        quick_symbols = [
            'API3-USDT-SWAP', 'AUCTION-USDT-SWAP', 'CORE-USDT-SWAP', 'DGB-USDT-SWAP',
            'LRC-USDT-SWAP', 'RAY-USDT-SWAP', 'LUNC-USDT-SWAP', 'USTC-USDT-SWAP',
            'ORDI-USDT-SWAP', 'SATS-USDT-SWAP', 'PEPE-USDT-SWAP', 'WIF-USDT-SWAP',
            'BONK-USDT-SWAP', 'NEIRO-USDT-SWAP', 'PNUT-USDT-SWAP', 'GOAT-USDT-SWAP',
            'TURBO-USDT-SWAP', 'MEME-USDT-SWAP', 'BOME-USDT-SWAP', 'POPCAT-USDT-SWAP'
        ]
        
        # 获取费率数据
        funding_rates = await monitor_service.get_batch_funding_rates(quick_symbols, batch_size=5)
        
        # 获取负费率币种的基础信息
        negative_symbols = [r['symbol'] for r in funding_rates if r['funding_rate'] < 0]
        basic_info = {}
        
        if negative_symbols:
            for symbol in negative_symbols:
                info = await monitor_service.get_symbol_basic_info(symbol)
                basic_info[symbol] = info
                await asyncio.sleep(0.1)
        
        # 分析机会
        opportunities = await monitor_service.analyze_negative_funding_opportunities(funding_rates, basic_info)
        
        return {
            "status": "success",
            "message": f"发现 {len(opportunities)} 个负费率机会",
            "data": {
                "opportunities": opportunities,
                "check_time": datetime.now().isoformat(),
                "symbols_checked": len(quick_symbols)
            }
        }
        
    except Exception as e:
        logger.error(f"获取负费率机会API异常: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.get("/summary", summary="获取负费率机会摘要")
async def get_opportunities_summary():
    """获取负费率机会摘要"""
    try:
        # 快速检查前20个热门币种
        hot_symbols = await monitor_service.get_top_volume_symbols(limit=20)
        
        if not hot_symbols:
            return {
                "status": "success",
                "message": "暂无数据",
                "data": {"opportunities": [], "summary": "当前无负费率机会"}
            }
        
        # 获取费率数据
        funding_rates = await monitor_service.get_batch_funding_rates(hot_symbols, batch_size=5)
        
        # 只分析负费率币种
        negative_rates = [r for r in funding_rates if r['funding_rate'] < 0]
        
        if not negative_rates:
            return {
                "status": "success",
                "message": "当前无负费率机会",
                "data": {"opportunities": [], "summary": "当前市场无负费率机会"}
            }
        
        # 简化分析（不获取详细信息）
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
        
        # 按费率排序
        opportunities.sort(key=lambda x: x['funding_rate_percent'])
        
        # 生成摘要
        best = opportunities[0] if opportunities else None
        summary = f"发现 {len(opportunities)} 个负费率机会"
        if best:
            summary += f"，最佳: {best['symbol']} 日化 {best['daily_rate_percent']:.3f}%"
        
        return {
            "status": "success",
            "message": summary,
            "data": {
                "opportunities": opportunities[:5],  # 只返回前5个
                "total_count": len(opportunities),
                "summary": summary,
                "check_time": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"获取摘要API异常: {e}")
        raise HTTPException(status_code=500, detail=f"获取摘要失败: {str(e)}")


@router.post("/start-monitor", summary="启动定时监控")
async def start_monitor(background_tasks: BackgroundTasks):
    """启动定时监控（后台任务）"""
    try:
        # 添加后台任务
        background_tasks.add_task(run_periodic_monitor)
        
        return {
            "status": "success",
            "message": "负费率监控已启动",
            "data": {
                "monitor_interval": "1小时",
                "start_time": datetime.now().isoformat(),
                "excluded_symbols": len(monitor_service.excluded_major_coins)
            }
        }
        
    except Exception as e:
        logger.error(f"启动监控API异常: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")


async def run_periodic_monitor():
    """运行周期性监控"""
    try:
        logger.info("启动负费率周期性监控")
        
        while True:
            try:
                # 运行监控检查
                result = await monitor_service.run_monitoring_cycle()
                
                if result['success']:
                    opportunities = result['opportunities']
                    logger.info(f"负费率监控完成: 发现 {len(opportunities)} 个机会")
                    
                    if opportunities:
                        best = opportunities[0]
                        logger.info(f"最佳机会: {best['symbol']} 费率 {best['funding_rate_percent']:.3f}%")
                else:
                    logger.error(f"负费率监控失败: {result.get('error')}")
                
                # 等待1小时
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"周期性监控异常: {e}")
                # 出错后等待10分钟再重试
                await asyncio.sleep(600)
                
    except Exception as e:
        logger.error(f"周期性监控启动失败: {e}")


# 注意：启动检查已移到main.py中的lifespan管理