import pytest
from brain_farm.app.services.correlation_filter import CorrelationFilter

def test_ast_similarity_identical():
    expr = "ts_zscore(close, 20)"
    sim = CorrelationFilter.calculate_ast_similarity(expr, expr)
    assert sim == 1.0

def test_ast_similarity_partial():
    expr1 = "ts_zscore(close, 20)"
    expr2 = "ts_zscore(open, 20)"
    sim = CorrelationFilter.calculate_ast_similarity(expr1, expr2)
    # Both have "ts_zscore" and "20". e1 has "close" (3 tokens), e2 has "open" (3 tokens)
    # Intersection = {"ts_zscore", "20"}, Union = {"ts_zscore", "20", "close", "open"}
    # Jaccard = 2/4 = 0.5
    assert sim == 0.5

def test_synthetic_signal_shape():
    expr = "group_neutralize(ts_decay_linear(rank(close), 10), subindustry)"
    sig = CorrelationFilter.generate_synthetic_signal(expr, length=100)
    assert len(sig) == 100
    # neutralise subtracts the mean, so signal mean should be close to 0
    assert abs(sig.mean()) < 1e-12

def test_correlation_value():
    expr1 = "close"
    expr2 = "close"
    corr = CorrelationFilter.calculate_correlation(expr1, expr2)
    assert corr == pytest.approx(1.0)
