# -*- coding: utf-8 -*-
"""
可视化服务
Visualization Service - 为回测结果生成图表和可视化内容
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import asyncio
import base64
import io

from app.core.logging import get_logger
from app.core.config import get_settings
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)
settings = get_settings()


class VisualizationService:
    """可视化服务"""
    
    def __init__(self):
        self.chart_cache_dir = Path("logs/cache/charts")
        self.chart_cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 尝试导入可视化库
        self.matplotlib_available = False
        self.seaborn_available = False
        self.plotly_available = False
        
        try:
            import matplotlib
            matplotlib.use('Agg')  # 非交互式后端
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from matplotlib.patches import Rectangle
            import seaborn as sns
            
            self.plt = plt
            self.mdates = mdates
            self.Rectangle = Rectangle
            self.sns = sns
            self.matplotlib_available = True
            self.seaborn_available = True
            
            # 设置中文字体
            plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
            plt.rcParams['axes.unicode_minus'] = False
            
            # 设置样式
            sns.set_style("whitegrid")
            sns.set_palette("husl")
            
        except ImportError as e:
            logger.warning(f"⚠️ 可视化库导入失败: {e}")
        
        try:
            import plotly.graph_objects as go
            import plotly.express as px
            from plotly.subplots import make_subplots
            
            self.go = go
            self.px = px
            self.make_subplots = make_subplots
            self.plotly_available = True
            
        except ImportError as e:
            logger.warning(f"⚠️ Plotly导入失败: {e}")
    
    async def generate_all_charts(
        self,
        backtest_results: Dict[str, Any],
        chart_format: str = "png",
        chart_size: Tuple[int, int] = (12, 8)
    ) -> Dict[str, str]:
        """
        生成所有回测图表
        
        Args:
            backtest_results: 回测结果数据
            chart_format: 图表格式 (png/svg/html)
            chart_size: 图表尺寸
            
        Returns:
            图表文件路径字典
        """
        try:
            logger.info(f"📊 开始生成回测图表")
            
            charts = {}
            
            if not self.matplotlib_available and not self.plotly_available:
                logger.warning("⚠️ 没有可用的可视化库，跳过图表生成")
                return charts
            
            # 权益曲线图
            if 'balance_history' in backtest_results:
                equity_chart = await self._generate_equity_curve(
                    backtest_results, chart_format, chart_size
                )
                if equity_chart:
                    charts['equity_curve'] = equity_chart
            
            # 回撤分析图
            if 'balance_history' in backtest_results:
                drawdown_chart = await self._generate_drawdown_chart(
                    backtest_results, chart_format, chart_size
                )
                if drawdown_chart:
                    charts['drawdown_chart'] = drawdown_chart
            
            # 交易分布图
            if 'trades' in backtest_results:
                trade_dist_chart = await self._generate_trade_distribution(
                    backtest_results, chart_format, chart_size
                )
                if trade_dist_chart:
                    charts['trade_distribution'] = trade_dist_chart
            
            # 盈亏分布直方图
            if 'trades' in backtest_results:
                pnl_hist_chart = await self._generate_pnl_histogram(
                    backtest_results, chart_format, chart_size
                )
                if pnl_hist_chart:
                    charts['pnl_histogram'] = pnl_hist_chart
            
            # 月度收益热力图
            if 'balance_history' in backtest_results:
                monthly_heatmap = await self._generate_monthly_returns_heatmap(
                    backtest_results, chart_format, chart_size
                )
                if monthly_heatmap:
                    charts['monthly_heatmap'] = monthly_heatmap
            
            # 滚动指标图
            if 'balance_history' in backtest_results:
                rolling_metrics_chart = await self._generate_rolling_metrics(
                    backtest_results, chart_format, chart_size
                )
                if rolling_metrics_chart:
                    charts['rolling_metrics'] = rolling_metrics_chart
            
            # 投资组合权重图（如果是投资组合回测）
            if 'portfolio_history' in backtest_results:
                portfolio_weights_chart = await self._generate_portfolio_weights(
                    backtest_results, chart_format, chart_size
                )
                if portfolio_weights_chart:
                    charts['portfolio_weights'] = portfolio_weights_chart
            
            # 风险指标雷达图
            if 'metrics' in backtest_results:
                risk_radar_chart = await self._generate_risk_radar(
                    backtest_results, chart_format, chart_size
                )
                if risk_radar_chart:
                    charts['risk_radar'] = risk_radar_chart
            
            logger.info(f"✅ 图表生成完成，共生成 {len(charts)} 个图表")
            return charts
            
        except Exception as e:
            logger.error(f"❌ 生成图表失败: {e}")
            return {}
    
    async def _generate_equity_curve(
        self,
        results: Dict[str, Any],
        chart_format: str,
        chart_size: Tuple[int, int]
    ) -> Optional[str]:
        """生成权益曲线图"""
        try:
            balance_history = results.get('balance_history', [])
            if not balance_history:
                return None
            
            # 准备数据
            timestamps = [item[0] if isinstance(item[0], datetime) else datetime.fromisoformat(item[0]) for item in balance_history]
            balances = [item[1] for item in balance_history]
            
            if self.plotly_available and chart_format == "html":
                # 使用Plotly生成交互式图表
                fig = self.go.Figure()
                
                fig.add_trace(self.go.Scatter(
                    x=timestamps,
                    y=balances,
                    mode='lines',
                    name='账户余额',
                    line=dict(color='blue', width=2),
                    hovertemplate='时间: %{x}<br>余额: %{y:,.2f}<extra></extra>'
                ))
                
                fig.update_layout(
                    title='权益曲线',
                    xaxis_title='时间',
                    yaxis_title='账户余额',
                    width=chart_size[0] * 80,
                    height=chart_size[1] * 80,
                    hovermode='x unified'
                )
                
                file_path = self.chart_cache_dir / f"equity_curve_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                fig.write_html(str(file_path))
                
            elif self.matplotlib_available:
                # 使用Matplotlib生成静态图表
                fig, ax = self.plt.subplots(figsize=chart_size)
                
                ax.plot(timestamps, balances, color='blue', linewidth=2, label='账户余额')
                ax.fill_between(timestamps, balances, alpha=0.3, color='blue')
                
                # 添加基准线
                initial_balance = balances[0]
                ax.axhline(y=initial_balance, color='gray', linestyle='--', alpha=0.7, label='初始资金')
                
                ax.set_title('权益曲线', fontsize=16, fontweight='bold')
                ax.set_xlabel('时间', fontsize=12)
                ax.set_ylabel('账户余额', fontsize=12)
                ax.legend()
                ax.grid(True, alpha=0.3)
                
                # 格式化x轴
                ax.xaxis.set_major_formatter(self.mdates.DateFormatter('%Y-%m-%d'))
                ax.xaxis.set_major_locator(self.mdates.DayLocator(interval=max(1, len(timestamps)//10)))
                self.plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
                
                self.plt.tight_layout()
                
                file_path = self.chart_cache_dir / f"equity_curve_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{chart_format}"
                self.plt.savefig(str(file_path), dpi=150, bbox_inches='tight')
                self.plt.close()
            
            else:
                return None
            
            logger.info(f"📈 权益曲线图已生成: {file_path}")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"❌ 生成权益曲线图失败: {e}")
            return None
    
    async def _generate_drawdown_chart(
        self,
        results: Dict[str, Any],
        chart_format: str,
        chart_size: Tuple[int, int]
    ) -> Optional[str]:
        """生成回撤分析图"""
        try:
            balance_history = results.get('balance_history', [])
            if not balance_history:
                return None
            
            # 准备数据
            timestamps = [item[0] if isinstance(item[0], datetime) else datetime.fromisoformat(item[0]) for item in balance_history]
            balances = [item[1] for item in balance_history]
            
            # 计算回撤
            peak = np.maximum.accumulate(balances)
            drawdown = (np.array(balances) - peak) / peak * 100
            
            if self.matplotlib_available:
                fig, (ax1, ax2) = self.plt.subplots(2, 1, figsize=chart_size, sharex=True)
                
                # 权益曲线
                ax1.plot(timestamps, balances, color='blue', linewidth=2, label='账户余额')
                ax1.plot(timestamps, peak, color='red', linestyle='--', alpha=0.7, label='历史峰值')
                ax1.set_title('权益曲线与历史峰值', fontsize=14, fontweight='bold')
                ax1.set_ylabel('账户余额', fontsize=12)
                ax1.legend()
                ax1.grid(True, alpha=0.3)
                
                # 回撤曲线
                ax2.fill_between(timestamps, drawdown, 0, alpha=0.3, color='red', label='回撤')
                ax2.plot(timestamps, drawdown, color='red', linewidth=1)
                ax2.set_title('回撤分析', fontsize=14, fontweight='bold')
                ax2.set_xlabel('时间', fontsize=12)
                ax2.set_ylabel('回撤 (%)', fontsize=12)
                ax2.legend()
                ax2.grid(True, alpha=0.3)
                
                # 标记最大回撤点
                max_dd_idx = np.argmin(drawdown)
                ax2.annotate(
                    f'最大回撤: {drawdown[max_dd_idx]:.2f}%',
                    xy=(timestamps[max_dd_idx], drawdown[max_dd_idx]),
                    xytext=(10, 10), textcoords='offset points',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7),
                    arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0')
                )
                
                # 格式化x轴
                ax2.xaxis.set_major_formatter(self.mdates.DateFormatter('%Y-%m-%d'))
                ax2.xaxis.set_major_locator(self.mdates.DayLocator(interval=max(1, len(timestamps)//10)))
                self.plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
                
                self.plt.tight_layout()
                
                file_path = self.chart_cache_dir / f"drawdown_chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{chart_format}"
                self.plt.savefig(str(file_path), dpi=150, bbox_inches='tight')
                self.plt.close()
                
                logger.info(f"📉 回撤分析图已生成: {file_path}")
                return str(file_path)
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 生成回撤分析图失败: {e}")
            return None
    
    async def _generate_trade_distribution(
        self,
        results: Dict[str, Any],
        chart_format: str,
        chart_size: Tuple[int, int]
    ) -> Optional[str]:
        """生成交易分布图"""
        try:
            trades = results.get('trades', [])
            if not trades:
                return None
            
            # 准备数据
            trade_data = []
            for trade in trades:
                if isinstance(trade, dict):
                    trade_data.append({
                        'pnl': trade.get('pnl', 0),
                        'pnl_percent': trade.get('pnl_percent', 0),
                        'duration_hours': trade.get('duration_hours', 0),
                        'entry_time': trade.get('entry_time', ''),
                        'side': trade.get('side', 'unknown')
                    })
            
            if not trade_data:
                return None
            
            df = pd.DataFrame(trade_data)
            
            if self.matplotlib_available:
                fig, ((ax1, ax2), (ax3, ax4)) = self.plt.subplots(2, 2, figsize=chart_size)
                
                # 盈亏分布
                profits = df[df['pnl'] > 0]['pnl']
                losses = df[df['pnl'] < 0]['pnl']
                
                ax1.hist([profits, losses], bins=20, alpha=0.7, color=['green', 'red'], label=['盈利', '亏损'])
                ax1.set_title('交易盈亏分布', fontweight='bold')
                ax1.set_xlabel('盈亏金额')
                ax1.set_ylabel('交易次数')
                ax1.legend()
                ax1.grid(True, alpha=0.3)
                
                # 盈亏百分比分布
                ax2.hist(df['pnl_percent'], bins=20, alpha=0.7, color='blue')
                ax2.set_title('收益率分布', fontweight='bold')
                ax2.set_xlabel('收益率 (%)')
                ax2.set_ylabel('交易次数')
                ax2.grid(True, alpha=0.3)
                
                # 持仓时间分布
                ax3.hist(df['duration_hours'], bins=20, alpha=0.7, color='orange')
                ax3.set_title('持仓时间分布', fontweight='bold')
                ax3.set_xlabel('持仓时间 (小时)')
                ax3.set_ylabel('交易次数')
                ax3.grid(True, alpha=0.3)
                
                # 多空分布
                side_counts = df['side'].value_counts()
                ax4.pie(side_counts.values, labels=side_counts.index, autopct='%1.1f%%', startangle=90)
                ax4.set_title('多空交易分布', fontweight='bold')
                
                self.plt.tight_layout()
                
                file_path = self.chart_cache_dir / f"trade_distribution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{chart_format}"
                self.plt.savefig(str(file_path), dpi=150, bbox_inches='tight')
                self.plt.close()
                
                logger.info(f"📊 交易分布图已生成: {file_path}")
                return str(file_path)
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 生成交易分布图失败: {e}")
            return None
    
    async def _generate_pnl_histogram(
        self,
        results: Dict[str, Any],
        chart_format: str,
        chart_size: Tuple[int, int]
    ) -> Optional[str]:
        """生成盈亏分布直方图"""
        try:
            trades = results.get('trades', [])
            if not trades:
                return None
            
            # 提取盈亏数据
            pnl_data = []
            for trade in trades:
                if isinstance(trade, dict):
                    pnl = trade.get('pnl_percent', 0)
                    if pnl != 0:  # 排除无效数据
                        pnl_data.append(pnl)
            
            if not pnl_data:
                return None
            
            if self.matplotlib_available:
                fig, ax = self.plt.subplots(figsize=chart_size)
                
                # 绘制直方图
                n, bins, patches = ax.hist(pnl_data, bins=30, alpha=0.7, edgecolor='black')
                
                # 为盈利和亏损设置不同颜色
                for i, (patch, bin_val) in enumerate(zip(patches, bins[:-1])):
                    if bin_val >= 0:
                        patch.set_facecolor('green')
                        patch.set_alpha(0.7)
                    else:
                        patch.set_facecolor('red')
                        patch.set_alpha(0.7)
                
                # 添加统计信息
                mean_pnl = np.mean(pnl_data)
                std_pnl = np.std(pnl_data)
                median_pnl = np.median(pnl_data)
                
                ax.axvline(mean_pnl, color='blue', linestyle='--', linewidth=2, label=f'均值: {mean_pnl:.2f}%')
                ax.axvline(median_pnl, color='orange', linestyle='--', linewidth=2, label=f'中位数: {median_pnl:.2f}%')
                ax.axvline(0, color='black', linestyle='-', linewidth=1, alpha=0.5, label='盈亏平衡线')
                
                ax.set_title('交易收益率分布直方图', fontsize=16, fontweight='bold')
                ax.set_xlabel('收益率 (%)', fontsize=12)
                ax.set_ylabel('交易次数', fontsize=12)
                ax.legend()
                ax.grid(True, alpha=0.3)
                
                # 添加统计文本
                stats_text = f'总交易: {len(pnl_data)}\n均值: {mean_pnl:.2f}%\n标准差: {std_pnl:.2f}%\n中位数: {median_pnl:.2f}%'
                ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, verticalalignment='top',
                       bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
                
                self.plt.tight_layout()
                
                file_path = self.chart_cache_dir / f"pnl_histogram_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{chart_format}"
                self.plt.savefig(str(file_path), dpi=150, bbox_inches='tight')
                self.plt.close()
                
                logger.info(f"📊 盈亏分布直方图已生成: {file_path}")
                return str(file_path)
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 生成盈亏分布直方图失败: {e}")
            return None
    
    async def _generate_monthly_returns_heatmap(
        self,
        results: Dict[str, Any],
        chart_format: str,
        chart_size: Tuple[int, int]
    ) -> Optional[str]:
        """生成月度收益热力图"""
        try:
            balance_history = results.get('balance_history', [])
            if not balance_history or len(balance_history) < 30:  # 需要足够的数据
                return None
            
            # 准备数据
            timestamps = [item[0] if isinstance(item[0], datetime) else datetime.fromisoformat(item[0]) for item in balance_history]
            balances = [item[1] for item in balance_history]
            
            # 转换为DataFrame
            df = pd.DataFrame({
                'date': timestamps,
                'balance': balances
            })
            df.set_index('date', inplace=True)
            
            # 计算日收益率
            df['returns'] = df['balance'].pct_change() * 100
            
            # 按月聚合
            monthly_returns = df['returns'].resample('M').apply(lambda x: (1 + x/100).prod() - 1) * 100
            
            if len(monthly_returns) < 3:  # 至少需要3个月的数据
                return None
            
            if self.seaborn_available and self.matplotlib_available:
                # 创建热力图数据
                monthly_returns.index = monthly_returns.index.strftime('%Y-%m')
                
                # 重新整理数据为矩阵形式
                years = set(pd.to_datetime(monthly_returns.index).year)
                months = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12']
                
                heatmap_data = []
                year_labels = []
                
                for year in sorted(years):
                    year_data = []
                    year_labels.append(str(year))
                    for month in months:
                        month_key = f"{year}-{month}"
                        if month_key in monthly_returns.index:
                            year_data.append(monthly_returns[month_key])
                        else:
                            year_data.append(np.nan)
                    heatmap_data.append(year_data)
                
                if heatmap_data:
                    fig, ax = self.plt.subplots(figsize=(12, max(4, len(years))))
                    
                    heatmap = self.sns.heatmap(
                        heatmap_data,
                        annot=True,
                        fmt='.1f',
                        cmap='RdYlGn',
                        center=0,
                        xticklabels=months,
                        yticklabels=year_labels,
                        cbar_kws={'label': '月度收益率 (%)'},
                        linewidths=0.5,
                        ax=ax
                    )
                    
                    ax.set_title('月度收益率热力图', fontsize=16, fontweight='bold')
                    ax.set_xlabel('月份', fontsize=12)
                    ax.set_ylabel('年份', fontsize=12)
                    
                    self.plt.tight_layout()
                    
                    file_path = self.chart_cache_dir / f"monthly_heatmap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{chart_format}"
                    self.plt.savefig(str(file_path), dpi=150, bbox_inches='tight')
                    self.plt.close()
                    
                    logger.info(f"🗓️ 月度收益热力图已生成: {file_path}")
                    return str(file_path)
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 生成月度收益热力图失败: {e}")
            return None
    
    async def _generate_rolling_metrics(
        self,
        results: Dict[str, Any],
        chart_format: str,
        chart_size: Tuple[int, int]
    ) -> Optional[str]:
        """生成滚动指标图"""
        try:
            balance_history = results.get('balance_history', [])
            if not balance_history or len(balance_history) < 50:
                return None
            
            # 准备数据
            timestamps = [item[0] if isinstance(item[0], datetime) else datetime.fromisoformat(item[0]) for item in balance_history]
            balances = [item[1] for item in balance_history]
            
            # 计算滚动指标
            df = pd.DataFrame({'date': timestamps, 'balance': balances})
            df.set_index('date', inplace=True)
            df['returns'] = df['balance'].pct_change()
            
            window = min(30, len(df) // 4)  # 滚动窗口
            
            # 滚动夏普比率
            rolling_sharpe = df['returns'].rolling(window).apply(
                lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0
            )
            
            # 滚动波动率
            rolling_volatility = df['returns'].rolling(window).std() * np.sqrt(252)
            
            # 滚动最大回撤
            rolling_max = df['balance'].rolling(window).max()
            rolling_drawdown = (df['balance'] - rolling_max) / rolling_max
            rolling_max_dd = rolling_drawdown.rolling(window).min()
            
            if self.matplotlib_available:
                fig, ((ax1, ax2), (ax3, ax4)) = self.plt.subplots(2, 2, figsize=chart_size)
                
                # 权益曲线
                ax1.plot(df.index, df['balance'], color='blue', linewidth=1.5)
                ax1.set_title('权益曲线', fontweight='bold')
                ax1.set_ylabel('账户余额')
                ax1.grid(True, alpha=0.3)
                
                # 滚动夏普比率
                ax2.plot(df.index, rolling_sharpe, color='green', linewidth=1.5)
                ax2.axhline(y=1, color='red', linestyle='--', alpha=0.7, label='基准线(1.0)')
                ax2.set_title(f'滚动夏普比率 ({window}期)', fontweight='bold')
                ax2.set_ylabel('夏普比率')
                ax2.legend()
                ax2.grid(True, alpha=0.3)
                
                # 滚动波动率
                ax3.plot(df.index, rolling_volatility * 100, color='orange', linewidth=1.5)
                ax3.set_title(f'滚动波动率 ({window}期)', fontweight='bold')
                ax3.set_ylabel('年化波动率 (%)')
                ax3.grid(True, alpha=0.3)
                
                # 滚动最大回撤
                ax4.fill_between(df.index, rolling_max_dd * 100, 0, alpha=0.3, color='red')
                ax4.plot(df.index, rolling_max_dd * 100, color='red', linewidth=1.5)
                ax4.set_title(f'滚动最大回撤 ({window}期)', fontweight='bold')
                ax4.set_ylabel('最大回撤 (%)')
                ax4.grid(True, alpha=0.3)
                
                # 格式化x轴
                for ax in [ax1, ax2, ax3, ax4]:
                    ax.xaxis.set_major_formatter(self.mdates.DateFormatter('%m-%d'))
                    ax.xaxis.set_major_locator(self.mdates.DayLocator(interval=max(1, len(df)//8)))
                    self.plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
                
                self.plt.tight_layout()
                
                file_path = self.chart_cache_dir / f"rolling_metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{chart_format}"
                self.plt.savefig(str(file_path), dpi=150, bbox_inches='tight')
                self.plt.close()
                
                logger.info(f"📈 滚动指标图已生成: {file_path}")
                return str(file_path)
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 生成滚动指标图失败: {e}")
            return None
    
    async def _generate_portfolio_weights(
        self,
        results: Dict[str, Any],
        chart_format: str,
        chart_size: Tuple[int, int]
    ) -> Optional[str]:
        """生成投资组合权重图"""
        try:
            portfolio_history = results.get('portfolio_history', [])
            if not portfolio_history:
                return None
            
            # 提取权重数据
            timestamps = []
            weights_data = {}
            
            for record in portfolio_history:
                timestamp = record.get('timestamp')
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp)
                timestamps.append(timestamp)
                
                weights = record.get('weights', {})
                for symbol, weight in weights.items():
                    if symbol not in weights_data:
                        weights_data[symbol] = []
                    weights_data[symbol].append(weight)
            
            if not weights_data or not timestamps:
                return None
            
            if self.matplotlib_available:
                fig, ax = self.plt.subplots(figsize=chart_size)
                
                # 绘制堆叠面积图
                symbols = list(weights_data.keys())
                weights_matrix = np.array([weights_data[symbol] for symbol in symbols]).T
                
                ax.stackplot(timestamps, weights_matrix.T, labels=symbols, alpha=0.7)
                
                ax.set_title('投资组合权重变化', fontsize=16, fontweight='bold')
                ax.set_xlabel('时间', fontsize=12)
                ax.set_ylabel('权重比例', fontsize=12)
                ax.legend(loc='center left', bbox_to_anchor=(1, 0.5))
                ax.grid(True, alpha=0.3)
                ax.set_ylim(0, 1)
                
                # 格式化x轴
                ax.xaxis.set_major_formatter(self.mdates.DateFormatter('%m-%d'))
                ax.xaxis.set_major_locator(self.mdates.DayLocator(interval=max(1, len(timestamps)//10)))
                self.plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
                
                self.plt.tight_layout()
                
                file_path = self.chart_cache_dir / f"portfolio_weights_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{chart_format}"
                self.plt.savefig(str(file_path), dpi=150, bbox_inches='tight')
                self.plt.close()
                
                logger.info(f"🥧 投资组合权重图已生成: {file_path}")
                return str(file_path)
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 生成投资组合权重图失败: {e}")
            return None
    
    async def _generate_risk_radar(
        self,
        results: Dict[str, Any],
        chart_format: str,
        chart_size: Tuple[int, int]
    ) -> Optional[str]:
        """生成风险指标雷达图"""
        try:
            metrics = results.get('metrics', {})
            if not metrics:
                return None
            
            # 提取风险指标并标准化到0-1
            risk_metrics = {
                '收益率': min(max(getattr(metrics, 'total_pnl_percent', 0) / 50, 0), 1),  # 标准化到50%
                '夏普比率': min(max(getattr(metrics, 'sharpe_ratio', 0) / 3, 0), 1),  # 标准化到3.0
                '胜率': getattr(metrics, 'win_rate', 0),  # 已经是0-1
                '盈亏比': min(max(getattr(metrics, 'profit_factor', 0) / 3, 0), 1),  # 标准化到3.0
                '稳定性': max(1 - getattr(metrics, 'max_drawdown_percent', 0) / 50, 0),  # 回撤越小越稳定
                '频率': min(max(getattr(metrics, 'total_trades', 0) / 100, 0), 1)  # 标准化到100笔
            }
            
            if self.matplotlib_available:
                # 雷达图数据
                categories = list(risk_metrics.keys())
                values = list(risk_metrics.values())
                
                # 计算角度
                angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
                values += values[:1]  # 闭合图形
                angles += angles[:1]
                
                fig, ax = self.plt.subplots(figsize=chart_size, subplot_kw=dict(projection='polar'))
                
                # 绘制雷达图
                ax.plot(angles, values, color='blue', linewidth=2, label='策略表现')
                ax.fill(angles, values, color='blue', alpha=0.25)
                
                # 设置标签
                ax.set_xticks(angles[:-1])
                ax.set_xticklabels(categories)
                ax.set_ylim(0, 1)
                
                # 添加网格线
                ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
                ax.set_yticklabels(['20%', '40%', '60%', '80%', '100%'])
                ax.grid(True)
                
                ax.set_title('策略风险指标雷达图', fontsize=16, fontweight='bold', pad=20)
                
                # 添加图例
                ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.0))
                
                # 添加指标说明
                explanation = '\n'.join([f"{k}: {v:.1%}" for k, v in risk_metrics.items()])
                ax.text(1.1, 0.5, explanation, transform=ax.transAxes, 
                       bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
                       verticalalignment='center')
                
                self.plt.tight_layout()
                
                file_path = self.chart_cache_dir / f"risk_radar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{chart_format}"
                self.plt.savefig(str(file_path), dpi=150, bbox_inches='tight')
                self.plt.close()
                
                logger.info(f"🎯 风险指标雷达图已生成: {file_path}")
                return str(file_path)
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 生成风险指标雷达图失败: {e}")
            return None
    
    async def generate_interactive_dashboard(
        self,
        backtest_results: Dict[str, Any]
    ) -> Optional[str]:
        """生成交互式仪表板"""
        try:
            if not self.plotly_available:
                logger.warning("⚠️ Plotly不可用，无法生成交互式仪表板")
                return None
            
            # 创建子图
            fig = self.make_subplots(
                rows=3, cols=2,
                subplot_titles=('权益曲线', '回撤分析', '收益分布', '月度表现', '风险指标', '交易统计'),
                specs=[[{"secondary_y": False}, {"secondary_y": False}],
                       [{"secondary_y": False}, {"secondary_y": False}],
                       [{"type": "polar"}, {"secondary_y": False}]]
            )
            
            # 权益曲线
            balance_history = backtest_results.get('balance_history', [])
            if balance_history:
                timestamps = [item[0] if isinstance(item[0], datetime) else datetime.fromisoformat(item[0]) for item in balance_history]
                balances = [item[1] for item in balance_history]
                
                fig.add_trace(
                    self.go.Scatter(x=timestamps, y=balances, mode='lines', name='权益曲线'),
                    row=1, col=1
                )
                
                # 回撤
                peak = np.maximum.accumulate(balances)
                drawdown = (np.array(balances) - peak) / peak * 100
                
                fig.add_trace(
                    self.go.Scatter(x=timestamps, y=drawdown, mode='lines', name='回撤', fill='tonexty'),
                    row=1, col=2
                )
            
            # 收益分布
            trades = backtest_results.get('trades', [])
            if trades:
                pnl_data = [trade.get('pnl_percent', 0) for trade in trades if isinstance(trade, dict)]
                
                fig.add_trace(
                    self.go.Histogram(x=pnl_data, name='收益分布', nbinsx=20),
                    row=2, col=1
                )
            
            # 更新布局
            fig.update_layout(
                height=1200,
                title_text="回测分析仪表板",
                showlegend=True
            )
            
            # 保存交互式图表
            file_path = self.chart_cache_dir / f"interactive_dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            fig.write_html(str(file_path))
            
            logger.info(f"📊 交互式仪表板已生成: {file_path}")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"❌ 生成交互式仪表板失败: {e}")
            return None
    
    def chart_to_base64(self, chart_path: str) -> Optional[str]:
        """将图表转换为base64编码"""
        try:
            if not Path(chart_path).exists():
                return None
            
            with open(chart_path, 'rb') as f:
                img_data = f.read()
            
            return base64.b64encode(img_data).decode('utf-8')
            
        except Exception as e:
            logger.error(f"❌ 图表转换base64失败: {e}")
            return None
    
    def cleanup_old_charts(self, days: int = 7):
        """清理旧图表文件"""
        try:
            cutoff_time = datetime.now() - timedelta(days=days)
            
            for chart_file in self.chart_cache_dir.glob("*"):
                if chart_file.is_file():
                    file_time = datetime.fromtimestamp(chart_file.stat().st_mtime)
                    if file_time < cutoff_time:
                        chart_file.unlink()
            
            logger.info(f"🧹 已清理{days}天前的图表文件")
            
        except Exception as e:
            logger.error(f"❌ 清理图表文件失败: {e}")


# 创建全局实例
visualization_service = VisualizationService()


