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
        
        # 排除的大市值币种（波动太大，不适合吃利息）
        self.excluded_major_coins = {
            'BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'BNB-USDT-SWAP', 
            'SOL-USDT-SWAP', 'XRP-USDT-SWAP', 'ADA-USDT-SWAP',
            'DOGE-USDT-SWAP', 'AVAX-USDT-SWAP', 'DOT-USDT-SWAP',
            'MATIC-USDT-SWAP', 'LTC-USDT-SWAP', 'BCH-USDT-SWAP',
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
        """分析负费率机会"""
        opportunities = []
        
        # 获取负费率阈值配置
        negative_threshold = settings.strategy_config['funding_rate']['negative_threshold']
        
        for rate_data in funding_rates:
            symbol = rate_data['symbol']
            funding_rate = rate_data['funding_rate']
            
            # 只关注达到阈值的负费率（如 -0.1% 以下）
            if funding_rate >= 0 or funding_rate > negative_threshold:
                continue
            
            # 获取基础信息
            info = basic_info.get(symbol, {})
            
            # 获取实际的费率间隔
            funding_interval_hours = await self.get_funding_interval(symbol)
            funding_times_per_day = 24 // funding_interval_hours
            
            # 计算收益（使用实际的费率间隔）
            daily_rate = funding_rate * funding_times_per_day
            annual_rate = daily_rate * 365
            
            # 评估机会质量
            score = 0
            reasons = []
            
            # 费率评分
            if funding_rate < -0.01:  # 小于-1%
                score += 60
                reasons.append(f"极高负费率 {funding_rate*100:.3f}%")
            elif funding_rate < -0.005:  # 小于-0.5%
                score += 40
                reasons.append(f"高负费率 {funding_rate*100:.3f}%")
            elif funding_rate < -0.002:  # 小于-0.2%
                score += 25
                reasons.append(f"中等负费率 {funding_rate*100:.3f}%")
            elif funding_rate < -0.001:  # 小于-0.1%
                score += 15
                reasons.append(f"轻微负费率 {funding_rate*100:.3f}%")
            else:
                score += 5
                reasons.append(f"微小负费率 {funding_rate*100:.3f}%")
            
            # 交易量评分
            volume_24h = info.get('volume_24h', 0)
            if volume_24h > 10000000:  # 大于1000万USDT
                score += 20
                reasons.append("交易量充足")
            elif volume_24h > 1000000:  # 大于100万USDT
                score += 15
                reasons.append("交易量适中")
            elif volume_24h > 100000:  # 大于10万USDT
                score += 5
                reasons.append("交易量偏小")
            
            # 价格稳定性评分
            change_24h = abs(info.get('change_24h', 0))
            if change_24h < 0.03:  # 24小时涨跌幅小于3%
                score += 20
                reasons.append("价格稳定")
            elif change_24h < 0.05:  # 小于5%
                score += 10
                reasons.append("价格较稳定")
            elif change_24h < 0.10:  # 小于10%
                score += 5
                reasons.append("价格波动适中")
            
            # 综合评级
            if score >= 80:
                rating = "🟢 强烈推荐"
                priority = 1
            elif score >= 60:
                rating = "🟡 推荐"
                priority = 2
            elif score >= 40:
                rating = "🟠 可考虑"
                priority = 3
            elif score >= 20:
                rating = "🔵 关注"
                priority = 4
            else:
                rating = "🔴 不推荐"
                priority = 5
            
            opportunities.append({
                'symbol': symbol,
                'funding_rate': funding_rate,
                'funding_rate_percent': funding_rate * 100,
                'daily_rate_percent': abs(daily_rate * 100),
                'annual_rate_percent': abs(annual_rate * 100),
                'daily_income_10k': abs(daily_rate * 10000),  # 1万U日收益
                'funding_interval_hours': funding_interval_hours,
                'funding_times_per_day': funding_times_per_day,
                'price': info.get('price', 0),
                'volume_24h': volume_24h,
                'change_24h_percent': info.get('change_24h', 0) * 100,
                'score': score,
                'rating': rating,
                'priority': priority,
                'reasons': reasons,
                'next_funding_time': rate_data.get('next_funding_time', 0),
                'analysis_time': datetime.now().isoformat()
            })
        
        # 按优先级和评分排序
        opportunities.sort(key=lambda x: (x['priority'], -x['score'], x['funding_rate']))
        
        return opportunities
    
    def format_notification_message(self, opportunities: List[Dict[str, Any]]) -> str:
        """格式化通知消息"""
        if not opportunities:
            negative_threshold_pct = abs(settings.strategy_config['funding_rate']['negative_threshold'] * 100)
            return f"📊 当前无显著负费率机会（阈值: -{negative_threshold_pct:.1f}%）\n⏰ 下次检查: 1小时后"
        
        # 只推送前6个最佳机会
        top_opportunities = opportunities[:6]
        
        message = f"💰 负费率吃利息机会 ({len(opportunities)}个发现)\n"
        message += f"⏰ 检查时间: {datetime.now().strftime('%m-%d %H:%M')}\n"
        message += f"💡 费率收取: 间隔因币种而异 (通常4-8小时)\n\n"
        
        for i, opp in enumerate(top_opportunities, 1):
            symbol_name = opp['symbol'].replace('-USDT-SWAP', '')
            rate_pct = opp['funding_rate_percent']
            daily_pct = opp['daily_rate_percent']
            annual_pct = opp['annual_rate_percent']
            daily_income = opp['daily_income_10k']
            volume_m = opp['volume_24h'] / 1000000  # 转换为百万
            
            # 生成买入建议
            buy_recommendation = self._generate_buy_recommendation(opp)
            
            funding_interval = opp.get('funding_interval_hours', 8)
            
            message += f"{opp['rating']} {i}. {symbol_name}\n"
            message += f"   💰 费率: {rate_pct:.3f}% (每{funding_interval}小时收取)\n"
            message += f"   📈 日化: {daily_pct:.3f}% | 年化: {annual_pct:.1f}%\n"
            message += f"   💵 1万U日收益: ${daily_income:.2f}\n"
            
            if i <= 3:  # 前3个显示更多详细信息
                message += f"   📊 24H交易额: ${volume_m:.1f}M\n"
                message += f"   💲 当前价格: ${opp['price']:.4f}\n"
                message += f"   {buy_recommendation}\n"
            else:
                message += f"   {buy_recommendation}\n"
            
            message += "\n"
        
        # 添加最佳操作建议
        if opportunities:
            best = opportunities[0]
            symbol_name = best['symbol'].replace('-USDT-SWAP', '')
            best_recommendation = self._generate_detailed_recommendation(best)
            
            best_interval = best.get('funding_interval_hours', 8)
            best_times_per_day = best.get('funding_times_per_day', 3)
            
            message += f"🎯 最佳标的分析: {symbol_name}\n"
            message += f"   💰 预期日化: {best['daily_rate_percent']:.3f}%\n"
            message += f"   ⏰ 每{best_interval}小时收益: ${best['daily_income_10k']/best_times_per_day:.2f}\n"
            message += f"   📊 评分: {best['score']}/100\n"
            message += f"   {best_recommendation}\n\n"
        
        message += "📋 操作说明:\n"
        message += "   • 开仓方向: 做多 (Long)\n"
        message += "   • 建议杠杆: 1-2倍\n"
        message += "   • 收益方式: 每8小时自动结算到账户\n"
        message += "   • 风险控制: 设置3-5%止损\n\n"
        
        message += "⚠️ 重要提醒:\n"
        message += "   • 费率可能变化，密切关注\n"
        message += "   • 币价波动风险需考虑\n"
        message += "   • 建议分散投资，控制仓位\n\n"
        
        message += "🔄 下次检查: 1小时后"
        
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