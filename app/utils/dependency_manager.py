# -*- coding: utf-8 -*-
"""
依赖管理系统
Dependency Management System
"""

import importlib
import subprocess
import sys
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.core.logging import get_logger
from app.utils.exceptions import TradingToolError

logger = get_logger(__name__)


class DependencyStatus(Enum):
    """依赖状态枚举"""
    AVAILABLE = "available"
    MISSING = "missing"
    VERSION_MISMATCH = "version_mismatch"
    IMPORT_ERROR = "import_error"


@dataclass
class DependencyInfo:
    """依赖信息数据类"""
    name: str
    available: bool
    version: Optional[str] = None
    required_version: Optional[str] = None
    error_message: Optional[str] = None
    install_command: Optional[str] = None
    status: DependencyStatus = DependencyStatus.MISSING
    last_check: Optional[datetime] = None


class DependencyError(TradingToolError):
    """依赖相关异常"""
    
    def __init__(self, message: str, dependency_name: str = None, details: dict = None):
        super().__init__(message)
        self.dependency_name = dependency_name
        self.details = details or {}


class DependencyManager:
    """
    依赖管理器
    Dependency Manager for handling optional and required dependencies
    """
    
    def __init__(self):
        self._dependencies: Dict[str, DependencyInfo] = {}
        self._required_dependencies: List[str] = []
        self._optional_dependencies: List[str] = []
        self._version_requirements: Dict[str, str] = {}
        
        # 预定义的依赖项配置
        self._initialize_dependency_config()
    
    def _initialize_dependency_config(self):
        """初始化依赖配置"""
        # 必需依赖项
        self._required_dependencies = [
            "fastapi",
            "uvicorn",
            "pydantic",
            "aiohttp",
            "pandas",
            "numpy",
            "sqlalchemy",
            "asyncpg"
        ]
        
        # 可选依赖项
        self._optional_dependencies = [
            "torch",
            "transformers",
            "scikit-learn",
            "joblib",
            "websockets",
            "redis",
            "celery",
            "matplotlib",
            "plotly",
            "ta-lib"
        ]
        
        # 版本要求
        self._version_requirements = {
            "fastapi": ">=0.68.0",
            "pandas": ">=1.3.0",
            "numpy": ">=1.21.0",
            "torch": ">=1.9.0",
            "transformers": ">=4.0.0",
            "scikit-learn": ">=1.0.0"
        }
    
    def check_dependency(self, module_name: str, import_path: str = None) -> DependencyInfo:
        """
        检查单个依赖项
        Check a single dependency
        
        Args:
            module_name: 模块名称 / Module name
            import_path: 导入路径（如果与模块名不同）/ Import path if different from module name
            
        Returns:
            DependencyInfo: 依赖信息 / Dependency information
        """
        import_name = import_path or module_name
        
        try:
            # 尝试导入模块
            module = importlib.import_module(import_name)
            
            # 获取版本信息
            version = self._get_module_version(module, module_name)
            
            # 检查版本兼容性
            required_version = self._version_requirements.get(module_name)
            version_compatible = self._check_version_compatibility(version, required_version)
            
            status = DependencyStatus.AVAILABLE
            if required_version and not version_compatible:
                status = DependencyStatus.VERSION_MISMATCH
            
            dep_info = DependencyInfo(
                name=module_name,
                available=True,
                version=version,
                required_version=required_version,
                status=status,
                last_check=datetime.now()
            )
            
            if status == DependencyStatus.VERSION_MISMATCH:
                dep_info.error_message = f"版本不兼容: 当前 {version}, 需要 {required_version}"
                dep_info.install_command = f"pip install {module_name}{required_version}"
            
            logger.debug(f"🔍 依赖检查成功: {module_name} v{version}")
            
        except ImportError as e:
            dep_info = DependencyInfo(
                name=module_name,
                available=False,
                error_message=str(e),
                install_command=f"pip install {module_name}",
                status=DependencyStatus.MISSING,
                last_check=datetime.now()
            )
            logger.warning(f"⚠️ 依赖缺失: {module_name} - {e}")
            
        except Exception as e:
            dep_info = DependencyInfo(
                name=module_name,
                available=False,
                error_message=f"导入错误: {str(e)}",
                status=DependencyStatus.IMPORT_ERROR,
                last_check=datetime.now()
            )
            logger.error(f"❌ 依赖检查失败: {module_name} - {e}")
        
        self._dependencies[module_name] = dep_info
        return dep_info
    
    def _get_module_version(self, module: Any, module_name: str) -> Optional[str]:
        """获取模块版本"""
        version_attrs = ['__version__', 'version', 'VERSION']
        
        for attr in version_attrs:
            if hasattr(module, attr):
                version = getattr(module, attr)
                if isinstance(version, str):
                    return version
                elif hasattr(version, '__str__'):
                    return str(version)
        
        # 尝试通过包管理器获取版本
        try:
            import pkg_resources
            return pkg_resources.get_distribution(module_name).version
        except:
            pass
        
        return None
    
    def _check_version_compatibility(self, current_version: str, required_version: str) -> bool:
        """检查版本兼容性"""
        if not current_version or not required_version:
            return True
        
        try:
            from packaging import version
            
            # 解析版本要求
            if required_version.startswith('>='):
                min_version = required_version[2:].strip()
                return version.parse(current_version) >= version.parse(min_version)
            elif required_version.startswith('=='):
                exact_version = required_version[2:].strip()
                return version.parse(current_version) == version.parse(exact_version)
            elif required_version.startswith('>'):
                min_version = required_version[1:].strip()
                return version.parse(current_version) > version.parse(min_version)
            else:
                # 默认为精确匹配
                return version.parse(current_version) == version.parse(required_version)
                
        except Exception as e:
            logger.warning(f"⚠️ 版本比较失败: {e}")
            return True  # 如果无法比较，假设兼容
    
    def get_missing_dependencies(self) -> List[DependencyInfo]:
        """
        获取缺失的依赖项
        Get missing dependencies
        
        Returns:
            List[DependencyInfo]: 缺失的依赖项列表 / List of missing dependencies
        """
        missing = []
        
        for dep_name in self._required_dependencies + self._optional_dependencies:
            if dep_name not in self._dependencies:
                self.check_dependency(dep_name)
            
            dep_info = self._dependencies[dep_name]
            if not dep_info.available or dep_info.status != DependencyStatus.AVAILABLE:
                missing.append(dep_info)
        
        return missing
    
    def get_dependency_status(self, module_name: str) -> Optional[DependencyInfo]:
        """
        获取依赖状态
        Get dependency status
        
        Args:
            module_name: 模块名称 / Module name
            
        Returns:
            Optional[DependencyInfo]: 依赖信息 / Dependency information
        """
        if module_name not in self._dependencies:
            return self.check_dependency(module_name)
        
        return self._dependencies[module_name]
    
    def install_dependency(self, module_name: str, version: str = None) -> bool:
        """
        自动安装依赖项
        Automatically install dependency
        
        Args:
            module_name: 模块名称 / Module name
            version: 版本要求 / Version requirement
            
        Returns:
            bool: 安装是否成功 / Whether installation was successful
        """
        try:
            install_cmd = [sys.executable, "-m", "pip", "install"]
            
            if version:
                install_cmd.append(f"{module_name}{version}")
            else:
                required_version = self._version_requirements.get(module_name)
                if required_version:
                    install_cmd.append(f"{module_name}{required_version}")
                else:
                    install_cmd.append(module_name)
            
            logger.info(f"🔧 正在安装依赖: {' '.join(install_cmd[3:])}")
            
            result = subprocess.run(
                install_cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )
            
            if result.returncode == 0:
                logger.info(f"✅ 依赖安装成功: {module_name}")
                # 重新检查依赖状态
                self.check_dependency(module_name)
                return True
            else:
                logger.error(f"❌ 依赖安装失败: {module_name}")
                logger.error(f"错误输出: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"❌ 依赖安装超时: {module_name}")
            return False
        except Exception as e:
            logger.error(f"❌ 依赖安装异常: {module_name} - {e}")
            return False
    
    def validate_all_dependencies(self) -> Dict[str, Any]:
        """
        验证所有依赖项
        Validate all dependencies
        
        Returns:
            Dict[str, Any]: 验证报告 / Validation report
        """
        logger.info("🔍 开始依赖验证...")
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "required_dependencies": {},
            "optional_dependencies": {},
            "missing_required": [],
            "missing_optional": [],
            "version_mismatches": [],
            "all_available": True
        }
        
        # 检查必需依赖项
        for dep_name in self._required_dependencies:
            dep_info = self.check_dependency(dep_name)
            report["required_dependencies"][dep_name] = {
                "available": dep_info.available,
                "version": dep_info.version,
                "status": dep_info.status.value
            }
            
            if not dep_info.available:
                report["missing_required"].append(dep_name)
                report["all_available"] = False
            elif dep_info.status == DependencyStatus.VERSION_MISMATCH:
                report["version_mismatches"].append({
                    "name": dep_name,
                    "current": dep_info.version,
                    "required": dep_info.required_version
                })
        
        # 检查可选依赖项
        for dep_name in self._optional_dependencies:
            dep_info = self.check_dependency(dep_name)
            report["optional_dependencies"][dep_name] = {
                "available": dep_info.available,
                "version": dep_info.version,
                "status": dep_info.status.value
            }
            
            if not dep_info.available:
                report["missing_optional"].append(dep_name)
        
        # 记录报告摘要
        if report["all_available"]:
            logger.info("✅ 所有必需依赖项都可用")
        else:
            logger.warning(f"⚠️ 缺失必需依赖项: {report['missing_required']}")
        
        if report["missing_optional"]:
            logger.info(f"ℹ️ 缺失可选依赖项: {report['missing_optional']}")
        
        return report
    
    def get_installation_guide(self) -> str:
        """
        生成安装指南
        Generate installation guide
        
        Returns:
            str: 安装指南文本 / Installation guide text
        """
        missing_deps = self.get_missing_dependencies()
        
        if not missing_deps:
            return "✅ 所有依赖项都已安装"
        
        guide = ["📦 依赖安装指南", "=" * 50, ""]
        
        required_missing = [dep for dep in missing_deps if dep.name in self._required_dependencies]
        optional_missing = [dep for dep in missing_deps if dep.name in self._optional_dependencies]
        
        if required_missing:
            guide.extend([
                "🚨 必需依赖项（必须安装）:",
                ""
            ])
            for dep in required_missing:
                guide.append(f"  • {dep.name}: {dep.install_command}")
                if dep.error_message:
                    guide.append(f"    错误: {dep.error_message}")
            guide.append("")
        
        if optional_missing:
            guide.extend([
                "⚡ 可选依赖项（建议安装）:",
                ""
            ])
            for dep in optional_missing:
                guide.append(f"  • {dep.name}: {dep.install_command}")
                if dep.error_message:
                    guide.append(f"    说明: {dep.error_message}")
            guide.append("")
        
        guide.extend([
            "💡 批量安装命令:",
            ""
        ])
        
        if required_missing:
            required_packages = " ".join([dep.name for dep in required_missing])
            guide.append(f"pip install {required_packages}")
        
        if optional_missing:
            optional_packages = " ".join([dep.name for dep in optional_missing])
            guide.append(f"pip install {optional_packages}")
        
        return "\n".join(guide)
    
    def is_dependency_available(self, module_name: str) -> bool:
        """
        检查依赖是否可用
        Check if dependency is available
        
        Args:
            module_name: 模块名称 / Module name
            
        Returns:
            bool: 是否可用 / Whether available
        """
        dep_info = self.get_dependency_status(module_name)
        return dep_info.available if dep_info else False
    
    def register_custom_dependency(self, name: str, import_path: str = None, 
                                 required: bool = False, version_requirement: str = None):
        """
        注册自定义依赖项
        Register custom dependency
        
        Args:
            name: 依赖名称 / Dependency name
            import_path: 导入路径 / Import path
            required: 是否为必需依赖 / Whether required
            version_requirement: 版本要求 / Version requirement
        """
        if required:
            if name not in self._required_dependencies:
                self._required_dependencies.append(name)
        else:
            if name not in self._optional_dependencies:
                self._optional_dependencies.append(name)
        
        if version_requirement:
            self._version_requirements[name] = version_requirement
        
        # 立即检查依赖状态
        self.check_dependency(name, import_path)
        
        logger.info(f"📝 注册自定义依赖: {name} ({'必需' if required else '可选'})")


# 全局依赖管理器实例
dependency_manager = DependencyManager()