import pytest
from fastapi.testclient import TestClient
from brain_farm.app.server import app

client = TestClient(app)

def test_root_redirect():
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/static/index.html"

def test_auth_status_unauthenticated():
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is False
    assert data["username"] == ""

def test_auth_login_mock():
    # Login in sandbox mock mode should proceed and return success without OTP
    payload = {
        "email": "testuser@mock.com",
        "password": "mockpassword",
        "use_mock": True
    }
    response = client.post("/api/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["otp_pending"] is False
    assert data["username"] == "testuser@mock.com"
    assert "user_id" in data
    
    # Store cookies to check status and create projects
    cookies = response.cookies
    
    # Check status with cookie
    status_response = client.get("/api/auth/status", cookies=cookies)
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["authenticated"] is True
    assert status_data["username"] == "testuser@mock.com"
    
    # Create project
    proj_payload = {
        "name": "Test Integration Project",
        "description": "Integration test description",
        "region": "USA",
        "universe": "TOP3000",
        "neutralization": "SUBINDUSTRY"
    }
    proj_response = client.post("/api/projects", json=proj_payload, cookies=cookies)
    assert proj_response.status_code == 200
    proj_data = proj_response.json()
    assert proj_data["success"] is True
    assert "project_id" in proj_data
    
    # Get projects list
    list_response = client.get("/api/projects", cookies=cookies)
    assert list_response.status_code == 200
    list_data = list_response.json()
    assert len(list_data) >= 1
    assert any(p["name"] == "Test Integration Project" for p in list_data)

def test_get_fields_catalog():
    response = client.get("/api/fields")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    # Check close field default exists
    assert any(f["id"] == "close" for f in data)

def test_favorite_field_toggle():
    # Since we can query fields and toggle favorite state:
    response = client.post("/api/fields/toggle-favorite", json={"field_id": "close"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "is_favorite" in data
