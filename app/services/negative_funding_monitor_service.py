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
from typing import List, Dict, Any, Optional
import json
from decimal import Decimal

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.okx_service import OKXService
from app.services.notification_service import NotificationService
from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)
settings = get_settings()


class NegativeFundingMonitorService:
    """负费率监控服务 - 每小时监控并推送"""
    
    def __init__(self):
        self.okx_service = OKXService()
        self.notification_service = NotificationService()
        
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
        
        # 缓存的目标币种列表
        self.funding_intervals_cache = {}  # 缓存费率间隔信息
        self.target_symbols = []
    
    async def get_batch_funding_rates(self, symbols: List[str], batch_size: int = 10) -> List[Dict[str, Any]]:
        """批量获取费率数据，控制请求频率"""
        funding_rates = []
        
        print(f"📊 开始获取 {len(symbols)} 个币种的费率数据...")
        
        # 分批处理，避免API限制
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            batch_results = []
            
            for symbol in batch:
                try:
                    rate_data = await self.okx_service.get_funding_rate(symbol)
                    if rate_data:
                        batch_results.append(rate_data)
                    
                    # 每个请求间隔0.2秒
                    await asyncio.sleep(0.2)
                    
                except Exception as e:
                    logger.warning(f"获取{symbol}费率失败: {e}")
                    continue
            
            funding_rates.extend(batch_results)
            
            # 每批次间隔1秒
            if i + batch_size < len(symbols):
                print(f"   已获取 {i + batch_size}/{len(symbols)} 个币种...")
                await asyncio.sleep(1)
        
        print(f"✅ 成功获取 {len(funding_rates)} 个币种的费率数据")
        return funding_rates
    
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
                    change_24h = abs(float(ticker.get('chg', '0') or '0'))
                    
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
            
            print(f"📊 获取到交易量/涨幅前{len(top_symbols)}的币种")
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
        """检测负费率显著上升"""
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
            change_24h = abs(info.get('change_24h', 0))
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
                'change_24h_percent': info.get('change_24h', 0) * 100,
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
    
    def format_notification_message(self, opportunities: List[Dict[str, Any]]) -> str:
        """格式化通知消息 - 优化版本，更清晰的信息展示"""
        if not opportunities:
            negative_threshold_pct = abs(settings.strategy_config['funding_rate']['negative_threshold'] * 100)
            return f"📊 当前无显著负费率机会（阈值: -{negative_threshold_pct:.1f}%）\n⏰ 下次检查: 1小时后"
        
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
                
                message += "\n"
        
        # 如果有更多机会，显示统计信息
        remaining_count = total_count - len(top_opportunities)
        if remaining_count > 0:
            message += f"📋 其他机会: {remaining_count}个 (评分较低或风险较高)\n\n"
        
        # 添加操作建议
        message += "💡 操作建议:\n"
        message += "• 优先选择主流币种和高流动性标的\n"
        message += "• 关注价格稳定性，避免高波动币种\n"
        message += "• 建议分散投资，单币种不超过总资金20%\n"
        message += "• 密切监控费率变化，及时调整仓位\n\n"
        
        message += "⏰ 下次检查: 1小时后"
        
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
    
    async def run_monitoring_cycle(self) -> Dict[str, Any]:
        """运行一次监控周期"""
        try:
            print("🔍 开始负费率监控周期...")
            start_time = datetime.now()
            
            # 1. 获取热门币种（交易量或涨幅前50）
            suitable_symbols = await self.get_top_volume_symbols(limit=50)
            print(f"📋 获取 {len(suitable_symbols)} 个热门币种进行监控")
            
            # 2. 获取费率数据
            funding_rates = await self.get_batch_funding_rates(suitable_symbols, batch_size=8)
            
            if not funding_rates:
                return {'success': False, 'error': '未获取到费率数据'}
            
            # 3. 获取基础信息（只获取有负费率的币种）
            negative_symbols = [r['symbol'] for r in funding_rates if r['funding_rate'] < 0]
            basic_info = {}
            
            if negative_symbols:
                print(f"📊 获取 {len(negative_symbols)} 个负费率币种的基础信息...")
                for symbol in negative_symbols:
                    info = await self.get_symbol_basic_info(symbol)
                    basic_info[symbol] = info
                    await asyncio.sleep(0.1)  # 控制频率
            
            # 4. 分析负费率机会
            opportunities = await self.analyze_negative_funding_opportunities(funding_rates, basic_info)
            
            # 5. 生成通知消息
            notification_message = self.format_notification_message(opportunities)
            
            # 6. 发送通知（只有发现机会时才发送）
            if opportunities:
                try:
                    # 直接发送详细的负费率机会分析消息
                    results = await self.notification_service.send_notification(
                        notification_message,
                        priority="normal"
                    )
                    if any(results.values()):
                        print("✅ 负费率机会通知已发送")
                        logger.info(f"📱 推送消息内容:\n{'-'*80}\n{notification_message}\n{'-'*80}")
                    else:
                        print("⚠️ 通知发送失败")
                except Exception as e:
                    logger.error(f"发送通知失败: {e}")
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            result = {
                'success': True,
                'total_symbols_checked': len(suitable_symbols),
                'funding_rates_obtained': len(funding_rates),
                'negative_funding_count': len(opportunities),
                'opportunities': opportunities,
                'notification_message': notification_message,
                'analysis_time': start_time.isoformat(),
                'duration_seconds': duration
            }
            
            print(f"✅ 监控完成: 发现 {len(opportunities)} 个负费率机会 (耗时 {duration:.1f}秒)")
            return result
            
        except Exception as e:
            logger.error(f"监控周期执行失败: {e}")
            return {'success': False, 'error': str(e)}
    
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