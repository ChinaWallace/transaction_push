# -*- coding: utf-8 -*-
"""
核心机会服务
Core Opportunity Service - 统一管理网格交易机会、套利机会、强势信号等
整合Kronos市场机会扫描、网格交易分析、动量信号等功能
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.binance_service import BinanceService
# Lazy import to avoid circular imports
# from app.services.trading.core_trading_service import get_core_trading_service, AnalysisType
from app.services.notification.core_notification_service import get_core_notification_service
from app.services.ml.kronos_market_opportunity_service import KronosMarketOpportunityService
from app.services.analysis.position_analysis_service import PositionAnalysisService

logger = get_logger(__name__)
settings = get_settings()


class OpportunityType(Enum):
    """机会类型"""
    STRONG_SIGNAL = "strong_signal"          # 强势信号
    GRID_TRADING = "grid_trading"            # 网格交易
    TREND_REVERSAL = "trend_reversal"        # 趋势反转
    BREAKOUT = "breakout"                    # 突破信号
    ARBITRAGE = "arbitrage"                  # 套利机会
    MEAN_REVERSION = "mean_reversion"        # 均值回归


class OpportunityLevel(Enum):
    """机会等级"""
    PREMIUM = "premium"      # 顶级机会 - 必须推送
    HIGH = "high"           # 高质量机会
    MEDIUM = "medium"       # 中等机会
    LOW = "low"            # 低质量机会 - 不推送


@dataclass
class MarketOpportunity:
    """市场机会"""
    symbol: str
    opportunity_type: OpportunityType
    level: OpportunityLevel
    score: float
    
    # 基础信息
    title: str
    description: str
    reasoning: str
    
    # 交易参数
    entry_price: float
    stop_loss_price: float = 0
    take_profit_price: float = 0
    position_size_usdt: float = 1000
    leverage: float = 1
    
    # 收益预期
    expected_return_percent: float = 0
    risk_percent: float = 0
    risk_reward_ratio: float = 0
    win_probability: float = 0
    
    # 时效性
    urgency: str = "normal"  # immediate, urgent, normal, low
    valid_until: datetime = None
    
    # 技术指标
    technical_indicators: Dict[str, float] = None
    
    # Kronos数据
    kronos_confidence: float = 0
    kronos_signal: str = ""
    
    # 网格参数（如果是网格机会）
    grid_params: Dict[str, Any] = None
    
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.valid_until is None:
            self.valid_until = self.timestamp + timedelta(hours=4)
        if self.technical_indicators is None:
            self.technical_indicators = {}
        if self.grid_params is None:
            self.grid_params = {}


@dataclass
class OpportunityFilter:
    """机会过滤器"""
    min_score: float = 60.0
    min_level: OpportunityLevel = OpportunityLevel.MEDIUM
    opportunity_types: List[OpportunityType] = None
    symbols: List[str] = None
    min_expected_return: float = 5.0
    max_risk: float = 20.0
    min_risk_reward_ratio: float = 1.5


class CoreOpportunityService:
    """核心机会服务类 - 统一机会管理"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.binance_service = BinanceService()
        self.notification_service = None
        self.trading_service = None
        
        # 整合原有机会扫描服务
        self.kronos_opportunity_service = KronosMarketOpportunityService()
        self.position_service = PositionAnalysisService()
        
        # 机会配置
        self.opportunity_config = {
            'strong_signal': {
                'enabled': True,
                'scan_interval_minutes': 30,
                'min_confidence': 0.75,
                'max_notifications_per_day': 10
            },
            'grid_trading': {
                'enabled': True,
                'scan_interval_minutes': 120,
                'min_score': 60.0,
                'max_notifications_per_day': 3
            }
        }
        
        # 扫描历史和统计
        self.last_scan_times = {}
        self.daily_notification_counts = {}
        self.opportunity_history = []
        
        # 过滤器
        self.default_filter = OpportunityFilter()
    
    async def scan_all_opportunities(
        self,
        force_scan: bool = False,
        opportunity_filter: Optional[OpportunityFilter] = None
    ) -> Dict[str, Any]:
        """
        扫描所有类型的机会 - 主要入口
        
        Args:
            force_scan: 是否强制扫描
            opportunity_filter: 机会过滤器
            
        Returns:
            扫描结果
        """
        try:
            scan_start = datetime.now()
            self.logger.info("🎯 开始全面机会扫描...")
            
            # 使用默认过滤器
            if opportunity_filter is None:
                opportunity_filter = self.default_filter
            
            results = {
                'scan_start': scan_start,
                'scan_results': {},
                'total_opportunities': 0,
                'high_quality_opportunities': 0,
                'notifications_sent': 0,
                'status': 'success'
            }
            
            # 并行扫描各类机会
            scan_tasks = []
            
            # 强势信号扫描
            if self.opportunity_config['strong_signal']['enabled']:
                if self._should_scan('strong_signal', force_scan):
                    scan_tasks.append(self._scan_strong_signals(opportunity_filter))
            
            # 网格交易机会扫描已暂时禁用
            

            
            # 执行所有扫描任务
            if scan_tasks:
                scan_results = await asyncio.gather(*scan_tasks, return_exceptions=True)
                
                # 处理扫描结果
                for i, result in enumerate(scan_results):
                    if isinstance(result, Exception):
                        self.logger.error(f"扫描任务 {i} 失败: {result}")
                    elif result:
                        scan_type = result.get('type', f'scan_{i}')
                        results['scan_results'][scan_type] = result
                        results['total_opportunities'] += result.get('opportunities_found', 0)
                        results['notifications_sent'] += result.get('notifications_sent', 0)
            
            # 收集所有高质量机会
            all_opportunities = []
            for scan_result in results['scan_results'].values():
                opportunities = scan_result.get('opportunities', [])
                high_quality = [
                    opp for opp in opportunities 
                    if opp.level in [OpportunityLevel.PREMIUM, OpportunityLevel.HIGH]
                ]
                all_opportunities.extend(high_quality)
            
            results['high_quality_opportunities'] = len(all_opportunities)
            results['top_opportunities'] = sorted(
                all_opportunities, 
                key=lambda x: x.score, 
                reverse=True
            )[:10]
            
            # 记录扫描摘要
            scan_duration = (datetime.now() - scan_start).total_seconds()
            results['scan_duration_seconds'] = scan_duration
            
            self.logger.info(
                f"✅ 全面机会扫描完成: "
                f"发现 {results['total_opportunities']} 个机会, "
                f"高质量机会 {results['high_quality_opportunities']} 个, "
                f"发送通知 {results['notifications_sent']} 个 "
                f"(耗时 {scan_duration:.1f}秒)"
            )
            
            return results
            
        except Exception as e:
            self.logger.error(f"全面机会扫描失败: {e}")
            return {
                'scan_start': datetime.now(),
                'status': 'error',
                'error': str(e),
                'total_opportunities': 0,
                'notifications_sent': 0
            }
    
    def _should_scan(self, opportunity_type: str, force_scan: bool = False) -> bool:
        """检查是否应该扫描"""
        if force_scan:
            return True
        
        config = self.opportunity_config.get(opportunity_type, {})
        interval_minutes = config.get('scan_interval_minutes', 60)
        
        last_scan = self.last_scan_times.get(opportunity_type)
        if last_scan is None:
            return True
        
        time_since_last = datetime.now() - last_scan
        return time_since_last >= timedelta(minutes=interval_minutes)
    
    async def _scan_strong_signals(self, opportunity_filter: OpportunityFilter) -> Dict[str, Any]:
        """扫描强势信号机会"""
        try:
            self.logger.info("🚀 扫描强势信号机会...")
            
            # 使用Kronos机会服务扫描强势信号
            kronos_result = await self.kronos_opportunity_service.scan_strong_trading_opportunities(force_scan=True)
            
            if kronos_result.get('status') != 'success':
                return {
                    'type': 'strong_signal',
                    'status': 'error',
                    'error': kronos_result.get('message', '扫描失败'),
                    'opportunities_found': 0,
                    'notifications_sent': 0
                }
            
            # 转换为统一格式
            opportunities = []
            kronos_opportunities = kronos_result.get('strong_opportunities', [])
            
            for kronos_opp in kronos_opportunities:
                # 评估机会等级
                score = kronos_opp.opportunity_score
                level = self._determine_opportunity_level(score)
                
                if level == OpportunityLevel.LOW:
                    continue  # 跳过低质量机会
                
                opportunity = MarketOpportunity(
                    symbol=kronos_opp.symbol,
                    opportunity_type=OpportunityType.STRONG_SIGNAL,
                    level=level,
                    score=score,
                    title=f"🚀 强势信号 - {kronos_opp.symbol}",
                    description=kronos_opp.description,
                    reasoning=kronos_opp.reasoning,
                    entry_price=kronos_opp.entry_price,
                    stop_loss_price=kronos_opp.stop_loss_price,
                    take_profit_price=kronos_opp.take_profit_price,
                    position_size_usdt=kronos_opp.position_size_usdt,
                    leverage=kronos_opp.leverage,
                    expected_return_percent=kronos_opp.expected_profit_usdt / kronos_opp.position_size_usdt * 100,
                    risk_reward_ratio=kronos_opp.risk_reward_ratio,
                    win_probability=kronos_opp.win_probability,
                    urgency=kronos_opp.urgency,
                    kronos_confidence=getattr(kronos_opp, 'kronos_confidence', 0),
                    kronos_signal=getattr(kronos_opp, 'kronos_signal', '')
                )
                
                # 应用过滤器
                if self._passes_filter(opportunity, opportunity_filter):
                    opportunities.append(opportunity)
            
            # 发送通知
            notifications_sent = 0
            if opportunities and self._can_send_notification('strong_signal'):
                notifications_sent = await self._send_opportunities_notification(
                    opportunities, OpportunityType.STRONG_SIGNAL
                )
            
            # 更新扫描时间
            self.last_scan_times['strong_signal'] = datetime.now()
            
            return {
                'type': 'strong_signal',
                'status': 'success',
                'opportunities_found': len(opportunities),
                'notifications_sent': notifications_sent,
                'opportunities': opportunities,
                'symbols_scanned': kronos_result.get('symbols_scanned', 0)
            }
            
        except Exception as e:
            self.logger.error(f"强势信号扫描失败: {e}")
            return {
                'type': 'strong_signal',
                'status': 'error',
                'error': str(e),
                'opportunities_found': 0,
                'notifications_sent': 0
            }
    
    async def _scan_grid_opportunities(self, opportunity_filter: OpportunityFilter) -> Dict[str, Any]:
        """扫描网格交易机会"""
        try:
            self.logger.info("🎯 扫描网格交易机会...")
            
            # 使用Kronos机会服务扫描网格机会
            kronos_result = await self.kronos_opportunity_service.scan_grid_trading_opportunities(force_scan=True)
            
            if kronos_result.get('status') != 'success':
                return {
                    'type': 'grid_trading',
                    'status': 'error',
                    'error': kronos_result.get('message', '扫描失败'),
                    'opportunities_found': 0,
                    'notifications_sent': 0
                }
            
            # 转换为统一格式
            opportunities = []
            grid_opportunities = kronos_result.get('grid_opportunities', [])
            
            for grid_opp in grid_opportunities:
                score = grid_opp.opportunity_score
                level = self._determine_opportunity_level(score)
                
                if level == OpportunityLevel.LOW:
                    continue
                
                # 计算网格参数
                grid_params = self._calculate_grid_parameters(grid_opp)
                
                opportunity = MarketOpportunity(
                    symbol=grid_opp.symbol,
                    opportunity_type=OpportunityType.GRID_TRADING,
                    level=level,
                    score=score,
                    title=f"🎯 网格交易 - {grid_opp.symbol}",
                    description=f"网格交易机会，评分: {score:.0f}",
                    reasoning=grid_opp.reasoning,
                    entry_price=grid_opp.entry_price,
                    position_size_usdt=grid_opp.position_size_usdt,
                    expected_return_percent=grid_opp.expected_profit_usdt / grid_opp.position_size_usdt * 100,
                    risk_reward_ratio=grid_opp.risk_reward_ratio,
                    urgency="normal",
                    grid_params=grid_params
                )
                
                # 应用过滤器
                if self._passes_filter(opportunity, opportunity_filter):
                    opportunities.append(opportunity)
            
            # 发送通知
            notifications_sent = 0
            if opportunities and self._can_send_notification('grid_trading'):
                notifications_sent = await self._send_opportunities_notification(
                    opportunities, OpportunityType.GRID_TRADING
                )
            
            # 更新扫描时间
            self.last_scan_times['grid_trading'] = datetime.now()
            
            return {
                'type': 'grid_trading',
                'status': 'success',
                'opportunities_found': len(opportunities),
                'notifications_sent': notifications_sent,
                'opportunities': opportunities,
                'symbols_scanned': kronos_result.get('symbols_scanned', 0)
            }
            
        except Exception as e:
            self.logger.error(f"网格交易机会扫描失败: {e}")
            return {
                'type': 'grid_trading',
                'status': 'error',
                'error': str(e),
                'opportunities_found': 0,
                'notifications_sent': 0
            }
    
    async def _scan_momentum_opportunities(self, opportunity_filter: OpportunityFilter) -> Dict[str, Any]:
        """扫描动量机会"""
        try:
            self.logger.info("📈 扫描动量机会...")
            
            # 获取核心交易服务 (lazy import)
            if not self.trading_service:
                from app.services.trading.core_trading_service import get_core_trading_service
                self.trading_service = await get_core_trading_service()
            
            # 获取活跃交易对
            symbols = await self._get_active_symbols()
            if not symbols:
                return {
                    'type': 'momentum',
                    'status': 'error',
                    'error': '无法获取交易对',
                    'opportunities_found': 0,
                    'notifications_sent': 0
                }
            
            # 选择成交量大的前20个交易对进行分析
            top_symbols = symbols[:20]
            
            # 批量分析动量信号 (lazy import)
            from app.services.trading.core_trading_service import AnalysisType
            signals = await self.trading_service.batch_analyze_symbols(
                top_symbols, 
                AnalysisType.INTEGRATED,
                max_concurrent=5
            )
            
            # 筛选动量机会
            opportunities = []
            for symbol, signal in signals.items():
                if not signal:
                    continue
                
                # 检查是否为动量机会
                if self._is_momentum_opportunity(signal):
                    score = signal.final_confidence * 100
                    level = self._determine_opportunity_level(score)
                    
                    if level == OpportunityLevel.LOW:
                        continue
                    
                    opportunity = MarketOpportunity(
                        symbol=symbol,
                        opportunity_type=OpportunityType.MOMENTUM,
                        level=level,
                        score=score,
                        title=f"📈 动量机会 - {symbol}",
                        description=f"动量突破信号，置信度: {signal.final_confidence:.1%}",
                        reasoning=signal.reasoning,
                        entry_price=signal.entry_price,
                        stop_loss_price=signal.stop_loss_price,
                        take_profit_price=signal.take_profit_price,
                        position_size_usdt=signal.position_size_usdt,
                        leverage=signal.leverage,
                        expected_return_percent=((signal.take_profit_price - signal.entry_price) / signal.entry_price) * 100,
                        risk_reward_ratio=signal.risk_reward_ratio,
                        urgency=signal.urgency,
                        kronos_confidence=signal.kronos_result.final_confidence if signal.kronos_result else 0
                    )
                    
                    # 应用过滤器
                    if self._passes_filter(opportunity, opportunity_filter):
                        opportunities.append(opportunity)
            
            # 发送通知
            notifications_sent = 0
            if opportunities and self._can_send_notification('momentum'):
                notifications_sent = await self._send_opportunities_notification(
                    opportunities, OpportunityType.MOMENTUM
                )
            
            # 更新扫描时间
            self.last_scan_times['momentum'] = datetime.now()
            
            return {
                'type': 'momentum',
                'status': 'success',
                'opportunities_found': len(opportunities),
                'notifications_sent': notifications_sent,
                'opportunities': opportunities,
                'symbols_scanned': len(top_symbols)
            }
            
        except Exception as e:
            self.logger.error(f"动量机会扫描失败: {e}")
            return {
                'type': 'momentum',
                'status': 'error',
                'error': str(e),
                'opportunities_found': 0,
                'notifications_sent': 0
            }
    
    def _determine_opportunity_level(self, score: float) -> OpportunityLevel:
        """确定机会等级"""
        if score >= 90:
            return OpportunityLevel.PREMIUM
        elif score >= 75:
            return OpportunityLevel.HIGH
        elif score >= 60:
            return OpportunityLevel.MEDIUM
        else:
            return OpportunityLevel.LOW
    
    def _passes_filter(self, opportunity: MarketOpportunity, filter: OpportunityFilter) -> bool:
        """检查机会是否通过过滤器"""
        if opportunity.score < filter.min_score:
            return False
        
        if opportunity.level.value < filter.min_level.value:
            return False
        
        if filter.opportunity_types and opportunity.opportunity_type not in filter.opportunity_types:
            return False
        
        if filter.symbols and opportunity.symbol not in filter.symbols:
            return False
        
        if opportunity.expected_return_percent < filter.min_expected_return:
            return False
        
        if opportunity.risk_percent > filter.max_risk:
            return False
        
        if opportunity.risk_reward_ratio < filter.min_risk_reward_ratio:
            return False
        
        return True
    
    def _is_momentum_opportunity(self, signal) -> bool:
        """判断是否为动量机会"""
        # 检查信号强度和动作
        if signal.signal_strength.value in ['strong', 'very_strong']:
            if signal.final_action.lower() in ['buy', 'strong_buy', '买入', '强烈买入']:
                return True
        
        # 检查Kronos信号
        if signal.kronos_result:
            if signal.kronos_result.final_confidence > 0.7:
                return True
        
        return False
    
    def _calculate_grid_parameters(self, grid_opp) -> Dict[str, Any]:
        """计算网格交易参数"""
        return {
            'grid_num': getattr(grid_opp, 'grid_num', 20),
            'price_range_percent': getattr(grid_opp, 'price_range_percent', 10),
            'grid_spacing': getattr(grid_opp, 'grid_spacing', 0.5),
            'investment_per_grid': getattr(grid_opp, 'investment_per_grid', 50),
            'total_investment': getattr(grid_opp, 'total_investment', 1000)
        }
    
    async def _get_active_symbols(self) -> List[str]:
        """获取活跃交易对"""
        try:
            async with self.binance_service as exchange:
                instruments = await exchange.get_raw_instruments('SWAP')
            
            if instruments:
                # 按成交量排序，返回活跃的交易对
                active_symbols = [
                    f"{inst['baseAsset']}-USDT-SWAP" for inst in instruments
                    if inst.get('status') == 'TRADING' and inst.get('quoteAsset') == 'USDT'
                ]
                return active_symbols[:50]  # 返回前50个
            
            return []
            
        except Exception as e:
            self.logger.error(f"获取活跃交易对失败: {e}")
            return []
    
    def _can_send_notification(self, opportunity_type: str) -> bool:
        """检查是否可以发送通知"""
        config = self.opportunity_config.get(opportunity_type, {})
        max_per_day = config.get('max_notifications_per_day', 10)
        
        today = datetime.now().date()
        
        if opportunity_type not in self.daily_notification_counts:
            self.daily_notification_counts[opportunity_type] = {
                'date': today,
                'count': 0
            }
        
        daily_count = self.daily_notification_counts[opportunity_type]
        
        # 检查日期和计数
        if daily_count['date'] != today:
            daily_count['date'] = today
            daily_count['count'] = 0
        
        return daily_count['count'] < max_per_day
    
    async def _send_opportunities_notification(
        self,
        opportunities: List[MarketOpportunity],
        opportunity_type: OpportunityType
    ) -> int:
        """发送机会通知"""
        try:
            if not self.notification_service:
                self.notification_service = await get_core_notification_service()
            
            # 根据机会类型选择通知方法
            if opportunity_type == OpportunityType.STRONG_SIGNAL:
                # 强势信号 - 分别发送
                notifications_sent = 0
                for opportunity in opportunities[:3]:  # 最多发送前3个
                    signal_data = self._convert_to_signal_data(opportunity)
                    success = await self.notification_service.send_trading_signal(signal_data)
                    if success:
                        notifications_sent += 1
                
            elif opportunity_type == OpportunityType.GRID_TRADING:
                # 网格机会 - 批量发送
                grid_data = {
                    'opportunities': [
                        self._convert_to_grid_data(opp) for opp in opportunities
                    ],
                    'total_opportunities': len(opportunities)
                }
                success = await self.notification_service.send_grid_opportunity(grid_data)
                notifications_sent = 1 if success else 0
                
            else:
                # 其他类型 - 作为交易信号发送
                notifications_sent = 0
                for opportunity in opportunities[:2]:  # 最多发送前2个
                    signal_data = self._convert_to_signal_data(opportunity)
                    success = await self.notification_service.send_trading_signal(signal_data)
                    if success:
                        notifications_sent += 1
            
            # 更新发送计数
            if notifications_sent > 0:
                today = datetime.now().date()
                opportunity_type_str = opportunity_type.value
                
                if opportunity_type_str not in self.daily_notification_counts:
                    self.daily_notification_counts[opportunity_type_str] = {
                        'date': today,
                        'count': 0
                    }
                
                self.daily_notification_counts[opportunity_type_str]['count'] += notifications_sent
                
                self.logger.info(f"✅ {opportunity_type.value}机会通知发送成功: {notifications_sent}个")
            
            return notifications_sent
            
        except Exception as e:
            self.logger.error(f"发送机会通知失败: {e}")
            return 0
    
    def _convert_to_signal_data(self, opportunity: MarketOpportunity) -> Dict[str, Any]:
        """转换为信号数据"""
        return {
            'symbol': opportunity.symbol,
            'action': '买入' if opportunity.expected_return_percent > 0 else '观望',
            'confidence': opportunity.score / 100,
            'current_price': opportunity.entry_price,
            'stop_loss': opportunity.stop_loss_price,
            'take_profit': opportunity.take_profit_price,
            'reasoning': opportunity.reasoning,
            'key_factors': [opportunity.title, f"评分: {opportunity.score:.0f}"],
            'urgency': opportunity.urgency,
            'timestamp': opportunity.timestamp,
            'opportunity_type': opportunity.opportunity_type.value
        }
    
    def _convert_to_grid_data(self, opportunity: MarketOpportunity) -> Dict[str, Any]:
        """转换为网格数据"""
        return {
            'symbol': opportunity.symbol,
            'score': opportunity.score,
            'entry_price': opportunity.entry_price,
            'expected_return': opportunity.expected_return_percent,
            'grid_params': opportunity.grid_params,
            'reasoning': opportunity.reasoning
        }
    
    async def get_opportunity_summary(self) -> Dict[str, Any]:
        """获取机会摘要"""
        try:
            now = datetime.now()
            today = now.date()
            
            summary = {
                'timestamp': now,
                'scan_status': {},
                'daily_statistics': {},
                'recent_opportunities': [],
                'total_opportunities_today': 0
            }
            
            # 检查扫描状态
            for opp_type, config in self.opportunity_config.items():
                if config.get('enabled'):
                    last_scan = self.last_scan_times.get(opp_type)
                    interval_minutes = config.get('scan_interval_minutes', 60)
                    
                    if last_scan:
                        time_since_last = (now - last_scan).total_seconds() / 60
                        status = 'normal' if time_since_last < interval_minutes * 2 else 'delayed'
                    else:
                        status = 'not_started'
                    
                    summary['scan_status'][opp_type] = {
                        'status': status,
                        'last_scan': last_scan,
                        'interval_minutes': interval_minutes
                    }
            
            # 统计今日通知数量
            total_notifications = 0
            for opp_type, count_data in self.daily_notification_counts.items():
                if count_data.get('date') == today:
                    count = count_data['count']
                    summary['daily_statistics'][opp_type] = count
                    total_notifications += count
            
            summary['total_opportunities_today'] = total_notifications
            
            # 获取最近的机会
            recent_opportunities = [
                opp for opp in self.opportunity_history[-10:]
                if opp.timestamp.date() == today
            ]
            
            summary['recent_opportunities'] = [
                {
                    'symbol': opp.symbol,
                    'type': opp.opportunity_type.value,
                    'level': opp.level.value,
                    'score': opp.score,
                    'timestamp': opp.timestamp
                }
                for opp in recent_opportunities
            ]
            
            return summary
            
        except Exception as e:
            self.logger.error(f"获取机会摘要失败: {e}")
            return {
                'timestamp': datetime.now(),
                'status': 'error',
                'error': str(e)
            }


# 全局服务实例
_core_opportunity_service = None


async def get_core_opportunity_service() -> CoreOpportunityService:
    """获取核心机会服务实例"""
    global _core_opportunity_service
    if _core_opportunity_service is None:
        _core_opportunity_service = CoreOpportunityService()
    return _core_opportunity_service
