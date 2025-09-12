# -*- coding: utf-8 -*-
"""
TradingView 数据模型
TradingView Data Models

定义TradingView扫描相关的数据结构和验证模式
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class TradingViewScanRequest(BaseModel):
    """TradingView 扫描请求"""
    
    columns: List[str] = Field(..., description="请求的数据列")
    filter: List[Dict[str, Any]] = Field(..., description="筛选条件")
    ignore_unknown_fields: bool = Field(default=False, description="忽略未知字段")
    options: Dict[str, Any] = Field(default_factory=dict, description="选项配置")
    range: List[int] = Field(default=[0, 100], description="数据范围")
    sort: Dict[str, str] = Field(..., description="排序配置")
    symbols: Dict[str, Any] = Field(default_factory=dict, description="符号配置")
    markets: List[str] = Field(default=["coin"], description="市场类型")


class TradingViewStrongSymbolVO(BaseModel):
    """TradingView 强势标的数据对象"""
    
    symbol: str = Field(..., description="交易对符号")
    full_name: str = Field(default="", description="完整名称")
    change_24h: Optional[Decimal] = Field(None, description="24小时涨跌幅")
    effective_liquidity: Optional[Decimal] = Field(None, description="有效流动性")
    volatility: Optional[Decimal] = Field(None, description="波动率")
    rank: Optional[int] = Field(None, description="市值排名")
    tags: str = Field(default="", description="标签")
    selection_count: Optional[int] = Field(default=1, description="入选次数")
    first_flag: str = Field(default="是", description="是否首次入选")
    
    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC-USDT-SWAP",
                "full_name": "Bitcoin",
                "change_24h": 5.67,
                "effective_liquidity": 1.25,
                "volatility": 12.34,
                "rank": 1,
                "tags": "cryptocurrency,layer-1",
                "selection_count": 3,
                "is_first_selection": False
            }
        }


class TradingViewScanResponse(BaseModel):
    """TradingView 扫描响应"""
    
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="响应消息")
    symbols: List[TradingViewStrongSymbolVO] = Field(default_factory=list, description="强势标的列表")
    total_count: int = Field(default=0, description="总数量")
    scan_time: datetime = Field(default_factory=datetime.now, description="扫描时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "扫描完成",
                "symbols": [],
                "total_count": 5,
                "scan_time": "2025-01-01T12:00:00Z"
            }
        }


class TradingViewNotificationMessage(BaseModel):
    """TradingView 通知消息"""
    
    alert_type: str = Field(default="强势标的", description="警报类型")
    symbols: List[TradingViewStrongSymbolVO] = Field(..., description="标的列表")
    scan_time: datetime = Field(..., description="扫描时间")

    def format_message(self) -> str:
        """格式化通知消息 - 考虑中英文字符宽度的严格对齐"""
        if not self.symbols:
            return f"📊 TV强势标的筛选器\n\n暂无符合条件的标的\n\n扫描时间: {self.scan_time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        lines = []
        lines.append("📊 TV强势标的筛选器")
        lines.append("")
        
        # 表头 - 使用字符宽度感知的对齐
        header = (
            self._pad_to_display_width("交易对", 12) +
            self._pad_to_display_width("流动性", 12) +
            self._pad_to_display_width("波动率", 12) +
            self._pad_to_display_width("入选次数", 12) +
            self._pad_to_display_width("市值排名", 12) +
            "标签"
        )
        lines.append(header)
        
        # 数据行
        for symbol_vo in self.symbols:
            liquidity = symbol_vo.effective_liquidity or Decimal('0')
            volatility = symbol_vo.volatility or Decimal('0')
            selection_count = symbol_vo.selection_count or 1
            rank = symbol_vo.rank or 0
            tags_formatted = self._format_tags_for_display(symbol_vo.tags)
            
            # 考虑中英文字符宽度差异的格式化
            symbol_str = self._pad_to_display_width(symbol_vo.symbol, 12)
            liquidity_str = self._pad_to_display_width(f"{liquidity:.2f}", 12)
            volatility_str = self._pad_to_display_width(f"{volatility:.2f}", 12)
            count_str = self._pad_to_display_width(str(selection_count), 12)
            rank_str = self._pad_to_display_width(str(rank), 12)
            
            line = symbol_str + liquidity_str + volatility_str + count_str + rank_str + tags_formatted
            lines.append(line)
        
        lines.append("")
        lines.append(f"扫描时间: {self.scan_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(lines)
    
    def _get_display_width(self, text: str) -> int:
        """计算字符串的实际显示宽度（中文字符=2，英文数字=1）"""
        width = 0
        for char in text:
            if ord(char) > 127:  # 中文字符
                width += 2
            else:  # 英文数字字符
                width += 1
        return width
    
    def _pad_to_display_width(self, text: str, target_width: int) -> str:
        """将文本填充到指定的显示宽度"""
        current_width = self._get_display_width(text)
        if current_width >= target_width:
            # 如果超长，需要智能截断
            return self._truncate_to_display_width(text, target_width)
        else:
            # 补充空格到目标宽度
            padding = target_width - current_width
            return text + " " * padding
    
    def _truncate_to_display_width(self, text: str, max_width: int) -> str:
        """截断文本到指定显示宽度"""
        current_width = 0
        result = ""
        for char in text:
            char_width = 2 if ord(char) > 127 else 1
            if current_width + char_width > max_width:
                break
            result += char
            current_width += char_width
        
        # 如果还有剩余空间，用空格填充
        if current_width < max_width:
            result += " " * (max_width - current_width)
        
        return result
    
    def _format_tags_for_display(self, tags: str) -> str:
        """格式化标签为显示格式 - 转换为中文"""
        if not tags:
            return ""
        
        # 标签映射 - 将英文标签转换为中文
        tag_mapping = {
            "interoperability": "互操作性",
            "gaming": "游戏",
            "collectibles-nfts": "NFT",
            "distributed-computing-storage": "分布式计算",
            "data-management-ai": "数据管理与AI",
            "smart-contract-platforms": "智能合约平台",
            "decentralized-exchanges": "去中心化交易所",
            "memecoins": "迷因"
        }
        
        # 处理标签字符串
        if isinstance(tags, str):
            # 移除方括号并分割
            clean_tags = tags.strip('[]"').replace('"', '')
            tag_list = [tag.strip() for tag in clean_tags.split(',') if tag.strip()]
        else:
            tag_list = tags if isinstance(tags, list) else []
        
        # 转换为中文标签
        chinese_tags = []
        for tag in tag_list:
            tag_clean = tag.strip().lower().replace(' ', '-')
            chinese_tag = tag_mapping.get(tag_clean, tag.strip())
            if chinese_tag and chinese_tag not in chinese_tags:
                chinese_tags.append(chinese_tag)
        
        # 返回格式化的标签字符串 - 保持逗号分隔
        return ",".join(chinese_tags) if chinese_tags else ""


class TradingViewHealthCheck(BaseModel):
    """TradingView 服务健康检查"""
    
    status: str = Field(..., description="服务状态")
    initialized: bool = Field(..., description="是否已初始化")
    api_accessible: bool = Field(..., description="API是否可访问")
    notification_service: bool = Field(..., description="通知服务状态")
    historical_symbols_count: int = Field(default=0, description="历史符号数量")
    last_check: str = Field(..., description="最后检查时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "initialized": True,
                "api_accessible": True,
                "notification_service": True,
                "historical_symbols_count": 150,
                "last_check": "2025-01-01T12:00:00Z"
            }
        }