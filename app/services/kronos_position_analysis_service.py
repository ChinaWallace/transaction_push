# -*- coding: utf-8 -*-
"""
Kronos持仓分析服务
定时分析当前账户持仓，提供基于Kronos预测的详细建议和风险评估
"""

import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger, trading_logger
from app.services.kronos_integrated_decision_service import get_kronos_integrated_service, KronosEnhancedDecision
from app.services.core_notification_service import get_core_notification_service
from app.services.okx_service import OKXService


@dataclass
class PositionAnalysisResult:
    """持仓分析结果"""
    symbol: str
    current_position: Dict[str, Any]
    kronos_decision: Optional[KronosEnhancedDecision]
    risk_assessment: str
    recommendation: str
    urgency_level: str
    potential_pnl: float
    suggested_action: str
    
    # 新增涨跌预测字段
    price_prediction: Optional[Dict[str, Any]] = None  # 价格预测详情
    trend_prediction: Optional[str] = None  # 趋势预测
    confidence_level: Optional[float] = None  # 预测置信度


class KronosPositionAnalysisService:
    """Kronos持仓分析服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.notification_service = None  # Will be initialized async
        self.okx_service = OKXService()
        
        # 分析配置
        self.analysis_config = {
            'enable_notifications': True,
            'min_position_value': 100,  # 最小持仓价值(USDT)
            'high_risk_threshold': 0.15,  # 15%风险阈值
            'notification_cooldown_minutes': 30,  # 通知冷却时间改为30分钟
            'urgent_notification_cooldown_minutes': 10,  # 紧急情况冷却时间10分钟
            'high_risk_notification_cooldown_minutes': 15,  # 高风险情况冷却时间15分钟
        }
        
        # 通知历史
        self.last_notification_time = None
    
    def update_notification_config(self, **kwargs):
        """更新通知配置"""
        for key, value in kwargs.items():
            if key in self.analysis_config:
                old_value = self.analysis_config[key]
                self.analysis_config[key] = value
                self.logger.info(f"📝 更新配置 {key}: {old_value} -> {value}")
            else:
                self.logger.warning(f"⚠️ 未知配置项: {key}")
    
    def get_notification_config(self) -> Dict[str, Any]:
        """获取当前通知配置"""
        return self.analysis_config.copy()
    
    async def _ensure_notification_service(self):
        """确保通知服务已初始化"""
        if self.notification_service is None:
            self.notification_service = await get_core_notification_service()
        
    async def run_scheduled_analysis(self, force_notification: bool = False) -> Dict[str, Any]:
        """运行定时持仓分析"""
        try:
            self.logger.info(f"🤖 开始定时Kronos持仓分析... (实例ID: {id(self)}, 强制推送: {force_notification})")
            
            # 获取当前持仓
            positions = await self._get_current_positions()
            if not positions:
                self.logger.info("📊 当前无持仓，跳过分析")
                return {"status": "no_positions"}
            
            # 分析每个持仓
            analysis_results = []
            for position in positions:
                result = await self._analyze_position(position)
                if result:
                    analysis_results.append(result)
            
            # 生成综合报告
            report = await self._generate_comprehensive_report(analysis_results)
            
            # 检查通知冷却（基于分析结果动态调整）
            if not force_notification and not self._should_send_notification(analysis_results):
                cooldown_remaining = self._get_cooldown_remaining_minutes(analysis_results)
                self.logger.info(f"⏰ 通知冷却期内，跳过推送 (剩余冷却时间: {cooldown_remaining:.1f}分钟)")
                return {
                    "status": "analyzed_no_notification", 
                    "reason": "cooldown", 
                    "cooldown_remaining_minutes": cooldown_remaining,
                    "positions_analyzed": len(analysis_results),
                    "report": report,
                    "analysis_time": datetime.now().isoformat()
                }
            
            # 发送通知
            if self.analysis_config['enable_notifications'] and analysis_results:
                self.logger.info(f"📢 准备发送Kronos持仓分析通知，分析结果数量: {len(analysis_results)}")
                notification_success = await self._send_position_analysis_notification(report, analysis_results)
                if notification_success:
                    self.logger.info("✅ Kronos持仓分析通知发送成功")
                    self.last_notification_time = datetime.now()
                else:
                    self.logger.warning("⚠️ Kronos持仓分析通知发送失败")
            elif not self.analysis_config['enable_notifications']:
                self.logger.info("📴 Kronos持仓分析通知已禁用")
            elif not analysis_results:
                self.logger.info("📊 无持仓分析结果，跳过通知")
            
            self.logger.info(f"✅ Kronos持仓分析完成，分析了 {len(analysis_results)} 个持仓")
            
            return {
                "status": "success",
                "positions_analyzed": len(analysis_results),
                "report": report,
                "analysis_time": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ 定时Kronos持仓分析失败: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _get_current_positions(self) -> List[Dict[str, Any]]:
        """获取当前持仓"""
        try:
            self.logger.info("🔍 开始获取当前持仓信息...")
            
            # 获取持仓信息
            all_positions = await self.okx_service.get_positions()
            if not all_positions:
                self.logger.info("📊 当前无任何持仓")
                return []
            
            self.logger.info(f"📊 获取到 {len(all_positions)} 个持仓记录")
            
            # 过滤有效持仓
            valid_positions = []
            for position in all_positions:
                pos_size = float(position.get('size', 0))
                symbol = position.get('symbol', '')
                
                # 只分析有持仓的币种
                if pos_size != 0:
                    # 获取持仓价值（已经在OKX服务中计算好了）
                    position_value = position.get('position_value_usd', 0)
                    mark_price = position.get('mark_price', 0)
                    
                    self.logger.info(f"💰 {symbol}: 持仓 {pos_size}, 价格 {mark_price}, 价值 {position_value:.2f} USDT")
                    
                    # 只分析价值超过阈值的持仓
                    if position_value >= self.analysis_config['min_position_value']:
                        # 转换为兼容格式
                        compatible_position = {
                            'instId': symbol,
                            'pos': str(pos_size),
                            'markPx': str(mark_price),
                            'upl': str(position.get('unrealized_pnl_usd', 0)),
                            'position_value': position_value,
                            # 保留原始数据
                            'original_data': position
                        }
                        valid_positions.append(compatible_position)
                        self.logger.info(f"✅ {symbol} 符合分析条件，加入分析列表")
                    else:
                        self.logger.info(f"⚪ {symbol} 持仓价值 {position_value:.2f} USDT 低于阈值 {self.analysis_config['min_position_value']} USDT")
            
            self.logger.info(f"📈 最终有效持仓数量: {len(valid_positions)}")
            return valid_positions
            
        except Exception as e:
            self.logger.error(f"获取当前持仓失败: {e}")
            return []
    
    async def _analyze_position(self, position: Dict[str, Any]) -> Optional[PositionAnalysisResult]:
        """分析单个持仓"""
        try:
            symbol = position.get('instId', '')
            if not symbol:
                return None
            
            self.logger.info(f"🔍 分析持仓: {symbol}")
            
            # 获取Kronos增强决策
            kronos_service = await get_kronos_integrated_service()
            kronos_decision = await kronos_service.get_kronos_enhanced_decision(symbol, force_update=True)
            
            # 分析持仓风险
            risk_assessment = self._assess_position_risk(position, kronos_decision)
            
            # 生成建议
            recommendation = self._generate_position_recommendation(position, kronos_decision)
            
            # 评估紧急程度
            urgency_level = self._assess_urgency(position, kronos_decision, risk_assessment)
            
            # 计算潜在盈亏
            potential_pnl = self._calculate_potential_pnl(position, kronos_decision)
            
            # 建议操作
            suggested_action = self._suggest_action(position, kronos_decision, risk_assessment)
            
            # 生成涨跌预测
            price_prediction = self._generate_price_prediction(position, kronos_decision)
            trend_prediction = self._generate_trend_prediction(kronos_decision)
            confidence_level = kronos_decision.kronos_confidence if kronos_decision else 0.5
            
            return PositionAnalysisResult(
                symbol=symbol,
                current_position=position,
                kronos_decision=kronos_decision,
                risk_assessment=risk_assessment,
                recommendation=recommendation,
                urgency_level=urgency_level,
                potential_pnl=potential_pnl,
                suggested_action=suggested_action,
                price_prediction=price_prediction,
                trend_prediction=trend_prediction,
                confidence_level=confidence_level
            )
            
        except Exception as e:
            self.logger.error(f"分析持仓失败: {e}")
            return None
    
    def _assess_position_risk(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision]) -> str:
        """评估持仓风险"""
        try:
            # 基础风险评估
            unrealized_pnl = float(position.get('upl', 0))
            position_value = position.get('position_value', 0)
            
            # 计算风险比例
            if position_value > 0:
                risk_ratio = abs(unrealized_pnl) / position_value
            else:
                risk_ratio = 0
            
            # 结合Kronos预测评估风险
            if kronos_decision:
                kronos_confidence = kronos_decision.kronos_confidence
                predicted_change = kronos_decision.kronos_prediction.price_change_pct if kronos_decision.kronos_prediction else 0
                
                # 正确判断持仓方向
                pos_size = float(position.get('pos', 0))
                original_data = position.get('original_data', {})
                pos_side = original_data.get('side', '')
                
                if pos_side:
                    if pos_side == 'long':
                        is_long = True
                    elif pos_side == 'short':
                        is_long = False
                    elif pos_side == 'net':
                        is_long = pos_size > 0
                    else:
                        is_long = pos_size > 0  # 默认逻辑
                else:
                    is_long = pos_size > 0  # 兼容旧数据
                
                # 如果Kronos预测与持仓方向相反，增加风险
                if (is_long and predicted_change < -0.03) or (not is_long and predicted_change > 0.03):
                    if kronos_confidence > 0.7:
                        return "极高风险"
                    elif kronos_confidence > 0.6:
                        return "高风险"
            
            # 基于风险比例判断
            if risk_ratio > 0.2:
                return "极高风险"
            elif risk_ratio > 0.15:
                return "高风险"
            elif risk_ratio > 0.1:
                return "中等风险"
            elif risk_ratio > 0.05:
                return "低风险"
            else:
                return "极低风险"
                
        except Exception as e:
            self.logger.error(f"评估持仓风险失败: {e}")
            return "未知风险"
    
    def _generate_position_recommendation(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision]) -> str:
        """生成持仓建议"""
        try:
            symbol = position.get('instId', '').replace('-USDT-SWAP', '')
            pos_size = float(position.get('pos', 0))
            
            # 正确判断持仓方向
            original_data = position.get('original_data', {})
            pos_side = original_data.get('side', '')
            
            if pos_side:
                if pos_side == 'long':
                    is_long = True
                elif pos_side == 'short':
                    is_long = False
                elif pos_side == 'net':
                    is_long = pos_size > 0
                else:
                    is_long = pos_size > 0  # 默认逻辑
            else:
                is_long = pos_size > 0  # 兼容旧数据
            
            if not kronos_decision:
                return f"无Kronos预测数据，建议谨慎持有{symbol}仓位"
            
            kronos_confidence = kronos_decision.kronos_confidence
            predicted_change = kronos_decision.kronos_prediction.price_change_pct if kronos_decision.kronos_prediction else 0
            final_action = kronos_decision.final_action
            
            # 生成详细建议
            if is_long:  # 多头持仓
                if predicted_change > 0.03 and kronos_confidence > 0.7:
                    return f"Kronos强烈看涨{symbol}，建议继续持有或适度加仓"
                elif predicted_change < -0.03 and kronos_confidence > 0.7:
                    return f"Kronos强烈看跌{symbol}，建议立即减仓或止损"
                elif predicted_change < -0.02 and kronos_confidence > 0.6:
                    return f"Kronos看跌{symbol}，建议谨慎减仓"
                else:
                    return f"Kronos对{symbol}预测中性，建议保持当前仓位"
            else:  # 空头持仓
                if predicted_change < -0.03 and kronos_confidence > 0.7:
                    return f"Kronos强烈看跌{symbol}，建议继续持有或适度加仓"
                elif predicted_change > 0.03 and kronos_confidence > 0.7:
                    return f"Kronos强烈看涨{symbol}，建议立即减仓或止损"
                elif predicted_change > 0.02 and kronos_confidence > 0.6:
                    return f"Kronos看涨{symbol}，建议谨慎减仓"
                else:
                    return f"Kronos对{symbol}预测中性，建议保持当前仓位"
                    
        except Exception as e:
            self.logger.error(f"生成持仓建议失败: {e}")
            return "建议谨慎操作"
    
    def _assess_urgency(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision], risk_assessment: str) -> str:
        """评估操作紧急程度"""
        try:
            if risk_assessment in ["极高风险", "高风险"]:
                return "紧急"
            
            if kronos_decision and kronos_decision.kronos_confidence > 0.8:
                predicted_change = kronos_decision.kronos_prediction.price_change_pct if kronos_decision.kronos_prediction else 0
                if abs(predicted_change) > 0.05:  # 预测变化超过5%
                    return "高"
            
            if risk_assessment == "中等风险":
                return "中等"
            
            return "低"
            
        except Exception as e:
            return "未知"
    
    def _calculate_potential_pnl(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision]) -> float:
        """计算潜在盈亏"""
        try:
            if not kronos_decision or not kronos_decision.kronos_prediction:
                return 0.0
            
            pos_size = float(position.get('pos', 0))
            mark_price = float(position.get('markPx', 0))
            predicted_change = kronos_decision.kronos_prediction.price_change_pct
            
            # 计算预测价格
            predicted_price = mark_price * (1 + predicted_change)
            
            # 计算潜在盈亏
            if pos_size > 0:  # 多头
                potential_pnl = pos_size * (predicted_price - mark_price)
            else:  # 空头
                potential_pnl = abs(pos_size) * (mark_price - predicted_price)
            
            return potential_pnl
            
        except Exception as e:
            self.logger.error(f"计算潜在盈亏失败: {e}")
            return 0.0
    
    def _suggest_action(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision], risk_assessment: str) -> str:
        """建议具体操作"""
        try:
            if risk_assessment in ["极高风险", "高风险"]:
                return "立即减仓或止损"
            
            if not kronos_decision:
                return "保持观望"
            
            final_action = kronos_decision.final_action
            kronos_confidence = kronos_decision.kronos_confidence
            
            if "强烈" in final_action and kronos_confidence > 0.8:
                if "买入" in final_action:
                    return "考虑加仓"
                elif "卖出" in final_action:
                    return "考虑减仓"
            elif "买入" in final_action and kronos_confidence > 0.7:
                return "可适度加仓"
            elif "卖出" in final_action and kronos_confidence > 0.7:
                return "可适度减仓"
            else:
                return "保持当前仓位"
                
        except Exception as e:
            return "谨慎操作"
    
    def _generate_price_prediction(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision]) -> Optional[Dict[str, Any]]:
        """生成价格预测详情"""
        try:
            if not kronos_decision or not kronos_decision.kronos_prediction:
                return None
            
            current_price = float(position.get('markPx', 0))
            predicted_change = kronos_decision.kronos_prediction.price_change_pct
            confidence = kronos_decision.kronos_confidence
            
            # 计算预测价格
            predicted_price = current_price * (1 + predicted_change)
            price_change_abs = predicted_price - current_price
            
            # 预测时间范围（基于Kronos模型的预测周期）
            prediction_timeframe = "24小时"  # 可以根据实际模型调整
            
            # 生成预测等级
            if abs(predicted_change) >= 0.1:  # 10%以上
                magnitude = "极大"
            elif abs(predicted_change) >= 0.05:  # 5-10%
                magnitude = "较大"
            elif abs(predicted_change) >= 0.02:  # 2-5%
                magnitude = "中等"
            elif abs(predicted_change) >= 0.01:  # 1-2%
                magnitude = "较小"
            else:  # 1%以下
                magnitude = "微小"
            
            # 预测方向
            if predicted_change > 0.01:
                direction = "上涨"
                direction_emoji = "📈"
            elif predicted_change < -0.01:
                direction = "下跌"
                direction_emoji = "📉"
            else:
                direction = "横盘"
                direction_emoji = "➡️"
            
            # 置信度等级
            if confidence >= 0.8:
                confidence_level = "极高"
            elif confidence >= 0.7:
                confidence_level = "高"
            elif confidence >= 0.6:
                confidence_level = "中等"
            elif confidence >= 0.5:
                confidence_level = "较低"
            else:
                confidence_level = "低"
            
            return {
                "current_price": current_price,
                "predicted_price": predicted_price,
                "price_change_abs": price_change_abs,
                "price_change_pct": predicted_change * 100,
                "direction": direction,
                "direction_emoji": direction_emoji,
                "magnitude": magnitude,
                "confidence": confidence,
                "confidence_level": confidence_level,
                "timeframe": prediction_timeframe,
                "prediction_summary": f"{direction_emoji} 预测{prediction_timeframe}内{direction}{magnitude}幅度 ({predicted_change*100:+.1f}%)"
            }
            
        except Exception as e:
            self.logger.error(f"生成价格预测失败: {e}")
            return None
    
    def _generate_trend_prediction(self, kronos_decision: Optional[KronosEnhancedDecision]) -> Optional[str]:
        """生成趋势预测"""
        try:
            if not kronos_decision or not kronos_decision.kronos_prediction:
                return "趋势不明"
            
            predicted_change = kronos_decision.kronos_prediction.price_change_pct
            confidence = kronos_decision.kronos_confidence
            
            # 基于预测变化和置信度生成趋势描述
            if confidence >= 0.8:
                if predicted_change >= 0.08:  # 8%以上为强烈看涨
                    return "强烈看涨"
                elif predicted_change >= 0.03:  # 3-8%为温和看涨
                    return "温和看涨"
                elif predicted_change <= -0.08:  # -8%以下为强烈看跌
                    return "强烈看跌"
                elif predicted_change <= -0.03:  # -3%到-8%为温和看跌
                    return "温和看跌"
                else:
                    return "震荡整理"
            elif confidence >= 0.6:
                if predicted_change >= 0.05:  # 中等置信度需要更大变化
                    return "偏向看涨"
                elif predicted_change <= -0.05:
                    return "偏向看跌"
                else:
                    return "方向不明"
            else:
                return "趋势不明"
                
        except Exception as e:
            self.logger.error(f"生成趋势预测失败: {e}")
            return "趋势不明"
    
    async def _generate_comprehensive_report(self, analysis_results: List[PositionAnalysisResult]) -> Dict[str, Any]:
        """生成综合报告"""
        try:
            # 获取账户总权益
            account_balance = await self.okx_service.get_account_balance()
            total_equity = account_balance.get('total_equity', 0)
            
            # 计算持仓统计
            total_positions = len(analysis_results)
            high_risk_count = sum(1 for r in analysis_results if r.risk_assessment in ["极高风险", "高风险"])
            urgent_actions = sum(1 for r in analysis_results if r.urgency_level in ["紧急", "高"])
            
            # 计算总持仓价值和盈亏
            total_position_value = 0
            total_unrealized_pnl = 0
            total_potential_pnl = 0
            
            for result in analysis_results:
                # 优先使用原始数据中的position_value_usd
                original_data = result.current_position.get('original_data', {})
                position_value = original_data.get('position_value_usd', result.current_position.get('position_value', 0))
                unrealized_pnl = float(result.current_position.get('upl', 0))
                
                total_position_value += position_value
                total_unrealized_pnl += unrealized_pnl
                total_potential_pnl += result.potential_pnl
            
            # 计算资金利用率
            fund_utilization = (total_position_value / total_equity * 100) if total_equity > 0 else 0
            
            # 计算整体杠杆
            overall_leverage = total_position_value / total_equity if total_equity > 0 else 0
            
            # 计算盈亏比例
            pnl_percentage = (total_unrealized_pnl / total_equity * 100) if total_equity > 0 else 0
            
            # 风险分布
            risk_distribution = {}
            for result in analysis_results:
                risk = result.risk_assessment
                risk_distribution[risk] = risk_distribution.get(risk, 0) + 1
            
            # 紧急操作建议
            urgent_recommendations = [
                r for r in analysis_results 
                if r.urgency_level in ["紧急", "高"]
            ]
            
            # 计算风险评分 (0-100)
            risk_score = self._calculate_risk_score(analysis_results, pnl_percentage, fund_utilization)
            
            # 计算综合评分 (0-100)
            overall_score = self._calculate_overall_score(risk_score, pnl_percentage, fund_utilization)
            
            return {
                "total_positions": total_positions,
                "total_equity": total_equity,
                "total_position_value": total_position_value,
                "total_unrealized_pnl": total_unrealized_pnl,
                "pnl_percentage": pnl_percentage,
                "fund_utilization": fund_utilization,
                "overall_leverage": overall_leverage,
                "high_risk_positions": high_risk_count,
                "urgent_actions_needed": urgent_actions,
                "total_potential_pnl": total_potential_pnl,
                "risk_distribution": risk_distribution,
                "risk_score": risk_score,
                "overall_score": overall_score,
                "urgent_recommendations": urgent_recommendations[:5],  # 最多5个紧急建议
                "analysis_timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"生成综合报告失败: {e}")
            return {}
    
    def _calculate_risk_score(self, analysis_results: List[PositionAnalysisResult], pnl_percentage: float, fund_utilization: float) -> int:
        """计算风险评分 (0-100, 越高越危险)"""
        try:
            risk_score = 0
            
            # 基于盈亏比例的风险 (30分)
            if pnl_percentage < -10:
                risk_score += 30
            elif pnl_percentage < -5:
                risk_score += 20
            elif pnl_percentage < -2:
                risk_score += 10
            
            # 基于资金利用率的风险 (25分)
            if fund_utilization > 80:
                risk_score += 25
            elif fund_utilization > 60:
                risk_score += 15
            elif fund_utilization > 40:
                risk_score += 8
            
            # 基于持仓风险分布的风险 (25分)
            high_risk_count = sum(1 for r in analysis_results if r.risk_assessment in ["极高风险", "高风险"])
            if analysis_results:
                high_risk_ratio = high_risk_count / len(analysis_results)
                risk_score += int(high_risk_ratio * 25)
            
            # 基于紧急操作需求的风险 (20分)
            urgent_count = sum(1 for r in analysis_results if r.urgency_level in ["紧急", "高"])
            if analysis_results:
                urgent_ratio = urgent_count / len(analysis_results)
                risk_score += int(urgent_ratio * 20)
            
            return min(risk_score, 100)
            
        except Exception as e:
            self.logger.error(f"计算风险评分失败: {e}")
            return 50
    
    def _calculate_overall_score(self, risk_score: int, pnl_percentage: float, fund_utilization: float) -> int:
        """计算综合评分 (0-100, 越高越好)"""
        try:
            base_score = 100 - risk_score
            
            # 盈利加分
            if pnl_percentage > 5:
                base_score += 10
            elif pnl_percentage > 2:
                base_score += 5
            
            # 合理资金利用率加分
            if 20 <= fund_utilization <= 50:
                base_score += 5
            
            return max(0, min(base_score, 100))
            
        except Exception as e:
            self.logger.error(f"计算综合评分失败: {e}")
            return 50
    
    async def _send_position_analysis_notification(self, report: Dict[str, Any], analysis_results: List[PositionAnalysisResult]):
        """发送持仓分析通知"""
        try:
            # 确保通知服务已初始化
            await self._ensure_notification_service()
            
            # 检查通知服务是否正确初始化
            if self.notification_service is None:
                self.logger.error("❌ 通知服务初始化失败")
                return False
            
            self.logger.info(f"🔍 通知服务已初始化: {type(self.notification_service).__name__}")
            # 获取报告数据
            total_positions = report.get("total_positions", 0)
            total_equity = report.get("total_equity", 0)
            total_unrealized_pnl = report.get("total_unrealized_pnl", 0)
            pnl_percentage = report.get("pnl_percentage", 0)
            fund_utilization = report.get("fund_utilization", 0)
            overall_leverage = report.get("overall_leverage", 0)
            high_risk_count = report.get("high_risk_positions", 0)
            urgent_actions = report.get("urgent_actions_needed", 0)
            overall_score = report.get("overall_score", 0)
            risk_score = report.get("risk_score", 0)
            
            # 构建通知标题
            if urgent_actions > 0:
                title = f"🚨 Kronos持仓分析: {urgent_actions}个紧急操作"
                priority = "high"
            elif high_risk_count > 0:
                title = f"⚠️ Kronos持仓分析: {high_risk_count}个高风险持仓"
                priority = "medium"
            else:
                title = f"📊 Kronos持仓分析: 账户状态良好"
                priority = "low"
            
            # 风险等级判断
            if risk_score >= 70:
                risk_level = "🔴 HIGH"
            elif risk_score >= 40:
                risk_level = "🟡 MEDIUM"
            elif risk_score >= 20:
                risk_level = "🟢 LOW"
            else:
                risk_level = "🔵 VERY LOW"
            
            # 构建通知内容
            message_parts = [
                f"**账户持仓分析报告 (评分: {overall_score}/100)**",
                "",
                f"📊 **账户概况:**",
                f"  • 总权益: ${total_equity:,.2f} USDT",
                f"  • 持仓数量: {total_positions} 个",
                f"  • 未实现盈亏: ${total_unrealized_pnl:+,.2f} ({pnl_percentage:+.1f}%)",
                f"  • 资金利用率: {fund_utilization:.1f}%",
                f"  • 整体杠杆: {overall_leverage:.1f}x",
                "",
                f"⚠️ **风险评估: {risk_level}**",
                f"  • 风险评分: {risk_score}/100",
            ]
            
            # 添加集中度风险
            if total_positions > 0:
                max_position_value = max(r.current_position.get('original_data', {}).get('position_value_usd', r.current_position.get('position_value', 0)) for r in analysis_results)
                concentration_risk = (max_position_value / total_equity * 100) if total_equity > 0 else 0
                message_parts.append(f"  • 集中度风险: {concentration_risk:.1f}%")
            
            message_parts.append("")
            
            # 添加风险分布
            risk_distribution = report.get("risk_distribution", {})
            if risk_distribution:
                message_parts.append("🎯 风险分布:")
                for risk_level, count in risk_distribution.items():
                    risk_emoji = {
                        "极高风险": "🔴",
                        "高风险": "🟠", 
                        "中等风险": "🟡",
                        "低风险": "🟢",
                        "极低风险": "🔵"
                    }.get(risk_level, "⚪")
                    message_parts.append(f"  {risk_emoji} {risk_level}: {count}个")
                message_parts.append("")
            
            # 添加紧急建议
            urgent_recommendations = report.get("urgent_recommendations", [])
            if urgent_recommendations:
                message_parts.append("🚨 紧急操作建议:")
                for i, rec in enumerate(urgent_recommendations[:3], 1):
                    symbol = rec.symbol.replace('-USDT-SWAP', '')
                    message_parts.append(f"{i}. **{symbol}**: {rec.suggested_action}")
                    message_parts.append(f"   💡 {rec.recommendation}")
                    
                    # 添加预测信息到紧急建议
                    if rec.price_prediction:
                        pred = rec.price_prediction
                        message_parts.append(f"   {pred['direction_emoji']} {pred['prediction_summary']}")
                    
                    if rec.potential_pnl != 0:
                        message_parts.append(f"   💰 预期: {rec.potential_pnl:+.2f} USDT")
                    message_parts.append("")
            
            # 添加详细持仓分析
            message_parts.append("📋 **详细持仓分析:**")
            for i, result in enumerate(analysis_results, 1):
                symbol = result.symbol.replace('-USDT-SWAP', '')
                pos_size = float(result.current_position.get('pos', 0))
                
                # 正确判断持仓方向 - 优先使用posSide字段
                original_data = result.current_position.get('original_data', {})
                pos_side = original_data.get('side', '')
                
                if pos_side:
                    # 使用OKX API的posSide字段
                    if pos_side == 'long':
                        direction = "多头"
                    elif pos_side == 'short':
                        direction = "空头"
                    elif pos_side == 'net':
                        # 买卖模式，通过pos值判断
                        direction = "空头" if pos_size < 0 else "多头"
                    else:
                        direction = "未知"
                else:
                    # 兼容旧数据，通过pos值判断
                    direction = "空头" if pos_size < 0 else "多头"
                # 优先使用原始数据中的position_value_usd，如果没有则使用position_value
                original_data = result.current_position.get('original_data', {})
                position_value = original_data.get('position_value_usd', result.current_position.get('position_value', 0))
                unrealized_pnl = float(result.current_position.get('upl', 0))
                mark_price = float(result.current_position.get('markPx', 0))
                
                # 计算占比
                position_ratio = (position_value / total_equity * 100) if total_equity > 0 else 0
                
                # 盈亏颜色
                pnl_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                
                message_parts.append(f"{i}. **{symbol}** ({direction})")
                message_parts.append(f"   💰 仓位: {abs(pos_size):.4f} @ ${mark_price:,.2f}")
                message_parts.append(f"   📊 价值: ${position_value:,.2f} ({position_ratio:.1f}%)")
                message_parts.append(f"   {pnl_emoji} 盈亏: ${unrealized_pnl:+,.2f}")
                
                # 添加涨跌预测信息
                if result.price_prediction:
                    pred = result.price_prediction
                    message_parts.append(f"   {pred['direction_emoji']} 预测: {pred['prediction_summary']}")
                    message_parts.append(f"   🎯 目标价: ${pred['predicted_price']:.4f} (置信度: {pred['confidence_level']})")
                
                # 添加趋势预测
                if result.trend_prediction and result.trend_prediction != "趋势不明":
                    trend_emoji = {
                        "强烈看涨": "🚀",
                        "温和看涨": "📈", 
                        "偏向看涨": "↗️",
                        "强烈看跌": "💥",
                        "温和看跌": "📉",
                        "偏向看跌": "↘️",
                        "震荡整理": "🔄"
                    }.get(result.trend_prediction, "➡️")
                    message_parts.append(f"   {trend_emoji} 趋势: {result.trend_prediction}")
                
                # 只显示有意义的Kronos建议（过滤"持有观望"）
                if result.kronos_decision and result.kronos_decision.final_action:
                    action = result.kronos_decision.final_action
                    if "持有观望" not in action and "观望" not in action:
                        confidence = result.kronos_decision.kronos_confidence
                        message_parts.append(f"   🤖 Kronos: {action} (置信度: {confidence:.2f})")
                
                message_parts.append(f"   ⚠️ 风险: {result.risk_assessment}")
                
                # 只显示需要操作的建议
                if result.suggested_action not in ["保持当前仓位", "保持观望", "谨慎操作"]:
                    message_parts.append(f"   🔧 建议: {result.suggested_action}")
                
                message_parts.append("")
            
            message_parts.extend([
                "💡 **重要提醒**:",
                "• 本分析基于Kronos AI预测，仅供参考",
                "• 请结合市场情况和个人风险承受能力决策",
                "• 高风险持仓建议及时调整",
                "",
                f"⏰ 下次分析: {(datetime.now() + timedelta(minutes=30)).strftime('%H:%M')}"
            ])
            
            message = "\n".join(message_parts)
            
            # 发送通知
            from app.services.core_notification_service import NotificationContent, NotificationType, NotificationPriority
            
            # 转换优先级字符串为枚举
            priority_map = {
                'low': NotificationPriority.LOW,
                'medium': NotificationPriority.NORMAL,
                'high': NotificationPriority.HIGH,
                'urgent': NotificationPriority.URGENT
            }
            
            notification_content = NotificationContent(
                type=NotificationType.POSITION_ANALYSIS,
                priority=priority_map.get(priority, NotificationPriority.NORMAL),
                title=title,
                message=message
            )
            
            self.logger.info(f"🔍 准备发送通知: 类型={notification_content.type.value}, 优先级={notification_content.priority.value}, 标题={title[:50]}...")
            
            results = await self.notification_service.send_notification(notification_content)
            
            self.logger.info(f"🔍 通知发送结果: {results}")
            
            # 检查是否有任何渠道发送成功
            success = any(results.values()) if isinstance(results, dict) else bool(results)
            
            if success:
                trading_logger.info(f"📢 已发送Kronos持仓分析通知: {total_positions}个持仓")
                successful_channels = [ch for ch, result in results.items() if result] if isinstance(results, dict) else []
                if successful_channels:
                    self.logger.info(f"✅ 通知发送成功的渠道: {', '.join(successful_channels)}")
            else:
                self.logger.warning(f"⚠️ 所有通知渠道发送失败: {results}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"发送持仓分析通知失败: {e}")
            return False
    
    def _should_send_notification(self, analysis_results: List[PositionAnalysisResult] = None) -> bool:
        """检查是否应该发送通知（基于冷却时间和紧急程度）"""
        if not self.last_notification_time:
            self.logger.info("📅 首次运行，允许发送通知")
            return True
        
        # 根据分析结果确定冷却时间
        cooldown_minutes = self._get_dynamic_cooldown_minutes(analysis_results)
        time_since_last = datetime.now() - self.last_notification_time
        cooldown_seconds = cooldown_minutes * 60
        
        should_send = time_since_last.total_seconds() >= cooldown_seconds
        
        self.logger.info(f"🕐 冷却检查: 上次通知时间 {self.last_notification_time.strftime('%H:%M:%S')}, "
                        f"已过去 {time_since_last.total_seconds()/60:.1f}分钟, "
                        f"冷却期 {cooldown_minutes}分钟, "
                        f"允许发送: {should_send}")
        
        return should_send
    
    def _get_dynamic_cooldown_minutes(self, analysis_results: List[PositionAnalysisResult] = None) -> int:
        """根据分析结果动态确定冷却时间"""
        if not analysis_results:
            return self.analysis_config['notification_cooldown_minutes']
        
        # 检查是否有紧急情况
        urgent_count = sum(1 for r in analysis_results if r.urgency_level == "紧急")
        high_risk_count = sum(1 for r in analysis_results if r.risk_assessment in ["极高风险", "高风险"])
        
        if urgent_count > 0:
            return self.analysis_config['urgent_notification_cooldown_minutes']
        elif high_risk_count > 0:
            return self.analysis_config['high_risk_notification_cooldown_minutes']
        else:
            return self.analysis_config['notification_cooldown_minutes']
    
    def _get_cooldown_remaining_minutes(self, analysis_results: List[PositionAnalysisResult] = None) -> float:
        """获取剩余冷却时间（分钟）"""
        if not self.last_notification_time:
            return 0.0
        
        cooldown_minutes = self._get_dynamic_cooldown_minutes(analysis_results)
        time_since_last = datetime.now() - self.last_notification_time
        cooldown_seconds = cooldown_minutes * 60
        
        remaining_seconds = cooldown_seconds - time_since_last.total_seconds()
        return max(0.0, remaining_seconds / 60)
    
    async def get_manual_analysis(self) -> Dict[str, Any]:
        """手动获取持仓分析 - 不发送通知，仅返回分析结果"""
        try:
            self.logger.info(f"🔍 手动获取持仓分析... (实例ID: {id(self)})")
            
            # 获取当前持仓
            positions = await self._get_current_positions()
            if not positions:
                self.logger.info("📊 当前无持仓，跳过分析")
                return {"status": "no_positions"}
            
            # 分析每个持仓
            analysis_results = []
            for position in positions:
                result = await self._analyze_position(position)
                if result:
                    analysis_results.append(result)
            
            # 生成综合报告
            report = await self._generate_comprehensive_report(analysis_results)
            
            # 手动分析不发送通知，只返回结果
            self.logger.info(f"✅ 手动持仓分析完成，分析了 {len(analysis_results)} 个持仓 (未发送通知)")
            
            return {
                "status": "success",
                "positions_analyzed": len(analysis_results),
                "report": report,
                "analysis_time": datetime.now().isoformat(),
                "notification_sent": False
            }
            
        except Exception as e:
            self.logger.error(f"❌ 手动持仓分析失败: {e}")
            return {"status": "error", "error": str(e)}
    
    async def run_startup_analysis(self) -> Dict[str, Any]:
        """启动时运行持仓分析（强制推送）"""
        self.logger.info("🚀 启动时Kronos持仓分析 - 强制推送模式")
        return await self.run_scheduled_analysis(force_notification=True)


# 全局服务实例
_kronos_position_service = None

async def get_kronos_position_service() -> KronosPositionAnalysisService:
    """获取Kronos持仓分析服务实例"""
    global _kronos_position_service
    if _kronos_position_service is None:
        _kronos_position_service = KronosPositionAnalysisService()
    return _kronos_position_service