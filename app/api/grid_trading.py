# -*- coding: utf-8 -*-
"""
网格交易API
Grid Trading API

提供网格交易机会推荐的API接口
"""

from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.core.logging import get_logger
from app.services.analysis.grid_trading_service import get_grid_trading_service
from app.schemas.grid_trading import (
    GridTradingBatch, 
    GridTradingRecommendation,
    GridOpportunityLevel
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/grid-trading", tags=["网格交易"])


@router.get("/opportunities",
    response_model=GridTradingBatch,
    summary="获取网格交易机会",
    description="""
    获取当前市场中适合做多网格交易的机会推荐
    
    **筛选条件:**
    - 波动性要大 (2%-15%)
    - 交易量要很大 (>5000万USDT)
    - 整体趋势向上或震荡
    - 不推荐持续阴跌的品种
    
    **返回信息:**
    - 以1万U为基准的仓位建议
    - 推荐交易区间和网格配置
    - 预期日收益率和波动率
    - 当前价格和风险提示
    """)
async def get_grid_opportunities(
    min_level: GridOpportunityLevel = Query(
        default=GridOpportunityLevel.MODERATE,
        description="最低机会等级"
    ),
    symbols: Optional[str] = Query(
        default=None,
        description="指定交易对，多个用逗号分隔"
    ),
    service = Depends(get_grid_trading_service)
) -> GridTradingBatch:
    """获取网格交易机会"""
    try:
        # 解析指定的交易对
        symbol_list = None
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(',')]
            # 确保是永续合约格式
            symbol_list = [
                s if s.endswith('-USDT-SWAP') else f"{s}-USDT-SWAP"
                for s in symbol_list
            ]
        
        # 分析网格交易机会
        result = await service.analyze_grid_opportunities(
            symbols=symbol_list,
            min_opportunity_level=min_level
        )
        
        logger.info(f"✅ 返回 {len(result.recommendations)} 个网格交易机会")
        return result
        
    except Exception as e:
        logger.error(f"❌ 获取网格交易机会失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取网格交易机会失败: {str(e)}"
        )


@router.get("/opportunities/{symbol}",
    response_model=GridTradingRecommendation,
    summary="获取单个交易对的网格机会",
    description="获取指定交易对的详细网格交易分析")
async def get_single_opportunity(
    symbol: str,
    service = Depends(get_grid_trading_service)
) -> GridTradingRecommendation:
    """获取单个交易对的网格机会"""
    try:
        # 确保是永续合约格式
        if not symbol.endswith('-USDT-SWAP'):
            symbol = f"{symbol.upper()}-USDT-SWAP"
        
        # 分析单个交易对
        result = await service.analyze_grid_opportunities(
            symbols=[symbol],
            min_opportunity_level=GridOpportunityLevel.POOR  # 允许所有等级
        )
        
        if not result.recommendations:
            raise HTTPException(
                status_code=404,
                detail=f"{symbol} 当前不适合网格交易"
            )
        
        return result.recommendations[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取 {symbol} 网格机会失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"分析失败: {str(e)}"
        )


@router.post("/analyze-batch",
    response_model=GridTradingBatch,
    summary="批量分析网格交易机会",
    description="批量分析多个交易对的网格交易机会")
async def analyze_batch_opportunities(
    symbols: List[str],
    min_level: GridOpportunityLevel = GridOpportunityLevel.MODERATE,
    background_tasks: BackgroundTasks = None,
    service = Depends(get_grid_trading_service)
) -> GridTradingBatch:
    """批量分析网格交易机会"""
    try:
        if not symbols:
            raise HTTPException(
                status_code=400,
                detail="交易对列表不能为空"
            )
        
        if len(symbols) > 50:
            raise HTTPException(
                status_code=400,
                detail="一次最多分析50个交易对"
            )
        
        # 格式化交易对名称
        formatted_symbols = []
        for symbol in symbols:
            symbol = symbol.strip().upper()
            if not symbol.endswith('-USDT-SWAP'):
                symbol = f"{symbol}-USDT-SWAP"
            formatted_symbols.append(symbol)
        
        # 执行批量分析
        result = await service.analyze_grid_opportunities(
            symbols=formatted_symbols,
            min_opportunity_level=min_level
        )
        
        logger.info(f"✅ 批量分析完成: {len(result.recommendations)} 个机会")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 批量分析失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"批量分析失败: {str(e)}"
        )


@router.get("/market-summary",
    response_model=Dict[str, Any],
    summary="获取网格交易市场概况",
    description="获取当前市场适合网格交易的整体概况")
async def get_market_summary(
    service = Depends(get_grid_trading_service)
) -> Dict[str, Any]:
    """获取网格交易市场概况"""
    try:
        # 获取所有机会
        result = await service.analyze_grid_opportunities(
            min_opportunity_level=GridOpportunityLevel.POOR
        )
        
        # 统计信息
        total_analyzed = result.total_count
        excellent_opportunities = result.excellent_count
        good_opportunities = result.good_count
        
        # 计算平均指标
        if result.recommendations:
            avg_volatility = sum(r.metrics.volatility_24h for r in result.recommendations) / len(result.recommendations)
            avg_expected_return = sum(r.expected_daily_return for r in result.recommendations) / len(result.recommendations)
            
            # 趋势分布
            trend_distribution = {}
            for rec in result.recommendations:
                trend = rec.trend_type.value
                trend_distribution[trend] = trend_distribution.get(trend, 0) + 1
        else:
            avg_volatility = 0
            avg_expected_return = 0
            trend_distribution = {}
        
        return {
            "market_summary": result.market_summary,
            "analysis_time": result.analysis_time.isoformat(),
            "statistics": {
                "total_analyzed": total_analyzed,
                "excellent_opportunities": excellent_opportunities,
                "good_opportunities": good_opportunities,
                "moderate_opportunities": total_analyzed - excellent_opportunities - good_opportunities,
                "success_rate": round((excellent_opportunities + good_opportunities) / max(total_analyzed, 1) * 100, 1)
            },
            "market_metrics": {
                "average_volatility": round(avg_volatility * 100, 2),
                "average_expected_daily_return": round(avg_expected_return, 2),
                "trend_distribution": trend_distribution
            },
            "top_opportunities": [
                {
                    "symbol": rec.symbol,
                    "opportunity_level": rec.opportunity_level.value,
                    "expected_daily_return": rec.expected_daily_return,
                    "current_price": rec.current_price,
                    "recommended_capital": rec.recommended_capital
                }
                for rec in result.recommendations[:5]
            ]
        }
        
    except Exception as e:
        logger.error(f"❌ 获取市场概况失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取市场概况失败: {str(e)}"
        )