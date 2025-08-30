#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
负费率监控服务 - 专注于吃利息机会的定时监控
Negative Funding Rate Monitor Service - Hourly monitoring for interest earning opportunities
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import json
from decimal import Decimal
from enum import Enum
from dataclasses import dataclass
import numpy as np

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.okx_service import OKXService
from app.services.core_notification_service import get_core_notification_service
from app.services.notification_service import NotificationService
from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)
settings = get_settings()

# 导入Kronos服务
try:
    from app.services.kronos_integrated_decision_service import get_kronos_integrated_service
    KRONOS_AVAILABLE = True
except ImportError:
    KRONOS_AVAILABLE = False
    logger.warning("Kronos服务不可用，将使用传统技术分析")


class PriceDirection(Enum):
    """价格方向预测"""
    STRONG_UP = "强烈看涨"
    UP = "看涨"
    NEUTRAL = "中性"
    DOWN = "看跌"
    STRONG_DOWN = "强烈看跌"


class RiskLevel(Enum):
    """风险等级"""
    VERY_LOW = "极低风险"
    LOW = "低风险"
    MEDIUM = "中等风险"
    HIGH = "高风险"
    VERY_HIGH = "极高风险"


@dataclass
class PricePrediction:
    """价格预测结果"""
    symbol: str
    current_price: float
    direction: PriceDirection
    confidence: float  # 0-1
    target_price_24h: float
    support_level: float
    resistance_level: float
    volatility_score: float  # 0-100
    trend_strength: float  # 0-1
    reasoning: List[str]
    # 新增Kronos相关字段
    kronos_prediction: Optional[Dict[str, Any]] = None
    kronos_confidence: float = 0.0
    kronos_signal: str = ""
    use_kronos: bool = False


@dataclass
class PositionRecommendation:
    """仓位建议"""
    symbol: str
    recommended_action: str  # "开多", "开空", "观望", "减仓"
    position_size_usdt: float
    leverage: float
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    risk_reward_ratio: float
    max_loss_usdt: float
    expected_daily_income: float
    holding_period_days: int
    risk_level: RiskLevel
    confidence: float
    reasoning: str


