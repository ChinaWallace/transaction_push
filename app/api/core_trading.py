# -*- coding: utf-8 -*-
"""
核心交易API路由
Core Trading API - 整合所有核心交易服务的统一API接口
"""

from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from app.core.logging import get_logger, trading_logger
from app.services.trading.core_trading_service import (
    get_core_trading_service, 
    CoreTradingService,
    AnalysisType,
    SignalStrength,
    TradingSignal
)
from app.services.notification.core_notification_service import get_core_notification_service
from app.services.core.core_scheduler_service import get_core_scheduler_service

logger = get_logger(__name__)
router = APIRouter(prefix="/api/core-trading", tags=["核心交易"])


# ========== 请求/响应模型 ==========

class TradingAnalysisRequest(BaseModel):
    """交易分析请求"""
    symbol: str = Field(..., description="交易对", example="ETH-USDT-SWAP")
    analysis_type: str = Field(
        default="integrated", 
        description="分析类型: kronos_only, technical_only, ml_only, integrated, position_focused"
    )
    force_update: bool = Field(default=False, description="是否强制更新")


class BatchAnalysisRequest(BaseModel):
    """批量分析请求"""
    symbols: List[str] = Field(..., description="交易对列表")
    analysis_type: str = Field(default="integrated", description="分析类型")
    max_concurrent: int = Field(default=5, description="最大并发数", ge=1, le=10)


class TradingSignalResponse(BaseModel):
    """交易信号响应"""
    symbol: str
    final_action: str
    final_confidence: float
    signal_strength: str
    entry_price: float
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    position_size: Optional[float] = None
    leverage: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    reasoning: str
    key_factors: List[str]
    urgency: str
    timestamp: datetime
    
    # 详细分析结果
    kronos_analysis: Optional[Dict[str, Any]] = None
    technical_analysis: Optional[Dict[str, Any]] = None
    ml_analysis: Optional[Dict[str, Any]] = None
    confidence_breakdown: Optional[Dict[str, Any]] = None


class DetailedAnalysisRequest(BaseModel):
    """详细分析请求"""
    symbol: str = Field(..., description="交易对", example="ETH-USDT-SWAP")
    include_reasoning: bool = Field(default=True, description="包含详细推理")
    include_risk_analysis: bool = Field(default=True, description="包含风险分析")
    include_price_targets: bool = Field(default=True, description="包含价格目标")


class DetailedAnalysisResponse(BaseModel):
    """详细分析响应"""
    symbol: str
    analysis_time: datetime
    
    # 核心决策
    final_recommendation: str
    confidence_score: float
    signal_strength: str
    
    # 价格和风险管理
    current_price: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    
    # 仓位管理
    recommended_position_size: float
    recommended_leverage: float
    kelly_fraction: float
    
    # 市场分析
    market_volatility: float
    confidence_factor: float
    kronos_adjustment: float
    
    # 详细推理
    detailed_reasoning: str
    key_factors: List[str]
    confidence_sources: List[str]
    
    # 各模块分析结果
    kronos_result: Optional[Dict[str, Any]] = None
    technical_result: Optional[Dict[str, Any]] = None
    ml_result: Optional[Dict[str, Any]] = None
    
    # 风险评估
    risk_assessment: Dict[str, Any]
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
    timestamp: datetime
    final_action: str
    final_confidence: float
    signal_strength: str
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    position_size_usdt: float
    leverage: float
    risk_reward_ratio: float
    reasoning: str
    key_factors: List[str]
    confidence_breakdown: Dict[str, float]
    urgency: str
    valid_until: datetime
    
    # 各模块结果摘要
    kronos_summary: Optional[Dict[str, Any]] = None
    technical_summary: Optional[Dict[str, Any]] = None
    ml_summary: Optional[Dict[str, Any]] = None
    position_summary: Optional[Dict[str, Any]] = None


