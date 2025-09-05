#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易对管理服务 - 管理交易对信息的获取和存储
Trading Pair Management Service - Manages trading pair information
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy import select, update
from sqlalchemy.dialects.mysql import insert

from app.services.exchanges.exchange_service_manager import get_exchange_service
from app.models.market_data import TradingPair
from app.core.database import db_manager
from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)
settings = get_settings()


class TradingPairService:
    """交易对管理服务"""
    
    def __init__(self):
        self.exchange_service = None  # 将在需要时异步初始化
        self.db_manager = db_manager
        
        # 排除的大市值币种（波动太大，不适合吃利息）
        self.excluded_major_coins = {
            'BTC-USDT-SWAP', 'BNB-USDT-SWAP', 
            'XRP-USDT-SWAP', 'ADA-USDT-SWAP',
            'DOGE-USDT-SWAP', 'AVAX-USDT-SWAP', 'DOT-USDT-SWAP',
            'LTC-USDT-SWAP', 'BCH-USDT-SWAP',
            'LINK-USDT-SWAP', 'UNI-USDT-SWAP', 'ATOM-USDT-SWAP',
            'NEAR-USDT-SWAP', 'FIL-USDT-SWAP', 'SAND-USDT-SWAP',
            'MANA-USDT-SWAP', 'APE-USDT-SWAP', 'SHIB-USDT-SWAP',
            # USD合约也排除
            'BTC-USD-SWAP', 'ETH-USD-SWAP', 'SOL-USD-SWAP',
            'XRP-USD-SWAP', 'ADA-USD-SWAP', 'DOGE-USD-SWAP',
            'AVAX-USD-SWAP', 'DOT-USD-SWAP', 'LTC-USD-SWAP'
        }
    
    async def _ensure_exchange_service(self):
        """确保交易所服务已初始化"""
        if self.exchange_service is None:
            self.exchange_service = await get_exchange_service()
    
    async def fetch_and_update_trading_pairs(self) -> Dict[str, Any]:
        """从配置的交易所获取并更新交易对信息"""
        try:
            logger.info("📊 开始获取交易对列表...")
            
            # 确保交易所服务已初始化
            await self._ensure_exchange_service()
            
            # 获取永续合约交易对
            instruments = await self.exchange_service.get_all_instruments('SWAP')
            
            if not instruments:
                logger.warning("未获取到交易对数据")
                return {'success': False, 'error': '未获取到交易对数据'}
            
            logger.info(f"获取到 {len(instruments)} 个交易对")
            
            # 筛选USDT永续合约
            usdt_pairs = []
            for instrument in instruments:
                inst_id = instrument.get('instId', '')
                if (inst_id.endswith('-USDT-SWAP') and 
                    inst_id not in self.excluded_major_coins and
                    instrument.get('state') == 'live'):  # 只要活跃的交易对
                    usdt_pairs.append(instrument)
            
            logger.info(f"筛选出 {len(usdt_pairs)} 个USDT永续合约")
            
            # 批量更新数据库
            updated_count = await self._batch_update_trading_pairs(usdt_pairs)
            
            return {
                'success': True,
                'total_instruments': len(instruments),
                'usdt_pairs': len(usdt_pairs),
                'updated_count': updated_count,
                'update_time': datetime.now()
            }
            
        except Exception as e:
            logger.error(f"更新交易对失败: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _batch_update_trading_pairs(self, instruments: List[Dict[str, Any]]) -> int:
        """批量更新交易对到数据库"""
        try:
            with self.db_manager.session_scope() as session:
                updated_count = 0
                
                for instrument in instruments:
                    # 处理时间字段，确保空值转换为None
                    list_time = instrument.get('listTime')
                    if list_time == '' or list_time is None:
                        list_time = None
                    else:
                        try:
                            list_time = int(list_time) if list_time else None
                        except (ValueError, TypeError):
                            list_time = None
                    
                    exp_time = instrument.get('expTime')
                    if exp_time == '' or exp_time is None:
                        exp_time = None
                    else:
                        try:
                            exp_time = int(exp_time) if exp_time else None
                        except (ValueError, TypeError):
                            exp_time = None
                    
                    # 使用MySQL的ON DUPLICATE KEY UPDATE语法
                    stmt = insert(TradingPair).values(
                        inst_id=instrument.get('instId'),
                        inst_type=instrument.get('instType'),
                        base_ccy=instrument.get('baseCcy'),
                        quote_ccy=instrument.get('quoteCcy'),
                        settle_ccy=instrument.get('settleCcy'),
                        ct_val=instrument.get('ctVal'),
                        ct_mult=instrument.get('ctMult'),
                        ct_val_ccy=instrument.get('ctValCcy'),
                        min_sz=instrument.get('minSz'),
                        lot_sz=instrument.get('lotSz'),
                        tick_sz=instrument.get('tickSz'),
                        state=instrument.get('state'),
                        list_time=list_time,
                        exp_time=exp_time,
                        is_active='true',
                        last_updated=datetime.utcnow()
                    )
                    
                    # ON DUPLICATE KEY UPDATE
                    stmt = stmt.on_duplicate_key_update(
                        inst_type=stmt.inserted.inst_type,
                        base_ccy=stmt.inserted.base_ccy,
                        quote_ccy=stmt.inserted.quote_ccy,
                        settle_ccy=stmt.inserted.settle_ccy,
                        ct_val=stmt.inserted.ct_val,
                        ct_mult=stmt.inserted.ct_mult,
                        ct_val_ccy=stmt.inserted.ct_val_ccy,
                        min_sz=stmt.inserted.min_sz,
                        lot_sz=stmt.inserted.lot_sz,
                        tick_sz=stmt.inserted.tick_sz,
                        state=stmt.inserted.state,
                        list_time=stmt.inserted.list_time,
                        exp_time=stmt.inserted.exp_time,
                        is_active=stmt.inserted.is_active,
                        last_updated=stmt.inserted.last_updated
                    )
                    
                    session.execute(stmt)
                    updated_count += 1
                
                # session.commit() is handled by session_scope context manager
                logger.info(f"✅ 批量更新成功: 更新 {updated_count} 个交易对到数据库")
                return updated_count
                
        except Exception as e:
            logger.error(f"❌ 批量更新交易对失败: {e}")
            return 0
    
    async def get_active_usdt_pairs(self) -> List[str]:
        """获取活跃的USDT永续合约列表"""
        try:
            with self.db_manager.session_scope() as session:
                query = select(TradingPair.inst_id).where(
                    TradingPair.inst_type == 'SWAP',
                    TradingPair.quote_ccy == 'USDT',
                    TradingPair.state == 'live',
                    TradingPair.is_active == 'true'
                )
                
                result = session.execute(query)
                pairs = [row[0] for row in result.fetchall()]
                
                logger.info(f"从数据库获取到 {len(pairs)} 个活跃USDT永续合约")
                return pairs
                
        except Exception as e:
            logger.error(f"获取活跃交易对失败: {e}")
            return []
    
    async def get_pairs_for_funding_monitor(self) -> List[str]:
        """获取用于负费率监控的交易对列表"""
        try:
            # 先尝试从数据库获取
            pairs = await self.get_active_usdt_pairs()
            
            # 如果数据库为空或数据过期，重新获取
            if not pairs or await self._is_data_outdated():
                logger.info("交易对数据为空或过期，重新获取...")
                update_result = await self.fetch_and_update_trading_pairs()
                
                if update_result['success']:
                    pairs = await self.get_active_usdt_pairs()
                else:
                    logger.warning("更新交易对失败，使用备用列表")
                    pairs = self._get_fallback_pairs()
            
            # 过滤掉排除的币种
            filtered_pairs = [pair for pair in pairs if pair not in self.excluded_major_coins]
            
            logger.info(f"获取到 {len(filtered_pairs)} 个用于监控的交易对")
            return filtered_pairs
            
        except Exception as e:
            logger.error(f"获取监控交易对失败: {e}")
            return self._get_fallback_pairs()
    
    async def _is_data_outdated(self) -> bool:
        """检查数据是否过期（超过24小时）"""
        try:
            with self.db_manager.session_scope() as session:
                query = select(TradingPair.last_updated).order_by(
                    TradingPair.last_updated.desc()
                ).limit(1)
                
                result = session.execute(query)
                last_update = result.scalar()
                
                if not last_update:
                    return True
                
                # 检查是否超过24小时
                return datetime.utcnow() - last_update > timedelta(hours=24)
                
        except Exception as e:
            logger.error(f"检查数据时效性失败: {e}")
            return True
    
    def _get_fallback_pairs(self) -> List[str]:
        """获取备用交易对列表（硬编码的常见USDT永续合约）"""
        fallback_pairs = [
            'ETH-USDT-SWAP', 'SOL-USDT-SWAP', 'MATIC-USDT-SWAP',
            'FTM-USDT-SWAP', 'AAVE-USDT-SWAP', 'SUSHI-USDT-SWAP',
            'CRV-USDT-SWAP', 'COMP-USDT-SWAP', 'YFI-USDT-SWAP',
            'SNX-USDT-SWAP', 'MKR-USDT-SWAP', 'ALPHA-USDT-SWAP',
            'CAKE-USDT-SWAP', 'RUNE-USDT-SWAP', 'LUNA-USDT-SWAP',
            'AVAX-USDT-SWAP', 'ALGO-USDT-SWAP', 'XTZ-USDT-SWAP',
            'EGLD-USDT-SWAP', 'THETA-USDT-SWAP', 'VET-USDT-SWAP',
            'TRX-USDT-SWAP', 'EOS-USDT-SWAP', 'NEO-USDT-SWAP',
            'IOST-USDT-SWAP', 'ONT-USDT-SWAP', 'ICX-USDT-SWAP'
        ]
        
        # 过滤掉排除的币种
        return [pair for pair in fallback_pairs if pair not in self.excluded_major_coins]
    
    async def update_pair_status(self, inst_id: str, is_active: bool) -> bool:
        """更新交易对状态"""
        try:
            with self.db_manager.session_scope() as session:
                stmt = update(TradingPair).where(
                    TradingPair.inst_id == inst_id
                ).values(
                    is_active='true' if is_active else 'false',
                    last_updated=datetime.utcnow()
                )
                
                session.execute(stmt)
                # session.commit() is handled by session_scope context manager
                
                logger.info(f"更新交易对 {inst_id} 状态为 {'启用' if is_active else '禁用'}")
                return True
                
        except Exception as e:
            logger.error(f"更新交易对状态失败: {e}")
            return False


# 独立运行函数
async def update_trading_pairs():
    """独立运行：更新交易对列表"""
    service = TradingPairService()
    result = await service.fetch_and_update_trading_pairs()
    
    if result['success']:
        logger.info(f"✅ 交易对更新成功:")
        logger.info(f"   总交易对数: {result['total_instruments']}")
        logger.info(f"   USDT永续合约: {result['usdt_pairs']}")
        print(f"   更新数量: {result['updated_count']}")
        print(f"   更新时间: {result['update_time']}")
    else:
        print(f"❌ 交易对更新失败: {result['error']}")


if __name__ == "__main__":
    asyncio.run(update_trading_pairs())