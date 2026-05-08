# -*- coding: utf-8 -*-
"""
Kronos持仓分析服务
定时分析当前账户持仓，提供基于Kronos预测的详细建议和风险评估
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger, trading_logger
from app.services.ml.kronos_integrated_decision_service import get_kronos_integrated_service, KronosEnhancedDecision
from app.services.notification.core_notification_service import get_core_notification_service
from app.services.exchanges.exchange_service_manager import get_exchange_service
from app.services.trading.trading_decision_service import TradingDecisionService


@dataclass
class PositionAnalysisResult:
    """持仓分析结果"""
    symbol: str
    current_position: Dict[str, Any]
    kronos_decision: Optional[KronosEnhancedDecision]
    risk_assessment: str
    recommendation: str
    urgency_level: str
    potential_pnl: float
    suggested_action: str
    
    # 新增涨跌预测字段
    price_prediction: Optional[Dict[str, Any]] = None  # 价格预测详情
    trend_prediction: Optional[str] = None  # 趋势预测
    confidence_level: Optional[float] = None  # 预测置信度


class KronosPositionAnalysisService:
    """Kronos持仓分析服务"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.notification_service = None  # Will be initialized async
        self.exchange_service = None  # 将在需要时异步初始化
        self.traditional_analysis_service = TradingDecisionService()  # 传统技术分析服务
        
        # 动态权重配置
        self.weight_config = {
            'kronos_base_weight': 0.7,      # Kronos模型基础权重
            'traditional_base_weight': 0.3,  # 传统分析基础权重
            'confidence_threshold': 0.6,     # 置信度阈值
            'weight_adjustment_factor': 0.2  # 权重调整因子
        }
        
        # 传统技术分析权重替换配置
        self.traditional_weight_config = {
            'trend_weight': 0.35,           # 趋势分析权重
            'momentum_weight': 0.25,        # 动量指标权重
            'volatility_weight': 0.15,      # 波动性指标权重
            'volume_weight': 0.15,          # 成交量分析权重
            'support_resistance_weight': 0.1 # 支撑阻力权重
        }
        
        # 分析配置
        self.analysis_config = {
            'enable_notifications': True,
            'min_position_value': 100,  # 最小持仓价值(USDT)
            'high_risk_threshold': 0.15,  # 15%风险阈值
            'notification_cooldown_minutes': 0,  # 移除通知冷却时间限制
            'urgent_notification_cooldown_minutes': 0,  # 移除紧急情况冷却时间限制
            'high_risk_notification_cooldown_minutes': 0,  # 移除高风险情况冷却时间限制
        }
        
        # 配置管理和异常处理
        self.system_config = {
            'kronos_availability_check': {
                'enabled': True,
                'timeout_seconds': 5.0,
                'retry_attempts': 2,
                'fallback_enabled': True
            },
            'dynamic_weights': {
                'enabled': True,
                'confidence_threshold': 0.5,
                'blend_mode': 'adaptive',  # 'adaptive', 'fixed', 'confidence_based'
                'min_kronos_weight': 0.3,
                'max_traditional_weight': 0.8
            },
            'risk_assessment': {
                'market_context_enabled': True,
                'volatility_adjustment': True,
                'position_duration_factor': True,
                'conservative_fallback': True
            },
            'traditional_fallback': {
                'enabled': True,
                'confidence_boost': 0.1,  # 提升传统分析置信度
                'weight_adjustment': 'dynamic',  # 'dynamic', 'fixed'
                'min_confidence': 0.6
            },
            'error_handling': {
                'max_retries': 3,
                'fallback_to_conservative': True,
                'log_errors': True,
                'circuit_breaker_threshold': 5,  # 连续失败次数阈值
                'circuit_breaker_timeout': 300   # 熔断器超时时间(秒)
            }
        }
        
        # 错误统计和熔断器状态
        self.error_stats = {
            'consecutive_failures': 0,
            'total_failures': 0,
            'last_failure_time': None,
            'circuit_breaker_active': False,
            'circuit_breaker_until': None
        }
        
        # 通知历史
        self.last_notification_time = None
    
    def update_system_config(self, section: str, **kwargs) -> bool:
        """更新系统配置"""
        try:
            if section not in self.system_config:
                self.logger.warning(f"⚠️ 未知配置节: {section}")
                return False
            
            for key, value in kwargs.items():
                if key in self.system_config[section]:
                    old_value = self.system_config[section][key]
                    self.system_config[section][key] = value
                    self.logger.info(f"📝 更新配置 {section}.{key}: {old_value} -> {value}")
                else:
                    self.logger.warning(f"⚠️ 未知配置项: {section}.{key}")
                    return False
            return True
        except Exception as e:
            self.logger.error(f"❌ 更新配置失败: {e}")
            return False
    
    def get_system_config(self, section: str = None) -> Dict[str, Any]:
        """获取系统配置"""
        if section:
            return self.system_config.get(section, {}).copy()
        return self.system_config.copy()
    
    def _check_circuit_breaker(self) -> bool:
        """检查熔断器状态"""
        if not self.error_stats['circuit_breaker_active']:
            return False
        
        if self.error_stats['circuit_breaker_until'] and \
           datetime.now() > self.error_stats['circuit_breaker_until']:
            # 熔断器超时，重置状态
            self._reset_circuit_breaker()
            return False
        
        return True
    
    def _trigger_circuit_breaker(self):
        """触发熔断器"""
        timeout_seconds = self.system_config['error_handling']['circuit_breaker_timeout']
        self.error_stats['circuit_breaker_active'] = True
        self.error_stats['circuit_breaker_until'] = datetime.now() + timedelta(seconds=timeout_seconds)
        self.logger.warning(f"🔴 熔断器已触发，将在 {timeout_seconds} 秒后重置")
    
    def _reset_circuit_breaker(self):
        """重置熔断器"""
        self.error_stats['circuit_breaker_active'] = False
        self.error_stats['circuit_breaker_until'] = None
        self.error_stats['consecutive_failures'] = 0
        self.logger.info("🟢 熔断器已重置")
    
    def _record_error(self, error: Exception, operation: str):
        """记录错误"""
        self.error_stats['total_failures'] += 1
        self.error_stats['consecutive_failures'] += 1
        self.error_stats['last_failure_time'] = datetime.now()
        
        if self.system_config['error_handling']['log_errors']:
            self.logger.error(f"❌ 操作失败 [{operation}]: {error}")
        
        # 检查是否需要触发熔断器
        threshold = self.system_config['error_handling']['circuit_breaker_threshold']
        if self.error_stats['consecutive_failures'] >= threshold:
            self._trigger_circuit_breaker()
    
    def _record_success(self, operation: str):
        """记录成功操作"""
        self.error_stats['consecutive_failures'] = 0
        if self.error_stats['circuit_breaker_active']:
            self._reset_circuit_breaker()
    
    async def _safe_execute(self, operation_name: str, operation_func, *args, **kwargs):
        """安全执行操作，带重试和异常处理"""
        if self._check_circuit_breaker():
            self.logger.warning(f"🔴 熔断器激活，跳过操作: {operation_name}")
            return None
        
        max_retries = self.system_config['error_handling']['max_retries']
        
        for attempt in range(max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(operation_func):
                    result = await operation_func(*args, **kwargs)
                else:
                    result = operation_func(*args, **kwargs)
                
                self._record_success(operation_name)
                return result
                
            except Exception as e:
                if attempt == max_retries:
                    self._record_error(e, operation_name)
                    if self.system_config['error_handling']['fallback_to_conservative']:
                        self.logger.warning(f"⚠️ 操作失败，使用保守策略: {operation_name}")
                        return self._get_conservative_fallback(operation_name)
                    raise
                else:
                    self.logger.warning(f"⚠️ 操作失败，重试 {attempt + 1}/{max_retries}: {operation_name}")
                    await asyncio.sleep(0.5 * (attempt + 1))  # 指数退避
        
        return None
    
    def _get_conservative_fallback(self, operation_name: str):
        """获取保守的回退结果"""
        if 'risk' in operation_name.lower():
            return "高风险"
        elif 'recommendation' in operation_name.lower():
            return "建议谨慎观察，避免新增仓位"
        elif 'weight' in operation_name.lower():
            return {'traditional_weight': 1.0, 'kronos_weight': 0.0}
        else:
            return None
    
    def update_notification_config(self, **kwargs):
        """更新通知配置"""
        for key, value in kwargs.items():
            if key in self.analysis_config:
                old_value = self.analysis_config[key]
                self.analysis_config[key] = value
                self.logger.info(f"📝 更新配置 {key}: {old_value} -> {value}")
            else:
                self.logger.warning(f"⚠️ 未知配置项: {key}")
    
    def get_notification_config(self) -> Dict[str, Any]:
        """获取当前通知配置"""
        return self.analysis_config.copy()
    
    async def _ensure_notification_service(self):
        """确保通知服务已初始化"""
        if self.notification_service is None:
            self.notification_service = await get_core_notification_service()
    
    async def _ensure_exchange_service(self):
        """确保交易所服务已初始化"""
        if self.exchange_service is None:
            self.exchange_service = await get_exchange_service()
        
    async def run_scheduled_analysis(self, force_notification: bool = False) -> Dict[str, Any]:
        """运行定时持仓分析"""
        try:
            self.logger.info(f"🤖 开始定时Kronos持仓分析... (实例ID: {id(self)}, 强制推送: {force_notification})")
            
            # 获取当前持仓
            positions = await self._get_current_positions()
            if not positions:
                self.logger.info("📊 当前无持仓，跳过分析")
                return {"status": "no_positions"}
            
            # 分析每个持仓
            analysis_results = []
            for position in positions:
                result = await self._analyze_position(position)
                if result:
                    analysis_results.append(result)
            
            # 生成综合报告
            report = await self._generate_comprehensive_report(analysis_results)
            
            # 检查通知冷却（基于分析结果动态调整）
            if not force_notification and not self._should_send_notification(analysis_results):
                cooldown_remaining = self._get_cooldown_remaining_minutes(analysis_results)
                self.logger.info(f"⏰ 通知冷却期内，跳过推送 (剩余冷却时间: {cooldown_remaining:.1f}分钟)")
                return {
                    "status": "analyzed_no_notification", 
                    "reason": "cooldown", 
                    "cooldown_remaining_minutes": cooldown_remaining,
                    "positions_analyzed": len(analysis_results),
                    "report": report,
                    "analysis_time": datetime.now().isoformat()
                }
            
            # 发送通知
            if self.analysis_config['enable_notifications'] and analysis_results:
                self.logger.info(f"📢 准备发送Kronos持仓分析通知，分析结果数量: {len(analysis_results)}")
                notification_success = await self._send_position_analysis_notification(report, analysis_results)
                if notification_success:
                    self.logger.info("✅ Kronos持仓分析通知发送成功")
                    self.last_notification_time = datetime.now()
                else:
                    self.logger.warning("⚠️ Kronos持仓分析通知发送失败")
            elif not self.analysis_config['enable_notifications']:
                self.logger.info("📴 Kronos持仓分析通知已禁用")
            elif not analysis_results:
                self.logger.info("📊 无持仓分析结果，跳过通知")
            
            self.logger.info(f"✅ Kronos持仓分析完成，分析了 {len(analysis_results)} 个持仓")
            
            return {
                "status": "success",
                "positions_analyzed": len(analysis_results),
                "report": report,
                "analysis_time": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ 定时Kronos持仓分析失败: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _get_current_positions(self) -> List[Dict[str, Any]]:
        """获取当前持仓"""
        try:
            self.logger.info("🔍 开始获取当前持仓信息...")
            
            # 检查交易所类型，币安跳过持仓获取
            from app.core.config import get_settings
            settings = get_settings()
            
            if settings.exchange_provider.lower() == 'binance':
                self.logger.info("📴 币安交易所跳过持仓获取")
                return []
            
            # 确保交易所服务已初始化
            await self._ensure_exchange_service()
            
            # 获取持仓信息
            async with self.exchange_service as exchange:
                all_positions = await exchange.get_positions()
            if not all_positions:
                self.logger.info("📊 当前无任何持仓")
                return []
            
            self.logger.info(f"📊 获取到 {len(all_positions)} 个持仓记录")
            
            # 过滤有效持仓
            valid_positions = []
            for position in all_positions:
                pos_size = float(position.get('size', 0))
                symbol = position.get('symbol', '')
                
                # 只分析有持仓的币种
                if pos_size != 0:
                    # 获取持仓价值（已由交易所服务计算）
                    position_value = position.get('position_value_usd', 0)
                    mark_price = position.get('mark_price', 0)
                    
                    self.logger.info(f"💰 {symbol}: 持仓 {pos_size}, 价格 {mark_price}, 价值 {position_value:.2f} USDT")
                    
                    # 只分析价值超过阈值的持仓
                    if position_value >= self.analysis_config['min_position_value']:
                        # 获取未实现盈亏，优先使用unrealized_pnl字段
                        unrealized_pnl = position.get('unrealized_pnl', 0)
                        if unrealized_pnl == 0:
                            # 如果unrealized_pnl为0，尝试使用upl字段
                            upl_str = position.get('upl', '0')
                            try:
                                unrealized_pnl = float(upl_str) if upl_str != 'N/A' else 0
                            except (ValueError, TypeError):
                                unrealized_pnl = 0
                        
                        # 转换为兼容格式
                        compatible_position = {
                            'instId': symbol,
                            'pos': str(pos_size),
                            'markPx': str(mark_price),
                            'upl': str(unrealized_pnl),  # 使用正确的盈亏数据
                            'position_value': position_value,
                            # 保留原始数据
                            'original_data': position
                        }
                        valid_positions.append(compatible_position)
                        self.logger.info(f"✅ {symbol} 符合分析条件，加入分析列表")
                    else:
                        self.logger.info(f"⚪ {symbol} 持仓价值 {position_value:.2f} USDT 低于阈值 {self.analysis_config['min_position_value']} USDT")
            
            self.logger.info(f"📈 最终有效持仓数量: {len(valid_positions)}")
            return valid_positions
            
        except Exception as e:
            self.logger.error(f"获取当前持仓失败: {e}")
            return []
    
    async def _analyze_position(self, position: Dict[str, Any]) -> Optional[PositionAnalysisResult]:
        """分析单个持仓"""
        try:
            symbol = position.get('instId', '')
            if not symbol:
                return None
            
            self.logger.info(f"🔍 分析持仓: {symbol}")
            
            # 获取Kronos增强决策
            kronos_service = await get_kronos_integrated_service()
            kronos_decision = await kronos_service.get_kronos_enhanced_decision(symbol, force_update=True)
            
            # 分析持仓风险
            risk_assessment = await self._assess_position_risk(position, kronos_decision)
            
            # 生成建议
            recommendation = await self._generate_position_recommendation(position, kronos_decision)
            
            # 评估紧急程度
            urgency_level = self._assess_urgency(position, kronos_decision, risk_assessment)
            
            # 计算潜在盈亏
            potential_pnl = self._calculate_potential_pnl(position, kronos_decision)
            
            # 建议操作
            suggested_action = self._suggest_action(position, kronos_decision, risk_assessment)
            
            # 生成涨跌预测
            price_prediction = self._generate_price_prediction(position, kronos_decision)
            trend_prediction = self._generate_trend_prediction(kronos_decision)
            confidence_level = kronos_decision.kronos_confidence if kronos_decision else 0.5
            
            return PositionAnalysisResult(
                symbol=symbol,
                current_position=position,
                kronos_decision=kronos_decision,
                risk_assessment=risk_assessment,
                recommendation=recommendation,
                urgency_level=urgency_level,
                potential_pnl=potential_pnl,
                suggested_action=suggested_action,
                price_prediction=price_prediction,
                trend_prediction=trend_prediction,
                confidence_level=confidence_level
            )
            
        except Exception as e:
            self.logger.error(f"分析持仓失败: {e}")
            return None
    
    async def _assess_position_risk(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision]) -> str:
        """评估持仓风险 - 优化版：使用动态权重分配算法融合多种分析方法"""
        try:
            # 基础风险评估
            unrealized_pnl = float(position.get('upl', 0))
            position_value = position.get('position_value', 0)
            symbol = position.get('instId', '')
            
            # 计算风险比例
            if position_value > 0:
                risk_ratio = abs(unrealized_pnl) / position_value
            else:
                risk_ratio = 0
            
            # 确保交易所服务已初始化
            await self._ensure_exchange_service()
            
            # 获取传统技术分析信号
            market_signals = {}
            try:
                market_signals = await self.traditional_analysis_service._get_market_signals(symbol, self.exchange_service)
            except Exception as e:
                self.logger.warning(f"获取传统技术分析信号失败: {e}")
                market_signals = {'confidence': 0.5, 'trend': 'neutral', 'technical_indicators': {}}
            
            # 计算动态权重
            weights = self._calculate_dynamic_weights(kronos_decision, market_signals)
            
            # 根据权重策略评估风险
            if weights['weight_source'] == 'traditional_only':
                # 仅使用传统分析
                self.logger.info(f"🔄 {symbol} Kronos模型不可用，使用传统技术分析评估风险")
                return await self._assess_risk_with_traditional_analysis(position, risk_ratio)
            
            elif weights['weight_source'] == 'dynamic_blend':
                # 使用动态权重融合评估
                self.logger.info(f"⚖️ {symbol} 使用动态权重融合评估 - Kronos:{weights['kronos_weight']:.1%}, 传统:{weights['traditional_weight']:.1%}")
                
                # 分别获取两种方法的风险评估
                if kronos_decision:
                    kronos_risk = await self._assess_risk_with_kronos(position, kronos_decision, risk_ratio)
                else:
                    kronos_risk = self._calculate_risk_level_by_ratio(risk_ratio)
                traditional_risk = await self._assess_risk_with_traditional_analysis(position, risk_ratio)
                
                # 融合风险评估结果
                blended_risk = self._blend_risk_assessments(kronos_risk, traditional_risk, weights)
                
                self.logger.info(f"📊 {symbol} 风险评估融合: Kronos={kronos_risk}, 传统={traditional_risk}, 融合={blended_risk}")
                return blended_risk
            
            else:
                # 回退到基础风险评估
                return self._calculate_risk_level_by_ratio(risk_ratio)
                
        except Exception as e:
            self.logger.error(f"评估持仓风险失败: {e}")
            return "未知风险"
    
    def _check_kronos_availability(self, kronos_decision: Optional[KronosEnhancedDecision]) -> bool:
        """检查Kronos模型可用性"""
        if not kronos_decision:
            return False
        
        # 检查Kronos预测数据完整性
        if not kronos_decision.kronos_prediction:
            return False
        
        # 检查置信度是否合理（避免异常低的置信度）
        if kronos_decision.kronos_confidence < 0.3:
            return False
        
        # 检查预测变化是否有效
        predicted_change = kronos_decision.kronos_prediction.price_change_pct
        if predicted_change is None or abs(predicted_change) > 1.0:  # 避免异常大的预测变化
            return False
        
        return True
    
    async def _assess_risk_with_kronos(self, position: Dict[str, Any], kronos_decision: KronosEnhancedDecision, risk_ratio: float) -> str:
        """使用Kronos预测评估风险"""
        kronos_confidence = kronos_decision.kronos_confidence
        predicted_change = kronos_decision.kronos_prediction.price_change_pct
        
        # 正确判断持仓方向
        pos_size = float(position.get('pos', 0))
        original_data = position.get('original_data', {})
        pos_side = original_data.get('side', '')
        
        if pos_side:
            if pos_side == 'long':
                is_long = True
            elif pos_side == 'short':
                is_long = False
            elif pos_side == 'net':
                is_long = pos_size > 0
            else:
                is_long = pos_size > 0  # 默认逻辑
        else:
            is_long = pos_size > 0  # 兼容旧数据
        
        # 如果Kronos预测与持仓方向相反，增加风险
        if (is_long and predicted_change < -0.03) or (not is_long and predicted_change > 0.03):
            if kronos_confidence > 0.7:
                return "极高风险"
            elif kronos_confidence > 0.6:
                return "高风险"
        
        # 基于风险比例和Kronos置信度综合判断
        return self._calculate_risk_level_by_ratio(risk_ratio, None)
    
    async def _assess_risk_with_traditional_analysis(self, position: Dict[str, Any], risk_ratio: float) -> str:
        """使用传统技术分析评估风险"""
        try:
            symbol = position.get('instId', '')
            
            # 确保交易所服务已初始化
            await self._ensure_exchange_service()
            
            # 获取传统技术分析信号
            market_signals = await self.traditional_analysis_service._get_market_signals(symbol, self.exchange_service)
            
            # 基于传统技术分析调整风险评估
            risk_adjustment = self._calculate_traditional_risk_adjustment(position, market_signals)
            
            # 计算调整后的风险等级
            adjusted_risk_ratio = risk_ratio * risk_adjustment
            
            # 计算市场上下文
            market_context = self._calculate_market_context(position, market_signals)
            
            # 记录使用传统分析的情况
            self.logger.info(f"📊 {symbol} 使用传统技术分析: 原始风险比例={risk_ratio:.3f}, 调整系数={risk_adjustment:.3f}, 调整后={adjusted_risk_ratio:.3f}")
            
            return self._calculate_risk_level_by_ratio(adjusted_risk_ratio, market_context)
            
        except Exception as e:
            self.logger.warning(f"传统技术分析评估失败: {e}, 使用基础风险评估")
            return self._calculate_risk_level_by_ratio(risk_ratio)
    
    def _calculate_traditional_risk_adjustment(self, position: Dict[str, Any], market_signals: Dict[str, Any]) -> float:
        """基于传统技术分析计算风险调整系数"""
        try:
            # 基础调整系数
            adjustment = 1.0
            
            # 获取持仓方向
            pos_size = float(position.get('pos', 0))
            original_data = position.get('original_data', {})
            pos_side = original_data.get('side', '')
            
            if pos_side:
                is_long = pos_side == 'long' or (pos_side == 'net' and pos_size > 0)
            else:
                is_long = pos_size > 0
            
            # 基于市场趋势调整
            market_trend = market_signals.get('trend', 'neutral')
            if market_trend == 'bullish' and is_long:
                adjustment *= 0.8  # 顺势持仓，降低风险
            elif market_trend == 'bearish' and not is_long:
                adjustment *= 0.8  # 顺势持仓，降低风险
            elif market_trend == 'bullish' and not is_long:
                adjustment *= 1.3  # 逆势持仓，增加风险
            elif market_trend == 'bearish' and is_long:
                adjustment *= 1.3  # 逆势持仓，增加风险
            
            # 基于技术指标调整
            technical_indicators = market_signals.get('technical_indicators', {})
            
            # RSI指标调整
            rsi_signal = technical_indicators.get('rsi_signal', 'neutral')
            if rsi_signal == 'overbought' and is_long:
                adjustment *= 1.2  # 超买时做多风险增加
            elif rsi_signal == 'oversold' and not is_long:
                adjustment *= 1.2  # 超卖时做空风险增加
            elif rsi_signal == 'oversold' and is_long:
                adjustment *= 0.9  # 超卖时做多风险降低
            elif rsi_signal == 'overbought' and not is_long:
                adjustment *= 0.9  # 超买时做空风险降低
            
            # MACD指标调整
            macd_signal = technical_indicators.get('macd_signal', 'neutral')
            if macd_signal == 'golden_cross' and is_long:
                adjustment *= 0.85  # 金叉时做多风险降低
            elif macd_signal == 'death_cross' and not is_long:
                adjustment *= 0.85  # 死叉时做空风险降低
            elif macd_signal == 'death_cross' and is_long:
                adjustment *= 1.25  # 死叉时做多风险增加
            elif macd_signal == 'golden_cross' and not is_long:
                adjustment *= 1.25  # 金叉时做空风险增加
            
            # 布林带指标调整
            bb_signal = technical_indicators.get('bb_signal', 'neutral')
            if bb_signal == 'near_upper' and is_long:
                adjustment *= 1.15  # 接近上轨做多风险增加
            elif bb_signal == 'near_lower' and not is_long:
                adjustment *= 1.15  # 接近下轨做空风险增加
            elif bb_signal == 'near_lower' and is_long:
                adjustment *= 0.9   # 接近下轨做多风险降低
            elif bb_signal == 'near_upper' and not is_long:
                adjustment *= 0.9   # 接近上轨做空风险降低
            
            # 限制调整范围在合理区间
            adjustment = max(0.5, min(2.0, adjustment))
            
            return adjustment
            
        except Exception as e:
            self.logger.warning(f"计算传统风险调整系数失败: {e}")
            return 1.0  # 返回中性调整系数
    
    def _calculate_risk_level_by_ratio(self, risk_ratio: float, context: Dict[str, Any] = None) -> str:
        """基于风险比例计算风险等级 - 优化版：考虑市场环境和持仓时间"""
        try:
            # 基础风险阈值
            base_thresholds = {
                "极高风险": 0.2,
                "高风险": 0.15,
                "中等风险": 0.1,
                "低风险": 0.05
            }
            
            # 根据上下文调整阈值
            if context:
                adjusted_thresholds = self._adjust_risk_thresholds(base_thresholds, context)
            else:
                adjusted_thresholds = base_thresholds
            
            # 计算风险等级
            if risk_ratio > adjusted_thresholds["极高风险"]:
                return "极高风险"
            elif risk_ratio > adjusted_thresholds["高风险"]:
                return "高风险"
            elif risk_ratio > adjusted_thresholds["中等风险"]:
                return "中等风险"
            elif risk_ratio > adjusted_thresholds["低风险"]:
                return "低风险"
            else:
                return "极低风险"
                
        except Exception as e:
            self.logger.warning(f"风险等级计算失败: {e}")
            # 回退到基础计算
            if risk_ratio > 0.2:
                return "极高风险"
            elif risk_ratio > 0.15:
                return "高风险"
            elif risk_ratio > 0.1:
                return "中等风险"
            elif risk_ratio > 0.05:
                return "低风险"
            else:
                return "极低风险"
    
    def _adjust_risk_thresholds(self, base_thresholds: Dict[str, float], context: Dict[str, Any]) -> Dict[str, float]:
        """根据市场环境和持仓情况调整风险阈值"""
        try:
            adjusted = base_thresholds.copy()
            
            # 获取市场波动性
            market_volatility = context.get('market_volatility', 'normal')
            
            # 获取持仓时间（小时）
            position_duration = context.get('position_duration_hours', 0)
            
            # 获取市场趋势强度
            trend_strength = context.get('trend_strength', 0.5)
            
            # 获取流动性状况
            liquidity_score = context.get('liquidity_score', 0.5)
            
            # 根据市场波动性调整
            volatility_adjustment = 1.0
            if market_volatility == 'high':
                volatility_adjustment = 0.8  # 高波动时降低阈值，更敏感
            elif market_volatility == 'low':
                volatility_adjustment = 1.2  # 低波动时提高阈值，更宽松
            
            # 根据持仓时间调整
            duration_adjustment = 1.0
            if position_duration > 72:  # 持仓超过3天
                duration_adjustment = 0.9  # 长期持仓风险阈值稍微降低
            elif position_duration < 4:  # 持仓不到4小时
                duration_adjustment = 1.1  # 短期持仓风险阈值稍微提高
            
            # 根据趋势强度调整
            trend_adjustment = 1.0
            if trend_strength > 0.8:  # 强趋势
                trend_adjustment = 1.1  # 强趋势时可以承受更高风险
            elif trend_strength < 0.3:  # 弱趋势或震荡
                trend_adjustment = 0.9  # 弱趋势时降低风险容忍度
            
            # 根据流动性调整
            liquidity_adjustment = 1.0
            if liquidity_score < 0.3:  # 低流动性
                liquidity_adjustment = 0.8  # 低流动性时降低风险阈值
            elif liquidity_score > 0.8:  # 高流动性
                liquidity_adjustment = 1.1  # 高流动性时可以承受更高风险
            
            # 综合调整因子
            total_adjustment = (volatility_adjustment * duration_adjustment * 
                              trend_adjustment * liquidity_adjustment)
            
            # 应用调整
            for level, threshold in adjusted.items():
                adjusted[level] = threshold * total_adjustment
                # 确保调整后的阈值在合理范围内
                adjusted[level] = max(0.01, min(0.5, adjusted[level]))
            
            self.logger.debug(f"风险阈值调整: 原始={base_thresholds}, 调整后={adjusted}, 调整因子={total_adjustment:.3f}")
            
            return adjusted
            
        except Exception as e:
            self.logger.warning(f"风险阈值调整失败: {e}")
            return base_thresholds
    
    def _calculate_market_context(self, position: Dict[str, Any], market_signals: Dict[str, Any]) -> Dict[str, Any]:
        """计算市场环境上下文信息"""
        try:
            context = {}
            
            # 计算市场波动性
            technical_indicators = market_signals.get('technical_indicators', {})
            volatility_indicators = technical_indicators.get('volatility', {})
            
            if volatility_indicators:
                atr_percentile = volatility_indicators.get('atr_percentile', 50)
                if atr_percentile > 80:
                    context['market_volatility'] = 'high'
                elif atr_percentile < 20:
                    context['market_volatility'] = 'low'
                else:
                    context['market_volatility'] = 'normal'
            else:
                context['market_volatility'] = 'normal'
            
            # 计算趋势强度
            trend_info = market_signals.get('trend_analysis', {})
            trend_strength = trend_info.get('strength', 0.5)
            context['trend_strength'] = trend_strength
            
            # 估算流动性评分（基于交易量和价差）
            volume_info = market_signals.get('volume_analysis', {})
            volume_percentile = volume_info.get('volume_percentile', 50)
            spread_info = market_signals.get('spread_analysis', {})
            spread_score = spread_info.get('spread_score', 0.5)
            
            # 综合流动性评分
            liquidity_score = (volume_percentile / 100 * 0.6 + spread_score * 0.4)
            context['liquidity_score'] = liquidity_score
            
            # 计算持仓时间（如果有相关信息）
            position_time = position.get('position_time')
            if position_time:
                from datetime import datetime
                try:
                    if isinstance(position_time, str):
                        pos_time = datetime.fromisoformat(position_time.replace('Z', '+00:00'))
                    else:
                        pos_time = position_time
                    
                    duration = (datetime.now() - pos_time).total_seconds() / 3600
                    context['position_duration_hours'] = duration
                except:
                    context['position_duration_hours'] = 0
            else:
                context['position_duration_hours'] = 0
            
            return context
            
        except Exception as e:
            self.logger.warning(f"计算市场上下文失败: {e}")
            return {
                'market_volatility': 'normal',
                'trend_strength': 0.5,
                'liquidity_score': 0.5,
                'position_duration_hours': 0
            }
    
    def _calculate_dynamic_weights(self, kronos_decision: Optional[KronosEnhancedDecision], 
                                 market_signals: Dict[str, Any]) -> Dict[str, float]:
        """动态权重分配算法 - 根据模型可用性和置信度智能调整权重"""
        try:
            # 检查Kronos模型可用性
            kronos_available = self._check_kronos_availability(kronos_decision)
            
            if not kronos_available:
                # Kronos不可用，完全使用传统分析
                return {
                    'kronos_weight': 0.0,
                    'traditional_weight': 1.0,
                    'confidence_score': market_signals.get('confidence', 0.5),
                    'weight_source': 'traditional_only'
                }
            
            # Kronos可用，动态调整权重
            kronos_confidence = kronos_decision.kronos_confidence
            traditional_confidence = market_signals.get('confidence', 0.5)
            
            # 基础权重
            base_kronos_weight = self.weight_config['kronos_base_weight']
            base_traditional_weight = self.weight_config['traditional_base_weight']
            
            # 根据置信度调整权重
            confidence_diff = kronos_confidence - traditional_confidence
            adjustment_factor = self.weight_config['weight_adjustment_factor']
            
            # 动态调整
            if kronos_confidence > self.weight_config['confidence_threshold']:
                # Kronos置信度高，增加其权重
                kronos_weight = min(0.9, base_kronos_weight + abs(confidence_diff) * adjustment_factor)
            else:
                # Kronos置信度低，降低其权重
                kronos_weight = max(0.3, base_kronos_weight - abs(confidence_diff) * adjustment_factor)
            
            traditional_weight = 1.0 - kronos_weight
            
            # 计算综合置信度
            combined_confidence = (kronos_confidence * kronos_weight + 
                                 traditional_confidence * traditional_weight)
            
            return {
                'kronos_weight': kronos_weight,
                'traditional_weight': traditional_weight,
                'confidence_score': combined_confidence,
                'weight_source': 'dynamic_blend',
                'kronos_confidence': kronos_confidence,
                'traditional_confidence': traditional_confidence
            }
            
        except Exception as e:
            self.logger.warning(f"动态权重计算失败: {e}, 使用默认权重")
            return {
                'kronos_weight': 0.5,
                'traditional_weight': 0.5,
                'confidence_score': 0.5,
                'weight_source': 'fallback_default'
            }
    
    def _blend_risk_assessments(self, kronos_risk: str, traditional_risk: str, 
                              weights: Dict[str, float]) -> str:
        """融合Kronos和传统分析的风险评估结果"""
        try:
            # 风险等级映射
            risk_levels = {
                "极低风险": 1,
                "低风险": 2,
                "中等风险": 3,
                "高风险": 4,
                "极高风险": 5,
                "未知风险": 3  # 默认中等风险
            }
            
            # 反向映射
            level_names = {1: "极低风险", 2: "低风险", 3: "中等风险", 4: "高风险", 5: "极高风险"}
            
            # 获取风险等级数值
            kronos_level = risk_levels.get(kronos_risk, 3)
            traditional_level = risk_levels.get(traditional_risk, 3)
            
            # 加权平均
            kronos_weight = weights.get('kronos_weight', 0.5)
            traditional_weight = weights.get('traditional_weight', 0.5)
            
            blended_level = (kronos_level * kronos_weight + 
                           traditional_level * traditional_weight)
            
            # 四舍五入到最近的整数等级
            final_level = round(blended_level)
            final_level = max(1, min(5, final_level))  # 确保在有效范围内
            
            return level_names[final_level]
            
        except Exception as e:
            self.logger.warning(f"风险评估融合失败: {e}")
            # 返回更保守的风险评估
            if kronos_risk in ["极高风险", "高风险"] or traditional_risk in ["极高风险", "高风险"]:
                return "高风险"
            else:
                return "中等风险"
    
    def _blend_recommendations(self, kronos_rec: str, traditional_rec: str, 
                             weights: Dict[str, float], symbol: str) -> str:
        """融合Kronos和传统分析的建议"""
        try:
            kronos_weight = weights.get('kronos_weight', 0.5)
            traditional_weight = weights.get('traditional_weight', 0.5)
            confidence_score = weights.get('confidence_score', 0.5)
            
            # 如果某个权重占主导地位（>0.8），直接使用其建议
            if kronos_weight > 0.8:
                return f"[Kronos主导] {kronos_rec}"
            elif traditional_weight > 0.8:
                return f"[技术分析主导] {traditional_rec}"
            
            # 否则提供融合建议
            confidence_desc = "高" if confidence_score > 0.7 else "中" if confidence_score > 0.5 else "低"
            
            return (f"[融合分析-{confidence_desc}置信度] "
                   f"Kronos建议({kronos_weight:.1%}权重): {kronos_rec.split('，')[0]}; "
                   f"技术分析建议({traditional_weight:.1%}权重): {traditional_rec.split('，')[0]}。"
                   f"综合建议: 谨慎操作，关注市场变化")
            
        except Exception as e:
            self.logger.warning(f"建议融合失败: {e}")
            return f"融合分析建议谨慎持有{symbol}仓位，密切关注市场动态"
    
    def _calculate_traditional_analysis_weights(self, market_signals: Dict[str, Any]) -> Dict[str, float]:
        """计算传统技术分析各组件的权重"""
        try:
            # 获取基础权重配置
            base_weights = self.traditional_weight_config.copy()
            
            # 根据市场信号调整权重
            technical_indicators = market_signals.get('technical_indicators', {})
            trend_analysis = market_signals.get('trend_analysis', {})
            volume_analysis = market_signals.get('volume_analysis', {})
            
            # 趋势强度调整
            trend_strength = trend_analysis.get('strength', 0.5)
            if trend_strength > 0.8:
                # 强趋势时增加趋势权重
                base_weights['trend_weight'] *= 1.3
                base_weights['momentum_weight'] *= 1.2
            elif trend_strength < 0.3:
                # 弱趋势时增加波动性和支撑阻力权重
                base_weights['volatility_weight'] *= 1.4
                base_weights['support_resistance_weight'] *= 1.3
            
            # 成交量异常调整
            volume_anomaly = volume_analysis.get('anomaly_score', 0)
            if volume_anomaly > 0.7:
                # 成交量异常时增加成交量权重
                base_weights['volume_weight'] *= 1.5
            
            # 波动性调整
            volatility_info = technical_indicators.get('volatility', {})
            if volatility_info:
                volatility_percentile = volatility_info.get('atr_percentile', 50)
                if volatility_percentile > 80:
                    # 高波动时增加波动性权重
                    base_weights['volatility_weight'] *= 1.3
                elif volatility_percentile < 20:
                    # 低波动时降低波动性权重
                    base_weights['volatility_weight'] *= 0.8
            
            # 归一化权重
            total_weight = sum(base_weights.values())
            normalized_weights = {k: v / total_weight for k, v in base_weights.items()}
            
            return normalized_weights
            
        except Exception as e:
            self.logger.warning(f"计算传统分析权重失败: {e}")
            return self.traditional_weight_config.copy()
    
    def _calculate_traditional_composite_score(self, market_signals: Dict[str, Any], 
                                             position: Dict[str, Any]) -> Dict[str, Any]:
        """计算传统技术分析的综合评分"""
        try:
            # 获取权重
            weights = self._calculate_traditional_analysis_weights(market_signals)
            
            # 计算各组件评分
            trend_score = self._calculate_trend_score(market_signals, position)
            momentum_score = self._calculate_momentum_score(market_signals, position)
            volatility_score = self._calculate_volatility_score(market_signals, position)
            volume_score = self._calculate_volume_score(market_signals, position)
            support_resistance_score = self._calculate_support_resistance_score(market_signals, position)
            
            # 加权综合评分
            composite_score = (
                trend_score * weights['trend_weight'] +
                momentum_score * weights['momentum_weight'] +
                volatility_score * weights['volatility_weight'] +
                volume_score * weights['volume_weight'] +
                support_resistance_score * weights['support_resistance_weight']
            )
            
            # 计算置信度
            confidence = self._calculate_traditional_confidence(market_signals, weights)
            
            return {
                'composite_score': composite_score,
                'confidence': confidence,
                'component_scores': {
                    'trend': trend_score,
                    'momentum': momentum_score,
                    'volatility': volatility_score,
                    'volume': volume_score,
                    'support_resistance': support_resistance_score
                },
                'weights': weights
            }
            
        except Exception as e:
            self.logger.warning(f"计算传统分析综合评分失败: {e}")
            return {
                'composite_score': 0.5,
                'confidence': 0.5,
                'component_scores': {},
                'weights': self.traditional_weight_config.copy()
            }
    
    def _calculate_trend_score(self, market_signals: Dict[str, Any], position: Dict[str, Any]) -> float:
        """计算趋势评分"""
        try:
            trend_analysis = market_signals.get('trend_analysis', {})
            trend_direction = trend_analysis.get('direction', 'neutral')
            trend_strength = trend_analysis.get('strength', 0.5)
            
            # 获取持仓方向
            pos_size = float(position.get('pos', 0))
            is_long = pos_size > 0
            
            # 基础评分
            if trend_direction == 'bullish' and is_long:
                base_score = 0.7 + (trend_strength * 0.3)  # 顺势多头
            elif trend_direction == 'bearish' and not is_long:
                base_score = 0.7 + (trend_strength * 0.3)  # 顺势空头
            elif trend_direction == 'bullish' and not is_long:
                base_score = 0.3 - (trend_strength * 0.2)  # 逆势空头
            elif trend_direction == 'bearish' and is_long:
                base_score = 0.3 - (trend_strength * 0.2)  # 逆势多头
            else:
                base_score = 0.5  # 中性
            
            return max(0.0, min(1.0, base_score))
            
        except Exception as e:
            self.logger.warning(f"计算趋势评分失败: {e}")
            return 0.5
    
    def _calculate_momentum_score(self, market_signals: Dict[str, Any], position: Dict[str, Any]) -> float:
        """计算动量评分"""
        try:
            technical_indicators = market_signals.get('technical_indicators', {})
            
            # RSI评分
            rsi_signal = technical_indicators.get('rsi_signal', 'neutral')
            rsi_score = 0.5
            if rsi_signal == 'oversold':
                rsi_score = 0.7  # 超卖有利于多头
            elif rsi_signal == 'overbought':
                rsi_score = 0.3  # 超买不利于多头
            
            # MACD评分
            macd_signal = technical_indicators.get('macd_signal', 'neutral')
            macd_score = 0.5
            if macd_signal == 'golden_cross':
                macd_score = 0.8  # 金叉看涨
            elif macd_signal == 'death_cross':
                macd_score = 0.2  # 死叉看跌
            
            # 综合动量评分
            momentum_score = (rsi_score * 0.4 + macd_score * 0.6)
            
            # 根据持仓方向调整
            pos_size = float(position.get('pos', 0))
            is_long = pos_size > 0
            
            if not is_long:
                momentum_score = 1.0 - momentum_score  # 空头时反转评分
            
            return max(0.0, min(1.0, momentum_score))
            
        except Exception as e:
            self.logger.warning(f"计算动量评分失败: {e}")
            return 0.5
    
    def _calculate_volatility_score(self, market_signals: Dict[str, Any], position: Dict[str, Any]) -> float:
        """计算波动性评分"""
        try:
            technical_indicators = market_signals.get('technical_indicators', {})
            volatility_info = technical_indicators.get('volatility', {})
            
            if not volatility_info:
                return 0.5
            
            # ATR百分位数
            atr_percentile = volatility_info.get('atr_percentile', 50)
            
            # 波动性评分（高波动性对短期持仓不利，对长期持仓影响较小）
            if atr_percentile > 80:
                volatility_score = 0.3  # 高波动性风险较高
            elif atr_percentile < 20:
                volatility_score = 0.7  # 低波动性相对安全
            else:
                volatility_score = 0.5  # 正常波动性
            
            return volatility_score
            
        except Exception as e:
            self.logger.warning(f"计算波动性评分失败: {e}")
            return 0.5
    
    def _calculate_volume_score(self, market_signals: Dict[str, Any], position: Dict[str, Any]) -> float:
        """计算成交量评分"""
        try:
            volume_analysis = market_signals.get('volume_analysis', {})
            
            if not volume_analysis:
                return 0.5
            
            # 成交量百分位数
            volume_percentile = volume_analysis.get('volume_percentile', 50)
            
            # 成交量异常评分
            anomaly_score = volume_analysis.get('anomaly_score', 0)
            
            # 基础成交量评分
            if volume_percentile > 80:
                base_score = 0.7  # 高成交量通常是好信号
            elif volume_percentile < 20:
                base_score = 0.4  # 低成交量可能缺乏确认
            else:
                base_score = 0.5
            
            # 异常调整
            if anomaly_score > 0.7:
                base_score += 0.1  # 成交量异常可能预示变化
            
            return max(0.0, min(1.0, base_score))
            
        except Exception as e:
            self.logger.warning(f"计算成交量评分失败: {e}")
            return 0.5
    
    def _calculate_support_resistance_score(self, market_signals: Dict[str, Any], position: Dict[str, Any]) -> float:
        """计算支撑阻力评分"""
        try:
            technical_indicators = market_signals.get('technical_indicators', {})
            
            # 布林带信号
            bb_signal = technical_indicators.get('bb_signal', 'neutral')
            
            bb_score = 0.5
            if bb_signal == 'near_lower':
                bb_score = 0.7  # 接近下轨，支撑位
            elif bb_signal == 'near_upper':
                bb_score = 0.3  # 接近上轨，阻力位
            
            # 根据持仓方向调整
            pos_size = float(position.get('pos', 0))
            is_long = pos_size > 0
            
            if not is_long:
                bb_score = 1.0 - bb_score  # 空头时反转评分
            
            return max(0.0, min(1.0, bb_score))
            
        except Exception as e:
            self.logger.warning(f"计算支撑阻力评分失败: {e}")
            return 0.5
    
    def _calculate_traditional_confidence(self, market_signals: Dict[str, Any], weights: Dict[str, float]) -> float:
        """计算传统分析的置信度"""
        try:
            # 基础置信度
            base_confidence = market_signals.get('confidence', 0.5)
            
            # 根据信号一致性调整置信度
            technical_indicators = market_signals.get('technical_indicators', {})
            
            # 计算信号一致性
            bullish_signals = 0
            bearish_signals = 0
            total_signals = 0
            
            # RSI信号
            rsi_signal = technical_indicators.get('rsi_signal', 'neutral')
            if rsi_signal != 'neutral':
                total_signals += 1
                if rsi_signal == 'oversold':
                    bullish_signals += 1
                elif rsi_signal == 'overbought':
                    bearish_signals += 1
            
            # MACD信号
            macd_signal = technical_indicators.get('macd_signal', 'neutral')
            if macd_signal != 'neutral':
                total_signals += 1
                if macd_signal == 'golden_cross':
                    bullish_signals += 1
                elif macd_signal == 'death_cross':
                    bearish_signals += 1
            
            # 趋势信号
            trend_analysis = market_signals.get('trend_analysis', {})
            trend_direction = trend_analysis.get('direction', 'neutral')
            if trend_direction != 'neutral':
                total_signals += 1
                if trend_direction == 'bullish':
                    bullish_signals += 1
                elif trend_direction == 'bearish':
                    bearish_signals += 1
            
            # 计算一致性
            if total_signals > 0:
                consistency = max(bullish_signals, bearish_signals) / total_signals
                confidence_adjustment = consistency * 0.3  # 最多调整30%
                adjusted_confidence = base_confidence + confidence_adjustment
            else:
                adjusted_confidence = base_confidence
            
            return max(0.1, min(0.95, adjusted_confidence))
            
        except Exception as e:
            self.logger.warning(f"计算传统分析置信度失败: {e}")
            return 0.5
    
    async def _generate_position_recommendation(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision]) -> str:
        """生成持仓建议 - 优化版：当Kronos模型不可用时使用传统技术分析"""
        try:
            symbol = position.get('instId', '').replace('-USDT-SWAP', '')
            pos_size = float(position.get('pos', 0))
            
            # 正确判断持仓方向
            original_data = position.get('original_data', {})
            pos_side = original_data.get('side', '')
            
            if pos_side:
                if pos_side == 'long':
                    is_long = True
                elif pos_side == 'short':
                    is_long = False
                elif pos_side == 'net':
                    is_long = pos_size > 0
                else:
                    is_long = pos_size > 0  # 默认逻辑
            else:
                is_long = pos_size > 0  # 兼容旧数据
            
            # 检查Kronos模型可用性
            kronos_available = self._check_kronos_availability(kronos_decision)
            
            if kronos_available and kronos_decision:
                # 使用Kronos预测生成建议
                return self._generate_kronos_recommendation(symbol, is_long, kronos_decision)
            else:
                # Kronos模型不可用，使用传统技术分析
                self.logger.info(f"🔄 {symbol} Kronos模型不可用，使用传统技术分析生成建议")
                return await self._generate_traditional_recommendation(symbol, is_long, position)
                    
        except Exception as e:
            self.logger.error(f"生成持仓建议失败: {e}")
            return "建议谨慎操作"
    
    def _generate_kronos_recommendation(self, symbol: str, is_long: bool, kronos_decision: KronosEnhancedDecision) -> str:
        """基于Kronos预测生成建议"""
        kronos_confidence = kronos_decision.kronos_confidence
        predicted_change = kronos_decision.kronos_prediction.price_change_pct if kronos_decision.kronos_prediction else 0
        
        # 生成详细建议
        if is_long:  # 多头持仓
            if predicted_change > 0.03 and kronos_confidence > 0.7:
                return f"Kronos强烈看涨{symbol}，建议继续持有或适度加仓"
            elif predicted_change < -0.03 and kronos_confidence > 0.7:
                return f"Kronos强烈看跌{symbol}，建议立即减仓或止损"
            elif predicted_change < -0.02 and kronos_confidence > 0.6:
                return f"Kronos看跌{symbol}，建议谨慎减仓"
            else:
                return f"Kronos对{symbol}预测中性，建议保持当前仓位"
        else:  # 空头持仓
            if predicted_change < -0.03 and kronos_confidence > 0.7:
                return f"Kronos强烈看跌{symbol}，建议继续持有或适度加仓"
            elif predicted_change > 0.03 and kronos_confidence > 0.7:
                return f"Kronos强烈看涨{symbol}，建议立即减仓或止损"
            elif predicted_change > 0.02 and kronos_confidence > 0.6:
                return f"Kronos看涨{symbol}，建议谨慎减仓"
            else:
                return f"Kronos对{symbol}预测中性，建议保持当前仓位"
    
    async def _generate_traditional_recommendation(self, symbol: str, is_long: bool, position: Dict[str, Any]) -> str:
        """基于传统技术分析生成建议"""
        try:
            # 确保交易所服务已初始化
            await self._ensure_exchange_service()
            
            # 获取传统技术分析信号
            full_symbol = position.get('instId', '')
            market_signals = await self.traditional_analysis_service._get_market_signals(full_symbol, self.exchange_service)
            
            # 基于传统技术分析生成建议
            recommendation = self._analyze_traditional_signals(symbol, is_long, market_signals, position)
            
            self.logger.info(f"📊 {symbol} 传统技术分析建议: {recommendation}")
            return recommendation
            
        except Exception as e:
            self.logger.warning(f"传统技术分析建议生成失败: {e}")
            return f"传统分析暂不可用，建议谨慎持有{symbol}仓位"
    
    def _analyze_traditional_signals(self, symbol: str, is_long: bool, market_signals: Dict[str, Any], position: Dict[str, Any]) -> str:
        """分析传统技术信号并生成建议"""
        try:
            # 获取市场趋势和技术指标
            market_trend = market_signals.get('trend', 'neutral')
            technical_indicators = market_signals.get('technical_indicators', {})
            confidence = market_signals.get('confidence', 0.5)
            
            # 获取关键技术指标
            rsi_signal = technical_indicators.get('rsi_signal', 'neutral')
            macd_signal = technical_indicators.get('macd_signal', 'neutral')
            bb_signal = technical_indicators.get('bb_signal', 'neutral')
            
            # 计算未实现盈亏比例
            unrealized_pnl = float(position.get('upl', 0))
            position_value = position.get('position_value', 0)
            pnl_ratio = (unrealized_pnl / position_value) if position_value > 0 else 0
            
            # 基于持仓方向和技术分析生成建议
            if is_long:  # 多头持仓
                return self._generate_long_position_advice(symbol, market_trend, technical_indicators, confidence, pnl_ratio)
            else:  # 空头持仓
                return self._generate_short_position_advice(symbol, market_trend, technical_indicators, confidence, pnl_ratio)
                
        except Exception as e:
            self.logger.warning(f"分析传统信号失败: {e}")
            return f"技术分析信号复杂，建议谨慎持有{symbol}仓位"
    
    def _generate_long_position_advice(self, symbol: str, trend: str, indicators: Dict[str, Any], confidence: float, pnl_ratio: float) -> str:
        """生成多头持仓建议"""
        rsi_signal = indicators.get('rsi_signal', 'neutral')
        macd_signal = indicators.get('macd_signal', 'neutral')
        bb_signal = indicators.get('bb_signal', 'neutral')
        
        # 强烈看涨信号
        if (trend == 'bullish' and confidence > 0.7 and 
            macd_signal == 'golden_cross' and rsi_signal != 'overbought'):
            return f"技术分析强烈看涨{symbol}，建议继续持有或适度加仓"
        
        # 看涨信号
        elif trend == 'bullish' and confidence > 0.6:
            if rsi_signal == 'overbought':
                return f"技术分析看涨{symbol}但RSI超买，建议谨慎持有"
            else:
                return f"技术分析看涨{symbol}，建议继续持有"
        
        # 看跌信号
        elif (trend == 'bearish' and confidence > 0.6) or macd_signal == 'death_cross':
            if pnl_ratio < -0.1:  # 已有较大亏损
                return f"技术分析看跌{symbol}且持仓亏损，建议考虑止损"
            else:
                return f"技术分析看跌{symbol}，建议谨慎减仓"
        
        # 超买警告
        elif rsi_signal == 'overbought' and bb_signal == 'near_upper':
            return f"技术分析显示{symbol}超买，建议部分止盈"
        
        # 超卖机会
        elif rsi_signal == 'oversold' and bb_signal == 'near_lower':
            return f"技术分析显示{symbol}超卖，当前多头仓位有利"
        
        # 中性建议
        else:
            if pnl_ratio > 0.1:  # 有较好盈利
                return f"技术分析中性，{symbol}持仓盈利良好，建议持有并设置止盈"
            elif pnl_ratio < -0.05:  # 有一定亏损
                return f"技术分析中性，{symbol}持仓有亏损，建议谨慎观察"
            else:
                return f"技术分析中性，建议保持{symbol}当前仓位"
    
    def _generate_short_position_advice(self, symbol: str, trend: str, indicators: Dict[str, Any], confidence: float, pnl_ratio: float) -> str:
        """生成空头持仓建议"""
        rsi_signal = indicators.get('rsi_signal', 'neutral')
        macd_signal = indicators.get('macd_signal', 'neutral')
        bb_signal = indicators.get('bb_signal', 'neutral')
        
        # 强烈看跌信号
        if (trend == 'bearish' and confidence > 0.7 and 
            macd_signal == 'death_cross' and rsi_signal != 'oversold'):
            return f"技术分析强烈看跌{symbol}，建议继续持有或适度加仓"
        
        # 看跌信号
        elif trend == 'bearish' and confidence > 0.6:
            if rsi_signal == 'oversold':
                return f"技术分析看跌{symbol}但RSI超卖，建议谨慎持有"
            else:
                return f"技术分析看跌{symbol}，建议继续持有"
        
        # 看涨信号
        elif (trend == 'bullish' and confidence > 0.6) or macd_signal == 'golden_cross':
            if pnl_ratio < -0.1:  # 已有较大亏损
                return f"技术分析看涨{symbol}且空头亏损，建议考虑止损"
            else:
                return f"技术分析看涨{symbol}，建议谨慎减仓"
        
        # 超卖警告
        elif rsi_signal == 'oversold' and bb_signal == 'near_lower':
            return f"技术分析显示{symbol}超卖，建议部分止盈"
        
        # 超买机会
        elif rsi_signal == 'overbought' and bb_signal == 'near_upper':
            return f"技术分析显示{symbol}超买，当前空头仓位有利"
        
        # 中性建议
        else:
            if pnl_ratio > 0.1:  # 有较好盈利
                return f"技术分析中性，{symbol}空头盈利良好，建议持有并设置止盈"
            elif pnl_ratio < -0.05:  # 有一定亏损
                return f"技术分析中性，{symbol}空头有亏损，建议谨慎观察"
            else:
                return f"技术分析中性，建议保持{symbol}当前仓位"
    
    def _assess_urgency(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision], risk_assessment: str) -> str:
        """评估操作紧急程度"""
        try:
            if risk_assessment in ["极高风险", "高风险"]:
                return "紧急"
            
            if kronos_decision and kronos_decision.kronos_confidence > 0.8:
                predicted_change = kronos_decision.kronos_prediction.price_change_pct
            
            # 修复：确保 predicted_change 是小数形式，不是百分比形式
            if abs(predicted_change) > 1:
                predicted_change = predicted_change / 100 if kronos_decision.kronos_prediction else 0
                if abs(predicted_change) > 0.05:  # 预测变化超过5%
                    return "高"
            
            if risk_assessment == "中等风险":
                return "中等"
            
            return "低"
            
        except Exception as e:
            return "未知"
    
    def _calculate_potential_pnl(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision]) -> float:
        """计算潜在盈亏"""
        try:
            if not kronos_decision or not kronos_decision.kronos_prediction:
                return 0.0
            
            # 获取持仓价值和方向
            pos_size = float(position.get('pos', 0))
            
            # 优先使用 position_value_usd，如果没有则使用 pos * markPx 计算
            original_data = position.get('original_data', {})
            position_value = original_data.get('position_value_usd') or position.get('position_value_usd')
            
            if not position_value:
                # 如果没有 position_value_usd，则使用 pos_size * mark_price 计算
                mark_price = float(position.get('markPx', 0))
                position_value = abs(pos_size) * mark_price
            else:
                position_value = float(position_value)
            
            predicted_change = kronos_decision.kronos_prediction.price_change_pct
            
            # 修复：确保 predicted_change 是小数形式，不是百分比形式
            if abs(predicted_change) > 1:
                predicted_change = predicted_change / 100
            
            # 基于持仓价值计算潜在盈亏
            if pos_size > 0:  # 多头
                potential_pnl = position_value * predicted_change
            else:  # 空头
                potential_pnl = position_value * (-predicted_change)
            
            # 添加详细调试日志 - 使用实际交易对名称
            symbol = position.get('instId', 'UNKNOWN')
            
            return potential_pnl
            
        except Exception as e:
            self.logger.error(f"计算潜在盈亏失败: {e}")
            return 0.0
    
    def _suggest_action(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision], risk_assessment: str) -> str:
        """建议具体操作"""
        try:
            if risk_assessment in ["极高风险", "高风险"]:
                return "立即减仓或止损"
            
            if not kronos_decision:
                return "保持观望"
            
            final_action = kronos_decision.final_action
            kronos_confidence = kronos_decision.kronos_confidence
            
            if "强烈" in final_action and kronos_confidence > 0.8:
                if "买入" in final_action:
                    return "考虑加仓"
                elif "卖出" in final_action:
                    return "考虑减仓"
            elif "买入" in final_action and kronos_confidence > 0.7:
                return "可适度加仓"
            elif "卖出" in final_action and kronos_confidence > 0.7:
                return "可适度减仓"
            else:
                return "保持当前仓位"
                
        except Exception as e:
            return "谨慎操作"
    
    def _generate_price_prediction(self, position: Dict[str, Any], kronos_decision: Optional[KronosEnhancedDecision]) -> Optional[Dict[str, Any]]:
        """生成价格预测详情"""
        try:
            if not kronos_decision or not kronos_decision.kronos_prediction:
                return None
            
            current_price = float(position.get('markPx', 0))
            predicted_change = kronos_decision.kronos_prediction.price_change_pct
            confidence = kronos_decision.kronos_confidence
            
            # 计算预测价格
            predicted_price = current_price * (1 + predicted_change)
            price_change_abs = predicted_price - current_price
            
            # 预测时间范围（基于Kronos模型的预测周期）
            prediction_timeframe = "24小时"  # 可以根据实际模型调整
            
            # 生成预测等级
            if abs(predicted_change) >= 0.1:  # 10%以上
                magnitude = "极大"
            elif abs(predicted_change) >= 0.05:  # 5-10%
                magnitude = "较大"
            elif abs(predicted_change) >= 0.02:  # 2-5%
                magnitude = "中等"
            elif abs(predicted_change) >= 0.01:  # 1-2%
                magnitude = "较小"
            else:  # 1%以下
                magnitude = "微小"
            
            # 预测方向
            if predicted_change > 0.01:
                direction = "上涨"
                direction_emoji = "📈"
            elif predicted_change < -0.01:
                direction = "下跌"
                direction_emoji = "📉"
            else:
                direction = "横盘"
                direction_emoji = "➡️"
            
            # 置信度等级
            if confidence >= 0.8:
                confidence_level = "极高"
            elif confidence >= 0.7:
                confidence_level = "高"
            elif confidence >= 0.6:
                confidence_level = "中等"
            elif confidence >= 0.5:
                confidence_level = "较低"
            else:
                confidence_level = "低"
            
            return {
                "current_price": current_price,
                "predicted_price": predicted_price,
                "price_change_abs": price_change_abs,
                "price_change_pct": predicted_change * 100,
                "direction": direction,
                "direction_emoji": direction_emoji,
                "magnitude": magnitude,
                "confidence": confidence,
                "confidence_level": confidence_level,
                "timeframe": prediction_timeframe,
                "prediction_summary": f"{direction_emoji} 预测{prediction_timeframe}内{direction}{magnitude}幅度 ({predicted_change*100:+.1f}%)"
            }
            
        except Exception as e:
            self.logger.error(f"生成价格预测失败: {e}")
            return None
    
    def _generate_trend_prediction(self, kronos_decision: Optional[KronosEnhancedDecision]) -> Optional[str]:
        """生成趋势预测"""
        try:
            if not kronos_decision or not kronos_decision.kronos_prediction:
                return "趋势不明"
            
            predicted_change = kronos_decision.kronos_prediction.price_change_pct
            confidence = kronos_decision.kronos_confidence
            
            # 基于预测变化和置信度生成趋势描述
            if confidence >= 0.8:
                if predicted_change >= 0.08:  # 8%以上为强烈看涨
                    return "强烈看涨"
                elif predicted_change >= 0.03:  # 3-8%为温和看涨
                    return "温和看涨"
                elif predicted_change <= -0.08:  # -8%以下为强烈看跌
                    return "强烈看跌"
                elif predicted_change <= -0.03:  # -3%到-8%为温和看跌
                    return "温和看跌"
                else:
                    return "震荡整理"
            elif confidence >= 0.6:
                if predicted_change >= 0.05:  # 中等置信度需要更大变化
                    return "偏向看涨"
                elif predicted_change <= -0.05:
                    return "偏向看跌"
                else:
                    return "方向不明"
            else:
                return "趋势不明"
                
        except Exception as e:
            self.logger.error(f"生成趋势预测失败: {e}")
            return "趋势不明"
    
    async def _generate_comprehensive_report(self, analysis_results: List[PositionAnalysisResult]) -> Dict[str, Any]:
        """生成综合报告"""
        try:
            # 确保交易所服务已初始化
            await self._ensure_exchange_service()
            
            # 获取账户总权益
            async with self.exchange_service as exchange:
                account_balance = await exchange.get_account_balance()
            total_equity = account_balance.get('total_equity', 0)
            
            # 计算持仓统计
            total_positions = len(analysis_results)
            high_risk_count = sum(1 for r in analysis_results if r.risk_assessment in ["极高风险", "高风险"])
            urgent_actions = sum(1 for r in analysis_results if r.urgency_level in ["紧急", "高"])
            
            # 计算总持仓价值和盈亏
            total_position_value = 0
            total_unrealized_pnl = 0
            total_potential_pnl = 0
            
            for result in analysis_results:
                # 优先使用原始数据中的position_value_usd
                original_data = result.current_position.get('original_data', {})
                position_value = original_data.get('position_value_usd', result.current_position.get('position_value', 0))
                unrealized_pnl = float(result.current_position.get('upl', 0))
                
                total_position_value += position_value
                total_unrealized_pnl += unrealized_pnl
                total_potential_pnl += result.potential_pnl
            
            # 计算资金利用率
            fund_utilization = (total_position_value / total_equity * 100) if total_equity > 0 else 0
            
            # 计算整体杠杆
            overall_leverage = total_position_value / total_equity if total_equity > 0 else 0
            
            # 计算盈亏比例
            pnl_percentage = (total_unrealized_pnl / total_equity * 100) if total_equity > 0 else 0
            
            # 风险分布
            risk_distribution = {}
            for result in analysis_results:
                risk = result.risk_assessment
                risk_distribution[risk] = risk_distribution.get(risk, 0) + 1
            
            # 紧急操作建议
            urgent_recommendations = [
                r for r in analysis_results 
                if r.urgency_level in ["紧急", "高"]
            ]
            
            # 计算风险评分 (0-100)
            risk_score = self._calculate_risk_score(analysis_results, pnl_percentage, fund_utilization)
            
            # 计算综合评分 (0-100)
            overall_score = self._calculate_overall_score(risk_score, pnl_percentage, fund_utilization)
            
            return {
                "total_positions": total_positions,
                "total_equity": total_equity,
                "total_position_value": total_position_value,
                "total_unrealized_pnl": total_unrealized_pnl,
                "pnl_percentage": pnl_percentage,
                "fund_utilization": fund_utilization,
                "overall_leverage": overall_leverage,
                "high_risk_positions": high_risk_count,
                "urgent_actions_needed": urgent_actions,
                "total_potential_pnl": total_potential_pnl,
                "risk_distribution": risk_distribution,
                "risk_score": risk_score,
                "overall_score": overall_score,
                "urgent_recommendations": urgent_recommendations[:5],  # 最多5个紧急建议
                "analysis_timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"生成综合报告失败: {e}")
            return {}
    
    def _calculate_risk_score(self, analysis_results: List[PositionAnalysisResult], pnl_percentage: float, fund_utilization: float) -> int:
        """计算风险评分 (0-100, 越高越危险)"""
        try:
            risk_score = 0
            
            # 基于盈亏比例的风险 (30分)
            if pnl_percentage < -10:
                risk_score += 30
            elif pnl_percentage < -5:
                risk_score += 20
            elif pnl_percentage < -2:
                risk_score += 10
            
            # 基于资金利用率的风险 (25分)
            if fund_utilization > 80:
                risk_score += 25
            elif fund_utilization > 60:
                risk_score += 15
            elif fund_utilization > 40:
                risk_score += 8
            
            # 基于持仓风险分布的风险 (25分)
            high_risk_count = sum(1 for r in analysis_results if r.risk_assessment in ["极高风险", "高风险"])
            if analysis_results:
                high_risk_ratio = high_risk_count / len(analysis_results)
                risk_score += int(high_risk_ratio * 25)
            
            # 基于紧急操作需求的风险 (20分)
            urgent_count = sum(1 for r in analysis_results if r.urgency_level in ["紧急", "高"])
            if analysis_results:
                urgent_ratio = urgent_count / len(analysis_results)
                risk_score += int(urgent_ratio * 20)
            
            return min(risk_score, 100)
            
        except Exception as e:
            self.logger.error(f"计算风险评分失败: {e}")
            return 50
    
    def _calculate_overall_score(self, risk_score: int, pnl_percentage: float, fund_utilization: float) -> int:
        """计算综合评分 (0-100, 越高越好)"""
        try:
            base_score = 100 - risk_score
            
            # 盈利加分
            if pnl_percentage > 5:
                base_score += 10
            elif pnl_percentage > 2:
                base_score += 5
            
            # 合理资金利用率加分
            if 20 <= fund_utilization <= 50:
                base_score += 5
            
            return max(0, min(base_score, 100))
            
        except Exception as e:
            self.logger.error(f"计算综合评分失败: {e}")
            return 50
    
    async def _send_position_analysis_notification(self, report: Dict[str, Any], analysis_results: List[PositionAnalysisResult]):
        """发送持仓分析通知"""
        try:
            # 确保通知服务已初始化
            await self._ensure_notification_service()
            
            # 检查通知服务是否正确初始化
            if self.notification_service is None:
                self.logger.error("❌ 通知服务初始化失败")
                return False
            
            self.logger.info(f"🔍 通知服务已初始化: {type(self.notification_service).__name__}")
            # 获取报告数据
            total_positions = report.get("total_positions", 0)
            total_equity = report.get("total_equity", 0)
            total_unrealized_pnl = report.get("total_unrealized_pnl", 0)
            pnl_percentage = report.get("pnl_percentage", 0)
            fund_utilization = report.get("fund_utilization", 0)
            overall_leverage = report.get("overall_leverage", 0)
            high_risk_count = report.get("high_risk_positions", 0)
            urgent_actions = report.get("urgent_actions_needed", 0)
            overall_score = report.get("overall_score", 0)
            risk_score = report.get("risk_score", 0)
            
            # 构建通知标题
            if urgent_actions > 0:
                title = f"🚨 Kronos持仓分析: {urgent_actions}个紧急操作"
                priority = "high"
            elif high_risk_count > 0:
                title = f"⚠️ Kronos持仓分析: {high_risk_count}个高风险持仓"
                priority = "medium"
            else:
                title = f"📊 Kronos持仓分析: 账户状态良好"
                priority = "medium"  # 改为medium确保持仓分析总是能推送
            
            # 风险等级判断
            if risk_score >= 70:
                risk_level = "🔴 HIGH"
            elif risk_score >= 40:
                risk_level = "🟡 MEDIUM"
            elif risk_score >= 20:
                risk_level = "🟢 LOW"
            else:
                risk_level = "🔵 VERY LOW"
            
            # 计算基于初始本金的整体盈亏
            from app.core.config import get_settings
            settings = get_settings()
            initial_capital = settings.account_initial_capital
            # 整体盈亏 = (当前权益 - 初始本金) / 初始本金 * 100%
            overall_pnl = total_equity - initial_capital
            overall_pnl_percentage = (overall_pnl / initial_capital * 100) if initial_capital > 0 else 0
            
            # 风险等级文字转换
            risk_level_text = {
                "🔴 HIGH": "极高风险",
                "🟠 MEDIUM": "高风险", 
                "🟡 MEDIUM": "中等风险",
                "🟢 LOW": "低风险",
                "🔵 VERY LOW": "极低风险"
            }.get(risk_level, "未知")
            
            # 构建通知内容 - 新格式
            message_parts = [
                f"📊 **详细信息:**",
                f"  • 总权益: ${total_equity:,.2f} USDT",
                f"  • 初始本金: ${initial_capital:,.2f} USDT",
                f"  • 整体盈亏: ${overall_pnl:+,.2f} ({overall_pnl_percentage:+.1f}%)",
                f"  • 未实现盈亏: ${total_unrealized_pnl:+,.2f} ({pnl_percentage:+.1f}%)",
                f"  • 资金利用率: {fund_utilization:.1f}%",
                f"  • 整体杠杆: {overall_leverage:.1f}x",
                f"  • 风险评分: {risk_score}/100",
            ]
            
            # 添加集中度风险
            if total_positions > 0:
                max_position_value = max(r.current_position.get('original_data', {}).get('position_value_usd', r.current_position.get('position_value', 0)) for r in analysis_results)
                concentration_risk = (max_position_value / total_equity * 100) if total_equity > 0 else 0
                message_parts.append(f"  • 集中度风险: {concentration_risk:.1f}%")
            
            message_parts.append("")
            
            # 添加风险分布
            risk_distribution = report.get("risk_distribution", {})
            if risk_distribution:
                message_parts.append("🎯 风险分布:")
                for risk_level, count in risk_distribution.items():
                    risk_emoji = {
                        "极高风险": "🔴",
                        "高风险": "🟠", 
                        "中等风险": "🟡",
                        "低风险": "🟢",
                        "极低风险": "🔵"
                    }.get(risk_level, "⚪")
                    message_parts.append(f"  {risk_emoji} {risk_level}: {count}个")
                message_parts.append("")
            
            # 添加紧急建议
            urgent_recommendations = report.get("urgent_recommendations", [])
            if urgent_recommendations:
                message_parts.append("🚨 紧急操作建议:")
                for i, rec in enumerate(urgent_recommendations[:3], 1):
                    symbol = rec.symbol.replace('-USDT-SWAP', '')
                    message_parts.append(f"{i}. **{symbol}**: {rec.suggested_action}")
                    message_parts.append(f"   💡 {rec.recommendation}")
                    
                    # 添加预测信息到紧急建议
                    if rec.price_prediction:
                        pred = rec.price_prediction
                        message_parts.append(f"   {pred['direction_emoji']} {pred['prediction_summary']}")
                    
                    if rec.potential_pnl != 0:
                        message_parts.append(f"   💰 预期: {rec.potential_pnl:+.2f} USDT")
                    message_parts.append("")
            
            # 添加详细持仓分析
            message_parts.append("📋 **详细持仓分析:**")
            for i, result in enumerate(analysis_results, 1):
                symbol = result.symbol.replace('-USDT-SWAP', '')
                pos_size = float(result.current_position.get('pos', 0))
                
                # 正确判断持仓方向 - 优先使用posSide字段
                original_data = result.current_position.get('original_data', {})
                pos_side = original_data.get('side', '')
                
                if pos_side:
                    # 使用交易所返回的 posSide 字段
                    if pos_side == 'long':
                        direction = "多头"
                    elif pos_side == 'short':
                        direction = "空头"
                    elif pos_side == 'net':
                        # 买卖模式，通过pos值判断
                        direction = "空头" if pos_size < 0 else "多头"
                    else:
                        direction = "未知"
                else:
                    # 兼容旧数据，通过pos值判断
                    direction = "空头" if pos_size < 0 else "多头"
                # 优先使用原始数据中的position_value_usd，如果没有则使用position_value
                original_data = result.current_position.get('original_data', {})
                position_value = original_data.get('position_value_usd', result.current_position.get('position_value', 0))
                unrealized_pnl = float(result.current_position.get('upl', 0))
                mark_price = float(result.current_position.get('markPx', 0))
                
                # 计算占比
                position_ratio = (position_value / total_equity * 100) if total_equity > 0 else 0
                
                # 盈亏颜色
                pnl_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                
                message_parts.append(f"{i}. **{symbol}** ({direction})")
                # 获取开仓价格 - 尝试多个可能的字段
                original_data = result.current_position.get('original_data', {})
                entry_price = (
                    original_data.get('avgPx') or
                    original_data.get('avg_px') or  # 可能的字段名
                    result.current_position.get('avgPx') or  # 直接从 current_position
                    result.current_position.get('avg_px') or  # 可能的字段名
                    result.current_position.get('avg_price') or  # 平均价格
                    result.current_position.get('entry_price') or  # 开仓价格
                    mark_price  # 最后回退到标记价格
                )
                message_parts.append(f"   💰 仓位: {abs(pos_size):.4f}")
                message_parts.append(f"   📈 开仓价: ${float(entry_price):,.4f}")
                message_parts.append(f"   💲 现价: ${mark_price:,.4f}")
                message_parts.append(f"   📊 价值: ${position_value:,.2f} ({position_ratio:.1f}%)")
                
                # 处理币本位合约的盈亏显示
                if symbol.endswith('-USD-SWAP'):
                    # 币本位合约，盈亏以基础币种计算
                    base_currency = symbol.split('-')[0]  # 提取基础币种，如 DOGE
                    # 计算USDT等值：币种盈亏 × 当前币价
                    usdt_equivalent = unrealized_pnl * mark_price
                    message_parts.append(f"   {pnl_emoji} 盈亏: {unrealized_pnl:+,.2f} {base_currency} (≈${usdt_equivalent:+,.2f})")
                else:
                    # USDT本位合约，盈亏以USDT计算
                    message_parts.append(f"   {pnl_emoji} 盈亏: ${unrealized_pnl:+,.2f}")
                
                # 添加涨跌预测信息
                if result.price_prediction:
                    pred = result.price_prediction
                    message_parts.append(f"   {pred['direction_emoji']} 预测: {pred['prediction_summary']}")
                    message_parts.append(f"   🎯 目标价: ${pred['predicted_price']:.4f} (置信度: {pred['confidence_level']})")
                
                # 添加趋势预测
                if result.trend_prediction and result.trend_prediction != "趋势不明":
                    trend_emoji = {
                        "强烈看涨": "🚀",
                        "温和看涨": "📈", 
                        "偏向看涨": "↗️",
                        "强烈看跌": "💥",
                        "温和看跌": "📉",
                        "偏向看跌": "↘️",
                        "震荡整理": "🔄"
                    }.get(result.trend_prediction, "➡️")
                    message_parts.append(f"   {trend_emoji} 趋势: {result.trend_prediction}")
                
                # 只显示有意义的Kronos建议（过滤"持有观望"）
                if result.kronos_decision and result.kronos_decision.final_action:
                    action = result.kronos_decision.final_action
                    if "持有观望" not in action and "观望" not in action:
                        confidence = result.kronos_decision.kronos_confidence
                        message_parts.append(f"   🤖 Kronos: {action} (置信度: {confidence:.2f})")
                
                message_parts.append(f"   ⚠️ 风险: {result.risk_assessment}")
                
                # 只显示需要操作的建议
                if result.suggested_action not in ["保持当前仓位", "保持观望", "谨慎操作"]:
                    message_parts.append(f"   🔧 建议: {result.suggested_action}")
                
                message_parts.append("")
            
            message_parts.extend([
                "💡 **重要提醒**:",
                "• 本分析基于Kronos AI预测，仅供参考",
                "• 请结合市场情况和个人风险承受能力决策",
                "• 高风险持仓建议及时调整",
                "",
                f"⏰ 下次分析: {(datetime.now() + timedelta(minutes=30)).strftime('%H:%M')}"
            ])
            
            message = "\n".join(message_parts)
            
            # 发送通知
            from app.services.notification.core_notification_service import NotificationContent, NotificationType, NotificationPriority
            
            # 转换优先级字符串为枚举
            priority_map = {
                'low': NotificationPriority.LOW,
                'medium': NotificationPriority.NORMAL,
                'high': NotificationPriority.HIGH,
                'urgent': NotificationPriority.URGENT
            }
            
            notification_content = NotificationContent(
                type=NotificationType.POSITION_ANALYSIS,
                priority=priority_map.get(priority, NotificationPriority.NORMAL),
                title=title,
                message=message
            )
            
            self.logger.info(f"🔍 准备发送通知: 类型={notification_content.type.value}, 优先级={notification_content.priority.value}, 标题={title[:50]}...")
            
            results = await self.notification_service.send_notification(notification_content)
            
            self.logger.info(f"🔍 通知发送结果: {results}")
            
            # 检查是否有任何渠道发送成功
            success = any(results.values()) if isinstance(results, dict) else bool(results)
            
            if success:
                trading_logger.info(f"📢 已发送Kronos持仓分析通知: {total_positions}个持仓")
                successful_channels = [ch for ch, result in results.items() if result] if isinstance(results, dict) else []
                if successful_channels:
                    self.logger.info(f"✅ 通知发送成功的渠道: {', '.join(successful_channels)}")
            else:
                self.logger.warning(f"⚠️ 所有通知渠道发送失败: {results}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"发送持仓分析通知失败: {e}")
            return False
    
    def _should_send_notification(self, analysis_results: List[PositionAnalysisResult] = None) -> bool:
        """检查是否应该发送通知（基于冷却时间和紧急程度）"""
        if not self.last_notification_time:
            self.logger.info("📅 首次运行，允许发送通知")
            return True
        
        # 根据分析结果确定冷却时间
        cooldown_minutes = self._get_dynamic_cooldown_minutes(analysis_results)
        time_since_last = datetime.now() - self.last_notification_time
        cooldown_seconds = cooldown_minutes * 60
        
        should_send = time_since_last.total_seconds() >= cooldown_seconds
        
        self.logger.info(f"🕐 冷却检查: 上次通知时间 {self.last_notification_time.strftime('%H:%M:%S')}, "
                        f"已过去 {time_since_last.total_seconds()/60:.1f}分钟, "
                        f"冷却期 {cooldown_minutes}分钟, "
                        f"允许发送: {should_send}")
        
        return should_send
    
    def _get_dynamic_cooldown_minutes(self, analysis_results: List[PositionAnalysisResult] = None) -> int:
        """根据分析结果动态确定冷却时间"""
        if not analysis_results:
            return self.analysis_config['notification_cooldown_minutes']
        
        # 检查是否有紧急情况
        urgent_count = sum(1 for r in analysis_results if r.urgency_level == "紧急")
        high_risk_count = sum(1 for r in analysis_results if r.risk_assessment in ["极高风险", "高风险"])
        
        if urgent_count > 0:
            return self.analysis_config['urgent_notification_cooldown_minutes']
        elif high_risk_count > 0:
            return self.analysis_config['high_risk_notification_cooldown_minutes']
        else:
            return self.analysis_config['notification_cooldown_minutes']
    
    def _get_cooldown_remaining_minutes(self, analysis_results: List[PositionAnalysisResult] = None) -> float:
        """获取剩余冷却时间（分钟）"""
        if not self.last_notification_time:
            return 0.0
        
        cooldown_minutes = self._get_dynamic_cooldown_minutes(analysis_results)
        time_since_last = datetime.now() - self.last_notification_time
        cooldown_seconds = cooldown_minutes * 60
        
        remaining_seconds = cooldown_seconds - time_since_last.total_seconds()
        return max(0.0, remaining_seconds / 60)
    
    async def get_manual_analysis(self) -> Dict[str, Any]:
        """手动获取持仓分析 - 不发送通知，仅返回分析结果"""
        try:
            self.logger.info(f"🔍 手动获取持仓分析... (实例ID: {id(self)})")
            
            # 获取当前持仓
            positions = await self._get_current_positions()
            if not positions:
                self.logger.info("📊 当前无持仓，跳过分析")
                return {"status": "no_positions"}
            
            # 分析每个持仓
            analysis_results = []
            for position in positions:
                result = await self._analyze_position(position)
                if result:
                    analysis_results.append(result)
            
            # 生成综合报告
            report = await self._generate_comprehensive_report(analysis_results)
            
            # 手动分析不发送通知，只返回结果
            self.logger.info(f"✅ 手动持仓分析完成，分析了 {len(analysis_results)} 个持仓 (未发送通知)")
            
            return {
                "status": "success",
                "positions_analyzed": len(analysis_results),
                "report": report,
                "analysis_time": datetime.now().isoformat(),
                "notification_sent": False
            }
            
        except Exception as e:
            self.logger.error(f"❌ 手动持仓分析失败: {e}")
            return {"status": "error", "error": str(e)}
    
    async def run_startup_analysis(self) -> Dict[str, Any]:
        """启动时运行持仓分析（强制推送）"""
        self.logger.info("🚀 启动时Kronos持仓分析 - 强制推送模式")
        return await self.run_scheduled_analysis(force_notification=True)


# 全局服务实例
_kronos_position_service = None

async def get_kronos_position_service() -> KronosPositionAnalysisService:
    """获取Kronos持仓分析服务实例"""
    global _kronos_position_service
    if _kronos_position_service is None:
        _kronos_position_service = KronosPositionAnalysisService()
    return _kronos_position_service
