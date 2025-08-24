# -*- coding: utf-8 -*-
"""
增强交易决策API - 集成Kronos预测
"""

from typing import Dict, List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query, Path
from fastapi.responses import JSONResponse

from app.schemas.kronos import TradingSignalWithKronos
from app.services.enhanced_kronos_trading_service import (
    get_enhanced_kronos_trading_service,
    EnhancedKronosTradingService
)
from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/signal/{symbol}", response_model=TradingSignalWithKronos)
async def get_enhanced_trading_signal(
    symbol: str = Path(..., description="交易对符号"),
    force_update: bool = Query(default=False, description="是否强制更新分析"),
    service: EnhancedKronosTradingService = Depends(get_enhanced_kronos_trading_service)
) -> TradingSignalWithKronos:
    """获取增强的交易信号（技术分析 + Kronos AI预测）"""
    try:
        # 获取增强交易信号
        enhanced_signal = await service.get_enhanced_trading_signal(
            symbol=symbol,
            force_update=force_update
        )
        
        if enhanced_signal is None:
            raise HTTPException(
                status_code=500,
                detail=f"无法生成{symbol}的交易信号"
            )
        
        # 转换为API响应格式
        api_signal = service.convert_to_api_format(enhanced_signal)
        
        logger.info(f"生成{symbol}增强交易信号: {api_signal.final_signal}")
        return api_signal
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取{symbol}增强交易信号失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取交易信号失败: {str(e)}"
        )


@router.post("/signals/batch")
async def get_batch_enhanced_trading_signals(
    symbols: List[str],
    force_update: bool = Query(default=False, description="是否强制更新分析"),
    service: EnhancedKronosTradingService = Depends(get_enhanced_kronos_trading_service)
) -> Dict[str, Optional[TradingSignalWithKronos]]:
    """批量获取增强的交易信号"""
    try:
        if not symbols:
            raise HTTPException(status_code=400, detail="交易对列表不能为空")
        
        if len(symbols) > 20:
            raise HTTPException(status_code=400, detail="一次最多处理20个交易对")
        
        # 批量获取增强信号
        enhanced_signals = await service.get_batch_enhanced_signals(
            symbols=symbols,
            force_update=force_update
        )
        
        # 转换为API响应格式
        api_signals = {}
        successful_count = 0
        
        for symbol, signal in enhanced_signals.items():
            if signal is not None:
                api_signals[symbol] = service.convert_to_api_format(signal)
                successful_count += 1
            else:
                api_signals[symbol] = None
        
        logger.info(f"批量生成增强交易信号完成，成功{successful_count}/{len(symbols)}个")
        return api_signals
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量获取增强交易信号失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"批量获取交易信号失败: {str(e)}"
        )


@router.get("/signals/monitored")
async def get_monitored_symbols_signals(
    force_update: bool = Query(default=False, description="是否强制更新分析"),
    service: EnhancedKronosTradingService = Depends(get_enhanced_kronos_trading_service)
) -> Dict[str, Optional[TradingSignalWithKronos]]:
    """获取所有监控币种的增强交易信号"""
    try:
        settings = get_settings()
        monitored_symbols = settings.monitored_symbols
        
        if not monitored_symbols:
            raise HTTPException(status_code=400, detail="未配置监控币种")
        
        # 批量获取信号
        enhanced_signals = await service.get_batch_enhanced_signals(
            symbols=monitored_symbols,
            force_update=force_update
        )
        
        # 转换为API响应格式
        api_signals = {}
        for symbol, signal in enhanced_signals.items():
            if signal is not None:
                api_signals[symbol] = service.convert_to_api_format(signal)
            else:
                api_signals[symbol] = None
        
        return api_signals
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取监控币种增强交易信号失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取监控币种交易信号失败: {str(e)}"
        )


