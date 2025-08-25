# -*- coding: utf-8 -*-
"""
收益机会API
Profit Opportunities API - 发现和推送高收益交易机会
"""

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime

from app.core.logging import get_logger
from app.strategies.profit_maximization_strategies import (
    get_profit_maximization_service, 
    OpportunityType,
    ProfitOpportunity
)
from app.services.intelligent_trading_notification_service import get_intelligent_notification_service

logger = get_logger(__name__)
router = APIRouter(prefix="/api/profit", tags=["收益机会"])


@router.get("/opportunities", summary="获取收益机会")
async def get_profit_opportunities(
    symbols: Optional[str] = Query(None, description="交易对列表，逗号分隔"),
    opportunity_types: Optional[str] = Query(None, description="机会类型，逗号分隔"),
    min_return: Optional[float] = Query(5.0, description="最低预期收益率%"),
    min_confidence: Optional[float] = Query(0.7, description="最低置信度"),
    limit: Optional[int] = Query(20, description="返回数量限制")
) -> Dict[str, Any]:
    """
    获取当前可用的收益机会
    
    Args:
        symbols: 指定交易对，如 "BTC-USDT-SWAP,ETH-USDT-SWAP"
        opportunity_types: 指定机会类型，如 "BREAKOUT,MOMENTUM"
        min_return: 最低预期收益率
        min_confidence: 最低置信度
        limit: 返回数量限制
    
    Returns:
        Dict: 收益机会列表和统计信息
    """
    try:
        profit_service = await get_profit_maximization_service()
        
        # 解析参数
        symbol_list = symbols.split(',') if symbols else None
        type_filter = opportunity_types.split(',') if opportunity_types else None
        
        # 扫描机会
        opportunities = await profit_service.scan_all_opportunities(symbol_list)
        
        # 过滤条件
        filtered_opportunities = []
        for opp in opportunities:
            # 收益率过滤
            if opp.expected_return < min_return:
                continue
            
            # 置信度过滤
            if opp.confidence < min_confidence:
                continue
            
            # 类型过滤
            if type_filter and opp.opportunity_type.name not in type_filter:
                continue
            
            filtered_opportunities.append(opp)
        
        # 限制数量
        filtered_opportunities = filtered_opportunities[:limit]
        
        # 格式化返回数据
        formatted_opportunities = []
        for opp in filtered_opportunities:
            formatted_opportunities.append({
                'symbol': opp.symbol,
                'opportunity_type': opp.opportunity_type.value,
                'entry_price': opp.entry_price,
                'target_price': opp.target_price,
                'stop_loss': opp.stop_loss,
                'expected_return': f"{opp.expected_return:.2f}%",
                'risk_reward_ratio': f"1:{opp.risk_reward_ratio:.1f}",
                'confidence': f"{opp.confidence:.1%}",
                'time_horizon': opp.time_horizon,
                'urgency': opp.urgency,
                'reasoning': opp.reasoning,
                'kronos_support': opp.kronos_support,
                'kronos_confidence': f"{opp.kronos_confidence:.1%}" if opp.kronos_confidence > 0 else "N/A",
                'market_sentiment': opp.market_sentiment,
                'volume_profile': opp.volume_profile,
                'timestamp': opp.timestamp.isoformat()
            })
        
        # 统计信息
        stats = {
            'total_scanned': len(opportunities),
            'total_filtered': len(filtered_opportunities),
            'by_type': {},
            'by_urgency': {},
            'avg_expected_return': 0,
            'avg_confidence': 0
        }
        
        if filtered_opportunities:
            # 按类型统计
            for opp in filtered_opportunities:
                opp_type = opp.opportunity_type.value
                stats['by_type'][opp_type] = stats['by_type'].get(opp_type, 0) + 1
                
                urgency = opp.urgency
                stats['by_urgency'][urgency] = stats['by_urgency'].get(urgency, 0) + 1
            
            # 平均值
            stats['avg_expected_return'] = sum(opp.expected_return for opp in filtered_opportunities) / len(filtered_opportunities)
            stats['avg_confidence'] = sum(opp.confidence for opp in filtered_opportunities) / len(filtered_opportunities)
        
        return {
            'success': True,
            'data': {
                'opportunities': formatted_opportunities,
                'stats': stats
            },
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"获取收益机会失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取收益机会失败: {str(e)}")


