import pytest
from brain_farm.app.services.sensitivity import ParameterSensitivityTester
from brain_farm.app.services.composite_scorer import WeightedCompositeScorer

def test_extract_lookbacks():
    expr = "ts_zscore(close, 20) + ts_std(open, 10)"
    lookbacks = ParameterSensitivityTester.extract_lookbacks(expr)
    
    assert len(lookbacks) == 2
    assert lookbacks[0][1] == 20
    assert lookbacks[1][1] == 10
    
    # Test text without lookbacks
    expr_none = "close + open"
    assert len(ParameterSensitivityTester.extract_lookbacks(expr_none)) == 0


def test_generate_perturbed_expressions():
    expr = "ts_zscore(close, 10)"
    perturbed = ParameterSensitivityTester.generate_perturbed_expressions(expr)
    
    # Should perturbed 10 to 8 and 12
    assert "ts_zscore(close, 8)" in perturbed
    assert "ts_zscore(close, 12)" in perturbed


def test_evaluate_sensitivity_penalty():
    expr = "ts_zscore(close, 10)"
    penalty = ParameterSensitivityTester.evaluate_sensitivity_penalty(expr, 1.5)
    
    # Standard lookback should yield high correlation to perturbed versions, resulting in 1.0 (no penalty)
    assert 0.5 <= penalty <= 1.0
    
    # No lookbacks should yield penalty of 1.0 (no lookbacks, no penalty)
    expr_none = "close + open"
    assert ParameterSensitivityTester.evaluate_sensitivity_penalty(expr_none, 1.5) == 1.0
