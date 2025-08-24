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
from app.services.notification_service import NotificationService
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


class KronosPositionAnalysisService:
    """Kronos持仓分析服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.notification_service = NotificationService()
        self.okx_service = OKXService()
        
        # 分析配置
        self.analysis_config = {
            'enable_notifications': True,
            'min_position_value': 100,  # 最小持仓价值(USDT)
            'high_risk_threshold': 0.15,  # 15%风险阈值
            'notification_cooldown_hours': 2,  # 通知冷却时间
        }
        
        # 通知历史
        self.last_notification_time = None
        
    async def run_scheduled_analysis(self, force_notification: bool = False) -> Dict[str, Any]:
        """运行定时持仓分析"""
        try:
            self.logger.info("🤖 开始定时Kronos持仓分析...")
            
            # 检查通知冷却（启动时强制推送）
            if not force_notification and not self._should_send_notification():
                self.logger.info("⏰ 通知冷却期内，跳过推送")
                return {"status": "skipped", "reason": "cooldown"}
            
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
            
            return PositionAnalysisResult(
                symbol=symbol,
                current_position=position,
                kronos_decision=kronos_decision,
                risk_assessment=risk_assessment,
                recommendation=recommendation,
                urgency_level=urgency_level,
                potential_pnl=potential_pnl,
                suggested_action=suggested_action
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
                
                # 持仓方向
                pos_size = float(position.get('pos', 0))
                is_long = pos_size > 0
                
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
            is_long = pos_size > 0
            
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
                    if rec.potential_pnl != 0:
                        message_parts.append(f"   💰 预期: {rec.potential_pnl:+.2f} USDT")
                    message_parts.append("")
            
            # 添加详细持仓分析
            message_parts.append("📋 **详细持仓分析:**")
            for i, result in enumerate(analysis_results, 1):
                symbol = result.symbol.replace('-USDT-SWAP', '')
                pos_size = float(result.current_position.get('pos', 0))
                direction = "多头" if pos_size > 0 else "空头"
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
            results = await self.notification_service.send_notification(
                message=message,
                priority=priority,
                subject=title
            )
            
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
    
    def _should_send_notification(self) -> bool:
        """检查是否应该发送通知"""
        if not self.last_notification_time:
            return True
        
        cooldown_hours = self.analysis_config['notification_cooldown_hours']
        time_since_last = datetime.now() - self.last_notification_time
        
        return time_since_last.total_seconds() >= cooldown_hours * 3600
    
    async def get_manual_analysis(self) -> Dict[str, Any]:
        """手动获取持仓分析"""
        return await self.run_scheduled_analysis()
    
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