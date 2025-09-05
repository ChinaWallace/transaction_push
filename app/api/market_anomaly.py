# -*- coding: utf-8 -*-
"""
市场异常监控API
Market Anomaly Monitoring API
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime

from app.core.logging import get_logger
from app.services.market_anomaly_monitor_service import get_market_anomaly_service
from app.schemas.market_anomaly import (
    MarketAnomalyResponse, AnomalyLevel, AnomalyType
)

logger = get_logger(__name__)
router = APIRouter()


@router.get("/scan", response_model=MarketAnomalyResponse)
async def scan_market_anomalies(
    symbols: Optional[str] = Query(None, description="指定币种列表，逗号分隔"),
    min_anomaly_level: AnomalyLevel = Query(AnomalyLevel.MEDIUM, description="最小异常级别"),
    only_recommended: bool = Query(True, description="是否只返回推荐币种"),
    limit: int = Query(50, description="最大返回数量")
):
    """
    扫描市场异常
    
    Args:
        symbols: 指定币种列表（可选）
        min_anomaly_level: 最小异常级别
        only_recommended: 是否只返回推荐币种
        limit: 最大返回数量
        
    Returns:
        市场异常扫描结果
    """
    try:
        logger.info(f"🔍 开始市场异常扫描...")
        
        # 解析币种列表
        symbol_list = None
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(',')]
            # 确保格式正确
            symbol_list = [s if s.endswith('-USDT-SWAP') else f"{s}-USDT-SWAP" for s in symbol_list]
        
        # 获取服务实例
        service = await get_market_anomaly_service()
        
        # 扫描异常
        anomalies, total_checked = await service.scan_market_anomalies(
            symbols=symbol_list,
            min_anomaly_level=min_anomaly_level,
            only_recommended=only_recommended
        )
        
        # 限制返回数量
        if len(anomalies) > limit:
            anomalies = anomalies[:limit]
        
        # 生成汇总
        summary = service.generate_summary(anomalies, total_checked)
        
        response_data = {
            "success": True,
            "message": f"扫描完成，发现{len(anomalies)}个异常",
            "data": anomalies,
            "summary": {
                "total_symbols_checked": summary.total_symbols_checked,
                "anomalies_found": summary.anomalies_found,
                "recommended_count": summary.recommended_count,
                "by_anomaly_level": summary.by_anomaly_level,
                "by_trend_direction": summary.by_trend_direction,
                "by_anomaly_type": summary.by_anomaly_type,
                "top_opportunities": summary.top_opportunities,
                "high_risk_symbols": summary.high_risk_symbols
            }
        }
        
        logger.info(f"✅ 市场异常扫描完成: {len(anomalies)}个异常")
        return response_data
        
    except Exception as e:
        logger.error(f"❌ 市场异常扫描失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analyze/{symbol}")
async def analyze_symbol_anomaly(symbol: str):
    """
    分析单个币种的异常情况
    
    Args:
        symbol: 币种符号
        
    Returns:
        单个币种的异常分析结果
    """
    try:
        logger.info(f"🔍 分析{symbol}的异常情况...")
        
        # 确保格式正确
        if not symbol.endswith('-USDT-SWAP'):
            symbol = f"{symbol.upper()}-USDT-SWAP"
        
        # 获取服务实例
        service = await get_market_anomaly_service()
        
        # 分析异常
        anomaly_data = await service.analyze_symbol_anomaly(symbol)
        
        if not anomaly_data:
            raise HTTPException(status_code=404, detail=f"无法分析{symbol}的异常情况")
        
        response = {
            "success": True,
            "message": f"{symbol}异常分析完成",
            "data": anomaly_data,
            "timestamp": datetime.now()
        }
        
        logger.info(f"✅ {symbol}异常分析完成: {anomaly_data.overall_anomaly_level.value}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 分析{symbol}异常失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-opportunities")
async def get_top_opportunities(
    limit: int = Query(10, description="返回数量"),
    trend_filter: Optional[str] = Query(None, description="趋势过滤: up/down/sideways")
):
    """
    获取最佳异常机会
    
    Args:
        limit: 返回数量
        trend_filter: 趋势过滤
        
    Returns:
        最佳异常机会列表
    """
    try:
        logger.info(f"🏆 获取前{limit}个最佳异常机会...")
        
        # 获取服务实例
        service = await get_market_anomaly_service()
        
        # 扫描所有异常
        anomalies, total_checked = await service.scan_market_anomalies(
            min_anomaly_level=AnomalyLevel.MEDIUM,
            only_recommended=True
        )
        
        # 趋势过滤
        if trend_filter:
            trend_map = {
                'up': ['strong_up', 'up'],
                'down': ['strong_down', 'down'],
                'sideways': ['sideways']
            }
            allowed_trends = trend_map.get(trend_filter.lower(), [])
            if allowed_trends:
                anomalies = [a for a in anomalies if a.trend_direction.value in allowed_trends]
        
        # 按评分排序并限制数量
        top_anomalies = sorted(anomalies, key=lambda x: x.anomaly_score, reverse=True)[:limit]
        
        # 构建简化的响应
        opportunities = []
        for anomaly in top_anomalies:
            opportunities.append({
                "symbol": anomaly.symbol_name,
                "score": anomaly.anomaly_score,
                "trend": anomaly.trend_direction.value,
                "price_change_24h": f"{anomaly.price_change_24h * 100:+.1f}%",
                "volume_ratio": f"{anomaly.volume_ratio:.1f}x",
                "anomaly_level": anomaly.overall_anomaly_level.value,
                "main_reason": anomaly.recommendation_reason[0] if anomaly.recommendation_reason else "",
                "current_price": anomaly.current_price
            })
        
        response = {
            "success": True,
            "message": f"获取到{len(opportunities)}个最佳机会",
            "data": opportunities,
            "filter_applied": trend_filter,
            "timestamp": datetime.now()
        }
        
        logger.info(f"✅ 获取最佳机会完成: {len(opportunities)}个")
        return response
        
    except Exception as e:
        logger.error(f"❌ 获取最佳机会失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_market_summary():
    """
    获取市场异常汇总
    
    Returns:
        市场异常汇总信息
    """
    try:
        logger.info("📊 获取市场异常汇总...")
        
        # 获取服务实例
        service = await get_market_anomaly_service()
        
        # 扫描异常
        anomalies, total_checked = await service.scan_market_anomalies(
            min_anomaly_level=AnomalyLevel.LOW,
            only_recommended=False
        )
        
        # 生成汇总
        summary = service.generate_summary(anomalies, total_checked)
        
        # 额外统计信息
        strong_up_count = sum(1 for a in anomalies if a.trend_direction.value in ['strong_up', 'up'])
        strong_down_count = sum(1 for a in anomalies if a.trend_direction.value in ['strong_down', 'down'])
        high_volume_count = sum(1 for a in anomalies if a.volume_ratio > 2.0)
        
        response = {
            "success": True,
            "message": "市场汇总获取成功",
            "data": {
                "basic_stats": {
                    "total_symbols_checked": summary.total_symbols_checked,
                    "anomalies_found": summary.anomalies_found,
                    "recommended_count": summary.recommended_count
                },
                "trend_analysis": {
                    "strong_uptrend": strong_up_count,
                    "strong_downtrend": strong_down_count,
                    "high_volume_activity": high_volume_count
                },
                "anomaly_distribution": summary.by_anomaly_level,
                "trend_distribution": summary.by_trend_direction,
                "anomaly_types": summary.by_anomaly_type,
                "top_opportunities": summary.top_opportunities[:5],
                "high_risk_symbols": summary.high_risk_symbols[:5]
            },
            "timestamp": datetime.now()
        }
        
        logger.info(f"✅ 市场汇总获取完成: {summary.anomalies_found}个异常")
        return response
        
    except Exception as e:
        logger.error(f"❌ 获取市场汇总失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/manual-scan")
async def manual_scan():
    """
    手动触发市场异常扫描
    
    Returns:
        扫描结果和通知状态
    """
    try:
        logger.info("🧪 手动触发市场异常扫描...")
        
        # 获取服务实例
        service = await get_market_anomaly_service()
        
        # 运行监控周期
        result = await service.run_monitoring_cycle()
        
        if result['success']:
            response = {
                "success": True,
                "message": f"扫描完成，发现{result['anomalies_found']}个异常，推荐{result['recommended_count']}个",
                "data": {
                    "anomalies_found": result['anomalies_found'],
                    "recommended_count": result['recommended_count'],
                    "notification_sent": result['anomalies_found'] > 0
                },
                "timestamp": result['timestamp']
            }
        else:
            response = {
                "success": False,
                "message": f"扫描失败: {result['error']}",
                "timestamp": result['timestamp']
            }
        
        logger.info(f"✅ 手动扫描完成")
        return response
        
    except Exception as e:
        logger.error(f"❌ 手动扫描失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_monitoring_config():
    """
    获取监控配置信息
    
    Returns:
        当前监控配置
    """
    try:
        service = await get_market_anomaly_service()
        
        config = {
            "thresholds": service.thresholds,
            "cache_expiry_minutes": service.cache_expiry.total_seconds() / 60,
            "default_filters": {
                "min_volume_24h": 1000000,
                "min_anomaly_level": "medium",
                "only_recommended": True
            },
            "supported_anomaly_types": [t.value for t in AnomalyType],
            "supported_anomaly_levels": [l.value for l in AnomalyLevel]
        }
        
        return {
            "success": True,
            "message": "配置信息获取成功",
            "data": config,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"❌ 获取配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))