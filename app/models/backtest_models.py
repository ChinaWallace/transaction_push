# -*- coding: utf-8 -*-
"""
回测数据模型
Backtest Data Models
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, JSON
from sqlalchemy.dialects.mysql import LONGTEXT

from app.models.base import BaseModel


class BacktestStatus(str, Enum):
    """回测状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BacktestType(str, Enum):
    """回测类型"""
    SINGLE = "single"
    PORTFOLIO = "portfolio"
    OPTIMIZATION = "optimization"
    COMPARISON = "comparison"


class BacktestTask(BaseModel):
    """回测任务模型"""
    __tablename__ = "backtest_tasks"
    
    task_id = Column(String(36), unique=True, index=True, nullable=False, comment="任务ID")
    task_type = Column(String(20), nullable=False, comment="任务类型")
    status = Column(String(20), default=BacktestStatus.PENDING, comment="任务状态")
    progress = Column(Integer, default=0, comment="执行进度")
    
    # 回测配置
    symbol = Column(String(20), comment="交易对")
    symbols = Column(JSON, comment="交易对列表(投资组合)")
    start_date = Column(DateTime, nullable=False, comment="开始日期")
    end_date = Column(DateTime, nullable=False, comment="结束日期")
    timeframe = Column(String(10), default="1h", comment="时间周期")
    initial_balance = Column(Float, default=10000.0, comment="初始资金")
    
    # 策略配置
    strategy_type = Column(String(50), default="supertrend", comment="策略类型")
    strategy_params = Column(JSON, comment="策略参数")
    risk_config = Column(JSON, comment="风险管理配置")
    
    # 执行信息
    started_at = Column(DateTime, comment="开始执行时间")
    completed_at = Column(DateTime, comment="完成时间")
    execution_time = Column(Float, comment="执行耗时(秒)")
    error_message = Column(Text, comment="错误信息")
    
    # 结果存储
    result_file_path = Column(String(500), comment="结果文件路径")
    result_summary = Column(JSON, comment="结果摘要")
    
    def __repr__(self):
        return f"<BacktestTask(task_id='{self.task_id}', type='{self.task_type}', status='{self.status}')>"


class BacktestResult(BaseModel):
    """回测结果模型"""
    __tablename__ = "backtest_results"
    
    task_id = Column(String(36), unique=True, index=True, nullable=False, comment="任务ID")
    
    # 基础指标
    total_trades = Column(Integer, default=0, comment="总交易次数")
    winning_trades = Column(Integer, default=0, comment="盈利交易次数")
    losing_trades = Column(Integer, default=0, comment="亏损交易次数")
    win_rate = Column(Float, default=0.0, comment="胜率")
    
    # 收益指标
    total_pnl = Column(Float, default=0.0, comment="总盈亏")
    total_pnl_percent = Column(Float, default=0.0, comment="总收益率")
    annualized_return = Column(Float, default=0.0, comment="年化收益率")
    
    # 风险指标
    max_drawdown = Column(Float, default=0.0, comment="最大回撤")
    max_drawdown_percent = Column(Float, default=0.0, comment="最大回撤百分比")
    volatility = Column(Float, default=0.0, comment="波动率")
    sharpe_ratio = Column(Float, default=0.0, comment="夏普比率")
    sortino_ratio = Column(Float, default=0.0, comment="Sortino比率")
    calmar_ratio = Column(Float, default=0.0, comment="Calmar比率")
    
    # 交易指标
    avg_win = Column(Float, default=0.0, comment="平均盈利")
    avg_loss = Column(Float, default=0.0, comment="平均亏损")
    profit_factor = Column(Float, default=0.0, comment="盈亏比")
    avg_trade_duration_hours = Column(Float, default=0.0, comment="平均持仓时间")
    
    # 其他指标
    max_consecutive_wins = Column(Integer, default=0, comment="最大连续盈利")
    max_consecutive_losses = Column(Integer, default=0, comment="最大连续亏损")
    total_commission = Column(Float, default=0.0, comment="总手续费")
    
    # 资金指标
    start_balance = Column(Float, default=0.0, comment="起始资金")
    end_balance = Column(Float, default=0.0, comment="结束资金")
    peak_balance = Column(Float, default=0.0, comment="峰值资金")
    
    def __repr__(self):
        return f"<BacktestResult(task_id='{self.task_id}', total_return={self.total_pnl_percent:.2f}%)>"