@router.get("/analysis/{symbol}")
async def get_detailed_analysis(
    symbol: str = Path(..., description="交易对符号"),
    force_update: bool = Query(default=False, description="是否强制更新分析"),
    service: EnhancedKronosTradingService = Depends(get_enhanced_kronos_trading_service)
) -> JSONResponse:
    """获取详细的分析报告"""
    try:
        # 获取增强交易信号
        enhanced_signal = await service.get_enhanced_trading_signal(
            symbol=symbol,
            force_update=force_update
        )
        
        if enhanced_signal is None:
            raise HTTPException(
                status_code=500,
                detail=f"无法生成{symbol}的分析报告"
            )
        
        # 构建详细分析报告
        analysis_report = {
            "symbol": enhanced_signal.symbol,
            "timestamp": enhanced_signal.timestamp.isoformat(),
            "summary": {
                "final_signal": enhanced_signal.final_signal,
                "final_confidence": enhanced_signal.final_confidence,
                "signal_strength": enhanced_signal.signal_strength,
                "confluence_score": enhanced_signal.confluence_score,
                "risk_level": enhanced_signal.risk_level
            },
            "technical_analysis": {
                "signal": enhanced_signal.technical_signal,
                "confidence": enhanced_signal.technical_confidence,
                "supertrend_signals": enhanced_signal.supertrend_signals
            },
            "kronos_prediction": {
                "signal": enhanced_signal.kronos_signal,
                "confidence": enhanced_signal.kronos_confidence,
                "price_target": enhanced_signal.kronos_price_target,
                "trend_direction": enhanced_signal.kronos_trend_direction
            },
            "risk_management": {
                "stop_loss": enhanced_signal.stop_loss,
                "take_profit": enhanced_signal.take_profit,
                "position_size": enhanced_signal.position_size,
                "risk_level": enhanced_signal.risk_level
            },
            "reasoning": enhanced_signal.reasoning,
            "recommendations": {
                "action": enhanced_signal.final_signal,
                "confidence_level": enhanced_signal.signal_strength,
                "position_sizing": f"{enhanced_signal.position_size:.1%}",
                "risk_reward": "1:2" if enhanced_signal.stop_loss and enhanced_signal.take_profit else "未设定"
            }
        }
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": f"{symbol}详细分析报告生成成功",
                "data": analysis_report,
                "timestamp": datetime.now().isoformat()
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取{symbol}详细分析失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取详细分析失败: {str(e)}"
        )


@router.get("/comparison/{symbol}")
async def get_signal_comparison(
    symbol: str = Path(..., description="交易对符号"),
    service: EnhancedKronosTradingService = Depends(get_enhanced_kronos_trading_service)
) -> JSONResponse:
    """获取技术分析与Kronos预测的对比"""
    try:
        # 获取增强交易信号
        enhanced_signal = await service.get_enhanced_trading_signal(
            symbol=symbol,
            force_update=False
        )
        
        if enhanced_signal is None:
            raise HTTPException(
                status_code=500,
                detail=f"无法生成{symbol}的对比分析"
            )
        
        # 构建对比分析
        comparison = {
            "symbol": enhanced_signal.symbol,
            "timestamp": enhanced_signal.timestamp.isoformat(),
            "technical_vs_kronos": {
                "technical_analysis": {
                    "signal": enhanced_signal.technical_signal,
                    "confidence": enhanced_signal.technical_confidence,
                    "method": "SuperTrend多周期分析"
                },
                "kronos_prediction": {
                    "signal": enhanced_signal.kronos_signal,
                    "confidence": enhanced_signal.kronos_confidence,
                    "method": "AI深度学习预测",
                    "price_target": enhanced_signal.kronos_price_target,
                    "trend_direction": enhanced_signal.kronos_trend_direction
                }
            },
            "consensus_analysis": {
                "confluence_score": enhanced_signal.confluence_score,
                "agreement_level": "高度一致" if enhanced_signal.confluence_score > 0.8 
                                 else "部分一致" if enhanced_signal.confluence_score > 0.5 
                                 else "存在分歧",
                "final_recommendation": {
                    "signal": enhanced_signal.final_signal,
                    "confidence": enhanced_signal.final_confidence,
                    "strength": enhanced_signal.signal_strength
                }
            },
            "decision_factors": {
                "technical_weight": "40%",
                "kronos_weight": "60%",
                "confluence_bonus": f"{(enhanced_signal.confluence_score - 0.5) * 20:.1f}%" if enhanced_signal.confluence_score > 0.5 else "0%"
            },
            "interpretation": enhanced_signal.reasoning
        }
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": f"{symbol}信号对比分析完成",
                "data": comparison,
                "timestamp": datetime.now().isoformat()
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取{symbol}信号对比失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取信号对比失败: {str(e)}"
        )