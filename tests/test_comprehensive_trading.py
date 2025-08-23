# -*- coding: utf-8 -*-
"""
综合交易策略测试
Comprehensive Trading Strategy Tests
"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from app.services.comprehensive_trading_service import ComprehensiveTradingService
from app.services.trading_decision_service import TradingDecisionService, PositionRecommendation, MarketAnalysis, TradingAction, RiskLevel


class TestComprehensiveTradingService:
    """综合交易策略服务测试"""
    
    @pytest.fixture
    def service(self):
        """创建服务实例"""
        return ComprehensiveTradingService()
    
    @pytest.fixture
    def mock_market_analysis(self):
        """模拟市场分析结果"""
        return MarketAnalysis(
            symbol="BTCUSDT",
            timestamp=datetime.now(),
            traditional_signals={
                "overall_signal": "buy",
                "signal_strength": 0.8,
                "volatility_score": 60.0
            },
            ml_prediction={
                "signal": "strong_buy",
                "confidence": 0.85,
                "model_accuracy": 0.78
            },
            ml_anomalies=[],
            bullish_score=80.0,
            bearish_score=20.0,
            volatility_score=60.0,
            market_regime="trending",
            trend_strength=0.8
        )
    
    @pytest.fixture
    def mock_recommendation(self):
        """模拟交易建议"""
        return PositionRecommendation(
            symbol="BTCUSDT",
            action=TradingAction.STRONG_BUY,
            confidence=85.0,
            position_size_percent=15.0,
            leverage=3.0,
            stop_loss_percent=3.5,
            take_profit_percent=8.0,
            risk_level=RiskLevel.MEDIUM,
            reasoning="强烈买入信号",
            support_levels=[42000.0, 41500.0, 41000.0],
            resistance_levels=[44000.0, 45000.0, 46000.0],
            hold_duration_hours=24,
            entry_timing="immediate"
        )
    
    @pytest.mark.asyncio
    async def test_start_trading_session(self, service):
        """测试启动交易会话"""
        symbols = ["BTCUSDT", "ETHUSDT"]
        session_config = {"auto_analysis": True}
        
        session_id = await service.start_trading_session(symbols, session_config)
        
        assert session_id.startswith("session_")
        assert session_id in service.active_sessions
        
        session = service.active_sessions[session_id]
        assert session.symbols == symbols
        assert session.status == "active"
    
    @pytest.mark.asyncio
    async def test_comprehensive_market_scan(self, service, mock_market_analysis, mock_recommendation):
        """测试综合市场扫描"""
        symbols = ["BTCUSDT", "ETHUSDT"]
        
        # Mock服务方法
        with patch.object(service.decision_service, 'analyze_market', new_callable=AsyncMock) as mock_analyze, \
             patch.object(service.decision_service, 'get_trading_recommendation', new_callable=AsyncMock) as mock_recommend, \
             patch.object(service.notification_service, 'send_trading_recommendation', new_callable=AsyncMock) as mock_notify:
            
            mock_analyze.return_value = mock_market_analysis
            mock_recommend.return_value = mock_recommendation
            mock_notify.return_value = {"feishu": True}
            
            result = await service.comprehensive_market_scan(
                symbols=symbols,
                account_balance=10000,
                send_notifications=True
            )
            
            assert "scan_results" in result
            assert "market_summary" in result
            assert result["market_summary"]["total_symbols"] == len(symbols)
            assert result["market_summary"]["strong_buy_signals"] >= 0
    
    @pytest.mark.asyncio
    async def test_portfolio_analysis(self, service, mock_market_analysis, mock_recommendation):
        """测试投资组合分析"""
        positions = {"BTCUSDT": 3000, "ETHUSDT": 2000}
        account_balance = 10000
        
        with patch.object(service.decision_service, 'analyze_market', new_callable=AsyncMock) as mock_analyze, \
             patch.object(service.decision_service, 'get_trading_recommendation', new_callable=AsyncMock) as mock_recommend:
            
            mock_analyze.return_value = mock_market_analysis
            mock_recommend.return_value = mock_recommendation
            
            result = await service.portfolio_analysis(positions, account_balance)
            
            assert "portfolio_metrics" in result
            assert "position_analyses" in result
            assert "portfolio_recommendations" in result
            assert "risk_assessment" in result
            
            # 检查投资组合指标
            metrics = result["portfolio_metrics"]
            assert metrics["total_positions"] == len(positions)
            assert metrics["total_value"] == sum(positions.values())
            assert 0 <= metrics["account_utilization"] <= 100
    
    @pytest.mark.asyncio
    async def test_real_time_monitoring(self, service):
        """测试实时监控"""
        symbols = ["BTCUSDT"]
        monitoring_config = {
            "interval_minutes": 1,  # 短间隔用于测试
            "alert_thresholds": {
                "high_volatility_threshold": 85
            }
        }
        
        with patch.object(service.scheduler_service, 'add_job') as mock_add_job:
            task_id = await service.real_time_monitoring(symbols, monitoring_config)
            
            assert task_id.startswith("monitor_")
            mock_add_job.assert_called_once()
    
    def test_calculate_position_risk(self, service, mock_market_analysis, mock_recommendation):
        """测试仓位风险计算"""
        position_weight = 0.3  # 30%仓位
        
        risk_score = service._calculate_position_risk(
            mock_market_analysis, mock_recommendation, position_weight
        )
        
        assert 0 <= risk_score <= 1
        assert isinstance(risk_score, float)
    
    def test_calculate_portfolio_metrics(self, service):
        """测试投资组合指标计算"""
        positions = {"BTCUSDT": 3000, "ETHUSDT": 2000}
        position_analyses = {
            "BTCUSDT": {
                "market_analysis": {"volatility_score": 60},
                "current_recommendation": {"risk_level": "medium"}
            },
            "ETHUSDT": {
                "market_analysis": {"volatility_score": 70},
                "current_recommendation": {"risk_level": "low"}
            }
        }
        account_balance = 10000
        total_risk_score = 0.4
        
        metrics = service._calculate_portfolio_metrics(
            positions, position_analyses, account_balance, total_risk_score
        )
        
        assert metrics["total_positions"] == 2
        assert metrics["total_value"] == 5000
        assert metrics["account_utilization"] == 50.0
        assert metrics["cash_reserve"] == 5000
        assert metrics["position_concentration"] == 60.0  # 3000/5000 * 100
    
    def test_generate_portfolio_recommendations(self, service):
        """测试投资组合建议生成"""
        metrics = {
            "cash_reserve_percent": 5,  # 现金储备不足
            "position_concentration": 45,  # 仓位集中度过高
            "high_risk_ratio": 35,  # 高风险仓位占比过高
            "average_volatility": 75  # 平均波动性较高
        }
        position_analyses = {}
        
        recommendations = service._generate_portfolio_recommendations(metrics, position_analyses)
        
        assert len(recommendations) > 0
        assert any("现金储备不足" in rec for rec in recommendations)
        assert any("过于集中" in rec for rec in recommendations)
        assert any("高风险仓位占比过高" in rec for rec in recommendations)
        assert any("波动性较高" in rec for rec in recommendations)
    
    def test_get_risk_level_from_score(self, service):
        """测试风险等级评估"""
        assert service._get_risk_level_from_score(0.9) == "very_high"
        assert service._get_risk_level_from_score(0.7) == "high"
        assert service._get_risk_level_from_score(0.5) == "medium"
        assert service._get_risk_level_from_score(0.3) == "low"
        assert service._get_risk_level_from_score(0.1) == "very_low"
    
    def test_check_alert_conditions(self, service):
        """测试警报条件检查"""
        scan_results = {
            "scan_results": {
                "BTCUSDT": {
                    "analysis": {"volatility_score": 90},
                    "recommendation": {
                        "confidence": 88,
                        "action": "strong_buy",
                        "risk_level": "high"
                    }
                },
                "ETHUSDT": {
                    "analysis": {"volatility_score": 50},
                    "recommendation": {
                        "confidence": 60,
                        "action": "hold",
                        "risk_level": "low"
                    }
                }
            }
        }
        
        alert_thresholds = {
            "high_volatility_threshold": 85,
            "strong_signal_confidence_threshold": 85,
            "risk_level_alert": ["high", "very_high"]
        }
        
        alerts = service._check_alert_conditions(scan_results, alert_thresholds)
        
        # BTCUSDT应该触发所有三种警报
        btc_alerts = [alert for alert in alerts if alert["symbol"] == "BTCUSDT"]
        assert len(btc_alerts) == 3  # 高波动性、强信号、高风险
        
        # ETHUSDT不应该触发任何警报
        eth_alerts = [alert for alert in alerts if alert["symbol"] == "ETHUSDT"]
        assert len(eth_alerts) == 0
    
    @pytest.mark.asyncio
    async def test_stop_trading_session(self, service):
        """测试停止交易会话"""
        # 先启动一个会话
        symbols = ["BTCUSDT"]
        session_id = await service.start_trading_session(symbols)
        
        # 停止会话
        with patch.object(service.scheduler_service, 'remove_job'):
            summary = await service.stop_trading_session(session_id)
            
            assert summary["session_id"] == session_id
            assert "duration_hours" in summary
            assert summary["symbols_analyzed"] == len(symbols)
            assert session_id not in service.active_sessions
    
    def test_get_session_status(self, service):
        """测试获取会话状态"""
        # 测试不存在的会话
        status = service.get_session_status("nonexistent")
        assert "error" in status
        
        # 测试存在的会话需要先创建会话
        # 这里简化测试，直接创建会话对象
        from app.services.comprehensive_trading_service import TradingSession
        session = TradingSession(
            session_id="test_session",
            symbols=["BTCUSDT"],
            start_time=datetime.now(),
            end_time=None,
            total_analyses=5,
            successful_analyses=4,
            recommendations_sent=2,
            alerts_sent=1,
            status="active"
        )
        service.active_sessions["test_session"] = session
        
        status = service.get_session_status("test_session")
        assert status["session_id"] == "test_session"
        assert status["status"] == "active"
        assert status["total_analyses"] == 5
        assert status["successful_analyses"] == 4


class TestComprehensiveTradingAPI:
    """综合交易策略API测试"""
    
    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        from fastapi.testclient import TestClient
        from main import create_app
        
        app = create_app()
        return TestClient(app)
    
    def test_start_trading_session_api(self, client):
        """测试启动交易会话API"""
        with patch('app.api.comprehensive_trading.comprehensive_service') as mock_service:
            mock_service.start_trading_session = AsyncMock(return_value="session_123")
            
            response = client.post("/api/comprehensive/session/start", json={
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "session_config": {"auto_analysis": True}
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "session_id" in data
    
    def test_market_scan_api(self, client):
        """测试市场扫描API"""
        mock_scan_result = {
            "scan_results": {"BTCUSDT": {"analysis": {}, "recommendation": {}}},
            "market_summary": {"total_symbols": 1, "successful_analyses": 1},
            "scan_duration_seconds": 1.5,
            "timestamp": datetime.now()
        }
        
        with patch('app.api.comprehensive_trading.comprehensive_service') as mock_service:
            mock_service.comprehensive_market_scan = AsyncMock(return_value=mock_scan_result)
            
            response = client.post("/api/comprehensive/market-scan", json={
                "symbols": ["BTCUSDT"],
                "account_balance": 10000,
                "send_notifications": False
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "scan_results" in data
            assert "market_summary" in data
    
    def test_portfolio_analysis_api(self, client):
        """测试投资组合分析API"""
        mock_analysis_result = {
            "portfolio_metrics": {"total_positions": 2},
            "position_analyses": {},
            "portfolio_recommendations": [],
            "risk_assessment": {"overall_risk_score": 0.3},
            "analysis_duration_seconds": 2.0,
            "timestamp": datetime.now()
        }
        
        with patch('app.api.comprehensive_trading.comprehensive_service') as mock_service:
            mock_service.portfolio_analysis = AsyncMock(return_value=mock_analysis_result)
            
            response = client.post("/api/comprehensive/portfolio/analyze", json={
                "positions": {"BTCUSDT": 3000, "ETHUSDT": 2000},
                "account_balance": 10000
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "portfolio_metrics" in data
            assert "risk_assessment" in data
    
    def test_quick_analysis_api(self, client):
        """测试快速分析API"""
        mock_scan_result = {
            "scan_results": {
                "BTCUSDT": {
                    "recommendation": {
                        "action": "buy",
                        "confidence": 75,
                        "risk_level": "medium"
                    },
                    "analysis": {
                        "market_regime": "trending",
                        "volatility_score": 60
                    }
                }
            },
            "market_summary": {},
            "scan_duration_seconds": 1.0
        }
        
        with patch('app.api.comprehensive_trading.comprehensive_service') as mock_service:
            mock_service.comprehensive_market_scan = AsyncMock(return_value=mock_scan_result)
            
            response = client.post("/api/comprehensive/quick-analysis", json={
                "symbols": ["BTCUSDT"],
                "analysis_type": "comprehensive",
                "send_notifications": False
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "results" in data["data"]
            assert "BTCUSDT" in data["data"]["results"]


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])