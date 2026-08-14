import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
from brain_farm.app.server import app
from brain_farm.app.database.session import init_db
from brain_farm.app.ai.manager import ai_manager, AIProviderState

@pytest.mark.asyncio
async def test_mode_a_deterministic_pipeline():
    """Verify Mode A operates 100% deterministically without any AI key."""
    await init_db()
    
    # Force unconfigured
    ai_manager._encrypted_key = None
    ai_manager.state = AIProviderState.NOT_CONFIGURED
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Check status
        status_res = await client.get("/api/ai/status")
        assert status_res.status_code == 200
        assert status_res.json()["configured"] is False
        assert status_res.json()["valid"] is False
        
        # 2. Login mock user
        login_res = await client.post("/api/auth/login", json={
            "email": "deterministic_tester@mock.com",
            "password": "mockpassword",
            "use_mock": True
        })
        assert login_res.status_code == 200
        
        # 3. Create project
        proj_res = await client.post("/api/projects", json={
            "name": "Deterministic Alpha Project",
            "region": "USA",
            "universe": "TOP3000",
            "neutralization": "SUBINDUSTRY"
        })
        assert proj_res.status_code == 200
        proj_id = proj_res.json()["project_id"]
        
        # 4. Generate & queue hypothesis deterministically (fallback)
        hypo_res = await client.post("/api/ai/hypothesis/generate", json={"family": "VALUE"})
        assert hypo_res.status_code == 200
        hypo_data = hypo_res.json()
        assert hypo_data["success"] is True
        assert hypo_data["ai_active"] is False
        assert hypo_data["hypothesis"]["family"] == "VALUE"
        
        # 5. Synthesize and queue to project
        queue_res = await client.post("/api/ai/hypothesis/synthesize-and-queue", json={
            "project_id": proj_id,
            "family": "VALUE",
            "hypothesis_text": hypo_data["hypothesis"]["hypothesis"],
            "count": 3
        })
        assert queue_res.status_code == 200
        q_data = queue_res.json()
        assert q_data["success"] is True
        assert q_data["queued_count"] >= 1
        
        # 6. Check Director plan fallback
        dir_res = await client.get(f"/api/ai/director/plan?project_id={proj_id}")
        assert dir_res.status_code == 200
        dir_data = dir_res.json()
        assert dir_data["success"] is True
        assert "VALUE" in dir_data["plan"]["recommended_allocation"]
        
        # 7. Check Memory endpoint
        mem_res = await client.get(f"/api/ai/memory?project_id={proj_id}")
        assert mem_res.status_code == 200
        assert "memory" in mem_res.json()

@pytest.mark.asyncio
async def test_mode_b_ai_enhanced_pipeline():
    """Verify Mode B activates AI agents when valid AI key is configured."""
    await init_db()
    
    # Configure mock OpenAI provider
    ai_manager.set_credentials("openai", "sk-mockvalidkey12345678901234567890")
    ai_manager.state = AIProviderState.AVAILABLE
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Status confirms Mode B
        status_res = await client.get("/api/ai/status")
        assert status_res.status_code == 200
        assert status_res.json()["configured"] is True
        assert status_res.json()["valid"] is True
        
        # 2. Login
        login_res = await client.post("/api/auth/login", json={
            "email": "ai_tester@mock.com",
            "password": "mockpassword",
            "use_mock": True
        })
        assert login_res.status_code == 200
        
        # 3. Create project
        proj_res = await client.post("/api/projects", json={
            "name": "AI Enhanced Alpha Project",
            "region": "USA",
            "universe": "TOP3000",
            "neutralization": "SUBINDUSTRY"
        })
        assert proj_res.status_code == 200
        proj_id = proj_res.json()["project_id"]
        
        # 4. Mock AI structured response for hypothesis
        mock_hypo_response = {
            "family": "QUALITY",
            "hypothesis": "Operating margin stability predicts superior forward risk-adjusted returns.",
            "horizon": "LONG",
            "preferred_fields": ["close", "volume"],
            "suggested_transformations": ["rank", "ts_decay_linear"],
            "reasoning": "Fundamental quality premium.",
            "priority": 0.92
        }
        
        with patch.object(ai_manager, "execute_structured_request", return_value=(mock_hypo_response, None)):
            hypo_res = await client.post("/api/ai/hypothesis/generate", json={"family": "QUALITY"})
            assert hypo_res.status_code == 200
            data = hypo_res.json()
            assert data["success"] is True
            assert data["hypothesis"]["family"] == "QUALITY"
            assert data["hypothesis"]["priority"] == 0.92
            
            # Queue alphas
            queue_res = await client.post("/api/ai/hypothesis/synthesize-and-queue", json={
                "project_id": proj_id,
                "family": "QUALITY",
                "hypothesis_text": data["hypothesis"]["hypothesis"],
                "count": 3
            })
            assert queue_res.status_code == 200
            assert queue_res.json()["queued_count"] >= 1

        # 5. Critic review
        mock_critic_response = {
            "risk_level": "LOW",
            "overfitting_probability": 0.15,
            "parameter_sensitivity_warning": False,
            "data_mining_bias_warning": False,
            "critique": "Solid economic grounding and parameter stability across sub-universes.",
            "recommendation": "PASS_ROBUST",
            "suggested_stress_tests": ["Sub-industry walkforward"]
        }
        with patch.object(ai_manager, "execute_structured_request", return_value=(mock_critic_response, None)):
            critic_res = await client.post("/api/ai/critic/review", json={
                "expression": "rank(ts_decay_linear(close, 10))",
                "sharpe": 1.45,
                "fitness": 1.20,
                "turnover": 0.35,
                "stability_score": 0.90,
                "robustness_score": 0.88
            })
            assert critic_res.status_code == 200
            c_data = critic_res.json()
            assert c_data["success"] is True
            assert c_data["review"]["risk_level"] == "LOW"
            assert c_data["review"]["recommendation"] == "PASS_ROBUST"

@pytest.mark.asyncio
async def test_ai_provider_error_fallback_resilience():
    """Verify system falls back seamlessly when AI provider errors or times out."""
    ai_manager.set_credentials("openai", "sk-mockkey12345678901234567890")
    ai_manager.state = AIProviderState.AVAILABLE
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Simulate provider timeout error
        with patch.object(ai_manager, "execute_structured_request", return_value=(None, "Connection timeout")):
            res = await client.post("/api/ai/hypothesis/generate", json={"family": "MOMENTUM"})
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            # Heuristic fallback was engaged
            assert data["hypothesis"]["family"] == "MOMENTUM"
            assert len(data["hypothesis"]["preferred_fields"]) > 0
