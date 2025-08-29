# -*- coding: utf-8 -*-
"""
回测数据模式
Backtest Data Schemas
"""

from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, validator
from decimal import Decimal


class BacktestStatusEnum(str, Enum):
    """回测状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BacktestTypeEnum(str, Enum):
    """回测类型枚举"""
    SINGLE = "single"
    PORTFOLIO = "portfolio"
    OPTIMIZATION = "optimization"
    COMPARISON = "comparison"


class OptimizationMethodEnum(str, Enum):
    """优化方法枚举"""
    GRID_SEARCH = "grid_search"
    RANDOM_SEARCH = "random_search"
    GENETIC_ALGORITHM = "genetic_algorithm"
    BAYESIAN_OPTIMIZATION = "bayesian_optimization"


class RiskLevelEnum(str, Enum):
    """风险级别枚举"""
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class PositionSideEnum(str, Enum):
    """持仓方向枚举"""
    LONG = "long"
    SHORT = "short"


class OrderTypeEnum(str, Enum):
    """订单类型枚举"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


# 基础模式
class BaseBacktestSchema(BaseModel):
    """回测基础模式"""
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: float(v)
        }


class StrategyParameterSchema(BaseBacktestSchema):
    """策略参数模式"""
    name: str = Field(..., description="参数名称")
    min_value: Union[int, float] = Field(..., description="最小值")
    max_value: Union[int, float] = Field(..., description="最大值")
    step: Union[int, float] = Field(..., description="步长")
    param_type: str = Field(default="float", description="参数类型")
    description: str = Field(default="", description="参数描述")
    
    @validator('param_type')
    def validate_param_type(cls, v):
        if v not in ['int', 'float']:
            raise ValueError('参数类型必须是 int 或 float')
        return v


class RiskManagementConfigSchema(BaseBacktestSchema):
    """风险管理配置模式"""
    max_position_size: float = Field(default=0.1, ge=0.01, le=1.0, description="最大仓位比例")
    max_daily_drawdown: float = Field(default=0.05, ge=0.01, le=0.5, description="最大日回撤")
    max_total_drawdown: float = Field(default=0.20, ge=0.05, le=1.0, description="最大总回撤")
    position_size_method: str = Field(default="fixed", description="仓位计算方法")
    stop_loss_method: str = Field(default="technical", description="止损方法")
    take_profit_method: str = Field(default="technical", description="止盈方法")
    risk_reward_ratio: float = Field(default=2.0, ge=0.5, le=10.0, description="风险收益比")
    enable_position_sizing: bool = Field(default=True, description="启用仓位管理")
    enable_dynamic_stops: bool = Field(default=True, description="启用动态止损")
    
    @validator('position_size_method')
    def validate_position_size_method(cls, v):
        if v not in ['fixed', 'kelly', 'volatility', 'percent_risk']:
            raise ValueError('仓位计算方法不支持')
        return v
    
    @validator('stop_loss_method')
    def validate_stop_loss_method(cls, v):
        if v not in ['fixed', 'technical', 'volatility', 'trailing']:
            raise ValueError('止损方法不支持')
        return v


class PortfolioConfigSchema(BaseBacktestSchema):
    """投资组合配置模式"""
    symbols: List[str] = Field(..., min_items=2, max_items=50, description="交易对列表")
    weights: Optional[Dict[str, float]] = Field(None, description="权重分配")
    rebalance_frequency: str = Field(default="weekly", description="重新平衡频率")
    max_correlation: float = Field(default=0.8, ge=0.0, le=1.0, description="最大相关性")
    min_symbols: int = Field(default=3, ge=2, le=10, description="最少交易对数量")
    max_symbols: int = Field(default=10, ge=5, le=50, description="最多交易对数量")
    
    @validator('symbols')
    def validate_symbols(cls, v):
        if len(set(v)) != len(v):
            raise ValueError('交易对列表不能有重复')
        return [s.upper() for s in v]
    
    @validator('weights')
    def validate_weights(cls, v, values):
        if v is not None:
            symbols = values.get('symbols', [])
            if len(v) != len(symbols):
                raise ValueError('权重数量必须与交易对数量一致')
            if abs(sum(v.values()) - 1.0) > 0.01:
                raise ValueError('权重总和必须等于1.0')
        return v
    
    @validator('rebalance_frequency')
    def validate_rebalance_frequency(cls, v):
        if v not in ['daily', 'weekly', 'monthly', 'quarterly']:
            raise ValueError('重新平衡频率不支持')
        return v


