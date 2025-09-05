# -*- coding: utf-8 -*-
"""
批量数据处理优化器
Batch data processing optimizer
"""

import asyncio
from typing import Dict, Any, List, Optional, Callable, TypeVar, Generic
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from dataclasses import dataclass
import time

from app.core.logging import get_logger
from app.models.unified_exchange_data import (
    UnifiedInstrument, UnifiedTicker, UnifiedFundingRate, UnifiedPosition
)

logger = get_logger(__name__)

T = TypeVar('T')
R = TypeVar('R')


@dataclass
class BatchConfig:
    """批处理配置"""
    batch_size: int = 100
    max_workers: int = 4
    use_process_pool: bool = False
    timeout: float = 30.0
    enable_parallel: bool = True


class BatchProcessor(Generic[T, R]):
    """
    批量数据处理器
    Batch data processor for optimizing large dataset transformations
    """
    
    def __init__(self, config: BatchConfig = None):
        """
        初始化批处理器
        
        Args:
            config: 批处理配置
        """
        self.config = config or BatchConfig()
        self._thread_pool = None
        self._process_pool = None
        logger.info(f"🔧 批处理器初始化完成: batch_size={self.config.batch_size}, "
                   f"max_workers={self.config.max_workers}")
    
    async def process_batch(
        self, 
        data_list: List[T], 
        processor_func: Callable[[T], R],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[R]:
        """
        批量处理数据
        Process data in batches
        
        Args:
            data_list: 待处理的数据列表
            processor_func: 处理函数
            progress_callback: 进度回调函数
            
        Returns:
            List[R]: 处理结果列表
        """
        if not data_list:
            return []
        
        total_items = len(data_list)
        logger.info(f"🚀 开始批量处理 {total_items} 个数据项")
        
        start_time = time.time()
        results = []
        
        try:
            if self.config.enable_parallel and total_items > self.config.batch_size:
                # 并行批处理
                results = await self._parallel_batch_process(
                    data_list, processor_func, progress_callback
                )
            else:
                # 串行批处理
                results = await self._serial_batch_process(
                    data_list, processor_func, progress_callback
                )
            
            duration = time.time() - start_time
            throughput = total_items / duration if duration > 0 else 0
            
            logger.info(f"✅ 批量处理完成: {len(results)}/{total_items} 项, "
                       f"耗时 {duration:.3f}秒, 吞吐量 {throughput:.1f} items/sec")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ 批量处理失败: {e}")
            raise
    
    async def _parallel_batch_process(
        self,
        data_list: List[T],
        processor_func: Callable[[T], R],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[R]:
        """并行批处理"""
        total_items = len(data_list)
        batch_size = self.config.batch_size
        batches = [
            data_list[i:i + batch_size] 
            for i in range(0, total_items, batch_size)
        ]
        
        logger.debug(f"🔄 创建 {len(batches)} 个批次进行并行处理")
        
        # 创建任务
        tasks = []
        for i, batch in enumerate(batches):
            task = self._process_single_batch(
                batch, processor_func, i, len(batches)
            )
            tasks.append(task)
        
        # 并行执行所有批次
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 合并结果并处理异常
        results = []
        processed_count = 0
        
        for i, batch_result in enumerate(batch_results):
            if isinstance(batch_result, Exception):
                logger.error(f"❌ 批次 {i} 处理失败: {batch_result}")
                # 对失败的批次进行串行重试
                try:
                    retry_result = await self._process_single_batch(
                        batches[i], processor_func, i, len(batches), retry=True
                    )
                    results.extend(retry_result)
                    processed_count += len(retry_result)
                except Exception as retry_error:
                    logger.error(f"❌ 批次 {i} 重试失败: {retry_error}")
                    continue
            else:
                results.extend(batch_result)
                processed_count += len(batch_result)
            
            # 调用进度回调
            if progress_callback:
                progress_callback(processed_count, total_items)
        
        return results
    
    async def _serial_batch_process(
        self,
        data_list: List[T],
        processor_func: Callable[[T], R],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[R]:
        """串行批处理"""
        total_items = len(data_list)
        batch_size = self.config.batch_size
        results = []
        processed_count = 0
        
        for i in range(0, total_items, batch_size):
            batch = data_list[i:i + batch_size]
            batch_index = i // batch_size
            total_batches = (total_items + batch_size - 1) // batch_size
            
            try:
                batch_result = await self._process_single_batch(
                    batch, processor_func, batch_index, total_batches
                )
                results.extend(batch_result)
                processed_count += len(batch_result)
                
                # 调用进度回调
                if progress_callback:
                    progress_callback(processed_count, total_items)
                    
            except Exception as e:
                logger.error(f"❌ 批次 {batch_index} 处理失败: {e}")
                continue
        
        return results
    
    async def _process_single_batch(
        self,
        batch: List[T],
        processor_func: Callable[[T], R],
        batch_index: int,
        total_batches: int,
        retry: bool = False
    ) -> List[R]:
        """处理单个批次"""
        batch_size = len(batch)
        retry_suffix = " (重试)" if retry else ""
        
        logger.debug(f"🔄 处理批次 {batch_index + 1}/{total_batches}{retry_suffix}: {batch_size} 项")
        
        start_time = time.time()
        results = []
        
        try:
            if self.config.use_process_pool and batch_size > 10:
                # 使用进程池处理CPU密集型任务
                results = await self._process_with_process_pool(batch, processor_func)
            elif batch_size > 5:
                # 使用线程池处理I/O密集型任务
                results = await self._process_with_thread_pool(batch, processor_func)
            else:
                # 直接串行处理小批次
                for item in batch:
                    try:
                        result = processor_func(item)
                        results.append(result)
                    except Exception as e:
                        logger.warning(f"⚠️ 处理单项数据失败: {e}")
                        continue
            
            duration = time.time() - start_time
            throughput = batch_size / duration if duration > 0 else 0
            
            logger.debug(f"✅ 批次 {batch_index + 1}{retry_suffix} 完成: "
                        f"{len(results)}/{batch_size} 项, "
                        f"耗时 {duration:.3f}秒, 吞吐量 {throughput:.1f} items/sec")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ 批次 {batch_index + 1}{retry_suffix} 处理异常: {e}")
            raise
    
    async def _process_with_thread_pool(
        self, 
        batch: List[T], 
        processor_func: Callable[[T], R]
    ) -> List[R]:
        """使用线程池处理批次"""
        if not self._thread_pool:
            self._thread_pool = ThreadPoolExecutor(max_workers=self.config.max_workers)
        
        loop = asyncio.get_event_loop()
        
        # 创建任务
        tasks = [
            loop.run_in_executor(self._thread_pool, processor_func, item)
            for item in batch
        ]
        
        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 过滤异常结果
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"⚠️ 线程池处理项目 {i} 失败: {result}")
            else:
                valid_results.append(result)
        
        return valid_results
    
    async def _process_with_process_pool(
        self, 
        batch: List[T], 
        processor_func: Callable[[T], R]
    ) -> List[R]:
        """使用进程池处理批次"""
        if not self._process_pool:
            self._process_pool = ProcessPoolExecutor(max_workers=self.config.max_workers)
        
        loop = asyncio.get_event_loop()
        
        try:
            # 创建任务
            tasks = [
                loop.run_in_executor(self._process_pool, processor_func, item)
                for item in batch
            ]
            
            # 等待所有任务完成
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.config.timeout
            )
            
            # 过滤异常结果
            valid_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"⚠️ 进程池处理项目 {i} 失败: {result}")
                else:
                    valid_results.append(result)
            
            return valid_results
            
        except asyncio.TimeoutError:
            logger.error(f"❌ 进程池处理超时 ({self.config.timeout}秒)")
            raise
    
    def optimize_batch_size(self, data_sample: List[T], processor_func: Callable[[T], R]) -> int:
        """
        优化批次大小
        Optimize batch size based on performance testing
        
        Args:
            data_sample: 数据样本
            processor_func: 处理函数
            
        Returns:
            int: 优化后的批次大小
        """
        if len(data_sample) < 10:
            return len(data_sample)
        
        logger.info("🔍 开始批次大小优化测试")
        
        # 测试不同的批次大小
        test_sizes = [10, 25, 50, 100, 200]
        test_sample = data_sample[:min(100, len(data_sample))]
        best_size = self.config.batch_size
        best_throughput = 0
        
        for size in test_sizes:
            if size > len(test_sample):
                continue
            
            try:
                start_time = time.time()
                test_batch = test_sample[:size]
                
                # 测试处理性能
                for item in test_batch:
                    processor_func(item)
                
                duration = time.time() - start_time
                throughput = size / duration if duration > 0 else 0
                
                logger.debug(f"📊 批次大小 {size}: 吞吐量 {throughput:.1f} items/sec")
                
                if throughput > best_throughput:
                    best_throughput = throughput
                    best_size = size
                    
            except Exception as e:
                logger.warning(f"⚠️ 批次大小 {size} 测试失败: {e}")
                continue
        
        logger.info(f"🎯 优化后的批次大小: {best_size} (吞吐量: {best_throughput:.1f} items/sec)")
        return best_size
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.cleanup()
    
    async def cleanup(self):
        """清理资源"""
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)
            self._thread_pool = None
        
        if self._process_pool:
            self._process_pool.shutdown(wait=True)
            self._process_pool = None
        
        logger.debug("🧹 批处理器资源清理完成")