class BacktestTrade(BaseModel):
    """回测交易记录模型"""
    __tablename__ = "backtest_trades"
    
    task_id = Column(String(36), index=True, nullable=False, comment="任务ID")
    trade_id = Column(String(100), unique=True, nullable=False, comment="交易ID")
    
    # 交易基本信息
    symbol = Column(String(20), nullable=False, comment="交易对")
    side = Column(String(10), nullable=False, comment="交易方向")
    
    # 价格信息
    entry_price = Column(Float, nullable=False, comment="入场价格")
    exit_price = Column(Float, nullable=False, comment="出场价格")
    quantity = Column(Float, nullable=False, comment="交易数量")
    
    # 盈亏信息
    pnl = Column(Float, nullable=False, comment="盈亏金额")
    pnl_percent = Column(Float, nullable=False, comment="盈亏百分比")
    commission = Column(Float, default=0.0, comment="手续费")
    
    # 时间信息
    entry_time = Column(DateTime, nullable=False, comment="入场时间")
    exit_time = Column(DateTime, nullable=False, comment="出场时间")
    duration_hours = Column(Float, comment="持仓时长(小时)")
    
    # 策略信息
    entry_reason = Column(String(200), comment="入场原因")
    exit_reason = Column(String(200), comment="出场原因")
    strategy_signals = Column(JSON, comment="策略信号详情")
    
    # 风险管理
    stop_loss_price = Column(Float, comment="止损价格")
    take_profit_price = Column(Float, comment="止盈价格")
    risk_reward_ratio = Column(Float, comment="风险收益比")
    
    def __repr__(self):
        return f"<BacktestTrade(trade_id='{self.trade_id}', symbol='{self.symbol}', pnl={self.pnl:.2f})>"


class OptimizationResult(BaseModel):
    """优化结果模型"""
    __tablename__ = "optimization_results"
    
    task_id = Column(String(36), index=True, nullable=False, comment="任务ID")
    optimization_id = Column(String(100), unique=True, nullable=False, comment="优化ID")
    
    # 优化配置
    optimization_method = Column(String(50), nullable=False, comment="优化方法")
    optimization_metric = Column(String(50), nullable=False, comment="优化指标")
    total_combinations = Column(Integer, default=0, comment="总组合数")
    
    # 最佳结果
    best_params = Column(JSON, nullable=False, comment="最佳参数")
    best_score = Column(Float, nullable=False, comment="最佳得分")
    
    # 执行信息
    optimization_time = Column(Float, comment="优化耗时(秒)")
    completed_combinations = Column(Integer, default=0, comment="完成组合数")
    
    # 参数敏感性分析
    param_sensitivity = Column(JSON, comment="参数敏感性分析")
    performance_distribution = Column(JSON, comment="性能分布统计")
    
    def __repr__(self):
        return f"<OptimizationResult(task_id='{self.task_id}', best_score={self.best_score:.4f})>"


class PortfolioMetrics(BaseModel):
    """投资组合指标模型"""
    __tablename__ = "portfolio_metrics"
    
    task_id = Column(String(36), unique=True, index=True, nullable=False, comment="任务ID")
    
    # 投资组合配置
    symbols = Column(JSON, nullable=False, comment="交易对列表")
    weights = Column(JSON, comment="权重配置")
    rebalance_frequency = Column(String(20), comment="重新平衡频率")
    
    # 投资组合指标
    portfolio_return = Column(Float, default=0.0, comment="投资组合收益率")
    portfolio_volatility = Column(Float, default=0.0, comment="投资组合波动率")
    portfolio_sharpe = Column(Float, default=0.0, comment="投资组合夏普比率")
    portfolio_max_drawdown = Column(Float, default=0.0, comment="投资组合最大回撤")
    
    # 风险分析
    average_correlation = Column(Float, default=0.0, comment="平均相关性")
    diversification_ratio = Column(Float, default=0.0, comment="多样化比率")
    var_95 = Column(Float, default=0.0, comment="95% VaR")
    cvar_95 = Column(Float, default=0.0, comment="95% CVaR")
    
    # 成分贡献
    symbol_contributions = Column(JSON, comment="成分贡献分析")
    correlation_matrix = Column(JSON, comment="相关性矩阵")
    
    # 风险事件
    risk_events_count = Column(Integer, default=0, comment="风险事件次数")
    rebalance_count = Column(Integer, default=0, comment="重新平衡次数")
    
    def __repr__(self):
        return f"<PortfolioMetrics(task_id='{self.task_id}', return={self.portfolio_return:.2f}%)>"