@router.get("/top-opportunities", summary="获取顶级收益机会")
async def get_top_opportunities(
    count: int = Query(5, description="返回数量", ge=1, le=10)
) -> Dict[str, Any]:
    """
    获取当前最佳的收益机会（自动筛选）
    
    Args:
        count: 返回的机会数量
    
    Returns:
        Dict: 顶级收益机会
    """
    try:
        profit_service = await get_profit_maximization_service()
        
        # 获取所有机会
        all_opportunities = await profit_service.scan_all_opportunities()
        
        # 智能筛选顶级机会
        top_opportunities = []
        
        for opp in all_opportunities:
            # 顶级机会标准
            is_top = (
                opp.expected_return >= 8.0 and      # 预期收益8%+
                opp.confidence >= 0.8 and           # 置信度80%+
                opp.risk_reward_ratio >= 2.0 and    # 风险收益比2:1+
                opp.urgency in ['immediate', 'within_1h']  # 紧急程度高
            )
            
            if is_top:
                top_opportunities.append(opp)
        
        # 按综合评分排序
        def calculate_score(opp):
            return (
                opp.expected_return * 0.4 +           # 收益权重40%
                opp.confidence * 100 * 0.3 +          # 置信度权重30%
                opp.risk_reward_ratio * 10 * 0.2 +    # 风险收益比权重20%
                (20 if opp.kronos_support else 0) * 0.1  # Kronos支持权重10%
            )
        
        top_opportunities.sort(key=calculate_score, reverse=True)
        top_opportunities = top_opportunities[:count]
        
        # 格式化返回
        formatted_top = []
        for opp in top_opportunities:
            formatted_top.append({
                'rank': len(formatted_top) + 1,
                'symbol': opp.symbol,
                'opportunity_type': opp.opportunity_type.value,
                'expected_return': f"{opp.expected_return:.1f}%",
                'confidence': f"{opp.confidence:.0%}",
                'risk_reward': f"1:{opp.risk_reward_ratio:.1f}",
                'urgency': opp.urgency,
                'entry_price': opp.entry_price,
                'target_price': opp.target_price,
                'stop_loss': opp.stop_loss,
                'reasoning': opp.reasoning,
                'kronos_support': "✅" if opp.kronos_support else "❌",
                'score': f"{calculate_score(opp):.1f}",
                'timestamp': opp.timestamp.isoformat()
            })
        
        return {
            'success': True,
            'data': {
                'top_opportunities': formatted_top,
                'summary': {
                    'total_found': len(all_opportunities),
                    'top_selected': len(formatted_top),
                    'avg_return': f"{sum(opp.expected_return for opp in top_opportunities) / len(top_opportunities):.1f}%" if top_opportunities else "0%",
                    'kronos_supported': sum(1 for opp in top_opportunities if opp.kronos_support)
                }
            },
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"获取顶级机会失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取顶级机会失败: {str(e)}")


