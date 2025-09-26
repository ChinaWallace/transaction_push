# -*- coding: utf-8 -*-
"""
网格交易调度器扩展
Grid Trading Scheduler Extension

为核心调度器添加网格交易推荐任务
"""

import asyncio
from typing import Dict, Any
from datetime import datetime

from app.core.logging import get_logger
from app.services.core.core_scheduler_service import get_core_scheduler_service, TaskPriority
from app.services.analysis.grid_trading_service import get_grid_trading_service
from app.services.notification.core_notification_service import get_core_notification_service

logger = get_logger(__name__)


class GridSchedulerExtension:
    """网格交易调度器扩展"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.initialized = False
        
        # 服务实例
        self.scheduler_service = None
        self.grid_service = None
        self.notification_service = None
    
    async def initialize(self) -> None:
        """初始化扩展"""
        if self.initialized:
            return
        
        try:
            # 获取服务实例
            self.scheduler_service = await get_core_scheduler_service()
            self.grid_service = await get_grid_trading_service()
            self.notification_service = await get_core_notification_service()
            
            # 注册网格交易任务
            await self._register_grid_trading_tasks()
            
            self.initialized = True
            self.logger.info("✅ 网格交易调度器扩展初始化完成")
            
        except Exception as e:
            self.logger.error(f"❌ 网格交易调度器扩展初始化失败: {e}")
            raise
    
    async def _register_grid_trading_tasks(self) -> None:
        """注册网格交易相关任务"""
        try:
            # 注册网格交易推荐任务 - 每小时执行一次
            self.scheduler_service.register_task(
                task_id="grid_trading_recommendations",
                name="网格交易机会推荐",
                func=self._run_grid_trading_recommendations,
                interval_minutes=60,  # 每小时执行
                priority=TaskPriority.NORMAL,
                enabled=True,
                max_retries=2,
                timeout_minutes=10,
                description="分析市场中适合做多网格交易的机会并推送推荐"
            )
            
            self.logger.info("✅ 网格交易任务注册完成")
            
        except Exception as e:
            self.logger.error(f"❌ 注册网格交易任务失败: {e}")
            raise
    
    async def _run_grid_trading_recommendations(self) -> Dict[str, Any]:
        """运行网格交易机会推荐任务"""
        try:
            self.logger.info("🔲 开始执行网格交易机会推荐...")
            
            # 分析网格交易机会
            from app.schemas.grid_trading import GridOpportunityLevel
            result = await self.grid_service.analyze_grid_opportunities(
                min_opportunity_level=GridOpportunityLevel.MODERATE
            )
            
            # 发送推荐通知
            if result.recommendations:
                await self._send_grid_trading_notification(result)
                self.logger.info(f"✅ 发送了 {len(result.recommendations)} 个网格交易推荐")
            else:
                # 即使没有推荐，也发送市场状态通知
                await self._send_no_opportunities_notification(result)
                self.logger.info("📉 当前无合适的网格交易机会")
            
            return {
                'status': 'success',
                'total_opportunities': result.total_count,
                'excellent_count': result.excellent_count,
                'good_count': result.good_count,
                'recommendations_sent': len(result.recommendations),
                'market_summary': result.market_summary,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"❌ 网格交易推荐任务失败: {e}")
            raise
    
    async def _send_grid_trading_notification(self, grid_result) -> None:
        """发送网格交易推荐通知"""
        try:
            from app.services.notification.core_notification_service import NotificationContent, NotificationType, NotificationPriority
            
            # 构建推荐消息
            message = f"🔲 **网格交易机会推荐** - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            message += f"📊 **市场概况**: {grid_result.market_summary}\n\n"
            message += f"🎯 **机会统计**:\n"
            message += f"• 总机会数: {grid_result.total_count}\n"
            message += f"• 优秀机会: {grid_result.excellent_count}\n"
            message += f"• 良好机会: {grid_result.good_count}\n\n"
            
            if grid_result.recommendations:
                message += f"🏆 **推荐机会** (前{min(5, len(grid_result.recommendations))}个):\n\n"
                
                for i, rec in enumerate(grid_result.recommendations[:5], 1):
                    # 趋势图标
                    trend_icon = {
                        'upward': '📈',
                        'sideways': '↔️',
                        'downward': '📉'
                    }.get(rec.trend_type.value, '📊')
                    
                    # 机会等级图标
                    level_icon = {
                        'excellent': '🌟',
                        'good': '⭐',
                        'moderate': '✨',
                        'poor': '💫'
                    }.get(rec.opportunity_level.value, '✨')
                    
                    message += f"{level_icon} **{i}. {rec.symbol}** {trend_icon}\n"
                    message += f"• 当前价格: ${rec.current_price:,.4f}\n"
                    message += f"• 推荐资金: {rec.recommended_capital:,.0f} USDT ({rec.position_percentage}%)\n"
                    message += f"• 交易区间: ${rec.trading_range.lower_bound:,.4f} - ${rec.trading_range.upper_bound:,.4f}\n"
                    message += f"• 网格配置: {rec.trading_range.grid_count}格, 间距{rec.trading_range.grid_spacing}%\n"
                    message += f"• 预期收益: 日{rec.expected_daily_return}% | 月{rec.expected_monthly_return}%\n"
                    message += f"• 风险等级: {rec.risk_level}\n"
                    message += f"• 推荐理由: {rec.reasoning}\n"
                    if rec.risk_warning:
                        message += f"• ⚠️ 风险提示: {rec.risk_warning}\n"
                    message += "\n"
            
            message += "💡 **网格交易提醒**:\n"
            message += "• 以上推荐基于1万U资金基准\n"
            message += "• 请根据个人风险承受能力调整仓位\n"
            message += "• 建议设置止损，防范极端行情\n"
            message += "• 注意手续费成本，选择合适的网格间距\n"
            
            content = NotificationContent(
                type=NotificationType.TRADING_SIGNAL,  # 使用交易信号类型
                priority=NotificationPriority.NORMAL,
                title="🔲 网格交易机会推荐",
                message=message,
                metadata={
                    'notification_type': 'grid_trading_recommendation',
                    'total_opportunities': grid_result.total_count,
                    'excellent_count': grid_result.excellent_count,
                    'good_count': grid_result.good_count,
                    'recommendations': [
                        {
                            'symbol': rec.symbol,
                            'opportunity_level': rec.opportunity_level.value,
                            'current_price': rec.current_price,
                            'recommended_capital': rec.recommended_capital,
                            'expected_daily_return': rec.expected_daily_return,
                            'risk_level': rec.risk_level,
                            'trend_type': rec.trend_type.value
                        }
                        for rec in grid_result.recommendations[:10]
                    ]
                }
            )
            
            await self.notification_service.send_notification(content)
            
        except Exception as e:
            self.logger.error(f"发送网格交易推荐通知失败: {e}")
    
    async def _send_no_opportunities_notification(self, grid_result) -> None:
        """发送无机会通知"""
        try:
            from app.services.notification.core_notification_service import NotificationContent, NotificationType, NotificationPriority
            
            message = f"🔲 **网格交易市场分析** - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            message += f"📊 **市场概况**: {grid_result.market_summary}\n\n"
            message += f"📉 **当前市场条件不适合网格交易**\n"
            message += f"• 分析了 {grid_result.total_count} 个交易对\n"
            message += f"• 未发现符合条件的网格交易机会\n\n"
            message += f"💡 **建议**:\n"
            message += f"• 等待市场波动率增加\n"
            message += f"• 关注震荡或上涨趋势的品种\n"
            message += f"• 下次分析时间: 1小时后\n"
            
            content = NotificationContent(
                type=NotificationType.MARKET_ANALYSIS,
                priority=NotificationPriority.LOW,
                title="🔲 网格交易市场分析",
                message=message,
                metadata={
                    'notification_type': 'grid_trading_no_opportunities',
                    'total_analyzed': grid_result.total_count,
                    'market_summary': grid_result.market_summary
                }
            )
            
            await self.notification_service.send_notification(content)
            
        except Exception as e:
            self.logger.error(f"发送无机会通知失败: {e}")
    
    async def run_startup_grid_recommendations(self) -> bool:
        """执行启动时的网格交易推荐"""
        try:
            self.logger.info("🚀 执行启动时网格交易推荐...")
            
            if not self.initialized:
                await self.initialize()
            
            # 执行推荐任务
            result = await self._run_grid_trading_recommendations()
            
            if result.get('status') == 'success':
                self.logger.info("✅ 启动时网格交易推荐完成")
                return True
            else:
                self.logger.warning("⚠️ 启动时网格交易推荐失败")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 启动时网格交易推荐异常: {e}")
            return False


# 全局单例实例
_grid_scheduler_extension: GridSchedulerExtension = None

async def get_grid_scheduler_extension() -> GridSchedulerExtension:
    """获取网格交易调度器扩展实例"""
    global _grid_scheduler_extension
    if _grid_scheduler_extension is None:
        _grid_scheduler_extension = GridSchedulerExtension()
        await _grid_scheduler_extension.initialize()
    return _grid_scheduler_extension