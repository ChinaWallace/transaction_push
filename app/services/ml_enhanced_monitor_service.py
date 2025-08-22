# -*- coding: utf-8 -*-
"""
ML增强监控服务
ML Enhanced Monitor Service with intelligent alerts and predictions
"""

import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from app.core.config import get_settings
from app.core.logging import get_logger, monitor_logger
from app.services.binance_service import BinanceService
from app.services.notification_service import NotificationService
from app.services.ml_enhanced_service import MLEnhancedService, PredictionSignal, AnomalyType
from app.services.monitor_service import MonitorService
from app.utils.exceptions import MonitorError, MLModelError

logger = get_logger(__name__)
settings = get_settings()


class AlertLevel(Enum):
    """警报级别枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class EnhancedAlert:
    """增强警报"""
    symbol: str
    alert_type: str
    level: AlertLevel
    message: str
    ml_prediction: Optional[Dict[str, Any]]
    anomaly_data: Optional[Dict[str, Any]]
    confidence_score: float
    recommendation: str
    timestamp: datetime


class MLEnhancedMonitorService:
    """ML增强监控服务类"""
    
    def __init__(self):
        self.binance_service = BinanceService()
        self.notification_service = NotificationService()
        self.ml_service = MLEnhancedService()
        self.traditional_monitor = MonitorService()
        
        # 配置
        self.ml_config = settings.ml_config
        self.monitored_symbols = settings.monitored_symbols
        
        # 警报历史（防止重复推送）
        self._alert_history = {}
        self._last_ml_analysis = {}
    
    async def enhanced_monitoring_cycle(self) -> Dict[str, Any]:
        """
        增强监控周期
        
        结合传统监控和ML分析的综合监控
        """
        try:
            monitor_logger.info("Starting enhanced monitoring cycle")
            
            results = {
                'timestamp': datetime.now(),
                'symbols_analyzed': len(self.monitored_symbols),
                'alerts': [],
                'ml_predictions': {},
                'anomalies': {},
                'traditional_alerts': {},
                'summary': {}
            }
            
            # 并发执行传统监控和ML分析
            tasks = []
            
            # 传统监控任务
            tasks.append(self._run_traditional_monitoring())
            
            # ML分析任务
            if self.ml_config.get('enable_ml_prediction', False):
                tasks.append(self._run_ml_analysis())
            
            # 异常检测任务
            if self.ml_config.get('enable_anomaly_detection', False):
                tasks.append(self._run_anomaly_detection())
            
            # 执行所有任务
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            traditional_results = task_results[0] if len(task_results) > 0 else {}
            ml_results = task_results[1] if len(task_results) > 1 and not isinstance(task_results[1], Exception) else {}
            anomaly_results = task_results[2] if len(task_results) > 2 and not isinstance(task_results[2], Exception) else {}
            
            # 合并结果
            results['traditional_alerts'] = traditional_results
            results['ml_predictions'] = ml_results
            results['anomalies'] = anomaly_results
            
            # 生成增强警报
            enhanced_alerts = await self._generate_enhanced_alerts(
                traditional_results, ml_results, anomaly_results
            )
            
            results['alerts'] = enhanced_alerts
            
            # 发送重要警报
            await self._send_critical_alerts(enhanced_alerts)
            
            # 生成摘要
            results['summary'] = self._generate_monitoring_summary(results)
            
            monitor_logger.info(f"Enhanced monitoring completed: {len(enhanced_alerts)} alerts generated")
            
            return results
            
        except Exception as e:
            logger.error(f"Enhanced monitoring cycle failed: {e}")
            raise MonitorError(f"Enhanced monitoring failed: {e}")
    
    async def _run_traditional_monitoring(self) -> Dict[str, Any]:
        """运行传统监控"""
        try:
            results = {}
            
            # 资金费率监控
            funding_results = await self.traditional_monitor.monitor_funding_rate(
                symbols=self.monitored_symbols, notify=False
            )
            results['funding_rate'] = funding_results
            
            # 持仓量监控
            oi_results = await self.traditional_monitor.monitor_open_interest(
                symbols=self.monitored_symbols, notify=False
            )
            results['open_interest'] = oi_results
            
            # 成交量监控
            volume_results = await self.traditional_monitor.monitor_volume_anomaly(
                symbols=self.monitored_symbols, notify=False
            )
            results['volume'] = volume_results
            
            return results
            
        except Exception as e:
            logger.error(f"Traditional monitoring failed: {e}")
            return {}
    
    async def _run_ml_analysis(self) -> Dict[str, Any]:
        """运行ML分析"""
        try:
            results = {}
            
            for symbol in self.monitored_symbols:
                try:
                    # 检查是否需要重新分析（避免频繁分析）
                    if self._should_run_ml_analysis(symbol):
                        prediction = await self.ml_service.predict_signal(symbol)
                        results[symbol] = {
                            'signal': prediction.signal.value,
                            'confidence': prediction.confidence,
                            'probability_distribution': prediction.probability_distribution,
                            'model_accuracy': prediction.model_accuracy,
                            'timestamp': prediction.timestamp
                        }
                        
                        # 更新最后分析时间
                        self._last_ml_analysis[symbol] = datetime.now()
                        
                except Exception as e:
                    logger.warning(f"ML analysis failed for {symbol}: {e}")
                    results[symbol] = {'error': str(e)}
            
            return results
            
        except Exception as e:
            logger.error(f"ML analysis failed: {e}")
            return {}
    
    async def _run_anomaly_detection(self) -> Dict[str, Any]:
        """运行异常检测"""
        try:
            results = {}
            
            for symbol in self.monitored_symbols:
                try:
                    anomalies = await self.ml_service.detect_anomalies(symbol)
                    if anomalies:
                        results[symbol] = [
                            {
                                'type': anomaly.anomaly_type.value,
                                'severity': anomaly.severity,
                                'description': anomaly.description,
                                'recommendation': anomaly.recommendation,
                                'timestamp': anomaly.timestamp
                            }
                            for anomaly in anomalies
                        ]
                        
                except Exception as e:
                    logger.warning(f"Anomaly detection failed for {symbol}: {e}")
                    results[symbol] = {'error': str(e)}
            
            return results
            
        except Exception as e:
            logger.error(f"Anomaly detection failed: {e}")
            return {}
    
    def _should_run_ml_analysis(self, symbol: str) -> bool:
        """判断是否需要运行ML分析"""
        last_analysis = self._last_ml_analysis.get(symbol)
        if last_analysis is None:
            return True
        
        # 每15分钟分析一次
        analysis_interval = timedelta(minutes=15)
        return datetime.now() - last_analysis > analysis_interval
    
    async def _generate_enhanced_alerts(self, 
                                      traditional_results: Dict[str, Any],
                                      ml_results: Dict[str, Any],
                                      anomaly_results: Dict[str, Any]) -> List[EnhancedAlert]:
        """生成增强警报"""
        alerts = []
        
        for symbol in self.monitored_symbols:
            try:
                # 获取各类数据
                ml_data = ml_results.get(symbol, {})
                anomaly_data = anomaly_results.get(symbol, [])
                
                # 分析传统监控结果
                traditional_alerts = self._extract_traditional_alerts(symbol, traditional_results)
                
                # 生成ML增强警报
                for traditional_alert in traditional_alerts:
                    enhanced_alert = await self._create_enhanced_alert(
                        symbol, traditional_alert, ml_data, anomaly_data
                    )
                    if enhanced_alert:
                        alerts.append(enhanced_alert)
                
                # 生成纯ML警报
                ml_alert = await self._create_ml_only_alert(symbol, ml_data, anomaly_data)
                if ml_alert:
                    alerts.append(ml_alert)
                    
            except Exception as e:
                logger.warning(f"Failed to generate enhanced alerts for {symbol}: {e}")
        
        return alerts
    
    def _extract_traditional_alerts(self, symbol: str, traditional_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从传统监控结果中提取警报"""
        alerts = []
        
        # 资金费率警报
        funding_data = traditional_results.get('funding_rate', {})
        if funding_data.get('alerts'):
            for alert in funding_data['alerts']:
                if alert.get('symbol') == symbol:
                    alerts.append({
                        'type': 'funding_rate',
                        'data': alert,
                        'level': 'medium' if abs(alert.get('rate', 0)) > 0.05 else 'low'
                    })
        
        # 持仓量警报
        oi_data = traditional_results.get('open_interest', {})
        if oi_data.get('alerts'):
            for alert in oi_data['alerts']:
                if alert.get('symbol') == symbol:
                    change_pct = alert.get('change_percentage', 0)
                    level = 'high' if abs(change_pct) > 10 else 'medium'
                    alerts.append({
                        'type': 'open_interest',
                        'data': alert,
                        'level': level
                    })
        
        # 成交量警报
        volume_data = traditional_results.get('volume', {})
        if volume_data.get('alerts'):
            for alert in volume_data['alerts']:
                if alert.get('symbol') == symbol:
                    multiplier = alert.get('volume_multiplier', 1)
                    level = 'high' if multiplier > 5 else 'medium'
                    alerts.append({
                        'type': 'volume',
                        'data': alert,
                        'level': level
                    })
        
        return alerts
    
    async def _create_enhanced_alert(self, 
                                   symbol: str,
                                   traditional_alert: Dict[str, Any],
                                   ml_data: Dict[str, Any],
                                   anomaly_data: List[Dict[str, Any]]) -> Optional[EnhancedAlert]:
        """创建增强警报"""
        try:
            alert_type = traditional_alert['type']
            traditional_level = traditional_alert['level']
            
            # 基础信息
            message_parts = [f"【{symbol}】{alert_type.upper()}警报"]
            
            # ML预测信息
            ml_prediction = None
            if ml_data and 'signal' in ml_data:
                ml_prediction = ml_data
                signal = ml_data['signal']
                confidence = ml_data.get('confidence', 0)
                
                message_parts.append(f"ML预测: {signal} (置信度: {confidence:.2%})")
            
            # 异常信息
            anomaly_info = None
            if anomaly_data:
                high_severity_anomalies = [a for a in anomaly_data if a.get('severity', 0) > 0.7]
                if high_severity_anomalies:
                    anomaly_info = high_severity_anomalies[0]
                    message_parts.append(f"检测到异常: {anomaly_info['description']}")
            
            # 计算综合置信度
            confidence_score = self._calculate_combined_confidence(
                traditional_alert, ml_data, anomaly_data
            )
            
            # 确定警报级别
            alert_level = self._determine_alert_level(
                traditional_level, ml_data, anomaly_data, confidence_score
            )
            
            # 生成建议
            recommendation = self._generate_recommendation(
                alert_type, ml_data, anomaly_data, alert_level
            )
            
            # 检查是否需要发送（防止重复）
            if not self._should_send_alert(symbol, alert_type, alert_level):
                return None
            
            enhanced_alert = EnhancedAlert(
                symbol=symbol,
                alert_type=alert_type,
                level=alert_level,
                message="\n".join(message_parts),
                ml_prediction=ml_prediction,
                anomaly_data=anomaly_info,
                confidence_score=confidence_score,
                recommendation=recommendation,
                timestamp=datetime.now()
            )
            
            # 记录警报历史
            self._record_alert_history(symbol, alert_type, alert_level)
            
            return enhanced_alert
            
        except Exception as e:
            logger.error(f"Failed to create enhanced alert for {symbol}: {e}")
            return None
    
    async def _create_ml_only_alert(self, 
                                  symbol: str,
                                  ml_data: Dict[str, Any],
                                  anomaly_data: List[Dict[str, Any]]) -> Optional[EnhancedAlert]:
        """创建纯ML警报"""
        try:
            # 只有在ML信号强烈或检测到严重异常时才发送
            should_alert = False
            alert_reasons = []
            
            # 检查ML信号
            if ml_data and 'signal' in ml_data:
                signal = ml_data['signal']
                confidence = ml_data.get('confidence', 0)
                
                # 强烈信号且高置信度
                if signal in ['strong_buy', 'strong_sell'] and confidence > 0.8:
                    should_alert = True
                    alert_reasons.append(f"强烈{signal}信号 (置信度: {confidence:.2%})")
            
            # 检查严重异常
            critical_anomalies = [a for a in anomaly_data if a.get('severity', 0) > 0.8]
            if critical_anomalies:
                should_alert = True
                for anomaly in critical_anomalies[:2]:  # 最多显示2个异常
                    alert_reasons.append(f"严重异常: {anomaly['description']}")
            
            if not should_alert or not alert_reasons:
                return None
            
            # 检查是否需要发送
            if not self._should_send_alert(symbol, 'ml_signal', AlertLevel.HIGH):
                return None
            
            message = f"【{symbol}】ML智能警报\n" + "\n".join(alert_reasons)
            
            recommendation = "建议密切关注市场动态，考虑调整仓位"
            if ml_data and ml_data.get('signal') in ['strong_buy', 'buy']:
                recommendation = "ML模型建议关注买入机会，但请结合其他指标确认"
            elif ml_data and ml_data.get('signal') in ['strong_sell', 'sell']:
                recommendation = "ML模型建议关注卖出机会，注意风险控制"
            
            enhanced_alert = EnhancedAlert(
                symbol=symbol,
                alert_type='ml_signal',
                level=AlertLevel.HIGH,
                message=message,
                ml_prediction=ml_data,
                anomaly_data=critical_anomalies[0] if critical_anomalies else None,
                confidence_score=ml_data.get('confidence', 0.5),
                recommendation=recommendation,
                timestamp=datetime.now()
            )
            
            # 记录警报历史
            self._record_alert_history(symbol, 'ml_signal', AlertLevel.HIGH)
            
            return enhanced_alert
            
        except Exception as e:
            logger.error(f"Failed to create ML-only alert for {symbol}: {e}")
            return None
    
    def _calculate_combined_confidence(self, 
                                     traditional_alert: Dict[str, Any],
                                     ml_data: Dict[str, Any],
                                     anomaly_data: List[Dict[str, Any]]) -> float:
        """计算综合置信度"""
        confidence_factors = []
        
        # 传统指标置信度
        traditional_confidence = 0.6  # 基础置信度
        if traditional_alert['level'] == 'high':
            traditional_confidence = 0.8
        elif traditional_alert['level'] == 'critical':
            traditional_confidence = 0.9
        confidence_factors.append(traditional_confidence)
        
        # ML预测置信度
        if ml_data and 'confidence' in ml_data:
            confidence_factors.append(ml_data['confidence'])
        
        # 异常检测置信度
        if anomaly_data:
            max_severity = max(a.get('severity', 0) for a in anomaly_data)
            confidence_factors.append(max_severity)
        
        # 计算加权平均
        if len(confidence_factors) > 1:
            return sum(confidence_factors) / len(confidence_factors)
        else:
            return confidence_factors[0] if confidence_factors else 0.5
    
    def _determine_alert_level(self, 
                             traditional_level: str,
                             ml_data: Dict[str, Any],
                             anomaly_data: List[Dict[str, Any]],
                             confidence_score: float) -> AlertLevel:
        """确定警报级别"""
        # 基础级别
        level_mapping = {
            'low': AlertLevel.LOW,
            'medium': AlertLevel.MEDIUM,
            'high': AlertLevel.HIGH,
            'critical': AlertLevel.CRITICAL
        }
        base_level = level_mapping.get(traditional_level, AlertLevel.MEDIUM)
        
        # ML信号调整
        if ml_data and 'signal' in ml_data:
            signal = ml_data['signal']
            confidence = ml_data.get('confidence', 0)
            
            if signal in ['strong_buy', 'strong_sell'] and confidence > 0.8:
                if base_level.value in ['low', 'medium']:
                    base_level = AlertLevel.HIGH
            elif signal in ['buy', 'sell'] and confidence > 0.7:
                if base_level == AlertLevel.LOW:
                    base_level = AlertLevel.MEDIUM
        
        # 异常检测调整
        if anomaly_data:
            max_severity = max(a.get('severity', 0) for a in anomaly_data)
            if max_severity > 0.8:
                if base_level.value in ['low', 'medium']:
                    base_level = AlertLevel.HIGH
        
        # 综合置信度调整
        if confidence_score > 0.9:
            if base_level == AlertLevel.HIGH:
                base_level = AlertLevel.CRITICAL
        elif confidence_score < 0.4:
            if base_level == AlertLevel.HIGH:
                base_level = AlertLevel.MEDIUM
        
        return base_level
    
    def _generate_recommendation(self, 
                               alert_type: str,
                               ml_data: Dict[str, Any],
                               anomaly_data: List[Dict[str, Any]],
                               alert_level: AlertLevel) -> str:
        """生成操作建议"""
        recommendations = []
        
        # 基于警报类型的建议
        if alert_type == 'funding_rate':
            recommendations.append("关注资金费率变化，考虑套利机会")
        elif alert_type == 'open_interest':
            recommendations.append("持仓量异常变化，注意市场情绪转变")
        elif alert_type == 'volume':
            recommendations.append("成交量异常放大，可能有重要消息或大资金进出")
        
        # 基于ML预测的建议
        if ml_data and 'signal' in ml_data:
            signal = ml_data['signal']
            if signal in ['strong_buy', 'buy']:
                recommendations.append("ML模型显示买入信号，可考虑逢低建仓")
            elif signal in ['strong_sell', 'sell']:
                recommendations.append("ML模型显示卖出信号，建议控制仓位风险")
            elif signal == 'hold':
                recommendations.append("ML模型建议观望，等待更明确信号")
        
        # 基于异常检测的建议
        if anomaly_data:
            for anomaly in anomaly_data[:1]:  # 只取第一个异常的建议
                if anomaly.get('recommendation'):
                    recommendations.append(anomaly['recommendation'])
        
        # 基于警报级别的建议
        if alert_level == AlertLevel.CRITICAL:
            recommendations.append("⚠️ 高风险警报，建议立即关注并采取行动")
        elif alert_level == AlertLevel.HIGH:
            recommendations.append("🔔 重要警报，建议密切关注市场动态")
        
        return " | ".join(recommendations) if recommendations else "建议持续关注市场变化"
    
    def _should_send_alert(self, symbol: str, alert_type: str, level: AlertLevel) -> bool:
        """判断是否应该发送警报（防重复）"""
        key = f"{symbol}_{alert_type}_{level.value}"
        last_sent = self._alert_history.get(key)
        
        if last_sent is None:
            return True
        
        # 根据级别设置不同的冷却时间
        cooldown_minutes = {
            AlertLevel.LOW: 60,      # 1小时
            AlertLevel.MEDIUM: 30,   # 30分钟
            AlertLevel.HIGH: 15,     # 15分钟
            AlertLevel.CRITICAL: 5   # 5分钟
        }
        
        cooldown = timedelta(minutes=cooldown_minutes.get(level, 30))
        return datetime.now() - last_sent > cooldown
    
    def _record_alert_history(self, symbol: str, alert_type: str, level: AlertLevel) -> None:
        """记录警报历史"""
        key = f"{symbol}_{alert_type}_{level.value}"
        self._alert_history[key] = datetime.now()
    
    async def _send_critical_alerts(self, alerts: List[EnhancedAlert]) -> None:
        """发送关键警报"""
        critical_alerts = [alert for alert in alerts if alert.level in [AlertLevel.HIGH, AlertLevel.CRITICAL]]
        
        if not critical_alerts:
            return
        
        try:
            for alert in critical_alerts:
                # 格式化消息
                formatted_message = self._format_alert_message(alert)
                
                # 发送通知
                await self.notification_service.send_notification(
                    message=formatted_message,
                    title=f"🚨 {alert.level.value.upper()} - {alert.symbol}",
                    priority="high" if alert.level == AlertLevel.CRITICAL else "normal"
                )
                
                monitor_logger.info(f"Sent {alert.level.value} alert for {alert.symbol}: {alert.alert_type}")
                
        except Exception as e:
            logger.error(f"Failed to send critical alerts: {e}")
    
    def _format_alert_message(self, alert: EnhancedAlert) -> str:
        """格式化警报消息"""
        level_icons = {
            AlertLevel.LOW: "🟢",
            AlertLevel.MEDIUM: "🟡", 
            AlertLevel.HIGH: "🔴",
            AlertLevel.CRITICAL: "🚨"
        }
        
        icon = level_icons.get(alert.level, "📊")
        
        message = f"""{icon} 【ML增强警报】

{alert.message}

💡 操作建议：{alert.recommendation}

📊 置信度：{alert.confidence_score:.2%}
⏰ 时间：{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"""
        
        return message
    
    def _generate_monitoring_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """生成监控摘要"""
        alerts = results.get('alerts', [])
        
        summary = {
            'total_alerts': len(alerts),
            'alert_levels': {
                'critical': len([a for a in alerts if a.level == AlertLevel.CRITICAL]),
                'high': len([a for a in alerts if a.level == AlertLevel.HIGH]),
                'medium': len([a for a in alerts if a.level == AlertLevel.MEDIUM]),
                'low': len([a for a in alerts if a.level == AlertLevel.LOW])
            },
            'alert_types': {},
            'symbols_with_alerts': list(set(a.symbol for a in alerts)),
            'ml_predictions_count': len([s for s in results.get('ml_predictions', {}).values() if 'signal' in s]),
            'anomalies_detected': sum(len(anomalies) for anomalies in results.get('anomalies', {}).values() if isinstance(anomalies, list)),
            'monitoring_health': 'healthy'
        }
        
        # 统计警报类型
        for alert in alerts:
            alert_type = alert.alert_type
            summary['alert_types'][alert_type] = summary['alert_types'].get(alert_type, 0) + 1
        
        # 评估监控健康状态
        if summary['alert_levels']['critical'] > 0:
            summary['monitoring_health'] = 'critical'
        elif summary['alert_levels']['high'] > 2:
            summary['monitoring_health'] = 'warning'
        
        return summary