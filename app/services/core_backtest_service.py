# -*- coding: utf-8 -*-
"""
核心回测服务
Core Backtest Service - 统一管理所有回测功能
整合基础回测、高级回测、策略优化、报告生成等功能
"""

import asyncio
from typing import Dict, Any, List, Optional, Tuple, Union
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
import numpy as np
import pandas as pd
from pathlib import Path
import json

from app.core.config import get_settings
from app.core.logging import get_logger, trading_logger
from app.services.backtest_service_complete import (
    CompleteBacktestService,
    AdvancedBacktestEngine,
    StrategyOptimizer,
    OptimizationMethod,
    RiskManagementConfig,
    PortfolioConfig
)
from app.services.backtest_report_service import BacktestReportService, ReportConfig
from app.services.core_notification_service import get_core_notification_service
from app.utils.exceptions import BacktestError, TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class BacktestType(Enum):
    """回测类型"""
    SINGLE_SYMBOL = "single_symbol"
    PORTFOLIO = "portfolio" 
    STRATEGY_COMPARISON = "strategy_comparison"
    OPTIMIZATION = "optimization"
    WALKFORWARD = "walkforward"


class BacktestStatus(Enum):
    """回测状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BacktestTask:
    """回测任务"""
    task_id: str
    backtest_type: BacktestType
    config: Dict[str, Any]
    status: BacktestStatus
    created_time: datetime
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: float = 0.0


@dataclass
class BacktestResult:
    """回测结果"""
    task_id: str
    backtest_type: BacktestType
    symbol: str
    start_date: datetime
    end_date: datetime
    
    # 核心指标
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    
    # 交易统计
    total_trades: int
    profitable_trades: int
    avg_profit: float
    avg_loss: float
    
    # 风险指标
    volatility: float
    calmar_ratio: float
    sortino_ratio: float
    
    # 详细结果
    equity_curve: List[Dict[str, Any]]
    trades: List[Dict[str, Any]]
    monthly_returns: Dict[str, float]
    
    # 报告
    report_path: Optional[str] = None
    charts_path: Optional[str] = None


class CoreBacktestService:
    """核心回测服务类 - 统一回测管理"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        
        # 整合原有回测服务
        self.complete_service = CompleteBacktestService()
        self.report_service = BacktestReportService()
        self.notification_service = None
        
        # 任务管理
        self.active_tasks: Dict[str, BacktestTask] = {}
        self.completed_tasks: Dict[str, BacktestTask] = {}
        self.max_concurrent_tasks = 3
        
        # 结果存储
        self.results_dir = Path("backtest_results")
        self.results_dir.mkdir(exist_ok=True)
        
        # 默认配置
        self.default_configs = {
            BacktestType.SINGLE_SYMBOL: {
                'initial_balance': 10000.0,
                'interval': '1h',
                'strategy': 'supertrend',
                'fee_rate': 0.001
            },
            BacktestType.PORTFOLIO: {
                'initial_balance': 100000.0,
                'interval': '1h',
                'rebalance_frequency': 'weekly',
                'max_symbols': 5
            },
            BacktestType.OPTIMIZATION: {
                'method': OptimizationMethod.GRID_SEARCH,
                'max_iterations': 100,
                'parallel_jobs': 2
            }
        }
    
    async def submit_backtest(
        self,
        backtest_type: BacktestType,
        config: Dict[str, Any],
        notify_on_completion: bool = True
    ) -> str:
        """
        提交回测任务
        
        Args:
            backtest_type: 回测类型
            config: 回测配置
            notify_on_completion: 完成时是否发送通知
            
        Returns:
            任务ID
        """
        try:
            # 检查并发限制
            active_count = len(self.active_tasks)
            if active_count >= self.max_concurrent_tasks:
                raise BacktestError(f"并发回测任务数量达到上限 ({self.max_concurrent_tasks})")
            
            # 生成任务ID
            task_id = f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.active_tasks)}"
            
            # 验证和补充配置
            validated_config = self._validate_and_complete_config(backtest_type, config)
            
            # 创建任务
            task = BacktestTask(
                task_id=task_id,
                backtest_type=backtest_type,
                config=validated_config,
                status=BacktestStatus.PENDING,
                created_time=datetime.now()
            )
            
            self.active_tasks[task_id] = task
            
            # 异步执行回测
            asyncio.create_task(self._execute_backtest_task(task, notify_on_completion))
            
            self.logger.info(f"✅ 回测任务已提交: {task_id} ({backtest_type.value})")
            return task_id
            
        except Exception as e:
            self.logger.error(f"提交回测任务失败: {e}")
            raise BacktestError(f"提交回测任务失败: {str(e)}")
    
    def _validate_and_complete_config(
        self,
        backtest_type: BacktestType,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """验证和补充配置"""
        
        # 获取默认配置
        default_config = self.default_configs.get(backtest_type, {}).copy()
        
        # 合并用户配置
        validated_config = {**default_config, **config}
        
        # 必需参数验证
        required_fields = {
            BacktestType.SINGLE_SYMBOL: ['symbol', 'start_date', 'end_date'],
            BacktestType.PORTFOLIO: ['symbols', 'start_date', 'end_date'],
            BacktestType.STRATEGY_COMPARISON: ['symbol', 'start_date', 'end_date', 'strategies'],
            BacktestType.OPTIMIZATION: ['symbol', 'start_date', 'end_date', 'parameters']
        }
        
        required = required_fields.get(backtest_type, [])
        for field in required:
            if field not in validated_config:
                raise BacktestError(f"缺少必需参数: {field}")
        
        # 日期格式转换
        if isinstance(validated_config.get('start_date'), str):
            validated_config['start_date'] = datetime.fromisoformat(validated_config['start_date'])
        if isinstance(validated_config.get('end_date'), str):
            validated_config['end_date'] = datetime.fromisoformat(validated_config['end_date'])
        
        return validated_config
    
    async def _execute_backtest_task(
        self,
        task: BacktestTask,
        notify_on_completion: bool
    ):
        """执行回测任务"""
        try:
            # 更新任务状态
            task.status = BacktestStatus.RUNNING
            task.start_time = datetime.now()
            
            self.logger.info(f"🚀 开始执行回测任务: {task.task_id}")
            
            # 根据回测类型执行
            if task.backtest_type == BacktestType.SINGLE_SYMBOL:
                result = await self._run_single_symbol_backtest(task)
            elif task.backtest_type == BacktestType.PORTFOLIO:
                result = await self._run_portfolio_backtest(task)
            elif task.backtest_type == BacktestType.STRATEGY_COMPARISON:
                result = await self._run_strategy_comparison_backtest(task)
            elif task.backtest_type == BacktestType.OPTIMIZATION:
                result = await self._run_optimization_backtest(task)
            else:
                raise BacktestError(f"不支持的回测类型: {task.backtest_type}")
            
            # 生成报告
            report_result = await self._generate_backtest_report(task, result)
            if report_result:
                result['report'] = report_result
            
            # 更新任务状态
            task.status = BacktestStatus.COMPLETED
            task.end_time = datetime.now()
            task.result = result
            task.progress = 100.0
            
            # 移动到完成任务
            self.completed_tasks[task.task_id] = task
            del self.active_tasks[task.task_id]
            
            duration = (task.end_time - task.start_time).total_seconds()
            self.logger.info(f"✅ 回测任务完成: {task.task_id} (耗时 {duration:.1f}秒)")
            
            # 发送完成通知
            if notify_on_completion:
                await self._send_backtest_completion_notification(task)
            
        except Exception as e:
            # 更新任务状态为失败
            task.status = BacktestStatus.FAILED
            task.end_time = datetime.now()
            task.error = str(e)
            
            # 移动到完成任务
            self.completed_tasks[task.task_id] = task
            del self.active_tasks[task.task_id]
            
            self.logger.error(f"❌ 回测任务失败: {task.task_id} - {e}")
            
            # 发送失败通知
            if notify_on_completion:
                await self._send_backtest_failure_notification(task)
    
    async def _run_single_symbol_backtest(self, task: BacktestTask) -> Dict[str, Any]:
        """运行单交易对回测"""
        config = task.config
        
        # 调用完整回测服务
        backtest_config = {
            'type': 'single',
            'symbol': config['symbol'],
            'start_date': config['start_date'].isoformat(),
            'end_date': config['end_date'].isoformat(),
            'basic_params': {
                'initial_balance': config.get('initial_balance', 10000),
                'strategy': config.get('strategy', 'supertrend'),
                'interval': config.get('interval', '1h')
            },
            'advanced_params': {
                'fee_rate': config.get('fee_rate', 0.001),
                'slippage': config.get('slippage', 0.0001)
            }
        }
        
        result = await self.complete_service.run_comprehensive_backtest(backtest_config)
        
        # 提取核心指标
        basic_result = result.get('basic_result', {})
        metrics = basic_result.get('metrics', {})
        
        return {
            'type': 'single_symbol',
            'symbol': config['symbol'],
            'metrics': metrics,
            'equity_curve': basic_result.get('equity_curve', []),
            'trades': basic_result.get('trades', []),
            'advanced_result': result.get('advanced_result', {}),
            'charts': result.get('charts', {})
        }
    
    async def _run_portfolio_backtest(self, task: BacktestTask) -> Dict[str, Any]:
        """运行投资组合回测"""
        config = task.config
        
        # 创建投资组合配置
        portfolio_config = PortfolioConfig(
            symbols=config['symbols'],
            allocation_method=config.get('allocation_method', 'equal_weight'),
            rebalance_frequency=config.get('rebalance_frequency', 'weekly'),
            max_symbols=config.get('max_symbols', len(config['symbols']))
        )
        
        # 创建高级回测引擎
        advanced_engine = AdvancedBacktestEngine()
        
        result = await advanced_engine.run_portfolio_backtest(
            portfolio_config=portfolio_config,
            start_date=config['start_date'],
            end_date=config['end_date'],
            initial_balance=config.get('initial_balance', 100000),
            interval=config.get('interval', '1h')
        )
        
        return {
            'type': 'portfolio',
            'symbols': config['symbols'],
            'portfolio_metrics': result.get('portfolio_metrics', {}),
            'individual_results': result.get('individual_results', {}),
            'rebalance_history': result.get('rebalance_history', [])
        }
    
    async def _run_strategy_comparison_backtest(self, task: BacktestTask) -> Dict[str, Any]:
        """运行策略比较回测"""
        config = task.config
        
        strategies = config['strategies']
        results = {}
        
        # 并行运行多个策略回测
        tasks = []
        for strategy_name, strategy_config in strategies.items():
            strategy_task_config = {
                **config,
                'strategy': strategy_name,
                **strategy_config
            }
            
            # 创建临时任务
            temp_task = BacktestTask(
                task_id=f"{task.task_id}_{strategy_name}",
                backtest_type=BacktestType.SINGLE_SYMBOL,
                config=strategy_task_config,
                status=BacktestStatus.RUNNING,
                created_time=datetime.now()
            )
            
            tasks.append((strategy_name, self._run_single_symbol_backtest(temp_task)))
        
        # 执行所有策略回测
        strategy_results = await asyncio.gather(
            *[task for _, task in tasks],
            return_exceptions=True
        )
        
        # 收集结果
        for i, (strategy_name, _) in enumerate(tasks):
            result = strategy_results[i]
            if isinstance(result, Exception):
                self.logger.error(f"策略 {strategy_name} 回测失败: {result}")
                results[strategy_name] = {'error': str(result)}
            else:
                results[strategy_name] = result
        
        # 生成比较报告
        comparison = self._generate_strategy_comparison(results)
        
        return {
            'type': 'strategy_comparison',
            'symbol': config['symbol'],
            'strategy_results': results,
            'comparison': comparison
        }
    
    async def _run_optimization_backtest(self, task: BacktestTask) -> Dict[str, Any]:
        """运行策略优化回测"""
        config = task.config
        
        # 创建策略优化器
        optimizer = StrategyOptimizer(AdvancedBacktestEngine())
        
        optimization_config = {
            'method': config.get('method', OptimizationMethod.GRID_SEARCH),
            'parameters': config['parameters'],
            'objective': config.get('objective', 'sharpe_ratio'),
            'max_iterations': config.get('max_iterations', 100)
        }
        
        result = await optimizer.optimize_strategy(
            symbol=config['symbol'],
            start_date=config['start_date'],
            end_date=config['end_date'],
            config=optimization_config
        )
        
        return {
            'type': 'optimization',
            'symbol': config['symbol'],
            'best_parameters': result.get('best_parameters', {}),
            'best_metrics': result.get('best_metrics', {}),
            'optimization_history': result.get('optimization_history', []),
            'parameter_sensitivity': result.get('parameter_sensitivity', {})
        }
    
    def _generate_strategy_comparison(self, strategy_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """生成策略比较分析"""
        comparison = {
            'summary': {},
            'rankings': {},
            'risk_return_analysis': {}
        }
        
        metrics_to_compare = ['total_return', 'sharpe_ratio', 'max_drawdown', 'win_rate']
        
        for metric in metrics_to_compare:
            metric_values = {}
            for strategy_name, result in strategy_results.items():
                if 'error' not in result:
                    metrics = result.get('metrics', {})
                    if metric in metrics:
                        metric_values[strategy_name] = metrics[metric]
            
            if metric_values:
                # 排序（大部分指标越大越好，max_drawdown除外）
                reverse = metric != 'max_drawdown'
                sorted_strategies = sorted(
                    metric_values.items(),
                    key=lambda x: x[1],
                    reverse=reverse
                )
                
                comparison['rankings'][metric] = [
                    {'strategy': name, 'value': value, 'rank': i+1}
                    for i, (name, value) in enumerate(sorted_strategies)
                ]
        
        return comparison
    
    async def _generate_backtest_report(
        self,
        task: BacktestTask,
        result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """生成回测报告"""
        try:
            # 创建报告配置
            report_config = ReportConfig(
                language='zh-CN',
                include_charts=True,
                template='detailed'
            )
            
            # 生成报告
            report = await self.report_service.generate_comprehensive_report(
                result, report_config
            )
            
            # 保存报告到文件
            report_filename = f"{task.task_id}_report.json"
            report_path = self.results_dir / report_filename
            
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)
            
            return {
                'report_path': str(report_path),
                'summary': report.get('summary', {}),
                'charts_generated': len(report.get('charts', {}))
            }
            
        except Exception as e:
            self.logger.error(f"生成回测报告失败: {e}")
            return None
    
    async def _send_backtest_completion_notification(self, task: BacktestTask):
        """发送回测完成通知"""
        try:
            if not self.notification_service:
                self.notification_service = await get_core_notification_service()
            
            result = task.result
            metrics = result.get('metrics', {}) if result else {}
            
            # 构建通知数据
            backtest_data = {
                'task_id': task.task_id,
                'backtest_type': task.backtest_type.value,
                'symbol': task.config.get('symbol', 'Portfolio'),
                'duration_minutes': int((task.end_time - task.start_time).total_seconds() / 60),
                'total_return': metrics.get('total_return', 0),
                'sharpe_ratio': metrics.get('sharpe_ratio', 0),
                'max_drawdown': metrics.get('max_drawdown', 0),
                'status': 'completed'
            }
            
            success = await self.notification_service.send_backtest_result(backtest_data)
            
            if success:
                self.logger.info(f"✅ 回测完成通知已发送: {task.task_id}")
            
        except Exception as e:
            self.logger.error(f"发送回测完成通知失败: {e}")
    
    async def _send_backtest_failure_notification(self, task: BacktestTask):
        """发送回测失败通知"""
        try:
            if not self.notification_service:
                self.notification_service = await get_core_notification_service()
            
            # 构建失败通知数据
            backtest_data = {
                'task_id': task.task_id,
                'backtest_type': task.backtest_type.value,
                'symbol': task.config.get('symbol', 'Unknown'),
                'error': task.error,
                'status': 'failed'
            }
            
            success = await self.notification_service.send_backtest_result(backtest_data)
            
            if success:
                self.logger.info(f"✅ 回测失败通知已发送: {task.task_id}")
            
        except Exception as e:
            self.logger.error(f"发送回测失败通知失败: {e}")
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        # 检查活跃任务
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            return {
                'task_id': task_id,
                'status': task.status.value,
                'progress': task.progress,
                'created_time': task.created_time,
                'start_time': task.start_time,
                'config': task.config
            }
        
        # 检查已完成任务
        if task_id in self.completed_tasks:
            task = self.completed_tasks[task_id]
            return {
                'task_id': task_id,
                'status': task.status.value,
                'progress': task.progress,
                'created_time': task.created_time,
                'start_time': task.start_time,
                'end_time': task.end_time,
                'config': task.config,
                'result': task.result,
                'error': task.error
            }
        
        return None
    
    async def list_tasks(
        self,
        status_filter: Optional[BacktestStatus] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """列出任务"""
        all_tasks = []
        
        # 添加活跃任务
        for task in self.active_tasks.values():
            if status_filter is None or task.status == status_filter:
                all_tasks.append(task)
        
        # 添加已完成任务
        for task in self.completed_tasks.values():
            if status_filter is None or task.status == status_filter:
                all_tasks.append(task)
        
        # 按创建时间排序
        all_tasks.sort(key=lambda x: x.created_time, reverse=True)
        
        # 限制数量
        tasks = all_tasks[:limit]
        
        return [
            {
                'task_id': task.task_id,
                'backtest_type': task.backtest_type.value,
                'status': task.status.value,
                'created_time': task.created_time,
                'start_time': task.start_time,
                'end_time': task.end_time,
                'symbol': task.config.get('symbol', 'N/A'),
                'progress': task.progress
            }
            for task in tasks
        ]
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task.status = BacktestStatus.CANCELLED
            task.end_time = datetime.now()
            
            # 移动到完成任务
            self.completed_tasks[task_id] = task
            del self.active_tasks[task_id]
            
            self.logger.info(f"✅ 回测任务已取消: {task_id}")
            return True
        
        return False


# 全局服务实例
_core_backtest_service = None


async def get_core_backtest_service() -> CoreBacktestService:
    """获取核心回测服务实例"""
    global _core_backtest_service
    if _core_backtest_service is None:
        _core_backtest_service = CoreBacktestService()
    return _core_backtest_service
