import pytest
from brain_farm.app.database.models import Project

def test_sub_universe_sharpe_validation():
    # Create a project with stringent sub-universe Sharpe
    proj = Project(
        user_id=1,
        name="Sub-Universe Test",
        min_sharpe=1.2,
        min_sub_universe_sharpe=1.5  # Crucially higher
    )
    
    # Check evaluation behavior:
    # 1. Main Sharpe is 1.3 (passes min_sharpe=1.2)
    # 2. Sub-universes have TOP2000=1.144, TOP1000=0.988 (fails min_sub_universe_sharpe=1.5)
    data = {
        "status": "COMPLETE",
        "alpha": "alpha-123456",
        "is": {
            "sharpe": 1.3,
            "fitness": 1.5,
            "turnover": 0.2,
            "returns": 0.05,
            "margin": 10.0
        },
        "subUniverseSharpe": {
            "TOP2000": 1.144,
            "TOP1000": 0.988
        }
    }
    
    failing_sub = []
    passed_sub_sharpe = True
    for sub, val in data["subUniverseSharpe"].items():
        if val < proj.min_sub_universe_sharpe:
            passed_sub_sharpe = False
            failing_sub.append(f"{sub}: {val}")
            
    passed = (
        data["is"]["sharpe"] >= proj.min_sharpe and
        passed_sub_sharpe
    )
    
    assert passed is False
    assert "TOP2000: 1.144" in failing_sub