class BacktestRequestSchema(BaseBacktestSchema):
    """回测请求模式"""
    symbol: str = Field(..., description="交易对")
    start_date: str = Field(..., description="开始日期 (YYYY-MM-DD)")
    end_date: str = Field(..., description="结束日期 (YYYY-MM-DD)")
    timeframe: str = Field(default="1h", description="时间周期")
    initial_balance: float = Field(default=10000.0, gt=0, description="初始资金")
    strategy_type: str = Field(default="supertrend", description="策略类型")
    use_ml: bool = Field(default=True, description="是否使用ML增强")
    ml_weight: float = Field(default=0.1, ge=0.0, le=1.0, description="ML权重")
    risk_config: Optional[RiskManagementConfigSchema] = Field(None, description="风险管理配置")
    
    @validator('symbol')
    def validate_symbol(cls, v):
        return v.upper()
    
    @validator('start_date', 'end_date')
    def validate_date_format(cls, v):
        try:
            datetime.fromisoformat(v)
            return v
        except ValueError:
            raise ValueError('日期格式不正确，应为 YYYY-MM-DD')
    
    @validator('timeframe')
    def validate_timeframe(cls, v):
        valid_timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
        if v not in valid_timeframes:
            raise ValueError(f'时间周期不支持，支持: {valid_timeframes}')
        return v


class PortfolioBacktestRequestSchema(BaseBacktestSchema):
    """投资组合回测请求模式"""
    portfolio_config: PortfolioConfigSchema = Field(..., description="投资组合配置")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    timeframe: str = Field(default="1h", description="时间周期")
    initial_balance: float = Field(default=100000.0, gt=0, description="初始资金")
    risk_config: Optional[RiskManagementConfigSchema] = Field(None, description="风险管理配置")
    rebalance_threshold: float = Field(default=0.05, ge=0.01, le=0.5, description="重新平衡阈值")


class OptimizationRequestSchema(BaseBacktestSchema):
    """策略优化请求模式"""
    symbol: str = Field(..., description="交易对")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    timeframe: str = Field(default="1h", description="时间周期")
    initial_balance: float = Field(default=10000.0, gt=0, description="初始资金")
    optimization_method: OptimizationMethodEnum = Field(default=OptimizationMethodEnum.GRID_SEARCH, description="优化方法")
    optimization_metric: str = Field(default="sharpe_ratio", description="优化指标")
    max_iterations: int = Field(default=100, ge=10, le=10000, description="最大迭代次数")
    parameters: List[StrategyParameterSchema] = Field(..., min_items=1, description="优化参数")
    
    @validator('optimization_metric')
    def validate_optimization_metric(cls, v):
        valid_metrics = ['sharpe_ratio', 'total_pnl_percent', 'win_rate', 'profit_factor', 'calmar_ratio']
        if v not in valid_metrics:
            raise ValueError(f'优化指标不支持，支持: {valid_metrics}')
        return v


class StrategySchema(BaseBacktestSchema):
    """策略模式"""
    name: str = Field(..., description="策略名称")
    type: str = Field(default="supertrend", description="策略类型")
    params: Dict[str, Any] = Field(default_factory=dict, description="策略参数")
    description: str = Field(default="", description="策略描述")
    
    @validator('type')
    def validate_strategy_type(cls, v):
        valid_types = ['supertrend', 'ml_enhanced', 'macd', 'rsi', 'bollinger_bands']
        if v not in valid_types:
            raise ValueError(f'策略类型不支持，支持: {valid_types}')
        return v


class StrategyComparisonRequestSchema(BaseBacktestSchema):
    """策略比较请求模式"""
    symbol: str = Field(..., description="交易对")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    timeframe: str = Field(default="1h", description="时间周期")
    initial_balance: float = Field(default=10000.0, gt=0, description="初始资金")
    strategies: List[StrategySchema] = Field(..., min_items=2, max_items=10, description="策略列表")


