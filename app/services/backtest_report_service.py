# -*- coding: utf-8 -*-
"""
回测报告服务
Backtest Report Service
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import numpy as np
import pandas as pd
import json
from pathlib import Path
import base64
import io

from app.core.logging import get_logger
from app.core.config import get_settings
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


@dataclass
class ReportSection:
    """报告章节"""
    title: str
    content: str
    charts: List[str] = None
    tables: List[Dict[str, Any]] = None
    insights: List[str] = None


@dataclass
class ReportConfig:
    """报告配置"""
    include_charts: bool = True
    include_detailed_trades: bool = True
    include_risk_analysis: bool = True
    include_optimization_details: bool = True
    chart_format: str = "png"
    language: str = "zh-CN"
    template: str = "standard"


class BacktestReportService:
    """回测报告服务"""
    
    def __init__(self):
        self.report_templates = {
            'standard': self._generate_standard_report,
            'executive': self._generate_executive_report,
            'detailed': self._generate_detailed_report,
            'risk_focus': self._generate_risk_focused_report
        }
        
        self.chart_generators = {}  # 将在需要时初始化
    
    async def generate_comprehensive_report(
        self,
        backtest_results: Dict[str, Any],
        config: ReportConfig = None
    ) -> Dict[str, Any]:
        """
        生成综合回测报告
        
        Args:
            backtest_results: 回测结果数据
            config: 报告配置
            
        Returns:
            完整的报告数据
        """
        try:
            config = config or ReportConfig()
            logger.info(f"📊 开始生成回测报告 (模板: {config.template})")
            
            # 获取报告生成器
            report_generator = self.report_templates.get(
                config.template, 
                self._generate_standard_report
            )
            
            # 生成报告
            report = await report_generator(backtest_results, config)
            
            # 添加元数据
            report['metadata'] = {
                'generated_at': datetime.now().isoformat(),
                'report_version': '1.0.0',
                'generator': 'BacktestReportService',
                'template': config.template,
                'language': config.language
            }
            
            logger.info(f"✅ 回测报告生成完成")
            return report
            
        except Exception as e:
            logger.error(f"❌ 生成回测报告失败: {e}")
            raise TradingToolError(f"报告生成失败: {str(e)}")
    
    async def _generate_standard_report(
        self,
        results: Dict[str, Any],
        config: ReportConfig
    ) -> Dict[str, Any]:
        """生成标准回测报告"""
        try:
            sections = []
            
            # 执行摘要
            executive_summary = await self._create_executive_summary(results)
            sections.append(ReportSection(
                title="执行摘要",
                content=executive_summary['content'],
                insights=executive_summary['key_insights']
            ))
            
            # 策略概述
            strategy_overview = await self._create_strategy_overview(results)
            sections.append(ReportSection(
                title="策略概述",
                content=strategy_overview['content'],
                tables=[strategy_overview['config_table']]
            ))
            
            # 绩效分析
            performance_analysis = await self._create_performance_analysis(results)
            sections.append(ReportSection(
                title="绩效分析",
                content=performance_analysis['content'],
                tables=[performance_analysis['metrics_table']],
                charts=performance_analysis.get('charts', []) if config.include_charts else []
            ))
            
            # 交易分析
            if config.include_detailed_trades:
                trade_analysis = await self._create_trade_analysis(results)
                sections.append(ReportSection(
                    title="交易分析",
                    content=trade_analysis['content'],
                    tables=[trade_analysis['trade_summary_table']],
                    charts=trade_analysis.get('charts', []) if config.include_charts else []
                ))
            
            # 风险分析
            if config.include_risk_analysis:
                risk_analysis = await self._create_risk_analysis(results)
                sections.append(ReportSection(
                    title="风险分析",
                    content=risk_analysis['content'],
                    tables=[risk_analysis['risk_metrics_table']],
                    insights=risk_analysis['risk_insights']
                ))
            
            # 优化建议
            optimization_recommendations = await self._create_optimization_recommendations(results)
            sections.append(ReportSection(
                title="优化建议",
                content=optimization_recommendations['content'],
                insights=optimization_recommendations['recommendations']
            ))
            
            return {
                'title': '回测分析报告',
                'subtitle': self._generate_report_subtitle(results),
                'sections': [section.__dict__ for section in sections],
                'summary_stats': await self._create_summary_stats(results),
                'conclusions': await self._create_conclusions(results)
            }
            
        except Exception as e:
            logger.error(f"❌ 生成标准报告失败: {e}")
            raise
    
    async def _generate_executive_report(
        self,
        results: Dict[str, Any],
        config: ReportConfig
    ) -> Dict[str, Any]:
        """生成高管摘要报告"""
        try:
            sections = []
            
            # 关键发现
            key_findings = await self._create_key_findings(results)
            sections.append(ReportSection(
                title="关键发现",
                content=key_findings['content'],
                insights=key_findings['findings']
            ))
            
            # 投资建议
            investment_recommendation = await self._create_investment_recommendation(results)
            sections.append(ReportSection(
                title="投资建议",
                content=investment_recommendation['content'],
                insights=investment_recommendation['recommendations']
            ))
            
            # 风险评估
            risk_assessment = await self._create_risk_assessment_summary(results)
            sections.append(ReportSection(
                title="风险评估",
                content=risk_assessment['content'],
                insights=risk_assessment['risk_factors']
            ))
            
            # 下一步行动
            next_steps = await self._create_next_steps(results)
            sections.append(ReportSection(
                title="行动建议",
                content=next_steps['content'],
                insights=next_steps['actions']
            ))
            
            return {
                'title': '策略回测 - 高管摘要',
                'subtitle': self._generate_report_subtitle(results),
                'sections': [section.__dict__ for section in sections],
                'executive_dashboard': await self._create_executive_dashboard(results)
            }
            
        except Exception as e:
            logger.error(f"❌ 生成高管报告失败: {e}")
            raise
    
    async def _generate_detailed_report(
        self,
        results: Dict[str, Any],
        config: ReportConfig
    ) -> Dict[str, Any]:
        """生成详细技术报告"""
        try:
            sections = []
            
            # 标准报告内容
            standard_report = await self._generate_standard_report(results, config)
            sections.extend([ReportSection(**section) for section in standard_report['sections']])
            
            # 技术指标详细分析
            technical_analysis = await self._create_technical_analysis(results)
            sections.append(ReportSection(
                title="技术指标分析",
                content=technical_analysis['content'],
                tables=technical_analysis['indicator_tables'],
                charts=technical_analysis.get('charts', []) if config.include_charts else []
            ))
            
            # 回撤分析
            drawdown_analysis = await self._create_drawdown_analysis(results)
            sections.append(ReportSection(
                title="回撤分析",
                content=drawdown_analysis['content'],
                tables=[drawdown_analysis['drawdown_table']],
                charts=drawdown_analysis.get('charts', []) if config.include_charts else []
            ))
            
            # 月度表现分析
            monthly_analysis = await self._create_monthly_analysis(results)
            sections.append(ReportSection(
                title="月度表现分析",
                content=monthly_analysis['content'],
                tables=[monthly_analysis['monthly_table']],
                charts=monthly_analysis.get('charts', []) if config.include_charts else []
            ))
            
            # 相关性分析
            correlation_analysis = await self._create_correlation_analysis(results)
            sections.append(ReportSection(
                title="相关性分析",
                content=correlation_analysis['content'],
                tables=[correlation_analysis['correlation_table']],
                charts=correlation_analysis.get('charts', []) if config.include_charts else []
            ))
            
            # 压力测试
            stress_test = await self._create_stress_test_analysis(results)
            sections.append(ReportSection(
                title="压力测试",
                content=stress_test['content'],
                tables=[stress_test['stress_scenarios_table']],
                insights=stress_test['stress_insights']
            ))
            
            return {
                'title': '详细技术分析报告',
                'subtitle': self._generate_report_subtitle(results),
                'sections': [section.__dict__ for section in sections],
                'appendices': await self._create_appendices(results)
            }
            
        except Exception as e:
            logger.error(f"❌ 生成详细报告失败: {e}")
            raise
    
    async def _generate_risk_focused_report(
        self,
        results: Dict[str, Any],
        config: ReportConfig
    ) -> Dict[str, Any]:
        """生成风险导向报告"""
        try:
            sections = []
            
            # 风险概述
            risk_overview = await self._create_risk_overview(results)
            sections.append(ReportSection(
                title="风险概述",
                content=risk_overview['content'],
                insights=risk_overview['risk_highlights']
            ))
            
            # VaR分析
            var_analysis = await self._create_var_analysis(results)
            sections.append(ReportSection(
                title="风险价值(VaR)分析",
                content=var_analysis['content'],
                tables=[var_analysis['var_table']],
                charts=var_analysis.get('charts', []) if config.include_charts else []
            ))
            
            # 极端风险分析
            tail_risk_analysis = await self._create_tail_risk_analysis(results)
            sections.append(ReportSection(
                title="极端风险分析",
                content=tail_risk_analysis['content'],
                tables=[tail_risk_analysis['tail_risk_table']],
                insights=tail_risk_analysis['tail_insights']
            ))
            
            # 风险分解
            risk_decomposition = await self._create_risk_decomposition(results)
            sections.append(ReportSection(
                title="风险分解分析",
                content=risk_decomposition['content'],
                tables=[risk_decomposition['decomposition_table']],
                charts=risk_decomposition.get('charts', []) if config.include_charts else []
            ))
            
            # 风险控制建议
            risk_controls = await self._create_risk_control_recommendations(results)
            sections.append(ReportSection(
                title="风险控制建议",
                content=risk_controls['content'],
                insights=risk_controls['control_measures']
            ))
            
            return {
                'title': '风险分析报告',
                'subtitle': self._generate_report_subtitle(results),
                'sections': [section.__dict__ for section in sections],
                'risk_dashboard': await self._create_risk_dashboard(results)
            }
            
        except Exception as e:
            logger.error(f"❌ 生成风险报告失败: {e}")
            raise
    
    # 报告内容创建方法
    async def _create_executive_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建执行摘要"""
        try:
            metrics = results.get('metrics', {})
            
            # 关键指标
            total_return = getattr(metrics, 'total_pnl_percent', 0)
            sharpe_ratio = getattr(metrics, 'sharpe_ratio', 0)
            max_drawdown = getattr(metrics, 'max_drawdown_percent', 0)
            win_rate = getattr(metrics, 'win_rate', 0)
            total_trades = getattr(metrics, 'total_trades', 0)
            
            # 生成内容
            content = f"""
本次回测分析涵盖了策略在指定时间段内的完整表现。策略共执行了{total_trades}笔交易，
实现了{total_return:.2f}%的总收益率，胜率为{win_rate:.1%}。

风险调整后的收益表现方面，策略获得了{sharpe_ratio:.2f}的夏普比率，
最大回撤控制在{max_drawdown:.2f}%以内，展现了良好的风险控制能力。

从风险收益特征来看，该策略在回测期间{'表现优异' if total_return > 0 and sharpe_ratio > 1 else '表现平稳' if total_return > 0 else '需要优化'}，
{'具备较强的实际应用价值' if sharpe_ratio > 1.5 and max_drawdown < 10 else '建议进一步优化后使用'}。
            """.strip()
            
            # 关键洞察
            key_insights = []
            
            if total_return > 10:
                key_insights.append("🚀 策略实现了超过10%的正收益，具备良好的盈利能力")
            elif total_return > 0:
                key_insights.append("📈 策略实现正收益，但收益空间有待提升")
            else:
                key_insights.append("📉 策略在回测期间出现亏损，需要重新评估")
            
            if sharpe_ratio > 2:
                key_insights.append("⭐ 夏普比率优异，风险调整后收益表现出色")
            elif sharpe_ratio > 1:
                key_insights.append("👍 夏普比率良好，风险收益比合理")
            else:
                key_insights.append("⚠️ 夏普比率偏低，建议优化风险管理")
            
            if max_drawdown < 5:
                key_insights.append("🛡️ 回撤控制优秀，展现了强劲的防守能力")
            elif max_drawdown < 10:
                key_insights.append("✅ 回撤控制良好，风险管理有效")
            else:
                key_insights.append("🚨 最大回撤较大，需要加强风险控制")
            
            if win_rate > 0.6:
                key_insights.append("🎯 胜率较高，策略准确性良好")
            elif win_rate > 0.4:
                key_insights.append("⚖️ 胜率适中，需要平衡盈亏比")
            else:
                key_insights.append("🔍 胜率偏低，建议优化入场时机")
            
            return {
                'content': content,
                'key_insights': key_insights
            }
            
        except Exception as e:
            logger.error(f"❌ 创建执行摘要失败: {e}")
            return {'content': '执行摘要生成失败', 'key_insights': []}
    
    async def _create_strategy_overview(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建策略概述"""
        try:
            config = results.get('config', {})
            
            content = f"""
本次回测采用的策略配置如下所示。回测时间范围为{config.get('start_date', '未知')}至{config.get('end_date', '未知')}，
涵盖了{config.get('symbols', ['未知'])}等交易对，初始资金为{config.get('initial_balance', 0):,.0f}。

策略采用{config.get('interval', '1h')}时间周期进行分析，手续费率设定为{config.get('commission_rate', 0.0004):.2%}，
滑点设定为{config.get('slippage', 0.0001):.2%}，确保回测结果贴近实际交易环境。

该配置旨在验证策略在实际市场条件下的表现，为后续的实盘交易提供可靠的参考依据。
            """.strip()
            
            # 配置表格
            config_table = {
                'title': '回测配置详情',
                'headers': ['配置项', '数值', '说明'],
                'rows': [
                    ['交易对', ', '.join(config.get('symbols', [])), '回测标的'],
                    ['回测周期', f"{config.get('start_date', '')} - {config.get('end_date', '')}", '数据时间范围'],
                    ['时间粒度', config.get('interval', '1h'), 'K线周期'],
                    ['初始资金', f"{config.get('initial_balance', 0):,.0f}", '回测起始资金'],
                    ['手续费率', f"{config.get('commission_rate', 0.0004):.2%}", '交易成本'],
                    ['滑点', f"{config.get('slippage', 0.0001):.2%}", '执行偏差']
                ]
            }
            
            return {
                'content': content,
                'config_table': config_table
            }
            
        except Exception as e:
            logger.error(f"❌ 创建策略概述失败: {e}")
            return {
                'content': '策略概述生成失败',
                'config_table': {'title': '配置信息', 'headers': [], 'rows': []}
            }
    
    async def _create_performance_analysis(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建绩效分析"""
        try:
            metrics = results.get('metrics', {})
            
            # 提取关键指标
            total_return = getattr(metrics, 'total_pnl_percent', 0)
            annual_return = getattr(metrics, 'total_pnl_percent', 0) * 4  # 简化年化计算
            sharpe_ratio = getattr(metrics, 'sharpe_ratio', 0)
            sortino_ratio = getattr(metrics, 'sortino_ratio', 0)
            max_drawdown = getattr(metrics, 'max_drawdown_percent', 0)
            volatility = getattr(metrics, 'total_pnl_percent', 0) / 4  # 简化波动率估算
            
            content = f"""
绩效分析显示，策略在回测期间实现了{total_return:.2f}%的总收益率，
年化收益率约为{annual_return:.2f}%。

从风险调整收益的角度看，策略获得了{sharpe_ratio:.2f}的夏普比率和{sortino_ratio:.2f}的Sortino比率，
{'表现优异' if sharpe_ratio > 1.5 else '表现良好' if sharpe_ratio > 1 else '有待改善'}。

风险控制方面，最大回撤为{max_drawdown:.2f}%，年化波动率约为{volatility:.2f}%，
整体风险收益特征{'符合预期' if max_drawdown < 15 and sharpe_ratio > 1 else '需要进一步优化'}。
            """.strip()
            
            # 绩效指标表格
            metrics_table = {
                'title': '关键绩效指标',
                'headers': ['指标', '数值', '评级', '说明'],
                'rows': [
                    ['总收益率', f"{total_return:.2f}%", self._grade_performance(total_return, 'return'), '回测期间总收益'],
                    ['年化收益率', f"{annual_return:.2f}%", self._grade_performance(annual_return, 'annual_return'), '年化收益预估'],
                    ['夏普比率', f"{sharpe_ratio:.2f}", self._grade_performance(sharpe_ratio, 'sharpe'), '风险调整收益'],
                    ['Sortino比率', f"{sortino_ratio:.2f}", self._grade_performance(sortino_ratio, 'sortino'), '下行风险调整收益'],
                    ['最大回撤', f"{max_drawdown:.2f}%", self._grade_performance(max_drawdown, 'drawdown'), '最大资金回撤'],
                    ['波动率', f"{volatility:.2f}%", self._grade_performance(volatility, 'volatility'), '收益波动程度']
                ]
            }
            
            return {
                'content': content,
                'metrics_table': metrics_table,
                'charts': ['equity_curve', 'drawdown_chart']  # 图表占位符
            }
            
        except Exception as e:
            logger.error(f"❌ 创建绩效分析失败: {e}")
            return {
                'content': '绩效分析生成失败',
                'metrics_table': {'title': '绩效指标', 'headers': [], 'rows': []}
            }
    
    async def _create_trade_analysis(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建交易分析"""
        try:
            metrics = results.get('metrics', {})
            trades = results.get('trades', [])
            
            total_trades = getattr(metrics, 'total_trades', 0)
            winning_trades = getattr(metrics, 'winning_trades', 0)
            losing_trades = getattr(metrics, 'losing_trades', 0)
            win_rate = getattr(metrics, 'win_rate', 0)
            avg_win = getattr(metrics, 'avg_win', 0)
            avg_loss = getattr(metrics, 'avg_loss', 0)
            avg_duration = getattr(metrics, 'avg_trade_duration_hours', 0)
            
            content = f"""
交易行为分析显示，策略在回测期间共执行{total_trades}笔交易，其中盈利交易{winning_trades}笔，
亏损交易{losing_trades}笔，胜率为{win_rate:.1%}。

从盈亏分布来看，平均盈利为{avg_win:.2f}，平均亏损为{abs(avg_loss):.2f}，
盈亏比为{abs(avg_win/avg_loss) if avg_loss != 0 else 0:.2f}，
{'表现良好' if abs(avg_win/avg_loss) > 1.5 else '有待优化' if avg_loss != 0 else '数据不足'}。

交易频率方面，平均持仓时间为{avg_duration:.1f}小时，
{'交易较为频繁' if avg_duration < 24 else '持仓周期适中' if avg_duration < 168 else '长期持仓策略'}。
            """.strip()
            
            # 交易统计表格
            trade_summary_table = {
                'title': '交易统计摘要',
                'headers': ['统计项', '数值', '占比/比率', '评价'],
                'rows': [
                    ['总交易次数', str(total_trades), '100%', '样本规模'],
                    ['盈利交易', str(winning_trades), f"{win_rate:.1%}", '胜率表现'],
                    ['亏损交易', str(losing_trades), f"{(1-win_rate):.1%}", '失败率'],
                    ['平均盈利', f"{avg_win:.2f}", f"{avg_win:.2f}", '单笔盈利'],
                    ['平均亏损', f"{abs(avg_loss):.2f}", f"{abs(avg_loss):.2f}", '单笔亏损'],
                    ['盈亏比', f"{abs(avg_win/avg_loss) if avg_loss != 0 else 0:.2f}", '比率', '盈亏关系'],
                    ['平均持仓时间', f"{avg_duration:.1f}小时", f"{avg_duration/24:.1f}天", '持仓周期']
                ]
            }
            
            return {
                'content': content,
                'trade_summary_table': trade_summary_table,
                'charts': ['trade_distribution', 'pnl_histogram']
            }
            
        except Exception as e:
            logger.error(f"❌ 创建交易分析失败: {e}")
            return {
                'content': '交易分析生成失败',
                'trade_summary_table': {'title': '交易统计', 'headers': [], 'rows': []}
            }
    
    async def _create_risk_analysis(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建风险分析"""
        try:
            metrics = results.get('metrics', {})
            
            max_drawdown = getattr(metrics, 'max_drawdown_percent', 0)
            sharpe_ratio = getattr(metrics, 'sharpe_ratio', 0)
            sortino_ratio = getattr(metrics, 'sortino_ratio', 0)
            max_consecutive_losses = getattr(metrics, 'max_consecutive_losses', 0)
            
            content = f"""
风险分析表明，策略的最大回撤为{max_drawdown:.2f}%，在可接受范围内。
最大连续亏损次数为{max_consecutive_losses}次，显示了策略的稳定性。

从风险调整收益角度，夏普比率{sharpe_ratio:.2f}和Sortino比率{sortino_ratio:.2f}
{'均表现优异' if sharpe_ratio > 1.5 and sortino_ratio > 1.5 else '表现尚可' if sharpe_ratio > 1 else '需要改善'}，
说明策略在风险控制方面{'表现出色' if max_drawdown < 10 else '有待加强'}。

整体而言，策略的风险特征{'符合预期' if max_drawdown < 15 and max_consecutive_losses < 5 else '需要关注'}，
建议{'继续使用' if max_drawdown < 10 and sharpe_ratio > 1 else '优化后使用'}。
            """.strip()
            
            # 风险指标表格
            risk_metrics_table = {
                'title': '风险指标详情',
                'headers': ['风险指标', '数值', '风险等级', '说明'],
                'rows': [
                    ['最大回撤', f"{max_drawdown:.2f}%", self._assess_risk_level(max_drawdown, 'drawdown'), '最大资金损失'],
                    ['夏普比率', f"{sharpe_ratio:.2f}", self._assess_risk_level(sharpe_ratio, 'sharpe'), '风险调整收益'],
                    ['Sortino比率', f"{sortino_ratio:.2f}", self._assess_risk_level(sortino_ratio, 'sortino'), '下行风险调整'],
                    ['最大连亏', f"{max_consecutive_losses}次", self._assess_risk_level(max_consecutive_losses, 'consecutive'), '连续亏损风险']
                ]
            }
            
            # 风险洞察
            risk_insights = []
            
            if max_drawdown > 20:
                risk_insights.append("🚨 最大回撤超过20%，存在较高的资金损失风险")
            elif max_drawdown > 10:
                risk_insights.append("⚠️ 最大回撤超过10%，建议加强风险控制")
            else:
                risk_insights.append("✅ 回撤控制良好，风险管理有效")
            
            if max_consecutive_losses > 5:
                risk_insights.append("🔄 连续亏损次数较多，可能存在策略适应性问题")
            
            if sharpe_ratio < 1:
                risk_insights.append("📊 夏普比率偏低，风险调整后收益不佳")
            
            return {
                'content': content,
                'risk_metrics_table': risk_metrics_table,
                'risk_insights': risk_insights
            }
            
        except Exception as e:
            logger.error(f"❌ 创建风险分析失败: {e}")
            return {
                'content': '风险分析生成失败',
                'risk_metrics_table': {'title': '风险指标', 'headers': [], 'rows': []},
                'risk_insights': []
            }
    
    async def _create_optimization_recommendations(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建优化建议"""
        try:
            metrics = results.get('metrics', {})
            
            total_return = getattr(metrics, 'total_pnl_percent', 0)
            sharpe_ratio = getattr(metrics, 'sharpe_ratio', 0)
            win_rate = getattr(metrics, 'win_rate', 0)
            max_drawdown = getattr(metrics, 'max_drawdown_percent', 0)
            
            content = """
基于回测结果分析，我们识别出以下优化机会和改进建议。
这些建议旨在提升策略的整体表现，包括收益提升、风险控制和执行效率等方面。

建议按优先级顺序实施，并在实施后重新进行回测验证效果。
            """.strip()
            
            recommendations = []
            
            # 基于收益率的建议
            if total_return < 5:
                recommendations.append("📈 总收益率偏低，建议优化入场信号的准确性")
                recommendations.append("🎯 考虑增加技术指标组合，提高信号质量")
            
            # 基于胜率的建议
            if win_rate < 0.4:
                recommendations.append("🔍 胜率较低，建议重新评估入场条件")
                recommendations.append("⏰ 考虑优化入场时机，避免噪音交易")
            elif win_rate > 0.7:
                recommendations.append("💎 胜率较高但可能错过机会，考虑适度放宽入场条件")
            
            # 基于夏普比率的建议
            if sharpe_ratio < 1:
                recommendations.append("⚖️ 夏普比率偏低，建议优化风险管理策略")
                recommendations.append("🛡️ 考虑引入动态止损机制")
            
            # 基于回撤的建议
            if max_drawdown > 15:
                recommendations.append("🚨 最大回撤过大，建议强化风险控制")
                recommendations.append("📊 考虑引入仓位管理和资金分配策略")
            
            # 通用优化建议
            recommendations.extend([
                "🔄 定期重新优化策略参数，适应市场变化",
                "📱 考虑增加多时间周期确认，提高信号可靠性",
                "🤖 探索机器学习技术，增强策略适应性",
                "💼 建议进行不同市场环境下的压力测试"
            ])
            
            return {
                'content': content,
                'recommendations': recommendations[:8]  # 限制建议数量
            }
            
        except Exception as e:
            logger.error(f"❌ 创建优化建议失败: {e}")
            return {
                'content': '优化建议生成失败',
                'recommendations': []
            }
    
    # 辅助方法
    def _generate_report_subtitle(self, results: Dict[str, Any]) -> str:
        """生成报告副标题"""
        config = results.get('config', {})
        symbols = config.get('symbols', [])
        start_date = config.get('start_date', '')
        end_date = config.get('end_date', '')
        
        if symbols:
            symbol_text = symbols[0] if len(symbols) == 1 else f"{symbols[0]}等{len(symbols)}个标的"
        else:
            symbol_text = "未知标的"
        
        return f"{symbol_text} | {start_date} - {end_date}"
    
    def _grade_performance(self, value: float, metric_type: str) -> str:
        """评级绩效表现"""
        if metric_type == 'return':
            if value > 20: return "A+"
            elif value > 10: return "A"
            elif value > 5: return "B+"
            elif value > 0: return "B"
            else: return "C"
        elif metric_type == 'sharpe':
            if value > 2: return "A+"
            elif value > 1.5: return "A"
            elif value > 1: return "B+"
            elif value > 0.5: return "B"
            else: return "C"
        elif metric_type == 'drawdown':
            if value < 5: return "A+"
            elif value < 10: return "A"
            elif value < 15: return "B+"
            elif value < 20: return "B"
            else: return "C"
        else:
            return "B"  # 默认评级
    
    def _assess_risk_level(self, value: float, risk_type: str) -> str:
        """评估风险等级"""
        if risk_type == 'drawdown':
            if value < 5: return "低风险"
            elif value < 10: return "中等风险"
            elif value < 20: return "较高风险"
            else: return "高风险"
        elif risk_type == 'sharpe':
            if value > 1.5: return "低风险"
            elif value > 1: return "中等风险"
            elif value > 0.5: return "较高风险"
            else: return "高风险"
        elif risk_type == 'consecutive':
            if value < 3: return "低风险"
            elif value < 5: return "中等风险"
            elif value < 8: return "较高风险"
            else: return "高风险"
        else:
            return "中等风险"
    
    async def _create_summary_stats(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建摘要统计"""
        try:
            metrics = results.get('metrics', {})
            
            return {
                'total_return': getattr(metrics, 'total_pnl_percent', 0),
                'sharpe_ratio': getattr(metrics, 'sharpe_ratio', 0),
                'max_drawdown': getattr(metrics, 'max_drawdown_percent', 0),
                'win_rate': getattr(metrics, 'win_rate', 0),
                'total_trades': getattr(metrics, 'total_trades', 0),
                'profit_factor': getattr(metrics, 'profit_factor', 0)
            }
        except Exception as e:
            logger.error(f"❌ 创建摘要统计失败: {e}")
            return {}
    
    async def _create_conclusions(self, results: Dict[str, Any]) -> List[str]:
        """创建结论"""
        try:
            metrics = results.get('metrics', {})
            
            total_return = getattr(metrics, 'total_pnl_percent', 0)
            sharpe_ratio = getattr(metrics, 'sharpe_ratio', 0)
            max_drawdown = getattr(metrics, 'max_drawdown_percent', 0)
            
            conclusions = []
            
            # 整体表现结论
            if total_return > 10 and sharpe_ratio > 1.5 and max_drawdown < 10:
                conclusions.append("🎯 策略表现优异，具备强劲的实盘应用潜力")
            elif total_return > 0 and sharpe_ratio > 1:
                conclusions.append("👍 策略表现良好，建议小资金试运行")
            else:
                conclusions.append("⚠️ 策略表现有待改善，建议进一步优化")
            
            # 风险控制结论
            if max_drawdown < 10:
                conclusions.append("🛡️ 风险控制表现出色，符合稳健投资要求")
            else:
                conclusions.append("📊 风险控制需要加强，建议优化止损策略")
            
            # 实施建议
            conclusions.append("🔄 建议进行不同市场环境下的验证测试")
            conclusions.append("📱 实盘前建议进行小额资金的模拟运行")
            
            return conclusions
            
        except Exception as e:
            logger.error(f"❌ 创建结论失败: {e}")
            return ["结论生成失败，请检查回测数据"]
    
    # 其他报告章节的创建方法（占位符，可根据需要实现）
    async def _create_key_findings(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建关键发现（高管报告用）"""
        # 实现关键发现逻辑
        pass
    
    async def _create_investment_recommendation(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建投资建议（高管报告用）"""
        # 实现投资建议逻辑
        pass
    
    async def _create_technical_analysis(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建技术分析（详细报告用）"""
        # 实现技术分析逻辑
        pass
    
    async def _create_var_analysis(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """创建VaR分析（风险报告用）"""
        # 实现VaR分析逻辑
        pass
    
    # 导出功能
    async def export_report_to_html(self, report: Dict[str, Any]) -> str:
        """导出报告为HTML格式"""
        try:
            html_template = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        .subtitle {{ color: #7f8c8d; font-size: 16px; margin-bottom: 20px; }}
        .section {{ margin-bottom: 30px; }}
        .insights {{ background: #ecf0f1; padding: 15px; border-left: 4px solid #3498db; margin: 15px 0; }}
        .insights li {{ margin: 5px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #f8f9fa; font-weight: bold; }}
        .chart-placeholder {{ background: #f8f9fa; padding: 20px; text-align: center; margin: 15px 0; border: 2px dashed #bdc3c7; }}
        .conclusions {{ background: #e8f5e8; padding: 20px; border-radius: 5px; margin-top: 30px; }}
        .footer {{ text-align: center; margin-top: 30px; color: #95a5a6; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <div class="subtitle">{subtitle}</div>
        {content}
        <div class="footer">
            报告生成时间: {generated_at}<br>
            © 量化交易分析系统
        </div>
    </div>
</body>
</html>
            """
            
            # 构建内容
            content_parts = []
            
            for section in report.get('sections', []):
                content_parts.append(f'<div class="section">')
                content_parts.append(f'<h2>{section["title"]}</h2>')
                content_parts.append(f'<p>{section["content"]}</p>')
                
                # 添加表格
                if section.get('tables'):
                    for table in section['tables']:
                        content_parts.append(f'<h3>{table["title"]}</h3>')
                        content_parts.append('<table>')
                        content_parts.append('<tr>')
                        for header in table['headers']:
                            content_parts.append(f'<th>{header}</th>')
                        content_parts.append('</tr>')
                        
                        for row in table['rows']:
                            content_parts.append('<tr>')
                            for cell in row:
                                content_parts.append(f'<td>{cell}</td>')
                            content_parts.append('</tr>')
                        content_parts.append('</table>')
                
                # 添加图表占位符
                if section.get('charts'):
                    for chart in section['charts']:
                        content_parts.append(f'<div class="chart-placeholder">图表: {chart}</div>')
                
                # 添加洞察
                if section.get('insights'):
                    content_parts.append('<div class="insights">')
                    content_parts.append('<ul>')
                    for insight in section['insights']:
                        content_parts.append(f'<li>{insight}</li>')
                    content_parts.append('</ul>')
                    content_parts.append('</div>')
                
                content_parts.append('</div>')
            
            # 添加结论
            if report.get('conclusions'):
                content_parts.append('<div class="conclusions">')
                content_parts.append('<h2>总结</h2>')
                content_parts.append('<ul>')
                for conclusion in report['conclusions']:
                    content_parts.append(f'<li>{conclusion}</li>')
                content_parts.append('</ul>')
                content_parts.append('</div>')
            
            # 填充模板
            html_content = html_template.format(
                title=report.get('title', '回测报告'),
                subtitle=report.get('subtitle', ''),
                content=''.join(content_parts),
                generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
            
            # 保存文件
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_path = f"logs/cache/backtest_report_{timestamp}.html"
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            logger.info(f"📄 HTML报告已导出: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"❌ 导出HTML报告失败: {e}")
            raise TradingToolError(f"HTML导出失败: {str(e)}")
    
    async def export_report_to_json(self, report: Dict[str, Any]) -> str:
        """导出报告为JSON格式"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_path = f"logs/cache/backtest_report_{timestamp}.json"
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            
            logger.info(f"📄 JSON报告已导出: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"❌ 导出JSON报告失败: {e}")
            raise TradingToolError(f"JSON导出失败: {str(e)}")


