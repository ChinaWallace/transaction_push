# -*- coding: utf-8 -*-
"""
回测API接口
Backtesting API endpoints
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Body, BackgroundTasks
from pydantic import BaseModel, Field, validator
import uuid

from app.core.logging import get_logger
from app.services.backtest.backtest_service_complete import (
    CompleteBacktestService, 
    StrategyParameter, 
    RiskManagementConfig,
    PortfolioConfig
)
from app.utils.exceptions import BacktestError

logger = get_logger(__name__)
router = APIRouter(prefix="/backtest", tags=["回测分析"])

# 创建回测服务实例
backtest_service = CompleteBacktestService()

# 存储异步任务状态
task_status = {}


class BacktestRequest(BaseModel):
    """回测请求"""
    symbol: str = Field(..., description="交易对")
    start_date: str = Field(..., description="开始日期 (YYYY-MM-DD)")
    end_date: str = Field(..., description="结束日期 (YYYY-MM-DD)")
    timeframe: str = Field(default="1h", description="时间周期")
    initial_balance: float = Field(default=10000.0, description="初始资金")
    strategy_type: str = Field(default="supertrend", description="策略类型")
    use_ml: bool = Field(default=True, description="是否使用ML增强")
    ml_weight: float = Field(default=0.1, description="ML权重")
    
    @validator('start_date', 'end_date')
    def validate_date(cls, v):
        try:
            datetime.fromisoformat(v)
            return v
        except ValueError:
            raise ValueError('日期格式不正确，应为 YYYY-MM-DD')


class PortfolioBacktestRequest(BaseModel):
    """投资组合回测请求"""
    symbols: List[str] = Field(..., description="交易对列表")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    timeframe: str = Field(default="1h", description="时间周期")
    initial_balance: float = Field(default=100000.0, description="初始资金")
    weights: Optional[Dict[str, float]] = Field(None, description="权重分配")
    rebalance_frequency: str = Field(default="weekly", description="重新平衡频率")
    max_correlation: float = Field(default=0.8, description="最大相关性")
    max_position_size: float = Field(default=0.1, description="最大仓位比例")
    max_drawdown: float = Field(default=0.2, description="最大回撤限制")


class OptimizationRequest(BaseModel):
    """策略优化请求"""
    symbol: str = Field(..., description="交易对")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    timeframe: str = Field(default="1h", description="时间周期")
    initial_balance: float = Field(default=10000.0, description="初始资金")
    optimization_method: str = Field(default="grid_search", description="优化方法")
    optimization_metric: str = Field(default="sharpe_ratio", description="优化指标")
    max_iterations: int = Field(default=100, description="最大迭代次数")
    parameters: List[Dict[str, Any]] = Field(..., description="优化参数")


class StrategyComparisonRequest(BaseModel):
    """策略比较请求"""
    symbol: str = Field(..., description="交易对")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    timeframe: str = Field(default="1h", description="时间周期")
    initial_balance: float = Field(default=10000.0, description="初始资金")
    strategies: List[Dict[str, Any]] = Field(..., description="策略列表")


@router.post("/single",
            summary="单一策略回测",
            response_model=Dict[str, Any])
async def single_strategy_backtest(request: BacktestRequest):
    """
    单一策略回测
    
    运行单个交易对的策略回测，支持SuperTrend和ML增强分析
    
    Args:
        request: 回测请求参数
        
    Returns:
        回测结果包含指标、交易记录、图表等
    """
    try:
        logger.info(f"🚀 开始单一策略回测: {request.symbol}")
        
        # 验证日期
        start_date = datetime.fromisoformat(request.start_date)
        end_date = datetime.fromisoformat(request.end_date)
        
        if start_date >= end_date:
            raise HTTPException(status_code=400, detail="开始日期必须早于结束日期")
        
        if (end_date - start_date).days > 365:
            raise HTTPException(status_code=400, detail="回测期间不能超过365天")
        
        # 构建回测配置
        config = {
            'type': 'single',
            'symbol': request.symbol.upper(),
            'start_date': request.start_date,
            'end_date': request.end_date,
            'basic_params': {
                'timeframe': request.timeframe,
                'initial_balance': request.initial_balance,
                'strategy_params': {
                    'use_ml': request.use_ml,
                    'ml_weight': request.ml_weight
                }
            },
            'advanced_params': {
                'interval': request.timeframe,
                'initial_balance': request.initial_balance,
                'strategy_configs': {
                    'strategy_type': request.strategy_type,
                    'use_ml': request.use_ml,
                    'ml_weight': request.ml_weight
                }
            }
        }
        
        # 运行综合回测
        result = await backtest_service.run_comprehensive_backtest(config)
        
        logger.info(f"✅ 单一策略回测完成: {request.symbol}")
        
        return {
            "status": "success",
            "message": f"{request.symbol} 回测完成",
            "data": result
        }
        
    except BacktestError as e:
        logger.error(f"❌ 回测业务错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ 单一策略回测失败: {e}")
        raise HTTPException(status_code=500, detail=f"回测失败: {str(e)}")


@router.post("/portfolio",
            summary="投资组合回测",
            response_model=Dict[str, Any])
async def portfolio_backtest(request: PortfolioBacktestRequest):
    """
    投资组合回测
    
    运行多个交易对的投资组合回测，支持权重分配和风险管理
    
    Args:
        request: 投资组合回测请求参数
        
    Returns:
        投资组合回测结果
    """
    try:
        logger.info(f"🚀 开始投资组合回测: {request.symbols}")
        
        # 验证参数
        if len(request.symbols) < 2:
            raise HTTPException(status_code=400, detail="投资组合至少需要2个交易对")
        
        if len(request.symbols) > 20:
            raise HTTPException(status_code=400, detail="投资组合最多支持20个交易对")
        
        # 验证权重
        if request.weights:
            if len(request.weights) != len(request.symbols):
                raise HTTPException(status_code=400, detail="权重数量必须与交易对数量一致")
            
            if abs(sum(request.weights.values()) - 1.0) > 0.01:
                raise HTTPException(status_code=400, detail="权重总和必须等于1.0")
        
        # 构建投资组合配置
        portfolio_config = PortfolioConfig(
            symbols=[s.upper() for s in request.symbols],
            weights=request.weights,
            rebalance_frequency=request.rebalance_frequency,
            max_correlation=request.max_correlation,
            min_symbols=2,
            max_symbols=len(request.symbols)
        )
        
        # 构建风险管理配置
        risk_config = RiskManagementConfig(
            max_position_size=request.max_position_size,
            max_total_drawdown=request.max_drawdown,
            enable_position_sizing=True,
            enable_dynamic_stops=True
        )
        
        # 构建回测配置
        config = {
            'type': 'portfolio',
            'start_date': request.start_date,
            'end_date': request.end_date,
            'portfolio_config': portfolio_config.__dict__,
            'risk_config': risk_config.__dict__,
            'params': {
                'interval': request.timeframe,
                'initial_balance': request.initial_balance
            }
        }
        
        # 运行综合回测
        result = await backtest_service.run_comprehensive_backtest(config)
        
        logger.info(f"✅ 投资组合回测完成: {request.symbols}")
        
        return {
            "status": "success",
            "message": f"投资组合回测完成 ({len(request.symbols)}个交易对)",
            "data": result
        }
        
    except BacktestError as e:
        logger.error(f"❌ 投资组合回测业务错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ 投资组合回测失败: {e}")
        raise HTTPException(status_code=500, detail=f"投资组合回测失败: {str(e)}")


@router.post("/optimization",
            summary="策略参数优化",
            response_model=Dict[str, Any])
async def strategy_optimization(request: OptimizationRequest):
    """
    策略参数优化
    
    使用网格搜索、随机搜索或遗传算法优化策略参数
    
    Args:
        request: 优化请求参数
        
    Returns:
        优化结果包含最佳参数和性能对比
    """
    try:
        logger.info(f"🎯 开始策略优化: {request.symbol}")
        
        # 验证优化方法
        if request.optimization_method not in ['grid_search', 'random_search', 'genetic_algorithm']:
            raise HTTPException(status_code=400, detail="不支持的优化方法")
        
        # 验证优化指标
        valid_metrics = ['sharpe_ratio', 'total_pnl_percent', 'win_rate', 'profit_factor']
        if request.optimization_metric not in valid_metrics:
            raise HTTPException(status_code=400, detail=f"不支持的优化指标，支持: {valid_metrics}")
        
        # 验证参数定义
        if not request.parameters:
            raise HTTPException(status_code=400, detail="必须提供至少一个优化参数")
        
        # 构建参数对象
        strategy_parameters = []
        for param_config in request.parameters:
            try:
                param = StrategyParameter(
                    name=param_config['name'],
                    min_value=param_config['min_value'],
                    max_value=param_config['max_value'],
                    step=param_config['step'],
                    param_type=param_config.get('param_type', float),
                    description=param_config.get('description', '')
                )
                strategy_parameters.append(param)
            except KeyError as e:
                raise HTTPException(status_code=400, detail=f"参数配置缺少字段: {e}")
        
        # 构建回测配置
        config = {
            'type': 'optimization',
            'symbol': request.symbol.upper(),
            'start_date': request.start_date,
            'end_date': request.end_date,
            'parameters': request.parameters,
            'method': request.optimization_method,
            'optimization_params': {
                'optimization_metric': request.optimization_metric,
                'max_iterations': request.max_iterations,
                'initial_balance': request.initial_balance
            },
            'backtest_params': {
                'timeframe': request.timeframe,
                'initial_balance': request.initial_balance
            }
        }
        
        # 运行优化
        result = await backtest_service.run_comprehensive_backtest(config)
        
        logger.info(f"✅ 策略优化完成: {request.symbol}")
        
        return {
            "status": "success",
            "message": f"{request.symbol} 策略优化完成",
            "data": result
        }
        
    except BacktestError as e:
        logger.error(f"❌ 策略优化业务错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ 策略优化失败: {e}")
        raise HTTPException(status_code=500, detail=f"策略优化失败: {str(e)}")


@router.post("/comparison",
            summary="策略比较分析",
            response_model=Dict[str, Any])
async def strategy_comparison(request: StrategyComparisonRequest):
    """
    策略比较分析
    
    比较多个策略在同一交易对上的表现
    
    Args:
        request: 策略比较请求参数
        
    Returns:
        策略比较结果和排名
    """
    try:
        logger.info(f"📊 开始策略比较: {request.symbol}")
        
        # 验证策略列表
        if len(request.strategies) < 2:
            raise HTTPException(status_code=400, detail="至少需要2个策略进行比较")
        
        if len(request.strategies) > 10:
            raise HTTPException(status_code=400, detail="最多支持10个策略比较")
        
        # 验证策略配置
        for i, strategy in enumerate(request.strategies):
            if 'name' not in strategy:
                raise HTTPException(status_code=400, detail=f"策略{i+1}缺少name字段")
            if 'type' not in strategy:
                strategy['type'] = 'supertrend'  # 默认策略类型
        
        # 构建回测配置
        config = {
            'type': 'strategy_comparison',
            'symbol': request.symbol.upper(),
            'start_date': request.start_date,
            'end_date': request.end_date,
            'strategies': request.strategies,
            'params': {
                'timeframe': request.timeframe,
                'initial_balance': request.initial_balance
            }
        }
        
        # 运行策略比较
        result = await backtest_service.run_comprehensive_backtest(config)
        
        logger.info(f"✅ 策略比较完成: {request.symbol}")
        
        return {
            "status": "success",
            "message": f"{request.symbol} 策略比较完成 ({len(request.strategies)}个策略)",
            "data": result
        }
        
    except BacktestError as e:
        logger.error(f"❌ 策略比较业务错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ 策略比较失败: {e}")
        raise HTTPException(status_code=500, detail=f"策略比较失败: {str(e)}")


@router.post("/async/{task_type}",
            summary="异步回测任务",
            response_model=Dict[str, Any])
async def create_async_backtest(
    task_type: str,
    background_tasks: BackgroundTasks,
    request_data: Dict[str, Any] = Body(...)
):
    """
    创建异步回测任务
    
    对于复杂的回测任务（如大规模优化），支持异步执行
    
    Args:
        task_type: 任务类型 (single/portfolio/optimization/comparison)
        background_tasks: FastAPI后台任务
        request_data: 请求数据
        
    Returns:
        任务ID和状态
    """
    try:
        # 生成任务ID
        task_id = str(uuid.uuid4())
        
        # 初始化任务状态
        task_status[task_id] = {
            'status': 'pending',
            'progress': 0,
            'message': '任务已创建，等待执行',
            'created_at': datetime.now().isoformat(),
            'task_type': task_type,
            'result': None,
            'error': None
        }
        
        # 根据任务类型构建配置
        if task_type == 'single':
            config = {
                'type': 'single',
                **request_data
            }
        elif task_type == 'portfolio':
            config = {
                'type': 'portfolio',
                **request_data
            }
        elif task_type == 'optimization':
            config = {
                'type': 'optimization',
                **request_data
            }
        elif task_type == 'comparison':
            config = {
                'type': 'strategy_comparison',
                **request_data
            }
        else:
            raise HTTPException(status_code=400, detail=f"不支持的任务类型: {task_type}")
        
        # 添加后台任务
        background_tasks.add_task(
            run_async_backtest,
            task_id,
            config
        )
        
        logger.info(f"🚀 异步回测任务已创建: {task_id} ({task_type})")
        
        return {
            "status": "success",
            "message": "异步回测任务已创建",
            "task_id": task_id,
            "task_type": task_type,
            "check_url": f"/backtest/status/{task_id}"
        }
        
    except Exception as e:
        logger.error(f"❌ 创建异步回测任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@router.get("/status/{task_id}",
           summary="查询任务状态",
           response_model=Dict[str, Any])
async def get_task_status(task_id: str):
    """
    查询异步任务状态
    
    Args:
        task_id: 任务ID
        
    Returns:
        任务状态和结果
    """
    try:
        if task_id not in task_status:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        status = task_status[task_id]
        
        return {
            "status": "success",
            "task_id": task_id,
            "task_status": status['status'],
            "progress": status['progress'],
            "message": status['message'],
            "created_at": status['created_at'],
            "task_type": status['task_type'],
            "result": status['result'],
            "error": status['error']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 查询任务状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.delete("/status/{task_id}",
              summary="取消/删除任务",
              response_model=Dict[str, Any])
async def delete_task(task_id: str):
    """
    取消或删除异步任务
    
    Args:
        task_id: 任务ID
        
    Returns:
        删除结果
    """
    try:
        if task_id not in task_status:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        # 删除任务状态
        del task_status[task_id]
        
        logger.info(f"🗑️ 已删除回测任务: {task_id}")
        
        return {
            "status": "success",
            "message": f"任务 {task_id} 已删除",
            "task_id": task_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.get("/tasks",
           summary="获取任务列表",
           response_model=Dict[str, Any])
async def get_all_tasks(
    status_filter: Optional[str] = Query(None, description="状态过滤"),
    limit: int = Query(default=50, ge=1, le=200, description="返回数量限制")
):
    """
    获取所有任务列表
    
    Args:
        status_filter: 状态过滤器 (pending/running/completed/failed)
        limit: 返回数量限制
        
    Returns:
        任务列表
    """
    try:
        tasks = []
        
        for task_id, status in task_status.items():
            if status_filter and status['status'] != status_filter:
                continue
            
            tasks.append({
                'task_id': task_id,
                'task_type': status['task_type'],
                'status': status['status'],
                'progress': status['progress'],
                'message': status['message'],
                'created_at': status['created_at']
            })
            
            if len(tasks) >= limit:
                break
        
        # 按创建时间排序
        tasks.sort(key=lambda x: x['created_at'], reverse=True)
        
        return {
            "status": "success",
            "total_tasks": len(task_status),
            "filtered_tasks": len(tasks),
            "tasks": tasks
        }
        
    except Exception as e:
        logger.error(f"❌ 获取任务列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.post("/export/{task_id}",
            summary="导出回测结果",
            response_model=Dict[str, Any])
async def export_backtest_results(
    task_id: str,
    export_format: str = Query(default="json", description="导出格式"),
    include_charts: bool = Query(default=True, description="是否包含图表")
):
    """
    导出回测结果
    
    Args:
        task_id: 任务ID
        export_format: 导出格式 (json/excel/pickle)
        include_charts: 是否包含图表
        
    Returns:
        导出文件路径
    """
    try:
        if task_id not in task_status:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        status = task_status[task_id]
        
        if status['status'] != 'completed':
            raise HTTPException(status_code=400, detail="任务未完成，无法导出")
        
        if not status['result']:
            raise HTTPException(status_code=400, detail="任务结果为空")
        
        # 准备导出数据
        export_data = status['result'].copy()
        
        if not include_charts and 'charts' in export_data:
            del export_data['charts']
        
        # 导出结果
        file_path = await backtest_service.export_results(
            export_data,
            export_format=export_format
        )
        
        logger.info(f"📁 回测结果已导出: {task_id} -> {file_path}")
        
        return {
            "status": "success",
            "message": "回测结果导出成功",
            "task_id": task_id,
            "file_path": file_path,
            "export_format": export_format
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 导出回测结果失败: {e}")
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


@router.get("/templates/optimization-params",
           summary="获取优化参数模板",
           response_model=Dict[str, Any])
async def get_optimization_parameter_templates():
    """
    获取策略优化参数模板
    
    Returns:
        各种策略的参数模板
    """
    try:
        templates = {
            "supertrend": [
                {
                    "name": "period",
                    "min_value": 5,
                    "max_value": 20,
                    "step": 1,
                    "param_type": "int",
                    "description": "SuperTrend周期"
                },
                {
                    "name": "multiplier",
                    "min_value": 1.0,
                    "max_value": 5.0,
                    "step": 0.5,
                    "param_type": "float",
                    "description": "ATR倍数"
                }
            ],
            "ml_enhanced": [
                {
                    "name": "ml_weight",
                    "min_value": 0.1,
                    "max_value": 0.9,
                    "step": 0.1,
                    "param_type": "float",
                    "description": "ML权重"
                },
                {
                    "name": "confidence_threshold",
                    "min_value": 0.5,
                    "max_value": 0.9,
                    "step": 0.1,
                    "param_type": "float",
                    "description": "置信度阈值"
                }
            ],
            "risk_management": [
                {
                    "name": "max_position_size",
                    "min_value": 0.05,
                    "max_value": 0.2,
                    "step": 0.01,
                    "param_type": "float",
                    "description": "最大仓位比例"
                },
                {
                    "name": "stop_loss_percent",
                    "min_value": 0.02,
                    "max_value": 0.1,
                    "step": 0.01,
                    "param_type": "float",
                    "description": "止损百分比"
                }
            ]
        }
        
        return {
            "status": "success",
            "message": "参数模板获取成功",
            "templates": templates,
            "usage_example": {
                "optimization_request": {
                    "symbol": "BTCUSDT",
                    "start_date": "2024-01-01",
                    "end_date": "2024-02-01",
                    "optimization_method": "grid_search",
                    "optimization_metric": "sharpe_ratio",
                    "parameters": templates["supertrend"]
                }
            }
        }
        
    except Exception as e:
        logger.error(f"❌ 获取参数模板失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


async def run_async_backtest(task_id: str, config: Dict[str, Any]):
    """
    运行异步回测任务
    
    Args:
        task_id: 任务ID
        config: 回测配置
    """
    try:
        # 更新任务状态
        task_status[task_id]['status'] = 'running'
        task_status[task_id]['progress'] = 10
        task_status[task_id]['message'] = '正在初始化回测...'
        
        # 运行回测
        result = await backtest_service.run_comprehensive_backtest(config)
        
        # 更新完成状态
        task_status[task_id]['status'] = 'completed'
        task_status[task_id]['progress'] = 100
        task_status[task_id]['message'] = '回测完成'
        task_status[task_id]['result'] = result
        
        logger.info(f"✅ 异步回测任务完成: {task_id}")
        
    except Exception as e:
        # 更新失败状态
        task_status[task_id]['status'] = 'failed'
        task_status[task_id]['progress'] = 0
        task_status[task_id]['message'] = f'回测失败: {str(e)}'
        task_status[task_id]['error'] = str(e)
        
        logger.error(f"❌ 异步回测任务失败: {task_id} - {e}")


# 清理过期任务的后台任务
async def cleanup_expired_tasks():
    """清理过期的任务状态"""
    try:
        current_time = datetime.now()
        expired_tasks = []
        
        for task_id, status in task_status.items():
            created_at = datetime.fromisoformat(status['created_at'])
            if (current_time - created_at).total_seconds() > 24 * 3600:  # 24小时过期
                expired_tasks.append(task_id)
        
        for task_id in expired_tasks:
            del task_status[task_id]
        
        if expired_tasks:
            logger.info(f"🧹 已清理 {len(expired_tasks)} 个过期任务")
            
    except Exception as e:
        logger.error(f"❌ 清理过期任务失败: {e}")


# 启动时清理过期任务
@router.on_event("startup")
async def startup_event():
    """启动事件处理"""
    logger.info("🚀 回测API服务启动")
    await cleanup_expired_tasks()


@router.on_event("shutdown")
async def shutdown_event():
    """关闭事件处理"""
    logger.info("🛑 回测API服务关闭")
    # 可以在这里保存任务状态到数据库





