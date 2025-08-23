# -*- coding: utf-8 -*-
"""
综合交易策略API
Comprehensive Trading Strategy API endpoints
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.comprehensive_trading_service import ComprehensiveTradingService
from app.schemas.base import BaseResponse

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter()


class TradingSessionRequest(BaseModel):
    """交易会话请求模型"""
    symbols: List[str] = Field(..., description="交易对列表", min_items=1, max_items=50)
    session_config: Optional[Dict[str, Any]] = Field(default=None, description="会话配置")


class MarketScanRequest(BaseModel):
    """市场扫描请求模型"""
    symbols: List[str] = Field(..., description="交易对列表", min_items=1, max_items=100)
    account_balance: float = Field(default=10000, gt=0, description="账户余额")
    send_notifications: bool = Field(default=True, description="是否发送通知")


class PortfolioAnalysisRequest(BaseModel):
    """投资组合分析请求模型"""
    positions: Dict[str, float] = Field(..., description="当前持仓 {symbol: position_size}")
    account_balance: float = Field(..., gt=0, description="账户余额")


class MonitoringRequest(BaseModel):
    """监控请求模型"""
    symbols: List[str] = Field(..., description="监控的交易对列表", min_items=1, max_items=50)
    monitoring_config: Optional[Dict[str, Any]] = Field(default=None, description="监控配置")


class TradingSessionResponse(BaseResponse):
    """交易会话响应模型"""
    session_id: str
    symbols: List[str]
    start_time: datetime


class MarketScanResponse(BaseResponse):
    """市场扫描响应模型"""
    scan_results: Dict[str, Any]
    market_summary: Dict[str, Any]
    scan_duration_seconds: float


class PortfolioAnalysisResponse(BaseResponse):
    """投资组合分析响应模型"""
    portfolio_metrics: Dict[str, Any]
    position_analyses: Dict[str, Any]
    portfolio_recommendations: List[str]
    risk_assessment: Dict[str, Any]
    analysis_duration_seconds: float


# 创建服务实例
comprehensive_service = ComprehensiveTradingService()


@router.post("/session/start", response_model=TradingSessionResponse)
async def start_trading_session(request: TradingSessionRequest) -> TradingSessionResponse:
    """
    启动交易会话
    
    创建一个新的交易会话，可以配置自动分析和通知
    """
    try:
        session_id = await comprehensive_service.start_trading_session(
            symbols=request.symbols,
            session_config=request.session_config
        )
        
        return TradingSessionResponse(
            status="success",
            session_id=session_id,
            symbols=request.symbols,
            start_time=datetime.now(),
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Failed to start trading session: {e}")
        raise HTTPException(status_code=500, detail=f"启动交易会话失败: {str(e)}")


@router.post("/session/{session_id}/stop", response_model=BaseResponse)
async def stop_trading_session(session_id: str) -> BaseResponse:
    """
    停止交易会话
    
    停止指定的交易会话并返回会话摘要
    """
    try:
        summary = await comprehensive_service.stop_trading_session(session_id)
        
        return BaseResponse(
            status="success",
            data=summary,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Failed to stop trading session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"停止交易会话失败: {str(e)}")


@router.get("/session/{session_id}/status", response_model=BaseResponse)
async def get_session_status(session_id: str) -> BaseResponse:
    """
    获取交易会话状态
    
    查询指定交易会话的当前状态和统计信息
    """
    try:
        status = comprehensive_service.get_session_status(session_id)
        
        if "error" in status:
            raise HTTPException(status_code=404, detail="交易会话不存在")
        
        return BaseResponse(
            status="success",
            data=status,
            timestamp=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session status {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"获取会话状态失败: {str(e)}")


@router.post("/market-scan", response_model=MarketScanResponse)
async def comprehensive_market_scan(request: MarketScanRequest) -> MarketScanResponse:
    """
    综合市场扫描
    
    对多个交易对进行全面分析，包括技术指标、ML预测和风险评估
    """
    try:
        scan_results = await comprehensive_service.comprehensive_market_scan(
            symbols=request.symbols,
            account_balance=request.account_balance,
            send_notifications=request.send_notifications
        )
        
        return MarketScanResponse(
            status="success",
            scan_results=scan_results["scan_results"],
            market_summary=scan_results["market_summary"],
            scan_duration_seconds=scan_results["scan_duration_seconds"],
            timestamp=scan_results["timestamp"]
        )
        
    except Exception as e:
        logger.error(f"Comprehensive market scan failed: {e}")
        raise HTTPException(status_code=500, detail=f"市场扫描失败: {str(e)}")


@router.post("/portfolio/analyze", response_model=PortfolioAnalysisResponse)
async def analyze_portfolio(request: PortfolioAnalysisRequest) -> PortfolioAnalysisResponse:
    """
    投资组合分析
    
    分析当前投资组合的风险、收益和优化建议
    """
    try:
        analysis_results = await comprehensive_service.portfolio_analysis(
            positions=request.positions,
            account_balance=request.account_balance
        )
        
        return PortfolioAnalysisResponse(
            status="success",
            portfolio_metrics=analysis_results["portfolio_metrics"],
            position_analyses=analysis_results["position_analyses"],
            portfolio_recommendations=analysis_results["portfolio_recommendations"],
            risk_assessment=analysis_results["risk_assessment"],
            analysis_duration_seconds=analysis_results["analysis_duration_seconds"],
            timestamp=analysis_results["timestamp"]
        )
        
    except Exception as e:
        logger.error(f"Portfolio analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"投资组合分析失败: {str(e)}")


@router.post("/monitoring/start", response_model=BaseResponse)
async def start_real_time_monitoring(request: MonitoringRequest) -> BaseResponse:
    """
    启动实时监控
    
    对指定交易对启动实时监控，自动检测异常并发送警报
    """
    try:
        task_id = await comprehensive_service.real_time_monitoring(
            symbols=request.symbols,
            monitoring_config=request.monitoring_config
        )
        
        return BaseResponse(
            status="success",
            data={
                "monitoring_task_id": task_id,
                "symbols": request.symbols,
                "config": request.monitoring_config
            },
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Failed to start real-time monitoring: {e}")
        raise HTTPException(status_code=500, detail=f"启动实时监控失败: {str(e)}")


@router.get("/portfolio/history", response_model=BaseResponse)
async def get_portfolio_history(
    hours: int = Query(default=24, ge=1, le=168, description="历史小时数")
) -> BaseResponse:
    """
    获取投资组合历史
    
    查询指定时间范围内的投资组合历史快照
    """
    try:
        history = comprehensive_service.get_portfolio_history(hours=hours)
        
        return BaseResponse(
            status="success",
            data={
                "history": history,
                "hours": hours,
                "snapshot_count": len(history)
            },
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Failed to get portfolio history: {e}")
        raise HTTPException(status_code=500, detail=f"获取投资组合历史失败: {str(e)}")


@router.post("/quick-analysis", response_model=BaseResponse)
async def quick_market_analysis(
    symbols: List[str] = Body(..., description="交易对列表", min_items=1, max_items=20),
    analysis_type: str = Body(default="comprehensive", description="分析类型"),
    send_notifications: bool = Body(default=False, description="是否发送通知")
) -> BaseResponse:
    """
    快速市场分析
    
    对少量交易对进行快速分析，适用于即时决策
    """
    try:
        if analysis_type == "comprehensive":
            # 综合分析
            scan_results = await comprehensive_service.comprehensive_market_scan(
                symbols=symbols,
                account_balance=10000,  # 使用默认余额
                send_notifications=send_notifications
            )
            
            # 提取关键信息
            quick_results = {}
            for symbol, result in scan_results["scan_results"].items():
                if "error" not in result:
                    recommendation = result.get("recommendation", {})
                    analysis = result.get("analysis", {})
                    
                    quick_results[symbol] = {
                        "action": recommendation.get("action", "hold"),
                        "confidence": recommendation.get("confidence", 0),
                        "risk_level": recommendation.get("risk_level", "medium"),
                        "market_regime": analysis.get("market_regime", "unknown"),
                        "volatility": analysis.get("volatility_score", 50)
                    }
                else:
                    quick_results[symbol] = {"error": result["error"]}
            
            return BaseResponse(
                status="success",
                data={
                    "analysis_type": analysis_type,
                    "results": quick_results,
                    "summary": scan_results["market_summary"],
                    "analysis_duration": scan_results["scan_duration_seconds"]
                },
                timestamp=datetime.now()
            )
        
        else:
            raise HTTPException(status_code=400, detail=f"不支持的分析类型: {analysis_type}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quick market analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"快速分析失败: {str(e)}")


@router.get("/market-overview", response_model=BaseResponse)
async def get_market_overview(
    top_symbols: int = Query(default=20, ge=5, le=50, description="顶级交易对数量")
) -> BaseResponse:
    """
    获取市场概览
    
    提供主要交易对的市场概览和趋势分析
    """
    try:
        # 获取热门交易对（这里使用预定义列表，实际可以从交易所API获取）
        popular_symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT",
            "XRPUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "SHIBUSDT",
            "MATICUSDT", "LTCUSDT", "UNIUSDT", "LINKUSDT", "ATOMUSDT",
            "ETCUSDT", "XLMUSDT", "BCHUSDT", "FILUSDT", "TRXUSDT"
        ]
        
        # 限制数量
        symbols_to_analyze = popular_symbols[:top_symbols]
        
        # 执行快速扫描
        scan_results = await comprehensive_service.comprehensive_market_scan(
            symbols=symbols_to_analyze,
            account_balance=10000,
            send_notifications=False
        )
        
        # 生成市场概览
        market_overview = {
            "scan_time": scan_results["timestamp"],
            "total_analyzed": len(symbols_to_analyze),
            "market_summary": scan_results["market_summary"],
            "top_gainers": [],
            "top_losers": [],
            "high_volatility": [],
            "strong_signals": []
        }
        
        # 分析结果并分类
        for symbol, result in scan_results["scan_results"].items():
            if "error" not in result:
                recommendation = result.get("recommendation", {})
                analysis = result.get("analysis", {})
                
                # 强信号
                if (recommendation.get("confidence", 0) > 80 and 
                    recommendation.get("action") in ["strong_buy", "strong_sell"]):
                    market_overview["strong_signals"].append({
                        "symbol": symbol,
                        "action": recommendation.get("action"),
                        "confidence": recommendation.get("confidence")
                    })
                
                # 高波动性
                if analysis.get("volatility_score", 0) > 80:
                    market_overview["high_volatility"].append({
                        "symbol": symbol,
                        "volatility": analysis.get("volatility_score")
                    })
        
        # 排序
        market_overview["strong_signals"].sort(key=lambda x: x["confidence"], reverse=True)
        market_overview["high_volatility"].sort(key=lambda x: x["volatility"], reverse=True)
        
        # 限制返回数量
        market_overview["strong_signals"] = market_overview["strong_signals"][:10]
        market_overview["high_volatility"] = market_overview["high_volatility"][:10]
        
        return BaseResponse(
            status="success",
            data=market_overview,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Market overview failed: {e}")
        raise HTTPException(status_code=500, detail=f"获取市场概览失败: {str(e)}")