import pytest
import asyncio
from brain_farm.app.services.brain_client import BrainClient

@pytest.mark.asyncio
async def test_mock_client_auth():
    # Force MockMode by email host
    client = BrainClient("user@mock.com", "any_password")
    
    # Authenticate
    ok, msg = await client.authenticate()
    assert ok is True
    assert client.is_authenticated is True
    assert "Mock Session" in msg

@pytest.mark.asyncio
async def test_mock_client_failed_auth():
    client = BrainClient("failed_auth@mock.com", "any_password")
    # In mock, "fail" in email triggers auth failure
    client.email = "fail@mock.com"
    ok, msg = await client.authenticate()
    assert ok is False
    assert "Auth failed" in msg

@pytest.mark.asyncio
async def test_mock_client_fields():
    client = BrainClient("user@mock.com", "", use_mock=True)
    await client.authenticate()
    
    fields_data = await client.get_data_fields(limit=5)
    assert fields_data["count"] > 0
    assert len(fields_data["results"]) == 5
    assert fields_data["results"][0]["id"] == "close"

@pytest.mark.asyncio
async def test_mock_simulation_polling():
    client = BrainClient("user@mock.com", "", use_mock=True)
    await client.authenticate()
    
    expr = "group_neutralize(rank(close), subindustry)"
    sim_id, err = await client.submit_simulation(expr, {"region": "USA", "universe": "TOP3000"})
    assert err is None
    assert sim_id is not None
    
    # Fast manual time forward simulation
    # Mock status moves from QUEUED to RUNNING to COMPLETE on timer.
    # In order to test this without waiting 5 seconds, we can modify the mock simulation created_at time
    mock_sim = client._mock_simulations[sim_id]
    assert mock_sim["status"] == "QUEUED"
    
    # Backdate simulated submit
    mock_sim["created_at"] -= 6.0  # more than 5s
    
    data, err = await client.get_simulation_status(sim_id)
    assert err is None
    assert data is not None
    assert data["status"] == "COMPLETE"
    assert "is" in data
    assert data["is"]["sharpe"] != 0.0
