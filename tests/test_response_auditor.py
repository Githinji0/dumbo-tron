import pytest
from brain_farm.app.services.response_auditor import ResponseStructureAuditor

def test_1_complete_with_valid_metrics():
    """Scenario 1: Remote status COMPLETE with valid metrics dictionary in response['is']."""
    response = {
        "status": "COMPLETE",
        "alpha": "alpha-valid-101",
        "longCount": 150,
        "shortCount": 140,
        "is": {
            "sharpe": 1.75,
            "fitness": 1.45,
            "turnover": 0.32,
            "returns": 0.18,
            "margin": 6.2,
            "drawdown": 0.08
        }
    }
    audit = ResponseStructureAuditor.audit(response, http_status=200)
    assert audit["remote_status"] == "COMPLETE"
    assert audit["portfolio_status"] == "PORTFOLIO_AVAILABLE"
    assert audit["metrics_status"] == "METRICS_AVAILABLE"
    assert audit["evaluation_status"] == "EVALUATED"
    assert audit["parser_path_used"] == "response['is']"
    assert audit["has_trades"] is True
    assert audit["extracted_metrics"]["sharpe"] == 1.75
    assert audit["extracted_metrics"]["fitness"] == 1.45
    assert audit["extracted_metrics"]["turnover"] == 0.32
    assert audit["failure_reason"] is None


def test_2_complete_with_empty_is():
    """Scenario 2: Remote status COMPLETE with empty IS block {}. Must be TECHNICAL_FAILURE."""
    response = {
        "status": "COMPLETE",
        "alpha": "qMNb9vv",
        "is": {}
    }
    audit = ResponseStructureAuditor.audit(
        response, 
        http_status=200, 
        expression_text="group_neutralize(rank(ts_mean(debt, 10) / ts_mean(debt, 5) - 1), subindustry)"
    )
    assert audit["remote_status"] == "COMPLETE"
    assert audit["portfolio_status"] == "PORTFOLIO_EMPTY"
    assert audit["metrics_status"] == "METRICS_MISSING"
    assert audit["evaluation_status"] == "TECHNICAL_FAILURE"
    assert audit["parser_path_used"] == "NONE"
    assert audit["extracted_metrics"] is None
    assert "in-sample (IS) portfolio dictionary is empty or null" in audit["failure_reason"]


def test_3_complete_with_empty_portfolio_null_is():
    """Scenario 3: Remote status COMPLETE with is: null and no trades."""
    response = {
        "status": "COMPLETE",
        "alpha": "alpha-empty-002",
        "is": None,
        "longCount": 0,
        "shortCount": 0
    }
    audit = ResponseStructureAuditor.audit(response, http_status=200)
    assert audit["remote_status"] == "COMPLETE"
    assert audit["portfolio_status"] == "PORTFOLIO_EMPTY"
    assert audit["metrics_status"] == "METRICS_MISSING"
    assert audit["evaluation_status"] == "TECHNICAL_FAILURE"
    assert audit["extracted_metrics"] is None


def test_4_complete_with_missing_metrics():
    """Scenario 4: Remote status COMPLETE with partial IS dictionary missing required keys."""
    response = {
        "status": "COMPLETE",
        "alpha": "alpha-partial-003",
        "is": {
            "sharpe": 1.20,
            # missing fitness and turnover
            "returns": 0.05
        }
    }
    audit = ResponseStructureAuditor.audit(response, http_status=200)
    assert audit["remote_status"] == "COMPLETE"
    assert audit["metrics_status"] == "METRICS_MISSING"
    assert audit["evaluation_status"] == "TECHNICAL_FAILURE"
    assert "Missing required keys" in audit["failure_reason"]
    assert audit["extracted_metrics"] is None


def test_5_malformed_response_structure():
    """Scenario 5: Malformed non-dictionary or null response."""
    audit_none = ResponseStructureAuditor.audit(None, http_status=500)
    assert audit_none["evaluation_status"] == "TECHNICAL_FAILURE"
    assert audit_none["metrics_status"] == "METRICS_PARSE_ERROR"

    audit_str = ResponseStructureAuditor.audit("Internal Server Error", http_status=502)
    assert audit_str["evaluation_status"] == "TECHNICAL_FAILURE"
    assert audit_str["metrics_status"] == "METRICS_PARSE_ERROR"


def test_6_parser_alternative_location_fallback():
    """Scenario 6: Metrics located in alternative valid path response['stats']."""
    response = {
        "status": "COMPLETE",
        "alpha": "alpha-stats-004",
        "stats": {
            "sharpe": 2.10,
            "fitness": 1.80,
            "turnover": 0.25,
            "returns": 0.22,
            "margin": 7.5
        }
    }
    audit = ResponseStructureAuditor.audit(response, http_status=200)
    assert audit["metrics_status"] == "METRICS_AVAILABLE"
    assert audit["evaluation_status"] == "EVALUATED"
    assert audit["parser_path_used"] == "response['stats']"
    assert audit["extracted_metrics"]["sharpe"] == 2.10
    assert audit["extracted_metrics"]["fitness"] == 1.80


def test_7_simulation_failure_error_status():
    """Scenario 7: Remote status ERROR or FAILED."""
    response = {
        "status": "ERROR",
        "message": "Syntax error in expression at character 12"
    }
    audit = ResponseStructureAuditor.audit(response, http_status=200)
    assert audit["remote_status"] == "ERROR"
    assert audit["evaluation_status"] == "TECHNICAL_FAILURE"
    assert audit["portfolio_status"] == "NOT_APPLICABLE"
    assert audit["metrics_status"] == "NOT_APPLICABLE"
    assert "Syntax error" in audit["failure_reason"]
    assert audit["extracted_metrics"] is None


def test_8_valid_zero_valued_metric():
    """Scenario 8: True empirical zero-valued metrics (Sharpe: 0.0) must be parsed as float 0.0."""
    response = {
        "status": "COMPLETE",
        "alpha": "alpha-zero-perf-005",
        "longCount": 100,
        "shortCount": 100,
        "is": {
            "sharpe": 0.0,
            "fitness": 0.0,
            "turnover": 0.50,
            "returns": 0.0,
            "margin": 0.0
        }
    }
    audit = ResponseStructureAuditor.audit(response, http_status=200)
    assert audit["remote_status"] == "COMPLETE"
    assert audit["metrics_status"] == "METRICS_AVAILABLE"
    assert audit["evaluation_status"] == "EVALUATED"
    assert audit["extracted_metrics"]["sharpe"] == 0.0
    assert audit["extracted_metrics"]["fitness"] == 0.0
    assert audit["extracted_metrics"]["turnover"] == 0.50
    assert isinstance(audit["extracted_metrics"]["sharpe"], float)


def test_9_missing_metric_distinction_and_sanitization():
    """Scenario 9: Missing metric (None != 0.0) and sensitive credentials sanitization."""
    response = {
        "status": "COMPLETE",
        "alpha": "alpha-sec-006",
        "token": "secret_session_token_12345",
        "authorization": "Bearer xyz-token",
        "is": None
    }
    audit = ResponseStructureAuditor.audit(response, http_status=200)
    # Ensure credentials are redacted in sanitized response
    assert audit["sanitized_response"]["token"] == "[REDACTED]"
    assert audit["sanitized_response"]["authorization"] == "[REDACTED]"
    
    # Missing metrics must be classified as METRICS_MISSING, NOT converted to 0.0
    assert audit["metrics_status"] == "METRICS_MISSING"
    assert audit["evaluation_status"] == "TECHNICAL_FAILURE"
    assert audit["extracted_metrics"] is None
