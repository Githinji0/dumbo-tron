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

def test_brain_health():
    # Health endpoint without active session
    client.cookies.clear()
    response = client.get("/api/brain/health")
    assert response.status_code == 200
    data = response.json()
    assert "reachable" in data
    assert "session_active" in data
    assert data["session_active"] is False

def test_brain_auth_test_mock_success():
    payload = {
        "email": "testuser@mock.com",
        "password": "mockpassword",
        "use_mock": True
    }
    response = client.post("/api/brain/auth/test", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["otp_pending"] is False
    assert data["error_code"] is None

def test_brain_auth_test_mock_failure():
    payload = {
        "email": "fail_user@mock.com",
        "password": "wrongpassword",
        "use_mock": True
    }
    response = client.post("/api/brain/auth/test", json=payload)
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error_code"] == "BRAIN_AUTH_INVALID_CREDENTIALS"

def test_brain_submit_all_registry_no_session():
    response = client.post("/api/passed/submit-all-registry", json={"project_id": 1})
    assert response.status_code == 401  # Session lost/unauthorized

def test_brain_submit_all_registry_mock():
    # Login first
    payload = {
        "email": "testuser@mock.com",
        "password": "mockpassword",
        "use_mock": True
    }
    resp_login = client.post("/api/auth/login", json=payload)
    cookies = resp_login.cookies
    
    # Trigger bulk submission on project 1
    response = client.post("/api/passed/submit-all-registry", json={"project_id": 1}, cookies=cookies)
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "submitted_count" in data

def test_classify_error_string():
    from brain_farm.app.server import classify_error_string
    
    # 1. Syntax Error
    res = classify_error_string('API Error 400: {"regular": {"code": ["Syntax error in expression: unbalanced parentheses"]}}')
    assert res["category"] == "ALPHA_SYNTAX_ERROR"
    assert "Syntax error" in res["detail"]

    # 2. Unknown Field
    res = classify_error_string('API Error 400: {"regular": {"code": ["Unknown field: sector"]}}')
    assert res["category"] == "UNKNOWN_FIELD"

    # 3. Invalid Operator
    res = classify_error_string('API Error 400: {"regular": {"code": ["Invalid operator: sign"]}}')
    assert res["category"] == "INVALID_OPERATOR"

    # 4. Invalid Parameter
    res = classify_error_string('API Error 400: {"regular": {"code": ["Invalid parameter count for ts_mean"]}}')
    assert res["category"] == "INVALID_PARAMETER"

    # 5. Invalid Settings
    res = classify_error_string('API Error 400: {"settings": {"universe": ["Invalid universe specified"]}}')
    assert res["category"] == "INVALID_SETTINGS"

    # 6. Payload Structure error
    res = classify_error_string('API Error 400: {"regular": ["This field is required."]}')
    assert res["category"] == "SIMULATION_PAYLOAD_ERROR"

    # 7. Authentication Error
    res = classify_error_string('API Error 401: Unauthorized session')
    assert res["category"] == "AUTHENTICATION_ERROR"

    # 8. Rate Limit Error
    res = classify_error_string('RATE_LIMIT:15')
    assert res["category"] == "RATE_LIMIT_ERROR"

