import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
from datetime import datetime, timedelta
import logging
from brain_farm.app.services.brain_client import BrainClient

@pytest.mark.asyncio
async def test_auth_success():
    client = BrainClient("user@real.com", "correctpassword", use_mock=False)
    
    mock_response = httpx.Response(
        status_code=201,
        headers={"Set-Cookie": "t=fake_token_cookie"},
        request=httpx.Request("POST", "https://api.worldquantbrain.com/authentication")
    )
    
    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_response
        ok, msg = await client.authenticate_step1()
        assert ok is True
        assert msg == "Live session authenticated successfully!"
        assert client.is_authenticated is True

@pytest.mark.asyncio
async def test_auth_invalid_credentials():
    client = BrainClient("user@real.com", "wrongpassword", use_mock=False)
    
    mock_response = httpx.Response(
        status_code=401,
        content=b'{"detail":"Invalid username/password."}',
        request=httpx.Request("POST", "https://api.worldquantbrain.com/authentication")
    )
    
    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_response
        ok, msg = await client.authenticate_step1()
        assert ok is False
        assert "401" in msg or "invalid" in msg.lower() or "credentials" in msg.lower()
        assert client.is_authenticated is False

@pytest.mark.asyncio
async def test_auth_rate_limiting():
    client = BrainClient("user@real.com", "password", use_mock=False)
    
    mock_response = httpx.Response(
        status_code=429,
        content=b'{"detail":"Too many login attempts."}',
        request=httpx.Request("POST", "https://api.worldquantbrain.com/authentication")
    )
    
    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_response
        ok, msg = await client.authenticate_step1()
        assert ok is False
        assert "429" in msg or "rate" in msg.lower() or "attempts" in msg.lower()

@pytest.mark.asyncio
async def test_auth_network_failure():
    client = BrainClient("user@real.com", "password", use_mock=False)
    
    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = httpx.ConnectTimeout("Connection timed out.")
        ok, msg = await client.authenticate_step1()
        assert ok is False
        assert "timeout" in msg.lower() or "connect" in msg.lower()

@pytest.mark.asyncio
async def test_auth_session_persistence():
    client = BrainClient("user@real.com", "password", use_mock=False)
    
    mock_auth_response = httpx.Response(
        status_code=201,
        headers={"Set-Cookie": "t=my_cookie_jwt"},
        request=httpx.Request("POST", "https://api.worldquantbrain.com/authentication")
    )
    
    mock_fields_response = httpx.Response(
        status_code=200,
        json={"count": 1, "results": [{"id": "close", "name": "Close Price"}]},
        request=httpx.Request("GET", "https://api.worldquantbrain.com/data-fields")
    )
    
    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = [mock_auth_response, mock_fields_response]
        
        ok, msg = await client.authenticate_step1()
        assert ok is True
        
        res = await client.get_data_fields(limit=1)
        assert res["count"] == 1
        assert res["results"][0]["id"] == "close"

@pytest.mark.asyncio
async def test_auth_no_credential_leak(caplog):
    logger = logging.getLogger("brain_farm.app.services.brain_client")
    logger.setLevel(logging.DEBUG)
    
    client = BrainClient("secret_email@leakcheck.com", "my_super_secret_password_12345", use_mock=False)
    
    mock_response = httpx.Response(
        status_code=401,
        content=b'{"detail":"Unauthorized"}',
        request=httpx.Request("POST", "https://api.worldquantbrain.com/authentication")
    )
    
    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_response
        
        with caplog.at_level(logging.DEBUG):
            await client.authenticate_step1()
            
        logs_text = caplog.text
        assert "my_super_secret_password_12345" not in logs_text
        assert "Authorization" not in logs_text
        assert "t=" not in logs_text
