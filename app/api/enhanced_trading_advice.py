# -*- coding: utf-8 -*-
"""
增强交易建议API
Enhanced Trading Advice API - 提供详细的开单建议和ML增强分析
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

from app.services.intelligent_trading_notification_service import IntelligentTradingNotificationService
from app.services.trading_decision_service import TradingDecisionService
from app.services.ml_enhanced_service import MLEnhancedService
from app.services.okx_service import OKXService
from app.core.logging import get_logger
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
router = APIRouter()


class TradingAdviceLevel(str, Enum):
    """建议等级"""
    PREMIUM = "premium"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DetailedTradingAdvice(BaseModel):
    """详细交易建议"""
    # 基本信息
    symbol: str = Field(description="交易对")
    advice_level: TradingAdviceLevel = Field(description="建议等级")
    action: str = Field(description="交易动作")
    confidence: float = Field(description="置信度")
    
    # 详细开单参数
    position_params: Dict[str, Any] = Field(description="仓位参数")
    price_levels: Dict[str, float] = Field(description="价格点位")
    risk_management: Dict[str, Any] = Field(description="风险管理")
    
    # ML增强信息
    ml_analysis: Optional[Dict[str, Any]] = Field(description="机器学习分析")
    market_anomalies: List[str] = Field(description="市场异常")
    
    # 执行建议
    execution_plan: Dict[str, Any] = Field(description="执行计划")
    
    # 市场分析
    market_context: Dict[str, Any] = Field(description="市场环境")
    
    # 风险提示
    risk_warnings: List[str] = Field(description="风险提示")
    
    timestamp: datetime = Field(description="生成时间")


class MarketScanResult(BaseModel):
    """市场扫描结果"""
    scan_summary: Dict[str, Any] = Field(description="扫描摘要")
    premium_opportunities: List[Dict[str, Any]] = Field(description="顶级机会")
    high_opportunities: List[Dict[str, Any]] = Field(description="高质量机会")
    market_overview: Dict[str, Any] = Field(description="市场概况")
    timestamp: datetime = Field(description="扫描时间")


@router.get("/enhanced/{symbol}", response_model=DetailedTradingAdvice)
async def get_enhanced_trading_advice(
    symbol: str = Path(..., description="交易对，如: BTC-USDT-SWAP"),
    include_ml: bool = Query(True, description="是否包含ML分析"),
    risk_tolerance: str = Query("medium", description="风险承受度: low/medium/high")
) -> DetailedTradingAdvice:
    """
    获取增强交易建议
    
    提供详细的开单建议，包括：
    - 精确的仓位计算和杠杆建议
    - 多层次止盈止损策略
    - ML增强的市场分析
    - 详细的执行计划
    """
    try:
        # 初始化服务
        decision_service = TradingDecisionService(exchange='okx')
        ml_service = MLEnhancedService() if include_ml else None
        
        # 获取基础交易建议
        recommendation = await decision_service.get_trading_recommendation(symbol)
        
        # ML增强分析
        ml_analysis = None
        market_anomalies = []
        if ml_service:
            try:
                ml_prediction = await ml_service.predict_signal(symbol)
                anomalies = await ml_service.detect_anomalies(symbol)
                
                ml_analysis = {
                    'signal': ml_prediction.signal.value,
                    'confidence': ml_prediction.confidence,
                    'probability_distribution': ml_prediction.probability_distribution,
                    'model_accuracy': ml_prediction.model_accuracy,
                    'features_importance': dict(list(ml_prediction.features_importance.items())[:5])
                }
                
                market_anomalies = [
                    f"{a.anomaly_type.value}: {a.description}" 
                    for a in anomalies if a.severity > 0.5
                ]
                
            except Exception as e:
                logger.warning(f"ML分析失败: {e}")
        
        # 构建详细仓位参数
        position_params = await _build_position_params(recommendation, risk_tolerance)
        
        # 构建价格点位
        price_levels = await _build_price_levels(recommendation, symbol)
        
        # 构建风险管理策略
        risk_management = await _build_risk_management(recommendation, risk_tolerance)
        
        # 构建执行计划
        execution_plan = await _build_execution_plan(recommendation, ml_analysis)
        
        # 构建市场环境分析
        market_context = await _build_market_context(symbol, recommendation)
        
        # 生成风险提示
        risk_warnings = _generate_risk_warnings(recommendation, ml_analysis, market_anomalies)
        
        # 评估建议等级
        advice_level = _evaluate_advice_level(recommendation, ml_analysis, market_anomalies)
        
        return DetailedTradingAdvice(
            symbol=symbol,
            advice_level=advice_level,
            action=recommendation.action.value,
            confidence=recommendation.confidence,
            
            position_params=position_params,
            price_levels=price_levels,
            risk_management=risk_management,
            
            ml_analysis=ml_analysis,
            market_anomalies=market_anomalies,
            
            execution_plan=execution_plan,
            market_context=market_context,
            risk_warnings=risk_warnings,
            
            timestamp=datetime.now()
        )
        
    except TradingToolError as e:
        logger.error(f"获取增强交易建议失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"增强交易建议服务异常: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用")


@router.get("/market/intelligent-scan", response_model=MarketScanResult)
async def intelligent_market_scan(
    force_scan: bool = Query(False, description="是否强制扫描"),
    min_confidence: float = Query(75.0, description="最低置信度阈值")
) -> MarketScanResult:
    """
    智能市场扫描
    
    扫描所有主要交易对，识别高质量交易机会
    """
    try:
        notification_service = IntelligentTradingNotificationService()
        
        # 执行智能扫描
        scan_results = await notification_service.scan_and_notify_opportunities(
            force_scan=force_scan
        )
        
        # 获取当前机会
        current_opportunities = await notification_service.get_current_opportunities()
        
        # 分类机会
        premium_ops = [op for op in current_opportunities if op.get('confidence', 0) > 85]
        high_ops = [op for op in current_opportunities if 75 <= op.get('confidence', 0) <= 85]
        
        # 构建市场概况
        market_overview = await _build_market_overview()
        
        return MarketScanResult(
            scan_summary=scan_results,
            premium_opportunities=premium_ops,
            high_opportunities=high_ops,
            market_overview=market_overview,
            timestamp=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"智能市场扫描失败: {e}")
        raise HTTPException(status_code=500, detail="市场扫描失败")


@router.post("/notifications/send-opportunities")
async def send_opportunity_notifications(
    force_send: bool = Query(False, description="是否强制发送")
) -> Dict[str, Any]:
    """
    手动触发机会通知
    
    立即扫描并推送交易机会
    """
    try:
        notification_service = IntelligentTradingNotificationService()
        
        results = await notification_service.scan_and_notify_opportunities(
            force_scan=force_send
        )
        
        return {
            'status': 'success',
            'message': '机会扫描和通知完成',
            'results': results,
            'timestamp': datetime.now()
        }
        
    except Exception as e:
        logger.error(f"发送机会通知失败: {e}")
        raise HTTPException(status_code=500, detail="通知发送失败")


@router.get("/position/calculator")
async def position_calculator(
    symbol: str = Query(..., description="交易对"),
    account_balance: float = Query(..., description="账户余额(USDT)"),
    risk_percent: float = Query(2.0, description="风险百分比"),
    entry_price: float = Query(..., description="入场价格"),
    stop_loss_price: float = Query(..., description="止损价格")
) -> Dict[str, Any]:
    """
    仓位计算器
    
    根据风险管理原则计算最优仓位
    """
    try:
        # 计算风险金额
        risk_amount = account_balance * (risk_percent / 100)
        
        # 计算价格风险
        price_risk = abs(entry_price - stop_loss_price) / entry_price
        
        # 计算基础仓位（不含杠杆）
        base_position_usdt = risk_amount / price_risk
        
        # 建议杠杆倍数（保守）
        max_leverage = min(3.0, account_balance / base_position_usdt)
        recommended_leverage = max(1.0, max_leverage * 0.7)  # 使用70%的最大杠杆
        
        # 最终仓位
        final_position_usdt = min(base_position_usdt, account_balance * 0.2)  # 最多20%仓位
        
        # 计算数量
        if 'USD-SWAP' in symbol:
            # 币本位合约
            position_size = final_position_usdt  # 面值以USD计
        else:
            # U本位合约
            position_size = final_position_usdt / entry_price
        
        return {
            'symbol': symbol,
            'calculations': {
                'risk_amount_usdt': risk_amount,
                'price_risk_percent': price_risk * 100,
                'recommended_position_usdt': final_position_usdt,
                'recommended_leverage': recommended_leverage,
                'position_size': position_size,
                'max_loss_usdt': risk_amount
            },
            'risk_metrics': {
                'position_percent_of_account': (final_position_usdt / account_balance) * 100,
                'leverage_ratio': recommended_leverage,
                'risk_reward_setup': 'Conservative'
            },
            'warnings': _generate_position_warnings(
                final_position_usdt, account_balance, recommended_leverage, price_risk
            )
        }
        
    except Exception as e:
        logger.error(f"仓位计算失败: {e}")
        raise HTTPException(status_code=400, detail="计算参数错误")


async def _build_position_params(recommendation, risk_tolerance: str) -> Dict[str, Any]:
    """构建仓位参数"""
    # 根据风险承受度调整
    risk_multipliers = {
        'low': 0.5,
        'medium': 1.0,
        'high': 1.5
    }
    
    multiplier = risk_multipliers.get(risk_tolerance, 1.0)
    
    return {
        'recommended_size_usdt': recommendation.position_size_usdt * multiplier,
        'recommended_size_percent': recommendation.position_size_percent * multiplier,
        'leverage': min(recommendation.leverage, 3.0 if risk_tolerance == 'low' else 5.0),
        'max_position_usdt': recommendation.account_info.get('total_equity', 0) * 0.25,
        'position_sizing_method': 'Kelly Criterion + Risk Parity',
        'rebalance_threshold': 0.1  # 10%偏差时重新平衡
    }


async def _build_price_levels(recommendation, symbol: str) -> Dict[str, float]:
    """构建价格点位"""
    current_price = recommendation.current_price
    
    # 多层次止盈
    take_profit_levels = []
    base_tp = recommendation.take_profit_price
    
    if recommendation.action.value in ['buy', 'strong_buy']:
        take_profit_levels = [
            current_price * 1.02,  # 2% 快速止盈
            current_price * 1.05,  # 5% 主要止盈
            base_tp,               # 目标止盈
            base_tp * 1.2          # 延伸止盈
        ]
    else:
        take_profit_levels = [
            current_price * 0.98,  # 2% 快速止盈
            current_price * 0.95,  # 5% 主要止盈
            base_tp,               # 目标止盈
            base_tp * 0.8          # 延伸止盈
        ]
    
    return {
        'current_price': current_price,
        'entry_price': recommendation.entry_price,
        'stop_loss': recommendation.stop_loss_price,
        'take_profit_1': take_profit_levels[0],
        'take_profit_2': take_profit_levels[1],
        'take_profit_3': take_profit_levels[2],
        'take_profit_4': take_profit_levels[3],
        'key_support': min(recommendation.key_levels.get('support', [current_price])),
        'key_resistance': max(recommendation.key_levels.get('resistance', [current_price]))
    }


async def _build_risk_management(recommendation, risk_tolerance: str) -> Dict[str, Any]:
    """构建风险管理策略"""
    return {
        'max_loss_usdt': recommendation.max_loss_usdt,
        'risk_reward_ratio': recommendation.risk_reward_ratio,
        'position_risk_percent': recommendation.position_size_percent,
        'stop_loss_type': 'Trailing Stop' if recommendation.confidence > 80 else 'Fixed Stop',
        'position_scaling': {
            'initial_entry': 0.5,  # 50%初始入场
            'add_on_confirmation': 0.3,  # 30%确认后加仓
            'final_add': 0.2  # 20%最终加仓
        },
        'exit_strategy': {
            'partial_profit_1': 0.25,  # 25%仓位在TP1平仓
            'partial_profit_2': 0.35,  # 35%仓位在TP2平仓
            'trailing_remainder': 0.4   # 40%仓位跟踪止盈
        },
        'risk_tolerance_level': risk_tolerance
    }


async def _build_execution_plan(recommendation, ml_analysis) -> Dict[str, Any]:
    """构建执行计划"""
    urgency = "high" if recommendation.confidence > 85 else "medium"
    
    plan = {
        'execution_urgency': urgency,
        'recommended_timing': recommendation.entry_timing,
        'order_type': 'Market' if urgency == 'high' else 'Limit',
        'entry_strategy': 'Single Entry' if recommendation.confidence > 80 else 'Scaled Entry',
        'monitoring_frequency': 'Every 15min' if urgency == 'high' else 'Every 1hour'
    }
    
    # ML增强的执行建议
    if ml_analysis and ml_analysis.get('confidence', 0) > 0.8:
        plan['ml_confirmation'] = True
        plan['confidence_boost'] = 'ML model confirms signal with high confidence'
    
    return plan


async def _build_market_context(symbol: str, recommendation) -> Dict[str, Any]:
    """构建市场环境分析"""
    try:
        async with OKXService() as okx:
            funding_rate = await okx.get_funding_rate(symbol)
            open_interest = await okx.get_open_interest(symbol)
            
        return {
            'funding_rate': funding_rate.get('funding_rate', 0) if funding_rate else 0,
            'open_interest': open_interest.get('open_interest', 0) if open_interest else 0,
            'market_sentiment': _analyze_market_sentiment(funding_rate, recommendation),
            'volatility_regime': 'High' if recommendation.confidence < 70 else 'Normal',
            'trend_strength': 'Strong' if recommendation.confidence > 85 else 'Moderate'
        }
    except Exception:
        return {'error': 'Unable to fetch market context'}


def _analyze_market_sentiment(funding_rate, recommendation) -> str:
    """分析市场情绪"""
    if not funding_rate:
        return 'Neutral'
    
    rate = funding_rate.get('funding_rate', 0)
    
    if rate > 0.01:
        return 'Extremely Bullish (Overheated)'
    elif rate > 0.005:
        return 'Bullish'
    elif rate < -0.005:
        return 'Bearish (Oversold)'
    else:
        return 'Neutral'


def _generate_risk_warnings(recommendation, ml_analysis, anomalies) -> List[str]:
    """生成风险提示"""
    warnings = []
    
    # 基于置信度的警告
    if recommendation.confidence < 70:
        warnings.append("⚠️ 信号置信度较低，建议减小仓位或等待更好机会")
    
    # 基于风险等级的警告
    if recommendation.risk_level.value in ['high', 'very_high']:
        warnings.append("🚨 高风险交易，请严格控制仓位和止损")
    
    # 基于杠杆的警告
    if recommendation.leverage > 3:
        warnings.append("⚡ 杠杆较高，市场波动可能导致快速亏损")
    
    # ML分析警告
    if ml_analysis and ml_analysis.get('confidence', 1) < 0.6:
        warnings.append("🤖 ML模型信号较弱，建议结合其他分析")
    
    # 异常情况警告
    if len(anomalies) > 2:
        warnings.append("📊 检测到多项市场异常，请谨慎交易")
    
    # 通用风险提示
    warnings.extend([
        "💡 请根据个人风险承受能力调整仓位",
        "📈 市场有风险，投资需谨慎",
        "⏰ 建议设置止损并严格执行"
    ])
    
    return warnings


def _evaluate_advice_level(recommendation, ml_analysis, anomalies) -> TradingAdviceLevel:
    """评估建议等级"""
    score = 0
    
    # 置信度评分
    if recommendation.confidence > 85:
        score += 40
    elif recommendation.confidence > 75:
        score += 30
    elif recommendation.confidence > 65:
        score += 20
    
    # 风险收益比评分
    if recommendation.risk_reward_ratio > 3:
        score += 25
    elif recommendation.risk_reward_ratio > 2:
        score += 15
    
    # ML确认评分
    if ml_analysis and ml_analysis.get('confidence', 0) > 0.8:
        score += 20
    
    # 风险等级评分
    if recommendation.risk_level.value in ['low', 'very_low']:
        score += 15
    
    if score >= 85:
        return TradingAdviceLevel.PREMIUM
    elif score >= 70:
        return TradingAdviceLevel.HIGH
    elif score >= 50:
        return TradingAdviceLevel.MEDIUM
    else:
        return TradingAdviceLevel.LOW


async def _build_market_overview() -> Dict[str, Any]:
    """构建市场概况"""
    try:
        # 这里可以添加更多市场分析
        return {
            'market_phase': 'Analysis Phase',
            'dominant_trend': 'Mixed Signals',
            'volatility_level': 'Medium',
            'recommended_strategy': 'Selective Trading',
            'risk_environment': 'Moderate'
        }
    except Exception:
        return {'status': 'Unable to analyze market overview'}


def _generate_position_warnings(position_usdt: float, account_balance: float, 
                              leverage: float, price_risk: float) -> List[str]:
    """生成仓位警告"""
    warnings = []
    
    position_percent = (position_usdt / account_balance) * 100
    
    if position_percent > 25:
        warnings.append("⚠️ 仓位超过账户25%，风险较高")
    
    if leverage > 3:
        warnings.append("⚡ 杠杆超过3倍，请注意强平风险")
    
    if price_risk > 0.05:
        warnings.append("📉 止损距离较大，请确认风险承受能力")
    
    return warnings