# -*- coding: utf-8 -*-
"""
核心币种操作建议卡片构建器
专门为核心币种推送优化的卡片格式
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.core.logging import get_logger

logger = get_logger(__name__)


class CoreSymbolsCardBuilder:
    """核心币种操作建议卡片构建器"""
    
    @staticmethod
    def build_core_symbols_card(signals: List[Any], notification_type: str = "核心币种总体推送") -> Dict[str, Any]:
        """构建核心币种操作建议卡片"""
        try:
            if not signals:
                return CoreSymbolsCardBuilder._build_empty_card(notification_type)
            
            # 统计信息
            total_count = len(signals)
            action_stats = {}
            avg_confidence = 0
            
            for signal in signals:
                action = getattr(signal, 'final_action', '未知')
                confidence = getattr(signal, 'final_confidence', 0)
                action_stats[action] = action_stats.get(action, 0) + 1
                avg_confidence += confidence
            
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
                action_icon = CoreSymbolsCardBuilder._get_action_icon(action)
                confidence_color = CoreSymbolsCardBuilder._get_confidence_color(confidence)
                action_color = CoreSymbolsCardBuilder._get_action_color(action)
                
                # 获取当前价格（从信号中获取或设为获取中）
                current_price = getattr(signal, 'current_price', None)
                price_text = f"${current_price:,.2f}" if current_price else "获取中..."
                
                # 币种信息卡片
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
                                "content": f"**🎯 信号强度**\n{CoreSymbolsCardBuilder._get_signal_strength_text(confidence)}",
                                "tag": "lark_md"
                            }
                        }
                    ]
                })
                
                # 分析要点 - 单独一行
                if reasoning and reasoning != '暂无分析':
                    card["elements"].append({
                        "tag": "div",
                        "text": {
                            "content": f"**💡 {clean_symbol} 分析要点**: {reasoning}",
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
                                "content": f"**🤖 AI分析引擎**\nKronos + ML + 技术分析",
                                "tag": "lark_md"
                            }
                        },
                        {
                            "is_short": True,
                            "text": {
                                "content": f"**⏰ 更新时间**\n{datetime.now().strftime('%m-%d %H:%M:%S')}",
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
                            "content": "⚠️ 投资有风险，决策需谨慎。本分析仅供参考，不构成投资建议。"
                        }
                    ]
                }
            ])
            
            return card
            
        except Exception as e:
            logger.error(f"构建核心币种卡片失败: {e}")
            return CoreSymbolsCardBuilder._build_error_card("核心币种分析卡片构建失败")
    
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
        if confidence >= 0.8:
            return "🔥 极强"
        elif confidence >= 0.6:
            return "💪 较强"
        elif confidence >= 0.4:
            return "📊 中等"
        else:
            return "🔍 较弱"
    
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
                        "content": "⚠️ **暂无核心币种数据**\n请检查配置或稍后重试",
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
    
    @staticmethod
    def _build_price_recommendations(action: str, current_price: float, entry_price: float, 
                                   stop_loss_price: float, take_profit_price: float) -> str:
        """构建价格操作建议"""
        if not current_price:
            return "⏳ 价格数据获取中..."
        
        recommendations = []
        
        # 根据操作类型给出具体建议
        if "买入" in action:
            if entry_price and entry_price != current_price:
                recommendations.append(f"💡 **建议买入价**: ${entry_price:,.2f}")
            else:
                recommendations.append(f"💡 **建议买入价**: ${current_price:,.2f} (当前价)")
            
            if stop_loss_price:
                loss_pct = abs(current_price - stop_loss_price) / current_price * 100
                recommendations.append(f"🛡️ **止损价**: ${stop_loss_price:,.2f} (-{loss_pct:.1f}%)")
            
            if take_profit_price:
                profit_pct = abs(take_profit_price - current_price) / current_price * 100
                recommendations.append(f"🎯 **止盈价**: ${take_profit_price:,.2f} (+{profit_pct:.1f}%)")
                
        elif "卖出" in action:
            if entry_price and entry_price != current_price:
                recommendations.append(f"💡 **建议卖出价**: ${entry_price:,.2f}")
            else:
                recommendations.append(f"💡 **建议卖出价**: ${current_price:,.2f} (当前价)")
            
            if stop_loss_price:
                loss_pct = abs(stop_loss_price - current_price) / current_price * 100
                recommendations.append(f"🛡️ **止损价**: ${stop_loss_price:,.2f} (+{loss_pct:.1f}%)")
            
            if take_profit_price:
                profit_pct = abs(current_price - take_profit_price) / current_price * 100
                recommendations.append(f"🎯 **止盈价**: ${take_profit_price:,.2f} (-{profit_pct:.1f}%)")
        else:
            recommendations.append(f"⏸️ **当前价格**: ${current_price:,.2f} (持有观望)")
        
        return " | ".join(recommendations) if recommendations else ""
    
    @staticmethod
    def _extract_technical_details(signal) -> str:
        """提取技术分析详情"""
        details = []
        
        # 提取各种技术指标信息
        try:
            # Kronos AI 结果
            kronos_result = getattr(signal, 'kronos_result', None)
            if kronos_result:
                kronos_confidence = getattr(kronos_result, 'kronos_confidence', 0)
                if kronos_confidence > 0:
                    details.append(f"🤖 Kronos AI: {kronos_confidence:.1%}置信度")
            
            # 技术分析结果
            technical_result = getattr(signal, 'technical_result', None)
            if technical_result and isinstance(technical_result, dict):
                # 趋势信息
                trend_signal = technical_result.get('trend_signal', '')
                if trend_signal:
                    details.append(f"📈 趋势: {trend_signal}")
                
                # 动量信息
                momentum_signal = technical_result.get('momentum_signal', '')
                if momentum_signal:
                    details.append(f"⚡ 动量: {momentum_signal}")
                
                # 成交量信息
                volume_signal = technical_result.get('volume_signal', '')
                if volume_signal:
                    details.append(f"📊 成交量: {volume_signal}")
            
            # ML 结果
            ml_result = getattr(signal, 'ml_result', None)
            if ml_result and isinstance(ml_result, dict):
                ml_confidence = ml_result.get('confidence', 0)
                if ml_confidence > 0:
                    details.append(f"🧠 ML分析: {ml_confidence:.1%}置信度")
            
            # 置信度分解
            confidence_breakdown = getattr(signal, 'confidence_breakdown', None)
            if confidence_breakdown and isinstance(confidence_breakdown, dict):
                breakdown_parts = []
                for source, conf in confidence_breakdown.items():
                    if conf > 0:
                        breakdown_parts.append(f"{source}({conf:.1%})")
                if breakdown_parts:
                    details.append(f"🔍 权重: {' + '.join(breakdown_parts)}")
            
        except Exception as e:
            logger.warning(f"提取技术分析详情失败: {e}")
        
        return " | ".join(details[:3]) if details else "📊 基础技术分析"