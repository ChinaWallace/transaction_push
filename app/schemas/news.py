# -*- coding: utf-8 -*-
"""
新闻分析相关的数据模型
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    """单条新闻数据模型"""
    id: str = Field(..., description="新闻ID")
    title: str = Field(..., description="新闻标题")
    content: str = Field(..., description="新闻内容")
    source: str = Field(..., description="新闻来源")
    publish_time: datetime = Field(..., description="发布时间")
    url: Optional[str] = Field(None, description="新闻链接")
    tags: List[str] = Field(default_factory=list, description="新闻标签")
    mentioned_symbols: List[str] = Field(default_factory=list, description="提及的币种符号")
    sentiment_score: Optional[float] = Field(None, description="情感分析得分")
    importance_score: Optional[float] = Field(None, description="重要性得分")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "news_123456",
                "title": "比特币突破65000美元创新高",
                "content": "比特币价格今日突破65000美元...",
                "source": "PANews",
                "publish_time": "2025-08-28T10:00:00Z",
                "url": "https://example.com/news/123456",
                "tags": ["比特币", "价格", "突破"],
                "mentioned_symbols": ["BTC", "BTCUSDT"],
                "sentiment_score": 0.8,
                "importance_score": 0.9
            }
        }


class NewsAnalysisResult(BaseModel):
    """新闻分析结果模型"""
    news_item: NewsItem = Field(..., description="新闻数据")
    extracted_symbols: List[str] = Field(..., description="提取的币种符号")
    sentiment_analysis: Dict[str, Any] = Field(..., description="情感分析结果")
    market_impact: str = Field(..., description="市场影响评估")
    trading_signals: List[Dict[str, Any]] = Field(default_factory=list, description="交易信号")
    kronos_analysis: Optional[Dict[str, Any]] = Field(None, description="Kronos分析结果")
    
    class Config:
        json_schema_extra = {
            "example": {
                "news_item": {
                    "id": "news_123456",
                    "title": "比特币突破65000美元创新高",
                    "content": "比特币价格今日突破65000美元...",
                    "source": "PANews",
                    "publish_time": "2025-08-28T10:00:00Z",
                    "mentioned_symbols": ["BTC", "BTCUSDT"]
                },
                "extracted_symbols": ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
                "sentiment_analysis": {
                    "overall_sentiment": "positive",
                    "confidence": 0.85,
                    "key_phrases": ["突破", "创新高", "上涨"]
                },
                "market_impact": "强烈看涨",
                "trading_signals": [
                    {
                        "symbol": "BTC-USDT-SWAP",
                        "signal": "buy",
                        "confidence": 0.8,
                        "reason": "新闻利好推动价格突破"
                    }
                ]
            }
        }


class NewsRequest(BaseModel):
    """新闻获取请求模型"""
    limit: Optional[int] = Field(default=20, ge=1, le=100, description="获取新闻数量")
    category: Optional[str] = Field(default=None, description="新闻分类")
    keywords: Optional[List[str]] = Field(default=None, description="关键词过滤")
    start_time: Optional[datetime] = Field(default=None, description="开始时间")
    end_time: Optional[datetime] = Field(default=None, description="结束时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "limit": 20,
                "category": "market",
                "keywords": ["比特币", "以太坊"],
                "start_time": "2025-08-28T00:00:00Z",
                "end_time": "2025-08-28T23:59:59Z"
            }
        }


class NewsAnalysisRequest(BaseModel):
    """新闻分析请求模型"""
    news_ids: Optional[List[str]] = Field(default=None, description="指定新闻ID列表")
    auto_fetch: bool = Field(default=True, description="是否自动获取最新新闻")
    enable_kronos: bool = Field(default=True, description="是否启用Kronos分析")
    symbol_filter: Optional[List[str]] = Field(default=None, description="币种过滤")
    
    class Config:
        json_schema_extra = {
            "example": {
                "news_ids": ["news_123456", "news_789012"],
                "auto_fetch": True,
                "enable_kronos": True,
                "symbol_filter": ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
            }
        }


class NewsResponse(BaseModel):
    """新闻响应模型"""
    status: str = Field(default="success", description="响应状态")
    message: str = Field(default="获取成功", description="响应消息")
    data: List[NewsItem] = Field(default_factory=list, description="新闻数据列表")
    total_count: int = Field(default=0, description="总数量")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间戳")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "message": "获取20条新闻成功",
                "data": [],
                "total_count": 20,
                "timestamp": "2025-08-28T12:00:00Z"
            }
        }


class NewsAnalysisResponse(BaseModel):
    """新闻分析响应模型"""
    status: str = Field(default="success", description="响应状态")
    message: str = Field(default="分析完成", description="响应消息")
    data: List[NewsAnalysisResult] = Field(default_factory=list, description="分析结果列表")
    summary: Dict[str, Any] = Field(default_factory=dict, description="分析摘要")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间戳")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "message": "分析5条新闻完成",
                "data": [],
                "summary": {
                    "total_analyzed": 5,
                    "positive_sentiment": 3,
                    "negative_sentiment": 1,
                    "neutral_sentiment": 1,
                    "trading_signals_generated": 8
                },
                "timestamp": "2025-08-28T12:00:00Z"
            }
        }


class KronosNewsAnalysisData(BaseModel):
    """Kronos新闻分析数据模型"""
    symbol: str = Field(..., description="币种符号")
    news_sentiment: str = Field(..., description="新闻情感")
    market_impact_prediction: str = Field(..., description="市场影响预测")
    kronos_confidence: float = Field(..., description="Kronos置信度")
    price_prediction: Optional[Dict[str, float]] = Field(None, description="价格预测")
    trading_recommendation: str = Field(..., description="交易建议")
    risk_assessment: str = Field(..., description="风险评估")
    
    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC-USDT-SWAP",
                "news_sentiment": "强烈看涨",
                "market_impact_prediction": "短期上涨3-5%",
                "kronos_confidence": 0.82,
                "price_prediction": {
                    "1h": 66500.0,
                    "4h": 67200.0,
                    "24h": 68000.0
                },
                "trading_recommendation": "建议适量做多",
                "risk_assessment": "中等风险"
            }
        }