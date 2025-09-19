# -*- coding: utf-8 -*-
"""
错误分析工具
Error Analyzer - 分析和诊断系统错误
"""

import re
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)


class ErrorCategory(Enum):
    """错误分类"""
    NETWORK = "network"           # 网络连接错误
    API_RATE_LIMIT = "rate_limit"  # API频率限制
    DATA_FORMAT = "data_format"    # 数据格式错误
    AUTHENTICATION = "auth"        # 认证错误
    TIMEOUT = "timeout"           # 超时错误
    SERVER_ERROR = "server"       # 服务器错误
    UNKNOWN = "unknown"           # 未知错误


@dataclass
class ErrorAnalysis:
    """错误分析结果"""
    category: ErrorCategory
    severity: str  # 'low', 'medium', 'high', 'critical'
    description: str
    possible_causes: List[str]
    suggested_actions: List[str]
    is_recoverable: bool
    retry_recommended: bool


class ErrorAnalyzer:
    """错误分析器"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        
        # 错误模式匹配规则
        self.error_patterns = {
            # 网络连接错误
            ErrorCategory.NETWORK: [
                r'ClientConnectorError',
                r'ClientConnectionError', 
                r'ConnectionResetError',
                r'ConnectionRefusedError',
                r'ClientOSError',
                r'aiohttp\.client_exceptions\.ClientConnectorError',
                r'Cannot connect to host',
                r'Connection timeout',
                r'Name or service not known',
                r'Network is unreachable',
                r'No route to host'
            ],
            
            # API频率限制
            ErrorCategory.API_RATE_LIMIT: [
                r'Too Many Requests',
                r'Rate limit exceeded',
                r'HTTP 429',
                r'status.*429',
                r'Retry-After',
                r'Request rate limit'
            ],
            
            # 超时错误
            ErrorCategory.TIMEOUT: [
                r'TimeoutError',
                r'asyncio\.TimeoutError',
                r'ServerTimeoutError',
                r'timeout',
                r'timed out',
                r'Request timeout'
            ],
            
            # 认证错误
            ErrorCategory.AUTHENTICATION: [
                r'HTTP 401',
                r'HTTP 403',
                r'Unauthorized',
                r'Forbidden',
                r'Invalid API key',
                r'Authentication failed',
                r'Invalid signature'
            ],
            
            # 服务器错误
            ErrorCategory.SERVER_ERROR: [
                r'HTTP 5\d{2}',
                r'Internal Server Error',
                r'Bad Gateway',
                r'Service Unavailable',
                r'Gateway Timeout'
            ],
            
            # 数据格式错误
            ErrorCategory.DATA_FORMAT: [
                r'JSONDecodeError',
                r'Invalid JSON',
                r'KeyError',
                r'ValueError.*invalid literal',
                r'ParseError'
            ]
        }
    
    def analyze_error(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> ErrorAnalysis:
        """
        分析错误并提供诊断信息
        
        Args:
            error: 异常对象
            context: 错误上下文信息
            
        Returns:
            ErrorAnalysis: 错误分析结果
        """
        try:
            error_type = type(error).__name__
            error_message = str(error)
            
            # 分析错误类别
            category = self._categorize_error(error_type, error_message)
            
            # 根据类别生成分析结果
            analysis = self._generate_analysis(category, error_type, error_message, context)
            
            self.logger.debug(f"🔍 错误分析完成: {category.value} - {analysis.description}")
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"❌ 错误分析失败: {e}")
            return self._get_default_analysis(error)
    
    def _categorize_error(self, error_type: str, error_message: str) -> ErrorCategory:
        """根据错误类型和消息分类错误"""
        full_error_text = f"{error_type}: {error_message}"
        
        for category, patterns in self.error_patterns.items():
            for pattern in patterns:
                if re.search(pattern, full_error_text, re.IGNORECASE):
                    return category
        
        return ErrorCategory.UNKNOWN
    
    def _generate_analysis(
        self, 
        category: ErrorCategory, 
        error_type: str, 
        error_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ErrorAnalysis:
        """根据错误类别生成详细分析"""
        
        if category == ErrorCategory.NETWORK:
            return ErrorAnalysis(
                category=category,
                severity='high',
                description=f"网络连接错误 ({error_type})",
                possible_causes=[
                    "网络连接不稳定",
                    "代理服务器问题",
                    "DNS解析失败",
                    "目标服务器不可达",
                    "防火墙阻止连接"
                ],
                suggested_actions=[
                    "检查网络连接状态",
                    "验证代理配置",
                    "检查DNS设置",
                    "尝试重新连接",
                    "检查防火墙设置"
                ],
                is_recoverable=True,
                retry_recommended=True
            )
        
        elif category == ErrorCategory.API_RATE_LIMIT:
            return ErrorAnalysis(
                category=category,
                severity='medium',
                description=f"API频率限制 ({error_type})",
                possible_causes=[
                    "请求频率过高",
                    "达到API调用限制",
                    "并发请求过多"
                ],
                suggested_actions=[
                    "降低请求频率",
                    "增加请求间隔",
                    "实施指数退避策略",
                    "检查API配额使用情况"
                ],
                is_recoverable=True,
                retry_recommended=True
            )
        
        elif category == ErrorCategory.TIMEOUT:
            return ErrorAnalysis(
                category=category,
                severity='medium',
                description=f"请求超时 ({error_type})",
                possible_causes=[
                    "网络延迟过高",
                    "服务器响应慢",
                    "超时设置过短",
                    "网络不稳定"
                ],
                suggested_actions=[
                    "增加超时时间",
                    "重试请求",
                    "检查网络质量",
                    "使用更快的服务器"
                ],
                is_recoverable=True,
                retry_recommended=True
            )
        
        elif category == ErrorCategory.AUTHENTICATION:
            return ErrorAnalysis(
                category=category,
                severity='high',
                description=f"认证失败 ({error_type})",
                possible_causes=[
                    "API密钥无效",
                    "签名错误",
                    "权限不足",
                    "密钥过期"
                ],
                suggested_actions=[
                    "检查API密钥配置",
                    "验证签名算法",
                    "检查权限设置",
                    "更新API密钥"
                ],
                is_recoverable=False,
                retry_recommended=False
            )
        
        elif category == ErrorCategory.SERVER_ERROR:
            return ErrorAnalysis(
                category=category,
                severity='high',
                description=f"服务器错误 ({error_type})",
                possible_causes=[
                    "服务器内部错误",
                    "服务临时不可用",
                    "服务器维护",
                    "负载过高"
                ],
                suggested_actions=[
                    "稍后重试",
                    "检查服务状态",
                    "使用备用服务",
                    "联系技术支持"
                ],
                is_recoverable=True,
                retry_recommended=True
            )
        
        elif category == ErrorCategory.DATA_FORMAT:
            return ErrorAnalysis(
                category=category,
                severity='medium',
                description=f"数据格式错误 ({error_type})",
                possible_causes=[
                    "API响应格式变更",
                    "数据解析错误",
                    "编码问题",
                    "数据损坏"
                ],
                suggested_actions=[
                    "检查API文档",
                    "验证数据格式",
                    "更新解析逻辑",
                    "处理异常数据"
                ],
                is_recoverable=False,
                retry_recommended=False
            )
        
        else:  # UNKNOWN
            return ErrorAnalysis(
                category=category,
                severity='medium',
                description=f"未知错误 ({error_type})",
                possible_causes=[
                    "新类型的错误",
                    "系统异常",
                    "代码逻辑错误"
                ],
                suggested_actions=[
                    "查看详细日志",
                    "联系技术支持",
                    "检查代码逻辑",
                    "添加错误处理"
                ],
                is_recoverable=False,
                retry_recommended=False
            )
    
    def _get_default_analysis(self, error: Exception) -> ErrorAnalysis:
        """获取默认错误分析"""
        return ErrorAnalysis(
            category=ErrorCategory.UNKNOWN,
            severity='medium',
            description=f"分析失败的错误 ({type(error).__name__})",
            possible_causes=["错误分析器异常"],
            suggested_actions=["查看原始错误信息", "联系技术支持"],
            is_recoverable=False,
            retry_recommended=False
        )
    
    def format_analysis_report(self, analysis: ErrorAnalysis, include_actions: bool = True) -> str:
        """格式化错误分析报告"""
        severity_icons = {
            'low': '🟢',
            'medium': '🟡', 
            'high': '🔴',
            'critical': '💀'
        }
        
        icon = severity_icons.get(analysis.severity, '❓')
        
        report = f"{icon} {analysis.description}\n"
        report += f"📊 严重程度: {analysis.severity.upper()}\n"
        report += f"🔄 可恢复: {'是' if analysis.is_recoverable else '否'}\n"
        report += f"♻️  建议重试: {'是' if analysis.retry_recommended else '否'}\n"
        
        if analysis.possible_causes:
            report += f"\n🔍 可能原因:\n"
            for cause in analysis.possible_causes:
                report += f"  • {cause}\n"
        
        if include_actions and analysis.suggested_actions:
            report += f"\n💡 建议操作:\n"
            for action in analysis.suggested_actions:
                report += f"  • {action}\n"
        
        return report.strip()


# 全局错误分析器实例
_error_analyzer: Optional[ErrorAnalyzer] = None


def get_error_analyzer() -> ErrorAnalyzer:
    """获取错误分析器实例"""
    global _error_analyzer
    if _error_analyzer is None:
        _error_analyzer = ErrorAnalyzer()
    return _error_analyzer


def analyze_and_log_error(
    error: Exception, 
    context: Optional[Dict[str, Any]] = None,
    operation_name: str = "未知操作"
) -> ErrorAnalysis:
    """
    分析错误并记录详细日志
    
    Args:
        error: 异常对象
        context: 错误上下文
        operation_name: 操作名称
        
    Returns:
        ErrorAnalysis: 错误分析结果
    """
    analyzer = get_error_analyzer()
    analysis = analyzer.analyze_error(error, context)
    
    # 记录分析结果到日志
    report = analyzer.format_analysis_report(analysis, include_actions=True)
    
    if analysis.severity in ['critical', 'high']:
        logger.error(f"❌ {operation_name} 错误分析:\n{report}")
    elif analysis.severity == 'medium':
        logger.warning(f"⚠️ {operation_name} 错误分析:\n{report}")
    else:
        logger.info(f"ℹ️ {operation_name} 错误分析:\n{report}")
    
    return analysis
