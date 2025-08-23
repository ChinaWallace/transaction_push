# -*- coding: utf-8 -*-
"""
ML策略优化API
ML Strategy Optimization API - 提供策略参数优化和自适应调整功能
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

from app.services.ml_strategy_optimizer import MLStrategyOptimizer, OptimizationTarget
from app.core.logging import get_logger
from app.utils.exceptions import MLModelError

logger = get_logger(__name__)
router = APIRouter()


class OptimizationRequest(BaseModel):
    """优化请求"""
    symbol: str = Field(description="交易对")
    strategy_name: str = Field(default="supertrend_ml", description="策略名称")
    optimization_target: str = Field(default="sharpe_ratio", description="优化目标")
    lookback_days: int = Field(default=30, ge=7, le=90, description="回测天数")


class OptimizationResponse(BaseModel):
    """优化响应"""
    symbol: str
    optimization_target: str
    
    # 优化结果
    best_parameters: Dict[str, Any] = Field(description="最优参数")
    best_score: float = Field(description="最优评分")
    improvement_percent: float = Field(description="改进幅度百分比")
    
    # 性能对比
    original_performance: Dict[str, Any] = Field(description="原始性能")
    optimized_performance: Dict[str, Any] = Field(description="优化后性能")
    
    # 稳定性
    stability_score: float = Field(description="稳定性评分")
    confidence_interval: List[float] = Field(description="置信区间")
    
    # 状态
    status: str = Field(description="优化状态")
    timestamp: datetime = Field(description="优化时间")


class BatchOptimizationResponse(BaseModel):
    """批量优化响应"""
    total_symbols: int = Field(description="总交易对数")
    successful_optimizations: int = Field(description="成功优化数")
    failed_optimizations: int = Field(description="失败优化数")
    
    results: Dict[str, Optional[OptimizationResponse]] = Field(description="优化结果")
    summary: Dict[str, Any] = Field(description="优化摘要")
    
    timestamp: datetime = Field(description="批量优化时间")


@router.post("/optimize/{symbol}", response_model=OptimizationResponse)
async def optimize_strategy_parameters(
    symbol: str,
    request: OptimizationRequest,
    background_tasks: BackgroundTasks
) -> OptimizationResponse:
    """
    优化单个交易对的策略参数
    
    使用机器学习方法优化策略参数，提升策略表现
    """
    try:
        optimizer = MLStrategyOptimizer()
        
        # 验证优化目标
        try:
            target = OptimizationTarget(request.optimization_target)
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"无效的优化目标: {request.optimization_target}"
            )
        
        # 执行优化
        result = await optimizer.optimize_strategy_parameters(
            symbol=symbol,
            strategy_name=request.strategy_name,
            optimization_target=target,
            lookback_days=request.lookback_days
        )
        
        # 转换为响应格式
        response = OptimizationResponse(
            symbol=result.symbol,
            optimization_target=result.optimization_target.value,
            
            best_parameters=result.best_parameters,
            best_score=result.best_score,
            improvement_percent=result.improvement_percent,
            
            original_performance={
                'total_return': result.original_performance.total_return,
                'sharpe_ratio': result.original_performance.sharpe_ratio,
                'max_drawdown': result.original_performance.max_drawdown,
                'win_rate': result.original_performance.win_rate,
                'total_trades': result.original_performance.total_trades
            },
            optimized_performance={
                'total_return': result.optimized_performance.total_return,
                'sharpe_ratio': result.optimized_performance.sharpe_ratio,
                'max_drawdown': result.optimized_performance.max_drawdown,
                'win_rate': result.optimized_performance.win_rate,
                'total_trades': result.optimized_performance.total_trades
            },
            
            stability_score=result.stability_score,
            confidence_interval=list(result.confidence_interval),
            
            status="completed",
            timestamp=result.timestamp
        )
        
        logger.info(f"策略优化完成: {symbol}, 改进: {result.improvement_percent:.2f}%")
        
        return response
        
    except MLModelError as e:
        logger.error(f"策略优化失败 {symbol}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"策略优化异常 {symbol}: {e}")
        raise HTTPException(status_code=500, detail="优化服务暂时不可用")


@router.post("/optimize/batch", response_model=BatchOptimizationResponse)
async def batch_optimize_strategies(
    symbols: str = Query(..., description="交易对列表，逗号分隔"),
    strategy_name: str = Query("supertrend_ml", description="策略名称"),
    optimization_target: str = Query("sharpe_ratio", description="优化目标"),
    lookback_days: int = Query(30, ge=7, le=90, description="回测天数"),
    max_concurrent: int = Query(3, ge=1, le=5, description="最大并发数")
) -> BatchOptimizationResponse:
    """
    批量优化多个交易对的策略参数
    
    同时优化多个交易对，提高效率
    """
    try:
        symbol_list = [s.strip() for s in symbols.split(',')]
        
        if len(symbol_list) > 10:
            raise HTTPException(status_code=400, detail="最多支持10个交易对")
        
        optimizer = MLStrategyOptimizer()
        
        # 验证优化目标
        try:
            target = OptimizationTarget(optimization_target)
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"无效的优化目标: {optimization_target}"
            )
        
        # 执行批量优化
        results = await optimizer.batch_optimize_strategies(
            symbols=symbol_list,
            max_concurrent=max_concurrent
        )
        
        # 统计结果
        successful_count = sum(1 for r in results.values() if r is not None)
        failed_count = len(symbol_list) - successful_count
        
        # 转换结果格式
        formatted_results = {}
        total_improvement = 0
        
        for symbol, result in results.items():
            if result is not None:
                formatted_results[symbol] = OptimizationResponse(
                    symbol=result.symbol,
                    optimization_target=result.optimization_target.value,
                    best_parameters=result.best_parameters,
                    best_score=result.best_score,
                    improvement_percent=result.improvement_percent,
                    original_performance={
                        'total_return': result.original_performance.total_return,
                        'sharpe_ratio': result.original_performance.sharpe_ratio,
                        'max_drawdown': result.original_performance.max_drawdown,
                        'win_rate': result.original_performance.win_rate
                    },
                    optimized_performance={
                        'total_return': result.optimized_performance.total_return,
                        'sharpe_ratio': result.optimized_performance.sharpe_ratio,
                        'max_drawdown': result.optimized_performance.max_drawdown,
                        'win_rate': result.optimized_performance.win_rate
                    },
                    stability_score=result.stability_score,
                    confidence_interval=list(result.confidence_interval),
                    status="completed",
                    timestamp=result.timestamp
                )
                total_improvement += result.improvement_percent
            else:
                formatted_results[symbol] = None
        
        # 计算摘要
        avg_improvement = total_improvement / successful_count if successful_count > 0 else 0
        
        summary = {
            'average_improvement_percent': avg_improvement,
            'best_performing_symbol': max(
                (s for s, r in results.items() if r is not None),
                key=lambda s: results[s].improvement_percent,
                default=None
            ),
            'optimization_target': optimization_target,
            'lookback_days': lookback_days
        }
        
        return BatchOptimizationResponse(
            total_symbols=len(symbol_list),
            successful_optimizations=successful_count,
            failed_optimizations=failed_count,
            results=formatted_results,
            summary=summary,
            timestamp=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量优化失败: {e}")
        raise HTTPException(status_code=500, detail="批量优化失败")


@router.post("/adaptive-update/{symbol}")
async def adaptive_parameter_update(
    symbol: str,
    performance_threshold: float = Query(0.1, ge=0.05, le=0.5, description="性能下降阈值")
) -> Dict[str, Any]:
    """
    自适应参数更新
    
    根据最近表现自动调整策略参数
    """
    try:
        optimizer = MLStrategyOptimizer()
        
        result = await optimizer.adaptive_parameter_update(
            symbol=symbol,
            performance_threshold=performance_threshold
        )
        
        return {
            'symbol': symbol,
            'update_result': result,
            'timestamp': datetime.now()
        }
        
    except Exception as e:
        logger.error(f"自适应更新失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail="自适应更新失败")


@router.get("/optimization-history/{symbol}")
async def get_optimization_history(
    symbol: str,
    limit: int = Query(10, ge=1, le=50, description="历史记录数量")
) -> Dict[str, Any]:
    """
    获取优化历史记录
    
    查看策略参数的优化历史
    """
    try:
        import json
        from pathlib import Path
        
        models_dir = Path("models/strategy_optimization")
        history_file = models_dir / f"{symbol}_optimization_history.json"
        
        if not history_file.exists():
            return {
                'symbol': symbol,
                'history': [],
                'message': '暂无优化历史'
            }
        
        with open(history_file, 'r') as f:
            history = json.load(f)
        
        # 限制返回数量
        recent_history = history[-limit:] if len(history) > limit else history
        
        return {
            'symbol': symbol,
            'total_optimizations': len(history),
            'recent_history': recent_history,
            'timestamp': datetime.now()
        }
        
    except Exception as e:
        logger.error(f"获取优化历史失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail="获取历史记录失败")


@router.get("/current-parameters/{symbol}")
async def get_current_parameters(
    symbol: str
) -> Dict[str, Any]:
    """
    获取当前策略参数
    
    查看当前使用的策略参数
    """
    try:
        optimizer = MLStrategyOptimizer()
        
        current_params = await optimizer._get_current_parameters(symbol, "supertrend_ml")
        
        return {
            'symbol': symbol,
            'strategy_name': 'supertrend_ml',
            'parameters': current_params,
            'timestamp': datetime.now()
        }
        
    except Exception as e:
        logger.error(f"获取当前参数失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail="获取参数失败")


@router.get("/performance-summary")
async def get_performance_summary(
    symbols: str = Query(..., description="交易对列表，逗号分隔")
) -> Dict[str, Any]:
    """
    获取性能摘要
    
    查看多个交易对的策略表现摘要
    """
    try:
        symbol_list = [s.strip() for s in symbols.split(',')]
        
        if len(symbol_list) > 20:
            raise HTTPException(status_code=400, detail="最多支持20个交易对")
        
        import json
        from pathlib import Path
        
        models_dir = Path("models/strategy_optimization")
        summary_data = {}
        
        for symbol in symbol_list:
            history_file = models_dir / f"{symbol}_optimization_history.json"
            
            if history_file.exists():
                try:
                    with open(history_file, 'r') as f:
                        history = json.load(f)
                    
                    if history:
                        latest = history[-1]
                        summary_data[symbol] = {
                            'last_optimization': latest.get('timestamp'),
                            'improvement': latest.get('improvement'),
                            'stability_score': latest.get('stability_score'),
                            'best_score': latest.get('best_score')
                        }
                    else:
                        summary_data[symbol] = {'status': 'no_history'}
                        
                except Exception:
                    summary_data[symbol] = {'status': 'error'}
            else:
                summary_data[symbol] = {'status': 'not_optimized'}
        
        return {
            'performance_summary': summary_data,
            'total_symbols': len(symbol_list),
            'optimized_count': sum(1 for data in summary_data.values() 
                                 if data.get('status') != 'not_optimized'),
            'timestamp': datetime.now()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取性能摘要失败: {e}")
        raise HTTPException(status_code=500, detail="获取摘要失败")