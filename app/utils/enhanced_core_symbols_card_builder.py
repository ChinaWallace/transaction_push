# -*- coding: utf-8 -*-
"""
增强版核心币种操作建议卡片构建器 - 修复版
Enhanced Core Symbols Card Builder with detailed technical analysis and price recommendations - Fixed Version
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.core.logging import get_logger
from app.utils.risk_assessment_helper import RiskAssessmentHelper

logger = get_logger(__name__)


class EnhancedCoreSymbolsCardBuilder:
    """增强版核心币种操作建议卡片构建器 - 修复版"""
    
    @staticmethod
    def build_enhanced_core_symbols_card(signals: List[Any], notification_type: str = "核心币种总体推送") -> Dict[str, Any]:
        """构建增强版核心币种操作建议卡片"""
        try:
            if not signals:
                return EnhancedCoreSymbolsCardBuilder._build_empty_card(notification_type)
            
            # 统计信息
            total_count = len(signals)
            action_stats = {}
            avg_confidence = 0
            strong_signals = []
            
            for signal in signals:
                action = getattr(signal, 'final_action', '未知')
                confidence = getattr(signal, 'final_confidence', 0)
                action_stats[action] = action_stats.get(action, 0) + 1
                avg_confidence += confidence
                
                # 收集强信号
                if confidence >= 0.7:
                    strong_signals.append(signal)
            
            avg_confidence = avg_confidence / total_count if total_count > 0 else 0
            
            # 构建卡片
            card = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": "blue",
                    "title": {"content": f"🎯 核心币种总体操作建议 | {notification_type}", "tag": "plain_text"}
                },
                "elements": [
                    # 市场概览
                    {
                        "tag": "div",
                        "fields": [
                            {
                                "is_short": True,
                                "text": {
                                    "content": f"**📊 分析币种**\n{total_count} 个核心币种",
                                    "tag": "lark_md"
                                }
                            },
                            {
                                "is_short": True,
                                "text": {
                                    "content": f"**🎯 平均置信度**\n{avg_confidence:.1%}",
                                    "tag": "lark_md"
                                }
                            },
                            {
                                "is_short": True,
                                "text": {
                                    "content": f"**🔥 强信号数量**\n{len(strong_signals)} 个 (≥70%)",
                                    "tag": "lark_md"
                                }
                            },
                            {
                                "is_short": True,
                                "text": {
                                    "content": f"**⏰ 更新时间**\n{datetime.now().strftime('%H:%M:%S')}",
                                    "tag": "lark_md"
                                }
                            }
                        ]
                    },
                    # 操作分布统计
                    {
                        "tag": "div",
                        "text": {
                            "content": f"**📈 操作分布**: {' | '.join([f'{action} {count}个' for action, count in action_stats.items()])}",
                            "tag": "lark_md"
                        }
                    },
                    {
                        "tag": "hr"
                    }
                ]
            }
            
            # 添加每个币种的详细信息
            for i, signal in enumerate(signals):
                symbol = getattr(signal, 'symbol', 'Unknown')
                action = getattr(signal, 'final_action', 'Unknown')
                confidence = getattr(signal, 'final_confidence', 0)
                reasoning = getattr(signal, 'reasoning', '暂无分析')
                
                # 简化币种名称
                clean_symbol = symbol.replace('-USDT-SWAP', '').replace('-USDT', '')
                
                # 动作图标和颜色
                action_icon = EnhancedCoreSymbolsCardBuilder._get_action_icon(action)
                confidence_color = EnhancedCoreSymbolsCardBuilder._get_confidence_color(confidence)
                action_color = EnhancedCoreSymbolsCardBuilder._get_action_color(action)
                
                # 获取价格和交易建议信息 - 安全处理None值
                current_price = getattr(signal, 'current_price', None)
                entry_price = getattr(signal, 'entry_price', current_price)
                stop_loss_price = getattr(signal, 'stop_loss_price', None)
                take_profit_price = getattr(signal, 'take_profit_price', None)
                
                price_text = f"${current_price:,.2f}" if current_price else "获取中..."
                
                # 币种标题卡片
                card["elements"].append({
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**{action_icon} {clean_symbol}**\n<font color='{action_color}'>{action}</font>",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**💰 当前价格**\n{price_text}",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**📊 置信度**\n<font color='{confidence_color}'>{confidence:.1%}</font>",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**🎯 信号强度**\n{EnhancedCoreSymbolsCardBuilder._get_signal_strength_text(confidence)}",
                                "tag": "lark_md"
                            }
                        }
                    ]
                })
                
                # 构建详细的操作建议 - 安全类型转换
                detailed_recommendations = EnhancedCoreSymbolsCardBuilder._build_detailed_recommendations(
                    clean_symbol, action, 
                    float(current_price or 0), 
                    float(entry_price or current_price or 0), 
                    float(stop_loss_price or 0), 
                    float(take_profit_price or 0), 
                    confidence
                )
                
                # 详细操作建议
                if detailed_recommendations:
                    card["elements"].append({
                        "tag": "div",
                        "text": {
                            "content": detailed_recommendations,
                            "tag": "lark_md"
                        }
                    })
                
                # 提取技术分析详情 - 完整显示
                technical_analysis = EnhancedCoreSymbolsCardBuilder._extract_comprehensive_technical_analysis(signal)
                if technical_analysis:
                    card["elements"].append({
                        "tag": "div",
                        "text": {
                            "content": technical_analysis,
                            "tag": "lark_md"
                        }
                    })
                
                # 核心逻辑和智能风险提示
                risk_assessment = RiskAssessmentHelper.assess_trading_risk(
                    action, confidence, 
                    EnhancedCoreSymbolsCardBuilder._get_signal_strength_text(confidence)
                )
                risk_warning = risk_assessment["risk_message"]
                
                if reasoning and reasoning != '暂无分析':
                    # 不再截断推理内容，完整显示所有分析详情
                    logic_text = f"**💡 {clean_symbol} 核心逻辑**: {reasoning}"
                    if risk_warning:
                        logic_text += f"\n{risk_warning}"
                    
                    card["elements"].append({
                        "tag": "div",
                        "text": {
                            "content": logic_text,
                            "tag": "lark_md"
                        }
                    })
                
                # 添加分隔线（除了最后一个）
                if i < len(signals) - 1:
                    card["elements"].append({"tag": "hr"})
            
            # 底部信息
            card["elements"].extend([
                {"tag": "hr"},
                {
                    "tag": "div",
                    "fields": [
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**🤖 AI分析引擎**\nKronos + VOL/OBV + 技术分析",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**📊 分析维度**\n趋势+动量+成交量+波动性",
                                "tag": "lark_md"
                            }
                        }
                    ]
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text", 
                            "content": "⚠️ 投资有风险，决策需谨慎。本分析仅供参考，不构成投资建议。请根据自身风险承受能力合理配置仓位。"
                        }
                    ]
                }
            ])
            
            return card
            
        except Exception as e:
            logger.error(f"构建增强版核心币种卡片失败: {e}")
            return EnhancedCoreSymbolsCardBuilder._build_error_card("增强版核心币种分析卡片构建失败")
    
    @staticmethod
    def _build_detailed_recommendations(symbol: str, action: str, current_price: float, 
                                      entry_price: float, stop_loss_price: float, 
                                      take_profit_price: float, confidence: float) -> str:
        """构建详细的操作建议"""
        if not current_price or current_price <= 0:
            return f"**🎯 {symbol} 操作建议**价格数据获取中，请稍后..."
        
        recommendations = [f"**🎯 {symbol} 具体操作建议**"]
        
        # 根据操作类型给出具体建议
        if "买入" in action:
            # 买入建议
            if entry_price and entry_price != current_price and entry_price > 0:
                recommendations.append(f"💡 **建议买入价**: ${entry_price:,.2f}")
            else:
                recommendations.append(f"💡 **建议买入价**: ${current_price:,.2f} (当前价)")
            
            # 止损建议
            if stop_loss_price and stop_loss_price > 0:
                loss_pct = abs(current_price - stop_loss_price) / current_price * 100
                recommendations.append(f"🛡️ **止损价**: ${stop_loss_price:,.2f} (-{loss_pct:.1f}%)")
            else:
                # 默认止损
                default_stop = current_price * 0.97
                recommendations.append(f"🛡️ **建议止损**: ${default_stop:,.2f} (-3.0%)")
            
            # 止盈建议
            if take_profit_price and take_profit_price > 0:
                profit_pct = abs(take_profit_price - current_price) / current_price * 100
                recommendations.append(f"🎯 **止盈价**: ${take_profit_price:,.2f} (+{profit_pct:.1f}%)")
            else:
                # 默认止盈
                default_tp = current_price * 1.09
                recommendations.append(f"🎯 **建议止盈**: ${default_tp:,.2f} (+9.0%)")
            
            # 仓位建议
            position_size = EnhancedCoreSymbolsCardBuilder._calculate_position_size(confidence)
            recommendations.append(f"📊 **建议仓位**: {position_size:.1%} (基于{confidence:.1%}置信度)")
                
        elif "卖出" in action:
            # 卖出建议
            if entry_price and entry_price != current_price and entry_price > 0:
                recommendations.append(f"💡 **建议卖出价**: ${entry_price:,.2f}")
            else:
                recommendations.append(f"💡 **建议卖出价**: ${current_price:,.2f} (当前价)")
            
            # 止损建议
            if stop_loss_price and stop_loss_price > 0:
                loss_pct = abs(stop_loss_price - current_price) / current_price * 100
                recommendations.append(f"🛡️ **止损价**: ${stop_loss_price:,.2f} (+{loss_pct:.1f}%)")
            else:
                default_stop = current_price * 1.03
                recommendations.append(f"🛡️ **建议止损**: ${default_stop:,.2f} (+3.0%)")
            
            # 止盈建议
            if take_profit_price and take_profit_price > 0:
                profit_pct = abs(current_price - take_profit_price) / current_price * 100
                recommendations.append(f"🎯 **止盈价**: ${take_profit_price:,.2f} (-{profit_pct:.1f}%)")
            else:
                default_tp = current_price * 0.91
                recommendations.append(f"🎯 **建议止盈**: ${default_tp:,.2f} (-9.0%)")
            
            # 仓位建议
            position_size = EnhancedCoreSymbolsCardBuilder._calculate_position_size(confidence)
            recommendations.append(f"📊 **建议仓位**: {position_size:.1%} (基于{confidence:.1%}置信度)")
        else:
            # 持有观望
            recommendations.append(f"⏸️ **当前价格**: ${current_price:,.2f}")
            recommendations.append("📊 **操作建议**: 持有观望，等待更明确信号")
        
        return "".join(recommendations)
    
    @staticmethod
    def _extract_comprehensive_technical_analysis(signal) -> str:
        """提取全面的技术分析详情 - 完整显示不截断"""
        analysis_parts = []
        
        try:
            # Kronos AI 分析
            kronos_result = getattr(signal, 'kronos_result', None)
            if kronos_result:
                kronos_confidence = getattr(kronos_result, 'kronos_confidence', 0)
                kronos_action = getattr(kronos_result, 'kronos_action', '')
                if kronos_confidence > 0:
                    analysis_parts.append(f"🤖 **Kronos AI**: {kronos_action} (置信度: {kronos_confidence:.1%})")
            
            # 技术分析结果 - 完整显示所有指标
            technical_result = getattr(signal, 'technical_result', None)
            if technical_result and isinstance(technical_result, dict):
                tech_parts = []
                
                # 趋势分析
                trend_analysis = technical_result.get('trend_analysis', {})
                if trend_analysis and isinstance(trend_analysis, dict):
                    overall_trend = trend_analysis.get('overall_trend', '')
                    ma_signal = trend_analysis.get('ma_signal', '')
                    if overall_trend:
                        tech_parts.append(f"趋势: {overall_trend}")
                    if ma_signal:
                        tech_parts.append(f"均线: {ma_signal}")
                
                # 动量分析
                momentum_analysis = technical_result.get('momentum_analysis', {})
                if momentum_analysis and isinstance(momentum_analysis, dict):
                    rsi_signal = momentum_analysis.get('rsi_signal', '')
                    macd_signal = momentum_analysis.get('macd_signal', '')
                    if rsi_signal:
                        tech_parts.append(f"RSI: {rsi_signal}")
                    if macd_signal:
                        tech_parts.append(f"MACD: {macd_signal}")
                
                # 成交量分析 (重点关注VOL和OBV)
                volume_analysis = technical_result.get('volume_analysis', {})
                if volume_analysis and isinstance(volume_analysis, dict):
                    volume_trend = volume_analysis.get('volume_trend', '')
                    obv_signal = volume_analysis.get('obv_signal', '')
                    volume_confirmation = volume_analysis.get('volume_confirmation', '')
                    if volume_trend:
                        tech_parts.append(f"成交量: {volume_trend}")
                    if obv_signal:
                        tech_parts.append(f"OBV: {obv_signal}")
                    if volume_confirmation:
                        tech_parts.append(f"量价确认: {volume_confirmation}")
                
                # 波动性分析
                volatility_analysis = technical_result.get('volatility_analysis', {})
                if volatility_analysis and isinstance(volatility_analysis, dict):
                    bb_signal = volatility_analysis.get('bb_signal', '')
                    atr_signal = volatility_analysis.get('atr_signal', '')
                    if bb_signal:
                        tech_parts.append(f"布林带: {bb_signal}")
                    if atr_signal:
                        tech_parts.append(f"ATR: {atr_signal}")
                
                if tech_parts:
                    # 分行显示技术分析，避免过长
                    tech_display = " | ".join(tech_parts)
                    if len(tech_display) > 80:
                        # 如果太长，分成两行
                        mid_point = len(tech_parts) // 2
                        line1 = " | ".join(tech_parts[:mid_point])
                        line2 = " | ".join(tech_parts[mid_point:])
                        analysis_parts.append(f"📊 **技术分析**: {line1}")
                        analysis_parts.append(f"   └─ {line2}")
                    else:
                        analysis_parts.append(f"📊 **技术分析**: {tech_display}")
            
            # ML分析结果
            ml_result = getattr(signal, 'ml_result', None)
            if ml_result:
                ml_signal = str(getattr(ml_result, 'signal', '')).replace('PredictionSignal.', '')
                ml_confidence = getattr(ml_result, 'confidence', 0)
                if ml_signal and ml_confidence > 0:
                    analysis_parts.append(f"🧠 **ML预测**: {ml_signal} (置信度: {ml_confidence:.1%})")
            
            # 量价分析结果
            volume_price_result = getattr(signal, 'volume_price_result', None)
            if volume_price_result and isinstance(volume_price_result, dict):
                vp_parts = []
                
                # 背离分析
                divergence_analysis = volume_price_result.get('divergence_analysis', {})
                if divergence_analysis and isinstance(divergence_analysis, dict):
                    divergence = divergence_analysis.get('price_volume_divergence', '')
                    if divergence and divergence != '无':
                        vp_parts.append(f"背离: {divergence}")
                
                # 量价确认
                volume_confirmation = volume_price_result.get('volume_confirmation', {})
                if volume_confirmation and isinstance(volume_confirmation, dict):
                    trend_confirmed = volume_confirmation.get('trend_confirmed', False)
                    if trend_confirmed:
                        vp_parts.append("量价确认: ✅")
                    else:
                        vp_parts.append("量价确认: ❌")
                
                if vp_parts:
                    analysis_parts.append(f"📈 **量价分析**: {' | '.join(vp_parts)}")
            
            # 置信度权重分解 - 修正权重显示
            confidence_breakdown = getattr(signal, 'confidence_breakdown', None)
            if confidence_breakdown and isinstance(confidence_breakdown, dict):
                weight_parts = []
                for source, conf in confidence_breakdown.items():
                    # 确保conf是数值类型，防止dict与float比较错误
                    if isinstance(conf, (int, float)) and conf > 0.05:  # 只显示权重大于5%的
                        source_name = {
                            'kronos': 'Kronos',
                            'technical': '技术',
                            'ml': 'ML',
                            'volume_price': '量价'
                        }.get(source, source)
                        weight_parts.append(f"{source_name}({conf:.1%})")
                    elif isinstance(conf, dict):
                        # 如果conf是字典，可能包含更详细的信息
                        weight_value = conf.get('weight', conf.get('confidence', 0))
                        if isinstance(weight_value, (int, float)) and weight_value > 0.05:
                            source_name = {
                                'kronos': 'Kronos',
                                'technical': '技术',
                                'ml': 'ML',
                                'volume_price': '量价'
                            }.get(source, source)
                            weight_parts.append(f"{source_name}({weight_value:.1%})")
                
                if weight_parts:
                    analysis_parts.append(f"⚖️ **权重分解**: {' + '.join(weight_parts)}")
            
        except Exception as e:
            logger.warning(f"提取技术分析详情失败: {e}")
            analysis_parts.append("📊 **技术分析**: 基础分析完成")
        
        return "".join(analysis_parts) if analysis_parts else "📊 **技术分析**: 数据处理中..."
    
    @staticmethod
    def _calculate_position_size(confidence: float) -> float:
        """根据置信度计算建议仓位大小"""
        if confidence >= 0.9:
            return 0.20  # 20%
        elif confidence >= 0.8:
            return 0.15  # 15%
        elif confidence >= 0.7:
            return 0.12  # 12%
        elif confidence >= 0.6:
            return 0.08  # 8%
        elif confidence >= 0.5:
            return 0.05  # 5%
        else:
            return 0.03  # 3%
    
    @staticmethod
    def _get_action_icon(action: str) -> str:
        """获取操作图标"""
        action_icons = {
            "强烈买入": "🚀",
            "买入": "📈", 
            "谨慎买入": "📊",
            "持有": "🤝",
            "谨慎观望": "👀",
            "观望": "⏸️",
            "谨慎卖出": "📉",
            "卖出": "📉",
            "强烈卖出": "🔻"
        }
        return action_icons.get(action, "❓")
    
    @staticmethod
    def _get_action_color(action: str) -> str:
        """获取操作颜色"""
        action_colors = {
            "强烈买入": "green",
            "买入": "green", 
            "谨慎买入": "blue",
            "持有": "grey",
            "谨慎观望": "orange",
            "观望": "orange",
            "谨慎卖出": "red",
            "卖出": "red",
            "强烈卖出": "red"
        }
        return action_colors.get(action, "grey")
    
    @staticmethod
    def _get_confidence_color(confidence: float) -> str:
        """获取置信度颜色"""
        if confidence >= 0.8:
            return "green"
        elif confidence >= 0.6:
            return "blue"
        elif confidence >= 0.4:
            return "orange"
        else:
            return "red"
    
    @staticmethod
    def _get_signal_strength_text(confidence: float) -> str:
        """获取信号强度文本"""
        if confidence >= 0.9:
            return "🔥 极强"
        elif confidence >= 0.8:
            return "💪 很强"
        elif confidence >= 0.7:
            return "📈 较强"
        elif confidence >= 0.6:
            return "📊 中等"
        elif confidence >= 0.5:
            return "🔍 较弱"
        else:
            return "❓ 很弱"
    
    @staticmethod
    def _build_empty_card(notification_type: str) -> Dict[str, Any]:
        """构建空数据卡片"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "orange",
                "title": {"content": f"🎯 核心币种操作建议 | {notification_type}", "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": "⚠️ **暂无核心币种数据**请检查配置或稍后重试",
                        "tag": "lark_md"
                    }
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text", 
                            "content": f"⏰ 检查时间: {datetime.now().strftime('%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }
    
    @staticmethod
    def _build_error_card(error_msg: str) -> Dict[str, Any]:
        """构建错误卡片"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "red",
                "title": {"content": "❌ 核心币种分析错误", "tag": "plain_text"}
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": f"**错误信息**: {error_msg}",
                        "tag": "lark_md"
                    }
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text", 
                            "content": f"⏰ 错误时间: {datetime.now().strftime('%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]
        }