# 响应模式
class BacktestMetricsSchema(BaseBacktestSchema):
    """回测指标模式"""
    total_trades: int = Field(default=0, description="总交易次数")
    winning_trades: int = Field(default=0, description="盈利交易次数")
    losing_trades: int = Field(default=0, description="亏损交易次数")
    win_rate: float = Field(default=0.0, description="胜率")
    
    total_pnl: float = Field(default=0.0, description="总盈亏")
    total_pnl_percent: float = Field(default=0.0, description="总收益率")
    annualized_return: float = Field(default=0.0, description="年化收益率")
    
    max_drawdown: float = Field(default=0.0, description="最大回撤")
    max_drawdown_percent: float = Field(default=0.0, description="最大回撤百分比")
    volatility: float = Field(default=0.0, description="波动率")
    sharpe_ratio: float = Field(default=0.0, description="夏普比率")
    sortino_ratio: float = Field(default=0.0, description="Sortino比率")
    calmar_ratio: float = Field(default=0.0, description="Calmar比率")
    
    avg_win: float = Field(default=0.0, description="平均盈利")
    avg_loss: float = Field(default=0.0, description="平均亏损")
    profit_factor: float = Field(default=0.0, description="盈亏比")
    avg_trade_duration_hours: float = Field(default=0.0, description="平均持仓时间")
    
    max_consecutive_wins: int = Field(default=0, description="最大连续盈利")
    max_consecutive_losses: int = Field(default=0, description="最大连续亏损")
    total_commission: float = Field(default=0.0, description="总手续费")
    
    start_balance: float = Field(default=0.0, description="起始资金")
    end_balance: float = Field(default=0.0, description="结束资金")
    peak_balance: float = Field(default=0.0, description="峰值资金")


class BacktestTradeSchema(BaseBacktestSchema):
    """回测交易记录模式"""
    trade_id: str = Field(..., description="交易ID")
    symbol: str = Field(..., description="交易对")
    side: PositionSideEnum = Field(..., description="交易方向")
    
    entry_price: float = Field(..., description="入场价格")
    exit_price: float = Field(..., description="出场价格")
    quantity: float = Field(..., description="交易数量")
    
    pnl: float = Field(..., description="盈亏金额")
    pnl_percent: float = Field(..., description="盈亏百分比")
    commission: float = Field(default=0.0, description="手续费")
    
    entry_time: datetime = Field(..., description="入场时间")
    exit_time: datetime = Field(..., description="出场时间")
    duration_hours: float = Field(..., description="持仓时长")
    
    entry_reason: str = Field(default="", description="入场原因")
    exit_reason: str = Field(default="", description="出场原因")
    strategy_signals: Dict[str, Any] = Field(default_factory=dict, description="策略信号")


class OptimizationResultSchema(BaseBacktestSchema):
    """优化结果模式"""
    best_params: Dict[str, Any] = Field(..., description="最佳参数")
    best_score: float = Field(..., description="最佳得分")
    optimization_metric: str = Field(..., description="优化指标")
    optimization_time: float = Field(..., description="优化耗时")
    total_combinations: int = Field(..., description="总组合数")
    
    all_results: List[Dict[str, Any]] = Field(default_factory=list, description="所有结果")
    param_sensitivity: Dict[str, Any] = Field(default_factory=dict, description="参数敏感性")
    convergence_history: List[float] = Field(default_factory=list, description="收敛历史")


class PortfolioMetricsSchema(BaseBacktestSchema):
    """投资组合指标模式"""
    portfolio_return: float = Field(default=0.0, description="投资组合收益率")
    portfolio_volatility: float = Field(default=0.0, description="投资组合波动率")
    portfolio_sharpe: float = Field(default=0.0, description="投资组合夏普比率")
    portfolio_max_drawdown: float = Field(default=0.0, description="投资组合最大回撤")
    
    average_correlation: float = Field(default=0.0, description="平均相关性")
    diversification_ratio: float = Field(default=0.0, description="多样化比率")
    var_95: float = Field(default=0.0, description="95% VaR")
    cvar_95: float = Field(default=0.0, description="95% CVaR")
    
    symbol_contributions: Dict[str, Any] = Field(default_factory=dict, description="成分贡献")
    correlation_matrix: Dict[str, Any] = Field(default_factory=dict, description="相关性矩阵")
    risk_events_count: int = Field(default=0, description="风险事件次数")


class RiskEventSchema(BaseBacktestSchema):
    """风险事件模式"""
    event_id: str = Field(..., description="事件ID")
    event_type: str = Field(..., description="事件类型")
    event_time: datetime = Field(..., description="事件时间")
    severity: str = Field(default="medium", description="严重程度")
    
    description: str = Field(default="", description="事件描述")
    trigger_value: Optional[float] = Field(None, description="触发值")
    threshold_value: Optional[float] = Field(None, description="阈值")
    
    affected_symbols: List[str] = Field(default_factory=list, description="受影响的交易对")
    portfolio_impact: Optional[float] = Field(None, description="对投资组合的影响")
    action_taken: str = Field(default="", description="采取的措施")


