# -*- coding: utf-8 -*-
"""
数据服务模块
Data Services Module

提供数据相关的服务，包括缓存、数据提供等功能
Provides data-related services including cache, data providers, etc.
"""

from .cache_service import (
    CacheService,
    get_cache_service,
    cache_get,
    cache_set,
    cache_delete,
    cache_clear
)

from .data_provider_service import (
    DataProviderService,
    get_data_provider_service
)

__all__ = [
    "CacheService",
    "get_cache_service", 
    "cache_get",
    "cache_set",
    "cache_delete",
    "cache_clear",
    "DataProviderService",
    "get_data_provider_service"
]