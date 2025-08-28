# -*- coding: utf-8 -*-
"""
新闻分析API接口
"""

from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Query, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.schemas.news import (
    NewsRequest, NewsResponse, NewsAnalysisRequest, NewsAnalysisResponse,
    NewsItem, NewsAnalysisResult
)
from app.services.news_analysis_service import NewsAnalysisService
from app.services.notification_service import NotificationService

logger = get_logger(__name__)
router = APIRouter()


@router.get("/latest", response_model=NewsResponse)
async def get_latest_news(
    limit: int = Query(default=20, ge=1, le=100, description="获取新闻数量"),
    category: Optional[str] = Query(default=None, description="新闻分类"),
    hours_back: int = Query(default=24, ge=1, le=168, description="获取多少小时内的新闻")
) -> NewsResponse:
    """获取最新新闻"""
    try:
        async with NewsAnalysisService() as news_service:
            news_items = await news_service.fetch_latest_news(
                limit=limit,
                category=category
            )
            
            # 过滤时间范围
            if hours_back < 168:  # 如果不是获取全部
                cutoff_time = datetime.now() - timedelta(hours=hours_back)
                news_items = [
                    item for item in news_items 
                    if item.publish_time >= cutoff_time
                ]
            
            return NewsResponse(
                status="success",
                message=f"成功获取 {len(news_items)} 条新闻",
                data=news_items,
                total_count=len(news_items),
                timestamp=datetime.now()
            )
            
    except Exception as e:
        logger.error(f"获取最新新闻失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取新闻失败: {str(e)}")


