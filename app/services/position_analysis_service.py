# -*- coding: utf-8 -*-
"""
持仓分析服务
Position Analysis Service - 分析当前账户持仓并提供合理化建议
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import asyncio
import numpy as np

from app.core.logging import get_logger, trading_logger
from app.core.config import get_settings
from app.services.okx_service import OKXService
from app.services.trading_decision_service import TradingDecisionService, RiskLevel
from app.services.core_notification_service import get_core_notification_service
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class PositionRecommendation(Enum):
    """持仓建议枚举"""
    HOLD = "持有"                    # 继续持有
    REDUCE = "减仓"                  # 减仓
    INCREASE = "加仓"                # 加仓
    CLOSE = "平仓"                   # 平仓
    HEDGE = "对冲"                   # 对冲
    REBALANCE = "重新平衡"           # 重新平衡


class PositionRisk(Enum):
    """持仓风险等级"""
    LOW = "低风险"                    # 低风险
    MEDIUM = "中等风险"               # 中等风险
    HIGH = "高风险"                   # 高风险
    CRITICAL = "极高风险"             # 危险


class PositionAnalysisService:
    """持仓分析服务类"""
    
    def __init__(self):
        self.exchange_service = OKXService()
        self.trading_service = TradingDecisionService()
        self.notification_service = None  # Will be initialized async
        
        # 风险阈值配置
        self.risk_thresholds = {
            'max_single_position_percent': 30.0,    # 单个持仓最大占比
            'max_total_leverage': 10.0,             # 最大总杠杆
            'max_unrealized_loss_percent': -15.0,   # 最大未实现亏损比例
            'concentration_risk_threshold': 50.0,    # 集中度风险阈值
            'correlation_risk_threshold': 0.7,       # 相关性风险阈值
        }
        
        # 主要币种配置
        self.major_coins = {
            'BTC': {
                'usdt_swap': 'BTC-USDT-SWAP',
                'usd_swap': 'BTC-USD-SWAP',
                'spot': 'BTC-USDT'
            },
            'ETH': {
                'usdt_swap': 'ETH-USDT-SWAP', 
                'usd_swap': 'ETH-USD-SWAP',
                'spot': 'ETH-USDT'
            },
            'SOL': {
                'usdt_swap': 'SOL-USDT-SWAP',
                'usd_swap': 'SOL-USD-SWAP', 
                'spot': 'SOL-USDT'
            },
            'XRP': {
                'usdt_swap': 'XRP-USDT-SWAP',
                'usd_swap': 'XRP-USD-SWAP',
                'spot': 'XRP-USDT'
            },
            'OKB': {
                'spot': 'OKB-USDT'
            }
        }
    
    async def _ensure_notification_service(self):
        """确保通知服务已初始化"""
        if self.notification_service is None:
            self.notification_service = await get_core_notification_service()
    
    async def analyze_account_positions(self) -> Dict[str, Any]:
        """
        分析账户持仓并生成建议
        
        Returns:
            持仓分析结果和建议
        """
        try:
            logger.info("🔍 开始分析账户持仓...")
            
            async with self.exchange_service as exchange:
                # 获取账户信息
                account_balance = await exchange.get_account_balance()
                positions = await exchange.get_positions()
                spot_balances = await exchange.get_spot_balances()
            
            if not account_balance:
                return {
                    "status": "error",
                    "message": "无法获取账户信息",
                    "timestamp": datetime.now()
                }
            
            # 分析结果结构
            analysis_result = {
                "timestamp": datetime.now(),
                "account_summary": await self._analyze_account_summary(account_balance, positions, spot_balances),
                "position_analysis": await self._analyze_individual_positions(positions, account_balance),
                "risk_assessment": await self._assess_portfolio_risk(account_balance, positions),
                "recommendations": [],
                "alerts": [],
                "overall_score": 0
            }
            
            # 生成具体建议
            analysis_result["recommendations"] = await self._generate_position_recommendations(
                account_balance, positions, analysis_result["risk_assessment"]
            )
            
            # 生成风险警报
            analysis_result["alerts"] = await self._generate_risk_alerts(
                analysis_result["risk_assessment"], positions
            )
            
            # 计算整体评分
            analysis_result["overall_score"] = self._calculate_overall_score(analysis_result)
            
            logger.info(f"✅ 持仓分析完成，整体评分: {analysis_result['overall_score']}/100")
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"❌ 持仓分析失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now()
            }
    
    async def _analyze_account_summary(self, account_balance: Dict, positions: List[Dict], 
                                     spot_balances: List[Dict]) -> Dict[str, Any]:
        """分析账户摘要"""
        total_equity = account_balance.get('total_equity', 0)
        
        # 计算持仓统计
        total_positions = len(positions)
        total_unrealized_pnl = sum(pos.get('unrealized_pnl_usd', 0) for pos in positions)
        total_position_value = sum(pos.get('position_value_usd', 0) for pos in positions)
        
        # 计算现货余额
        total_spot_value = sum(balance.get('equity', 0) for balance in spot_balances 
                              if balance.get('currency') == 'USDT')
        
        # 计算利用率
        utilization_rate = (total_position_value / total_equity * 100) if total_equity > 0 else 0
        
        # 计算盈亏比例
        pnl_percentage = (total_unrealized_pnl / total_equity * 100) if total_equity > 0 else 0
        
        return {
            "total_equity": total_equity,
            "total_positions": total_positions,
            "total_unrealized_pnl": total_unrealized_pnl,
            "total_position_value": total_position_value,
            "total_spot_value": total_spot_value,
            "utilization_rate": utilization_rate,
            "pnl_percentage": pnl_percentage,
            "available_balance": total_equity - total_position_value,
            "leverage_ratio": total_position_value / total_equity if total_equity > 0 else 0
        }
    
    async def _analyze_individual_positions(self, positions: List[Dict], account_balance: Dict) -> List[Dict[str, Any]]:
        """分析单个持仓"""
        position_analyses = []
        
        for position in positions:
            try:
                symbol = position.get('symbol', '')
                size = position.get('size_abs', 0)
                unrealized_pnl = position.get('unrealized_pnl_usd', 0)
                position_value = position.get('position_value_usd', 0)
                
                # 获取当前市场信号
                try:
                    async with self.exchange_service as exchange:
                        market_signals = await self.trading_service._get_market_signals(symbol, exchange)
                except Exception as e:
                    logger.warning(f"获取 {symbol} 市场信号失败: {e}")
                    market_signals = {}
                
                # 计算全仓风险指标
                cross_margin_risk = self._calculate_cross_margin_risk(position, account_balance)
                
                # 分析持仓健康度
                position_health = self._assess_position_health(position, market_signals)
                
                # 生成持仓建议
                recommendation = self._generate_position_recommendation(position, market_signals, position_health, account_balance)
                
                analysis = {
                    "symbol": symbol,
                    "side": position.get('side', ''),
                    "size": size,
                    "position_value_usd": position_value,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_ratio": position.get('unrealized_pnl_ratio', 0),
                    "actual_loss_ratio": cross_margin_risk["actual_loss_ratio"],
                    "position_weight": cross_margin_risk["position_weight"],
                    "risk_exposure": cross_margin_risk["risk_exposure"],
                    "leverage": position.get('leverage', 1),
                    "avg_price": position.get('avg_price', 0),
                    "mark_price": position.get('mark_price', 0),
                    "health_score": position_health["score"],
                    "risk_level": position_health["risk_level"],
                    "market_trend": market_signals.get('trend', 'neutral'),
                    "recommendation": recommendation["action"],
                    "recommendation_reason": recommendation["reason"],
                    "suggested_action": recommendation["details"],
                    "cross_margin_risk": cross_margin_risk
                }
                
                position_analyses.append(analysis)
                
            except Exception as e:
                logger.warning(f"分析持仓失败: {position}, 错误: {e}")
                continue
        
        return position_analyses
    
    def _calculate_cross_margin_risk(self, position: Dict, account_balance: Dict) -> Dict[str, Any]:
        """计算全仓模式下的风险指标"""
        total_equity = account_balance.get('total_equity', 0)
        unrealized_pnl_usd = position.get('unrealized_pnl_usd', 0)
        position_value = position.get('position_value_usd', 0)
        leverage = position.get('leverage', 1)
        
        # 实际亏损占总权益比例
        actual_loss_ratio = (unrealized_pnl_usd / total_equity) if total_equity > 0 else 0
        
        # 持仓权重
        position_weight = (position_value / total_equity * 100) if total_equity > 0 else 0
        
        # 风险敞口 = 持仓价值 * 杠杆 / 总权益
        risk_exposure = (position_value * leverage / total_equity) if total_equity > 0 else 0
        
        # 最大可承受亏损（假设强平线为总权益的80%）
        max_tolerable_loss = total_equity * 0.2
        current_loss = abs(unrealized_pnl_usd) if unrealized_pnl_usd < 0 else 0
        loss_buffer = max_tolerable_loss - current_loss
        
        return {
            "actual_loss_ratio": actual_loss_ratio,
            "position_weight": position_weight,
            "risk_exposure": risk_exposure,
            "loss_buffer": loss_buffer,
            "max_tolerable_loss": max_tolerable_loss,
            "risk_utilization": (current_loss / max_tolerable_loss) if max_tolerable_loss > 0 else 0
        }

    def _assess_position_health(self, position: Dict, market_signals: Dict) -> Dict[str, Any]:
        """评估持仓健康度 - 针对数字货币优化"""
        score = 100
        risk_factors = []
        
        # 获取关键数据
        unrealized_pnl_usd = position.get('unrealized_pnl_usd', 0)
        position_value_usd = position.get('position_value_usd', 0)
        avg_price = position.get('avg_price', 0)
        mark_price = position.get('mark_price', 0)
        
        # 计算实际盈亏比例（基于持仓价值）
        if position_value_usd > 0:
            actual_pnl_ratio = unrealized_pnl_usd / position_value_usd
        else:
            actual_pnl_ratio = 0
        
        # 计算价格偏离度
        if avg_price > 0 and mark_price > 0:
            price_deviation = (mark_price - avg_price) / avg_price
            side = position.get('side', '')
            if side == 'short':
                price_deviation = -price_deviation  # 做空时反向计算
        else:
            price_deviation = actual_pnl_ratio
        
        # 1. 盈亏情况评估 (40分) - 加重权重，更严格
        if actual_pnl_ratio < -0.10:  # 亏损超过10%
            score -= 40
            risk_factors.append(f"严重亏损 {abs(actual_pnl_ratio)*100:.1f}%")
        elif actual_pnl_ratio < -0.05:  # 亏损超过5%
            score -= 25
            risk_factors.append(f"较大亏损 {abs(actual_pnl_ratio)*100:.1f}%")
        elif actual_pnl_ratio < -0.02:  # 亏损超过2%
            score -= 15
            risk_factors.append(f"轻微亏损 {abs(actual_pnl_ratio)*100:.1f}%")
        elif actual_pnl_ratio > 0.10:  # 盈利超过10%
            score += 5  # 适度奖励分
        
        # 2. 杠杆风险评估 (25分) - 更严格的杠杆控制
        leverage = position.get('leverage', 1)
        if leverage > 15:
            score -= 25
            risk_factors.append(f"极高杠杆 {leverage:.1f}x")
        elif leverage > 8:
            score -= 18
            risk_factors.append(f"高杠杆 {leverage:.1f}x")
        elif leverage > 3:
            score -= 10
            risk_factors.append(f"中等杠杆 {leverage:.1f}x")
        
        # 3. 市场趋势一致性 (20分)
        side = position.get('side', '')
        market_trend = market_signals.get('trend', 'neutral')
        
        if (side == 'long' and market_trend == 'bearish') or (side == 'short' and market_trend == 'bullish'):
            score -= 20
            risk_factors.append("逆势持仓")
        elif market_trend == 'neutral':
            score -= 8
            risk_factors.append("趋势不明")
        
        # 4. 波动率风险 (15分)
        volatility = market_signals.get('volatility', 'medium')
        if volatility == 'high':
            score -= 15
            risk_factors.append("高波动率")
        elif volatility == 'medium':
            score -= 5
        
        # 5. 持仓规模风险 - 新增评估维度
        if position_value_usd > 50000:  # 超过5万美元
            score -= 10
            risk_factors.append("大额持仓")
        elif position_value_usd > 20000:  # 超过2万美元
            score -= 5
            risk_factors.append("中等规模持仓")
        
        # 6. 价格偏离风险 - 新增评估维度
        if abs(price_deviation) > 0.15:  # 价格偏离超过15%
            score -= 15
            risk_factors.append(f"价格大幅偏离 {abs(price_deviation)*100:.1f}%")
        elif abs(price_deviation) > 0.08:  # 价格偏离超过8%
            score -= 8
            risk_factors.append(f"价格明显偏离 {abs(price_deviation)*100:.1f}%")
        
        # 确定风险等级 - 更严格的标准
        if score >= 85:
            risk_level = PositionRisk.LOW
        elif score >= 70:
            risk_level = PositionRisk.MEDIUM
        elif score >= 50:
            risk_level = PositionRisk.HIGH
        else:
            risk_level = PositionRisk.CRITICAL
        
        return {
            "score": max(0, min(100, score)),
            "risk_level": risk_level,
            "risk_factors": risk_factors,
            "actual_pnl_ratio": actual_pnl_ratio,
            "price_deviation": price_deviation,
            "position_value_usd": position_value_usd
        }
    
    def _generate_position_recommendation(self, position: Dict, market_signals: Dict, 
                                        health: Dict, account_balance: Dict = None) -> Dict[str, Any]:
        """生成单个持仓建议"""
        symbol = position.get('symbol', '')
        pnl_ratio = position.get('unrealized_pnl_ratio', 0)  # 单仓位盈亏比例
        unrealized_pnl_usd = position.get('unrealized_pnl_usd', 0)  # 实际盈亏金额
        leverage = position.get('leverage', 1)
        side = position.get('side', '')
        market_trend = market_signals.get('trend', 'neutral')
        health_score = health["score"]
        position_value = position.get('position_value_usd', 0)
        
        # 计算全仓模式下的实际亏损比例
        total_equity = account_balance.get('total_equity', 0) if account_balance else 0
        actual_loss_ratio = (unrealized_pnl_usd / total_equity) if total_equity > 0 else 0
        
        # 计算持仓占总权益的比例
        position_weight = (position_value / total_equity * 100) if total_equity > 0 else 0
        
        # 决策逻辑 - 优先考虑实际亏损比例
        if health_score < 30 or actual_loss_ratio < -0.08:  # 实际亏损超过总权益8%
            # 危险持仓，建议平仓
            return {
                "action": PositionRecommendation.CLOSE,
                "reason": f"实际亏损${abs(unrealized_pnl_usd):,.0f}({abs(actual_loss_ratio)*100:.1f}%总权益)，风险过大",
                "details": {
                    "urgency": "紧急",
                    "suggested_percentage": 100,
                    "time_frame": "立即执行",
                    "specific_action": f"市价平仓 {symbol} 全部持仓",
                    "risk_analysis": f"该持仓已造成总权益{abs(actual_loss_ratio)*100:.1f}%的实际亏损"
                }
            }
        
        elif actual_loss_ratio < -0.05 or pnl_ratio < -0.12:  # 实际亏损超过5%或单仓亏损12%
            # 严重亏损，建议减仓
            reduce_percentage = min(80, max(50, abs(actual_loss_ratio) * 1000))  # 根据亏损程度调整减仓比例
            return {
                "action": PositionRecommendation.REDUCE,
                "reason": f"实际亏损${abs(unrealized_pnl_usd):,.0f}({abs(actual_loss_ratio)*100:.1f}%总权益)，建议止损",
                "details": {
                    "urgency": "高",
                    "suggested_percentage": int(reduce_percentage),
                    "time_frame": "24小时内",
                    "specific_action": f"减仓{symbol} {int(reduce_percentage)}%，设置止损位于{position.get('mark_price', 0) * (0.95 if side == 'long' else 1.05):.4f}",
                    "risk_analysis": f"当前亏损已占总权益{abs(actual_loss_ratio)*100:.1f}%，持仓权重{position_weight:.1f}%"
                }
            }
        
        elif leverage > 15 and position_weight > 20:  # 高杠杆且持仓占比大
            # 杠杆过高，建议降杠杆
            return {
                "action": PositionRecommendation.REDUCE,
                "reason": f"杠杆{leverage:.1f}x过高，持仓占比{position_weight:.1f}%，建议降低风险",
                "details": {
                    "urgency": "中",
                    "suggested_percentage": 40,
                    "time_frame": "48小时内",
                    "specific_action": f"减仓{symbol} 40%或增加保证金降低杠杆至10x以下",
                    "risk_analysis": f"高杠杆持仓在市场波动中风险极大，建议控制在合理范围"
                }
            }
        
        elif (side == 'long' and market_trend == 'bearish') or (side == 'short' and market_trend == 'bullish'):
            # 逆势持仓
            return {
                "action": PositionRecommendation.HEDGE,
                "reason": "持仓方向与市场趋势相反，建议对冲或减仓",
                "details": {
                    "urgency": "中",
                    "suggested_percentage": 30,
                    "time_frame": "关注趋势变化",
                    "specific_action": f"考虑开设反向对冲仓位或减仓{symbol} 30%",
                    "risk_analysis": f"逆势持仓风险较高，当前{'做多' if side == 'long' else '做空'}但趋势{'看跌' if market_trend == 'bearish' else '看涨'}"
                }
            }
        
        elif actual_loss_ratio > 0.10 and market_trend == 'neutral':  # 实际盈利超过10%但趋势转弱
            # 高盈利但趋势转弱，建议部分止盈
            return {
                "action": PositionRecommendation.REDUCE,
                "reason": f"盈利${unrealized_pnl_usd:,.0f}({actual_loss_ratio*100:.1f}%总权益)，趋势转弱，建议止盈",
                "details": {
                    "urgency": "低",
                    "suggested_percentage": 30,
                    "time_frame": "适时止盈",
                    "specific_action": f"分批止盈{symbol} 30%，保留核心仓位，设置移动止盈",
                    "risk_analysis": f"已获得可观盈利，适当锁定利润降低回撤风险"
                }
            }
        
        elif health_score > 70 and ((side == 'long' and market_trend == 'bullish') or 
                                   (side == 'short' and market_trend == 'bearish')) and position_weight < 25:
            # 健康持仓且顺势，持仓占比不高，可考虑加仓
            return {
                "action": PositionRecommendation.INCREASE,
                "reason": "持仓健康且顺应趋势，可适当加仓",
                "details": {
                    "urgency": "低",
                    "suggested_percentage": 20,
                    "time_frame": "等待回调机会",
                    "specific_action": f"等待{symbol}回调至支撑位后加仓20%，控制总仓位不超过30%",
                    "risk_analysis": f"当前持仓健康，趋势向好，但需控制仓位规模"
                }
            }
        
        else:
            # 正常持仓，继续持有
            return {
                "action": PositionRecommendation.HOLD,
                "reason": "持仓状态良好，继续持有",
                "details": {
                    "urgency": "无",
                    "suggested_percentage": 0,
                    "time_frame": "持续监控",
                    "specific_action": f"继续持有{symbol}，关注市场变化和风险指标",
                    "risk_analysis": f"当前持仓风险可控，盈亏状况正常"
                }
            }
    
    async def _assess_portfolio_risk(self, account_balance: Dict, positions: List[Dict]) -> Dict[str, Any]:
        """评估投资组合风险"""
        total_equity = account_balance.get('total_equity', 0)
        
        if not positions or total_equity <= 0:
            return {
                "overall_risk": PositionRisk.LOW,
                "risk_score": 0,
                "risk_factors": [],
                "concentration_risk": 0,
                "leverage_risk": 0,
                "correlation_risk": 0
            }
        
        risk_factors = []
        risk_score = 0
        
        # 1. 集中度风险
        position_values = [pos.get('position_value_usd', 0) for pos in positions]
        max_position_value = max(position_values) if position_values else 0
        concentration_ratio = (max_position_value / total_equity * 100) if total_equity > 0 else 0
        
        if concentration_ratio > self.risk_thresholds['max_single_position_percent']:
            risk_score += 30
            risk_factors.append(f"单一持仓占比过高: {concentration_ratio:.1f}%")
        
        # 2. 杠杆风险
        total_position_value = sum(position_values)
        overall_leverage = total_position_value / total_equity if total_equity > 0 else 0
        
        if overall_leverage > self.risk_thresholds['max_total_leverage']:
            risk_score += 25
            risk_factors.append(f"总杠杆过高: {overall_leverage:.1f}x")
        elif overall_leverage > 5:
            risk_score += 15
            risk_factors.append(f"杠杆较高: {overall_leverage:.1f}x")
        
        # 3. 未实现亏损风险
        total_unrealized_pnl = sum(pos.get('unrealized_pnl_usd', 0) for pos in positions)
        pnl_percentage = (total_unrealized_pnl / total_equity * 100) if total_equity > 0 else 0
        
        if pnl_percentage < self.risk_thresholds['max_unrealized_loss_percent']:
            risk_score += 35
            risk_factors.append(f"未实现亏损过大: {pnl_percentage:.1f}%")
        elif pnl_percentage < -8:
            risk_score += 20
            risk_factors.append(f"未实现亏损较大: {pnl_percentage:.1f}%")
        
        # 4. 方向性风险（同向持仓过多）
        long_positions = [pos for pos in positions if pos.get('side') == 'long']
        short_positions = [pos for pos in positions if pos.get('side') == 'short']
        
        long_value = sum(pos.get('position_value_usd', 0) for pos in long_positions)
        short_value = sum(pos.get('position_value_usd', 0) for pos in short_positions)
        
        if total_position_value > 0:
            directional_bias = abs(long_value - short_value) / total_position_value
            if directional_bias > 0.8:
                risk_score += 15
                risk_factors.append("持仓方向过于集中")
        
        # 确定整体风险等级
        if risk_score >= 70:
            overall_risk = PositionRisk.CRITICAL
        elif risk_score >= 50:
            overall_risk = PositionRisk.HIGH
        elif risk_score >= 30:
            overall_risk = PositionRisk.MEDIUM
        else:
            overall_risk = PositionRisk.LOW
        
        return {
            "overall_risk": overall_risk,
            "risk_score": risk_score,
            "risk_factors": risk_factors,
            "concentration_risk": concentration_ratio,
            "leverage_risk": overall_leverage,
            "correlation_risk": directional_bias if 'directional_bias' in locals() else 0,
            "pnl_percentage": pnl_percentage,
            "total_positions": len(positions),
            "long_positions": len(long_positions),
            "short_positions": len(short_positions)
        }
    
    async def _generate_position_recommendations(self, account_balance: Dict, positions: List[Dict], 
                                               risk_assessment: Dict) -> List[Dict[str, Any]]:
        """生成投资组合级别的建议"""
        recommendations = []
        
        risk_score = risk_assessment.get('risk_score', 0)
        risk_factors = risk_assessment.get('risk_factors', [])
        
        # 1. 高风险建议
        if risk_score >= 70:
            recommendations.append({
                "type": "urgent",
                "title": "紧急风险控制",
                "description": "投资组合风险过高，建议立即采取风险控制措施",
                "actions": [
                    "减少高杠杆持仓",
                    "平仓亏损严重的持仓",
                    "降低整体仓位"
                ],
                "priority": "high"
            })
        
        # 2. 集中度风险建议
        if risk_assessment.get('concentration_risk', 0) > 25:
            recommendations.append({
                "type": "diversification",
                "title": "分散投资建议",
                "description": f"单一持仓占比{risk_assessment['concentration_risk']:.1f}%过高",
                "actions": [
                    "减少最大持仓的仓位",
                    "增加其他品种的配置",
                    "考虑分批建仓"
                ],
                "priority": "medium"
            })
        
        # 3. 杠杆风险建议
        if risk_assessment.get('leverage_risk', 0) > 8:
            recommendations.append({
                "type": "leverage",
                "title": "杠杆控制建议",
                "description": f"总杠杆{risk_assessment['leverage_risk']:.1f}x过高",
                "actions": [
                    "降低高杠杆持仓",
                    "增加保证金",
                    "设置更严格的止损"
                ],
                "priority": "high"
            })
        
        # 4. 盈亏管理建议
        pnl_percentage = risk_assessment.get('pnl_percentage', 0)
        if pnl_percentage < -10:
            recommendations.append({
                "type": "loss_management",
                "title": "亏损管理建议",
                "description": f"未实现亏损{abs(pnl_percentage):.1f}%较大",
                "actions": [
                    "评估止损策略",
                    "考虑部分平仓",
                    "调整风险管理参数"
                ],
                "priority": "high"
            })
        elif pnl_percentage > 15:
            recommendations.append({
                "type": "profit_taking",
                "title": "止盈建议",
                "description": f"未实现盈利{pnl_percentage:.1f}%较高",
                "actions": [
                    "考虑部分止盈",
                    "调整止盈止损位",
                    "锁定部分利润"
                ],
                "priority": "medium"
            })
        
        # 5. 平衡性建议
        long_positions = risk_assessment.get('long_positions', 0)
        short_positions = risk_assessment.get('short_positions', 0)
        
        if long_positions > 0 and short_positions == 0:
            recommendations.append({
                "type": "balance",
                "title": "持仓平衡建议",
                "description": "持仓方向过于单一，缺乏对冲",
                "actions": [
                    "考虑适当的对冲持仓",
                    "关注市场风险事件",
                    "准备应急平仓计划"
                ],
                "priority": "low"
            })
        
        return recommendations
    
    async def _generate_risk_alerts(self, risk_assessment: Dict, positions: List[Dict]) -> List[Dict[str, Any]]:
        """生成风险警报"""
        alerts = []
        
        # 1. 严重亏损警报
        for position in positions:
            pnl_ratio = position.get('unrealized_pnl_ratio', 0)
            if pnl_ratio < -0.15:
                alerts.append({
                    "type": "severe_loss",
                    "level": "critical",
                    "symbol": position.get('symbol', ''),
                    "message": f"严重亏损 {abs(pnl_ratio)*100:.1f}%",
                    "suggestion": "建议立即止损"
                })
        
        # 2. 高杠杆警报
        for position in positions:
            leverage = position.get('leverage', 1)
            if leverage > 20:
                alerts.append({
                    "type": "high_leverage",
                    "level": "high",
                    "symbol": position.get('symbol', ''),
                    "message": f"极高杠杆 {leverage:.1f}x",
                    "suggestion": "建议降低杠杆"
                })
        
        # 3. 集中度风险警报
        concentration_risk = risk_assessment.get('concentration_risk', 0)
        if concentration_risk > 40:
            alerts.append({
                "type": "concentration",
                "level": "high",
                "symbol": "portfolio",
                "message": f"持仓集中度过高 {concentration_risk:.1f}%",
                "suggestion": "建议分散投资"
            })
        
        return alerts
    
    def _calculate_overall_score(self, analysis_result: Dict) -> int:
        """计算整体评分"""
        base_score = 100
        
        # 风险评估扣分
        risk_score = analysis_result["risk_assessment"].get("risk_score", 0)
        base_score -= risk_score
        
        # 警报扣分
        alerts = analysis_result.get("alerts", [])
        critical_alerts = len([a for a in alerts if a.get("level") == "critical"])
        high_alerts = len([a for a in alerts if a.get("level") == "high"])
        
        base_score -= critical_alerts * 15
        base_score -= high_alerts * 8
        
        # 持仓健康度加分
        position_analyses = analysis_result.get("position_analysis", [])
        if position_analyses:
            avg_health = sum(pos.get("health_score", 0) for pos in position_analyses) / len(position_analyses)
            if avg_health > 80:
                base_score += 10
            elif avg_health < 50:
                base_score -= 10
        
        return max(0, min(100, base_score))
    
    async def send_position_analysis_notification(self, analysis_result: Dict) -> bool:
        """发送持仓分析通知"""
        try:
            account_summary = analysis_result.get("account_summary", {})
            risk_assessment = analysis_result.get("risk_assessment", {})
            recommendations = analysis_result.get("recommendations", [])
            alerts = analysis_result.get("alerts", [])
            overall_score = analysis_result.get("overall_score", 0)
            
            # 构建通知消息
            title = f"💼 账户持仓分析报告 (评分: {overall_score}/100)"
            
            message_parts = [
                "📊 账户概况:",
                f"  • 总权益: ${account_summary.get('total_equity', 0):,.2f} USDT",
                f"  • 持仓数量: {account_summary.get('total_positions', 0)} 个",
                f"  • 未实现盈亏: ${account_summary.get('total_unrealized_pnl', 0):,.2f} ({account_summary.get('pnl_percentage', 0):.1f}%)",
                f"  • 资金利用率: {account_summary.get('utilization_rate', 0):.1f}%",
                f"  • 整体杠杆: {account_summary.get('leverage_ratio', 0):.1f}x",
                ""
            ]
            
            # 风险评估
            risk_level = risk_assessment.get('overall_risk', PositionRisk.LOW)
            risk_emoji = {
                PositionRisk.LOW: "🟢",
                PositionRisk.MEDIUM: "🟡", 
                PositionRisk.HIGH: "🟠",
                PositionRisk.CRITICAL: "🔴"
            }
            
            message_parts.extend([
                f"⚠️ 风险评估: {risk_emoji.get(risk_level, '🟡')} {risk_level.value}",
                f"  • 风险评分: {risk_assessment.get('risk_score', 0)}/100",
                f"  • 集中度风险: {risk_assessment.get('concentration_risk', 0):.1f}%",
                ""
            ])
            
            # 关键警报
            if alerts:
                message_parts.append("🚨 风险警报:")
                for alert in alerts[:3]:  # 最多显示3个警报
                    level_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(alert.get("level"), "ℹ️")
                    message_parts.append(f"  {level_emoji} {alert.get('symbol', '')}: {alert.get('message', '')}")
                message_parts.append("")
            
            # 主要建议
            if recommendations:
                message_parts.append("💡 主要建议:")
                for rec in recommendations[:3]:  # 最多显示3个建议
                    priority_emoji = {"high": "🔥", "medium": "⚡", "low": "💭"}.get(rec.get("priority"), "📝")
                    message_parts.append(f"  {priority_emoji} {rec.get('title', '')}")
                message_parts.append("")
            
            # 持仓详情（只显示有问题的）
            position_analyses = analysis_result.get("position_analysis", [])
            problem_positions = [pos for pos in position_analyses 
                               if pos.get("health_score", 100) < 70 or 
                                  pos.get("recommendation") != PositionRecommendation.HOLD.value]
            
            if problem_positions:
                message_parts.append("📋 需要关注的持仓:")
                for pos in problem_positions[:5]:  # 最多显示5个
                    rec_emoji = {
                        "平仓": "❌", "减仓": "📉", "加仓": "📈", 
                        "对冲": "🔄", "持有": "⏸️", "重新平衡": "⚖️"
                    }.get(pos.get("recommendation"), "📊")
                    
                    pnl = pos.get("unrealized_pnl", 0)
                    pnl_text = f"${pnl:,.0f}" if pnl != 0 else "±$0"
                    actual_loss_ratio = pos.get("actual_loss_ratio", 0)
                    position_weight = pos.get("position_weight", 0)
                    
                    # 获取持仓方向
                    side = pos.get("side", "")
                    side_text = "多头" if side == "long" else "空头" if side == "short" else side
                    
                    recommendation = pos.get('recommendation', '')
                    if hasattr(recommendation, 'value'):
                        recommendation = recommendation.value
                    
                    # 获取具体操作建议
                    suggested_action = pos.get('suggested_action', {})
                    specific_action = suggested_action.get('specific_action', '')
                    urgency = suggested_action.get('urgency', '')
                    
                    message_parts.append(
                        f"  {rec_emoji} {pos.get('symbol', '')} ({side_text}): {recommendation} "
                        f"(盈亏: {pnl_text}/{abs(actual_loss_ratio)*100:.1f}%权益, 仓位: {position_weight:.1f}%)"
                    )
                    
                    # 添加具体操作建议
                    if specific_action:
                        urgency_emoji = {"紧急": "🚨", "高": "⚠️", "中": "⚡", "低": "💭"}.get(urgency, "💡")
                        message_parts.append(f"    {urgency_emoji} {specific_action}")
                        
                    # 添加风险分析
                    risk_analysis = suggested_action.get('risk_analysis', '')
                    if risk_analysis:
                        message_parts.append(f"    📊 {risk_analysis}")
            
            message = "\n".join(message_parts)
            
            # 确定通知优先级
            if overall_score < 50 or risk_level == PositionRisk.CRITICAL:
                priority = "high"
            elif overall_score < 70 or risk_level == PositionRisk.HIGH:
                priority = "medium"
            else:
                priority = "normal"
            
            # 确保通知服务已初始化
            await self._ensure_notification_service()
            
            # 发送通知 (添加超时保护)
            try:
                success_results = await asyncio.wait_for(
                    self.notification_service.send_notification(
                        message=f"{title}\n\n{message}",
                        priority=priority
                    ),
                    timeout=30.0  # 30秒超时
                )
            except asyncio.TimeoutError:
                logger.warning("⏰ 持仓分析通知发送超时，跳过通知")
                return False
            
            success = any(success_results.values()) if success_results else False
            
            if success:
                trading_logger.info(f"📢 已发送持仓分析通知 (评分: {overall_score}/100)")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 发送持仓分析通知失败: {e}")
            return False
    
    async def analyze_grid_opportunities(self) -> Dict[str, Any]:
        """
        分析网格交易机会
        
        Returns:
            网格交易机会分析结果
        """
        try:
            logger.info("🎯 开始分析网格交易机会...")
            
            opportunities = []
            
            # 分析主要币种的网格机会
            for coin, symbols in self.major_coins.items():
                for contract_type, symbol in symbols.items():
                    try:
                        async with self.exchange_service as exchange:
                            # 获取7天历史数据
                            klines = await exchange.get_kline_data(symbol, '1H', 168)
                            current_price = await exchange.get_current_price(symbol)
                            
                            if not klines or len(klines) < 50 or not current_price:
                                continue
                            
                            prices = [k['close'] for k in klines]
                            
                            # 计算波动性指标
                            volatility = np.std(prices) / np.mean(prices)
                            price_range = (max(prices) - min(prices)) / np.mean(prices)
                            
                            # 计算24小时波动
                            if len(prices) >= 24:
                                daily_volatility = np.std(prices[-24:]) / np.mean(prices[-24:])
                            else:
                                daily_volatility = volatility
                            
                            # 网格策略评分
                            grid_score = self._calculate_grid_score(coin, volatility, price_range)
                            
                            # 计算网格参数
                            grid_num = min(30, max(10, int(price_range * 100)))
                            investment = 1000  # 默认投资1000U
                            
                            # 预期收益计算
                            trades_per_day = volatility * 24 / (price_range / grid_num) if price_range > 0 else 0
                            profit_per_trade = investment / grid_num * 0.002
                            daily_profit = trades_per_day * profit_per_trade
                            
                            opportunities.append({
                                'coin': coin,
                                'symbol': symbol,
                                'contract_type': contract_type,
                                'current_price': current_price,
                                'volatility': volatility,
                                'daily_volatility': daily_volatility,
                                'price_range': price_range,
                                'grid_score': grid_score,
                                'grid_num': grid_num,
                                'daily_profit': daily_profit,
                                'annual_return': daily_profit * 365 / investment * 100,
                                'recommendation': self._get_grid_recommendation(grid_score)
                            })
                            
                    except Exception as e:
                        logger.warning(f"分析{symbol}网格机会失败: {e}")
                        continue
            
            # 按网格评分排序
            opportunities.sort(key=lambda x: x['grid_score'], reverse=True)
            
            result = {
                'timestamp': datetime.now(),
                'total_analyzed': len(opportunities),
                'top_opportunities': opportunities[:5],  # 前5个机会
                'high_score_count': len([o for o in opportunities if o['grid_score'] >= 80]),
                'medium_score_count': len([o for o in opportunities if 60 <= o['grid_score'] < 80]),
                'avg_annual_return': np.mean([o['annual_return'] for o in opportunities]) if opportunities else 0
            }
            
            logger.info(f"✅ 网格机会分析完成，发现 {len(opportunities)} 个机会")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 网格机会分析失败: {e}")
            return {
                'timestamp': datetime.now(),
                'error': str(e),
                'total_analyzed': 0,
                'top_opportunities': []
            }
    
    def _calculate_grid_score(self, coin: str, volatility: float, price_range: float) -> int:
        """计算网格策略评分"""
        score = 0
        
        # 波动性评分 (权重60%)
        if volatility > 0.05:  # 高波动 (>5%)
            score += 60
        elif volatility > 0.03:  # 中等波动 (3-5%)
            score += 40
        elif volatility > 0.02:  # 低波动 (2-3%)
            score += 20
        
        # 价格区间评分 (权重30%)
        if price_range > 0.15:  # 大区间 (>15%)
            score += 30
        elif price_range > 0.10:  # 中等区间 (10-15%)
            score += 20
        elif price_range > 0.05:  # 小区间 (5-10%)
            score += 10
        
        # 流动性评分 (权重10%) - 主流币加分
        if coin in ['BTC', 'ETH']:
            score += 10
        elif coin in ['SOL', 'XRP']:
            score += 5
        
        return min(100, score)
    
    def _get_grid_recommendation(self, score: int) -> str:
        """根据评分获取网格推荐"""
        if score >= 80:
            return "强烈推荐"
        elif score >= 60:
            return "推荐"
        elif score >= 40:
            return "谨慎考虑"
        else:
            return "不推荐"
    
    async def analyze_market_opportunities(self) -> Dict[str, Any]:
        """
        分析市场交易机会
        
        Returns:
            市场机会分析结果
        """
        try:
            logger.info("💎 开始分析市场交易机会...")
            
            # 分析币本位合约机会
            coin_contracts = await self._analyze_coin_based_contracts()
            
            # 分析现货机会
            spot_opportunities = await self._analyze_spot_opportunities()
            
            result = {
                'timestamp': datetime.now(),
                'coin_contracts': coin_contracts,
                'spot_opportunities': spot_opportunities,
                'market_sentiment': self._assess_market_sentiment(coin_contracts, spot_opportunities)
            }
            
            logger.info("✅ 市场机会分析完成")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 市场机会分析失败: {e}")
            return {
                'timestamp': datetime.now(),
                'error': str(e),
                'coin_contracts': [],
                'spot_opportunities': []
            }
    
    async def _analyze_coin_based_contracts(self) -> List[Dict[str, Any]]:
        """分析币本位合约机会"""
        coin_contracts = []
        
        for coin in ['BTC', 'ETH', 'SOL', 'XRP']:
            if 'usd_swap' in self.major_coins[coin]:
                symbol = self.major_coins[coin]['usd_swap']
                
                try:
                    async with self.exchange_service as exchange:
                        current_price = await exchange.get_current_price(symbol)
                        funding_rate = await exchange.get_funding_rate(symbol)
                        klines = await exchange.get_kline_data(symbol, '4H', 72)  # 3天4小时K线
                        
                        if not klines or not current_price:
                            continue
                        
                        prices = [k['close'] for k in klines]
                        
                        # 趋势分析
                        ma_short = np.mean(prices[-6:])   # 短期均线
                        ma_long = np.mean(prices[-18:])   # 长期均线
                        
                        trend = "上涨" if ma_short > ma_long * 1.02 else "下跌" if ma_short < ma_long * 0.98 else "震荡"
                        
                        # 波动性分析
                        volatility = np.std(prices) / np.mean(prices)
                        
                        # 资金费率分析
                        funding_cost = 0
                        funding_signal = "中性"
                        if funding_rate:
                            rate = funding_rate.get('funding_rate', 0)
                            funding_cost = abs(rate) * 8 * 365  # 年化资金费率成本
                            
                            if rate > 0.01:
                                funding_signal = "看跌"  # 多头过热
                            elif rate < -0.005:
                                funding_signal = "看涨"  # 空头过热
                        
                        # 生成交易建议
                        suggestion = self._generate_contract_suggestion(trend, volatility, funding_signal)
                        
                        coin_contracts.append({
                            'coin': coin,
                            'symbol': symbol,
                            'current_price': current_price,
                            'trend': trend,
                            'volatility': volatility,
                            'funding_rate': rate if funding_rate else 0,
                            'funding_cost': funding_cost,
                            'funding_signal': funding_signal,
                            'suggestion': suggestion
                        })
                        
                except Exception as e:
                    logger.warning(f"分析{symbol}失败: {e}")
                    continue
        
        return coin_contracts
    
    def _generate_contract_suggestion(self, trend: str, volatility: float, funding_signal: str) -> str:
        """生成合约交易建议"""
        if trend == "上涨" and volatility > 0.03:
            return "适合做多，可考虑网格策略"
        elif trend == "下跌" and volatility > 0.03:
            return "适合做空，注意风险控制"
        elif volatility > 0.04:
            return "高波动，适合网格交易"
        else:
            return "波动较小，观望为主"
    
    async def _analyze_spot_opportunities(self) -> List[Dict[str, Any]]:
        """分析现货交易机会"""
        spot_opportunities = []
        spot_symbols = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'OKB-USDT']
        
        for symbol in spot_symbols:
            try:
                async with self.exchange_service as exchange:
                    current_price = await exchange.get_current_price(symbol)
                    klines = await exchange.get_kline_data(symbol, '1D', 30)  # 30天日K线
                    
                    if not klines or not current_price:
                        continue
                    
                    prices = [k['close'] for k in klines]
                    volumes = [k['volume'] for k in klines]
                    
                    # 技术分析
                    ma7 = np.mean(prices[-7:])
                    ma30 = np.mean(prices[-30:])
                    
                    # 价格位置分析
                    max_30d = max(prices)
                    min_30d = min(prices)
                    price_position = (current_price - min_30d) / (max_30d - min_30d)
                    
                    # 成交量分析
                    avg_volume = np.mean(volumes[-7:])
                    recent_volume = np.mean(volumes[-3:])
                    volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1
                    
                    coin = symbol.split('-')[0]
                    
                    # 生成现货建议
                    suggestion = self._generate_spot_suggestion(coin, price_position, ma7, ma30, volume_ratio)
                    
                    spot_opportunities.append({
                        'coin': coin,
                        'symbol': symbol,
                        'current_price': current_price,
                        'price_position': price_position,
                        'ma_ratio': ma7 / ma30,
                        'volume_ratio': volume_ratio,
                        'suggestion': suggestion
                    })
                    
            except Exception as e:
                logger.warning(f"分析{symbol}失败: {e}")
                continue
        
        return spot_opportunities
    
    def _generate_spot_suggestion(self, coin: str, price_position: float, ma7: float, ma30: float, volume_ratio: float) -> str:
        """生成现货交易建议"""
        if coin == 'OKB':
            if price_position < 0.3:
                return "价格较低，适合分批买入"
            elif price_position > 0.8:
                return "价格较高，谨慎追高"
            else:
                return "价格适中，可定投或网格"
        else:
            if price_position < 0.2 and ma7 > ma30:
                return "低位反弹，可考虑买入"
            elif price_position > 0.9:
                return "高位风险，建议减仓"
            elif 0.3 <= price_position <= 0.7:
                return "适合网格交易"
            else:
                return "观望为主"
    
    def _assess_market_sentiment(self, coin_contracts: List[Dict], spot_opportunities: List[Dict]) -> str:
        """评估市场情绪"""
        if not coin_contracts and not spot_opportunities:
            return "数据不足"
        
        # 统计上涨趋势的合约数量
        uptrend_count = len([c for c in coin_contracts if c.get('trend') == '上涨'])
        total_contracts = len(coin_contracts)
        
        # 统计价格位置较高的现货数量
        high_position_count = len([s for s in spot_opportunities if s.get('price_position', 0) > 0.7])
        total_spots = len(spot_opportunities)
        
        if total_contracts > 0:
            uptrend_ratio = uptrend_count / total_contracts
            if uptrend_ratio > 0.6:
                return "偏乐观"
            elif uptrend_ratio < 0.3:
                return "偏悲观"
        
        return "中性"
    
    async def send_market_analysis_notification(self, grid_analysis: Dict, market_analysis: Dict) -> bool:
        """发送市场分析通知"""
        try:
            title = f"📊 市场机会分析报告 ({datetime.now().strftime('%H:%M')})"
            
            message_parts = [
                "🎯 网格交易机会:",
                f"  • 分析品种: {grid_analysis.get('total_analyzed', 0)} 个",
                f"  • 高分机会: {grid_analysis.get('high_score_count', 0)} 个",
                f"  • 平均年化收益: {grid_analysis.get('avg_annual_return', 0):.1f}%",
                ""
            ]
            
            # 显示前3个网格机会
            top_opportunities = grid_analysis.get('top_opportunities', [])[:3]
            if top_opportunities:
                message_parts.append("🏆 推荐网格机会:")
                for opp in top_opportunities:
                    coin = opp.get('coin', '')
                    score = opp.get('grid_score', 0)
                    annual_return = opp.get('annual_return', 0)
                    recommendation = opp.get('recommendation', '')
                    
                    message_parts.append(f"  • {coin}: {recommendation} (评分: {score}/100, 预期年化: {annual_return:.1f}%)")
                message_parts.append("")
            
            # 市场情绪
            market_sentiment = market_analysis.get('market_sentiment', '中性')
            message_parts.extend([
                f"📈 市场情绪: {market_sentiment}",
                ""
            ])
            
            # 币本位合约机会
            coin_contracts = market_analysis.get('coin_contracts', [])
            if coin_contracts:
                message_parts.append("🪙 币本位合约:")
                for contract in coin_contracts[:3]:  # 显示前3个
                    coin = contract.get('coin', '')
                    trend = contract.get('trend', '')
                    suggestion = contract.get('suggestion', '')
                    message_parts.append(f"  • {coin}: {trend} - {suggestion}")
                message_parts.append("")
            
            # 现货机会
            spot_opportunities = market_analysis.get('spot_opportunities', [])
            if spot_opportunities:
                message_parts.append("💎 现货机会:")
                for spot in spot_opportunities[:3]:  # 显示前3个
                    coin = spot.get('coin', '')
                    suggestion = spot.get('suggestion', '')
                    message_parts.append(f"  • {coin}: {suggestion}")
            
            message = "\n".join(message_parts)
            
            # 确保通知服务已初始化
            await self._ensure_notification_service()
            
            # 发送通知 (添加超时保护)
            try:
                success_results = await asyncio.wait_for(
                    self.notification_service.send_notification(
                        message=f"{title}\n\n{message}",
                        priority="normal"
                    ),
                    timeout=30.0  # 30秒超时
                )
            except asyncio.TimeoutError:
                logger.warning("⏰ 市场分析通知发送超时，跳过通知")
                return False
            
            success = any(success_results.values()) if success_results else False
            
            if success:
                trading_logger.info("📢 已发送市场分析通知")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ 发送市场分析通知失败: {e}")
            return False