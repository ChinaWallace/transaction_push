# -*- coding: utf-8 -*-
"""
通知服务API路由
Notification service API routes
"""

from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any, List

from app.core.logging import get_logger
from app.services.core_notification_service import get_core_notification_service
from app.services.notification_service import NotificationService
from app.schemas.notification import NotificationRequest, NotificationResponse

logger = get_logger(__name__)
router = APIRouter()

# 创建通知服务实例
notification_service = NotificationService()


@router.post("/send",
           summary="发送通知",
           response_model=NotificationResponse)
async def send_notification(request: NotificationRequest):
    """
    发送通知到指定渠道
    
    Args:
        request: 通知请求
    """
    try:
        logger.info(f"Sending notification to {request.channel}")
        
        results = await notification_service.send_notification(
            message=request.message,
            channels=[request.channel],
            priority=request.priority
        )
        
        success = results.get(request.channel, False)
        
        return NotificationResponse(
            success=success,
            data={
                "channel": request.channel,
                "sent": success,
                "results": results
            },
            message=f"Notification {'sent successfully' if success else 'failed'} to {request.channel}"
        )
        
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send notification: {str(e)}")


@router.post("/broadcast",
           summary="广播通知",
           response_model=NotificationResponse)
async def broadcast_notification(
    message: str = Body(..., description="通知消息"),
    priority: str = Body("normal", description="优先级"),
    subject: str = Body(None, description="消息主题")
):
    """
    广播通知到所有启用的渠道
    
    Args:
        message: 通知消息
        priority: 优先级 (low/normal/high/urgent)
        subject: 消息主题
    """
    try:
        logger.info("Broadcasting notification to all channels")
        
        results = await notification_service.send_notification(
            message=message,
            priority=priority,
            subject=subject
        )
        
        success_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        
        return NotificationResponse(
            success=success_count > 0,
            data={
                "results": results,
                "success_count": success_count,
                "total_count": total_count
            },
            message=f"Broadcast completed: {success_count}/{total_count} channels succeeded"
        )
        
    except Exception as e:
        logger.error(f"Failed to broadcast notification: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to broadcast notification: {str(e)}")


@router.post("/test",
           summary="测试通知",
           response_model=NotificationResponse)
async def test_notifications():
    """测试所有通知渠道"""
    try:
        logger.info("Testing all notification channels")
        
        results = await notification_service.test_notifications()
        
        success_channels = [ch for ch, success in results.items() if success]
        failed_channels = [ch for ch, success in results.items() if not success]
        
        return NotificationResponse(
            success=len(success_channels) > 0,
            data={
                "results": results,
                "success_channels": success_channels,
                "failed_channels": failed_channels,
                "total_channels": len(results)
            },
            message=f"Test completed: {len(success_channels)} channels working, {len(failed_channels)} failed"
        )
        
    except Exception as e:
        logger.error(f"Failed to test notifications: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to test notifications: {str(e)}")


@router.get("/channels",
           summary="获取通知渠道",
           response_model=Dict[str, Any])
async def get_notification_channels():
    """获取所有通知渠道的配置状态"""
    try:
        from app.core.config import get_settings
        settings = get_settings()
        
        channels_info = {}
        for channel, config in settings.notification_config.items():
            channels_info[channel] = {
                "enabled": config.get("enabled", False),
                "configured": bool(config.get("webhook_url") or 
                                config.get("bot_token") or 
                                config.get("smtp_host"))
            }
        
        return {
            "success": True,
            "data": {
                "channels": channels_info,
                "total_channels": len(channels_info),
                "enabled_channels": [ch for ch, info in channels_info.items() if info["enabled"]]
            },
            "message": "Notification channels information retrieved successfully"
        }
        
    except Exception as e:
        logger.error(f"Failed to get notification channels: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get notification channels: {str(e)}")


@router.get("/history",
           summary="通知历史",
           response_model=Dict[str, Any])
async def get_notification_history(
    limit: int = 100,
    channel: str = None
):
    """
    获取通知历史记录
    
    Args:
        limit: 返回记录数量限制
        channel: 指定渠道过滤
    """
    try:
        # 这里应该从数据库查询历史记录
        # 暂时返回模拟数据
        
        return {
            "success": True,
            "data": {
                "notifications": [],
                "total": 0,
                "limit": limit,
                "channel_filter": channel
            },
            "message": "Notification history retrieved successfully (feature under development)"
        }
        
    except Exception as e:
        logger.error(f"Failed to get notification history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get notification history: {str(e)}")