class NegativeFundingMonitorService:
    """负费率监控服务 - 每小时监控并推送"""
    
    def __init__(self):
        self.okx_service = OKXService()
        self.notification_service = None  # Will be initialized async
        
        # 历史费率数据存储 (用于检测显著变化)
        self.funding_rate_history = {}  # {symbol: [(timestamp, rate), ...]}
        self.max_history_hours = 24  # 保留24小时历史数据
        
        # 排除的大市值币种（波动太大，不适合吃利息）
        # 注意：ETH和SOL现在用于Kronos分析，不在排除列表中
        self.excluded_major_coins = {
            'BTC-USDT-SWAP', 'BNB-USDT-SWAP', 
            'XRP-USDT-SWAP', 'ADA-USDT-SWAP',
            'DOGE-USDT-SWAP', 'AVAX-USDT-SWAP', 'DOT-USDT-SWAP',
            'LTC-USDT-SWAP', 'BCH-USDT-SWAP',
            'LINK-USDT-SWAP', 'UNI-USDT-SWAP', 'ATOM-USDT-SWAP',
            'NEAR-USDT-SWAP', 'FIL-USDT-SWAP', 'SAND-USDT-SWAP',
            'MANA-USDT-SWAP', 'APE-USDT-SWAP', 'SHIB-USDT-SWAP',
            # USD合约也排除
            'BTC-USD-SWAP', 'ETH-USD-SWAP', 'SOL-USD-SWAP',
            'XRP-USD-SWAP', 'ADA-USD-SWAP', 'DOGE-USD-SWAP',
            'AVAX-USD-SWAP', 'DOT-USD-SWAP', 'LTC-USD-SWAP'
        }
        
        self.funding_intervals_cache = {}  # 缓存费率间隔信息
        self.target_symbols = []
        
        # 仓位管理参数
        self.position_config = {
            'max_position_per_symbol': 5000,    # 单币种最大仓位(USDT)
            'max_total_position': 20000,        # 总仓位上限(USDT)
            'base_leverage': 2.0,               # 基础杠杆
            'max_leverage': 5.0,                # 最大杠杆
            'risk_per_trade': 0.02,             # 单笔交易风险比例
            'min_risk_reward_ratio': 2.0        # 最小风险收益比
        }
    
    async def _ensure_notification_service(self):
        """确保通知服务已初始化"""
        if self.notification_service is None:
            self.notification_service = await get_core_notification_service()
    
    async def get_all_funding_rates_optimized(self) -> List[Dict[str, Any]]:
        """优化版：直接从OKX获取所有SWAP交易对，然后批量获取费率"""
        try:
            logger.debug("📡 正在获取所有SWAP交易对列表...")
            
            # 1. 直接从OKX获取所有SWAP交易对
            async with self.okx_service:
                instruments = await self.okx_service.get_all_instruments('SWAP')
                
                if not instruments:
                    logger.warning("未获取到SWAP交易对列表")
                    return []
                
                # 过滤出活跃的USDT永续合约
                usdt_symbols = [
                    inst['instId'] for inst in instruments 
                    if inst.get('state') == 'live' and 'USDT-SWAP' in inst['instId']
                ]
            
            if not usdt_symbols:
                logger.warning("未获取到USDT永续合约列表")
                return []
            
            logger.debug(f"📋 发现 {len(usdt_symbols)} 个USDT永续合约")
            
            # 2. 直接使用OKX服务的优化批处理方法
            async with self.okx_service:
                funding_rates = await self.okx_service.get_batch_funding_rates(usdt_symbols)
            
            logger.debug(f"✅ 成功获取 {len(funding_rates)} 个USDT合约费率数据")
            return funding_rates

        except Exception as e:
            logger.error(f"批量获取费率失败: {e}")
            return []  
    
    async def get_symbol_basic_info(self, symbol: str) -> Dict[str, Any]:
        """获取币种基础信息（价格和交易量）"""
        try:
            params = {'instId': symbol}
            result = await self.okx_service._make_request('GET', '/api/v5/market/ticker', params=params)
            
            if result:
                data = result[0]
                return {
                    'symbol': symbol,
                    'price': float(data.get('last', '0') or '0'),
                    'volume_24h': float(data.get('volCcy24h', '0') or '0'),  # 24小时交易额
                    'change_24h': float(data.get('chg', '0') or '0')
                }
            
            return {'symbol': symbol, 'price': 0, 'volume_24h': 0, 'change_24h': 0}
            
        except Exception as e:
            logger.warning(f"获取{symbol}基础信息失败: {e}")
            return {'symbol': symbol, 'price': 0, 'volume_24h': 0, 'change_24h': 0}
    
    def _update_funding_rate_history(self, symbol: str, funding_rate: float):
        """更新费率历史数据"""
        current_time = datetime.now()
        
        if symbol not in self.funding_rate_history:
            self.funding_rate_history[symbol] = []
        
        # 添加新数据点
        self.funding_rate_history[symbol].append((current_time, funding_rate))
        
        # 清理超过24小时的历史数据
        cutoff_time = current_time - timedelta(hours=self.max_history_hours)
        self.funding_rate_history[symbol] = [
            (timestamp, rate) for timestamp, rate in self.funding_rate_history[symbol]
            if timestamp > cutoff_time
        ]
    
    def _detect_funding_rate_surge(self, symbol: str, current_rate: float) -> Dict[str, Any]:
        """检测负费率显著变化"""
        if symbol not in self.funding_rate_history or len(self.funding_rate_history[symbol]) < 2:
            return {'is_surge': False, 'surge_info': ''}
        
        history = self.funding_rate_history[symbol]
        
        # 获取1小时前、2小时前、4小时前的费率
        current_time = datetime.now()
        rates_1h_ago = []
        rates_2h_ago = []
        rates_4h_ago = []
        
        for timestamp, rate in history:
            time_diff = (current_time - timestamp).total_seconds() / 3600
            
            if 0.8 <= time_diff <= 1.2:  # 1小时前 (±12分钟)
                rates_1h_ago.append(rate)
            elif 1.8 <= time_diff <= 2.2:  # 2小时前
                rates_2h_ago.append(rate)
            elif 3.8 <= time_diff <= 4.2:  # 4小时前
                rates_4h_ago.append(rate)
        
        surge_info = ""
        is_surge = False
        
        # 检测1小时内的显著变化
        if rates_1h_ago and current_rate < 0:
            avg_1h_ago = sum(rates_1h_ago) / len(rates_1h_ago)
            rate_change_1h = abs(current_rate) - abs(avg_1h_ago)
            
            if rate_change_1h > 0.005:  # 负费率增加超过0.5%
                surge_info += f"📈1h内负费率上升{rate_change_1h:.3%} "
                is_surge = True
        
        # 检测2小时内的显著变化
        if rates_2h_ago and current_rate < 0:
            avg_2h_ago = sum(rates_2h_ago) / len(rates_2h_ago)
            rate_change_2h = abs(current_rate) - abs(avg_2h_ago)
            
            if rate_change_2h > 0.008:  # 2小时内负费率增加超过0.8%
                surge_info += f"📈2h内负费率上升{rate_change_2h:.3%} "
                is_surge = True
        
        # 检测4小时内的显著变化
        if rates_4h_ago and current_rate < 0:
            avg_4h_ago = sum(rates_4h_ago) / len(rates_4h_ago)
            rate_change_4h = abs(current_rate) - abs(avg_4h_ago)
            
            if rate_change_4h > 0.015:  # 4小时内负费率增加超过1.5%
                surge_info += f"🚀4h内负费率大幅上升{rate_change_4h:.3%} "
                is_surge = True
        
        return {
            'is_surge': is_surge,
            'surge_info': surge_info.strip(),
            'current_rate': current_rate,
            'rates_1h_ago': rates_1h_ago,
            'rates_2h_ago': rates_2h_ago,
            'rates_4h_ago': rates_4h_ago
        }

    async def get_top_volume_symbols(self, limit: int = 50) -> List[str]:
        """获取交易量或涨幅前N的币种（排除大市值币种）"""
        try:
            # 获取所有USDT永续合约的24小时统计数据
            result = await self.okx_service._make_request('GET', '/api/v5/market/tickers', 
                                                        params={'instType': 'SWAP'})
            
            if not result:
                return []
            
            # 筛选USDT合约并排除大市值币种
            usdt_tickers = []
            for ticker in result:
                symbol = ticker.get('instId', '')
                if (symbol.endswith('-USDT-SWAP') and 
                    symbol not in self.excluded_major_coins):
                    
                    volume_24h = float(ticker.get('volCcy24h', '0') or '0')
                    change_24h = float(ticker.get('chg', '0') or '0')  # 保留正负号，不取绝对值
                    
                    # 只考虑有一定交易量的币种（大于10万USDT）
                    if volume_24h > 100000:
                        usdt_tickers.append({
                            'symbol': symbol,
                            'volume_24h': volume_24h,
                            'change_24h': change_24h,
                            'score': volume_24h / 1000000 + change_24h * 100  # 综合评分
                        })
            
            # 按综合评分排序（交易量 + 涨跌幅）
            usdt_tickers.sort(key=lambda x: x['score'], reverse=True)
            
            # 返回前N个币种
            top_symbols = [ticker['symbol'] for ticker in usdt_tickers[:limit]]
            
            logger.debug(f"📊 获取到交易量/涨幅前{len(top_symbols)}的币种")
            return top_symbols
            
        except Exception as e:
            logger.error(f"获取热门币种失败: {e}")
            # 返回备用列表
            return [
                'API3-USDT-SWAP', 'AUCTION-USDT-SWAP', 'CORE-USDT-SWAP', 'DGB-USDT-SWAP',
                'LRC-USDT-SWAP', 'RAY-USDT-SWAP', 'LUNC-USDT-SWAP', 'USTC-USDT-SWAP',
                'ORDI-USDT-SWAP', 'SATS-USDT-SWAP', 'PEPE-USDT-SWAP', 'WIF-USDT-SWAP',
                'BONK-USDT-SWAP', 'NEIRO-USDT-SWAP', 'PNUT-USDT-SWAP', 'GOAT-USDT-SWAP'
            ]
    
    async def get_funding_interval(self, symbol: str) -> int:
        """获取币种的费率间隔（小时）"""
        # 检查缓存
        if symbol in self.funding_intervals_cache:
            return self.funding_intervals_cache[symbol]
        
        try:
            # 获取费率历史来计算间隔
            async with self.okx_service:
                history = await self.okx_service.get_funding_rate_history(symbol, limit=5)
                
                if history:
                    interval = self.okx_service.calculate_funding_interval(history)
                    self.funding_intervals_cache[symbol] = interval
                    return interval
                else:
                    # 如果无法获取历史，使用默认值
                    default_interval = 8
                    # 某些特殊币种可能有不同的间隔
                    if any(x in symbol for x in ['DOGE', 'SHIB', 'PEPE', 'FLOKI']):
                        default_interval = 4  # meme币通常4小时
                    elif 'BTC' in symbol or 'ETH' in symbol:
                        default_interval = 8  # 主流币8小时
                    
                    self.funding_intervals_cache[symbol] = default_interval
                    return default_interval
                    
        except Exception as e:
            logger.warning(f"获取{symbol}费率间隔失败: {e}")
            # 默认8小时
            self.funding_intervals_cache[symbol] = 8
            return 8

    async def analyze_negative_funding_opportunities(self, funding_rates: List[Dict[str, Any]], 
                                                   basic_info: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """分析负费率机会 - 优化版本，更精准的机会识别"""
        opportunities = []
        
        # 获取负费率阈值配置
        negative_threshold = settings.strategy_config['funding_rate']['negative_threshold']
        
        for rate_data in funding_rates:
            symbol = rate_data['symbol']
            funding_rate = rate_data['funding_rate']
            
            # 更新费率历史数据
            self._update_funding_rate_history(symbol, funding_rate)
            
            # 检测负费率显著上升
            surge_detection = self._detect_funding_rate_surge(symbol, funding_rate)
            
            # 优化筛选条件：
            # 1. 负费率必须达到阈值 OR 有显著上升趋势
            # 2. 排除费率刚转负但幅度很小的情况（除非有上升趋势）
            if funding_rate >= 0:
                continue
                
            # 更严格的筛选：要么费率足够低，要么有明显上升趋势
            is_significant_negative = funding_rate <= negative_threshold
            is_trending_negative = surge_detection['is_surge'] and funding_rate < -0.0005  # 至少-0.05%
            
            if not (is_significant_negative or is_trending_negative):
                continue
            
            # 获取基础信息
            info = basic_info.get(symbol, {})
            
            # 获取实际的费率间隔
            funding_interval_hours = await self.get_funding_interval(symbol)
            funding_times_per_day = 24 // funding_interval_hours
            
            # 计算收益（使用实际的费率间隔）
            daily_rate = funding_rate * funding_times_per_day
            annual_rate = daily_rate * 365
            
            # 评估机会质量 - 优化评分系统
            score = 0
            reasons = []
            risk_factors = []
            
            # 费率评分 - 更细致的分级
            abs_rate = abs(funding_rate)
            if abs_rate >= 0.015:  # 大于等于1.5%
                score += 80
                reasons.append(f"🔥 超高负费率 {funding_rate*100:.3f}%")
            elif abs_rate >= 0.01:  # 大于等于1%
                score += 65
                reasons.append(f"🚀 极高负费率 {funding_rate*100:.3f}%")
            elif abs_rate >= 0.005:  # 大于等于0.5%
                score += 45
                reasons.append(f"📈 高负费率 {funding_rate*100:.3f}%")
            elif abs_rate >= 0.002:  # 大于等于0.2%
                score += 30
                reasons.append(f"💰 中等负费率 {funding_rate*100:.3f}%")
            elif abs_rate >= 0.001:  # 大于等于0.1%
                score += 20
                reasons.append(f"📊 轻微负费率 {funding_rate*100:.3f}%")
            else:
                score += 10
                reasons.append(f"🔍 微小负费率 {funding_rate*100:.3f}%")
            
            # 交易量评分 - 更精细的分级
            volume_24h = info.get('volume_24h', 0)
            if volume_24h > 50000000:  # 大于5000万USDT
                score += 25
                reasons.append("💎 超大交易量")
            elif volume_24h > 20000000:  # 大于2000万USDT
                score += 22
                reasons.append("🏆 大交易量")
            elif volume_24h > 10000000:  # 大于1000万USDT
                score += 18
                reasons.append("✅ 交易量充足")
            elif volume_24h > 5000000:  # 大于500万USDT
                score += 15
                reasons.append("📊 交易量良好")
            elif volume_24h > 1000000:  # 大于100万USDT
                score += 10
                reasons.append("⚠️ 交易量适中")
            elif volume_24h > 500000:  # 大于50万USDT
                score += 5
                reasons.append("🔸 交易量偏小")
            else:
                risk_factors.append("交易量过小，流动性风险")
            
            # 价格稳定性评分 - 考虑波动率对套利的影响
            change_24h = abs(info.get('change_24h', 0))  # 这里需要绝对值来判断波动性
            if change_24h < 0.02:  # 24小时涨跌幅小于2%
                score += 25
                reasons.append("🛡️ 价格非常稳定")
            elif change_24h < 0.03:  # 小于3%
                score += 20
                reasons.append("✅ 价格稳定")
            elif change_24h < 0.05:  # 小于5%
                score += 15
                reasons.append("📊 价格较稳定")
            elif change_24h < 0.08:  # 小于8%
                score += 8
                reasons.append("⚠️ 价格波动适中")
            elif change_24h < 0.15:  # 小于15%
                score += 3
                risk_factors.append("价格波动较大")
            else:
                risk_factors.append("价格波动剧烈，风险高")
            
            # 负费率上升趋势评分 - 优化趋势检测奖励
            if surge_detection['is_surge']:
                surge_info = surge_detection['surge_info']
                if "4h内负费率大幅上升" in surge_info:
                    score += 35
                    reasons.append(f"🚀 {surge_info}")
                elif "2h内负费率上升" in surge_info:
                    score += 25
                    reasons.append(f"📈 {surge_info}")
                elif "1h内负费率上升" in surge_info:
                    score += 18
                    reasons.append(f"📈 {surge_info}")
                else:
                    score += 12
                    reasons.append(f"📊 {surge_info}")
            
            # 币种特殊性评分 - 考虑币种的历史表现
            symbol_name = symbol.replace('-USDT-SWAP', '')
            
            # 主流币种（相对稳定，适合套利）
            if symbol_name in ['ETH', 'BTC', 'BNB', 'SOL', 'ADA', 'DOT', 'AVAX']:
                score += 15
                reasons.append("🏅 主流币种")
            # DeFi/Layer1 币种（通常有较好的流动性）
            elif symbol_name in ['UNI', 'AAVE', 'COMP', 'SUSHI', 'ATOM', 'NEAR', 'FTM', 'MATIC']:
                score += 10
                reasons.append("🔗 DeFi/Layer1")
            # 热门山寨币
            elif symbol_name in ['DOGE', 'SHIB', 'PEPE', 'FLOKI']:
                score += 5
                reasons.append("🐕 热门币种")
                risk_factors.append("山寨币波动风险")
            
            # 风险调整 - 根据风险因素降低评分
            risk_penalty = len(risk_factors) * 8
            score = max(0, score - risk_penalty)
            
            # 综合评级 - 更精细的分级
            if score >= 90:
                rating = "🌟 极力推荐"
                priority = 1
            elif score >= 75:
                rating = "🟢 强烈推荐"
                priority = 1
            elif score >= 60:
                rating = "🟡 推荐"
                priority = 2
            elif score >= 45:
                rating = "🟠 可考虑"
                priority = 3
            elif score >= 30:
                rating = "🔵 关注"
                priority = 4
            elif score >= 15:
                rating = "⚪ 观望"
                priority = 5
            else:
                rating = "🔴 不推荐"
                priority = 6
            
            # 计算预期收益和风险指标
            expected_daily_return = abs(daily_rate)
            risk_adjusted_return = expected_daily_return / max(change_24h, 0.01)  # 风险调整收益
            
            opportunities.append({
                'symbol': symbol,
                'symbol_name': symbol_name,
                'funding_rate': funding_rate,
                'funding_rate_percent': funding_rate * 100,
                'daily_rate_percent': abs(daily_rate * 100),
                'annual_rate_percent': abs(annual_rate * 100),
                'daily_income_10k': abs(daily_rate * 10000),  # 1万U日收益
                'funding_interval_hours': funding_interval_hours,
                'funding_times_per_day': funding_times_per_day,
                'price': info.get('price', 0),
                'volume_24h': volume_24h,
                'volume_24h_formatted': f"{volume_24h/1000000:.1f}M" if volume_24h > 1000000 else f"{volume_24h/1000:.0f}K",
                'change_24h_percent': info.get('change_24h', 0) * 100,  # OKX返回小数，需要乘100转为百分比
                'score': score,
                'rating': rating,
                'priority': priority,
                'reasons': reasons,
                'risk_factors': risk_factors,
                'next_funding_time': rate_data.get('next_funding_time', 0),
                'analysis_time': datetime.now().isoformat(),
                'surge_detection': surge_detection,
                'is_surge': surge_detection['is_surge'],
                'surge_info': surge_detection['surge_info'],
                # 新增指标
                'expected_daily_return': expected_daily_return,
                'risk_adjusted_return': risk_adjusted_return,
                'liquidity_score': min(100, volume_24h / 100000),  # 流动性评分 (0-100)
                'stability_score': max(0, 100 - change_24h * 1000)  # 稳定性评分 (0-100)
            })
        
        # 多维度排序：优先级 -> 风险调整收益 -> 评分 -> 费率
        opportunities.sort(key=lambda x: (
            x['priority'], 
            -x['risk_adjusted_return'],  # 风险调整收益越高越好
            -x['score'], 
            x['funding_rate']  # 费率越负越好
        ))
        
        return opportunities
    
    def format_notification_message(self, opportunities: List[Dict[str, Any]], enhanced: bool = False) -> str:
        """格式化通知消息 - 支持增强模式
        
        Args:
            opportunities: 机会列表
            enhanced: 是否为增强模式（包含价格预测和仓位建议）
        """
        if not opportunities:
            return f"📊 当前无显著负费率机会（筛选阈值: -0.1%以下）\n⏰ 下次检查: 20分钟后"
        
        # 分离不同类型的机会
        surge_opportunities = [opp for opp in opportunities if opp['is_surge']]
        high_score_opportunities = [opp for opp in opportunities if not opp['is_surge'] and opp['score'] >= 60]
        normal_opportunities = [opp for opp in opportunities if not opp['is_surge'] and opp['score'] < 60]
        
        surge_count = len(surge_opportunities)
        high_score_count = len(high_score_opportunities)
        total_count = len(opportunities)
        
        # 构建标题
        message = f"💰 负费率套利机会分析 ({total_count}个发现)\n"
        message += f"⏰ 分析时间: {datetime.now().strftime('%m-%d %H:%M')}\n"
        
        if surge_count > 0:
            message += f"🚀 趋势机会: {surge_count}个  "
        if high_score_count > 0:
            message += f"⭐ 优质机会: {high_score_count}个"
        message += "\n\n"
        
        # 显示最佳机会（优先级1-2的机会）
        top_opportunities = [opp for opp in opportunities if opp['priority'] <= 2][:5]
        
        if top_opportunities:
            message += "🏆 推荐机会 (TOP5):\n"
            for i, opp in enumerate(top_opportunities, 1):
                symbol_name = opp['symbol_name']
                rate_pct = opp['funding_rate_percent']
                daily_pct = opp['daily_rate_percent']
                daily_income = opp['daily_income_10k']
                rating = opp['rating']
                volume_formatted = opp['volume_24h_formatted']
                change_pct = opp['change_24h_percent']
                
                # 构建单个机会信息
                message += f"{rating} {i}. {symbol_name}\n"
                message += f"   💰 费率: {rate_pct:.3f}% → 日化: {daily_pct:.3f}%\n"
                message += f"   💵 1万U日收益: ${daily_income:.2f}\n"
                message += f"   📊 24h: 量{volume_formatted} | 涨跌{change_pct:+.1f}%\n"
                
                # 显示特殊标签
                if opp['is_surge']:
                    message += f"   🚀 {opp['surge_info']}\n"
                
                # 显示主要优势
                main_reasons = [r for r in opp['reasons'] if any(emoji in r for emoji in ['🔥', '🚀', '💎', '🏆', '✅', '🛡️'])]
                if main_reasons:
                    message += f"   ✨ {main_reasons[0]}\n"
                
                # 显示风险提示
                if opp['risk_factors']:
                    message += f"   ⚠️ {opp['risk_factors'][0]}\n"
                
                # 增强模式：显示价格预测和仓位建议
                if enhanced:
                    # 价格预测
                    if opp.get('price_prediction'):
                        pred = opp['price_prediction']
                        # 显示预测来源
                        source_icon = "🤖" if pred.get('use_kronos') else "📊"
                        source_text = "Kronos AI" if pred.get('use_kronos') else "技术分析"
                        
                        message += f"   {source_icon} {source_text}预测: {pred['direction']} (置信度: {pred['confidence']:.1%})\n"
                        
                        # 安全获取价格数据
                        current_price = pred.get('current_price', 0)
                        target_price = pred.get('target_price_24h', current_price)
                        
                        if target_price != current_price and current_price > 0:
                            change_pct = (target_price - current_price) / current_price * 100
                            message += f"   🎯 24h目标: ${target_price:.4f} ({change_pct:+.2f}%)\n"
                        
                        # 如果是Kronos预测，显示额外信息
                        if pred.get('use_kronos') and pred.get('kronos_signal'):
                            message += f"   💡 AI建议: {pred['kronos_signal']}\n"
                    
                    # 仓位建议
                    if opp.get('position_recommendation'):
                        pos = opp['position_recommendation']
                        message += f"   💼 建议操作: {pos['recommended_action']}\n"
                        if pos['recommended_action'] == "开多":
                            message += f"   💵 建议仓位: ${pos['position_size_usdt']:.0f} ({pos['leverage']:.1f}x)\n"
                            message += f"   📊 预期日收益: ${pos['expected_daily_income']:.2f}\n"
                            message += f"   🛡️ 风险等级: {pos['risk_level']}\n"
                    
                    # 机会类型和紧急程度
                    if opp.get('opportunity_type'):
                        message += f"   ⚡ 类型: {opp['opportunity_type']} | 紧急度: {opp.get('urgency', '正常')}\n"
                
                message += "\n"
        
        # 如果有更多机会，显示统计信息
        remaining_count = total_count - len(top_opportunities)
        if remaining_count > 0:
            message += f"📋 其他机会: {remaining_count}个 (评分较低或风险较高)\n\n"
        
        # 添加操作建议
        message += "💡 操作建议:\n"
        if enhanced:
            # 增强模式建议
            message += "• 优先选择「趋势套利」机会，双重收益\n"
            message += "• 严格按照建议仓位和杠杆操作\n"
            message += "• 设置止损止盈，控制风险\n"
            message += "• 关注价格预测置信度，高置信度优先\n"
            message += "• 「立即」和「尽快」机会及时把握\n\n"
        else:
            # 普通模式建议
            message += "• 优先选择主流币种和高流动性标的\n"
            message += "• 关注价格稳定性，避免高波动币种\n"
            message += "• 建议分散投资，单币种不超过总资金20%\n"
            message += "• 密切监控费率变化，及时调整仓位\n\n"
        
        message += "⏰ 下次检查: 20分钟后\n"
        message += f"📋 筛选标准: 负费率 ≤ -0.1%"
        
        return message
    
    def _generate_buy_recommendation(self, opportunity: Dict[str, Any]) -> str:
        """生成买入建议"""
        score = opportunity['score']
        daily_rate = opportunity['daily_rate_percent']
        volume_24h = opportunity['volume_24h']
        
        if score >= 70:
            if daily_rate > 1.0:  # 日化超过1%
                return "🟢 强烈建议买入 - 高收益低风险"
            else:
                return "🟢 建议买入 - 稳健收益"
        elif score >= 50:
            if daily_rate > 0.5:  # 日化超过0.5%
                return "🟡 可以买入 - 中等收益"
            else:
                return "🟡 谨慎买入 - 收益一般"
        elif score >= 30:
            return "🟠 观望为主 - 风险较高"
        else:
            return "🔴 不建议买入 - 风险过大"
    
    def _generate_detailed_recommendation(self, best_opportunity: Dict[str, Any]) -> str:
        """生成详细的投资建议"""
        daily_rate = best_opportunity['daily_rate_percent']
        score = best_opportunity['score']
        volume_24h = best_opportunity['volume_24h']
        change_24h = abs(best_opportunity.get('change_24h_percent', 0))
        
        recommendation = ""
        
        # 收益评估
        if daily_rate > 2.0:
            recommendation += "💎 超高收益机会"
        elif daily_rate > 1.0:
            recommendation += "🔥 高收益机会"
        elif daily_rate > 0.5:
            recommendation += "✨ 中等收益机会"
        else:
            recommendation += "📊 稳健收益机会"
        
        # 风险评估
        if change_24h < 3:
            recommendation += " | 🛡️ 低波动风险"
        elif change_24h < 8:
            recommendation += " | ⚡ 中等波动风险"
        else:
            recommendation += " | 🌪️ 高波动风险"
        
        # 流动性评估
        if volume_24h > 10000000:  # 大于1000万
            recommendation += " | 💧 流动性充足"
        elif volume_24h > 1000000:  # 大于100万
            recommendation += " | 💧 流动性适中"
        else:
            recommendation += " | 💧 流动性偏低"
        
        return recommendation
    
    async def run_monitoring_cycle(self, enable_enhanced_analysis: bool = False) -> Dict[str, Any]:
        """运行一次监控周期
        
        Args:
            enable_enhanced_analysis: 是否启用增强分析（价格预测和仓位建议）
        """
        try:
            logger.info("🔍 开始负费率监控周期...")
            start_time = datetime.now()
            
            # 1. 直接获取所有USDT永续合约的费率数据（一次性请求，避免频繁调用）
            all_funding_rates = await self.get_all_funding_rates_optimized()
            
            if not all_funding_rates:
                return {'success': False, 'error': '未获取到费率数据'}
            
            # 2. 筛选出负费率低于-0.1%的币种进行详细分析
            significant_negative_threshold = -0.001  # -0.1%
            negative_funding_rates = [r for r in all_funding_rates if r['funding_rate'] <= significant_negative_threshold]
            
            total_negative_count = len([r for r in all_funding_rates if r['funding_rate'] < 0])
            logger.info(f"📊 发现 {total_negative_count} 个负费率币种，其中 {len(negative_funding_rates)} 个低于-0.1%，开始详细分析...")
            
            funding_rates = negative_funding_rates  # 直接使用负费率数据
            
            # 3. 获取负费率币种的基础信息（价格、交易量等）
            negative_symbols = [r['symbol'] for r in funding_rates]
            basic_info = {}
            
            if negative_symbols:
                logger.debug(f"📊 获取 {len(negative_symbols)} 个负费率币种的基础信息...")
                for symbol in negative_symbols:
                    info = await self.get_symbol_basic_info(symbol)
                    basic_info[symbol] = info
                    await asyncio.sleep(0.1)  # 控制频率
            
            # 4. 分析负费率机会
            opportunities = await self.analyze_negative_funding_opportunities(funding_rates, basic_info)
            
            # 5. 增强分析（可选）
            if enable_enhanced_analysis and opportunities:
                logger.info("🚀 开始增强分析（价格预测 + 仓位建议）...")
                opportunities = await self.analyze_enhanced_opportunities(opportunities)
                logger.info(f"✅ 增强分析完成，共 {len(opportunities)} 个机会")
            
            # 6. 生成通知消息
            notification_message = self.format_notification_message(opportunities, enhanced=enable_enhanced_analysis)
            
            # 7. 发送通知（只有发现机会时才发送）
            if opportunities:
                try:
                    # 确保通知服务已初始化
                    await self._ensure_notification_service()
                    
                    # 直接发送详细的负费率机会分析消息
                    from app.services.core_notification_service import NotificationContent, NotificationType, NotificationPriority
                    
                    content = NotificationContent(
                        type=NotificationType.FUNDING_RATE,
                        priority=NotificationPriority.NORMAL,
                        title="💰 负费率套利机会",
                        message=notification_message,
                        metadata={
                            'opportunities': opportunities,  # 添加完整的机会数据
                            'opportunities_count': len(opportunities),
                            'monitoring_type': 'negative_funding',
                            'skip_formatting': True  # 标记跳过重新格式化
                        }
                    )
                    
                    results = await self.notification_service.send_notification(content)
                    if any(results.values()):
                        logger.info("✅ 负费率机会通知已发送")
                        logger.debug(f"📱 推送消息内容:\n{'-'*80}\n{notification_message}\n{'-'*80}")
                    else:
                        logger.warning("⚠️ 通知发送失败")
                except Exception as e:
                    logger.error(f"发送通知失败: {e}")
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            result = {
                'success': True,
                'total_symbols_checked': len(all_funding_rates),
                'funding_rates_obtained': len(funding_rates),
                'negative_funding_count': len(opportunities),
                'opportunities': opportunities,
                'notification_message': notification_message,
                'analysis_time': start_time.isoformat(),
                'duration_seconds': duration
            }
            
            logger.info(f"✅ 监控完成: 发现 {len(opportunities)} 个负费率机会 (耗时 {duration:.1f}秒)")
            return result
            
        except Exception as e:
            logger.error(f"监控周期执行失败: {e}")
            return {'success': False, 'error': str(e)}
    
    async def run_enhanced_monitoring_cycle(self) -> Dict[str, Any]:
        """运行增强版监控周期（包含价格预测和仓位建议）"""
        logger.info("🚀 开始增强版负费率监控周期...")
        return await self.run_monitoring_cycle(enable_enhanced_analysis=True)
    
    # ========== 新增：价格预测和仓位建议功能 ==========
    
    async def get_market_data(self, symbol: str, timeframe: str = '1H', limit: int = 100) -> List[Dict[str, Any]]:
        """获取市场数据"""
        try:
            async with self.okx_service as exchange:
                klines = await exchange.get_kline_data(symbol, timeframe, limit)
                return klines
        except Exception as e:
            logger.error(f"获取 {symbol} 市场数据失败: {e}")
            return []
    
    def calculate_rsi(self, prices: List[float], period: int = 14) -> Optional[float]:
        """计算RSI指标"""
        try:
            if len(prices) < period + 1:
                return None
            
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            gains = [d if d > 0 else 0 for d in deltas]
            losses = [-d if d < 0 else 0 for d in deltas]
            
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            
            if avg_loss == 0:
                return 100
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return rsi
            
        except Exception as e:
            logger.error(f"RSI计算失败: {e}")
            return None
    
    def calculate_moving_average(self, prices: List[float], period: int) -> Optional[float]:
        """计算移动平均线"""
        try:
            if len(prices) < period:
                return None
            return sum(prices[-period:]) / period
        except Exception as e:
            logger.error(f"移动平均线计算失败: {e}")
            return None
    
    async def analyze_price_prediction(self, symbol: str) -> Optional[PricePrediction]:
        """分析价格预测 - 优先使用Kronos，回退到技术分析"""
        try:
            # 1. 尝试使用Kronos预测
            kronos_result = await self._get_kronos_prediction(symbol)
            if kronos_result:
                return kronos_result
            
            # 2. 回退到传统技术分析
            logger.info(f"Kronos预测不可用，使用技术分析 {symbol}")
            # 获取K线数据
            klines_1h = await self.get_market_data(symbol, '1H', 168)  # 7天1小时数据
            
            if not klines_1h or len(klines_1h) < 50:
                return None
            
            # 提取价格数据
            closes = [float(k['close']) for k in klines_1h]
            highs = [float(k['high']) for k in klines_1h]
            lows = [float(k['low']) for k in klines_1h]
            volumes = [float(k['volume']) for k in klines_1h]
            
            current_price = closes[-1]
            
            # 技术指标分析
            rsi = self.calculate_rsi(closes)
            ma20 = self.calculate_moving_average(closes, 20)
            ma50 = self.calculate_moving_average(closes, 50)
            
            # 支撑阻力位计算
            recent_highs = sorted(highs[-50:], reverse=True)[:5]
            recent_lows = sorted(lows[-50:])[:5]
            resistance_level = sum(recent_highs) / len(recent_highs)
            support_level = sum(recent_lows) / len(recent_lows)
            
            # 趋势分析
            trend_strength = 0.5
            if ma20 and ma50:
                if ma20 > ma50 and current_price > ma20:
                    trend_strength = 0.8
                elif ma20 < ma50 and current_price < ma20:
                    trend_strength = 0.2
            
            # 波动率计算
            returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
            volatility = np.std(returns[-20:]) if len(returns) >= 20 else 0.02
            volatility_score = min(volatility * 100 / 0.05 * 100, 100)
            
            # 综合预测
            direction, confidence = self._generate_prediction(rsi, ma20, ma50, current_price, trend_strength)
            
            # 目标价格
            price_change_pct = confidence * 0.03  # 最大3%变动
            if direction in [PriceDirection.STRONG_UP, PriceDirection.UP]:
                target_price_24h = current_price * (1 + price_change_pct)
            elif direction in [PriceDirection.STRONG_DOWN, PriceDirection.DOWN]:
                target_price_24h = current_price * (1 - price_change_pct)
            else:
                target_price_24h = current_price
            
            # 生成推理
            reasoning = self._generate_reasoning(rsi, ma20, ma50, current_price, direction)
            
            return PricePrediction(
                symbol=symbol,
                current_price=current_price,
                direction=direction,
                confidence=confidence,
                target_price_24h=target_price_24h,
                support_level=support_level,
                resistance_level=resistance_level,
                volatility_score=volatility_score,
                trend_strength=trend_strength,
                reasoning=reasoning
            )
            
        except Exception as e:
            logger.error(f"价格预测分析失败 {symbol}: {e}")
            return None
    
    async def _get_kronos_prediction(self, symbol: str) -> Optional[PricePrediction]:
        """获取Kronos预测结果"""
        try:
            if not KRONOS_AVAILABLE:
                return None
            
            # 获取Kronos集成决策服务
            kronos_service = await get_kronos_integrated_service()
            if not kronos_service:
                return None
            
            # 获取Kronos增强决策
            kronos_decision = await kronos_service.get_kronos_enhanced_decision(symbol, force_update=False)
            if not kronos_decision or not kronos_decision.kronos_prediction:
                return None
            
            kronos_pred = kronos_decision.kronos_prediction
            current_price = kronos_pred.current_price
            
            # 转换Kronos预测为PriceDirection
            price_change_pct = kronos_pred.price_change_pct
            confidence = kronos_pred.confidence
            
            if price_change_pct > 0.03 and confidence > 0.7:
                direction = PriceDirection.STRONG_UP
            elif price_change_pct > 0.01 and confidence > 0.6:
                direction = PriceDirection.UP
            elif price_change_pct < -0.03 and confidence > 0.7:
                direction = PriceDirection.STRONG_DOWN
            elif price_change_pct < -0.01 and confidence > 0.6:
                direction = PriceDirection.DOWN
            else:
                direction = PriceDirection.NEUTRAL
            
            # 计算目标价格
            target_price_24h = current_price * (1 + price_change_pct)
            
            # 计算支撑阻力位（基于Kronos预测的波动范围）
            volatility_range = abs(price_change_pct) * 0.5
            support_level = current_price * (1 - volatility_range)
            resistance_level = current_price * (1 + volatility_range)
            
            # 生成推理说明
            reasoning = [
                f"🤖 Kronos AI预测: {direction.value}",
                f"📊 预测变化: {price_change_pct*100:+.2f}%",
                f"🎯 置信度: {confidence:.1%}",
                f"💡 目标价格: ${target_price_24h:.4f}",
                f"📈 当前价格: ${current_price:.4f}"
            ]
            
            # 添加Kronos具体推理
            if hasattr(kronos_decision, 'reasoning') and kronos_decision.reasoning:
                reasoning.append(f"🔍 AI分析: {kronos_decision.reasoning[:100]}...")
            
            return PricePrediction(
                symbol=symbol,
                current_price=current_price,
                direction=direction,
                confidence=confidence,
                target_price_24h=target_price_24h,
                support_level=support_level,
                resistance_level=resistance_level,
                volatility_score=min(100, abs(price_change_pct) * 1000),
                trend_strength=confidence,
                reasoning=reasoning,
                kronos_prediction={
                    'price_change_pct': price_change_pct,
                    'predicted_price': kronos_pred.predicted_price,
                    'confidence': confidence,
                    'prediction_time': kronos_pred.prediction_time.isoformat() if kronos_pred.prediction_time else None
                },
                kronos_confidence=confidence,
                kronos_signal=kronos_decision.final_action,
                use_kronos=True
            )
            
        except Exception as e:
            logger.error(f"获取Kronos预测失败 {symbol}: {e}")
            return None
    
    def _generate_prediction(self, rsi: Optional[float], ma20: Optional[float], 
                           ma50: Optional[float], current_price: float, 
                           trend_strength: float) -> Tuple[PriceDirection, float]:
        """生成价格方向预测"""
        try:
            bullish_score = 0
            bearish_score = 0
            
            # RSI分析
            if rsi:
                if rsi < 30:
                    bullish_score += 0.8
                elif rsi > 70:
                    bearish_score += 0.8
                elif rsi > 50:
                    bullish_score += 0.3
                else:
                    bearish_score += 0.3
            
            # 移动平均线分析
            if ma20 and ma50:
                if ma20 > ma50 and current_price > ma20:
                    bullish_score += 0.7
                elif ma20 < ma50 and current_price < ma20:
                    bearish_score += 0.7
                elif current_price > ma20:
                    bullish_score += 0.4
                else:
                    bearish_score += 0.4
            
            # 趋势强度
            if trend_strength > 0.6:
                bullish_score += 0.5
            elif trend_strength < 0.4:
                bearish_score += 0.5
            
            # 计算最终方向
            net_score = bullish_score - bearish_score
            confidence = min(abs(net_score) / 2, 0.9)
            
            if net_score > 1.0:
                direction = PriceDirection.STRONG_UP
            elif net_score > 0.3:
                direction = PriceDirection.UP
            elif net_score > -0.3:
                direction = PriceDirection.NEUTRAL
            elif net_score > -1.0:
                direction = PriceDirection.DOWN
            else:
                direction = PriceDirection.STRONG_DOWN
            
            return direction, confidence
            
        except Exception as e:
            logger.error(f"生成预测失败: {e}")
            return PriceDirection.NEUTRAL, 0.5
    
    def _generate_reasoning(self, rsi: Optional[float], ma20: Optional[float], 
                          ma50: Optional[float], current_price: float, 
                          direction: PriceDirection) -> List[str]:
        """生成预测推理"""
        reasoning = []
        
        try:
            if rsi:
                if rsi < 30:
                    reasoning.append(f"RSI({rsi:.1f})超卖，支持反弹")
                elif rsi > 70:
                    reasoning.append(f"RSI({rsi:.1f})超买，存在回调压力")
                else:
                    reasoning.append(f"RSI({rsi:.1f})中性区域")
            
            if ma20 and ma50:
                if ma20 > ma50:
                    reasoning.append("短期均线上穿长期均线，趋势向好")
                else:
                    reasoning.append("短期均线下穿长期均线，趋势偏弱")
                
                if current_price > ma20:
                    reasoning.append("价格位于短期均线上方")
                else:
                    reasoning.append("价格位于短期均线下方")
            
            direction_desc = {
                PriceDirection.STRONG_UP: "技术面强烈看涨",
                PriceDirection.UP: "技术面偏向看涨",
                PriceDirection.NEUTRAL: "技术面中性",
                PriceDirection.DOWN: "技术面偏向看跌",
                PriceDirection.STRONG_DOWN: "技术面强烈看跌"
            }
            reasoning.append(direction_desc.get(direction, "技术面不明确"))
            
        except Exception as e:
            logger.error(f"生成推理失败: {e}")
            reasoning.append("技术分析异常")
        
        return reasoning
    
    async def generate_position_recommendation(self, symbol: str, funding_rate: float, 
                                             price_prediction: PricePrediction) -> Optional[PositionRecommendation]:
        """生成仓位建议"""
        try:
            current_price = price_prediction.current_price
            direction = price_prediction.direction
            confidence = price_prediction.confidence
            volatility = price_prediction.volatility_score
            
            # 基础仓位计算
            base_position = self.position_config['max_position_per_symbol']
            
            # 根据置信度和波动率调整仓位
            confidence_multiplier = confidence
            volatility_multiplier = max(0.3, 1 - volatility / 200)
            funding_multiplier = min(1.5, 1 + abs(funding_rate) * 10)
            
            recommended_position = base_position * confidence_multiplier * volatility_multiplier * funding_multiplier
            recommended_position = min(recommended_position, self.position_config['max_position_per_symbol'])
            
            # 确定操作方向
            if funding_rate < 0:  # 负费率，开多收费率
                if direction in [PriceDirection.STRONG_UP, PriceDirection.UP]:
                    action = "开多"
                    leverage = min(self.position_config['max_leverage'], 
                                 self.position_config['base_leverage'] * (1 + confidence))
                elif direction in [PriceDirection.STRONG_DOWN, PriceDirection.DOWN]:
                    action = "观望"
                    leverage = 1.0
                    recommended_position *= 0.3
                else:
                    action = "开多"
                    leverage = self.position_config['base_leverage']
            else:
                action = "观望"
                leverage = 1.0
                recommended_position = 0
            
            # 计算价格
            entry_price = current_price * 1.001 if action == "开多" else current_price
            stop_loss_price = min(price_prediction.support_level * 0.98, current_price * 0.97) if action == "开多" else current_price
            take_profit_price = max(price_prediction.resistance_level * 0.98, price_prediction.target_price_24h) if action == "开多" else current_price
            
            # 风险收益比
            if action == "开多" and stop_loss_price < entry_price:
                risk_per_unit = entry_price - stop_loss_price
                reward_per_unit = take_profit_price - entry_price
                risk_reward_ratio = reward_per_unit / risk_per_unit if risk_per_unit > 0 else 0
            else:
                risk_reward_ratio = 0
            
            # 最大损失
            max_loss_usdt = (entry_price - stop_loss_price) / entry_price * recommended_position * leverage if action == "开多" else 0
            
            # 预期收益
            expected_daily_income = abs(funding_rate * 3) * recommended_position * leverage
            if action == "开多" and direction in [PriceDirection.STRONG_UP, PriceDirection.UP]:
                price_gain = (price_prediction.target_price_24h - current_price) / current_price
                expected_daily_income += price_gain * recommended_position * leverage * confidence
            
            # 风险等级
            risk_level = self._assess_risk_level(volatility, confidence, leverage, max_loss_usdt)
            
            # 持仓周期
            holding_period = 1 if abs(funding_rate) > 0.01 else 3 if abs(funding_rate) > 0.005 else 7
            
            # 推理
            reasoning = f"负费率{funding_rate*100:.2f}%，{direction.value}，置信度{confidence:.1%}"
            
            return PositionRecommendation(
                symbol=symbol,
                recommended_action=action,
                position_size_usdt=recommended_position,
                leverage=leverage,
                entry_price=entry_price,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                risk_reward_ratio=risk_reward_ratio,
                max_loss_usdt=max_loss_usdt,
                expected_daily_income=expected_daily_income,
                holding_period_days=holding_period,
                risk_level=risk_level,
                confidence=confidence,
                reasoning=reasoning
            )
            
        except Exception as e:
            logger.error(f"生成仓位建议失败 {symbol}: {e}")
            return None
    
    def _assess_risk_level(self, volatility: float, confidence: float, 
                          leverage: float, max_loss_usdt: float) -> RiskLevel:
        """评估风险等级"""
        risk_score = 0
        
        # 波动率风险
        if volatility > 80:
            risk_score += 40
        elif volatility > 60:
            risk_score += 30
        elif volatility > 40:
            risk_score += 20
        else:
            risk_score += 10
        
        # 置信度风险
        risk_score += (1 - confidence) * 30
        
        # 杠杆风险
        if leverage > 4:
            risk_score += 30
        elif leverage > 2:
            risk_score += 20
        else:
            risk_score += 10
        
        # 最大损失风险
        if max_loss_usdt > 1000:
            risk_score += 20
        elif max_loss_usdt > 500:
            risk_score += 15
        else:
            risk_score += 5
        
        if risk_score >= 80:
            return RiskLevel.VERY_HIGH
        elif risk_score >= 65:
            return RiskLevel.HIGH
        elif risk_score >= 45:
            return RiskLevel.MEDIUM
        elif risk_score >= 25:
            return RiskLevel.LOW
        else:
            return RiskLevel.VERY_LOW
    
    async def analyze_enhanced_opportunities(self, opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """分析增强版机会（添加价格预测和仓位建议）"""
        enhanced_opportunities = []
        
        for opp in opportunities:
            try:
                symbol = opp['symbol']
                funding_rate = opp['funding_rate']
                
                logger.info(f"📊 增强分析 {symbol}...")
                
                # 价格预测
                price_prediction = await self.analyze_price_prediction(symbol)
                if not price_prediction:
                    logger.warning(f"无法获取 {symbol} 价格预测，跳过增强分析")
                    # 保留原始机会数据
                    enhanced_opp = opp.copy()
                    enhanced_opp.update({
                        'price_prediction': None,
                        'position_recommendation': None,
                        'enhanced_score': opp.get('score', 0),
                        'opportunity_type': '纯套利',
                        'urgency': '正常'
                    })
                    enhanced_opportunities.append(enhanced_opp)
                    continue
                
                # 仓位建议
                position_recommendation = await self.generate_position_recommendation(
                    symbol, funding_rate, price_prediction
                )
                
                # 计算增强评分
                enhanced_score = self._calculate_enhanced_score(opp, price_prediction, position_recommendation)
                
                # 确定机会类型
                if price_prediction.direction in [PriceDirection.STRONG_UP, PriceDirection.UP]:
                    opportunity_type = "趋势套利"
                elif price_prediction.direction in [PriceDirection.STRONG_DOWN, PriceDirection.DOWN]:
                    opportunity_type = "反转套利"
                else:
                    opportunity_type = "纯套利"
                
                # 确定紧急程度
                if enhanced_score > 85 and abs(funding_rate) > 0.01:
                    urgency = "立即"
                elif enhanced_score > 70:
                    urgency = "尽快"
                elif enhanced_score > 50:
                    urgency = "正常"
                else:
                    urgency = "观望"
                
                # 构建增强机会数据
                enhanced_opp = opp.copy()
                enhanced_opp.update({
                    'price_prediction': {
                        'direction': price_prediction.direction.value,
                        'confidence': price_prediction.confidence,
                        'target_price_24h': price_prediction.target_price_24h,
                        'current_price': price_prediction.current_price,
                        'support_level': price_prediction.support_level,
                        'resistance_level': price_prediction.resistance_level,
                        'volatility_score': price_prediction.volatility_score,
                        'reasoning': price_prediction.reasoning,
                        'use_kronos': price_prediction.use_kronos,
                        'kronos_signal': price_prediction.kronos_signal,
                        'kronos_confidence': price_prediction.kronos_confidence
                    } if price_prediction else None,
                    'position_recommendation': {
                        'recommended_action': position_recommendation.recommended_action,
                        'position_size_usdt': position_recommendation.position_size_usdt,
                        'leverage': position_recommendation.leverage,
                        'entry_price': position_recommendation.entry_price,
                        'stop_loss_price': position_recommendation.stop_loss_price,
                        'take_profit_price': position_recommendation.take_profit_price,
                        'risk_reward_ratio': position_recommendation.risk_reward_ratio,
                        'max_loss_usdt': position_recommendation.max_loss_usdt,
                        'expected_daily_income': position_recommendation.expected_daily_income,
                        'holding_period_days': position_recommendation.holding_period_days,
                        'risk_level': position_recommendation.risk_level.value,
                        'reasoning': position_recommendation.reasoning
                    } if position_recommendation else None,
                    'enhanced_score': enhanced_score,
                    'opportunity_type': opportunity_type,
                    'urgency': urgency
                })
                
                enhanced_opportunities.append(enhanced_opp)
                
            except Exception as e:
                logger.error(f"增强分析 {symbol} 失败: {e}")
                # 保留原始数据
                enhanced_opp = opp.copy()
                enhanced_opp.update({
                    'price_prediction': None,
                    'position_recommendation': None,
                    'enhanced_score': opp.get('score', 0),
                    'opportunity_type': '纯套利',
                    'urgency': '正常'
                })
                enhanced_opportunities.append(enhanced_opp)
        
        # 按增强评分重新排序
        enhanced_opportunities.sort(key=lambda x: x['enhanced_score'], reverse=True)
        
        return enhanced_opportunities
    
    def _calculate_enhanced_score(self, funding_opp: Dict[str, Any], 
                                price_prediction: Optional[PricePrediction], 
                                position_rec: Optional[PositionRecommendation]) -> float:
        """计算增强评分"""
        try:
            # 基础费率评分 (50%)
            base_score = funding_opp.get('score', 0) * 0.5
            
            # 价格预测评分 (30%)
            prediction_score = 0
            if price_prediction:
                prediction_score = price_prediction.confidence * 100
                if price_prediction.direction in [PriceDirection.STRONG_UP, PriceDirection.UP]:
                    prediction_score *= 1.2  # 看涨加分
                elif price_prediction.direction in [PriceDirection.STRONG_DOWN, PriceDirection.DOWN]:
                    prediction_score *= 0.6  # 看跌减分
                prediction_score = min(prediction_score, 100) * 0.3
            
            # 仓位建议评分 (20%)
            position_score = 0
            if position_rec:
                if position_rec.recommended_action == "开多":
                    position_score = 80
                    if position_rec.risk_reward_ratio > 3:
                        position_score += 20
                    elif position_rec.risk_reward_ratio > 2:
                        position_score += 10
                else:
                    position_score = 20
                position_score = position_score * 0.2
            
            total_score = base_score + prediction_score + position_score
            return min(total_score, 100)
            
        except Exception as e:
            logger.error(f"计算增强评分失败: {e}")
            return funding_opp.get('score', 0)
    
    def print_opportunities_summary(self, opportunities: List[Dict[str, Any]]):
        """打印机会摘要"""
        if not opportunities:
            print("📊 当前无负费率机会")
            return
        
        print(f"\n💰 负费率机会摘要 - 共 {len(opportunities)} 个")
        print("=" * 80)
        print(f"{'排名':<4} {'币种':<12} {'费率%':<10} {'日化%':<10} {'1万U日收益':<12} {'评级':<12}")
        print("=" * 80)
        
        for i, opp in enumerate(opportunities[:10], 1):  # 显示前10个
            symbol_name = opp['symbol'].replace('-USDT-SWAP', '')
            rate_pct = f"{opp['funding_rate_percent']:.3f}"
            daily_pct = f"{opp['daily_rate_percent']:.3f}"
            daily_income = f"${opp['daily_income_10k']:.2f}"
            rating = opp['rating']
            
            print(f"{i:<4} {symbol_name:<12} {rate_pct:<10} {daily_pct:<10} {daily_income:<12} {rating:<12}")
        
        # 显示最佳机会详情
        if opportunities:
            best = opportunities[0]
            print(f"\n🎯 最佳机会: {best['symbol'].replace('-USDT-SWAP', '')}")
            print(f"   费率: {best['funding_rate_percent']:.3f}%")
            print(f"   日化收益: {best['daily_rate_percent']:.3f}%")
            print(f"   年化收益: {best['annual_rate_percent']:.1f}%")
            print(f"   1万U日收益: ${best['daily_income_10k']:.2f}")
            print(f"   评分: {best['score']}/100")


# 独立运行函数
async def run_single_check():
    """运行单次检查"""
    monitor = NegativeFundingMonitorService()
    
    result = await monitor.run_monitoring_cycle()
    
    if result['success']:
        opportunities = result['opportunities']
        
        # 打印摘要
        monitor.print_opportunities_summary(opportunities)
        
        # 保存数据
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"negative_funding_check_{timestamp}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 数据已保存到: {filename}")
        
    else:
        print(f"❌ 监控失败: {result.get('error', '未知错误')}")


if __name__ == "__main__":
    asyncio.run(run_single_check())