class RiskEvent(BaseModel):
    """风险事件模型"""
    __tablename__ = "risk_events"
    
    task_id = Column(String(36), index=True, nullable=False, comment="任务ID")
    event_id = Column(String(100), unique=True, nullable=False, comment="事件ID")
    
    # 事件信息
    event_type = Column(String(50), nullable=False, comment="事件类型")
    event_time = Column(DateTime, nullable=False, comment="事件时间")
    severity = Column(String(20), default="medium", comment="严重程度")
    
    # 事件详情
    description = Column(Text, comment="事件描述")
    trigger_value = Column(Float, comment="触发值")
    threshold_value = Column(Float, comment="阈值")
    
    # 影响分析
    affected_symbols = Column(JSON, comment="受影响的交易对")
    portfolio_impact = Column(Float, comment="对投资组合的影响")
    
    # 处理措施
    action_taken = Column(String(200), comment="采取的措施")
    resolution_time = Column(DateTime, comment="解决时间")
    
    def __repr__(self):
        return f"<RiskEvent(event_id='{self.event_id}', type='{self.event_type}', time='{self.event_time}')>"


class StrategyComparison(BaseModel):
    """策略比较模型"""
    __tablename__ = "strategy_comparisons"
    
    task_id = Column(String(36), unique=True, index=True, nullable=False, comment="任务ID")
    
    # 比较配置
    symbol = Column(String(20), nullable=False, comment="交易对")
    strategies = Column(JSON, nullable=False, comment="策略列表")
    comparison_period = Column(String(50), comment="比较周期")
    
    # 最佳策略
    best_return_strategy = Column(String(50), comment="最佳收益策略")
    best_sharpe_strategy = Column(String(50), comment="最佳夏普策略")
    best_drawdown_strategy = Column(String(50), comment="最佳回撤策略")
    
    # 比较结果
    strategy_rankings = Column(JSON, comment="策略排名")
    performance_matrix = Column(JSON, comment="性能矩阵")
    statistical_tests = Column(JSON, comment="统计检验结果")
    
    # 推荐结果
    recommended_strategy = Column(String(50), comment="推荐策略")
    recommendation_reason = Column(Text, comment="推荐理由")
    confidence_score = Column(Float, comment="推荐置信度")
    
    def __repr__(self):
        return f"<StrategyComparison(task_id='{self.task_id}', symbol='{self.symbol}')>"


class BacktestChart(BaseModel):
    """回测图表模型"""
    __tablename__ = "backtest_charts"
    
    task_id = Column(String(36), index=True, nullable=False, comment="任务ID")
    chart_id = Column(String(100), unique=True, nullable=False, comment="图表ID")
    
    # 图表信息
    chart_type = Column(String(50), nullable=False, comment="图表类型")
    chart_title = Column(String(200), comment="图表标题")
    chart_description = Column(Text, comment="图表描述")
    
    # 文件信息
    file_path = Column(String(500), comment="文件路径")
    file_format = Column(String(10), default="png", comment="文件格式")
    file_size = Column(Integer, comment="文件大小(bytes)")
    
    # 图表配置
    chart_config = Column(JSON, comment="图表配置")
    data_source = Column(JSON, comment="数据源信息")
    
    # 生成信息
    generated_at = Column(DateTime, default=datetime.utcnow, comment="生成时间")
    is_cached = Column(Boolean, default=False, comment="是否已缓存")
    
    def __repr__(self):
        return f"<BacktestChart(chart_id='{self.chart_id}', type='{self.chart_type}')>"


class BacktestCache(BaseModel):
    """回测缓存模型"""
    __tablename__ = "backtest_cache"
    
    cache_key = Column(String(100), unique=True, nullable=False, comment="缓存键")
    
    # 缓存内容
    cache_type = Column(String(50), nullable=False, comment="缓存类型")
    cache_data = Column(LONGTEXT, comment="缓存数据")
    
    # 缓存配置
    symbol = Column(String(20), comment="交易对")
    start_date = Column(DateTime, comment="开始日期")
    end_date = Column(DateTime, comment="结束日期")
    strategy_hash = Column(String(64), comment="策略哈希")
    
    # 缓存管理
    access_count = Column(Integer, default=0, comment="访问次数")
    last_accessed = Column(DateTime, default=datetime.utcnow, comment="最后访问时间")
    expires_at = Column(DateTime, comment="过期时间")
    
    # 统计信息
    cache_size = Column(Integer, comment="缓存大小(bytes)")
    generation_time = Column(Float, comment="生成耗时(秒)")
    
    def __repr__(self):
        return f"<BacktestCache(cache_key='{self.cache_key}', type='{self.cache_type}')>"


