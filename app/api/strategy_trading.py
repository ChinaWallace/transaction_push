# -*- coding: utf-8 -*-
"""
策略交易API
Strategy Trading API - 提供网格、定投等策略交易接口
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime

from app.services.strategy_trading_service import (
    StrategyTradingService, GridStrategy, DCAStrategy, StrategyType
)
from app.core.logging import get_logger
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
router = APIRouter()


class GridStrategyRequest(BaseModel):
    """网格策略请求"""
    symbol: str = Field(..., description="交易对")
    grid_num: int = Field(..., ge=5, le=50, description="网格数量(5-50)")
    max_price: float = Field(..., gt=0, description="最高价格")
    min_price: float = Field(..., gt=0, description="最低价格")
    investment: float = Field(..., gt=0, description="投资金额(USDT)")


class DCAStrategyRequest(BaseModel):
    """定投策略请求"""
    symbol: str = Field(..., description="交易对")
    side: str = Field(..., pattern="^(buy|sell)$", description="方向(buy/sell)")
    investment: float = Field(..., gt=0, description="投资金额(USDT)")
    price_ratio: float = Field(0.05, ge=0.01, le=0.2, description="价格变动比例(1%-20%)")
    take_profit_ratio: float = Field(0.1, ge=0.02, le=0.5, description="止盈比例(2%-50%)")


class StrategyRecommendationResponse(BaseModel):
    """策略建议响应"""
    symbol: str
    strategy_type: str
    recommended: bool
    confidence: float
    parameters: Dict[str, Any]
    expected_daily_return: float
    expected_annual_return: float
    max_drawdown: float
    risk_level: str
    capital_requirement: float
    reasoning: str


class ActiveStrategyResponse(BaseModel):
    """活跃策略响应"""
    algo_id: str
    symbol: str
    strategy_type: str
    state: str
    status_text: str
    investment: float
    profit: float
    profit_rate_percent: float
    create_time: str


@router.get("/recommendations", response_model=List[StrategyRecommendationResponse])
async def get_strategy_recommendations(
    symbols: str = Query(..., description="交易对列表，逗号分隔"),
    investment: float = Query(1000, gt=0, description="投资金额(USDT)")
) -> List[StrategyRecommendationResponse]:
    """
    获取策略建议
    
    分析指定交易对的网格和定投策略机会，返回推荐的策略配置
    """
    try:
        symbol_list = [s.strip() for s in symbols.split(',')]
        
        if len(symbol_list) > 10:
            raise HTTPException(status_code=400, detail="最多支持10个交易对")
        
        service = StrategyTradingService()
        recommendations = await service.get_strategy_recommendations(symbol_list, investment)
        
        return [
            StrategyRecommendationResponse(
                symbol=rec.symbol,
                strategy_type=rec.strategy_type.value,
                recommended=rec.recommended,
                confidence=rec.confidence,
                parameters=rec.parameters,
                expected_daily_return=rec.expected_daily_return,
                expected_annual_return=rec.expected_annual_return,
                max_drawdown=rec.max_drawdown,
                risk_level=rec.risk_level,
                capital_requirement=rec.capital_requirement,
                reasoning=rec.reasoning
            )
            for rec in recommendations
        ]
        
    except Exception as e:
        logger.error(f"获取策略建议失败: {e}")
        raise HTTPException(status_code=500, detail="获取策略建议失败")


@router.post("/grid/create")
async def create_grid_strategy(request: GridStrategyRequest) -> Dict[str, Any]:
    """
    创建网格策略
    
    在指定价格区间内创建网格交易策略
    """
    try:
        # 验证价格区间
        if request.min_price >= request.max_price:
            raise HTTPException(status_code=400, detail="最低价格必须小于最高价格")
        
        service = StrategyTradingService()
        strategy = GridStrategy(
            symbol=request.symbol,
            grid_num=request.grid_num,
            max_price=request.max_price,
            min_price=request.min_price,
            investment=request.investment,
            profit_per_grid=(request.max_price - request.min_price) / request.grid_num * 0.002
        )
        
        result = await service.create_grid_strategy(strategy)
        
        return {
            "status": "success",
            "message": "网格策略创建成功",
            "data": result,
            "timestamp": datetime.now()
        }
        
    except TradingToolError as e:
        logger.error(f"创建网格策略失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建网格策略异常: {e}")
        raise HTTPException(status_code=500, detail="创建网格策略失败")


@router.post("/dca/create")
async def create_dca_strategy(request: DCAStrategyRequest) -> Dict[str, Any]:
    """
    创建定投策略
    
    创建定期投资策略，类似马丁格尔策略
    """
    try:
        service = StrategyTradingService()
        strategy = DCAStrategy(
            symbol=request.symbol,
            side=request.side,
            investment=request.investment,
            price_ratio=request.price_ratio,
            take_profit_ratio=request.take_profit_ratio
        )
        
        result = await service.create_dca_strategy(strategy)
        
        return {
            "status": "success",
            "message": "定投策略创建成功",
            "data": result,
            "timestamp": datetime.now()
        }
        
    except TradingToolError as e:
        logger.error(f"创建定投策略失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建定投策略异常: {e}")
        raise HTTPException(status_code=500, detail="创建定投策略失败")


@router.get("/active", response_model=List[ActiveStrategyResponse])
async def get_active_strategies() -> List[ActiveStrategyResponse]:
    """
    获取活跃策略
    
    返回当前正在运行的所有策略
    """
    try:
        service = StrategyTradingService()
        strategies = await service.get_active_strategies()
        
        return [
            ActiveStrategyResponse(
                algo_id=strategy['algo_id'],
                symbol=strategy['symbol'],
                strategy_type=strategy['strategy_type'],
                state=strategy['state'],
                status_text=strategy.get('status_text', strategy['state']),
                investment=strategy['investment'],
                profit=strategy['profit'],
                profit_rate_percent=strategy.get('profit_rate_percent', 0),
                create_time=strategy['create_time']
            )
            for strategy in strategies
        ]
        
    except Exception as e:
        logger.error(f"获取活跃策略失败: {e}")
        raise HTTPException(status_code=500, detail="获取活跃策略失败")


@router.post("/stop/{algo_id}")
async def stop_strategy(
    algo_id: str,
    strategy_type: str = Query(..., pattern="^(grid|dca)$", description="策略类型")
) -> Dict[str, Any]:
    """
    停止策略
    
    停止指定的策略交易
    """
    try:
        service = StrategyTradingService()
        result = await service.stop_strategy(algo_id, strategy_type)
        
        if result:
            return {
                "status": "success",
                "message": "策略停止成功",
                "algo_id": algo_id,
                "timestamp": datetime.now()
            }
        else:
            raise HTTPException(status_code=400, detail="策略停止失败")
            
    except Exception as e:
        logger.error(f"停止策略失败: {e}")
        raise HTTPException(status_code=500, detail="停止策略失败")


@router.get("/grid/analyze/{symbol}")
async def analyze_grid_opportunity(
    symbol: str,
    investment: float = Query(1000, gt=0, description="投资金额(USDT)")
) -> StrategyRecommendationResponse:
    """
    分析网格交易机会
    
    分析指定交易对的网格交易潜力
    """
    try:
        service = StrategyTradingService()
        recommendation = await service.analyze_grid_opportunity(symbol, investment)
        
        return StrategyRecommendationResponse(
            symbol=recommendation.symbol,
            strategy_type=recommendation.strategy_type.value,
            recommended=recommendation.recommended,
            confidence=recommendation.confidence,
            parameters=recommendation.parameters,
            expected_daily_return=recommendation.expected_daily_return,
            expected_annual_return=recommendation.expected_annual_return,
            max_drawdown=recommendation.max_drawdown,
            risk_level=recommendation.risk_level,
            capital_requirement=recommendation.capital_requirement,
            reasoning=recommendation.reasoning
        )
        
    except Exception as e:
        logger.error(f"分析网格机会失败: {e}")
        raise HTTPException(status_code=500, detail="分析网格机会失败")


@router.get("/dca/analyze/{symbol}")
async def analyze_dca_opportunity(
    symbol: str,
    investment: float = Query(1000, gt=0, description="投资金额(USDT)")
) -> StrategyRecommendationResponse:
    """
    分析定投策略机会
    
    分析指定交易对的定投策略潜力
    """
    try:
        service = StrategyTradingService()
        recommendation = await service.analyze_dca_opportunity(symbol, investment)
        
        return StrategyRecommendationResponse(
            symbol=recommendation.symbol,
            strategy_type=recommendation.strategy_type.value,
            recommended=recommendation.recommended,
            confidence=recommendation.confidence,
            parameters=recommendation.parameters,
            expected_daily_return=recommendation.expected_daily_return,
            expected_annual_return=recommendation.expected_annual_return,
            max_drawdown=recommendation.max_drawdown,
            risk_level=recommendation.risk_level,
            capital_requirement=recommendation.capital_requirement,
            reasoning=recommendation.reasoning
        )
        
    except Exception as e:
        logger.error(f"分析定投机会失败: {e}")
        raise HTTPException(status_code=500, detail="分析定投机会失败")