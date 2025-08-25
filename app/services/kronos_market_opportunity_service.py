# -*- coding: utf-8 -*-
"""
Kronos市场机会扫描服务
专门使用Kronos AI扫描和推送强交易机会，包括网格交易机会分析
"""

import asyncio
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger, trading_logger
from app.services.kronos_integrated_decision_service import get_kronos_integrated_service, KronosEnhancedDecision
from app.services.kronos_notification_service import get_kronos_notification_service
from app.services.okx_service import OKXService
from app.services.notification_service import NotificationService
from app.utils.exceptions import TradingToolError


class OpportunityType(Enum):
    """机会类型"""
    STRONG_SIGNAL = "强交易信号"
    GRID_TRADING = "网格交易"
    TREND_REVERSAL = "趋势反转"
    BREAKOUT = "突破信号"
    ARBITRAGE = "套利机会"


@dataclass
class KronosMarketOpportunity:
    """Kronos市场机会"""
    symbol: str
    opportunity_type: OpportunityType
    direction: str  # "看涨", "看跌", "震荡"
    confidence: float
    kronos_confidence: float
    
    # 价格信息
    current_price: float
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    
    # 机会评分
    opportunity_score: float = 0.0
    risk_score: float = 0.0
    
    # 推荐参数
    position_size: float = 0.1
    leverage: float = 1.0
    
    # 分析依据
    reasoning: str = ""
    key_factors: List[str] = None
    
    # 时效性
    urgency: str = "medium"  # "high", "medium", "low"
    valid_until: datetime = None
    
    # 网格交易专用
    grid_upper: Optional[float] = None
    grid_lower: Optional[float] = None
    grid_count: Optional[int] = None
    
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.key_factors is None:
            self.key_factors = []
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.valid_until is None:
            self.valid_until = self.timestamp + timedelta(hours=4)


