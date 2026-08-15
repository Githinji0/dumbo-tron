"""
Comprehensive unit and regression tests for SignalPreflight and StructuralDedup.
"""
import pytest
from brain_farm.app.services.signal_preflight import (
    SignalPreflight,
    PreflightDecision,
    ConstantSignalRisk
)
from brain_farm.app.services.structural_dedup import StructuralDedup


def test_preflight_valid_fast_expression():
    expr = "group_neutralize(ts_decay_linear(rank(close) / rank(ts_mean(close, 20)), 20), subindustry)"
    report = SignalPreflight.evaluate(expr, family="MOMENTUM")
    
    assert report["decision"] == PreflightDecision.PASS
    assert report["constant_signal_risk"] == ConstantSignalRisk.LOW
    assert report["compatibility_score"] >= 0.70
    assert "close" in report["expression"]


def test_preflight_problematic_slow_fundamental_candidate():
    # Specific problematic candidate: group_neutralize(rank(ts_mean(capex, 10) / ts_mean(capex, 30) - 1), subindustry)
    expr = "group_neutralize(rank(ts_mean(capex, 10) / ts_mean(capex, 30) - 1), subindustry)"
    report = SignalPreflight.evaluate(expr, family="VALUE")
    
    assert report["decision"] in (PreflightDecision.REJECT, PreflightDecision.REGENERATE)
    assert report["constant_signal_risk"] == ConstantSignalRisk.HIGH
    assert "capex" in report["expression"]
    assert "quarterly" in report["reason"].lower() or "ratio" in report["reason"].lower() or "variation" in report["reason"].lower()


def test_preflight_tautological_constant():
    # Tautological identity: close / close - 1 -> constant 0.0
    expr = "rank(close / close - 1)"
    report = SignalPreflight.evaluate(expr)
    assert report["decision"] in (PreflightDecision.REJECT, PreflightDecision.REGENERATE)
    assert report["constant_signal_risk"] == ConstantSignalRisk.HIGH


def test_preflight_syntax_error():
    expr = "group_neutralize(rank(close), subindustry"  # Missing closing paren
    report = SignalPreflight.evaluate(expr)
    assert report["decision"] == PreflightDecision.REJECT
    assert "syntax error" in report["reason"].lower() or "unbalanced" in report["reason"].lower() or "parentheses" in report["reason"].lower()


def test_preflight_duplicate_detection():
    expr1 = "rank(ts_delta(close, 10))"
    expr2 = "rank(ts_delta(close, 10))"
    
    hash1 = StructuralDedup.compute_expression_hash(expr1)
    report = SignalPreflight.evaluate(expr2, existing_hashes=[hash1])
    
    assert report["decision"] == PreflightDecision.REJECT
    assert report["duplicate_risk"] == "EXACT_DUPLICATE"


def test_structural_hash_equivalence():
    # Two expressions with identical structural skeleton: OP(VAR, INT)
    expr_a = "rank(ts_delta(close, 10))"
    expr_b = "rank(ts_delta(open, 10))"
    
    struct_a = StructuralDedup.compute_structure_hash(expr_a)
    struct_b = StructuralDedup.compute_structure_hash(expr_b)
    assert struct_a == struct_b


def test_lineage_metadata_construction():
    parent_expr = "rank(book_value / close)"
    child_expr = "group_neutralize(rank(book_value / close), subindustry)"
    
    lineage = StructuralDedup.build_lineage_metadata(
        current_expr=child_expr,
        parent_expr=parent_expr,
        parent_candidate_id=42,
        mutation_type="NEUTRALIZATION_WRAP",
        hypothesis="Value anomaly relative to subindustry peers"
    )
    
    assert lineage["parent_candidate_id"] == 42
    assert lineage["mutation_type"] == "NEUTRALIZATION_WRAP"
    assert lineage["expression_hash"] is not None
    assert lineage["structure_hash"] is not None
