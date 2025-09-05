# -*- coding: utf-8 -*-
"""
交易对服务验证脚本
Trading Pair Service Verification Script

验证币安交易对服务的正确性，包括：
1. 测试交易对筛选功能
2. 验证数据库字段映射
3. 检查适配器的数据转换
"""

import asyncio
import sys
import os
from typing import Dict, Any

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging import get_logger
from app.core.config import get_settings
from app.services.trading.trading_pair_service import TradingPairService
from app.services.exchanges.exchange_service_manager import get_exchange_service
from app.services.exchanges.adapters.adapter_factory import get_adapter
from app.core.database import db_manager
from app.models.market_data import TradingPair
from sqlalchemy import select, func

logger = get_logger(__name__)
settings = get_settings()


class TradingPairServiceVerifier:
    """交易对服务验证器"""
    
    def __init__(self):
        self.trading_pair_service = TradingPairService()
        self.exchange_service = None
        self.adapter = None
        self.verification_results = {
            'filtering_test': {'passed': False, 'details': {}},
            'database_mapping_test': {'passed': False, 'details': {}},
            'adapter_test': {'passed': False, 'details': {}},
            'integration_test': {'passed': False, 'details': {}},
            'overall_status': 'FAILED'
        }
    
    async def initialize(self):
        """初始化验证器"""
        try:
            logger.info("🚀 初始化交易对服务验证器...")
            
            # 获取交易所服务
            self.exchange_service = await get_exchange_service()
            logger.info(f"✅ 交易所服务初始化完成: {type(self.exchange_service).__name__}")
            
            # 获取数据适配器
            self.adapter = get_adapter("binance")
            logger.info(f"✅ 数据适配器初始化完成: {type(self.adapter).__name__}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 验证器初始化失败: {e}")
            return False
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """运行所有验证测试"""
        logger.info("📊 开始运行交易对服务验证测试...")
        
        # 测试1: 交易对筛选功能
        await self.test_trading_pair_filtering()
        
        # 测试2: 数据库字段映射
        await self.test_database_field_mapping()
        
        # 测试3: 数据适配器功能
        await self.test_data_adapter()
        
        # 测试4: 集成测试
        await self.test_integration()
        
        # 计算总体状态
        self._calculate_overall_status()
        
        return self.verification_results
    
    async def test_trading_pair_filtering(self):
        """测试交易对筛选功能"""
        logger.info("🔍 测试1: 交易对筛选功能")
        
        try:
            test_details = {
                'raw_instruments_count': 0,
                'usdt_swap_count': 0,
                'filtered_pairs': [],
                'excluded_pairs': [],
                'sample_pairs': []
            }
            
            # 获取原始交易对数据
            raw_instruments = await self.exchange_service.get_all_instruments('SWAP')
            test_details['raw_instruments_count'] = len(raw_instruments)
            logger.info(f"📊 获取到原始交易对数据: {len(raw_instruments)} 个")
            
            if not raw_instruments:
                raise Exception("未获取到任何交易对数据")
            
            # 筛选USDT永续合约
            usdt_pairs = []
            excluded_pairs = []
            
            for instrument in raw_instruments:
                inst_id = instrument.get('instId', '')
                state = instrument.get('state', '')
                
                if inst_id.endswith('-USDT-SWAP'):
                    if state == 'live':
                        # 检查是否在排除列表中
                        if inst_id in self.trading_pair_service.excluded_major_coins:
                            excluded_pairs.append(inst_id)
                        else:
                            usdt_pairs.append(instrument)
                    else:
                        logger.debug(f"跳过非活跃交易对: {inst_id} (状态: {state})")
            
            test_details['usdt_swap_count'] = len(usdt_pairs)
            test_details['excluded_pairs'] = excluded_pairs[:10]  # 只记录前10个
            test_details['sample_pairs'] = [pair.get('instId') for pair in usdt_pairs[:10]]
            
            logger.info(f"✅ 筛选结果: USDT永续合约 {len(usdt_pairs)} 个，排除 {len(excluded_pairs)} 个")
            
            # 验证筛选质量
            if len(usdt_pairs) > 0:
                # 检查样本数据的格式
                sample_pair = usdt_pairs[0]
                required_fields = ['instId', 'instType', 'baseCcy', 'quoteCcy', 'state']
                missing_fields = [field for field in required_fields if field not in sample_pair]
                
                if missing_fields:
                    logger.warning(f"⚠️ 样本数据缺少字段: {missing_fields}")
                    test_details['missing_fields'] = missing_fields
                else:
                    logger.info("✅ 样本数据字段完整")
                
                self.verification_results['filtering_test']['passed'] = True
                logger.info("✅ 测试1通过: 交易对筛选功能正常")
            else:
                raise Exception("筛选出的USDT永续合约数量为0")
            
            self.verification_results['filtering_test']['details'] = test_details
            
        except Exception as e:
            logger.error(f"❌ 测试1失败: 交易对筛选功能异常 - {e}")
            self.verification_results['filtering_test']['details']['error'] = str(e)
    
    async def test_database_field_mapping(self):
        """测试数据库字段映射"""
        logger.info("🔍 测试2: 数据库字段映射")
        
        try:
            test_details = {
                'field_mapping_check': {},
                'database_write_test': False,
                'field_validation': {}
            }
            
            # 获取一个样本交易对数据
            instruments = await self.exchange_service.get_all_instruments('SWAP')
            if not instruments:
                raise Exception("无法获取交易对数据进行测试")
            
            # 找一个USDT永续合约作为测试样本
            test_instrument = None
            for instrument in instruments:
                if (instrument.get('instId', '').endswith('-USDT-SWAP') and 
                    instrument.get('state') == 'live'):
                    test_instrument = instrument
                    break
            
            if not test_instrument:
                raise Exception("未找到合适的测试交易对")
            
            logger.info(f"📊 使用测试交易对: {test_instrument.get('instId')}")
            
            # 检查字段映射
            expected_fields = {
                'instId': test_instrument.get('instId'),
                'instType': test_instrument.get('instType'),
                'baseCcy': test_instrument.get('baseCcy'),
                'quoteCcy': test_instrument.get('quoteCcy'),
                'settleCcy': test_instrument.get('settleCcy'),
                'state': test_instrument.get('state')
            }
            
            for field, value in expected_fields.items():
                if value is not None:
                    test_details['field_mapping_check'][field] = {
                        'present': True,
                        'value': str(value)[:50]  # 限制长度
                    }
                else:
                    test_details['field_mapping_check'][field] = {
                        'present': False,
                        'value': None
                    }
            
            # 测试数据库写入（使用_batch_update_trading_pairs方法）
            try:
                # 创建一个测试用的交易对数据
                test_data = [test_instrument]
                updated_count = await self.trading_pair_service._batch_update_trading_pairs(test_data)
                
                if updated_count > 0:
                    test_details['database_write_test'] = True
                    logger.info(f"✅ 数据库写入测试成功: 更新 {updated_count} 个交易对")
                    
                    # 验证数据库中的数据
                    with db_manager.session_scope() as session:
                        query = select(TradingPair).where(
                            TradingPair.inst_id == test_instrument.get('instId')
                        )
                        result = session.execute(query)
                        db_record = result.scalar_one_or_none()
                        
                        if db_record:
                            test_details['field_validation'] = {
                                'inst_id': db_record.inst_id,
                                'inst_type': db_record.inst_type,
                                'base_ccy': db_record.base_ccy,
                                'quote_ccy': db_record.quote_ccy,
                                'state': db_record.state,
                                'is_active': db_record.is_active,
                                'last_updated': str(db_record.last_updated)
                            }
                            logger.info("✅ 数据库字段验证成功")
                        else:
                            logger.warning("⚠️ 数据库中未找到写入的记录")
                else:
                    raise Exception("数据库写入失败，更新数量为0")
                
            except Exception as db_error:
                logger.error(f"❌ 数据库写入测试失败: {db_error}")
                test_details['database_write_error'] = str(db_error)
                raise db_error
            
            self.verification_results['database_mapping_test']['passed'] = True
            self.verification_results['database_mapping_test']['details'] = test_details
            logger.info("✅ 测试2通过: 数据库字段映射正常")
            
        except Exception as e:
            logger.error(f"❌ 测试2失败: 数据库字段映射异常 - {e}")
            self.verification_results['database_mapping_test']['details']['error'] = str(e)
    
    async def test_data_adapter(self):
        """测试数据适配器功能"""
        logger.info("🔍 测试3: 数据适配器功能")
        
        try:
            test_details = {
                'adapter_type': type(self.adapter).__name__,
                'raw_data_test': {},
                'adaptation_test': {},
                'field_transformation': {}
            }
            
            # 获取原始数据进行适配测试
            if hasattr(self.exchange_service, 'rest_service'):
                # 获取币安原始交易对数据
                raw_instruments = await self.exchange_service.rest_service.get_raw_instruments()
                test_details['raw_data_test']['count'] = len(raw_instruments) if raw_instruments else 0
                
                if raw_instruments and len(raw_instruments) > 0:
                    # 测试适配器转换
                    sample_raw = raw_instruments[0]
                    test_details['raw_data_test']['sample_fields'] = list(sample_raw.keys())
                    
                    # 使用适配器转换数据
                    unified_instruments = self.adapter.adapt_instruments(raw_instruments[:10])  # 只测试前10个
                    test_details['adaptation_test']['converted_count'] = len(unified_instruments)
                    
                    if unified_instruments:
                        sample_unified = unified_instruments[0]
                        test_details['adaptation_test']['unified_fields'] = [
                            'instId', 'instType', 'baseCcy', 'quoteCcy', 'state'
                        ]
                        
                        # 检查字段转换
                        test_details['field_transformation'] = {
                            'original_symbol': sample_raw.get('symbol'),
                            'unified_instId': sample_unified.instId,
                            'original_status': sample_raw.get('status'),
                            'unified_state': sample_unified.state,
                            'original_baseAsset': sample_raw.get('baseAsset'),
                            'unified_baseCcy': sample_unified.baseCcy
                        }
                        
                        logger.info(f"✅ 适配器转换成功: {sample_raw.get('symbol')} -> {sample_unified.instId}")
                        
                        # 验证转换逻辑
                        if (sample_raw.get('symbol', '').endswith('USDT') and 
                            sample_unified.instId.endswith('-USDT-SWAP')):
                            logger.info("✅ 符号转换逻辑正确")
                        else:
                            logger.warning("⚠️ 符号转换逻辑可能有问题")
                        
                        if (sample_raw.get('status') == 'TRADING' and 
                            sample_unified.state == 'live'):
                            logger.info("✅ 状态转换逻辑正确")
                        else:
                            logger.warning("⚠️ 状态转换逻辑可能有问题")
                        
                        self.verification_results['adapter_test']['passed'] = True
                        logger.info("✅ 测试3通过: 数据适配器功能正常")
                    else:
                        raise Exception("适配器转换结果为空")
                else:
                    raise Exception("无法获取原始数据进行适配测试")
            else:
                raise Exception("交易所服务不支持获取原始数据")
            
            self.verification_results['adapter_test']['details'] = test_details
            
        except Exception as e:
            logger.error(f"❌ 测试3失败: 数据适配器功能异常 - {e}")
            self.verification_results['adapter_test']['details']['error'] = str(e)
    
    async def test_integration(self):
        """集成测试"""
        logger.info("🔍 测试4: 集成测试")
        
        try:
            test_details = {
                'full_update_test': {},
                'database_count_before': 0,
                'database_count_after': 0,
                'active_pairs_test': {}
            }
            
            # 获取更新前的数据库记录数
            with db_manager.session_scope() as session:
                count_query = select(func.count(TradingPair.id))
                result = session.execute(count_query)
                test_details['database_count_before'] = result.scalar()
            
            logger.info(f"📊 更新前数据库记录数: {test_details['database_count_before']}")
            
            # 执行完整的交易对更新流程
            update_result = await self.trading_pair_service.fetch_and_update_trading_pairs()
            test_details['full_update_test'] = update_result
            
            if update_result.get('success'):
                logger.info(f"✅ 完整更新流程成功:")
                logger.info(f"   总交易对数: {update_result.get('total_instruments', 0)}")
                logger.info(f"   USDT永续合约: {update_result.get('usdt_pairs', 0)}")
                logger.info(f"   更新数量: {update_result.get('updated_count', 0)}")
                
                # 获取更新后的数据库记录数
                with db_manager.session_scope() as session:
                    count_query = select(func.count(TradingPair.id))
                    result = session.execute(count_query)
                    test_details['database_count_after'] = result.scalar()
                
                logger.info(f"📊 更新后数据库记录数: {test_details['database_count_after']}")
                
                # 测试获取活跃交易对
                active_pairs = await self.trading_pair_service.get_active_usdt_pairs()
                test_details['active_pairs_test'] = {
                    'count': len(active_pairs),
                    'sample_pairs': active_pairs[:10] if active_pairs else []
                }
                
                logger.info(f"✅ 获取活跃交易对: {len(active_pairs)} 个")
                
                # 验证筛选出的交易对数量合理
                if update_result.get('usdt_pairs', 0) > 0:
                    self.verification_results['integration_test']['passed'] = True
                    logger.info("✅ 测试4通过: 集成测试成功")
                else:
                    raise Exception("集成测试失败：筛选出的USDT永续合约数量为0")
            else:
                raise Exception(f"完整更新流程失败: {update_result.get('error')}")
            
            self.verification_results['integration_test']['details'] = test_details
            
        except Exception as e:
            logger.error(f"❌ 测试4失败: 集成测试异常 - {e}")
            self.verification_results['integration_test']['details']['error'] = str(e)
    
    def _calculate_overall_status(self):
        """计算总体状态"""
        passed_tests = sum(1 for test in self.verification_results.values() 
                          if isinstance(test, dict) and test.get('passed', False))
        total_tests = 4  # 总共4个测试
        
        if passed_tests == total_tests:
            self.verification_results['overall_status'] = 'PASSED'
        elif passed_tests > 0:
            self.verification_results['overall_status'] = 'PARTIAL'
        else:
            self.verification_results['overall_status'] = 'FAILED'
        
        self.verification_results['test_summary'] = {
            'passed_tests': passed_tests,
            'total_tests': total_tests,
            'pass_rate': f"{passed_tests}/{total_tests} ({passed_tests/total_tests*100:.1f}%)"
        }
    
    def print_results(self):
        """打印验证结果"""
        print("\n" + "="*80)
        print("🔍 交易对服务验证结果报告")
        print("="*80)
        
        # 总体状态
        status_emoji = {
            'PASSED': '✅',
            'PARTIAL': '⚠️',
            'FAILED': '❌'
        }
        overall_status = self.verification_results['overall_status']
        print(f"\n📊 总体状态: {status_emoji.get(overall_status, '❓')} {overall_status}")
        
        if 'test_summary' in self.verification_results:
            summary = self.verification_results['test_summary']
            print(f"📈 测试通过率: {summary['pass_rate']}")
        
        # 各项测试结果
        test_names = {
            'filtering_test': '1. 交易对筛选功能',
            'database_mapping_test': '2. 数据库字段映射',
            'adapter_test': '3. 数据适配器功能',
            'integration_test': '4. 集成测试'
        }
        
        print("\n📋 详细测试结果:")
        for test_key, test_name in test_names.items():
            if test_key in self.verification_results:
                test_result = self.verification_results[test_key]
                status = "✅ 通过" if test_result.get('passed') else "❌ 失败"
                print(f"   {test_name}: {status}")
                
                # 显示关键信息
                details = test_result.get('details', {})
                if test_key == 'filtering_test' and details:
                    print(f"      - 原始交易对: {details.get('raw_instruments_count', 0)} 个")
                    print(f"      - USDT永续合约: {details.get('usdt_swap_count', 0)} 个")
                elif test_key == 'integration_test' and details:
                    update_test = details.get('full_update_test', {})
                    if update_test.get('success'):
                        print(f"      - 更新成功: {update_test.get('updated_count', 0)} 个交易对")
                
                # 显示错误信息
                if 'error' in details:
                    print(f"      ❌ 错误: {details['error']}")
        
        print("\n" + "="*80)


async def main():
    """主函数"""
    print("🚀 启动交易对服务验证...")
    
    verifier = TradingPairServiceVerifier()
    
    # 初始化验证器
    if not await verifier.initialize():
        print("❌ 验证器初始化失败")
        return
    
    # 运行所有测试
    results = await verifier.run_all_tests()
    
    # 打印结果
    verifier.print_results()
    
    # 返回退出码
    if results['overall_status'] == 'PASSED':
        print("\n✅ 所有测试通过！交易对服务工作正常。")
        return 0
    elif results['overall_status'] == 'PARTIAL':
        print("\n⚠️ 部分测试通过，请检查失败的测试项。")
        return 1
    else:
        print("\n❌ 测试失败，交易对服务存在问题。")
        return 2


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断测试")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ 验证脚本执行异常: {e}")
        sys.exit(1)