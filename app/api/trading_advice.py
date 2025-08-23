# -*- coding: utf-8 -*-
"""
交易建议API
Trading Advice API - 提供基于OKX数据的实际交易建议
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel, Field
from datetime import datetime

from app.services.trading_decision_service import TradingDecisionService, TradingRecommendation
from app.core.logging import get_logger
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
router = APIRouter()


class TradingAdviceResponse(BaseModel):
    """交易建议响应"""
    symbol: str
    action: str
    confidence: float
    
    # 核心建议
    position_size_usdt: float = Field(description="建议仓位金额(USDT)")
    position_size_percent: float = Field(description="建议仓位百分比")
    leverage: float = Field(description="建议杠杆倍数")
    
    # 价格点位
    current_price: float = Field(description="当前价格")
    entry_price: float = Field(description="建议入场价格")
    stop_loss_price: float = Field(description="止损价格")
    take_profit_price: float = Field(description="止盈价格")
    
    # 风险管理
    risk_level: str = Field(description="风险等级")
    max_loss_usdt: float = Field(description="最大亏损金额")
    expected_profit_usdt: float = Field(description="预期盈利金额")
    risk_reward_ratio: float = Field(description="风险收益比")
    
    # 执行建议
    entry_timing: str = Field(description="入场时机")
    hold_duration_hours: Optional[int] = Field(description="建议持仓时间(小时)")
    
    # 决策依据
    reasoning: str = Field(description="决策理由")
    
    # 账户信息
    account_equity: float = Field(description="账户总权益")
    current_positions: Optional[Dict] = Field(description="当前持仓")
    
    timestamp: datetime = Field(description="生成时间")


class AccountSummaryResponse(BaseModel):
    """账户摘要响应"""
    total_equity: float = Field(description="总权益(USDT)")
    available_balance: float = Field(description="可用余额")
    total_positions: int = Field(description="持仓数量")
    total_unrealized_pnl: float = Field(description="总未实现盈亏")
    positions: List[Dict[str, Any]] = Field(description="持仓详情")
    timestamp: datetime = Field(description="更新时间")


@router.get("/advice/{symbol}", response_model=TradingAdviceResponse)
async def get_trading_advice(
    symbol: str = Path(..., description="交易对，如: BTC-USDT-SWAP"),
    exchange: str = Query("okx", description="交易所，默认okx")
) -> TradingAdviceResponse:
    """
    获取交易建议
    
    基于实际账户数据和市场分析，提供具体的交易建议，包括：
    - 开仓方向和仓位大小
    - 杠杆倍数建议
    - 止盈止损点位
    - 风险评估和预期收益
    """
    try:
        # 创建交易决策服务
        decision_service = TradingDecisionService(exchange=exchange)
        
        # 获取交易建议
        recommendation = await decision_service.get_trading_recommendation(symbol)
        
        return TradingAdviceResponse(
            symbol=recommendation.symbol,
            action=recommendation.action.value,
            confidence=recommendation.confidence,
            
            position_size_usdt=recommendation.position_size_usdt,
            position_size_percent=recommendation.position_size_percent,
            leverage=recommendation.leverage,
            
            current_price=recommendation.current_price,
            entry_price=recommendation.entry_price,
            stop_loss_price=recommendation.stop_loss_price,
            take_profit_price=recommendation.take_profit_price,
            
            risk_level=recommendation.risk_level.value,
            max_loss_usdt=recommendation.max_loss_usdt,
            expected_profit_usdt=recommendation.expected_profit_usdt,
            risk_reward_ratio=recommendation.risk_reward_ratio,
            
            entry_timing=recommendation.entry_timing,
            hold_duration_hours=recommendation.hold_duration_hours,
            
            reasoning=recommendation.reasoning,
            
            account_equity=recommendation.account_info.get('total_equity', 0),
            current_positions=recommendation.current_positions,
            
            timestamp=datetime.now()
        )
        
    except TradingToolError as e:
        logger.error(f"获取交易建议失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"交易建议服务异常: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用")


@router.get("/account/summary", response_model=AccountSummaryResponse)
async def get_account_summary(
    exchange: str = Query("okx", description="交易所，默认okx")
) -> AccountSummaryResponse:
    """
    获取账户摘要
    
    显示当前账户状态，包括：
    - 总权益和可用余额
    - 所有持仓情况
    - 总盈亏状况
    """
    try:
        from app.services.okx_service import OKXService
        
        async with OKXService() as okx:
            # 获取账户信息和持仓
            account_info = await okx.get_account_balance()
            positions = await okx.get_positions()
            
            # 计算汇总数据
            total_equity = account_info.get('total_equity', 0)
            available_balance = account_info.get('balances', {}).get('USDT', {}).get('available', 0)
            
            total_unrealized_pnl = sum(pos.get('unrealized_pnl', 0) for pos in positions)
            
            return AccountSummaryResponse(
                total_equity=total_equity,
                available_balance=available_balance,
                total_positions=len(positions),
                total_unrealized_pnl=total_unrealized_pnl,
                positions=positions,
                timestamp=datetime.now()
            )
            
    except Exception as e:
        logger.error(f"获取账户摘要失败: {e}")
        raise HTTPException(status_code=500, detail="获取账户信息失败")


@router.get("/advice/batch", response_model=List[TradingAdviceResponse])
async def get_batch_trading_advice(
    symbols: str = Query(..., description="交易对列表，逗号分隔，如: BTC-USDT-SWAP,ETH-USDT-SWAP"),
    exchange: str = Query("okx", description="交易所，默认okx")
) -> List[TradingAdviceResponse]:
    """
    批量获取交易建议
    
    一次性获取多个交易对的建议，适合快速决策
    """
    try:
        symbol_list = [s.strip() for s in symbols.split(',')]
        
        if len(symbol_list) > 10:
            raise HTTPException(status_code=400, detail="最多支持10个交易对")
        
        decision_service = TradingDecisionService(exchange=exchange)
        
        # 并行获取建议
        import asyncio
        tasks = [decision_service.get_trading_recommendation(symbol) for symbol in symbol_list]
        recommendations = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = []
        for i, rec in enumerate(recommendations):
            if isinstance(rec, Exception):
                logger.warning(f"获取{symbol_list[i]}建议失败: {rec}")
                continue
                
            results.append(TradingAdviceResponse(
                symbol=rec.symbol,
                action=rec.action.value,
                confidence=rec.confidence,
                
                position_size_usdt=rec.position_size_usdt,
                position_size_percent=rec.position_size_percent,
                leverage=rec.leverage,
                
                current_price=rec.current_price,
                entry_price=rec.entry_price,
                stop_loss_price=rec.stop_loss_price,
                take_profit_price=rec.take_profit_price,
                
                risk_level=rec.risk_level.value,
                max_loss_usdt=rec.max_loss_usdt,
                expected_profit_usdt=rec.expected_profit_usdt,
                risk_reward_ratio=rec.risk_reward_ratio,
                
                entry_timing=rec.entry_timing,
                hold_duration_hours=rec.hold_duration_hours,
                
                reasoning=rec.reasoning,
                
                account_equity=rec.account_info.get('total_equity', 0),
                current_positions=rec.current_positions,
                
                timestamp=datetime.now()
            ))
        
        return results
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量获取交易建议失败: {e}")
        raise HTTPException(status_code=500, detail="批量获取失败")


@router.get("/market/quick-scan")
async def quick_market_scan(
    exchange: str = Query("okx", description="交易所，默认okx")
) -> Dict[str, Any]:
    """
    快速市场扫描
    
    扫描主要交易对，找出最有潜力的交易机会
    """
    try:
        # 主要交易对
        major_symbols = [
            "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", 
            "DOGE-USDT-SWAP", "XRP-USDT-SWAP"
        ]
        
        decision_service = TradingDecisionService(exchange=exchange)
        
        opportunities = []
        
        for symbol in major_symbols:
            try:
                rec = await decision_service.get_trading_recommendation(symbol)
                
                # 只关注有明确交易信号的
                if rec.action.value not in ['hold', 'wait'] and rec.confidence > 65:
                    opportunities.append({
                        'symbol': symbol,
                        'action': rec.action.value,
                        'confidence': rec.confidence,
                        'expected_return': rec.risk_reward_ratio,
                        'risk_level': rec.risk_level.value,
                        'reasoning': rec.reasoning.split('|')[0]  # 只取第一个理由
                    })
                    
            except Exception as e:
                logger.warning(f"扫描{symbol}失败: {e}")
                continue
        
        # 按置信度排序
        opportunities.sort(key=lambda x: x['confidence'], reverse=True)
        
        return {
            'scan_time': datetime.now(),
            'total_scanned': len(major_symbols),
            'opportunities_found': len(opportunities),
            'top_opportunities': opportunities[:3],  # 返回前3个机会
            'all_opportunities': opportunities
        }
        
    except Exception as e:
        logger.error(f"市场扫描失败: {e}")
        raise HTTPException(status_code=500, detail="市场扫描失败")