# -*- coding: utf-8 -*-
"""
数据适配验证脚本
Data adaptation validation script

验证币安数据适配的正确性，实现自动化的数据格式检查，创建适配前后数据对比工具
"""

import asyncio
import json
import sys
from typing import Dict, Any, List
from datetime import datetime
from pathlib import Path
import argparse

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))

from app.core.logging import get_logger
from app.services.exchanges.adapters.adapter_factory import AdapterFactory
from app.services.exchanges.adapters.adapter_diagnostics import AdapterDiagnostics
from app.models.unified_exchange_data import (
    DataAdaptationError, FieldMappingError
)

logger = get_logger(__name__)


class DataAdaptationValidator:
    """
    数据适配验证器
    Data adaptation validator
    
    验证币安数据适配的正确性和完整性
    """
    
    def __init__(self):
        self.validation_results: Dict[str, Any] = {}
        self.test_data_samples: Dict[str, List[Dict[str, Any]]] = {}
        self.comparison_results: Dict[str, Any] = {}
    
    async def run_comprehensive_validation(self, exchange: str = "binance") -> Dict[str, Any]:
        """
        运行综合验证
        Run comprehensive validation
        
        Args:
            exchange: 要验证的交易所名称
            
        Returns:
            Dict: 验证结果
        """
        logger.info(f"🔍 开始 {exchange} 数据适配综合验证")
        
        validation_result = {
            "timestamp": datetime.now().isoformat(),
            "exchange": exchange,
            "overall_status": "unknown",
            "validations": {},
            "summary": {
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 0,
                "error_tests": 0
            },
            "recommendations": []
        }
        
        try:
            # 1. 适配器基础验证
            logger.info("🔧 执行适配器基础验证")
            adapter_validation = await self._validate_adapter_basics(exchange)
            validation_result["validations"]["adapter_basics"] = adapter_validation
            
            # 2. 数据格式验证
            logger.info("📊 执行数据格式验证")
            format_validation = await self._validate_data_formats(exchange)
            validation_result["validations"]["data_formats"] = format_validation
            
            # 3. 字段映射验证
            logger.info("🗂️ 执行字段映射验证")
            mapping_validation = await self._validate_field_mappings(exchange)
            validation_result["validations"]["field_mappings"] = mapping_validation
            
            # 4. 数据完整性验证
            logger.info("✅ 执行数据完整性验证")
            integrity_validation = await self._validate_data_integrity(exchange)
            validation_result["validations"]["data_integrity"] = integrity_validation
            
            # 5. 性能验证
            logger.info("⚡ 执行性能验证")
            performance_validation = await self._validate_performance(exchange)
            validation_result["validations"]["performance"] = performance_validation
            
            # 6. 错误处理验证
            logger.info("🛡️ 执行错误处理验证")
            error_handling_validation = await self._validate_error_handling(exchange)
            validation_result["validations"]["error_handling"] = error_handling_validation
            
            # 统计结果
            self._calculate_summary(validation_result)
            
            # 生成建议
            validation_result["recommendations"] = self._generate_recommendations(validation_result)
            
            logger.info(f"✅ {exchange} 数据适配综合验证完成")
            
        except Exception as e:
            logger.error(f"❌ 验证过程中发生错误: {e}")
            validation_result["overall_status"] = "error"
            validation_result["error"] = str(e)
        
        return validation_result
    
    async def _validate_adapter_basics(self, exchange: str) -> Dict[str, Any]:
        """验证适配器基础功能"""
        result = {
            "status": "unknown",
            "tests": {},
            "errors": []
        }
        
        try:
            # 测试适配器实例化
            adapter = AdapterFactory.get_adapter(exchange)
            result["tests"]["instantiation"] = {"status": "passed", "message": "适配器实例化成功"}
            
            # 测试适配器信息获取
            adapter_info = adapter.get_adapter_info()
            result["tests"]["info_retrieval"] = {
                "status": "passed", 
                "message": "适配器信息获取成功",
                "data": adapter_info
            }
            
            # 验证支持的数据类型
            expected_types = ["instruments", "ticker", "funding_rate", "position"]
            supported_types = adapter_info.get("supported_data_types", [])
            missing_types = [t for t in expected_types if t not in supported_types]
            
            if missing_types:
                result["tests"]["supported_types"] = {
                    "status": "failed",
                    "message": f"缺少支持的数据类型: {missing_types}"
                }
                result["errors"].append(f"缺少支持的数据类型: {missing_types}")
            else:
                result["tests"]["supported_types"] = {
                    "status": "passed",
                    "message": "所有必需的数据类型都支持"
                }
            
            # 确定整体状态
            all_passed = all(test.get("status") == "passed" for test in result["tests"].values())
            result["status"] = "passed" if all_passed else "failed"
            
        except Exception as e:
            result["status"] = "error"
            result["errors"].append(str(e))
            logger.error(f"❌ 适配器基础验证失败: {e}")
        
        return result
    
    async def _validate_data_formats(self, exchange: str) -> Dict[str, Any]:
        """验证数据格式"""
        result = {
            "status": "unknown",
            "tests": {},
            "errors": []
        }
        
        try:
            adapter = AdapterFactory.get_adapter(exchange)
            
            # 测试交易对数据格式
            instruments_test = await self._test_instruments_format(adapter)
            result["tests"]["instruments_format"] = instruments_test
            
            # 测试ticker数据格式
            ticker_test = await self._test_ticker_format(adapter)
            result["tests"]["ticker_format"] = ticker_test
            
            # 测试资金费率数据格式
            funding_rate_test = await self._test_funding_rate_format(adapter)
            result["tests"]["funding_rate_format"] = funding_rate_test
            
            # 测试持仓数据格式
            position_test = await self._test_position_format(adapter)
            result["tests"]["position_format"] = position_test
            
            # 确定整体状态
            all_passed = all(test.get("status") == "passed" for test in result["tests"].values())
            result["status"] = "passed" if all_passed else "failed"
            
        except Exception as e:
            result["status"] = "error"
            result["errors"].append(str(e))
            logger.error(f"❌ 数据格式验证失败: {e}")
        
        return result
    
    async def _test_instruments_format(self, adapter) -> Dict[str, Any]:
        """测试交易对数据格式"""
        try:
            # 模拟币安交易对数据
            sample_data = [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "contractType": "PERPETUAL",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                        {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"}
                    ]
                }
            ]
            
            # 执行适配
            adapted_data = adapter.adapt_instruments(sample_data)
            
            if not adapted_data:
                return {"status": "failed", "message": "适配结果为空"}
            
            # 验证适配结果格式
            instrument = adapted_data[0]
            
            # 检查必需字段
            required_fields = ["instId", "instType", "baseCcy", "quoteCcy", "state"]
            missing_fields = [field for field in required_fields if not hasattr(instrument, field)]
            
            if missing_fields:
                return {
                    "status": "failed", 
                    "message": f"缺少必需字段: {missing_fields}"
                }
            
            # 验证字段值
            if instrument.instId != "BTC-USDT-SWAP":
                return {
                    "status": "failed",
                    "message": f"交易对符号格式错误: {instrument.instId}"
                }
            
            return {
                "status": "passed",
                "message": "交易对数据格式验证通过",
                "sample_result": {
                    "instId": instrument.instId,
                    "instType": instrument.instType,
                    "baseCcy": instrument.baseCcy,
                    "quoteCcy": instrument.quoteCcy
                }
            }
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def _test_ticker_format(self, adapter) -> Dict[str, Any]:
        """测试ticker数据格式"""
        try:
            # 模拟币安ticker数据
            sample_data = {
                "symbol": "BTCUSDT",
                "lastPrice": "50000.00",
                "bidPrice": "49999.00",
                "askPrice": "50001.00",
                "bidQty": "1.5",
                "askQty": "2.0",
                "openPrice": "49500.00",
                "highPrice": "50500.00",
                "lowPrice": "49000.00",
                "volume": "1000.00",
                "quoteVolume": "50000000.00",
                "closeTime": 1640995200000
            }
            
            # 执行适配
            adapted_data = adapter.adapt_ticker(sample_data)
            
            # 检查必需字段
            required_fields = ["instId", "last", "askPx", "bidPx"]
            missing_fields = [field for field in required_fields if not hasattr(adapted_data, field)]
            
            if missing_fields:
                return {
                    "status": "failed",
                    "message": f"缺少必需字段: {missing_fields}"
                }
            
            # 验证字段值
            if adapted_data.instId != "BTC-USDT-SWAP":
                return {
                    "status": "failed",
                    "message": f"交易对符号格式错误: {adapted_data.instId}"
                }
            
            return {
                "status": "passed",
                "message": "ticker数据格式验证通过",
                "sample_result": {
                    "instId": adapted_data.instId,
                    "last": adapted_data.last,
                    "askPx": adapted_data.askPx,
                    "bidPx": adapted_data.bidPx
                }
            }
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def _test_funding_rate_format(self, adapter) -> Dict[str, Any]:
        """测试资金费率数据格式"""
        try:
            # 模拟币安资金费率数据
            sample_data = {
                "symbol": "BTCUSDT",
                "lastFundingRate": "0.0001",
                "fundingTime": 1640995200000,
                "nextFundingTime": 1641024000000
            }
            
            # 执行适配
            adapted_data = adapter.adapt_funding_rate(sample_data)
            
            # 检查必需字段
            required_fields = ["instId", "fundingRate"]
            missing_fields = [field for field in required_fields if not hasattr(adapted_data, field)]
            
            if missing_fields:
                return {
                    "status": "failed",
                    "message": f"缺少必需字段: {missing_fields}"
                }
            
            return {
                "status": "passed",
                "message": "资金费率数据格式验证通过",
                "sample_result": {
                    "instId": adapted_data.instId,
                    "fundingRate": adapted_data.fundingRate
                }
            }
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def _test_position_format(self, adapter) -> Dict[str, Any]:
        """测试持仓数据格式"""
        try:
            # 模拟币安持仓数据
            sample_data = {
                "symbol": "BTCUSDT",
                "positionAmt": "0.001",
                "entryPrice": "50000.0",
                "markPrice": "50100.0",
                "unRealizedProfit": "0.1",
                "positionSide": "LONG"
            }
            
            # 执行适配
            adapted_data = adapter.adapt_position(sample_data)
            
            # 检查必需字段
            required_fields = ["instId", "posSide", "pos"]
            missing_fields = [field for field in required_fields if not hasattr(adapted_data, field)]
            
            if missing_fields:
                return {
                    "status": "failed",
                    "message": f"缺少必需字段: {missing_fields}"
                }
            
            return {
                "status": "passed",
                "message": "持仓数据格式验证通过",
                "sample_result": {
                    "instId": adapted_data.instId,
                    "posSide": adapted_data.posSide,
                    "pos": adapted_data.pos
                }
            }
            
        except Exception as e:
            return {"status": "error", "message": str(e)}  
  
    async def _validate_field_mappings(self, exchange: str) -> Dict[str, Any]:
        """验证字段映射"""
        result = {
            "status": "unknown",
            "tests": {},
            "errors": []
        }
        
        try:
            adapter = AdapterFactory.get_adapter(exchange)
            
            # 测试字段映射的准确性
            mapping_tests = [
                self._test_symbol_mapping(adapter),
                self._test_price_mapping(adapter),
                self._test_quantity_mapping(adapter),
                self._test_timestamp_mapping(adapter)
            ]
            
            for i, test_result in enumerate(mapping_tests):
                test_name = ["symbol_mapping", "price_mapping", "quantity_mapping", "timestamp_mapping"][i]
                result["tests"][test_name] = test_result
            
            # 确定整体状态
            all_passed = all(test.get("status") == "passed" for test in result["tests"].values())
            result["status"] = "passed" if all_passed else "failed"
            
        except Exception as e:
            result["status"] = "error"
            result["errors"].append(str(e))
            logger.error(f"❌ 字段映射验证失败: {e}")
        
        return result
    
    def _test_symbol_mapping(self, adapter) -> Dict[str, Any]:
        """测试交易对符号映射"""
        try:
            test_cases = [
                ("BTCUSDT", "BTC-USDT-SWAP"),
                ("ETHUSDT", "ETH-USDT-SWAP"),
                ("ADAUSDT", "ADA-USDT-SWAP")
            ]
            
            for raw_symbol, expected_symbol in test_cases:
                normalized = adapter._normalize_symbol(raw_symbol, "binance")
                if normalized != expected_symbol:
                    return {
                        "status": "failed",
                        "message": f"符号映射错误: {raw_symbol} -> {normalized}, 期望: {expected_symbol}"
                    }
            
            return {"status": "passed", "message": "交易对符号映射正确"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _test_price_mapping(self, adapter) -> Dict[str, Any]:
        """测试价格字段映射"""
        try:
            test_data = {
                "lastPrice": "50000.123",
                "bidPrice": "49999.456",
                "askPrice": "50001.789"
            }
            
            # 测试价格转换
            last_price = adapter._safe_get_float(test_data, "lastPrice")
            bid_price = adapter._safe_get_float(test_data, "bidPrice")
            ask_price = adapter._safe_get_float(test_data, "askPrice")
            
            if last_price != "50000.123" or bid_price != "49999.456" or ask_price != "50001.789":
                return {
                    "status": "failed",
                    "message": "价格字段映射不正确"
                }
            
            return {"status": "passed", "message": "价格字段映射正确"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _test_quantity_mapping(self, adapter) -> Dict[str, Any]:
        """测试数量字段映射"""
        try:
            test_data = {
                "volume": "1000.5",
                "bidQty": "2.5",
                "askQty": "3.7"
            }
            
            # 测试数量转换
            volume = adapter._safe_get_float(test_data, "volume")
            bid_qty = adapter._safe_get_float(test_data, "bidQty")
            ask_qty = adapter._safe_get_float(test_data, "askQty")
            
            if volume != "1000.5" or bid_qty != "2.5" or ask_qty != "3.7":
                return {
                    "status": "failed",
                    "message": "数量字段映射不正确"
                }
            
            return {"status": "passed", "message": "数量字段映射正确"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _test_timestamp_mapping(self, adapter) -> Dict[str, Any]:
        """测试时间戳字段映射"""
        try:
            test_cases = [
                (1640995200000, "1640995200000"),  # 毫秒时间戳
                (1640995200, "1640995200000"),     # 秒时间戳
                ("1640995200000", "1640995200000") # 字符串时间戳
            ]
            
            for input_ts, expected_ts in test_cases:
                result_ts = adapter._safe_get_timestamp({"timestamp": input_ts}, "timestamp")
                if result_ts != expected_ts:
                    return {
                        "status": "failed",
                        "message": f"时间戳映射错误: {input_ts} -> {result_ts}, 期望: {expected_ts}"
                    }
            
            return {"status": "passed", "message": "时间戳字段映射正确"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def _validate_data_integrity(self, exchange: str) -> Dict[str, Any]:
        """验证数据完整性"""
        result = {
            "status": "unknown",
            "tests": {},
            "errors": []
        }
        
        try:
            adapter = AdapterFactory.get_adapter(exchange)
            
            # 测试必需字段验证
            required_fields_test = self._test_required_fields_validation(adapter)
            result["tests"]["required_fields"] = required_fields_test
            
            # 测试数据类型转换
            type_conversion_test = self._test_type_conversion(adapter)
            result["tests"]["type_conversion"] = type_conversion_test
            
            # 测试默认值处理
            default_values_test = self._test_default_values(adapter)
            result["tests"]["default_values"] = default_values_test
            
            # 测试数据验证
            data_validation_test = self._test_data_validation(adapter)
            result["tests"]["data_validation"] = data_validation_test
            
            # 确定整体状态
            all_passed = all(test.get("status") == "passed" for test in result["tests"].values())
            result["status"] = "passed" if all_passed else "failed"
            
        except Exception as e:
            result["status"] = "error"
            result["errors"].append(str(e))
            logger.error(f"❌ 数据完整性验证失败: {e}")
        
        return result
    
    def _test_required_fields_validation(self, adapter) -> Dict[str, Any]:
        """测试必需字段验证"""
        try:
            # 测试缺少必需字段的情况
            try:
                adapter._validate_required_fields({}, ["required_field"], "test_data")
                return {
                    "status": "failed",
                    "message": "应该抛出FieldMappingError但没有抛出"
                }
            except FieldMappingError:
                return {"status": "passed", "message": "必需字段验证正常工作"}
            except Exception as e:
                return {
                    "status": "failed",
                    "message": f"抛出了错误的异常类型: {type(e).__name__}"
                }
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _test_type_conversion(self, adapter) -> Dict[str, Any]:
        """测试数据类型转换"""
        try:
            # 测试数值转换
            test_cases = [
                (123, "123"),
                (123.456, "123.456"),
                ("123.789", "123.789"),
                (None, "0")
            ]
            
            for input_val, expected_val in test_cases:
                result = adapter._safe_decimal_convert(input_val, "test_field")
                if result != expected_val:
                    return {
                        "status": "failed",
                        "message": f"数值转换错误: {input_val} -> {result}, 期望: {expected_val}"
                    }
            
            return {"status": "passed", "message": "数据类型转换正常"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _test_default_values(self, adapter) -> Dict[str, Any]:
        """测试默认值处理"""
        try:
            # 测试默认值设置
            test_data = {"existing_field": "value"}
            field_defaults = {
                "existing_field": "default1",
                "missing_field": "default2"
            }
            
            result = adapter._validate_and_set_defaults(test_data, field_defaults)
            
            if result["existing_field"] != "value":
                return {
                    "status": "failed",
                    "message": "现有字段值被错误覆盖"
                }
            
            if result["missing_field"] != "default2":
                return {
                    "status": "failed",
                    "message": "缺失字段未设置默认值"
                }
            
            return {"status": "passed", "message": "默认值处理正常"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _test_data_validation(self, adapter) -> Dict[str, Any]:
        """测试数据验证"""
        try:
            # 测试状态标准化
            test_cases = [
                ("TRADING", "live"),
                ("trading", "live"),
                ("BREAK", "suspend"),
                ("suspend", "suspend"),
                ("unknown", "suspend")
            ]
            
            for input_state, expected_state in test_cases:
                result = adapter._normalize_state(input_state)
                if result != expected_state:
                    return {
                        "status": "failed",
                        "message": f"状态标准化错误: {input_state} -> {result}, 期望: {expected_state}"
                    }
            
            return {"status": "passed", "message": "数据验证正常"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def _validate_performance(self, exchange: str) -> Dict[str, Any]:
        """验证性能"""
        result = {
            "status": "unknown",
            "tests": {},
            "errors": []
        }
        
        try:
            adapter = AdapterFactory.get_adapter(exchange)
            
            # 测试单个数据适配性能
            single_performance = await self._test_single_adaptation_performance(adapter)
            result["tests"]["single_adaptation"] = single_performance
            
            # 测试批量数据适配性能
            batch_performance = await self._test_batch_adaptation_performance(adapter)
            result["tests"]["batch_adaptation"] = batch_performance
            
            # 测试缓存性能
            cache_performance = await self._test_cache_performance(adapter)
            result["tests"]["cache_performance"] = cache_performance
            
            # 确定整体状态
            all_passed = all(test.get("status") == "passed" for test in result["tests"].values())
            result["status"] = "passed" if all_passed else "failed"
            
        except Exception as e:
            result["status"] = "error"
            result["errors"].append(str(e))
            logger.error(f"❌ 性能验证失败: {e}")
        
        return result
    
    async def _test_single_adaptation_performance(self, adapter) -> Dict[str, Any]:
        """测试单个数据适配性能"""
        try:
            import time
            
            # 准备测试数据
            sample_ticker = {
                "symbol": "BTCUSDT",
                "lastPrice": "50000.00",
                "bidPrice": "49999.00",
                "askPrice": "50001.00",
                "closeTime": 1640995200000
            }
            
            # 测试适配性能
            start_time = time.time()
            for _ in range(100):  # 执行100次
                adapter.adapt_ticker(sample_ticker)
            end_time = time.time()
            
            avg_time = (end_time - start_time) / 100
            
            # 性能阈值：单次适配应该在1ms以内
            if avg_time > 0.001:
                return {
                    "status": "failed",
                    "message": f"单次适配性能过慢: {avg_time:.4f}s",
                    "avg_time": avg_time
                }
            
            return {
                "status": "passed",
                "message": f"单次适配性能良好: {avg_time:.4f}s",
                "avg_time": avg_time
            }
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def _test_batch_adaptation_performance(self, adapter) -> Dict[str, Any]:
        """测试批量数据适配性能"""
        try:
            import time
            
            # 准备批量测试数据
            sample_tickers = []
            for i in range(100):
                sample_tickers.append({
                    "symbol": f"BTC{i}USDT",
                    "lastPrice": f"{50000 + i}.00",
                    "bidPrice": f"{49999 + i}.00",
                    "askPrice": f"{50001 + i}.00",
                    "closeTime": 1640995200000 + i
                })
            
            # 测试批量适配性能
            start_time = time.time()
            adapter.adapt_tickers(sample_tickers)
            end_time = time.time()
            
            total_time = end_time - start_time
            avg_time_per_item = total_time / 100
            
            # 性能阈值：批量适配每个项目应该在0.5ms以内
            if avg_time_per_item > 0.0005:
                return {
                    "status": "failed",
                    "message": f"批量适配性能过慢: {avg_time_per_item:.4f}s/item",
                    "total_time": total_time,
                    "avg_time_per_item": avg_time_per_item
                }
            
            return {
                "status": "passed",
                "message": f"批量适配性能良好: {avg_time_per_item:.4f}s/item",
                "total_time": total_time,
                "avg_time_per_item": avg_time_per_item
            }
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def _test_cache_performance(self, adapter) -> Dict[str, Any]:
        """测试缓存性能"""
        try:
            import time
            
            # 清空缓存
            AdapterFactory.clear_cache()
            
            # 第一次获取适配器（无缓存）
            start_time = time.time()
            adapter1 = AdapterFactory.get_adapter("binance", use_cache=True)
            first_time = time.time() - start_time
            
            # 第二次获取适配器（有缓存）
            start_time = time.time()
            adapter2 = AdapterFactory.get_adapter("binance", use_cache=True)
            second_time = time.time() - start_time
            
            # 验证缓存命中
            cache_hit = adapter1 is adapter2
            performance_improvement = first_time > second_time
            
            if not cache_hit:
                return {
                    "status": "failed",
                    "message": "缓存未命中"
                }
            
            if not performance_improvement:
                return {
                    "status": "warning",
                    "message": "缓存性能提升不明显",
                    "first_time": first_time,
                    "second_time": second_time
                }
            
            return {
                "status": "passed",
                "message": "缓存性能良好",
                "first_time": first_time,
                "second_time": second_time,
                "improvement_ratio": first_time / second_time if second_time > 0 else float('inf')
            }
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def _validate_error_handling(self, exchange: str) -> Dict[str, Any]:
        """验证错误处理"""
        result = {
            "status": "unknown",
            "tests": {},
            "errors": []
        }
        
        try:
            adapter = AdapterFactory.get_adapter(exchange)
            
            # 测试异常处理
            exception_handling_test = self._test_exception_handling(adapter)
            result["tests"]["exception_handling"] = exception_handling_test
            
            # 测试错误恢复
            error_recovery_test = self._test_error_recovery(adapter)
            result["tests"]["error_recovery"] = error_recovery_test
            
            # 测试日志记录
            logging_test = self._test_error_logging(adapter)
            result["tests"]["error_logging"] = logging_test
            
            # 确定整体状态
            all_passed = all(test.get("status") == "passed" for test in result["tests"].values())
            result["status"] = "passed" if all_passed else "failed"
            
        except Exception as e:
            result["status"] = "error"
            result["errors"].append(str(e))
            logger.error(f"❌ 错误处理验证失败: {e}")
        
        return result
    
    def _test_exception_handling(self, adapter) -> Dict[str, Any]:
        """测试异常处理"""
        try:
            # 测试无效数据处理
            invalid_data_cases = [
                {},  # 空数据
                {"invalid": "data"},  # 无效字段
                None  # None数据
            ]
            
            for invalid_data in invalid_data_cases:
                try:
                    if invalid_data is None:
                        # 测试None数据
                        adapter.adapt_ticker(None)
                    else:
                        adapter.adapt_ticker(invalid_data)
                    return {
                        "status": "failed",
                        "message": f"应该抛出异常但没有抛出: {invalid_data}"
                    }
                except DataAdaptationError:
                    # 期望的异常类型
                    continue
                except Exception as e:
                    return {
                        "status": "failed",
                        "message": f"抛出了错误的异常类型: {type(e).__name__}"
                    }
            
            return {"status": "passed", "message": "异常处理正常"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _test_error_recovery(self, adapter) -> Dict[str, Any]:
        """测试错误恢复"""
        try:
            # 测试部分数据错误的恢复
            mixed_data = [
                {  # 有效数据
                    "symbol": "BTCUSDT",
                    "lastPrice": "50000.00",
                    "closeTime": 1640995200000
                },
                {  # 无效数据
                    "invalid": "data"
                },
                {  # 另一个有效数据
                    "symbol": "ETHUSDT",
                    "lastPrice": "3000.00",
                    "closeTime": 1640995200000
                }
            ]
            
            # 批量适配应该跳过无效数据，处理有效数据
            results = adapter.adapt_tickers(mixed_data)
            
            # 应该有2个有效结果
            if len(results) != 2:
                return {
                    "status": "failed",
                    "message": f"错误恢复失败，期望2个结果，实际{len(results)}个"
                }
            
            return {"status": "passed", "message": "错误恢复正常"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _test_error_logging(self, adapter) -> Dict[str, Any]:
        """测试错误日志记录"""
        try:
            # 这个测试比较简单，主要验证错误处理方法存在
            if not hasattr(adapter, '_handle_adaptation_error'):
                return {
                    "status": "failed",
                    "message": "缺少错误处理方法"
                }
            
            return {"status": "passed", "message": "错误日志记录功能存在"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _calculate_summary(self, validation_result: Dict[str, Any]) -> None:
        """计算验证结果摘要"""
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        error_tests = 0
        
        for validation_category in validation_result["validations"].values():
            if "tests" in validation_category:
                for test in validation_category["tests"].values():
                    total_tests += 1
                    status = test.get("status", "unknown")
                    if status == "passed":
                        passed_tests += 1
                    elif status == "failed":
                        failed_tests += 1
                    elif status == "error":
                        error_tests += 1
        
        validation_result["summary"] = {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "error_tests": error_tests
        }
        
        # 确定整体状态
        if error_tests > 0:
            validation_result["overall_status"] = "error"
        elif failed_tests > 0:
            validation_result["overall_status"] = "failed"
        elif passed_tests == total_tests:
            validation_result["overall_status"] = "passed"
        else:
            validation_result["overall_status"] = "unknown"
    
    def _generate_recommendations(self, validation_result: Dict[str, Any]) -> List[str]:
        """生成改进建议"""
        recommendations = []
        
        # 检查失败的测试并生成建议
        for category_name, category_result in validation_result["validations"].items():
            if category_result.get("status") == "failed":
                if category_name == "adapter_basics":
                    recommendations.append("建议检查适配器基础配置和依赖")
                elif category_name == "data_formats":
                    recommendations.append("建议检查数据格式转换逻辑")
                elif category_name == "field_mappings":
                    recommendations.append("建议检查字段映射配置")
                elif category_name == "data_integrity":
                    recommendations.append("建议加强数据完整性验证")
                elif category_name == "performance":
                    recommendations.append("建议优化适配器性能")
                elif category_name == "error_handling":
                    recommendations.append("建议改进错误处理机制")
        
        # 检查性能问题
        performance_result = validation_result["validations"].get("performance", {})
        if performance_result.get("status") == "failed":
            recommendations.append("建议优化数据适配性能，考虑使用缓存或批处理")
        
        # 检查错误率
        summary = validation_result.get("summary", {})
        if summary.get("failed_tests", 0) > summary.get("total_tests", 1) * 0.1:
            recommendations.append("失败测试比例较高，建议全面检查适配器实现")
        
        return recommendations
    
    def generate_validation_report(self, validation_result: Dict[str, Any]) -> str:
        """
        生成验证报告
        Generate validation report
        """
        report_lines = [
            "=" * 80,
            "数据适配验证报告",
            "Data Adaptation Validation Report",
            "=" * 80,
            f"验证时间: {validation_result['timestamp']}",
            f"交易所: {validation_result['exchange']}",
            f"整体状态: {validation_result['overall_status']}",
            "",
            "摘要信息:",
            f"  总测试数: {validation_result['summary']['total_tests']}",
            f"  通过测试: {validation_result['summary']['passed_tests']}",
            f"  失败测试: {validation_result['summary']['failed_tests']}",
            f"  错误测试: {validation_result['summary']['error_tests']}",
            f"  成功率: {validation_result['summary']['passed_tests'] / max(validation_result['summary']['total_tests'], 1) * 100:.1f}%",
            "",
            "详细结果:",
        ]
        
        for category_name, category_result in validation_result["validations"].items():
            report_lines.extend([
                f"  {category_name}:",
                f"    状态: {category_result['status']}",
            ])
            
            if "tests" in category_result:
                report_lines.append("    测试结果:")
                for test_name, test_result in category_result["tests"].items():
                    status = test_result.get("status", "unknown")
                    message = test_result.get("message", "")
                    report_lines.append(f"      {test_name}: {status} - {message}")
            
            if "errors" in category_result and category_result["errors"]:
                report_lines.append("    错误信息:")
                for error in category_result["errors"]:
                    report_lines.append(f"      - {error}")
            
            report_lines.append("")
        
        if validation_result.get("recommendations"):
            report_lines.extend([
                "改进建议:",
                *[f"  - {rec}" for rec in validation_result["recommendations"]],
                ""
            ])
        
        report_lines.extend([
            "=" * 80,
            "报告结束"
        ])
        
        return "\n".join(report_lines)
    
    async def compare_adaptation_results(self, exchange: str, raw_data: Dict[str, Any], 
                                       data_type: str) -> Dict[str, Any]:
        """
        对比适配前后的数据
        Compare data before and after adaptation
        
        Args:
            exchange: 交易所名称
            raw_data: 原始数据
            data_type: 数据类型 (ticker, instrument, funding_rate, position)
            
        Returns:
            Dict: 对比结果
        """
        comparison_result = {
            "timestamp": datetime.now().isoformat(),
            "exchange": exchange,
            "data_type": data_type,
            "raw_data": raw_data,
            "adapted_data": None,
            "comparison": {},
            "status": "unknown"
        }
        
        try:
            adapter = AdapterFactory.get_adapter(exchange)
            
            # 根据数据类型执行适配
            if data_type == "ticker":
                adapted_data = adapter.adapt_ticker(raw_data)
            elif data_type == "instrument":
                adapted_data = adapter.adapt_instruments([raw_data])[0] if raw_data else None
            elif data_type == "funding_rate":
                adapted_data = adapter.adapt_funding_rate(raw_data)
            elif data_type == "position":
                adapted_data = adapter.adapt_position(raw_data)
            else:
                raise ValueError(f"不支持的数据类型: {data_type}")
            
            comparison_result["adapted_data"] = adapted_data.__dict__ if adapted_data else None
            
            # 执行字段对比
            comparison_result["comparison"] = self._compare_fields(raw_data, adapted_data, data_type)
            comparison_result["status"] = "success"
            
        except Exception as e:
            comparison_result["status"] = "error"
            comparison_result["error"] = str(e)
            logger.error(f"❌ 数据对比失败: {e}")
        
        return comparison_result
    
    def _compare_fields(self, raw_data: Dict[str, Any], adapted_data, data_type: str) -> Dict[str, Any]:
        """对比字段映射"""
        comparison = {
            "field_mappings": {},
            "missing_fields": [],
            "extra_fields": [],
            "type_conversions": {}
        }
        
        if not adapted_data:
            return comparison
        
        # 定义字段映射关系
        field_mappings = {
            "ticker": {
                "symbol": "instId",
                "lastPrice": "last",
                "bidPrice": "bidPx",
                "askPrice": "askPx",
                "bidQty": "bidSz",
                "askQty": "askSz",
                "volume": "vol24h",
                "quoteVolume": "volCcy24h"
            },
            "instrument": {
                "symbol": "instId",
                "baseAsset": "baseCcy",
                "quoteAsset": "quoteCcy",
                "status": "state"
            },
            "funding_rate": {
                "symbol": "instId",
                "lastFundingRate": "fundingRate",
                "fundingTime": "fundingTime",
                "nextFundingTime": "nextFundingTime"
            },
            "position": {
                "symbol": "instId",
                "positionAmt": "pos",
                "positionSide": "posSide",
                "entryPrice": "avgPx",
                "unRealizedProfit": "upl"
            }
        }
        
        mappings = field_mappings.get(data_type, {})
        
        for raw_field, adapted_field in mappings.items():
            if raw_field in raw_data and hasattr(adapted_data, adapted_field):
                raw_value = raw_data[raw_field]
                adapted_value = getattr(adapted_data, adapted_field)
                
                comparison["field_mappings"][f"{raw_field} -> {adapted_field}"] = {
                    "raw_value": raw_value,
                    "adapted_value": adapted_value,
                    "raw_type": type(raw_value).__name__,
                    "adapted_type": type(adapted_value).__name__
                }
                
                # 检查类型转换
                if type(raw_value) != type(adapted_value):
                    comparison["type_conversions"][adapted_field] = {
                        "from": type(raw_value).__name__,
                        "to": type(adapted_value).__name__
                    }
        
        return comparison


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="数据适配验证脚本")
    parser.add_argument("--exchange", default="binance", help="要验证的交易所")
    parser.add_argument("--output", help="输出报告文件路径")
    parser.add_argument("--compare", action="store_true", help="执行数据对比测试")
    parser.add_argument("--quick", action="store_true", help="快速验证模式")
    
    args = parser.parse_args()
    
    validator = DataAdaptationValidator()
    
    try:
        if args.quick:
            # 快速验证模式
            logger.info("🚀 执行快速验证")
            diagnostics = AdapterDiagnostics()
            health_check = await diagnostics.quick_health_check(args.exchange)
            
            if health_check:
                print(f"✅ {args.exchange} 适配器健康检查通过")
            else:
                print(f"❌ {args.exchange} 适配器健康检查失败")
            
        elif args.compare:
            # 数据对比模式
            logger.info("🔍 执行数据对比测试")
            
            # 示例数据对比
            sample_ticker = {
                "symbol": "BTCUSDT",
                "lastPrice": "50000.00",
                "bidPrice": "49999.00",
                "askPrice": "50001.00",
                "closeTime": 1640995200000
            }
            
            comparison_result = await validator.compare_adaptation_results(
                args.exchange, sample_ticker, "ticker"
            )
            
            print("数据对比结果:")
            print(json.dumps(comparison_result, indent=2, ensure_ascii=False))
            
        else:
            # 完整验证模式
            logger.info("🔍 执行完整验证")
            validation_result = await validator.run_comprehensive_validation(args.exchange)
            
            # 生成报告
            report = validator.generate_validation_report(validation_result)
            
            if args.output:
                # 保存到文件
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(report)
                logger.info(f"📄 验证报告已保存到: {args.output}")
            else:
                # 打印到控制台
                print(report)
            
            # 输出JSON结果
            json_output = args.output.replace('.txt', '.json') if args.output else None
            if json_output:
                with open(json_output, 'w', encoding='utf-8') as f:
                    json.dump(validation_result, f, indent=2, ensure_ascii=False)
                logger.info(f"📄 JSON结果已保存到: {json_output}")
    
    except Exception as e:
        logger.error(f"❌ 验证过程中发生错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())