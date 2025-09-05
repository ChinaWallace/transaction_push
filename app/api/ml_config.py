# -*- coding: utf-8 -*-
"""
ML配置管理API
ML Configuration Management API
"""

from typing import Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.ml_weight_config import get_ml_weight_config, MLMode, set_ml_mode
from app.schemas.base import BaseResponse

logger = get_logger(__name__)
router = APIRouter()


class MLModeRequest(BaseModel):
    """ML模式设置请求"""
    mode: str = Field(..., description="ML模式: disabled, training, balanced, enhanced")


class MLConfigResponse(BaseResponse):
    """ML配置响应"""
    current_mode: str = Field(..., description="当前ML模式")
    weights: Dict[str, float] = Field(..., description="当前权重配置")
    influence_level: str = Field(..., description="ML影响程度")


@router.get("/ml-config", response_model=MLConfigResponse)
async def get_ml_config():
    """
    获取当前ML配置
    Get current ML configuration
    """
    try:
        ml_config = get_ml_weight_config()
        
        return MLConfigResponse(
            success=True,
            message="获取ML配置成功",
            current_mode=ml_config.current_mode.value,
            weights=ml_config.get_weights(),
            influence_level=ml_config.get_ml_influence_level()
        )
        
    except Exception as e:
        logger.error(f"❌ 获取ML配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取ML配置失败: {e}")


@router.post("/ml-config/mode", response_model=MLConfigResponse)
async def set_ml_config_mode(request: MLModeRequest):
    """
    设置ML模式
    Set ML mode
    
    Args:
        request: ML模式设置请求
        
    Returns:
        更新后的ML配置
    """
    try:
        # 验证模式
        mode_map = {
            "disabled": MLMode.DISABLED,
            "training": MLMode.TRAINING,
            "balanced": MLMode.BALANCED,
            "enhanced": MLMode.ENHANCED
        }
        
        if request.mode not in mode_map:
            raise HTTPException(
                status_code=400, 
                detail=f"无效的ML模式: {request.mode}，支持的模式: {list(mode_map.keys())}"
            )
        
        # 设置新模式
        new_mode = mode_map[request.mode]
        set_ml_mode(new_mode)
        
        ml_config = get_ml_weight_config()
        
        logger.info(f"✅ ML模式已更新: {new_mode.value}")
        
        return MLConfigResponse(
            success=True,
            message=f"ML模式已设置为: {new_mode.value}",
            current_mode=ml_config.current_mode.value,
            weights=ml_config.get_weights(),
            influence_level=ml_config.get_ml_influence_level()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 设置ML模式失败: {e}")
        raise HTTPException(status_code=500, detail=f"设置ML模式失败: {e}")


@router.get("/ml-config/modes")
async def get_available_ml_modes():
    """
    获取可用的ML模式列表
    Get available ML modes
    """
    try:
        modes = {
            "disabled": {
                "name": "禁用模式",
                "description": "完全禁用ML，仅使用传统分析",
                "ml_weight": 0.0,
                "use_case": "当ML表现不佳时使用"
            },
            "training": {
                "name": "训练模式", 
                "description": "ML跟随传统信号学习，权重很低",
                "ml_weight": 0.1,
                "use_case": "让ML学习和适应市场，推荐当前使用"
            },
            "balanced": {
                "name": "平衡模式",
                "description": "ML与传统分析平衡参与决策",
                "ml_weight": 0.3,
                "use_case": "ML表现稳定后的过渡阶段"
            },
            "enhanced": {
                "name": "增强模式",
                "description": "ML主导决策，传统分析作为辅助",
                "ml_weight": 0.6,
                "use_case": "ML表现优异且稳定时使用"
            }
        }
        
        return {
            "success": True,
            "message": "获取ML模式列表成功",
            "modes": modes,
            "recommendation": "当前推荐使用 training 模式，让ML跟随学习"
        }
        
    except Exception as e:
        logger.error(f"❌ 获取ML模式列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取ML模式列表失败: {e}")


@router.get("/ml-config/status")
async def get_ml_status():
    """
    获取ML系统状态
    Get ML system status
    """
    try:
        ml_config = get_ml_weight_config()
        
        status = {
            "ml_enabled": ml_config.should_use_ml(),
            "current_mode": ml_config.current_mode.value,
            "influence_level": ml_config.get_ml_influence_level(),
            "weights": ml_config.get_weights(),
            "recommendations": []
        }
        
        # 添加建议
        if ml_config.current_mode == MLMode.ENHANCED:
            status["recommendations"].append("⚠️ 当前ML权重较高，建议监控ML表现")
        elif ml_config.current_mode == MLMode.TRAINING:
            status["recommendations"].append("✅ 当前为训练模式，ML正在跟随学习")
        elif ml_config.current_mode == MLMode.DISABLED:
            status["recommendations"].append("ℹ️ ML已禁用，仅使用传统分析")
        
        return {
            "success": True,
            "message": "获取ML状态成功",
            "status": status
        }
        
    except Exception as e:
        logger.error(f"❌ 获取ML状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取ML状态失败: {e}")