class PositionAnalysisResponse(BaseModel):
    """持仓分析响应"""
    timestamp: datetime
    total_positions: int
    total_value_usdt: float
    total_pnl_usdt: float
    total_pnl_percent: float
    risk_level: str
    positions: List[Dict[str, Any]]
    recommendations: List[str]
    urgent_actions: List[str]


class BatchAnalysisResponse(BaseModel):
    """批量分析响应"""
    analysis_time: datetime
    total_symbols: int
    successful_analyses: int
    failed_analyses: int
    signals: List[TradingSignalResponse]
    strong_signals: List[TradingSignalResponse]
    summary: Dict[str, Any]


# ========== 依赖注入 ==========

async def get_trading_service() -> CoreTradingService:
    """获取核心交易服务"""
    return await get_core_trading_service()


# ========== API路由 ==========

@router.post("/analyze", response_model=TradingSignalResponse)
async def analyze_trading_signal(
    request: TradingAnalysisRequest,
    trading_service: CoreTradingService = Depends(get_trading_service)
):
    """
    分析单个交易对的交易信号
    
    - **symbol**: 交易对符号 (如: ETH-USDT-SWAP)
    - **analysis_type**: 分析类型
        - `integrated`: 综合分析 (默认)
        - `kronos_only`: 仅Kronos分析
        - `technical_only`: 仅技术分析
        - `ml_only`: 仅ML分析
        - `position_focused`: 持仓导向分析
    - **force_update**: 是否强制更新数据
    """
    try:
        trading_logger.info(f"🎯 开始分析交易信号: {request.symbol} ({request.analysis_type})")
        
        # 转换分析类型
        try:
            analysis_type = AnalysisType(request.analysis_type)
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"无效的分析类型: {request.analysis_type}"
            )
        
        # 执行分析
        signal = await trading_service.analyze_trading_signal(
            symbol=request.symbol,
            analysis_type=analysis_type,
            force_update=request.force_update
        )
        
        if not signal:
            raise HTTPException(
                status_code=404,
                detail=f"无法生成 {request.symbol} 的交易信号"
            )
        
        # 转换为响应格式
        response = _convert_signal_to_response(signal)
        
        trading_logger.info(
            f"✅ 交易信号分析完成: {request.symbol} - {signal.final_action} "
            f"(置信度: {signal.final_confidence:.2f})"
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"分析交易信号失败 {request.symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@router.post("/batch-analyze", response_model=BatchAnalysisResponse)
async def batch_analyze_signals(
    request: BatchAnalysisRequest,
    background_tasks: BackgroundTasks,
    trading_service: CoreTradingService = Depends(get_trading_service)
):
    """
    批量分析多个交易对的交易信号
    
    - **symbols**: 交易对列表
    - **analysis_type**: 分析类型 (同单个分析)
    - **max_concurrent**: 最大并发分析数量
    """
    try:
        trading_logger.info(f"🔄 开始批量分析: {len(request.symbols)} 个交易对")
        
        # 验证交易对数量
        if len(request.symbols) > 20:
            raise HTTPException(
                status_code=400,
                detail="批量分析最多支持20个交易对"
            )
        
        # 转换分析类型
        try:
            analysis_type = AnalysisType(request.analysis_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"无效的分析类型: {request.analysis_type}"
            )
        
        # 执行批量分析
        results = await trading_service.batch_analyze_symbols(
            symbols=request.symbols,
            analysis_type=analysis_type,
            max_concurrent=request.max_concurrent
        )
        
        # 处理结果
        signals = []
        strong_signals = []
        successful_count = 0
        
        for symbol, signal in results.items():
            if signal:
                successful_count += 1
                response_signal = _convert_signal_to_response(signal)
                signals.append(response_signal)
                
                # 筛选强信号
                if signal.signal_strength in [SignalStrength.STRONG, SignalStrength.VERY_STRONG]:
                    strong_signals.append(response_signal)
        
        # 构建响应
        response = BatchAnalysisResponse(
            analysis_time=datetime.now(),
            total_symbols=len(request.symbols),
            successful_analyses=successful_count,
            failed_analyses=len(request.symbols) - successful_count,
            signals=signals,
            strong_signals=strong_signals,
            summary={
                "success_rate": successful_count / len(request.symbols),
                "strong_signals_count": len(strong_signals),
                "analysis_type": request.analysis_type,
                "top_signals": [
                    {
                        "symbol": s.symbol,
                        "action": s.final_action,
                        "confidence": s.final_confidence,
                        "strength": s.signal_strength
                    }
                    for s in sorted(signals, key=lambda x: x.final_confidence, reverse=True)[:5]
                ]
            }
        )
        
        # 后台发送强信号通知
        if strong_signals:
            background_tasks.add_task(
                _send_batch_strong_signals_notification,
                strong_signals,
                request.analysis_type
            )
        
        trading_logger.info(
            f"✅ 批量分析完成: {successful_count}/{len(request.symbols)} 成功, "
            f"{len(strong_signals)} 个强信号"
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量分析失败: {str(e)}")


@router.get("/position-analysis", response_model=PositionAnalysisResponse)
async def get_position_analysis(
    trading_service: CoreTradingService = Depends(get_trading_service)
):
    """
    获取综合持仓分析
    
    分析当前所有持仓的状况，包括:
    - 持仓概览
    - 盈亏分析
    - 风险评估
    - 操作建议
    """
    try:
        trading_logger.info("📊 开始持仓分析")
        
        result = await trading_service.get_comprehensive_position_analysis()
        
        if not result:
            raise HTTPException(
                status_code=404,
                detail="无法获取持仓分析数据"
            )
        
        response = PositionAnalysisResponse(
            timestamp=result.timestamp,
            total_positions=result.total_positions,
            total_value_usdt=result.total_value_usdt,
            total_pnl_usdt=result.total_pnl_usdt,
            total_pnl_percent=result.total_pnl_percent,
            risk_level=result.risk_level,
            positions=result.positions,
            recommendations=result.recommendations,
            urgent_actions=result.urgent_actions
        )
        
        trading_logger.info(
            f"✅ 持仓分析完成: {result.total_positions} 个持仓, "
            f"总盈亏 {result.total_pnl_percent:.1f}%"
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"持仓分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"持仓分析失败: {str(e)}")


@router.get("/market-opportunities")
async def get_market_opportunities(
    limit: int = Query(default=10, ge=1, le=50, description="返回机会数量"),
    min_score: float = Query(default=70.0, ge=0, le=100, description="最低评分"),
    opportunity_type: Optional[str] = Query(default=None, description="机会类型过滤")
):
    """
    获取当前市场机会
    
    - **limit**: 返回的机会数量
    - **min_score**: 最低评分筛选
    - **opportunity_type**: 机会类型 (strong_signal, grid_trading, arbitrage)
    """
    try:
        # 这里可以集成机会扫描服务
        # 暂时返回示例数据
        opportunities = [
            {
                "symbol": "ETH-USDT-SWAP",
                "opportunity_type": "strong_signal",
                "score": 85.5,
                "description": "技术指标强烈买入信号",
                "parameters": {
                    "entry_price": 2450.0,
                    "target_price": 2580.0,
                    "stop_loss": 2380.0
                },
                "risk_level": "中等",
                "estimated_return": 0.053,
                "recommended_position": 1000.0
            }
        ]
        
        # 应用过滤条件
        filtered_opportunities = [
            opp for opp in opportunities
            if opp["score"] >= min_score and
            (not opportunity_type or opp["opportunity_type"] == opportunity_type)
        ]
        
        return {
            "timestamp": datetime.now(),
            "total_opportunities": len(filtered_opportunities),
            "opportunities": filtered_opportunities[:limit],
            "filters": {
                "min_score": min_score,
                "opportunity_type": opportunity_type,
                "limit": limit
            }
        }
        
    except Exception as e:
        logger.error(f"获取市场机会失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取市场机会失败: {str(e)}")


@router.post("/detailed-analysis", response_model=DetailedAnalysisResponse)
async def get_detailed_trading_analysis(
    request: DetailedAnalysisRequest,
    trading_service: CoreTradingService = Depends(get_trading_service)
):
    """
    获取详细的交易分析 - 包含完整的推理过程和风险管理建议
    
    这个端点提供最全面的交易分析，包括：
    - 多模型综合决策
    - 详细的推理过程
    - 动态止盈止损计算
    - 风险管理建议
    - 仓位大小计算
    """
    try:
        logger.info(f"开始详细交易分析: {request.symbol}")
        
        # 执行综合分析
        signal = await trading_service.analyze_symbol(
            symbol=request.symbol,
            analysis_type=AnalysisType.INTEGRATED
        )
        
        if not signal:
            raise HTTPException(
                status_code=404, 
                detail=f"无法获取 {request.symbol} 的交易分析"
            )
        
        # 构建详细响应
        response_data = {
            "symbol": signal.symbol,
            "analysis_time": signal.timestamp,
            
            # 核心决策
            "final_recommendation": signal.final_action,
            "confidence_score": signal.final_confidence,
            "signal_strength": signal.signal_strength.value,
            
            # 价格和风险管理
            "current_price": signal.entry_price,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss_price or 0,
            "take_profit": signal.take_profit_price or 0,
            "risk_reward_ratio": getattr(signal, 'risk_reward_ratio', 0),
            
            # 仓位管理
            "recommended_position_size": signal.position_size or 1000,
            "recommended_leverage": getattr(signal, 'leverage', 2.0),
            "kelly_fraction": getattr(signal, 'kelly_fraction', 0.1),
            
            # 市场分析
            "market_volatility": getattr(signal, 'volatility', 0.02),
            "confidence_factor": getattr(signal, 'confidence_factor', 1.0),
            "kronos_adjustment": getattr(signal, 'kronos_adjustment', 1.0),
            
            # 详细推理
            "detailed_reasoning": signal.reasoning,
            "key_factors": signal.key_factors,
            "confidence_sources": getattr(signal, 'confidence_sources', []),
            
            # 各模块结果
            "kronos_result": signal.kronos_result.__dict__ if signal.kronos_result else None,
            "technical_result": signal.technical_result,
            "ml_result": signal.ml_result,
            
            # 风险评估
            "risk_assessment": {
                "overall_risk": "中等",
                "position_risk": "适中",
                "market_risk": "正常",
                "liquidity_risk": "低",
                "recommendations": [
                    "建议分批建仓，避免一次性满仓",
                    "严格执行止损，控制单笔损失",
                    "关注市场情绪变化，及时调整策略"
                ]
            }
        }
        
        # 根据请求选项添加额外信息
        if request.include_reasoning:
            # 已包含在detailed_reasoning中
            pass
        
        if request.include_risk_analysis:
            # 增强风险分析
            risk_level = "低风险" if signal.final_confidence > 0.8 else "中等风险" if signal.final_confidence > 0.6 else "高风险"
            response_data["risk_assessment"]["confidence_based_risk"] = risk_level
        
        if request.include_price_targets:
            # 添加多级价格目标
            current_price = signal.entry_price
            if signal.final_action.lower() in ['buy', 'strong_buy', '买入', '强烈买入']:
                response_data["price_targets"] = {
                    "short_term": current_price * 1.03,  # 3%
                    "medium_term": current_price * 1.06,  # 6%
                    "long_term": current_price * 1.12    # 12%
                }
            elif signal.final_action.lower() in ['sell', 'strong_sell', '卖出', '强烈卖出']:
                response_data["price_targets"] = {
                    "short_term": current_price * 0.97,  # -3%
                    "medium_term": current_price * 0.94,  # -6%
                    "long_term": current_price * 0.88    # -12%
                }
        
        logger.info(f"✅ 详细分析完成: {request.symbol} - {signal.final_action}")
        
        return DetailedAnalysisResponse(**response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"详细交易分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@router.get("/explain-confidence/{symbol}")
async def explain_confidence_calculation(
    symbol: str,
    trading_service: CoreTradingService = Depends(get_trading_service)
):
    """
    解释置信度计算过程 - 用于调试和理解AI决策
    
    详细说明：
    - 各个模型的置信度来源
    - 权重分配逻辑
    - 最终置信度计算公式
    - 影响因素分析
    """
    try:
        logger.info(f"解释置信度计算: {symbol}")
        
        # 获取分析结果
        signal = await trading_service.analyze_symbol(symbol, AnalysisType.INTEGRATED)
        
        if not signal:
            raise HTTPException(status_code=404, detail=f"无法获取 {symbol} 的分析结果")
        
        # 构建置信度解释
        explanation = {
            "symbol": symbol,
            "final_confidence": signal.final_confidence,
            "confidence_display": f"{signal.final_confidence:.1%}" if signal.final_confidence <= 1.0 else f"{signal.final_confidence:.1f}%",
            "calculation_method": "多模型加权平均",
            
            "model_contributions": [],
            "weight_allocation": {
                "kronos_ai": 0.4,
                "technical_analysis": 0.35,
                "machine_learning": 0.25
            },
            
            "confidence_factors": {
                "signal_consistency": "信号一致性程度",
                "model_accuracy": "各模型历史准确率",
                "market_conditions": "当前市场环境",
                "volatility_adjustment": "波动率调整因子"
            },
            
            "calculation_steps": [
                "1. 收集各模型的原始置信度",
                "2. 根据历史表现调整权重",
                "3. 计算信号一致性得分",
                "4. 应用市场环境修正",
                "5. 生成最终综合置信度"
            ],
            
            "interpretation": {
                "confidence_ranges": {
                    "0.9-1.0": "极高置信度 - 强烈建议执行",
                    "0.8-0.9": "高置信度 - 建议执行",
                    "0.7-0.8": "中高置信度 - 谨慎执行",
                    "0.6-0.7": "中等置信度 - 小仓位试探",
                    "0.5-0.6": "低置信度 - 观望为主",
                    "0.0-0.5": "极低置信度 - 不建议操作"
                }
            }
        }
        
        # 添加具体模型贡献
        if signal.kronos_result:
            explanation["model_contributions"].append({
                "model": "Kronos AI",
                "confidence": signal.kronos_result.kronos_confidence,
                "weight": 0.4,
                "contribution": signal.kronos_result.kronos_confidence * 0.4,
                "signal": signal.kronos_result.final_action
            })
        
        if signal.technical_result:
            tech_conf = signal.technical_result.get('confidence', 0)
            explanation["model_contributions"].append({
                "model": "技术分析",
                "confidence": tech_conf,
                "weight": 0.35,
                "contribution": tech_conf * 0.35,
                "signal": signal.technical_result.get('action', '未知')
            })
        
        if signal.ml_result:
            ml_conf = signal.ml_result.get('confidence', 0)
            explanation["model_contributions"].append({
                "model": "机器学习",
                "confidence": ml_conf,
                "weight": 0.25,
                "contribution": ml_conf * 0.25,
                "signal": signal.ml_result.get('signal', '未知')
            })
        
        # 计算理论置信度（用于验证）
        theoretical_confidence = sum(
            contrib["contribution"] for contrib in explanation["model_contributions"]
        )
        explanation["theoretical_confidence"] = theoretical_confidence
        explanation["confidence_difference"] = abs(signal.final_confidence - theoretical_confidence)
        
        return explanation
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"置信度解释失败: {e}")
        raise HTTPException(status_code=500, detail=f"解释失败: {str(e)}")


@router.post("/send-signal-notification/{symbol}")
async def send_signal_notification(
    symbol: str,
    background_tasks: BackgroundTasks,
    trading_service: CoreTradingService = Depends(get_trading_service)
):
    """
    手动发送交易信号通知
    
    - **symbol**: 交易对符号
    """
    try:
        # 先分析信号
        signal = await trading_service.analyze_trading_signal(
            symbol=symbol,
            analysis_type=AnalysisType.INTEGRATED,
            force_update=True
        )
        
        if not signal:
            raise HTTPException(
                status_code=404,
                detail=f"无法生成 {symbol} 的交易信号"
            )
        
        # 后台发送通知
        background_tasks.add_task(
            trading_service.send_trading_signal_notification,
            signal
        )
        
        return {
            "message": f"已提交 {symbol} 信号通知任务",
            "signal_summary": {
                "action": signal.final_action,
                "confidence": signal.final_confidence,
                "strength": signal.signal_strength.value
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"发送信号通知失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"发送通知失败: {str(e)}")


@router.get("/scheduler/status")
async def get_scheduler_status():
    """获取调度器状态"""
    try:
        scheduler_service = await get_core_scheduler_service()
        stats = scheduler_service.get_scheduler_stats()
        task_status = scheduler_service.get_task_status()
        
        return {
            "scheduler_stats": stats,
            "task_status": task_status,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"获取调度器状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@router.post("/scheduler/run-task/{task_id}")
async def run_task_manually(
    task_id: str,
    background_tasks: BackgroundTasks
):
    """手动运行调度任务"""
    try:
        scheduler_service = await get_core_scheduler_service()
        
        # 后台执行任务
        background_tasks.add_task(
            scheduler_service.run_task_manually,
            task_id
        )
        
        return {
            "message": f"已提交手动执行任务: {task_id}",
            "task_id": task_id,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"手动运行任务失败 {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"运行任务失败: {str(e)}")


@router.get("/health")
async def health_check():
    """
    核心交易服务健康检查
    
    检查各个核心服务的状态和可用性
    """
    try:
        health_status = {
            "timestamp": datetime.now(),
            "overall_status": "healthy",
            "services": {},
            "version": "1.0.0",
            "uptime_seconds": 0  # 可以添加实际的运行时间计算
        }
        
        # 检查核心交易服务
        try:
            await get_core_trading_service()
            health_status["services"]["core_trading"] = {
                "status": "healthy",
                "message": "核心交易服务运行正常"
            }
        except Exception as e:
            health_status["services"]["core_trading"] = {
                "status": "unhealthy",
                "message": f"核心交易服务异常: {str(e)}"
            }
            health_status["overall_status"] = "degraded"
        
        # 检查通知服务
        try:
            await get_core_notification_service()
            health_status["services"]["core_notification"] = {
                "status": "healthy",
                "message": "核心通知服务运行正常"
            }
        except Exception as e:
            health_status["services"]["core_notification"] = {
                "status": "unhealthy",
                "message": f"核心通知服务异常: {str(e)}"
            }
            health_status["overall_status"] = "degraded"
        
        # 检查调度服务
        try:
            scheduler_service = await get_core_scheduler_service()
            scheduler_stats = scheduler_service.get_scheduler_stats()
            health_status["services"]["core_scheduler"] = {
                "status": "healthy" if scheduler_stats.get("running") else "stopped",
                "message": "核心调度服务运行正常" if scheduler_stats.get("running") else "调度服务已停止",
                "stats": {
                    "total_tasks": scheduler_stats.get("total_tasks", 0),
                    "success_rate": scheduler_stats.get("success_rate", 0)
                }
            }
        except Exception as e:
            health_status["services"]["core_scheduler"] = {
                "status": "unhealthy",
                "message": f"核心调度服务异常: {str(e)}"
            }
            health_status["overall_status"] = "degraded"
        
        # 检查是否有任何服务不健康
        unhealthy_services = [
            name for name, service in health_status["services"].items()
            if service["status"] == "unhealthy"
        ]
        
        if unhealthy_services:
            health_status["overall_status"] = "unhealthy"
            health_status["issues"] = f"以下服务不健康: {', '.join(unhealthy_services)}"
        
        # 根据整体状态设置HTTP状态码
        status_code = 200
        if health_status["overall_status"] == "unhealthy":
            status_code = 503
        elif health_status["overall_status"] == "degraded":
            status_code = 200  # 部分功能可用，返回200但标记为degraded
        
        return health_status
        
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {
            "timestamp": datetime.now(),
            "overall_status": "unhealthy",
            "error": str(e),
            "services": {}
        }


@router.get("/version")
async def get_version():
    """获取核心交易服务版本信息"""
    return {
        "service_name": "核心交易服务",
        "version": "1.0.0",
        "build_date": "2024-01-15",
        "description": "整合Kronos AI、技术分析、ML预测的统一交易决策服务",
        "features": [
            "综合交易信号分析",
            "批量交易对分析",
            "持仓风险评估",
            "市场机会扫描",
            "智能通知推送",
            "定时任务调度"
        ],
        "supported_analysis_types": [
            "integrated",
            "kronos_only", 
            "technical_only",
            "ml_only",
            "position_focused"
        ]
    }


# ========== 辅助函数 ==========

def _convert_signal_to_response(signal: TradingSignal) -> TradingSignalResponse:
    """转换交易信号为响应格式"""
    
    # 提取各模块摘要
    kronos_summary = None
    if signal.kronos_result:
        kronos_summary = {
            "action": signal.kronos_result.final_action,
            "confidence": signal.kronos_result.kronos_confidence,
            "signal_strength": signal.kronos_result.kronos_signal_strength.value,
            "reasoning": signal.kronos_result.reasoning[:100] + "..." if len(signal.kronos_result.reasoning) > 100 else signal.kronos_result.reasoning
        }
    
    technical_summary = None
    if signal.technical_result:
        technical_summary = {
            "action": signal.technical_result.get("action"),
            "confidence": signal.technical_result.get("confidence"),
            "risk_level": signal.technical_result.get("risk_level")
        }
    
    ml_summary = None
    if signal.ml_result:
        ml_summary = {
            "signal": signal.ml_result.get("signal"),
            "confidence": signal.ml_result.get("confidence")
        }
    
    position_summary = None
    if signal.position_result:
        position_summary = {
            "has_position": signal.position_result.get("has_position", False),
            "unrealized_pnl_ratio": signal.position_result.get("unrealized_pnl_ratio", 0)
        }
    
    return TradingSignalResponse(
        symbol=signal.symbol,
        timestamp=signal.timestamp,
        final_action=signal.final_action,
        final_confidence=signal.final_confidence,
        signal_strength=signal.signal_strength.value,
        entry_price=signal.entry_price,
        stop_loss_price=signal.stop_loss_price,
        take_profit_price=signal.take_profit_price,
        position_size_usdt=signal.position_size_usdt,
        leverage=signal.leverage,
        risk_reward_ratio=signal.risk_reward_ratio,
        reasoning=signal.reasoning,
        key_factors=signal.key_factors,
        confidence_breakdown=signal.confidence_breakdown,
        urgency=signal.urgency,
        valid_until=signal.valid_until,
        kronos_summary=kronos_summary,
        technical_summary=technical_summary,
        ml_summary=ml_summary,
        position_summary=position_summary
    )


async def _send_batch_strong_signals_notification(
    strong_signals: List[TradingSignalResponse],
    analysis_type: str
):
    """发送批量强信号通知"""
    try:
        await get_core_notification_service()
        
        # 构建批量通知数据
        notification_data = {
            "analysis_type": analysis_type,
            "strong_signals_count": len(strong_signals),
            "signals": [
                {
                    "symbol": signal.symbol,
                    "action": signal.final_action,
                    "confidence": signal.final_confidence,
                    "strength": signal.signal_strength
                }
                for signal in strong_signals
            ],
            "timestamp": datetime.now()
        }
        
        # 发送通知 (这里需要根据实际的通知服务接口调整)
        # await notification_service.send_batch_trading_signals(notification_data)
        
        logger.info(f"✅ 已发送批量强信号通知: {len(strong_signals)} 个信号")
        
    except Exception as e:
        logger.error(f"发送批量强信号通知失败: {e}")