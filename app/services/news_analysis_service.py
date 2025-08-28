# -*- coding: utf-8 -*-
"""
新闻分析服务
News Analysis Service - 获取PANews新闻并进行分析，集成Kronos预测
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import asyncio
import aiohttp
import re
import json
from urllib.parse import urljoin

from app.core.logging import get_logger
from app.core.config import get_settings
from app.schemas.news import NewsItem, NewsAnalysisResult, KronosNewsAnalysisData
from app.utils.exceptions import TradingToolError, ServiceUnavailableError
from app.utils.http_manager import get_http_manager

logger = get_logger(__name__)
settings = get_settings()


class NewsAnalysisService:
    """新闻分析服务类"""
    
    def __init__(self):
        self.base_url = "https://api.panewslab.com/webapi"
        self.http_manager = None
        
        # 币种符号映射 - 将新闻中的币种名称映射到交易对
        self.symbol_mapping = {
            # 主流币种
            '比特币': ['BTC-USDT-SWAP', 'BTC-USD-SWAP'],
            'bitcoin': ['BTC-USDT-SWAP', 'BTC-USD-SWAP'],
            'btc': ['BTC-USDT-SWAP', 'BTC-USD-SWAP'],
            '以太坊': ['ETH-USDT-SWAP', 'ETH-USD-SWAP'],
            'ethereum': ['ETH-USDT-SWAP', 'ETH-USD-SWAP'],
            'eth': ['ETH-USDT-SWAP', 'ETH-USD-SWAP'],
            'solana': ['SOL-USDT-SWAP', 'SOL-USD-SWAP'],
            'sol': ['SOL-USDT-SWAP', 'SOL-USD-SWAP'],
            
            # 其他主流币种
            'bnb': ['BNB-USDT-SWAP'],
            'ada': ['ADA-USDT-SWAP'],
            'dot': ['DOT-USDT-SWAP'],
            'avax': ['AVAX-USDT-SWAP'],
            'atom': ['ATOM-USDT-SWAP'],
            'near': ['NEAR-USDT-SWAP'],
            'link': ['LINK-USDT-SWAP'],
            'uni': ['UNI-USDT-SWAP'],
            'aave': ['AAVE-USDT-SWAP'],
            'ltc': ['LTC-USDT-SWAP'],
            'bch': ['BCH-USDT-SWAP'],
            'xrp': ['XRP-USDT-SWAP'],
            'doge': ['DOGE-USDT-SWAP'],
            
            # 热门DeFi和新兴币种
            'pepe': ['PEPE-USDT-SWAP'],
            'shib': ['SHIB-USDT-SWAP'],
            'apt': ['APT-USDT-SWAP'],
            'sui': ['SUI-USDT-SWAP'],
            'arb': ['ARB-USDT-SWAP'],
            'op': ['OP-USDT-SWAP'],
        }
        
        # 情感分析关键词
        self.sentiment_keywords = {
            'positive': [
                '上涨', '突破', '创新高', '利好', '看涨', '买入', '增长', '飙升',
                '暴涨', '大涨', '强势', '反弹', '回升', '牛市', '积极', '乐观',
                'bullish', 'pump', 'moon', 'surge', 'rally', 'breakout'
            ],
            'negative': [
                '下跌', '暴跌', '崩盘', '利空', '看跌', '卖出', '下降', '跳水',
                '大跌', '熊市', '恐慌', '抛售', '清仓', '做空', '悲观', '风险',
                'bearish', 'dump', 'crash', 'drop', 'fall', 'decline'
            ],
            'neutral': [
                '震荡', '横盘', '整理', '观望', '持平', '稳定', '调整', '盘整',
                'sideways', 'consolidation', 'stable', 'flat'
            ]
        }
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self._ensure_http_manager()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if exc_type:
            logger.error(f"新闻分析服务异常: {exc_type.__name__}: {exc_val}")
    
    async def _ensure_http_manager(self):
        """确保HTTP管理器可用"""
        if not self.http_manager:
            self.http_manager = await get_http_manager()
            logger.debug("✅ 新闻分析服务已连接到统一HTTP连接池")
    
    async def fetch_latest_news(self, limit: int = 20, category: str = None) -> List[NewsItem]:
        """
        获取最新新闻 - 支持多种API源
        """
        try:
            await self._ensure_http_manager()
            
            # 尝试多个新闻源
            news_sources = [
                self._fetch_from_panews,
                self._fetch_from_alternative_api,
                self._get_mock_news_data  # 最后的回退方案
            ]
            
            for source_func in news_sources:
                try:
                    if source_func == self._get_mock_news_data:
                        # 模拟数据不需要参数
                        news_items = source_func()
                    else:
                        news_items = await source_func(limit, category)
                    
                    if news_items and len(news_items) > 0:
                        logger.info(f"成功从 {source_func.__name__} 获取 {len(news_items)} 条新闻")
                        return news_items
                        
                except Exception as e:
                    logger.warning(f"新闻源 {source_func.__name__} 失败: {e}")
                    continue
            
            # 如果所有源都失败，返回模拟数据
            logger.warning("所有新闻源都失败，使用模拟数据")
            return self._get_mock_news_data()
                    
        except Exception as e:
            logger.error(f"获取新闻失败: {e}")
            return self._get_mock_news_data()
    
    async def _fetch_from_panews(self, limit: int, category: str = None) -> List[NewsItem]:
        """从PANews获取新闻"""
        # 尝试不同的PANews API端点
        endpoints = [
            "/news",
            "/v1/news", 
            "/api/news",
            "/webapi/news"
        ]
        
        for endpoint in endpoints:
            try:
                url = f"{self.base_url.replace('/webapi', '')}{endpoint}"
                
                # 尝试不同的参数组合
                param_sets = [
                    {'limit': min(limit, 100), 'offset': 0, 'lang': 'zh'},
                    {'limit': min(limit, 100), 'page': 1, 'language': 'zh'},
                    {'count': min(limit, 100), 'start': 0},
                    {'size': min(limit, 100)}
                ]
                
                if category:
                    for params in param_sets:
                        params['category'] = category
                
                for params in param_sets:
                    try:
                        async with self.http_manager.get_session() as session:
                            kwargs = {'params': params, 'timeout': 10}
                            
                            # 配置代理
                            if settings.proxy_enabled and settings.proxy_url:
                                kwargs['proxy'] = settings.proxy_url
                            
                            async with session.get(url, **kwargs) as response:
                                if response.status == 200:
                                    data = await response.json()
                                    news_items = self._parse_panews_response(data)
                                    if news_items:
                                        return news_items
                                        
                    except Exception as e:
                        logger.debug(f"PANews API尝试失败 {url} {params}: {e}")
                        continue
                        
            except Exception as e:
                logger.debug(f"PANews端点失败 {endpoint}: {e}")
                continue
        
        return []
    
    async def _fetch_from_alternative_api(self, limit: int, category: str = None) -> List[NewsItem]:
        """从备用API获取新闻（可以是其他新闻源）"""
        try:
            # 这里可以添加其他新闻API，比如：
            # - CoinDesk API
            # - CryptoNews API  
            # - 自建新闻聚合API
            
            # 暂时返回空，表示没有备用API
            return []
            
        except Exception as e:
            logger.debug(f"备用API获取失败: {e}")
            return []
    
    def _parse_panews_response(self, data: Any) -> List[NewsItem]:
        """解析PANews API响应"""
        try:
            news_list = []
            
            # 尝试不同的数据结构
            if isinstance(data, dict):
                # 检查是否有错误
                if data.get('code') != 0 and data.get('status') != 'success' and not data.get('success', True):
                    logger.debug(f"PANews API返回错误: {data}")
                    return []
                
                # 尝试不同的数据路径
                possible_paths = [
                    data.get('data', {}).get('list', []),
                    data.get('data', {}).get('items', []),
                    data.get('data', {}).get('news', []),
                    data.get('data', []),
                    data.get('list', []),
                    data.get('items', []),
                    data.get('news', []),
                    data.get('result', [])
                ]
                
                for path in possible_paths:
                    if isinstance(path, list) and len(path) > 0:
                        news_list = path
                        break
                        
            elif isinstance(data, list):
                news_list = data
            
            if not news_list:
                return []
            
            # 转换为NewsItem对象
            news_items = []
            for item in news_list:
                try:
                    news_item = self._parse_news_item(item)
                    if news_item:
                        news_items.append(news_item)
                except Exception as e:
                    logger.debug(f"解析新闻项失败: {e}")
                    continue
            
            return news_items
            
        except Exception as e:
            logger.debug(f"解析PANews响应失败: {e}")
            return []
    
    def _get_mock_news_data(self) -> List[NewsItem]:
        """获取模拟新闻数据用于测试"""
        mock_news = [
            {
                'id': 'mock_001',
                'title': '比特币突破65000美元创新高，市场情绪乐观',
                'content': '比特币价格今日突破65000美元关键阻力位，创下近期新高。分析师认为这是由于机构投资者持续买入和市场情绪改善所致。技术分析显示，BTC有望继续上涨至68000美元。',
                'publish_time': datetime.now().isoformat(),
                'url': 'https://example.com/news/mock_001'
            },
            {
                'id': 'mock_002', 
                'title': '以太坊升级在即，ETH价格强势反弹',
                'content': '以太坊即将进行重要升级，预计将提升网络性能和降低gas费用。受此消息影响，ETH价格今日上涨超过5%，突破2600美元。DeFi生态系统也因此受益。',
                'publish_time': (datetime.now() - timedelta(hours=1)).isoformat(),
                'url': 'https://example.com/news/mock_002'
            },
            {
                'id': 'mock_003',
                'title': 'Solana生态爆发，SOL代币涨幅领先',
                'content': 'Solana生态系统近期表现强劲，多个DeFi项目和NFT平台选择在Solana上部署。SOL代币价格因此大涨8%，成为今日涨幅最大的主流币种之一。',
                'publish_time': (datetime.now() - timedelta(hours=2)).isoformat(),
                'url': 'https://example.com/news/mock_003'
            },
            {
                'id': 'mock_004',
                'title': '加密货币市场监管政策趋于明朗',
                'content': '多国监管机构近期发布了更加明确的加密货币监管指导意见，为行业发展提供了更好的法律框架。市场普遍认为这将有利于加密货币的长期发展。',
                'publish_time': (datetime.now() - timedelta(hours=3)).isoformat(),
                'url': 'https://example.com/news/mock_004'
            },
            {
                'id': 'mock_005',
                'title': '机构投资者持续增持比特币和以太坊',
                'content': '据最新数据显示，机构投资者在过去一周内大幅增持比特币和以太坊。这表明机构对加密货币市场的长期前景保持乐观态度。',
                'publish_time': (datetime.now() - timedelta(hours=4)).isoformat(),
                'url': 'https://example.com/news/mock_005'
            }
        ]
        
        news_items = []
        for item in mock_news:
            try:
                news_item = self._parse_news_item(item)
                if news_item:
                    news_items.append(news_item)
            except Exception as e:
                logger.warning(f"解析模拟新闻失败: {e}")
                continue
        
        return news_items
    
    def _parse_news_item(self, raw_item: Dict[str, Any]) -> Optional[NewsItem]:
        """解析原始新闻数据为NewsItem对象"""
        try:
            # 提取基本信息
            news_id = str(raw_item.get('id', ''))
            title = raw_item.get('title', '').strip()
            content = raw_item.get('content', '').strip()
            
            if not title or not content:
                return None
            
            # 解析发布时间
            publish_time_str = raw_item.get('publish_time') or raw_item.get('created_at')
            if publish_time_str:
                try:
                    # 尝试多种时间格式
                    if isinstance(publish_time_str, (int, float)):
                        publish_time = datetime.fromtimestamp(publish_time_str)
                    else:
                        # 尝试ISO格式
                        if 'T' in publish_time_str:
                            publish_time = datetime.fromisoformat(publish_time_str.replace('Z', '+00:00'))
                        else:
                            # 尝试其他格式
                            publish_time = datetime.fromisoformat(publish_time_str)
                except Exception as e:
                    logger.debug(f"时间解析失败: {publish_time_str}, 错误: {e}")
                    publish_time = datetime.now()
            else:
                publish_time = datetime.now()
            
            # 提取币种符号
            mentioned_symbols = self._extract_symbols_from_text(title + ' ' + content)
            
            # 基础情感分析
            sentiment_score = self._analyze_sentiment(title + ' ' + content)
            
            # 计算重要性得分
            importance_score = self._calculate_importance(title, content, mentioned_symbols)
            
            return NewsItem(
                id=news_id,
                title=title,
                content=content,
                source="PANews",
                publish_time=publish_time,
                url=raw_item.get('url'),
                tags=raw_item.get('tags', []),
                mentioned_symbols=mentioned_symbols,
                sentiment_score=sentiment_score,
                importance_score=importance_score
            )
            
        except Exception as e:
            logger.error(f"解析新闻项失败: {e}")
            return None
    
    def _extract_symbols_from_text(self, text: str) -> List[str]:
        """从文本中提取币种符号"""
        symbols = set()
        text_lower = text.lower()
        
        # 遍历符号映射
        for keyword, symbol_list in self.symbol_mapping.items():
            if keyword.lower() in text_lower:
                symbols.update(symbol_list)
        
        # 使用正则表达式提取币种符号
        # 匹配类似 BTC, ETH, SOL 等格式
        symbol_pattern = r'\b([A-Z]{2,10})\b'
        matches = re.findall(symbol_pattern, text.upper())
        
        for match in matches:
            # 过滤掉常见的非币种缩写
            if match not in ['USD', 'CNY', 'API', 'CEO', 'CTO', 'NFT', 'DeFi', 'DAO']:
                # 尝试构造交易对
                potential_symbols = [
                    f"{match}-USDT-SWAP",
                    f"{match}-USD-SWAP"
                ]
                symbols.update(potential_symbols)
        
        return list(symbols)
    
    def _analyze_sentiment(self, text: str) -> float:
        """分析文本情感倾向，返回-1到1之间的分数"""
        text_lower = text.lower()
        
        positive_count = 0
        negative_count = 0
        
        # 统计正面和负面关键词
        for keyword in self.sentiment_keywords['positive']:
            positive_count += text_lower.count(keyword.lower())
        
        for keyword in self.sentiment_keywords['negative']:
            negative_count += text_lower.count(keyword.lower())
        
        # 计算情感分数
        total_sentiment_words = positive_count + negative_count
        if total_sentiment_words == 0:
            return 0.0  # 中性
        
        sentiment_score = (positive_count - negative_count) / total_sentiment_words
        return max(-1.0, min(1.0, sentiment_score))
    
    def _calculate_importance(self, title: str, content: str, symbols: List[str]) -> float:
        """计算新闻重要性得分"""
        importance = 0.0
        
        # 标题权重更高
        title_lower = title.lower()
        content_lower = content.lower()
        
        # 重要关键词加分
        important_keywords = [
            '突破', '创新高', '暴涨', '暴跌', '监管', '政策', '上市', '合并',
            '分叉', '减半', '升级', '黑客', '被盗', '交易所', '央行', '美联储'
        ]
        
        for keyword in important_keywords:
            if keyword in title_lower:
                importance += 0.3
            elif keyword in content_lower:
                importance += 0.1
        
        # 提及币种数量
        importance += len(symbols) * 0.1
        
        # 内容长度（更长的内容可能更重要）
        if len(content) > 500:
            importance += 0.2
        elif len(content) > 200:
            importance += 0.1
        
        return min(1.0, importance)
    
    async def analyze_news_with_kronos(self, news_items: List[NewsItem]) -> List[NewsAnalysisResult]:
        """
        使用Kronos分析新闻影响
        """
        try:
            # 导入Kronos服务
            from app.services.kronos_prediction_service import KronosPredictionService
            
            results = []
            
            kronos_service = KronosPredictionService()
            
            for news_item in news_items:
                    try:
                        # 基础分析
                        analysis_result = await self._analyze_single_news(news_item)
                        
                        # 如果新闻提及了币种，使用Kronos进行预测
                        if news_item.mentioned_symbols:
                            kronos_analyses = {}
                            
                            # 只分析ETH和SOL（根据配置）
                            target_symbols = [
                                symbol for symbol in news_item.mentioned_symbols 
                                if any(target in symbol for target in ['ETH', 'SOL'])
                            ]
                            
                            for symbol in target_symbols[:3]:  # 限制最多分析3个币种
                                try:
                                    # 获取Kronos预测
                                    kronos_result = await kronos_service.predict_symbol(
                                        symbol=symbol,
                                        lookback_periods=100,
                                        prediction_horizon=12
                                    )
                                    
                                    if kronos_result:
                                        # 结合新闻情感和Kronos预测
                                        kronos_analysis = self._combine_news_and_kronos(
                                            news_item, kronos_result
                                        )
                                        kronos_analyses[symbol] = kronos_analysis
                                        
                                        # 生成交易信号
                                        trading_signal = self._generate_trading_signal(
                                            symbol, news_item, kronos_result
                                        )
                                        analysis_result.trading_signals.append(trading_signal)
                                        
                                except Exception as e:
                                    logger.warning(f"Kronos分析{symbol}失败: {e}")
                                    continue
                            
                            analysis_result.kronos_analysis = kronos_analyses
                        
                        results.append(analysis_result)
                        
                    except Exception as e:
                        logger.error(f"分析新闻失败: {e}")
                        continue
            
            logger.info(f"完成 {len(results)} 条新闻的Kronos分析")
            return results
            
        except Exception as e:
            logger.error(f"新闻Kronos分析失败: {e}")
            return []
    
    async def _analyze_single_news(self, news_item: NewsItem) -> NewsAnalysisResult:
        """分析单条新闻"""
        # 提取币种符号
        extracted_symbols = news_item.mentioned_symbols
        
        # 情感分析
        sentiment_analysis = {
            'overall_sentiment': self._get_sentiment_label(news_item.sentiment_score),
            'confidence': abs(news_item.sentiment_score),
            'score': news_item.sentiment_score,
            'key_phrases': self._extract_key_phrases(news_item.title + ' ' + news_item.content)
        }
        
        # 市场影响评估
        market_impact = self._assess_market_impact(news_item)
        
        return NewsAnalysisResult(
            news_item=news_item,
            extracted_symbols=extracted_symbols,
            sentiment_analysis=sentiment_analysis,
            market_impact=market_impact,
            trading_signals=[],
            kronos_analysis=None
        )
    
    def _get_sentiment_label(self, score: float) -> str:
        """将情感分数转换为标签"""
        if score > 0.3:
            return "positive"
        elif score < -0.3:
            return "negative"
        else:
            return "neutral"
    
    def _extract_key_phrases(self, text: str) -> List[str]:
        """提取关键短语"""
        key_phrases = []
        text_lower = text.lower()
        
        # 提取情感关键词
        for category, keywords in self.sentiment_keywords.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    key_phrases.append(keyword)
        
        return list(set(key_phrases))[:10]  # 最多返回10个关键短语
    
    def _assess_market_impact(self, news_item: NewsItem) -> str:
        """评估市场影响"""
        sentiment_score = news_item.sentiment_score or 0
        importance_score = news_item.importance_score or 0
        
        # 综合评分
        impact_score = (abs(sentiment_score) * 0.6 + importance_score * 0.4)
        
        if impact_score > 0.7:
            if sentiment_score > 0:
                return "强烈看涨"
            else:
                return "强烈看跌"
        elif impact_score > 0.4:
            if sentiment_score > 0:
                return "温和看涨"
            else:
                return "温和看跌"
        else:
            return "影响有限"
    
    def _combine_news_and_kronos(self, news_item: NewsItem, kronos_result: Dict[str, Any]) -> KronosNewsAnalysisData:
        """结合新闻分析和Kronos预测"""
        symbol = kronos_result.get('symbol', '')
        
        # 新闻情感
        news_sentiment = self._get_sentiment_label(news_item.sentiment_score or 0)
        
        # Kronos置信度
        kronos_confidence = kronos_result.get('confidence', 0.0)
        
        # 市场影响预测
        price_change_pct = kronos_result.get('price_change_pct', 0.0)
        market_impact = f"预测{price_change_pct*100:.1f}%变化"
        
        # 交易建议
        trading_recommendation = self._generate_trading_recommendation(
            news_item.sentiment_score, kronos_confidence, price_change_pct
        )
        
        # 风险评估
        risk_assessment = self._assess_risk(kronos_confidence, abs(price_change_pct))
        
        return KronosNewsAnalysisData(
            symbol=symbol,
            news_sentiment=news_sentiment,
            market_impact_prediction=market_impact,
            kronos_confidence=kronos_confidence,
            price_prediction=self._extract_price_predictions(kronos_result),
            trading_recommendation=trading_recommendation,
            risk_assessment=risk_assessment
        )
    
    def _generate_trading_recommendation(self, sentiment_score: float, kronos_confidence: float, price_change: float) -> str:
        """生成交易建议"""
        if kronos_confidence < 0.5:
            return "观望为主"
        
        if sentiment_score > 0.3 and price_change > 0.02:
            return "建议适量做多"
        elif sentiment_score < -0.3 and price_change < -0.02:
            return "建议适量做空"
        elif abs(price_change) > 0.05:
            return "高波动预期，谨慎操作"
        else:
            return "保持现有仓位"
    
    def _assess_risk(self, confidence: float, price_change_abs: float) -> str:
        """评估风险等级"""
        if confidence > 0.8 and price_change_abs < 0.03:
            return "低风险"
        elif confidence > 0.6 and price_change_abs < 0.05:
            return "中等风险"
        else:
            return "高风险"
    
    def _extract_price_predictions(self, kronos_result: Dict[str, Any]) -> Optional[Dict[str, float]]:
        """提取价格预测"""
        predictions = kronos_result.get('predictions', [])
        if not predictions:
            return None
        
        # 简化预测，只返回几个关键时间点
        return {
            "1h": predictions[0].get('close', 0) if len(predictions) > 0 else 0,
            "4h": predictions[3].get('close', 0) if len(predictions) > 3 else 0,
            "24h": predictions[-1].get('close', 0) if predictions else 0
        }
    
    def _generate_trading_signal(self, symbol: str, news_item: NewsItem, kronos_result: Dict[str, Any]) -> Dict[str, Any]:
        """生成交易信号"""
        sentiment_score = news_item.sentiment_score or 0
        kronos_confidence = kronos_result.get('confidence', 0.0)
        price_change_pct = kronos_result.get('price_change_pct', 0.0)
        
        # 信号强度计算
        signal_strength = (abs(sentiment_score) * 0.4 + kronos_confidence * 0.6)
        
        # 信号方向
        if sentiment_score > 0.2 and price_change_pct > 0.01:
            signal = "buy"
        elif sentiment_score < -0.2 and price_change_pct < -0.01:
            signal = "sell"
        else:
            signal = "hold"
        
        return {
            'symbol': symbol,
            'signal': signal,
            'confidence': signal_strength,
            'reason': f"新闻情感: {sentiment_score:.2f}, Kronos预测: {price_change_pct*100:.1f}%",
            'news_title': news_item.title,
            'timestamp': datetime.now()
        }
    
    async def get_market_moving_news(self, hours_back: int = 24) -> List[NewsAnalysisResult]:
        """获取市场影响较大的新闻"""
        try:
            # 获取最近的新闻
            news_items = await self.fetch_latest_news(limit=50)
            
            # 过滤时间范围
            cutoff_time = datetime.now() - timedelta(hours=hours_back)
            recent_news = [
                item for item in news_items 
                if item.publish_time >= cutoff_time
            ]
            
            # 分析新闻
            analysis_results = await self.analyze_news_with_kronos(recent_news)
            
            # 过滤出市场影响较大的新闻
            market_moving_news = [
                result for result in analysis_results
                if (result.news_item.importance_score or 0) > 0.5 or
                   abs(result.news_item.sentiment_score or 0) > 0.4 or
                   len(result.trading_signals) > 0
            ]
            
            # 按重要性排序
            market_moving_news.sort(
                key=lambda x: (x.news_item.importance_score or 0) + abs(x.news_item.sentiment_score or 0),
                reverse=True
            )
            
            logger.info(f"发现 {len(market_moving_news)} 条市场影响较大的新闻")
            return market_moving_news
            
        except Exception as e:
            logger.error(f"获取市场影响新闻失败: {e}")
            return []