@router.post("/analyze", response_model=NewsAnalysisResponse)
async def analyze_news(
    request: NewsAnalysisRequest,
    background_tasks: BackgroundTasks
) -> NewsAnalysisResponse:
    """分析新闻并集成Kronos预测"""
    try:
        async with NewsAnalysisService() as news_service:
            # 获取要分析的新闻
            if request.auto_fetch:
                # 自动获取最新新闻
                news_items = await news_service.fetch_latest_news(limit=30)
                
                # 如果有币种过滤，只分析相关新闻
                if request.symbol_filter:
                    filtered_news = []
                    for item in news_items:
                        if any(symbol in item.mentioned_symbols for symbol in request.symbol_filter):
                            filtered_news.append(item)
                    news_items = filtered_news
            else:
                # 根据指定ID获取新闻（这里简化处理，实际需要实现根据ID获取）
                news_items = await news_service.fetch_latest_news(limit=10)
            
            # 执行分析
            if request.enable_kronos:
                analysis_results = await news_service.analyze_news_with_kronos(news_items)
            else:
                # 只做基础分析，不使用Kronos
                analysis_results = []
                for item in news_items:
                    basic_analysis = await news_service._analyze_single_news(item)
                    analysis_results.append(basic_analysis)
            
            # 生成分析摘要
            summary = _generate_analysis_summary(analysis_results)
            
            # 后台任务：发送重要信号通知
            if analysis_results:
                background_tasks.add_task(
                    _send_important_signals_notification,
                    analysis_results
                )
            
            return NewsAnalysisResponse(
                status="success",
                message=f"成功分析 {len(analysis_results)} 条新闻",
                data=analysis_results,
                summary=summary,
                timestamp=datetime.now()
            )
            
    except Exception as e:
        logger.error(f"新闻分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@router.get("/market-impact", response_model=NewsAnalysisResponse)
async def get_market_impact_news(
    hours_back: int = Query(default=24, ge=1, le=168, description="回看时间（小时）"),
    min_importance: float = Query(default=0.5, ge=0.0, le=1.0, description="最低重要性阈值")
) -> NewsAnalysisResponse:
    """获取有市场影响的新闻分析"""
    try:
        async with NewsAnalysisService() as news_service:
            # 获取市场影响较大的新闻
            market_news = await news_service.get_market_moving_news(hours_back=hours_back)
            
            # 按重要性过滤
            filtered_news = [
                result for result in market_news
                if (result.news_item.importance_score or 0) >= min_importance
            ]
            
            # 生成摘要
            summary = _generate_analysis_summary(filtered_news)
            summary['filter_criteria'] = {
                'hours_back': hours_back,
                'min_importance': min_importance
            }
            
            return NewsAnalysisResponse(
                status="success",
                message=f"发现 {len(filtered_news)} 条有市场影响的新闻",
                data=filtered_news,
                summary=summary,
                timestamp=datetime.now()
            )
            
    except Exception as e:
        logger.error(f"获取市场影响新闻失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.get("/symbols/{symbol}/news", response_model=NewsAnalysisResponse)
async def get_symbol_related_news(
    symbol: str,
    hours_back: int = Query(default=48, ge=1, le=168, description="回看时间（小时）"),
    enable_kronos: bool = Query(default=True, description="是否启用Kronos分析")
) -> NewsAnalysisResponse:
    """获取特定币种相关的新闻分析"""
    try:
        async with NewsAnalysisService() as news_service:
            # 获取最新新闻
            all_news = await news_service.fetch_latest_news(limit=100)
            
            # 过滤时间和币种相关的新闻
            cutoff_time = datetime.now() - timedelta(hours=hours_back)
            symbol_news = []
            
            for item in all_news:
                if item.publish_time >= cutoff_time:
                    # 检查是否提及该币种
                    if (symbol in item.mentioned_symbols or 
                        any(symbol.split('-')[0].lower() in item.title.lower() or 
                            symbol.split('-')[0].lower() in item.content.lower())):
                        symbol_news.append(item)
            
            # 分析新闻
            if enable_kronos and symbol_news:
                analysis_results = await news_service.analyze_news_with_kronos(symbol_news)
            else:
                analysis_results = []
                for item in symbol_news:
                    basic_analysis = await news_service._analyze_single_news(item)
                    analysis_results.append(basic_analysis)
            
            # 生成摘要
            summary = _generate_analysis_summary(analysis_results)
            summary['target_symbol'] = symbol
            
            return NewsAnalysisResponse(
                status="success",
                message=f"找到 {len(analysis_results)} 条与 {symbol} 相关的新闻",
                data=analysis_results,
                summary=summary,
                timestamp=datetime.now()
            )
            
    except Exception as e:
        logger.error(f"获取{symbol}相关新闻失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.post("/monitor/start")
async def start_news_monitoring(
    background_tasks: BackgroundTasks,
    interval_minutes: int = Query(default=30, ge=5, le=180, description="监控间隔（分钟）")
) -> JSONResponse:
    """启动新闻监控"""
    try:
        # 添加后台监控任务
        background_tasks.add_task(
            _start_continuous_news_monitoring,
            interval_minutes
        )
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": f"新闻监控已启动，间隔 {interval_minutes} 分钟",
                "timestamp": datetime.now().isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"启动新闻监控失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")


def _generate_analysis_summary(analysis_results: List[NewsAnalysisResult]) -> dict:
    """生成分析摘要"""
    if not analysis_results:
        return {
            "total_analyzed": 0,
            "positive_sentiment": 0,
            "negative_sentiment": 0,
            "neutral_sentiment": 0,
            "trading_signals_generated": 0,
            "kronos_analyses": 0
        }
    
    positive_count = 0
    negative_count = 0
    neutral_count = 0
    total_signals = 0
    kronos_count = 0
    
    for result in analysis_results:
        # 统计情感分布
        sentiment = result.sentiment_analysis.get('overall_sentiment', 'neutral')
        if sentiment == 'positive':
            positive_count += 1
        elif sentiment == 'negative':
            negative_count += 1
        else:
            neutral_count += 1
        
        # 统计交易信号
        total_signals += len(result.trading_signals)
        
        # 统计Kronos分析
        if result.kronos_analysis:
            kronos_count += 1
    
    return {
        "total_analyzed": len(analysis_results),
        "positive_sentiment": positive_count,
        "negative_sentiment": negative_count,
        "neutral_sentiment": neutral_count,
        "trading_signals_generated": total_signals,
        "kronos_analyses": kronos_count,
        "sentiment_distribution": {
            "positive_pct": round(positive_count / len(analysis_results) * 100, 1),
            "negative_pct": round(negative_count / len(analysis_results) * 100, 1),
            "neutral_pct": round(neutral_count / len(analysis_results) * 100, 1)
        }
    }


async def _send_important_signals_notification(analysis_results: List[NewsAnalysisResult]):
    """发送重要信号通知"""
    try:
        # 筛选重要信号
        important_signals = []
        
        for result in analysis_results:
            # 高重要性或强情感的新闻
            if ((result.news_item.importance_score or 0) > 0.7 or 
                abs(result.news_item.sentiment_score or 0) > 0.6):
                
                for signal in result.trading_signals:
                    if signal.get('confidence', 0) > 0.6:
                        important_signals.append({
                            'news_title': result.news_item.title,
                            'symbol': signal['symbol'],
                            'signal': signal['signal'],
                            'confidence': signal['confidence'],
                            'reason': signal['reason']
                        })
        
        if important_signals:
            # 发送通知
            async with NotificationService() as notification_service:
                message = "📰 重要新闻交易信号\n\n"
                
                for i, signal in enumerate(important_signals[:5], 1):  # 最多5个信号
                    message += f"{i}. {signal['news_title'][:50]}...\n"
                    message += f"   币种: {signal['symbol']}\n"
                    message += f"   信号: {signal['signal']} (置信度: {signal['confidence']:.2f})\n"
                    message += f"   原因: {signal['reason']}\n\n"
                
                await notification_service.send_notification(
                    message=message,
                    title="新闻分析交易信号",
                    priority="high"
                )
                
                logger.info(f"已发送 {len(important_signals)} 个重要新闻交易信号通知")
        
    except Exception as e:
        logger.error(f"发送新闻信号通知失败: {e}")


async def _start_continuous_news_monitoring(interval_minutes: int):
    """启动持续新闻监控"""
    import asyncio
    
    logger.info(f"开始持续新闻监控，间隔 {interval_minutes} 分钟")
    
    while True:
        try:
            async with NewsAnalysisService() as news_service:
                # 获取最新新闻并分析
                market_news = await news_service.get_market_moving_news(hours_back=2)
                
                if market_news:
                    # 发送通知
                    await _send_important_signals_notification(market_news)
                
                logger.info(f"新闻监控完成，发现 {len(market_news)} 条重要新闻")
            
            # 等待下次监控
            await asyncio.sleep(interval_minutes * 60)
            
        except Exception as e:
            logger.error(f"新闻监控异常: {e}")
            # 出错后等待较短时间再重试
            await asyncio.sleep(300)  # 5分钟后重试