class AdapterBatchProcessor:
    """
    适配器专用批处理器
    Specialized batch processor for adapters
    """
    
    def __init__(self):
        self.instrument_processor = BatchProcessor[Dict[str, Any], UnifiedInstrument](
            BatchConfig(batch_size=200, max_workers=4, enable_parallel=True)
        )
        self.ticker_processor = BatchProcessor[Dict[str, Any], UnifiedTicker](
            BatchConfig(batch_size=100, max_workers=3, enable_parallel=True)
        )
        self.funding_rate_processor = BatchProcessor[Dict[str, Any], UnifiedFundingRate](
            BatchConfig(batch_size=50, max_workers=2, enable_parallel=True)
        )
        self.position_processor = BatchProcessor[Dict[str, Any], UnifiedPosition](
            BatchConfig(batch_size=50, max_workers=2, enable_parallel=True)
        )
        
        logger.info("🔧 适配器批处理器初始化完成")
    
    async def batch_adapt_instruments(
        self, 
        raw_data: List[Dict[str, Any]], 
        adapter_func: Callable[[Dict[str, Any]], UnifiedInstrument],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[UnifiedInstrument]:
        """批量适配交易对数据"""
        return await self.instrument_processor.process_batch(
            raw_data, adapter_func, progress_callback
        )
    
    async def batch_adapt_tickers(
        self, 
        raw_data: List[Dict[str, Any]], 
        adapter_func: Callable[[Dict[str, Any]], UnifiedTicker],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[UnifiedTicker]:
        """批量适配ticker数据"""
        return await self.ticker_processor.process_batch(
            raw_data, adapter_func, progress_callback
        )
    
    async def batch_adapt_funding_rates(
        self, 
        raw_data: List[Dict[str, Any]], 
        adapter_func: Callable[[Dict[str, Any]], UnifiedFundingRate],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[UnifiedFundingRate]:
        """批量适配资金费率数据"""
        return await self.funding_rate_processor.process_batch(
            raw_data, adapter_func, progress_callback
        )
    
    async def batch_adapt_positions(
        self, 
        raw_data: List[Dict[str, Any]], 
        adapter_func: Callable[[Dict[str, Any]], UnifiedPosition],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[UnifiedPosition]:
        """批量适配持仓数据"""
        return await self.position_processor.process_batch(
            raw_data, adapter_func, progress_callback
        )
    
    async def cleanup(self):
        """清理所有处理器资源"""
        await asyncio.gather(
            self.instrument_processor.cleanup(),
            self.ticker_processor.cleanup(),
            self.funding_rate_processor.cleanup(),
            self.position_processor.cleanup(),
            return_exceptions=True
        )
        logger.info("🧹 适配器批处理器清理完成")


# 全局批处理器实例
adapter_batch_processor = AdapterBatchProcessor()