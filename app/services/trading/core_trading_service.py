# -*- coding: utf-8 -*-
"""
核心交易服务
Core Trading Service

整合所有交易决策功能的核心服务
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.trading import TradingSignal, AnalysisType, SignalStrength
from app.utils.exceptions import TradingToolError, ServiceInitializationError

# 导入依赖服务
from app.services.ml.kronos_integrated_decision_service import (
    get_kronos_integrated_service, 
    KronosIntegratedDecisionService,
    KronosEnhancedDecision
)
from app.services.analysis.position_analysis_service import (
    get_position_analysis_service,
    PositionAnalysisService
)
from app.utils.core_symbols_card_builder import CoreSymbolsCardBuilder
from app.services.exchanges.service_manager import (
    get_exchange_service
)
from app.services.trading.trading_decision_service import (
    get_trading_decision_service,
    TradingDecisionService
)
from app.services.ml import (
    get_ml_enhanced_service,
    MLEnhancedService
)
from app.services.analysis.trend_analysis_service import (
    get_trend_analysis_service,
    TrendAnalysisService
)
from app.services.volume_anomaly_service import (
    get_volume_anomaly_service
)
from app.services.analysis.open_interest_analysis_service import (
    get_oi_analysis_service as get_open_interest_analysis_service
)
from app.services.core.dynamic_weight_service import (
    get_dynamic_weight_service
)
from app.services.notification.core_notification_service import (
    get_core_notification_service
)

logger = get_logger(__name__)

@dataclass
class CoreSymbolsReport:
    """核心币种报告"""
    timestamp: datetime
    total_symbols: int
    successful_analyses: int
    analysis_success_rate: float
    action_categories: Dict[str, List[Dict[str, Any]]]
    summary: Dict[str, Any]
    market_overview: Optional[str] = None
    trading_recommendations: Optional[str] = None

class CoreTradingService:
    """核心交易服务 - 整合所有交易决策功能"""
    
    def __init__(self):
        """初始化核心交易服务"""
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.initialized = False
        
        # 依赖服务 - 延迟初始化
        self.kronos_service: Optional[KronosIntegratedDecisionService] = None
        self.position_service: Optional[PositionAnalysisService] = None
        self.exchange_service = None
        self.trading_decision_service: Optional[TradingDecisionService] = None
        self.ml_service: Optional[MLEnhancedService] = None
        self.trend_service: Optional[TrendAnalysisService] = None
        self.volume_anomaly_service = None
        self.open_interest_service = None
        self.dynamic_weight_service = None
        self.notification_service = None
        
        # 缓存
        self.analysis_cache: Dict[str, Any] = {}
        self.last_analysis_time: Dict[str, datetime] = {}
        
        # 配置
        self.cache_duration_minutes = self.settings.cache_config.get('analysis_cache_minutes', 5)
        self.confidence_threshold = self.settings.strategy_config.get('confidence_threshold', 0.6)
        
        # 核心币种配置
        self.core_symbols = self.settings.monitored_symbols or [
            "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"
        ]
    
    async def initialize(self) -> None:
        """异步初始化所有依赖服务"""
        if self.initialized:
            return
            
        try:
            self.logger.info("🚀 开始初始化核心交易服务...")
            
            # 初始化依赖服务
            initialization_tasks = []
            
            # Kronos AI 服务
            if self.settings.kronos_config.get('enable_kronos_prediction', False):
                initialization_tasks.append(self._init_kronos_service())
            
            # 其他核心服务
            initialization_tasks.extend([
                self._init_position_service(),
                self._init_exchange_service(),
                self._init_trading_decision_service(),
                self._init_notification_service()
            ])
            
            # ML 服务 (可选)
            if self.settings.ml_config.get('enable_ml_prediction', False):
                initialization_tasks.append(self._init_ml_service())
            
            # 技术分析服务
            initialization_tasks.append(self._init_trend_service())
            
            # 监控服务
            initialization_tasks.extend([
                self._init_volume_anomaly_service(),
                self._init_open_interest_service(),
                self._init_dynamic_weight_service()
            ])
            
            # 并行初始化所有服务
            await asyncio.gather(*initialization_tasks, return_exceptions=True)
            
            self.initialized = True
            self.logger.info("✅ 核心交易服务初始化完成")
            
        except Exception as e:
            self.logger.error(f"❌ 核心交易服务初始化失败: {e}")
            raise ServiceInitializationError(f"核心交易服务初始化失败: {str(e)}") from e
    
    async def _init_kronos_service(self):
        """初始化 Kronos 服务"""
        try:
            self.kronos_service = await get_kronos_integrated_service()
            self.logger.info("✅ Kronos AI 服务已启用")
        except Exception as e:
            self.logger.warning(f"⚠️ Kronos 服务初始化失败: {e}")
    
    async def _init_position_service(self):
        """初始化持仓分析服务"""
        try:
            self.position_service = await get_position_analysis_service()
        except Exception as e:
            self.logger.warning(f"⚠️ 持仓分析服务初始化失败: {e}")
    
    async def _init_exchange_service(self):
        """初始化交易所服务"""
        try:
            self.exchange_service = await get_exchange_service()
        except Exception as e:
            self.logger.warning(f"⚠️ 交易所服务初始化失败: {e}")
    
    async def _init_trading_decision_service(self):
        """初始化交易决策服务"""
        try:
            self.trading_decision_service = await get_trading_decision_service()
        except Exception as e:
            self.logger.warning(f"⚠️ 交易决策服务初始化失败: {e}")
    
    async def _init_ml_service(self):
        """初始化机器学习服务"""
        try:
            self.ml_service = await get_ml_enhanced_service()
            self.logger.info("✅ ML 增强服务已启用")
        except Exception as e:
            self.logger.warning(f"⚠️ ML 服务初始化失败: {e}")
    
    async def _init_trend_service(self):
        """初始化趋势分析服务"""
        try:
            self.trend_service = await get_trend_analysis_service()
        except Exception as e:
            self.logger.warning(f"⚠️ 趋势分析服务初始化失败: {e}")
    
    async def _init_volume_anomaly_service(self):
        """初始化成交量异常服务"""
        try:
            self.volume_anomaly_service = get_volume_anomaly_service()
        except Exception as e:
            self.logger.warning(f"⚠️ 成交量异常服务初始化失败: {e}")
    
    async def _init_open_interest_service(self):
        """初始化持仓量分析服务"""
        try:
            self.open_interest_service = get_open_interest_analysis_service()
        except Exception as e:
            self.logger.warning(f"⚠️ 持仓量分析服务初始化失败: {e}")
    
    async def _init_dynamic_weight_service(self):
        """初始化动态权重服务"""
        try:
            self.dynamic_weight_service = get_dynamic_weight_service()
        except Exception as e:
            self.logger.warning(f"⚠️ 动态权重服务初始化失败: {e}")
    
    async def _init_notification_service(self):
        """初始化通知服务"""
        try:
            self.notification_service = await get_core_notification_service()
        except Exception as e:
            self.logger.warning(f"⚠️ 通知服务初始化失败: {e}")

    async def get_core_symbols_analysis(self) -> List[TradingSignal]:
        """获取核心币种分析结果"""
        if not self.initialized:
            await self.initialize()
        
        self.logger.info(f"🔍 开始分析核心币种: {self.core_symbols}")
        
        # 并行分析所有核心币种
        analysis_tasks = []
        for symbol in self.core_symbols:
            task = self.analyze_symbol(
                symbol=symbol,
                analysis_type=AnalysisType.INTEGRATED,
                force_update=True
            )
            analysis_tasks.append(task)
        
        # 等待所有分析完成
        results = await asyncio.gather(*analysis_tasks, return_exceptions=True)
        
        # 过滤有效结果
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"❌ {self.core_symbols[i]} 分析失败: {result}")
            elif result is not None:
                valid_results.append(result)
        
        self.logger.info(f"✅ 核心币种分析完成，成功分析 {len(valid_results)}/{len(self.core_symbols)} 个")
        return valid_results

    async def send_core_symbols_report(self, notification_type: str = "定时推送") -> bool:
        """发送核心币种报告"""
        try:
            # 获取分析结果
            analysis_results = await self.get_core_symbols_analysis()
            
            if not analysis_results:
                self.logger.warning("⚠️ 没有有效的分析结果，跳过推送")
                return False
            
            # 生成报告
            report = await self._generate_core_symbols_report(analysis_results)
            
            # 生成卡片格式内容
            card_content = await self._build_card_notification(report, notification_type)
            
            # 发送通知 - 使用通知服务发送卡片
            if self.notification_service:
                success = await self.notification_service.send_core_symbols_report(analysis_results)
                
                if success:
                    self.logger.info(f"✅ 核心币种报告推送成功 ({notification_type})")
                    return True
                else:
                    self.logger.error(f"❌ 核心币种报告推送失败 ({notification_type})")
                    return False
            else:
                self.logger.warning("⚠️ 通知服务未初始化，无法发送报告")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 发送核心币种报告失败: {e}")
            return False

    async def _generate_core_symbols_report(self, analysis_results: List[TradingSignal]) -> CoreSymbolsReport:
        """生成核心币种报告"""
        # 按操作建议分类
        action_categories = {
            "强烈买入": [],
            "买入": [],
            "持有": [],
            "卖出": [],
            "强烈卖出": [],
            "观望": []
        }
        
        for signal in analysis_results:
            action = signal.final_action
            category_item = {
                "symbol": signal.symbol,
                "confidence": signal.final_confidence,
                "reasoning": signal.reasoning,
                "signal_strength": signal.signal_strength.value if signal.signal_strength else "UNKNOWN"
            }
            
            if action in action_categories:
                action_categories[action].append(category_item)
            else:
                # 默认归类到观望
                action_categories["观望"].append(category_item)
        
        # 计算统计信息
        total_symbols = len(self.core_symbols)
        successful_analyses = len(analysis_results)
        analysis_success_rate = (successful_analyses / total_symbols * 100) if total_symbols > 0 else 0
        
        # 生成市场概览和交易建议
        market_overview = await self._generate_market_overview(analysis_results)
        trading_recommendations = await self._generate_trading_recommendations(action_categories)
        
        return CoreSymbolsReport(
            timestamp=datetime.now(),
            total_symbols=total_symbols,
            successful_analyses=successful_analyses,
            analysis_success_rate=analysis_success_rate,
            action_categories=action_categories,
            summary={
                "total_symbols": total_symbols,
                "successful_analyses": successful_analyses,
                "analysis_success_rate": round(analysis_success_rate, 1)
            },
            market_overview=market_overview,
            trading_recommendations=trading_recommendations
        )

    async def _build_card_notification(self, report: CoreSymbolsReport, notification_type: str) -> Dict[str, Any]:
        """构建卡片格式通知内容 - 使用专用卡片构建器"""
        try:
            # 从报告中重新构建信号列表
            signals = []
            
            # 遍历所有操作分类，重新构建 TradingSignal 对象
            for action, items in report.action_categories.items():
                for item in items:
                    # 创建简化的信号对象用于卡片显示
                    signal = type('TradingSignal', (), {
                        'symbol': item['symbol'],
                        'final_action': action,
                        'final_confidence': item['confidence'],
                        'reasoning': item['reasoning'],
                        'signal_strength': item.get('signal_strength', 'MEDIUM'),
                        'current_price': None  # 价格信息可以从实时数据获取
                    })()
                    signals.append(signal)
            
            # 使用专用卡片构建器
            card_data = CoreSymbolsCardBuilder.build_core_symbols_card(
                signals=signals,
                notification_type=notification_type
            )
            
            return card_data
        
        except Exception as e:
            self.logger.error(f"❌ 构建卡片通知失败: {e}")
            return {
                "config": {
                    "wide_screen_mode": True,
                    "enable_forward": True
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "content": f"❌ 核心币种分析失败: {str(e)}",
                            "tag": "plain_text"
                        }
                    }
                ]
            }

    def _get_action_emoji(self, action: str) -> str:
        """获取操作对应的表情符号"""
        emoji_map = {
            "强烈买入": "🚀",
            "买入": "📈", 
            "持有": "🔒",
            "卖出": "📉",
            "强烈卖出": "🔻",
            "观望": "⏸️"
        }
        return emoji_map.get(action, "❓")

    async def _old_build_card_notification_backup(self, report, notification_type: str = "核心币种分析") -> str:
        """旧版卡片构建方法 - 备份"""
        try:
            lines = []
            lines.append(f"📊 {notification_type} - 核心币种分析报告")
            lines.append(f"⏰ 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("")
            
            # 按操作类型分组
            action_categories = {}
            for item in report.analysis_results:
                action = item['action']
                if action not in action_categories:
                    action_categories[action] = []
                action_categories[action].append(item)
            
            # 强烈买入
            if action_categories.get("强烈买入"):
                lines.append("🚀 **强烈买入建议**")
                for item in action_categories["强烈买入"]:
                    lines.append(f"• **{item['symbol']}** - 置信度: {item['confidence']:.1%}")
                    lines.append(f"  {item['reasoning']}")
                lines.append("")
            
            # 买入
            if action_categories.get("买入"):
                lines.append("📈 **买入建议**")
                for item in action_categories["买入"]:
                    lines.append(f"• **{item['symbol']}** - 置信度: {item['confidence']:.1%}")
                    lines.append(f"  {item['reasoning']}")
                lines.append("")
            
            # 持有
            if action_categories.get("持有"):
                lines.append("🔒 **持有建议**")
                for item in action_categories["持有"]:
                    lines.append(f"• **{item['symbol']}** - 置信度: {item['confidence']:.1%}")
                    lines.append(f"  {item['reasoning']}")
                lines.append("")
            
            # 卖出
            if action_categories.get("卖出"):
                lines.append("📉 **卖出建议**")
                for item in action_categories["卖出"]:
                    lines.append(f"• **{item['symbol']}** - 置信度: {item['confidence']:.1%}")
                lines.append("⏸️ **观望建议**")
                for item in action_categories["观望"]:
                    lines.append(f"• **{item['symbol']}** - 置信度: {item['confidence']:.1%}")
                    lines.append(f"  {item['reasoning']}")
                lines.append("")
            
            # 添加市场概览
            if report.market_overview:
                lines.append("🌍 **市场概览**")
                lines.append(report.market_overview)
                lines.append("")
            
            # 添加交易建议
            if report.trading_recommendations:
                lines.append("💡 **交易建议**")
                lines.append(report.trading_recommendations)
            
            return "\n".join(lines)
            
        except Exception as e:
            self.logger.error(f"❌ 构建卡片通知失败: {e}")
            return f"📊 {notification_type} - 核心币种分析报告\n\n❌ 报告生成失败: {str(e)}"

    def _get_action_emoji(self, action: str) -> str:
        """获取操作对应的表情符号"""
        emoji_map = {
            "强烈买入": "🚀",
            "买入": "📈", 
            "持有": "🔒",
            "卖出": "📉",
            "强烈卖出": "🔻",
            "观望": "⏸️"
        }
        return emoji_map.get(action, "❓")

    async def _generate_market_overview(self, analysis_results: List[TradingSignal]) -> str:
        """生成市场概览"""
        try:
            if not analysis_results:
                return "暂无分析数据"
            
            # 统计各种操作建议的数量
            action_counts = {}
            total_confidence = 0
            
            for signal in analysis_results:
                action = signal.final_action
                action_counts[action] = action_counts.get(action, 0) + 1
                total_confidence += signal.final_confidence
            
            avg_confidence = total_confidence / len(analysis_results)
            
            # 生成概览文本
            overview_parts = []
            overview_parts.append(f"平均置信度: {avg_confidence:.1%}")
            
            # 主要趋势
            if action_counts:
                dominant_action = max(action_counts.items(), key=lambda x: x[1])
                overview_parts.append(f"主要趋势: {dominant_action[0]} ({dominant_action[1]}个币种)")
            
            return " | ".join(overview_parts)
            
        except Exception as e:
            self.logger.error(f"❌ 生成市场概览失败: {e}")
            return "市场概览生成失败"

    async def _generate_trading_recommendations(self, action_categories: Dict[str, List[Dict[str, Any]]]) -> str:
        """生成交易建议"""
        try:
            recommendations = []
            
            # 根据不同操作建议生成相应的交易建议
            if action_categories.get("强烈买入"):
                recommendations.append("🚀 市场出现强烈买入信号，建议重点关注相关币种")
            
            if action_categories.get("强烈卖出"):
                recommendations.append("🔻 市场出现强烈卖出信号，建议谨慎操作并考虑止损")
            
            if len(action_categories.get("持有", [])) > len(action_categories.get("买入", [])) + len(action_categories.get("卖出", [])):
                recommendations.append("🔒 市场整体趋于稳定，建议以持有为主")
            
            if not recommendations:
                recommendations.append("📊 市场信号混合，建议根据个人风险偏好谨慎操作")
            
            return " | ".join(recommendations)
            
        except Exception as e:
            self.logger.error(f"❌ 生成交易建议失败: {e}")
            return "交易建议生成失败"

    async def analyze_symbol(
        self, 
        symbol: str, 
        analysis_type: AnalysisType = AnalysisType.INTEGRATED,
        force_update: bool = False
    ) -> Optional[TradingSignal]:
        """分析指定交易对 - 核心分析方法"""
        if not self.initialized:
            await self.initialize()
        
        try:
            # 检查缓存
            if not force_update and symbol in self.analysis_cache:
                cached_time = self.last_analysis_time.get(symbol)
                if cached_time and (datetime.now() - cached_time).total_seconds() < self.cache_duration_minutes * 60:
                    self.logger.debug(f"📋 使用缓存的 {symbol} 分析结果")
                    return self.analysis_cache[symbol]
            
            self.logger.info(f"🔍 开始分析 {symbol} (类型: {analysis_type.value})")
            
            # 根据分析类型执行相应的分析
            if analysis_type == AnalysisType.KRONOS_ONLY:
                result = await self._analyze_kronos_only(symbol)
            elif analysis_type == AnalysisType.TECHNICAL_ONLY:
                result = await self._analyze_technical_only(symbol)
            elif analysis_type == AnalysisType.ML_ONLY:
                result = await self._analyze_ml_only(symbol)
            else:
                # 综合分析 - 默认模式
                result = await self._analyze_integrated(symbol)
            
            # 缓存结果
            if result:
                self.analysis_cache[symbol] = result
                self.last_analysis_time[symbol] = datetime.now()
                self.logger.info(f"✅ {symbol} 分析完成: {result.final_action} (置信度: {result.final_confidence:.1%})")
            else:
                self.logger.warning(f"⚠️ {symbol} 分析未产生有效结果")
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ 分析 {symbol} 失败: {e}")
            raise TradingToolError(f"交易分析失败: {str(e)}") from e

    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        try:
            if self.exchange_service:
                price = await self.exchange_service.get_current_price(symbol)
                return price
        except Exception as e:
            self.logger.warning(f"获取 {symbol} 价格失败: {e}")
        return None

    async def _get_detailed_technical_analysis(self, symbol: str) -> Dict[str, Any]:
        """获取详细技术分析"""
        try:
            from app.services.analysis.detailed_technical_analysis_service import get_detailed_technical_analysis_service
            
            detailed_service = get_detailed_technical_analysis_service()
            analysis = await detailed_service.analyze_symbol_detailed(symbol)
            
            if analysis:
                return {
                    "trend_indicators": [
                        {
                            "name": ind.name,
                            "signal": ind.signal,
                            "strength": ind.strength,
                            "value": ind.value,
                            "description": ind.description
                        } for ind in analysis.trend_indicators
                    ],
                    "momentum_indicators": [
                        {
                            "name": ind.name,
                            "signal": ind.signal,
                            "strength": ind.strength,
                            "value": ind.value,
                            "description": ind.description
                        } for ind in analysis.momentum_indicators
                    ],
                    "volume_indicators": [
                        {
                            "name": ind.name,
                            "signal": ind.signal,
                            "strength": ind.strength,
                            "value": ind.value,
                            "description": ind.description
                        } for ind in analysis.volume_indicators
                    ],
                    "volatility_indicators": [
                        {
                            "name": ind.name,
                            "signal": ind.signal,
                            "strength": ind.strength,
                            "value": ind.value,
                            "description": ind.description
                        } for ind in analysis.volatility_indicators
                    ],
                    "scores": {
                        "trend": analysis.trend_score,
                        "momentum": analysis.momentum_score,
                        "volume": analysis.volume_score,
                        "volatility": analysis.volatility_score
                    },
                    "overall_signal": analysis.overall_signal,
                    "overall_confidence": analysis.overall_confidence
                }
        except Exception as e:
            self.logger.warning(f"获取 {symbol} 详细技术分析失败: {e}")
        
        return {}

    def _build_detailed_technical_reasoning(
        self, 
        basic_result: Dict[str, Any], 
        detailed_analysis: Dict[str, Any]
    ) -> str:
        """构建详细的技术分析推理"""
        reasoning_parts = []
        
        # 基础技术分析
        basic_reasoning = basic_result.get('reasoning', '技术指标分析')
        reasoning_parts.append(f"📊 基础分析: {basic_reasoning}")
        
        if detailed_analysis:
            # 趋势指标分析
            trend_indicators = detailed_analysis.get("trend_indicators", [])
            if trend_indicators:
                trend_details = []
                for ind in trend_indicators:
                    if ind["name"] in ["supertrend", "ema_cross"]:
                        trend_details.append(f"{ind['name']}({ind['signal']}, 强度{ind['strength']:.1%})")
                
                if trend_details:
                    reasoning_parts.append(f"📈 趋势指标: {', '.join(trend_details)}")
            
            # 动量指标分析
            momentum_indicators = detailed_analysis.get("momentum_indicators", [])
            if momentum_indicators:
                momentum_details = []
                for ind in momentum_indicators:
                    if ind["name"] in ["rsi", "macd"]:
                        momentum_details.append(f"{ind['name']}({ind['signal']}, {ind['value']:.2f})")
                
                if momentum_details:
                    reasoning_parts.append(f"⚡ 动量指标: {', '.join(momentum_details)}")
            
            # 波动率指标分析（布林带等）
            volatility_indicators = detailed_analysis.get("volatility_indicators", [])
            if volatility_indicators:
                volatility_details = []
                for ind in volatility_indicators:
                    if ind["name"] == "bollinger":
                        volatility_details.append(f"布林带({ind['signal']}, {ind['description']})")
                    else:
                        volatility_details.append(f"{ind['name']}({ind['signal']})")
                
                if volatility_details:
                    reasoning_parts.append(f"📊 波动率: {', '.join(volatility_details)}")
            
            # 成交量分析
            volume_indicators = detailed_analysis.get("volume_indicators", [])
            if volume_indicators:
                volume_details = []
                for ind in volume_indicators:
                    volume_details.append(f"{ind['name']}({ind['signal']})")
                
                if volume_details:
                    reasoning_parts.append(f"📈 成交量: {', '.join(volume_details)}")
            
            # 综合评分
            scores = detailed_analysis.get("scores", {})
            if scores:
                score_text = f"趋势{scores.get('trend', 0):.0f}分, 动量{scores.get('momentum', 0):.0f}分, 成交量{scores.get('volume', 0):.0f}分"
                reasoning_parts.append(f"🎯 综合评分: {score_text}")
        
        return " | ".join(reasoning_parts) if reasoning_parts else basic_reasoning

    async def _analyze_kronos_only(self, symbol: str) -> Optional[TradingSignal]:
        """仅使用 Kronos AI 分析"""
        if not self.kronos_service:
            self.logger.warning(f"⚠️ Kronos 服务未启用，无法分析 {symbol}")
            return None
        
        try:
            kronos_result = await self.kronos_service.get_kronos_enhanced_decision(
                symbol=symbol,
                force_update=True
            )
            
            if kronos_result:
                # 获取当前价格
                current_price = await self._get_current_price(symbol)
                
                return TradingSignal(
                    symbol=symbol,
                    final_action=kronos_result.final_action,
                    final_confidence=kronos_result.kronos_confidence,
                    signal_strength=SignalStrength.from_confidence(kronos_result.kronos_confidence),
                    reasoning=f"Kronos AI 分析: {kronos_result.reasoning}",
                    timestamp=datetime.now(),
                    current_price=current_price,
                    kronos_result=kronos_result,
                    technical_result=None,
                    ml_result=None,
                    entry_price=current_price
                )
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Kronos 分析 {symbol} 失败: {e}")
            return None

    async def _analyze_technical_only(self, symbol: str) -> Optional[TradingSignal]:
        """仅使用技术分析"""
        if not self.trend_service:
            self.logger.warning(f"⚠️ 技术分析服务未启用，无法分析 {symbol}")
            return None
        
        try:
            # 调用技术分析服务的 analyze_symbol 方法
            tech_result = await self.trend_service.analyze_symbol(symbol)
            
            if tech_result:
                # 获取详细技术分析
                detailed_analysis = await self._get_detailed_technical_analysis(symbol)
                
                # 处理技术分析结果，可能是 TradingSignal 对象或字典
                if hasattr(tech_result, 'final_action'):
                    # 如果是 TradingSignal 对象
                    return tech_result
                else:
                    # 如果是字典，构建 TradingSignal
                    current_price = await self._get_current_price(symbol)
                    
                    # 构建详细的技术分析推理
                    detailed_reasoning = self._build_detailed_technical_reasoning(
                        tech_result, detailed_analysis
                    )
                    
                    return TradingSignal(
                        symbol=symbol,
                        final_action=tech_result.get("action", "持有"),
                        final_confidence=tech_result.get("confidence", 0.5),
                        signal_strength=SignalStrength.from_confidence(tech_result.get("confidence", 0.5)),
                        reasoning=detailed_reasoning,
                        timestamp=datetime.now(),
                        current_price=current_price,
                        kronos_result=None,
                        technical_result=tech_result,
                        ml_result=None,
                        entry_price=current_price
                    )
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ 技术分析 {symbol} 失败: {e}")
            return None

    async def _analyze_ml_only(self, symbol: str) -> Optional[TradingSignal]:
        """仅使用机器学习分析"""
        if not self.ml_service:
            self.logger.warning(f"⚠️ ML 服务未启用，无法分析 {symbol}")
            return None
        
        try:
            ml_result = await self.ml_service.predict_signal(symbol)
            
            if ml_result:
                # 获取当前价格
                current_price = await self._get_current_price(symbol)
                
                return TradingSignal(
                    symbol=symbol,
                    final_action=ml_result.signal,
                    final_confidence=ml_result.confidence,
                    signal_strength=SignalStrength.from_confidence(ml_result.confidence),
                    reasoning=f"机器学习分析: {getattr(ml_result, 'reasoning', '机器学习预测')}",
                    timestamp=datetime.now(),
                    current_price=current_price,
                    kronos_result=None,
                    technical_result=None,
                    ml_result=ml_result,
                    entry_price=current_price
                )
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ ML 分析 {symbol} 失败: {e}")
            return None

    async def _analyze_integrated(self, symbol: str) -> Optional[TradingSignal]:
        """综合分析 - 融合多种分析方法"""
        results = {}
        confidence_scores = {}
        
        # 1. Kronos AI 分析
        if self.kronos_service:
            kronos_result = await self._safe_analyze_kronos(symbol)
            if kronos_result:
                results['kronos'] = kronos_result
                confidence_scores['kronos'] = kronos_result.kronos_confidence
        
        # 2. 技术分析
        if self.trend_service:
            tech_result = await self._safe_analyze_technical(symbol)
            if tech_result:
                results['technical'] = tech_result
                # 处理技术分析结果的置信度
                if hasattr(tech_result, 'final_confidence'):
                    confidence_scores['technical'] = tech_result.final_confidence
                elif isinstance(tech_result, dict):
                    confidence_scores['technical'] = tech_result.get('confidence', 0.5)
                else:
                    confidence_scores['technical'] = 0.5
        
        # 3. ML 分析
        if self.ml_service:
            ml_result = await self._safe_analyze_ml(symbol)
            if ml_result:
                results['ml'] = ml_result
                confidence_scores['ml'] = getattr(ml_result, 'confidence', 0.5)
        
        # 4. 决策融合
        if not results:
            self.logger.warning(f"⚠️ {symbol} 没有可用的分析结果")
            return None
        
        return await self._fuse_decisions(symbol, results, confidence_scores)

    async def _safe_analyze_kronos(self, symbol: str):
        """安全的 Kronos 分析"""
        try:
            if self.kronos_service:
                return await self.kronos_service.get_kronos_enhanced_decision(symbol, force_update=True)
        except Exception as e:
            self.logger.warning(f"⚠️ Kronos 分析 {symbol} 失败: {e}")
        return None

    async def _safe_analyze_technical(self, symbol: str):
        """安全的技术分析"""
        try:
            if self.trend_service:
                return await self.trend_service.analyze_symbol(symbol)
        except Exception as e:
            self.logger.warning(f"⚠️ 技术分析 {symbol} 失败: {e}")
        return None

    async def _safe_analyze_ml(self, symbol: str):
        """安全的 ML 分析"""
        try:
            if self.ml_service:
                return await self.ml_service.predict_signal(symbol)
        except Exception as e:
            self.logger.warning(f"⚠️ ML 分析 {symbol} 失败: {e}")
        return None

    async def _fuse_decisions(self, symbol: str, results: Dict[str, Any], confidence_scores: Dict[str, float]) -> TradingSignal:
        """融合多个分析结果"""
        try:
            # 获取动态权重
            if self.dynamic_weight_service:
                weights_obj = await self.dynamic_weight_service.get_dynamic_weights(symbol)
                # 转换权重对象为字典
                if hasattr(weights_obj, '__dict__'):
                    weights = {
                        'kronos': getattr(weights_obj, 'kronos_weight', 0.5),
                        'technical': getattr(weights_obj, 'technical_weight', 0.3), 
                        'ml': getattr(weights_obj, 'ml_weight', 0.2),
                        'position': getattr(weights_obj, 'position_weight', 0.0)
                    }
                else:
                    # 如果已经是字典，直接使用
                    weights = weights_obj if isinstance(weights_obj, dict) else {
                        'kronos': 0.5, 'technical': 0.3, 'ml': 0.2
                    }
            else:
                # 默认权重
                weights = {'kronos': 0.5, 'technical': 0.3, 'ml': 0.2}
            
            # 计算加权置信度和动作
            weighted_actions = {}
            weighted_confidences = {}
            total_weight = 0
            
            for method, result in results.items():
                if method in weights and method in confidence_scores:
                    weight = weights[method]
                    confidence = confidence_scores[method]
                    
                    if method == 'kronos':
                        action = getattr(result, 'final_action', '持有')
                    elif method == 'technical':
                        if hasattr(result, 'final_action'):
                            action = result.final_action
                        elif isinstance(result, dict):
                            action = result.get('action', '持有')
                        else:
                            action = '持有'
                    elif method == 'ml':
                        action = getattr(result, 'signal', '持有')
                    else:
                        continue
                    
                    # 累计动作权重
                    if action not in weighted_actions:
                        weighted_actions[action] = 0
                        weighted_confidences[action] = 0
                    
                    weighted_actions[action] += weight
                    weighted_confidences[action] += weight * confidence
                    total_weight += weight
            
            if not weighted_actions:
                # 如果没有有效的加权结果，使用第一个可用结果
                first_result = list(results.values())[0]
                if hasattr(first_result, 'final_action'):
                    final_action = first_result.final_action
                    final_confidence = getattr(first_result, 'kronos_confidence', 0.5)
                else:
                    final_action = "持有"
                    final_confidence = 0.5
            else:
                # 选择权重最高的动作
                final_action = max(weighted_actions.items(), key=lambda x: x[1])[0]
                
                # 计算该动作的加权平均置信度
                action_weight = weighted_actions[final_action]
                final_confidence = weighted_confidences[final_action] / action_weight if action_weight > 0 else 0.5
                
                # 确保置信度在合理范围内
                final_confidence = max(0.1, min(0.95, final_confidence))
            
            # 生成推理说明
            reasoning_parts = []
            for method, result in results.items():
                if method == 'kronos':
                    reasoning_parts.append(f"Kronos: {getattr(result, 'final_action', '持有')}")
                elif method == 'technical':
                    if hasattr(result, 'final_action'):
                        reasoning_parts.append(f"技术: {result.final_action}")
                    elif isinstance(result, dict):
                        reasoning_parts.append(f"技术: {result.get('action', '持有')}")
                    else:
                        reasoning_parts.append(f"技术: 持有")
                elif method == 'ml':
                    reasoning_parts.append(f"ML: {getattr(result, 'signal', '持有')}")
            
            reasoning = f"综合分析 ({', '.join(reasoning_parts)})"
            
            # 转换对象为字典以符合 Pydantic 模型要求
            kronos_dict = None
            if results.get('kronos'):
                kronos_obj = results['kronos']
                if hasattr(kronos_obj, '__dict__'):
                    kronos_dict = {k: str(v) if hasattr(v, '__dict__') else v for k, v in kronos_obj.__dict__.items()}
                else:
                    kronos_dict = results['kronos']
            
            ml_dict = None
            if results.get('ml'):
                ml_obj = results['ml']
                if hasattr(ml_obj, '__dict__'):
                    ml_dict = {k: str(v) if hasattr(v, '__dict__') else v for k, v in ml_obj.__dict__.items()}
                else:
                    ml_dict = results['ml']
            
            # 获取当前价格
            current_price = await self._get_current_price(symbol)
            
            return TradingSignal(
                symbol=symbol,
                final_action=final_action,
                final_confidence=final_confidence,
                signal_strength=SignalStrength.from_confidence(final_confidence),
                reasoning=reasoning,
                timestamp=datetime.now(),
                current_price=current_price,
                kronos_result=kronos_dict,
                technical_result=results.get('technical'),
                ml_result=ml_dict,
                entry_price=current_price,
                confidence_breakdown=confidence_scores
            )
            
        except Exception as e:
            self.logger.error(f"❌ 决策融合失败: {e}")
            # 获取当前价格（即使在错误情况下也尝试获取）
            current_price = await self._get_current_price(symbol)
            
            # 返回默认结果
            return TradingSignal(
                symbol=symbol,
                final_action="持有",
                final_confidence=0.5,
                signal_strength=SignalStrength.WEAK,
                reasoning=f"决策融合失败，使用默认建议: {str(e)}",
                timestamp=datetime.now(),
                current_price=current_price,
                kronos_result=None,
                technical_result=None,
                ml_result=None,
                entry_price=current_price
            )

    async def health_check(self) -> Dict[str, Any]:
        """服务健康检查"""
        if not self.initialized:
            return {"status": "not_initialized", "healthy": False}
        
        checks = {
            "service_initialized": self.initialized,
            "dependencies": {}
        }
        
        # 检查依赖服务健康状态
        if self.kronos_service:
            try:
                # 简单的健康检查，检查服务是否可用
                if hasattr(self.kronos_service, 'health_check'):
                    kronos_health = await self.kronos_service.health_check()
                else:
                    kronos_health = {"healthy": True, "status": "available"}
                checks["dependencies"]["kronos"] = kronos_health
            except Exception:
                checks["dependencies"]["kronos"] = {"healthy": False, "status": "unavailable"}
        
        if self.exchange_service:
            try:
                # 简单的健康检查，检查服务是否可用
                if hasattr(self.exchange_service, 'health_check'):
                    exchange_health = await self.exchange_service.health_check()
                else:
                    exchange_health = {"healthy": True, "status": "available"}
                checks["dependencies"]["exchange"] = exchange_health
            except Exception:
                checks["dependencies"]["exchange"] = {"healthy": False, "status": "unavailable"}
        
        # 计算整体健康状态
        dependency_health = []
        for dep in checks["dependencies"].values():
            if isinstance(dep, dict):
                dependency_health.append(dep.get("healthy", False))
            else:
                dependency_health.append(False)
        
        all_healthy = len(dependency_health) > 0 and all(dependency_health)
        checks["healthy"] = all_healthy
        checks["status"] = "healthy" if all_healthy else "degraded"
        
        return checks

    async def cleanup(self) -> None:
        """清理资源"""
        try:
            self.logger.info("🧹 开始清理核心交易服务资源...")
            
            # 清理缓存
            self.analysis_cache.clear()
            self.last_analysis_time.clear()
            
            # 清理依赖服务
            cleanup_tasks = []
            
            if self.kronos_service and hasattr(self.kronos_service, 'cleanup'):
                cleanup_tasks.append(self.kronos_service.cleanup())
            
            if self.exchange_service and hasattr(self.exchange_service, 'cleanup'):
                cleanup_tasks.append(self.exchange_service.cleanup())
            
            if cleanup_tasks:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            
            self.initialized = False
            self.logger.info("✅ 核心交易服务资源清理完成")
            
        except Exception as e:
            self.logger.error(f"❌ 清理核心交易服务资源失败: {e}")

# 全局服务实例
_core_trading_service: Optional[CoreTradingService] = None

async def get_core_trading_service() -> CoreTradingService:
    """获取核心交易服务实例 - 全局单例"""
    global _core_trading_service
    if _core_trading_service is None:
        _core_trading_service = CoreTradingService()
        await _core_trading_service.initialize()
    return _core_trading_service