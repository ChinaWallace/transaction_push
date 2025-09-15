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
                            "content": f"**💡 {clean_symbol} 分析要点**: {reasoning[:120]}{'...' if len(reasoning) > 120 else ''}",
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