@router.post("/notify-opportunities", summary="推送收益机会通知")
async def notify_profit_opportunities(
    min_return: float = Query(10.0, description="最低收益率阈值"),
    force_send: bool = Query(False, description="强制发送")
) -> Dict[str, Any]:
    """
    扫描并推送高收益机会通知
    
    Args:
        min_return: 最低收益率阈值
        force_send: 是否强制发送通知
    
    Returns:
        Dict: 推送结果
    """
    try:
        profit_service = await get_profit_maximization_service()
        notification_service = await get_intelligent_notification_service()
        
        # 扫描高收益机会
        opportunities = await profit_service.scan_all_opportunities()
        
        # 筛选符合条件的机会
        high_return_opportunities = [
            opp for opp in opportunities
            if opp.expected_return >= min_return and opp.confidence >= 0.75
        ]
        
        if not high_return_opportunities:
            return {
                'success': True,
                'message': f'未发现收益率超过{min_return}%的机会',
                'data': {'opportunities_found': 0, 'notifications_sent': 0}
            }
        
        # 构建通知消息
        notifications_sent = 0
        
        for opp in high_return_opportunities[:5]:  # 最多推送5个
            message = f"""🚀 【高收益机会】{opp.opportunity_type.value}

💎 交易对: {opp.symbol}
📈 预期收益: {opp.expected_return:.1f}%
🎯 置信度: {opp.confidence:.0%}
📊 风险收益比: 1:{opp.risk_reward_ratio:.1f}
⏰ 时效性: {opp.urgency}

💡 交易建议:
• 入场价: {opp.entry_price:.4f}
• 目标价: {opp.target_price:.4f}
• 止损价: {opp.stop_loss:.4f}

🔍 机会分析: {opp.reasoning}

🤖 Kronos支持: {"✅" if opp.kronos_support else "❌"}
📊 市场情绪: {opp.market_sentiment}
📈 成交量: {opp.volume_profile}

⏰ 发现时间: {opp.timestamp.strftime('%H:%M:%S')}"""

            try:
                await notification_service.notification_service.send_notification(
                    message, priority="high"
                )
                notifications_sent += 1
                logger.info(f"已推送收益机会通知: {opp.symbol} - {opp.expected_return:.1f}%")
                
            except Exception as e:
                logger.error(f"推送通知失败 {opp.symbol}: {e}")
        
        return {
            'success': True,
            'message': f'成功推送{notifications_sent}个高收益机会',
            'data': {
                'opportunities_found': len(high_return_opportunities),
                'notifications_sent': notifications_sent,
                'top_opportunity': {
                    'symbol': high_return_opportunities[0].symbol,
                    'return': f"{high_return_opportunities[0].expected_return:.1f}%",
                    'type': high_return_opportunities[0].opportunity_type.value
                } if high_return_opportunities else None
            },
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"推送收益机会失败: {e}")
        raise HTTPException(status_code=500, detail=f"推送失败: {str(e)}")


@router.get("/opportunity-types", summary="获取机会类型列表")
async def get_opportunity_types() -> Dict[str, Any]:
    """
    获取所有可用的机会类型
    
    Returns:
        Dict: 机会类型列表和说明
    """
    opportunity_types = []
    
    for opp_type in OpportunityType:
        opportunity_types.append({
            'name': opp_type.name,
            'value': opp_type.value,
            'description': _get_opportunity_description(opp_type)
        })
    
    return {
        'success': True,
        'data': {
            'opportunity_types': opportunity_types,
            'total_types': len(opportunity_types)
        }
    }


def _get_opportunity_description(opp_type: OpportunityType) -> str:
    """获取机会类型描述"""
    descriptions = {
        OpportunityType.BREAKOUT: "价格突破关键阻力或支撑位，适合趋势跟随",
        OpportunityType.REVERSAL: "趋势反转信号，适合逆向交易",
        OpportunityType.MOMENTUM: "强势动量延续，适合顺势而为",
        OpportunityType.ARBITRAGE: "价差套利机会，风险相对较低",
        OpportunityType.FUNDING_RATE: "资金费率套利，稳定收益来源",
        OpportunityType.VOLATILITY: "高波动率交易，适合短线操作",
        OpportunityType.NEWS_DRIVEN: "消息面驱动的交易机会",
        OpportunityType.TECHNICAL_PATTERN: "经典技术形态，技术分析基础"
    }
    return descriptions.get(opp_type, "暂无描述")