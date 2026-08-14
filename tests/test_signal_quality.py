import pytest
from brain_farm.app.evaluators.signal_classifier import SignalQualityClassifier, ResearchQualityScorer
from brain_farm.app.evaluators.pre_screen import StatisticalPreScreen

def test_signal_quality_classification():
    # 1. Raw signals
    res1 = SignalQualityClassifier.classify("group_neutralize(vwap, subindustry)")
    assert res1["signal_type"] == "RAW_SIGNAL"
    assert res1["is_naked_neutralization"] is True

    res2 = SignalQualityClassifier.classify("rank(close)")
    assert res2["signal_type"] == "RAW_SIGNAL"

    res3 = SignalQualityClassifier.classify("close")
    assert res3["signal_type"] == "RAW_SIGNAL"

    # 2. Transformed signals
    res4 = SignalQualityClassifier.classify("ts_delta(close, 5)")
    assert res4["signal_type"] == "TRANSFORMED_SIGNAL"

    res5 = SignalQualityClassifier.classify("ts_decay_linear(volume, 10)")
    assert res5["signal_type"] == "TRANSFORMED_SIGNAL"

    # 3. Predictive signals
    res6 = SignalQualityClassifier.classify("group_neutralize(ts_decay_linear(rank(ts_delta(close, 5)), 10), subindustry)")
    assert res6["signal_type"] == "PREDICTIVE_SIGNAL"
    assert res6["has_group_neutralization"] is True
    assert res6["is_naked_neutralization"] is False

    res7 = SignalQualityClassifier.classify("rank(ts_zscore(close, 20))")
    assert res7["signal_type"] == "PREDICTIVE_SIGNAL"


def test_statistical_pre_screen_rejections():
    allowed_fields = ["close", "open", "volume", "vwap", "subindustry", "industry"]

    # Rejection of naked single-field neutralization
    ok, reason = StatisticalPreScreen.pre_screen("group_neutralize(vwap, subindustry)", allowed_fields)
    assert not ok
    assert "naked group neutralization" in reason.lower() or "structurally weak" in reason.lower()

    # Rejection of trivial self-cancelling formula
    ok, reason = StatisticalPreScreen.pre_screen("close - close", allowed_fields)
    assert not ok

    # Acceptance of structured predictive signal
    ok, reason = StatisticalPreScreen.pre_screen("group_neutralize(ts_decay_linear(rank(ts_delta(close, 5)), 10), subindustry)", allowed_fields)
    assert ok


def test_research_quality_scorer():
    expr_naked = "group_neutralize(vwap, subindustry)"
    score_naked = ResearchQualityScorer.compute_score(expr_naked)
    assert score_naked["research_quality_score"] <= 30.0

    expr_predictive = "group_neutralize(ts_decay_linear(rank(ts_delta(close, 5)), 10), subindustry)"
    score_pred = ResearchQualityScorer.compute_score(
        expr_predictive, 
        hypothesis="Momentum decay hypothesis: price acceleration over 5 days decays over 10 days",
        research_family="MOMENTUM"
    )
    assert score_pred["research_quality_score"] >= 80.0
    assert score_pred["signal_type"] == "PREDICTIVE_SIGNAL"
