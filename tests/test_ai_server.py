import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from brain_farm.app.server import app
from brain_farm.app.ai.manager import ai_manager, AIProviderState

client = TestClient(app)

def test_ai_status_endpoint_initial():
    # Force unconfigured state
    ai_manager._encrypted_key = None
    ai_manager.state = AIProviderState.NOT_CONFIGURED
    
    response = client.get("/api/ai/status")
    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is False
    assert data["valid"] is False
    assert "provider" in data
    assert "available_providers" in data
    assert "openai" in data["available_providers"]
    assert "gemini" in data["available_providers"]
    # Check that no sensitive key is returned
    assert "encrypted_api_key" not in data
    assert "api_key" not in data

def test_ai_config_endpoint_save_no_leak():
    payload = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "sk-mocktest12345678901234567890abcdef",
        "is_enabled": True,
        "features": {
            "hypothesis": True,
            "failure_analysis": True,
            "near_miss": True,
            "turnover_opt": True,
            "director": True,
            "critic": True,
            "summary": True
        }
    }
    response = client.post("/api/ai/config", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    status = data["status"]
    assert status["provider"] == "openai"
    assert status["configured"] is True
    # Ensure plaintext key NEVER in response
    assert "sk-mocktest" not in str(data)
    assert "api_key" not in status

def test_ai_validate_endpoint_mock():
    with patch.object(ai_manager, "validate_active_provider", return_value=(True, "Validated successfully")):
        response = client.post("/api/ai/validate")
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert "message" in data
        assert "api_key" not in data

def test_ai_usage_endpoint():
    response = client.get("/api/ai/usage")
    assert response.status_code == 200
    data = response.json()
    assert "daily_calls" in data
    assert "monthly_calls" in data
    assert "estimated_cost_usd" in data
    assert "feature_calls" in data
    assert "daily_budget_limit" in data

def test_ai_chat_endpoint_fallback():
    # When disabled
    ai_manager.features["enabled"] = False
    response = client.post("/api/ai/chat", json={"message": "Suggest a value formula"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "unavailable" in data["error"].lower()
    
    # Re-enable
    ai_manager.features["enabled"] = True
