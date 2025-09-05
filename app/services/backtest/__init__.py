# -*- coding: utf-8 -*-
"""
回测相关服务模块
Backtest Services Module
"""

from .backtest_service_complete import CompleteBacktestService
from .backtest_report_service import BacktestReportService

# 便利函数
def get_complete_backtest_service():
    """获取完整回测服务的便利函数"""
    return CompleteBacktestService()

def get_backtest_report_service():
    """获取回测报告服务的便利函数"""
    return BacktestReportService()

__all__ = [
    'CompleteBacktestService',
    'BacktestReportService',
    # 便利函数
    'get_complete_backtest_service',
    'get_backtest_report_service'
]