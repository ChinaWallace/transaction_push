# -*- coding: utf-8 -*-
"""
飞书表格卡片构建器
"""

import re
from typing import Any, Dict, List


class FeishuTableCardBuilder:
    """飞书表格卡片构建器"""
    
    @staticmethod
    def build_tradingview_table_card(message: str, lines: List[str]) -> Dict[str, Any]:
        """构建TradingView表格样式卡片"""
        try:
            # 解析消息内容
            symbols_data = []
            scan_time = ""
            
            in_data_section = False
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                if "扫描时间:" in line:
                    scan_time = line.split("扫描时间:")[-1].strip()
                elif line.startswith("📊"):
                    continue
                elif "交易对" in line and "流动性" in line:
                    in_data_section = True
                    continue
                elif in_data_section and line:
                    # 解析数据行
                    parts = re.split(r'\s{2,}', line)
                    parts = [p.strip() for p in parts if p.strip()]
                    
                    if len(parts) >= 5:
                        symbols_data.append({
                            "symbol": parts[0],
                            "current_price": parts[1],
                            "liquidity": parts[2],
                            "volatility": parts[3],
                            "rank": parts[4] if parts[4] != '-' else '0',
                            "tags": " ".join(parts[5:]) if len(parts) > 5 else ""
                        })
            
            # 构建表格卡片
            card = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": "blue",
                    "title": {"content": "📊 TV强势标的筛选器", "tag": "plain_text"}
                },
                "elements": []
            }
            
            elements = card["elements"]
            
            if symbols_data:
                card["elements"].append({
                    "tag": "div",
                    "text": {
                        "content": f"🎯 **本次扫描发现 {len(symbols_data)} 个强势标的**",
                        "tag": "lark_md"
                    }
                })
                
                card["elements"].append({"tag": "hr"})
                
                elements.append({
                    "tag": "div",
                    "text": {
                        "content": "**🪙 交易对     💰 当前价格   💧 流动性     📈 波动率     📊 市值排名   🏷️ 标签**",
                        "tag": "lark_md"
                    }
                })
                
                elements.append({"tag": "hr"})
                
                for data in symbols_data:
                    symbol = f"{data['symbol']:<10}"
                    current_price = f"{data['current_price']:<12}"
                    liquidity = f"{data['liquidity']:<10}"
                    volatility = f"{data['volatility']}%"
                    volatility = f"{volatility:<10}"
                    rank = data['rank'] if data['rank'] != '0' else '-'
                    rank = f"{rank:<10}"
                    tags = data['tags'][:15] + "..." if len(data['tags']) > 15 else data['tags']
                    tags = f"{tags:<10}"
                    
                    elements.append({
                        "tag": "div",
                        "text": {
                            "content": f"{symbol}{current_price}{liquidity}{volatility}{rank}{tags}",
                            "tag": "plain_text"
                        }
                    })
                
                # 操作建议
                card["elements"].append({"tag": "hr"})
                card["elements"].append({
                    "tag": "div",
                    "text": {
                        "content": "💡 **操作建议**\n• 关注流动性较高的标的\n• 结合技术分析确认入场时机\n• 注意风险控制，合理配置仓位",
                        "tag": "lark_md"
                    }
                })
            
            # 时间信息
            if scan_time:
                card["elements"].append({
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": f"⏰ 扫描时间: {scan_time}"}]
                })
            
            return card
            
        except Exception as e:
            return {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": "red",
                    "title": {"content": "📊 TV强势标的筛选器", "tag": "plain_text"}
                },
                "elements": [{
                    "tag": "div",
                    "text": {
                        "content": f"❌ **卡片解析失败**: {str(e)}",
                        "tag": "lark_md"
                    }
                }]
            }