class BacktestReportSchema(BaseBacktestSchema):
    """回测报告模式"""
    summary: Dict[str, Any] = Field(default_factory=dict, description="摘要信息")
    symbol_analysis: Dict[str, Any] = Field(default_factory=dict, description="交易对分析")
    time_series_analysis: Dict[str, Any] = Field(default_factory=dict, description="时间序列分析")
    risk_analysis: Dict[str, Any] = Field(default_factory=dict, description="风险分析")
    performance_attribution: Dict[str, Any] = Field(default_factory=dict, description="业绩归因")
    recommendations: List[str] = Field(default_factory=list, description="建议")


class BacktestResultSchema(BaseBacktestSchema):
    """回测结果模式"""
    status: str = Field(..., description="回测状态")
    task_type: BacktestTypeEnum = Field(..., description="回测类型")
    
    # 基础结果
    metrics: Optional[BacktestMetricsSchema] = Field(None, description="回测指标")
    trades: List[BacktestTradeSchema] = Field(default_factory=list, description="交易记录")
    balance_history: List[List[Union[str, float]]] = Field(default_factory=list, description="余额历史")
    
    # 高级结果
    portfolio_metrics: Optional[PortfolioMetricsSchema] = Field(None, description="投资组合指标")
    optimization_result: Optional[OptimizationResultSchema] = Field(None, description="优化结果")
    risk_events: List[RiskEventSchema] = Field(default_factory=list, description="风险事件")
    
    # 报告和图表
    report: Optional[BacktestReportSchema] = Field(None, description="详细报告")
    charts: Dict[str, str] = Field(default_factory=dict, description="图表文件路径")
    
    # 配置信息
    config: Dict[str, Any] = Field(default_factory=dict, description="回测配置")
    execution_time: Optional[float] = Field(None, description="执行时间")
    
    # 推荐信息
    recommendations: List[str] = Field(default_factory=list, description="优化建议")


class TaskStatusSchema(BaseBacktestSchema):
    """任务状态模式"""
    task_id: str = Field(..., description="任务ID")
    task_type: BacktestTypeEnum = Field(..., description="任务类型")
    status: BacktestStatusEnum = Field(..., description="任务状态")
    progress: int = Field(default=0, ge=0, le=100, description="执行进度")
    message: str = Field(default="", description="状态消息")
    
    created_at: datetime = Field(..., description="创建时间")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    
    result: Optional[BacktestResultSchema] = Field(None, description="回测结果")
    error: Optional[str] = Field(None, description="错误信息")


class TaskListSchema(BaseBacktestSchema):
    """任务列表模式"""
    total_tasks: int = Field(..., description="总任务数")
    filtered_tasks: int = Field(..., description="过滤后任务数")
    tasks: List[TaskStatusSchema] = Field(..., description="任务列表")


class StrategyComparisonSchema(BaseBacktestSchema):
    """策略比较模式"""
    individual_results: Dict[str, BacktestResultSchema] = Field(..., description="各策略结果")
    comparison: Dict[str, Any] = Field(..., description="比较分析")
    rankings: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict, description="排名结果")
    
    best_return_strategy: Optional[str] = Field(None, description="最佳收益策略")
    best_sharpe_strategy: Optional[str] = Field(None, description="最佳夏普策略")
    recommended_strategy: Optional[str] = Field(None, description="推荐策略")


class BacktestResponseSchema(BaseBacktestSchema):
    """回测响应模式"""
    status: str = Field(..., description="响应状态")
    message: str = Field(..., description="响应消息")
    data: Union[
        BacktestResultSchema,
        TaskStatusSchema,
        StrategyComparisonSchema,
        Dict[str, Any]
    ] = Field(..., description="响应数据")
    
    # 可选字段
    task_id: Optional[str] = Field(None, description="任务ID")
    execution_time: Optional[float] = Field(None, description="执行时间")
    warnings: List[str] = Field(default_factory=list, description="警告信息")


class ExportRequestSchema(BaseBacktestSchema):
    """导出请求模式"""
    task_id: str = Field(..., description="任务ID")
    export_format: str = Field(default="json", description="导出格式")
    include_charts: bool = Field(default=True, description="是否包含图表")
    include_raw_data: bool = Field(default=False, description="是否包含原始数据")
    
    @validator('export_format')
    def validate_export_format(cls, v):
        valid_formats = ['json', 'excel', 'csv', 'pickle']
        if v not in valid_formats:
            raise ValueError(f'导出格式不支持，支持: {valid_formats}')
        return v


class ParameterTemplateSchema(BaseBacktestSchema):
    """参数模板模式"""
    templates: Dict[str, List[StrategyParameterSchema]] = Field(..., description="参数模板")
    usage_example: Dict[str, Any] = Field(..., description="使用示例")
    descriptions: Dict[str, str] = Field(default_factory=dict, description="模板说明")



