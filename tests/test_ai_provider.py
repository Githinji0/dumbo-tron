import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from brain_farm.app.ai.provider import AIProviderState
from brain_farm.app.ai.openai_provider import OpenAIProvider
from brain_farm.app.ai.gemini_provider import GeminiProvider
from brain_farm.app.ai.manager import AIManager
from brain_farm.app.ai.security import redact_sensitive_text
from brain_farm.app.ai.schemas import ResearchHypothesis, FailureAnalysis, NearMissProposal

def test_redact_sensitive_text():
    raw = "Bearer sk-proj-1234567890abcdefghijklm with password='supersecret' and cookie: session=xyz123456789"
    redacted = redact_sensitive_text(raw)
    assert "sk-proj" not in redacted
    assert "supersecret" not in redacted
    assert "xyz123456789" not in redacted
    assert "[REDACTED" in redacted

def test_schemas_validation():
    # Research Hypothesis
    hypo = ResearchHypothesis(
        family="VALUE",
        hypothesis="Medium-term valuation signals provide more cross-sectional stability.",
        horizon="MEDIUM",
        preferred_fields=["close", "volume"],
        suggested_transformations=["rank", "ts_decay_linear"],
        priority=0.85
    )
    assert hypo.family == "VALUE"
    assert hypo.priority == 0.85
    
    # Failure Analysis
    fail = FailureAnalysis(
        classification="WEAK_SIGNAL",
        likely_issue="Noise ratio too high for short-term horizon",
        recommended_action="TUNE_HORIZON",
        recommended_families=["QUALITY", "VALUE"]
    )
    assert fail.classification == "WEAK_SIGNAL"
    assert "QUALITY" in fail.recommended_families

@pytest.mark.asyncio
async def test_ai_manager_no_key_mode():
    mgr = AIManager()
    # Force no key
    mgr._encrypted_key = None
    mgr.state = AIProviderState.NOT_CONFIGURED
    
    assert mgr.is_available() is False
    status = mgr.get_safe_status()
    assert status["configured"] is False
    assert status["valid"] is False
    assert status["state"] == "AI_NOT_CONFIGURED"
    
    # Fallback execution
    data, err = await mgr.execute_structured_request("hypothesis", "Generate hypothesis")
    assert data is None
    assert "unavailable" in err.lower()

@pytest.mark.asyncio
async def test_openai_validation_mock_success():
    provider = OpenAIProvider()
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        
        is_valid, msg, meta = await provider.validate_key("sk-validkey12345678901234567890")
        assert is_valid is True
        assert "verified" in msg.lower()

@pytest.mark.asyncio
async def test_openai_validation_mock_failure():
    provider = OpenAIProvider()
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp
        
        is_valid, msg, meta = await provider.validate_key("sk-invalidkey12345678901234567890")
        assert is_valid is False
        assert "rejected" in msg.lower()

@pytest.mark.asyncio
async def test_gemini_generation_mock_success():
    provider = GeminiProvider()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": '{"family": "VALUE", "hypothesis": "Test hypothesis", "priority": 0.9}'}]
                }
            }],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20, "totalTokenCount": 30}
        }
        mock_post.return_value = mock_resp
        
        data, err, usage = await provider.generate_json("fake-gemini-key", "Test prompt")
        assert err is None
        assert data["family"] == "VALUE"
        assert data["priority"] == 0.9
        assert usage["total_tokens"] == 30
