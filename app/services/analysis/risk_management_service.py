# -*- coding: utf-8 -*-
"""
风险管理服务
Risk Management Service
"""

from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.core.config import get_settings
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class RiskLevel(Enum):
    """风险级别"""
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class AlertLevel(Enum):
    """警报级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class RiskMetrics:
    """风险指标"""
    var_95: float = 0.0  # 95% VaR
    var_99: float = 0.0  # 99% VaR
    cvar_95: float = 0.0  # 95% CVaR
    cvar_99: float = 0.0  # 99% CVaR
    max_drawdown: float = 0.0  # 最大回撤
    volatility: float = 0.0  # 波动率
    sharpe_ratio: float = 0.0  # 夏普比率
    sortino_ratio: float = 0.0  # Sortino比率
    calmar_ratio: float = 0.0  # Calmar比率
    beta: float = 0.0  # Beta系数
    treynor_ratio: float = 0.0  # Treynor比率
    information_ratio: float = 0.0  # 信息比率
    tracking_error: float = 0.0  # 跟踪误差


@dataclass
class PositionRisk:
    """持仓风险"""
    symbol: str
    position_size: float
    market_value: float
    unrealized_pnl: float
    var_contribution: float
    concentration_risk: float
    liquidity_risk: float
    correlation_risk: float


@dataclass
class RiskAlert:
    """风险警报"""
    alert_id: str
    alert_type: str
    level: AlertLevel
    message: str
    timestamp: datetime
    affected_positions: List[str]
    recommended_actions: List[str]
    threshold_value: float
    current_value: float


class RiskManagementService:
    """风险管理服务"""
    
    def __init__(self):
        self.risk_limits = {
            'max_portfolio_var': 0.05,  # 最大投资组合VaR 5%
            'max_single_position_weight': 0.2,  # 单一持仓最大权重 20%
            'max_sector_concentration': 0.4,  # 单一行业最大集中度 40%
            'max_drawdown_limit': 0.15,  # 最大回撤限制 15%
            'min_liquidity_ratio': 0.1,  # 最小流动性比率 10%
            'max_correlation_exposure': 0.8,  # 最大相关性暴露 80%
            'max_leverage': 3.0,  # 最大杠杆倍数
            'min_sharpe_ratio': 0.5  # 最小夏普比率
        }
        
        self.alert_thresholds = {
            'var_breach': 0.04,  # VaR突破阈值
            'drawdown_warning': 0.10,  # 回撤警告阈值
            'concentration_warning': 0.15,  # 集中度警告阈值
            'correlation_warning': 0.7,  # 相关性警告阈值
            'volatility_spike': 2.0  # 波动率异常倍数
        }
        
        self.active_alerts: List[RiskAlert] = []
        self.risk_history: List[Dict[str, Any]] = []
    
    async def calculate_portfolio_risk(
        self,
        positions: Dict[str, Any],
        market_data: Dict[str, pd.DataFrame],
        lookback_days: int = 252
    ) -> Tuple[RiskMetrics, List[PositionRisk]]:
        """
        计算投资组合风险指标
        
        Args:
            positions: 持仓信息
            market_data: 市场数据
            lookback_days: 回看天数
            
        Returns:
            投资组合风险指标和单个持仓风险
        """
        try:
            logger.info(f"📊 开始计算投资组合风险指标")
            
            # 计算收益率矩阵
            returns_data = {}
            weights = {}
            total_value = sum(pos.get('market_value', 0) for pos in positions.values())
            
            for symbol, position in positions.items():
                if symbol in market_data and not market_data[symbol].empty:
                    # 计算收益率
                    prices = market_data[symbol]['close'].tail(lookback_days)
                    returns = prices.pct_change().dropna()
                    
                    if len(returns) > 20:  # 确保有足够数据
                        returns_data[symbol] = returns
                        weights[symbol] = position.get('market_value', 0) / total_value if total_value > 0 else 0
            
            if not returns_data:
                raise TradingToolError("没有足够的收益率数据计算风险指标")
            
            # 创建收益率矩阵
            returns_df = pd.DataFrame(returns_data).fillna(0)
            weights_array = np.array([weights.get(symbol, 0) for symbol in returns_df.columns])
            
            # 计算投资组合收益率
            portfolio_returns = (returns_df * weights_array).sum(axis=1)
            
            # 计算风险指标
            risk_metrics = await self._calculate_risk_metrics(portfolio_returns, returns_df, weights_array)
            
            # 计算单个持仓风险
            position_risks = await self._calculate_position_risks(
                positions, returns_df, weights, total_value
            )
            
            logger.info(f"✅ 风险指标计算完成: VaR 95% = {risk_metrics.var_95:.2%}")
            
            return risk_metrics, position_risks
            
        except Exception as e:
            logger.error(f"❌ 计算投资组合风险失败: {e}")
            raise TradingToolError(f"风险计算失败: {str(e)}")
    
    async def _calculate_risk_metrics(
        self,
        portfolio_returns: pd.Series,
        returns_df: pd.DataFrame,
        weights: np.ndarray
    ) -> RiskMetrics:
        """计算详细风险指标"""
        try:
            # 基础统计
            mean_return = portfolio_returns.mean()
            std_return = portfolio_returns.std()
            
            # VaR计算
            var_95 = np.percentile(portfolio_returns, 5)
            var_99 = np.percentile(portfolio_returns, 1)
            
            # CVaR计算
            cvar_95 = portfolio_returns[portfolio_returns <= var_95].mean()
            cvar_99 = portfolio_returns[portfolio_returns <= var_99].mean()
            
            # 最大回撤
            cumulative_returns = (1 + portfolio_returns).cumprod()
            rolling_max = cumulative_returns.expanding().max()
            drawdowns = (cumulative_returns - rolling_max) / rolling_max
            max_drawdown = drawdowns.min()
            
            # 年化指标
            annual_return = mean_return * 252
            annual_volatility = std_return * np.sqrt(252)
            
            # 夏普比率
            risk_free_rate = 0.02  # 假设无风险利率2%
            sharpe_ratio = (annual_return - risk_free_rate) / annual_volatility if annual_volatility > 0 else 0
            
            # Sortino比率
            negative_returns = portfolio_returns[portfolio_returns < 0]
            downside_deviation = negative_returns.std() * np.sqrt(252) if len(negative_returns) > 0 else 0
            sortino_ratio = (annual_return - risk_free_rate) / downside_deviation if downside_deviation > 0 else 0
            
            # Calmar比率
            calmar_ratio = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0
            
            # 协方差矩阵
            cov_matrix = returns_df.cov() * 252  # 年化协方差
            
            # Beta计算（相对于等权重市场组合）
            market_returns = returns_df.mean(axis=1)
            beta = np.cov(portfolio_returns, market_returns)[0, 1] / np.var(market_returns) if np.var(market_returns) > 0 else 1
            
            # Treynor比率
            treynor_ratio = (annual_return - risk_free_rate) / beta if beta != 0 else 0
            
            return RiskMetrics(
                var_95=abs(var_95),
                var_99=abs(var_99),
                cvar_95=abs(cvar_95),
                cvar_99=abs(cvar_99),
                max_drawdown=abs(max_drawdown),
                volatility=annual_volatility,
                sharpe_ratio=sharpe_ratio,
                sortino_ratio=sortino_ratio,
                calmar_ratio=calmar_ratio,
                beta=beta,
                treynor_ratio=treynor_ratio
            )
            
        except Exception as e:
            logger.error(f"❌ 计算风险指标失败: {e}")
            return RiskMetrics()
    
    async def _calculate_position_risks(
        self,
        positions: Dict[str, Any],
        returns_df: pd.DataFrame,
        weights: Dict[str, float],
        total_value: float
    ) -> List[PositionRisk]:
        """计算单个持仓风险"""
        position_risks = []
        
        try:
            for symbol, position in positions.items():
                if symbol not in returns_df.columns:
                    continue
                
                position_returns = returns_df[symbol]
                position_weight = weights.get(symbol, 0)
                market_value = position.get('market_value', 0)
                
                # VaR贡献
                var_contribution = abs(np.percentile(position_returns, 5)) * position_weight
                
                # 集中度风险
                concentration_risk = position_weight  # 权重本身就是集中度风险
                
                # 流动性风险（基于波动率代理）
                liquidity_risk = position_returns.std() * np.sqrt(252)
                
                # 相关性风险（与其他持仓的平均相关性）
                other_symbols = [s for s in returns_df.columns if s != symbol]
                if other_symbols:
                    correlations = [returns_df[symbol].corr(returns_df[other]) for other in other_symbols]
                    correlation_risk = np.mean([abs(corr) for corr in correlations if not np.isnan(corr)])
                else:
                    correlation_risk = 0.0
                
                position_risk = PositionRisk(
                    symbol=symbol,
                    position_size=position.get('size', 0),
                    market_value=market_value,
                    unrealized_pnl=position.get('unrealized_pnl', 0),
                    var_contribution=var_contribution,
                    concentration_risk=concentration_risk,
                    liquidity_risk=liquidity_risk,
                    correlation_risk=correlation_risk
                )
                
                position_risks.append(position_risk)
            
            return position_risks
            
        except Exception as e:
            logger.error(f"❌ 计算持仓风险失败: {e}")
            return position_risks
    
    async def check_risk_limits(
        self,
        risk_metrics: RiskMetrics,
        position_risks: List[PositionRisk],
        portfolio_value: float
    ) -> List[RiskAlert]:
        """检查风险限制"""
        alerts = []
        
        try:
            # 检查VaR限制
            if risk_metrics.var_95 > self.risk_limits['max_portfolio_var']:
                alert = RiskAlert(
                    alert_id=f"var_breach_{int(datetime.now().timestamp())}",
                    alert_type="var_breach",
                    level=AlertLevel.WARNING,
                    message=f"投资组合VaR({risk_metrics.var_95:.2%})超过限制({self.risk_limits['max_portfolio_var']:.2%})",
                    timestamp=datetime.now(),
                    affected_positions=[],
                    recommended_actions=["降低风险暴露", "增加对冲", "减少杠杆"],
                    threshold_value=self.risk_limits['max_portfolio_var'],
                    current_value=risk_metrics.var_95
                )
                alerts.append(alert)
            
            # 检查最大回撤
            if risk_metrics.max_drawdown > self.risk_limits['max_drawdown_limit']:
                alert = RiskAlert(
                    alert_id=f"drawdown_breach_{int(datetime.now().timestamp())}",
                    alert_type="drawdown_breach",
                    level=AlertLevel.CRITICAL,
                    message=f"最大回撤({risk_metrics.max_drawdown:.2%})超过限制({self.risk_limits['max_drawdown_limit']:.2%})",
                    timestamp=datetime.now(),
                    affected_positions=[],
                    recommended_actions=["执行止损", "降低仓位", "重新评估策略"],
                    threshold_value=self.risk_limits['max_drawdown_limit'],
                    current_value=risk_metrics.max_drawdown
                )
                alerts.append(alert)
            
            # 检查单一持仓集中度
            for position_risk in position_risks:
                if position_risk.concentration_risk > self.risk_limits['max_single_position_weight']:
                    alert = RiskAlert(
                        alert_id=f"concentration_{position_risk.symbol}_{int(datetime.now().timestamp())}",
                        alert_type="concentration_risk",
                        level=AlertLevel.WARNING,
                        message=f"{position_risk.symbol}持仓占比({position_risk.concentration_risk:.2%})过高",
                        timestamp=datetime.now(),
                        affected_positions=[position_risk.symbol],
                        recommended_actions=["减少该持仓", "增加其他资产", "重新平衡投资组合"],
                        threshold_value=self.risk_limits['max_single_position_weight'],
                        current_value=position_risk.concentration_risk
                    )
                    alerts.append(alert)
            
            # 检查夏普比率
            if risk_metrics.sharpe_ratio < self.risk_limits['min_sharpe_ratio']:
                alert = RiskAlert(
                    alert_id=f"low_sharpe_{int(datetime.now().timestamp())}",
                    alert_type="performance_warning",
                    level=AlertLevel.INFO,
                    message=f"夏普比率({risk_metrics.sharpe_ratio:.2f})低于预期({self.risk_limits['min_sharpe_ratio']:.2f})",
                    timestamp=datetime.now(),
                    affected_positions=[],
                    recommended_actions=["优化策略参数", "降低交易成本", "改善入场时机"],
                    threshold_value=self.risk_limits['min_sharpe_ratio'],
                    current_value=risk_metrics.sharpe_ratio
                )
                alerts.append(alert)
            
            # 更新活动警报
            self.active_alerts.extend(alerts)
            
            # 清理过期警报
            await self._cleanup_expired_alerts()
            
            return alerts
            
        except Exception as e:
            logger.error(f"❌ 检查风险限制失败: {e}")
            return alerts
    
    async def _cleanup_expired_alerts(self, hours: int = 24):
        """清理过期警报"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            self.active_alerts = [
                alert for alert in self.active_alerts 
                if alert.timestamp > cutoff_time
            ]
        except Exception as e:
            logger.error(f"❌ 清理过期警报失败: {e}")
    
    async def calculate_optimal_position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_loss_price: float,
        account_balance: float,
        risk_per_trade: float = 0.02,
        method: str = "fixed_risk"
    ) -> float:
        """
        计算最优仓位大小
        
        Args:
            symbol: 交易对
            entry_price: 入场价格
            stop_loss_price: 止损价格
            account_balance: 账户余额
            risk_per_trade: 单笔交易风险比例
            method: 计算方法
            
        Returns:
            建议仓位大小
        """
        try:
            if method == "fixed_risk":
                # 固定风险法
                risk_amount = account_balance * risk_per_trade
                price_risk = abs(entry_price - stop_loss_price)
                position_size = risk_amount / price_risk if price_risk > 0 else 0
                
            elif method == "kelly":
                # Kelly公式法（需要历史胜率和盈亏比数据）
                win_rate = 0.6  # 假设胜率60%
                avg_win = 0.05  # 假设平均盈利5%
                avg_loss = 0.03  # 假设平均亏损3%
                
                kelly_percent = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
                kelly_percent = max(0, min(kelly_percent, 0.25))  # 限制在0-25%之间
                
                position_value = account_balance * kelly_percent
                position_size = position_value / entry_price
                
            elif method == "volatility":
                # 基于波动率的仓位大小（需要历史波动率数据）
                target_volatility = 0.15  # 目标组合波动率15%
                asset_volatility = 0.30  # 假设资产波动率30%
                
                volatility_weight = target_volatility / asset_volatility
                volatility_weight = max(0, min(volatility_weight, 0.5))  # 限制在0-50%之间
                
                position_value = account_balance * volatility_weight
                position_size = position_value / entry_price
                
            else:
                # 默认固定比例法
                position_value = account_balance * 0.1  # 10%固定比例
                position_size = position_value / entry_price
            
            # 应用最大仓位限制
            max_position_value = account_balance * self.risk_limits['max_single_position_weight']
            max_position_size = max_position_value / entry_price
            
            final_position_size = min(position_size, max_position_size)
            
            logger.info(f"💰 {symbol} 建议仓位大小: {final_position_size:.6f} (方法: {method})")
            
            return final_position_size
            
        except Exception as e:
            logger.error(f"❌ 计算最优仓位大小失败: {e}")
            return 0.0
    
    async def calculate_dynamic_stop_loss(
        self,
        symbol: str,
        entry_price: float,
        position_side: str,
        market_data: pd.DataFrame,
        method: str = "atr"
    ) -> Tuple[float, str]:
        """
        计算动态止损价格
        
        Args:
            symbol: 交易对
            entry_price: 入场价格
            position_side: 持仓方向 (long/short)
            market_data: 市场数据
            method: 计算方法
            
        Returns:
            止损价格和计算依据
        """
        try:
            if market_data.empty or len(market_data) < 20:
                # 数据不足，使用固定百分比
                if position_side == "long":
                    stop_loss = entry_price * 0.95  # 5%止损
                else:
                    stop_loss = entry_price * 1.05
                return stop_loss, "固定百分比止损(5%)"
            
            if method == "atr":
                # ATR止损法
                high = market_data['high']
                low = market_data['low']
                close = market_data['close']
                
                # 计算ATR
                tr1 = high - low
                tr2 = abs(high - close.shift(1))
                tr3 = abs(low - close.shift(1))
                true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                atr = true_range.rolling(window=14).mean().iloc[-1]
                
                if position_side == "long":
                    stop_loss = entry_price - (atr * 2)  # 2倍ATR
                else:
                    stop_loss = entry_price + (atr * 2)
                
                reason = f"ATR止损法(2倍ATR={atr:.4f})"
                
            elif method == "support_resistance":
                # 支撑阻力位止损法
                recent_prices = market_data['close'].tail(50)
                
                if position_side == "long":
                    # 寻找支撑位
                    support_levels = []
                    for i in range(2, len(recent_prices) - 2):
                        if (recent_prices.iloc[i] < recent_prices.iloc[i-1] and 
                            recent_prices.iloc[i] < recent_prices.iloc[i-2] and
                            recent_prices.iloc[i] < recent_prices.iloc[i+1] and 
                            recent_prices.iloc[i] < recent_prices.iloc[i+2]):
                            support_levels.append(recent_prices.iloc[i])
                    
                    if support_levels:
                        stop_loss = max([s for s in support_levels if s < entry_price])
                        reason = f"支撑位止损({stop_loss:.4f})"
                    else:
                        stop_loss = entry_price * 0.95
                        reason = "未找到有效支撑位，使用固定止损"
                else:
                    # 寻找阻力位
                    resistance_levels = []
                    for i in range(2, len(recent_prices) - 2):
                        if (recent_prices.iloc[i] > recent_prices.iloc[i-1] and 
                            recent_prices.iloc[i] > recent_prices.iloc[i-2] and
                            recent_prices.iloc[i] > recent_prices.iloc[i+1] and 
                            recent_prices.iloc[i] > recent_prices.iloc[i+2]):
                            resistance_levels.append(recent_prices.iloc[i])
                    
                    if resistance_levels:
                        stop_loss = min([r for r in resistance_levels if r > entry_price])
                        reason = f"阻力位止损({stop_loss:.4f})"
                    else:
                        stop_loss = entry_price * 1.05
                        reason = "未找到有效阻力位，使用固定止损"
                        
            elif method == "volatility":
                # 波动率止损法
                returns = market_data['close'].pct_change().dropna()
                volatility = returns.std() * np.sqrt(252)  # 年化波动率
                
                daily_volatility = volatility / np.sqrt(252)
                
                if position_side == "long":
                    stop_loss = entry_price * (1 - daily_volatility * 2)  # 2倍日波动率
                else:
                    stop_loss = entry_price * (1 + daily_volatility * 2)
                
                reason = f"波动率止损法(2倍日波动率={daily_volatility:.2%})"
                
            else:
                # 默认固定百分比
                if position_side == "long":
                    stop_loss = entry_price * 0.97  # 3%止损
                else:
                    stop_loss = entry_price * 1.03
                reason = "固定百分比止损(3%)"
            
            logger.info(f"🛑 {symbol} 动态止损: {stop_loss:.4f} ({reason})")
            
            return stop_loss, reason
            
        except Exception as e:
            logger.error(f"❌ 计算动态止损失败: {e}")
            # 返回默认止损
            if position_side == "long":
                return entry_price * 0.95, "计算失败，使用默认止损"
            else:
                return entry_price * 1.05, "计算失败，使用默认止损"
    
    async def monitor_portfolio_health(
        self,
        portfolio_data: Dict[str, Any],
        market_data: Dict[str, pd.DataFrame]
    ) -> Dict[str, Any]:
        """
        监控投资组合健康状况
        
        Args:
            portfolio_data: 投资组合数据
            market_data: 市场数据
            
        Returns:
            健康状况报告
        """
        try:
            logger.info("🏥 开始监控投资组合健康状况")
            
            # 计算风险指标
            risk_metrics, position_risks = await self.calculate_portfolio_risk(
                portfolio_data.get('positions', {}),
                market_data
            )
            
            # 检查风险限制
            alerts = await self.check_risk_limits(
                risk_metrics,
                position_risks,
                portfolio_data.get('total_value', 0)
            )
            
            # 计算健康评分
            health_score = await self._calculate_health_score(risk_metrics, position_risks)
            
            # 生成建议
            recommendations = await self._generate_risk_recommendations(
                risk_metrics, position_risks, alerts
            )
            
            health_report = {
                'timestamp': datetime.now().isoformat(),
                'health_score': health_score,
                'risk_level': self._determine_risk_level(health_score),
                'risk_metrics': {
                    'var_95': risk_metrics.var_95,
                    'max_drawdown': risk_metrics.max_drawdown,
                    'sharpe_ratio': risk_metrics.sharpe_ratio,
                    'volatility': risk_metrics.volatility
                },
                'position_risks': [
                    {
                        'symbol': pr.symbol,
                        'concentration_risk': pr.concentration_risk,
                        'var_contribution': pr.var_contribution,
                        'liquidity_risk': pr.liquidity_risk
                    }
                    for pr in position_risks
                ],
                'active_alerts': [
                    {
                        'type': alert.alert_type,
                        'level': alert.level.value,
                        'message': alert.message,
                        'timestamp': alert.timestamp.isoformat()
                    }
                    for alert in alerts
                ],
                'recommendations': recommendations,
                'summary': {
                    'total_positions': len(position_risks),
                    'high_risk_positions': len([pr for pr in position_risks if pr.concentration_risk > 0.15]),
                    'critical_alerts': len([a for a in alerts if a.level == AlertLevel.CRITICAL]),
                    'warning_alerts': len([a for a in alerts if a.level == AlertLevel.WARNING])
                }
            }
            
            # 记录历史
            self.risk_history.append({
                'timestamp': datetime.now(),
                'health_score': health_score,
                'var_95': risk_metrics.var_95,
                'max_drawdown': risk_metrics.max_drawdown,
                'alerts_count': len(alerts)
            })
            
            # 保持历史记录数量
            if len(self.risk_history) > 1000:
                self.risk_history = self.risk_history[-1000:]
            
            logger.info(f"✅ 投资组合健康监控完成，健康评分: {health_score:.1f}")
            
            return health_report
            
        except Exception as e:
            logger.error(f"❌ 监控投资组合健康状况失败: {e}")
            return {
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
                'health_score': 0.0,
                'risk_level': 'unknown'
            }
    
    async def _calculate_health_score(
        self,
        risk_metrics: RiskMetrics,
        position_risks: List[PositionRisk]
    ) -> float:
        """计算投资组合健康评分(0-100)"""
        try:
            scores = []
            
            # VaR评分 (权重: 25%)
            var_score = max(0, 100 - (risk_metrics.var_95 / 0.1) * 100)  # VaR越低评分越高
            scores.append(('var', var_score, 0.25))
            
            # 夏普比率评分 (权重: 20%)
            sharpe_score = min(100, max(0, risk_metrics.sharpe_ratio * 50))  # 夏普比率2.0对应100分
            scores.append(('sharpe', sharpe_score, 0.20))
            
            # 最大回撤评分 (权重: 20%)
            drawdown_score = max(0, 100 - (risk_metrics.max_drawdown / 0.2) * 100)
            scores.append(('drawdown', drawdown_score, 0.20))
            
            # 集中度评分 (权重: 15%)
            max_concentration = max([pr.concentration_risk for pr in position_risks]) if position_risks else 0
            concentration_score = max(0, 100 - (max_concentration / 0.3) * 100)
            scores.append(('concentration', concentration_score, 0.15))
            
            # 多样化评分 (权重: 10%)
            diversification_score = min(100, len(position_risks) * 10)  # 10个持仓对应100分
            scores.append(('diversification', diversification_score, 0.10))
            
            # 流动性评分 (权重: 10%)
            avg_liquidity_risk = np.mean([pr.liquidity_risk for pr in position_risks]) if position_risks else 0
            liquidity_score = max(0, 100 - (avg_liquidity_risk / 0.5) * 100)
            scores.append(('liquidity', liquidity_score, 0.10))
            
            # 计算加权总分
            total_score = sum(score * weight for _, score, weight in scores)
            
            return round(total_score, 1)
            
        except Exception as e:
            logger.error(f"❌ 计算健康评分失败: {e}")
            return 50.0  # 默认中等评分
    
    def _determine_risk_level(self, health_score: float) -> str:
        """根据健康评分确定风险级别"""
        if health_score >= 80:
            return "低风险"
        elif health_score >= 60:
            return "中等风险"
        elif health_score >= 40:
            return "较高风险"
        elif health_score >= 20:
            return "高风险"
        else:
            return "极高风险"
    
    async def _generate_risk_recommendations(
        self,
        risk_metrics: RiskMetrics,
        position_risks: List[PositionRisk],
        alerts: List[RiskAlert]
    ) -> List[str]:
        """生成风险管理建议"""
        recommendations = []
        
        try:
            # 基于VaR的建议
            if risk_metrics.var_95 > 0.05:
                recommendations.append("🛡️ VaR过高，建议降低风险暴露或增加对冲")
            
            # 基于夏普比率的建议
            if risk_metrics.sharpe_ratio < 1.0:
                recommendations.append("📈 夏普比率偏低，建议优化收益风险比")
            
            # 基于最大回撤的建议
            if risk_metrics.max_drawdown > 0.15:
                recommendations.append("📉 最大回撤过大，建议加强止损管理")
            
            # 基于集中度的建议
            high_concentration_positions = [
                pr.symbol for pr in position_risks 
                if pr.concentration_risk > 0.2
            ]
            if high_concentration_positions:
                recommendations.append(f"⚖️ 以下持仓集中度过高: {', '.join(high_concentration_positions)}")
            
            # 基于相关性的建议
            high_correlation_positions = [
                pr.symbol for pr in position_risks 
                if pr.correlation_risk > 0.8
            ]
            if high_correlation_positions:
                recommendations.append(f"🔗 以下持仓相关性过高: {', '.join(high_correlation_positions)}")
            
            # 基于流动性的建议
            low_liquidity_positions = [
                pr.symbol for pr in position_risks 
                if pr.liquidity_risk > 0.4
            ]
            if low_liquidity_positions:
                recommendations.append(f"💧 以下持仓流动性较差: {', '.join(low_liquidity_positions)}")
            
            # 基于活动警报的建议
            critical_alerts = [a for a in alerts if a.level == AlertLevel.CRITICAL]
            if critical_alerts:
                recommendations.append("🚨 存在紧急风险警报，建议立即采取风控措施")
            
            # 通用建议
            if not recommendations:
                recommendations.append("✅ 当前风险状况良好，建议继续监控")
            
            return recommendations
            
        except Exception as e:
            logger.error(f"❌ 生成风险建议失败: {e}")
            return ["❌ 无法生成风险建议，请检查系统状态"]
    
    def get_risk_limits(self) -> Dict[str, float]:
        """获取当前风险限制"""
        return self.risk_limits.copy()
    
    def update_risk_limits(self, new_limits: Dict[str, float]):
        """更新风险限制"""
        self.risk_limits.update(new_limits)
        logger.info(f"🔧 已更新风险限制: {new_limits}")
    
    def get_active_alerts(self) -> List[RiskAlert]:
        """获取活动警报"""
        return self.active_alerts.copy()
    
    def get_risk_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """获取风险历史记录"""
        cutoff_time = datetime.now() - timedelta(days=days)
        return [
            record for record in self.risk_history 
            if record['timestamp'] > cutoff_time
        ]