class KronosMarketOpportunityService:
    """Kronos市场机会扫描服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.okx_service = OKXService()
        self.notification_service = NotificationService()
        
        # 扫描配置
        self.scan_config = self.settings.kronos_config.get('market_scan_config', {})
        self.enable_scan = self.scan_config.get('enable_market_scan', True)
        self.strong_signal_threshold = self.scan_config.get('strong_signal_threshold', 0.7)
        self.grid_opportunity_threshold = self.scan_config.get('grid_opportunity_threshold', 0.6)
        
        # 最后扫描时间记录
        self.last_scan_time = {}
        self.scan_intervals = {
            'strong_signal': timedelta(minutes=30),  # 强信号30分钟扫描一次
            'grid_trading': timedelta(hours=2),      # 网格机会2小时扫描一次
        }
    
    async def scan_strong_trading_opportunities(self, force_scan: bool = False) -> Dict[str, Any]:
        """
        扫描强交易机会 - 只推送Kronos强信号，不推送传统分析
        
        Args:
            force_scan: 是否强制扫描
            
        Returns:
            扫描结果
        """
        try:
            if not self.enable_scan:
                return {"status": "disabled", "message": "Kronos市场扫描已禁用"}
            
            # 检查扫描间隔
            if not force_scan and not self._should_scan('strong_signal'):
                return {"status": "skipped", "message": "未到扫描时间"}
            
            self.logger.info("🤖 开始Kronos强交易机会扫描...")
            
            # 获取要扫描的交易对
            symbols = await self._get_scan_symbols()
            
            # 使用Kronos集成服务进行分析
            kronos_service = await get_kronos_integrated_service()
            results = await kronos_service.batch_analyze_symbols(symbols, force_update=True)
            
            # 筛选强信号机会
            strong_opportunities = []
            for symbol, decision in results.items():
                if decision and self._is_strong_opportunity(decision):
                    opportunity = await self._convert_to_opportunity(decision, OpportunityType.STRONG_SIGNAL)
                    if opportunity:
                        strong_opportunities.append(opportunity)
            
            # 按机会评分排序
            strong_opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)
            
            # 发送通知
            notification_count = 0
            if strong_opportunities:
                notification_count = await self._send_strong_opportunities_notification(
                    strong_opportunities[:5]  # 最多推送前5个
                )
            
            # 更新扫描时间
            self.last_scan_time['strong_signal'] = datetime.now()
            
            result = {
                "status": "success",
                "scan_time": datetime.now(),
                "symbols_scanned": len(symbols),
                "opportunities_found": len(strong_opportunities),
                "notifications_sent": notification_count,
                "top_opportunities": [self._format_opportunity_summary(op) for op in strong_opportunities[:3]]
            }
            
            self.logger.info(f"✅ Kronos强交易机会扫描完成: 发现 {len(strong_opportunities)} 个机会")
            return result
            
        except Exception as e:
            self.logger.error(f"Kronos强交易机会扫描失败: {e}")
            return {"status": "error", "error": str(e)}
    
    async def scan_grid_trading_opportunities(self, force_scan: bool = False) -> Dict[str, Any]:
        """
        扫描网格交易机会 - 获取交易量前50的币种用Kronos分析网格潜力
        
        Args:
            force_scan: 是否强制扫描
            
        Returns:
            扫描结果
        """
        try:
            if not self.enable_scan:
                return {"status": "disabled", "message": "网格交易扫描已禁用"}
            
            # 检查扫描间隔
            if not force_scan and not self._should_scan('grid_trading'):
                return {"status": "skipped", "message": "未到扫描时间"}
            
            self.logger.info("🎯 开始Kronos网格交易机会扫描...")
            
            # 获取交易量前50的币种
            top_volume_symbols = await self._get_top_volume_symbols(50)
            
            if not top_volume_symbols:
                return {"status": "error", "message": "无法获取交易量数据"}
            
            # 使用Kronos分析网格交易潜力
            grid_opportunities = []
            kronos_service = await get_kronos_integrated_service()
            
            # 批量分析（分批处理避免过载）
            batch_size = 10
            for i in range(0, len(top_volume_symbols), batch_size):
                batch_symbols = top_volume_symbols[i:i + batch_size]
                batch_results = await kronos_service.batch_analyze_symbols(batch_symbols, force_update=True)
                
                for symbol, decision in batch_results.items():
                    if decision:
                        grid_opportunity = await self._analyze_grid_potential(symbol, decision)
                        if grid_opportunity and grid_opportunity.opportunity_score >= 60:  # 60分以上才推荐
                            grid_opportunities.append(grid_opportunity)
                
                # 避免API限制，批次间稍作延迟
                await asyncio.sleep(1)
            
            # 按网格适合度排序
            grid_opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)
            
            # 发送网格机会通知
            notification_count = 0
            if grid_opportunities:
                notification_count = await self._send_grid_opportunities_notification(
                    grid_opportunities[:10]  # 最多推送前10个
                )
            
            # 更新扫描时间
            self.last_scan_time['grid_trading'] = datetime.now()
            
            result = {
                "status": "success",
                "scan_time": datetime.now(),
                "symbols_scanned": len(top_volume_symbols),
                "grid_opportunities": len(grid_opportunities),
                "notifications_sent": notification_count,
                "top_grid_opportunities": [self._format_opportunity_summary(op) for op in grid_opportunities[:5]]
            }
            
            self.logger.info(f"✅ Kronos网格交易扫描完成: 发现 {len(grid_opportunities)} 个网格机会")
            return result
            
        except Exception as e:
            self.logger.error(f"Kronos网格交易扫描失败: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _get_scan_symbols(self) -> List[str]:
        """获取要扫描的交易对列表"""
        # 主流币种 + 热门币种
        main_symbols = [
            "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP",
            "DOGE-USDT-SWAP", "XRP-USDT-SWAP", "ADA-USDT-SWAP",
            "AVAX-USDT-SWAP", "DOT-USDT-SWAP", "LINK-USDT-SWAP",
            "UNI-USDT-SWAP", "LTC-USDT-SWAP", "BCH-USDT-SWAP",
            "ATOM-USDT-SWAP"
        ]
        
        return main_symbols
    
    async def _get_top_volume_symbols(self, limit: int = 50) -> List[str]:
        """获取交易量前N的币种"""
        try:
            # 获取所有永续合约的24小时交易量数据
            async with self.okx_service as okx:
                tickers = await okx.get_all_tickers("SWAP")
                
                if not tickers:
                    return []
                
                # 筛选USDT永续合约并按交易量排序
                usdt_swaps = []
                for ticker in tickers:
                    if ticker.get('instId', '').endswith('-USDT-SWAP'):
                        volume_24h = float(ticker.get('vol24h', 0))
                        if volume_24h > 0:
                            usdt_swaps.append({
                                'symbol': ticker['instId'],
                                'volume_24h': volume_24h,
                                'turnover_24h': float(ticker.get('volCcy24h', 0))
                            })
                
                # 按交易量排序
                usdt_swaps.sort(key=lambda x: x['volume_24h'], reverse=True)
                
                # 返回前N个交易对
                top_symbols = [item['symbol'] for item in usdt_swaps[:limit]]
                
                self.logger.info(f"获取交易量前{limit}币种: {len(top_symbols)}个")
                return top_symbols
                
        except Exception as e:
            self.logger.error(f"获取交易量排行失败: {e}")
            return []
    
    def _is_strong_opportunity(self, decision: KronosEnhancedDecision) -> bool:
        """判断是否为强交易机会"""
        # 过滤掉"持有观望"信号
        if decision.final_action in ["持有观望", "观望", "持有"]:
            return False
        
        # Kronos置信度要求
        if decision.kronos_confidence < self.strong_signal_threshold:
            return False
        
        # 信号一致性要求
        if decision.signal_confluence < 0.6:
            return False
        
        # 强信号强度要求
        strong_strengths = ["强", "极强"]
        if decision.kronos_signal_strength.value not in strong_strengths:
            return False
        
        return True
    
    async def _convert_to_opportunity(
        self, 
        decision: KronosEnhancedDecision, 
        opp_type: OpportunityType
    ) -> Optional[KronosMarketOpportunity]:
        """将Kronos决策转换为市场机会"""
        try:
            # 获取当前价格
            current_price = await self.okx_service.get_current_price(decision.symbol)
            if not current_price:
                return None
            
            # 确定方向
            direction = self._determine_direction(decision)
            
            # 计算机会评分
            opportunity_score = self._calculate_opportunity_score(decision)
            
            # 计算风险评分
            risk_score = self._calculate_risk_score(decision)
            
            # 提取关键因素
            key_factors = self._extract_key_factors(decision)
            
            # 生成推理说明
            reasoning = self._generate_reasoning(decision, direction)
            
            return KronosMarketOpportunity(
                symbol=decision.symbol,
                opportunity_type=opp_type,
                direction=direction,
                confidence=decision.final_confidence,
                kronos_confidence=decision.kronos_confidence,
                current_price=current_price,
                target_price=decision.take_profit,
                stop_loss=decision.stop_loss,
                opportunity_score=opportunity_score,
                risk_score=risk_score,
                position_size=decision.position_size,
                reasoning=reasoning,
                key_factors=key_factors,
                urgency=self._determine_urgency(decision),
                timestamp=decision.timestamp
            )
            
        except Exception as e:
            self.logger.error(f"转换机会失败 {decision.symbol}: {e}")
            return None
    
    async def _analyze_grid_potential(
        self, 
        symbol: str, 
        decision: KronosEnhancedDecision
    ) -> Optional[KronosMarketOpportunity]:
        """分析网格交易潜力"""
        try:
            # 获取历史数据分析波动性
            async with self.okx_service as okx:
                kline_data = await okx.get_kline_data(symbol, "1H", 168)  # 7天小时线
                
                if not kline_data or len(kline_data) < 100:
                    return None
                
                # 计算波动性指标
                prices = [float(k['close']) for k in kline_data]
                df = pd.DataFrame({'close': prices})
                
                # 计算波动率
                returns = df['close'].pct_change().dropna()
                volatility = returns.std() * (24 ** 0.5)  # 日化波动率
                
                # 计算价格区间
                recent_high = df['close'].tail(48).max()  # 近48小时最高
                recent_low = df['close'].tail(48).min()   # 近48小时最低
                current_price = prices[-1]
                
                # 网格适合度评分
                grid_score = self._calculate_grid_score(
                    volatility, decision, recent_high, recent_low, current_price
                )
                
                if grid_score < 60:  # 低于60分不推荐
                    return None
                
                # 计算网格参数
                grid_upper = recent_high * 1.02  # 上轨加2%缓冲
                grid_lower = recent_low * 0.98   # 下轨减2%缓冲
                grid_count = min(20, max(10, int((grid_upper - grid_lower) / current_price * 100)))
                
                # 确定方向（网格交易通常是震荡）
                if volatility > 0.03 and abs(decision.kronos_prediction.price_change_pct) < 0.05:
                    direction = "震荡"
                elif decision.kronos_prediction.price_change_pct > 0:
                    direction = "偏多震荡"
                else:
                    direction = "偏空震荡"
                
                return KronosMarketOpportunity(
                    symbol=symbol,
                    opportunity_type=OpportunityType.GRID_TRADING,
                    direction=direction,
                    confidence=decision.final_confidence,
                    kronos_confidence=decision.kronos_confidence,
                    current_price=current_price,
                    opportunity_score=grid_score,
                    risk_score=min(80, volatility * 1000),  # 波动率转风险评分
                    grid_upper=grid_upper,
                    grid_lower=grid_lower,
                    grid_count=grid_count,
                    reasoning=f"波动率{volatility:.2%}，适合网格交易。Kronos预测{direction}，建议{grid_count}格网格策略。",
                    key_factors=[
                        f"日化波动率: {volatility:.2%}",
                        f"价格区间: {grid_lower:.4f} - {grid_upper:.4f}",
                        f"Kronos置信度: {decision.kronos_confidence:.2f}",
                        f"网格数量: {grid_count}格"
                    ],
                    urgency="low"  # 网格交易不急
                )
                
        except Exception as e:
            self.logger.error(f"分析网格潜力失败 {symbol}: {e}")
            return None
    
    def _calculate_grid_score(
        self, 
        volatility: float, 
        decision: KronosEnhancedDecision, 
        high: float, 
        low: float, 
        current: float
    ) -> float:
        """计算网格交易适合度评分"""
        score = 0
        
        # 波动率评分 (40分)
        if 0.02 <= volatility <= 0.06:  # 2%-6%日波动率最适合
            score += 40
        elif 0.015 <= volatility <= 0.08:
            score += 30
        elif volatility > 0.01:
            score += 20
        
        # 价格位置评分 (25分)
        price_position = (current - low) / (high - low) if high > low else 0.5
        if 0.3 <= price_position <= 0.7:  # 中间位置最好
            score += 25
        elif 0.2 <= price_position <= 0.8:
            score += 20
        else:
            score += 10
        
        # Kronos预测稳定性 (20分)
        if decision.kronos_prediction:
            predicted_change = abs(decision.kronos_prediction.price_change_pct)
            if predicted_change < 0.03:  # 预测变化小于3%
                score += 20
            elif predicted_change < 0.05:
                score += 15
            else:
                score += 5
        
        # 信号一致性 (15分)
        if decision.signal_confluence > 0.7:
            score += 15
        elif decision.signal_confluence > 0.5:
            score += 10
        else:
            score += 5
        
        return min(100, score)
    
    def _determine_direction(self, decision: KronosEnhancedDecision) -> str:
        """确定交易方向"""
        if "买入" in decision.final_action or "做多" in decision.final_action:
            return "看涨"
        elif "卖出" in decision.final_action or "做空" in decision.final_action:
            return "看跌"
        else:
            return "震荡"
    
    def _calculate_opportunity_score(self, decision: KronosEnhancedDecision) -> float:
        """计算机会评分"""
        score = 0
        
        # Kronos置信度 (40分)
        score += decision.kronos_confidence * 40
        
        # 信号强度 (30分)
        strength_scores = {"极强": 30, "强": 25, "中等": 15, "弱": 5, "极弱": 0}
        score += strength_scores.get(decision.kronos_signal_strength.value, 0)
        
        # 信号一致性 (20分)
        score += decision.signal_confluence * 20
        
        # 最终置信度 (10分)
        score += decision.final_confidence * 10
        
        return min(100, score)
    
    def _calculate_risk_score(self, decision: KronosEnhancedDecision) -> float:
        """计算风险评分"""
        risk_score = 50  # 基础风险
        
        # 根据Kronos预测调整
        if decision.kronos_prediction:
            predicted_change = abs(decision.kronos_prediction.price_change_pct)
            risk_score += predicted_change * 500  # 预测变化越大风险越高
        
        # 根据置信度调整
        risk_score -= decision.kronos_confidence * 30  # 置信度越高风险越低
        
        return max(0, min(100, risk_score))
    
    def _extract_key_factors(self, decision: KronosEnhancedDecision) -> List[str]:
        """提取关键因素"""
        factors = []
        
        # Kronos相关因素
        factors.append(f"Kronos置信度: {decision.kronos_confidence:.2f}")
        factors.append(f"信号强度: {decision.kronos_signal_strength.value}")
        
        if decision.kronos_prediction:
            change_pct = decision.kronos_prediction.price_change_pct * 100
            factors.append(f"预测变化: {change_pct:+.1f}%")
        
        # 技术分析因素
        factors.append(f"技术信号: {decision.technical_signal}")
        factors.append(f"信号一致性: {decision.signal_confluence:.2f}")
        
        return factors[:5]
    
    def _generate_reasoning(self, decision: KronosEnhancedDecision, direction: str) -> str:
        """生成推理说明"""
        reasoning_parts = []
        
        # 方向和置信度
        reasoning_parts.append(f"Kronos AI分析显示{direction}信号")
        reasoning_parts.append(f"置信度{decision.kronos_confidence:.2f}")
        
        # 预测变化
        if decision.kronos_prediction:
            change_pct = decision.kronos_prediction.price_change_pct * 100
            if abs(change_pct) > 1:
                reasoning_parts.append(f"预测价格变化{change_pct:+.1f}%")
        
        # 信号强度
        reasoning_parts.append(f"信号强度{decision.kronos_signal_strength.value}")
        
        # 一致性
        if decision.signal_confluence > 0.7:
            reasoning_parts.append("多指标高度一致")
        elif decision.signal_confluence > 0.5:
            reasoning_parts.append("指标基本一致")
        
        return "，".join(reasoning_parts) + "。"
    
    def _determine_urgency(self, decision: KronosEnhancedDecision) -> str:
        """确定紧急程度"""
        if decision.kronos_confidence > 0.8 and decision.kronos_signal_strength.value == "极强":
            return "high"
        elif decision.kronos_confidence > 0.7:
            return "medium"
        else:
            return "low"
    
    def _should_scan(self, scan_type: str) -> bool:
        """检查是否应该扫描"""
        last_time = self.last_scan_time.get(scan_type)
        if not last_time:
            return True
        
        interval = self.scan_intervals.get(scan_type, timedelta(hours=1))
        return datetime.now() - last_time >= interval
    
    async def _send_strong_opportunities_notification(
        self, 
        opportunities: List[KronosMarketOpportunity]
    ) -> int:
        """发送强交易机会通知"""
        try:
            if not opportunities:
                return 0
            
            count = len(opportunities)
            message = f"🤖 **Kronos强交易机会扫描**\n\n"
            message += f"🔥 发现 {count} 个强信号机会:\n\n"
            
            for i, opp in enumerate(opportunities[:5], 1):
                direction_emoji = "🚀" if opp.direction == "看涨" else "📉" if opp.direction == "看跌" else "🔄"
                
                message += f"{i}. **{opp.symbol}** {direction_emoji}\n"
                message += f"   📊 方向: {opp.direction} | 🤖 Kronos: {opp.kronos_confidence:.2f}\n"
                message += f"   💯 评分: {opp.opportunity_score:.0f}/100 | ⚠️ 风险: {opp.risk_score:.0f}/100\n"
                message += f"   💡 {opp.reasoning}\n\n"
            
            if count > 5:
                message += f"... 还有 {count - 5} 个机会\n\n"
            
            message += f"⏰ 扫描时间: {datetime.now().strftime('%H:%M:%S')}\n"
            message += "💡 仅推送Kronos AI识别的强信号，传统分析已停用"
            
            success = await self.notification_service.send_notification(
                title=f"🤖 Kronos强交易机会: {count}个",
                message=message,
                notification_type="kronos_strong_opportunities",
                priority="high"
            )
            
            return 1 if success else 0
            
        except Exception as e:
            self.logger.error(f"发送强机会通知失败: {e}")
            return 0
    
    async def _send_grid_opportunities_notification(
        self, 
        opportunities: List[KronosMarketOpportunity]
    ) -> int:
        """发送网格交易机会通知"""
        try:
            if not opportunities:
                return 0
            
            count = len(opportunities)
            message = f"🎯 **Kronos网格交易机会**\n\n"
            message += f"📊 交易量前50币种分析，发现 {count} 个网格机会:\n\n"
            
            for i, opp in enumerate(opportunities[:8], 1):  # 网格机会显示更多
                symbol_name = opp.symbol.replace('-USDT-SWAP', '')
                
                message += f"{i}. **{symbol_name}** 🔄\n"
                message += f"   📈 评分: {opp.opportunity_score:.0f}/100 | 🎯 {opp.direction}\n"
                message += f"   💰 区间: {opp.grid_lower:.4f} - {opp.grid_upper:.4f}\n"
                message += f"   🔢 建议: {opp.grid_count}格网格\n\n"
            
            if count > 8:
                message += f"... 还有 {count - 8} 个网格机会\n\n"
            
            message += f"⏰ 扫描时间: {datetime.now().strftime('%H:%M:%S')}\n"
            message += "🤖 基于Kronos AI分析的网格交易适合度评估"
            
            success = await self.notification_service.send_notification(
                title=f"🎯 Kronos网格机会: {count}个",
                message=message,
                notification_type="kronos_grid_opportunities",
                priority="medium"
            )
            
            return 1 if success else 0
            
        except Exception as e:
            self.logger.error(f"发送网格机会通知失败: {e}")
            return 0
    
    def _format_opportunity_summary(self, opp: KronosMarketOpportunity) -> Dict[str, Any]:
        """格式化机会摘要"""
        return {
            "symbol": opp.symbol,
            "type": opp.opportunity_type.value,
            "direction": opp.direction,
            "kronos_confidence": opp.kronos_confidence,
            "opportunity_score": opp.opportunity_score,
            "risk_score": opp.risk_score,
            "reasoning": opp.reasoning,
            "urgency": opp.urgency
        }
    
    async def get_scan_status(self) -> Dict[str, Any]:
        """获取扫描状态"""
        return {
            "enabled": self.enable_scan,
            "last_scan_times": {
                scan_type: time.isoformat() if time else None
                for scan_type, time in self.last_scan_time.items()
            },
            "scan_intervals": {
                scan_type: interval.total_seconds() / 60  # 转换为分钟
                for scan_type, interval in self.scan_intervals.items()
            },
            "thresholds": {
                "strong_signal": self.strong_signal_threshold,
                "grid_opportunity": self.grid_opportunity_threshold
            }
        }


# 全局服务实例
_kronos_market_opportunity_service = None

async def get_kronos_market_opportunity_service() -> KronosMarketOpportunityService:
    """获取Kronos市场机会服务实例"""
    global _kronos_market_opportunity_service
    if _kronos_market_opportunity_service is None:
        _kronos_market_opportunity_service = KronosMarketOpportunityService()
    return _kronos_market_opportunity_service