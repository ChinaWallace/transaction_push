# -*- coding: utf-8 -*-
"""
清理未使用的导入脚本
Script to clean unused imports from Python files
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class UnusedImportCleaner:
    """未使用导入清理器"""
    
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.cleaned_files: List[str] = []
        self.errors: List[Dict[str, Any]] = []
        
    def find_python_files(self) -> List[Path]:
        """查找所有Python文件"""
        python_files = []
        
        # 排除的目录
        exclude_dirs = {
            '__pycache__', 
            '.git', 
            '.pytest_cache', 
            '.venv', 
            'venv',
            'env',
            'node_modules',
            '.kiro',
            'Kronos-master'  # 排除第三方代码
        }
        
        for root, dirs, files in os.walk(self.project_root):
            # 过滤掉排除的目录
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                if file.endswith('.py'):
                    file_path = Path(root) / file
                    python_files.append(file_path)
        
        return python_files
    
    def clean_file_imports(self, file_path: Path) -> bool:
        """清理单个文件的未使用导入"""
        try:
            logger.info(f"🔍 扫描文件: {file_path}")
            
            # 使用autoflake清理未使用的导入
            cmd = [
                sys.executable, "-m", "autoflake",
                "--remove-all-unused-imports",
                "--remove-unused-variables", 
                "--in-place",
                str(file_path)
            ]
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                encoding='utf-8'
            )
            
            if result.returncode == 0:
                if result.stdout.strip():
                    logger.info(f"✅ 清理完成: {file_path}")
                    self.cleaned_files.append(str(file_path))
                return True
            else:
                error_msg = result.stderr.strip() if result.stderr else "未知错误"
                logger.error(f"❌ 清理失败: {file_path} - {error_msg}")
                self.errors.append({
                    "file": str(file_path),
                    "error": error_msg
                })
                return False
                
        except Exception as e:
            logger.error(f"💥 处理文件异常: {file_path} - {e}")
            self.errors.append({
                "file": str(file_path),
                "error": str(e)
            })
            return False
    
    def verify_syntax(self, file_path: Path) -> bool:
        """验证文件语法是否正确"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                compile(f.read(), str(file_path), 'exec')
            return True
        except SyntaxError as e:
            logger.error(f"❌ 语法错误: {file_path} - {e}")
            return False
        except Exception as e:
            logger.error(f"❌ 验证失败: {file_path} - {e}")
            return False
    
    def clean_all_imports(self) -> Dict[str, Any]:
        """清理所有Python文件的未使用导入"""
        logger.info("🚀 开始清理未使用的导入...")
        
        python_files = self.find_python_files()
        logger.info(f"📊 找到 {len(python_files)} 个Python文件")
        
        success_count = 0
        syntax_errors = []
        
        for file_path in python_files:
            # 先验证语法
            if not self.verify_syntax(file_path):
                syntax_errors.append(str(file_path))
                continue
                
            # 清理导入
            if self.clean_file_imports(file_path):
                success_count += 1
                
                # 清理后再次验证语法
                if not self.verify_syntax(file_path):
                    logger.warning(f"⚠️ 清理后语法错误: {file_path}")
        
        # 生成报告
        report = {
            "total_files": len(python_files),
            "processed_files": success_count,
            "cleaned_files": len(self.cleaned_files),
            "syntax_errors": syntax_errors,
            "processing_errors": self.errors,
            "cleaned_file_list": self.cleaned_files
        }
        
        return report
    
    def print_report(self, report: Dict[str, Any]):
        """打印清理报告"""
        print("\n" + "="*60)
        print("📋 未使用导入清理报告")
        print("="*60)
        print(f"📊 总文件数: {report['total_files']}")
        print(f"✅ 处理成功: {report['processed_files']}")
        print(f"🧹 已清理文件: {report['cleaned_files']}")
        print(f"❌ 语法错误: {len(report['syntax_errors'])}")
        print(f"💥 处理错误: {len(report['processing_errors'])}")
        
        if report['cleaned_file_list']:
            print(f"\n🧹 已清理的文件:")
            for file in report['cleaned_file_list']:
                print(f"  - {file}")
        
        if report['syntax_errors']:
            print(f"\n❌ 语法错误的文件:")
            for file in report['syntax_errors']:
                print(f"  - {file}")
        
        if report['processing_errors']:
            print(f"\n💥 处理错误:")
            for error in report['processing_errors']:
                print(f"  - {error['file']}: {error['error']}")
        
        print("="*60)

def main():
    """主函数"""
    try:
        cleaner = UnusedImportCleaner()
        report = cleaner.clean_all_imports()
        cleaner.print_report(report)
        
        if report['processing_errors']:
            logger.warning("⚠️ 部分文件处理失败，请检查错误信息")
            return 1
        else:
            logger.info("✅ 所有文件处理完成")
            return 0
            
    except KeyboardInterrupt:
        logger.info("🛑 用户中断操作")
        return 1
    except Exception as e:
        logger.error(f"💥 程序异常: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())