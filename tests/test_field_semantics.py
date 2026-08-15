"""
Unit tests for Field and Operator Semantic Metadata Registry.
"""
import pytest
from brain_farm.app.services.field_semantics import (
    FieldSemantics,
    FieldCategory,
    TemporalBehavior,
    OperatorType
)


def test_field_metadata_retrieval():
    close_info = FieldSemantics.get_field_info("close")
    assert close_info["category"] == FieldCategory.PRICE
    assert close_info["temporal_behavior"] == TemporalBehavior.FAST

    capex_info = FieldSemantics.get_field_info("capex")
    assert capex_info["category"] == FieldCategory.FUNDAMENTAL
    assert capex_info["temporal_behavior"] == TemporalBehavior.SLOW

    debt_info = FieldSemantics.get_field_info("debt")
    assert debt_info["category"] == FieldCategory.FUNDAMENTAL
    assert debt_info["temporal_behavior"] == TemporalBehavior.SLOW

    unknown_info = FieldSemantics.get_field_info("custom_alpha_var")
    assert unknown_info["category"] == FieldCategory.UNKNOWN
    assert unknown_info["temporal_behavior"] == TemporalBehavior.UNKNOWN


def test_operator_metadata_retrieval():
    ts_mean_info = FieldSemantics.get_operator_info("ts_mean")
    assert ts_mean_info["type"] == OperatorType.TIME_SERIES
    assert ts_mean_info["requires_temporal_variation"] is True

    rank_info = FieldSemantics.get_operator_info("rank")
    assert rank_info["type"] == OperatorType.CROSS_SECTIONAL
    assert rank_info["requires_cross_sectional_variation"] is True

    gn_info = FieldSemantics.get_operator_info("group_neutralize")
    assert gn_info["type"] == OperatorType.GROUP_TRANSFORMATION


def test_compatibility_fast_field():
    # Fast market field + standard time-series operator -> High compatibility score
    score, warnings = FieldSemantics.evaluate_compatibility(
        fields=["close", "volume"],
        operators=["ts_decay_linear", "rank"],
        lookbacks=[20],
        family="MOMENTUM"
    )
    assert score >= 0.80
    assert len(warnings) == 0


def test_compatibility_slow_field_short_lookback():
    # Slow fundamental field + short lookback (<20d) -> Low compatibility score
    score, warnings = FieldSemantics.evaluate_compatibility(
        fields=["capex"],
        operators=["ts_mean", "rank"],
        lookbacks=[10],
        family="VALUE"
    )
    assert score <= 0.50
    assert any("short lookback window" in w for w in warnings)
