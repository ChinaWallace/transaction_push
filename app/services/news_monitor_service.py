# -*- coding: utf-8 -*-
"""
新闻监控服务
News Monitor Service - 定时监控新闻并进行分析推送
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import asyncio

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.news_analysis_service import NewsAnalysisService
from app.services.notification_service import NotificationService
from app.schemas.news import NewsAnalysisResult

logger = get_logger(__name__)
settings = get_settings()


class NewsMonitorService:
    """新闻监控服务类"""
    
    def __init__(self):
        self.last_check_time = None
        self.processed_news_ids = set()  # 记录已处理的新闻ID
        self.max_processed_ids = 1000  # 最大记录数量
        
        # 从配置获取参数
        self.news_config = settings.news_config
        self.enable_monitoring = self.news_config.get('enable_news_analysis', True)
        self.fetch_interval = self.news_config.get('fetch_interval_minutes', 30)
        self.importance_threshold = self.news_config.get('importance_threshold', 0.3)
        self.sentiment_threshold = self.news_config.get('sentiment_threshold', 0.2)
        self.enable_auto_notification = self.news_config.get('enable_auto_notification', True)
        
        # Kronos集成配置
        self.enable_kronos = self.news_config.get('enable_kronos_integration', True)
        self.kronos_symbols = self.news_config.get('kronos_analysis_symbols', ['ETH-USDT-SWAP', 'SOL-USDT-SWAP'])
        self.kronos_threshold = self.news_config.get('kronos_confidence_threshold', 0.6)
        
        # 通知配置
        notification_config = self.news_config.get('notification_config', {})
        self.enable_alerts = notification_config.get('enable_news_alerts', True)
        self.high_impact_threshold = notification_config.get('high_impact_threshold', 0.7)
        self.max_alerts_per_hour = notification_config.get('max_alerts_per_hour', 10)
        
        # 通知频率控制
        self.recent_notifications = []  # 记录最近的通知时间
    
    async def run_monitoring_cycle(self) -> Dict[str, Any]:
        """执行一次完整的新闻监控周期"""
        if not self.enable_monitoring:
            return {
                "status": "disabled",
                "message": "新闻监控已禁用"
            }
        
        try:
            logger.info("📰 开始新闻监控周期...")
            start_time = datetime.now()
            
            # 获取最新新闻
            async with NewsAnalysisService() as news_service:
                # 获取最近2小时的新闻
                news_items = await news_service.fetch_latest_news(limit=50)
                
                if not news_items:
                    logger.info("📰 未获取到新闻数据")
                    return {
                        "status": "success",
                        "message": "未获取到新闻数据",
                        "news_count": 0,
                        "analysis_count": 0,
                        "notifications_sent": 0
                    }
                
                # 过滤出新的新闻（避免重复处理）
                new_news = []
                for item in news_items:
                    if item.id not in self.processed_news_ids:
                        # 只处理最近2小时的新闻
                        if item.publish_time >= datetime.now() - timedelta(hours=2):
                            new_news.append(item)
                            self.processed_news_ids.add(item.id)
                
                # 清理过期的已处理ID记录
                if len(self.processed_news_ids) > self.max_processed_ids:
                    # 保留最近的一半
                    recent_ids = list(self.processed_news_ids)[-self.max_processed_ids//2:]
                    self.processed_news_ids = set(recent_ids)
                
                if not new_news:
                    logger.info("📰 无新的新闻需要处理")
                    return {
                        "status": "success",
                        "message": "无新的新闻需要处理",
                        "news_count": len(news_items),
                        "analysis_count": 0,
                        "notifications_sent": 0
                    }
                
                logger.info(f"📰 发现 {len(new_news)} 条新新闻，开始分析...")
                
                # 分析新闻
                if self.enable_kronos:
                    analysis_results = await news_service.analyze_news_with_kronos(new_news)
                else:
                    # 只做基础分析
                    analysis_results = []
                    for item in new_news:
                        basic_analysis = await news_service._analyze_single_news(item)
                        analysis_results.append(basic_analysis)
                
                # 筛选重要新闻并发送通知
                notifications_sent = 0
                if self.enable_auto_notification and analysis_results:
                    notifications_sent = await self._process_analysis_results(analysis_results)
                
                duration = (datetime.now() - start_time).total_seconds()
                
                result = {
                    "status": "success",
                    "message": f"新闻监控完成，分析了 {len(analysis_results)} 条新闻",
                    "news_count": len(news_items),
                    "new_news_count": len(new_news),
                    "analysis_count": len(analysis_results),
                    "notifications_sent": notifications_sent,
                    "duration_seconds": round(duration, 2),
                    "timestamp": datetime.now()
                }
                
                logger.info(f"✅ 新闻监控周期完成: {result['message']}")
                return result
                
        except Exception as e:
            logger.error(f"❌ 新闻监控周期失败: {e}")
            return {
                "status": "error",
                "message": f"监控失败: {str(e)}",
                "error": str(e),
                "timestamp": datetime.now()
            }
    
    async def _process_analysis_results(self, analysis_results: List[NewsAnalysisResult]) -> int:
        """处理分析结果并发送通知"""
        try:
            # 筛选重要新闻
            important_news = []
            trading_signals = []
            
            for result in analysis_results:
                news_item = result.news_item
                
                # 判断是否为重要新闻
                is_important = (
                    (news_item.importance_score or 0) >= self.importance_threshold or
                    abs(news_item.sentiment_score or 0) >= self.sentiment_threshold or
                    len(result.trading_signals) > 0
                )
                
                if is_important:
                    important_news.append(result)
                    
                    # 收集交易信号
                    for signal in result.trading_signals:
                        if signal.get('confidence', 0) >= self.kronos_threshold:
                            trading_signals.append({
                                'news_title': news_item.title,
                                'symbol': signal['symbol'],
                                'signal': signal['signal'],
                                'confidence': signal['confidence'],
                                'reason': signal['reason'],
                                'timestamp': signal.get('timestamp', datetime.now())
                            })
            
            if not important_news:
                logger.info("📰 无重要新闻需要通知")
                return 0
            
            # 检查通知频率限制
            if not self._can_send_notification():
                logger.info(f"📰 通知频率限制，跳过本次推送（{len(important_news)}条重要新闻）")
                return 0
            
            # 发送新闻摘要通知
            notifications_sent = await self._send_news_summary_notification(important_news, trading_signals)
            
            # 记录通知时间
            self._record_notification()
            
            return notifications_sent
            
        except Exception as e:
            logger.error(f"❌ 处理新闻分析结果失败: {e}")
            return 0
    
    def _can_send_notification(self) -> bool:
        """检查是否可以发送通知（频率限制）"""
        now = datetime.now()
        
        # 清理1小时前的通知记录
        self.recent_notifications = [
            t for t in self.recent_notifications 
            if now - t < timedelta(hours=1)
        ]
        
        # 检查是否超过频率限制
        return len(self.recent_notifications) < self.max_alerts_per_hour
    
    def _record_notification(self):
        """记录通知时间"""
        self.recent_notifications.append(datetime.now())
    
    async def _send_news_summary_notification(self, important_news: List[NewsAnalysisResult], trading_signals: List[Dict]) -> int:
        """发送新闻摘要通知"""
        try:
            async with NotificationService() as notification_service:
                # 构建通知消息
                message = "📰 **重要新闻分析摘要**\n\n"
                
                # 新闻摘要
                message += f"🔍 **发现 {len(important_news)} 条重要新闻:**\n"
                
                for i, result in enumerate(important_news[:5], 1):  # 最多显示5条
                    news = result.news_item
                    sentiment = result.sentiment_analysis.get('overall_sentiment', 'neutral')
                    sentiment_emoji = {'positive': '📈', 'negative': '📉', 'neutral': '➡️'}.get(sentiment, '➡️')
                    
                    title = news.title[:60] + "..." if len(news.title) > 60 else news.title
                    importance = news.importance_score or 0
                    
                    message += f"{i}. {sentiment_emoji} {title}\n"
                    message += f"   重要性: {importance:.2f} | 情感: {sentiment}\n"
                    
                    # 显示提及的币种
                    if news.mentioned_symbols:
                        symbols = [s.replace('-USDT-SWAP', '').replace('-USD-SWAP', '') for s in news.mentioned_symbols[:3]]
                        message += f"   币种: {', '.join(symbols)}\n"
                    
                    message += "\n"
                
                # 交易信号摘要
                if trading_signals:
                    message += f"🎯 **生成 {len(trading_signals)} 个交易信号:**\n"
                    
                    # 按置信度排序，显示前3个
                    top_signals = sorted(trading_signals, key=lambda x: x['confidence'], reverse=True)[:3]
                    
                    for i, signal in enumerate(top_signals, 1):
                        symbol = signal['symbol'].replace('-USDT-SWAP', '').replace('-USD-SWAP', '')
                        action = signal['signal']
                        confidence = signal['confidence']
                        
                        action_emoji = {'buy': '🟢', 'sell': '🔴', 'hold': '🟡'}.get(action, '⚪')
                        
                        message += f"{i}. {action_emoji} {symbol} {action.upper()}\n"
                        message += f"   置信度: {confidence:.2f} | Kronos分析\n"
                        message += f"   原因: {signal['reason'][:50]}...\n\n"
                
                # 添加时间戳和提示
                message += f"⏰ 分析时间: {datetime.now().strftime('%H:%M:%S')}\n"
                message += f"🤖 集成Kronos AI分析，仅推送高质量信号"
                
                # 发送通知
                await notification_service.send_notification(
                    title=f"📰 新闻分析: {len(important_news)}条重要 | {len(trading_signals)}个信号",
                    message=message,
                    notification_type="news_analysis",
                    priority="high" if len(trading_signals) > 0 else "medium"
                )
                
                logger.info(f"📢 已发送新闻摘要通知: {len(important_news)}条新闻, {len(trading_signals)}个信号")
                return 1
                
        except Exception as e:
            logger.error(f"❌ 发送新闻摘要通知失败: {e}")
            return 0
    
    async def get_monitoring_status(self) -> Dict[str, Any]:
        """获取监控状态"""
        return {
            "enabled": self.enable_monitoring,
            "last_check_time": self.last_check_time,
            "processed_news_count": len(self.processed_news_ids),
            "recent_notifications_count": len(self.recent_notifications),
            "config": {
                "fetch_interval_minutes": self.fetch_interval,
                "importance_threshold": self.importance_threshold,
                "sentiment_threshold": self.sentiment_threshold,
                "enable_kronos": self.enable_kronos,
                "kronos_symbols": self.kronos_symbols,
                "max_alerts_per_hour": self.max_alerts_per_hour
            }
        }
    
    async def reset_monitoring_state(self):
        """重置监控状态"""
        self.processed_news_ids.clear()
        self.recent_notifications.clear()
        self.last_check_time = None
        logger.info("📰 新闻监控状态已重置")


# 全局单例实例
_news_monitor_service = None


async def get_news_monitor_service() -> NewsMonitorService:
    """获取新闻监控服务单例"""
    global _news_monitor_service
    if _news_monitor_service is None:
        _news_monitor_service = NewsMonitorService()
    return _news_monitor_service