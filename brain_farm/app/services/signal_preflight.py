"""
Pre-Simulation Signal Preflight Engine for Dumbo-Tron.

Validates syntax, operator whitelists, field catalog semantics, temporal lookback alignment,
constant-signal risk, structural complexity, and duplicate avoidance BEFORE submission to BRAIN.
"""
from typing import Dict, Any, List, Optional, Tuple
import logging
import re

from brain_farm.app.services.field_semantics import (
    FieldSemantics,
    FieldCategory,
    TemporalBehavior,
    OperatorType
)
from brain_farm.app.services.structural_dedup import StructuralDedup
from brain_farm.app.evaluators.validator import FormulaValidator

logger = logging.getLogger("brain_farm.signal_preflight")


class PreflightDecision:
    PASS = "PASS"
    REJECT = "REJECT"
    REGENERATE = "REGENERATE"


class ConstantSignalRisk:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SignalPreflight:
    """Pre-simulation gatekeeper assessing structural viability and constant-signal risk."""

    PREFLIGHT_MIN_COMPATIBILITY_SCORE = 0.40
    PREFLIGHT_MAX_COMPLEXITY = 8

    @classmethod
    def evaluate(
        cls,
        expression_text: str,
        family: Optional[str] = None,
        existing_hashes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Runs the full preflight assessment on an expression text.
        Returns a comprehensive SignalQualityReport.
        """
        expr_clean = expression_text.strip()
        
        # Stage 1: Basic syntax & bracket validation
        if not FormulaValidator.validate_parentheses(expr_clean):
            return cls._build_report(
                expression=expr_clean,
                decision=PreflightDecision.REJECT,
                reason="Syntax Error: Unbalanced or mismatched parentheses in formula.",
                constant_risk=ConstantSignalRisk.HIGH,
                compatibility=0.0
            )

        # Stage 2: Token extraction
        fields, operators, lookbacks = StructuralDedup.extract_fields_and_operators(expr_clean)
        if not fields:
            return cls._build_report(
                expression=expr_clean,
                decision=PreflightDecision.REJECT,
                reason="No recognized data fields found in formula",
                constant_risk=ConstantSignalRisk.HIGH,
                compatibility=0.0
            )

        # Stage 3: Field semantics & temporal categorization
        field_categories = []
        temporal_behaviors = []
        for f in fields:
            info = FieldSemantics.get_field_info(f)
            field_categories.append(info.get("category", FieldCategory.UNKNOWN))
            temporal_behaviors.append(info.get("temporal_behavior", TemporalBehavior.UNKNOWN))

        # Stage 4: Semantic compatibility scoring
        compat_score, warnings = FieldSemantics.evaluate_compatibility(
            fields=fields,
            operators=operators,
            lookbacks=lookbacks,
            family=family
        )

        # Stage 5: Constant-signal & Low-variation risk detection
        constant_risk, risk_reason = cls._detect_constant_signal_risk(
            expr_clean=expr_clean,
            fields=fields,
            operators=operators,
            lookbacks=lookbacks,
            temporal_behaviors=temporal_behaviors
        )

        # Stage 6: Duplicate detection if hash list provided
        expr_hash = StructuralDedup.compute_expression_hash(expr_clean)
        struct_hash = StructuralDedup.compute_structure_hash(expr_clean)
        duplicate_risk = "LOW"
        if existing_hashes and expr_hash in existing_hashes:
            duplicate_risk = "EXACT_DUPLICATE"

        # Stage 7: Complexity calculation
        complexity = len(operators) + len(fields) + len(lookbacks)

        # Stage 8: Determine Preflight Decision
        decision = PreflightDecision.PASS
        reasons = []

        if duplicate_risk == "EXACT_DUPLICATE":
            decision = PreflightDecision.REJECT
            reasons.append("Exact duplicate of an existing expression in project.")
        elif constant_risk == ConstantSignalRisk.HIGH:
            decision = PreflightDecision.REGENERATE
            reasons.append(risk_reason or "Elevated probability of constant or zero cross-sectional variation.")
        elif compat_score < cls.PREFLIGHT_MIN_COMPATIBILITY_SCORE:
            decision = PreflightDecision.REGENERATE
            reasons.extend(warnings)
        elif complexity > cls.PREFLIGHT_MAX_COMPLEXITY:
            decision = PreflightDecision.REJECT
            reasons.append(f"Excessive formula complexity ({complexity} > {cls.PREFLIGHT_MAX_COMPLEXITY}).")

        if not reasons and warnings:
            reasons.extend(warnings)

        final_reason = " | ".join(reasons) if reasons else "Expression passed preflight validation checks."

        return cls._build_report(
            expression=expr_clean,
            decision=decision,
            reason=final_reason,
            constant_risk=constant_risk,
            compatibility=compat_score,
            field_categories=list(set(field_categories)),
            temporal_behaviors=list(set(temporal_behaviors)),
            operators=operators,
            lookbacks=lookbacks,
            duplicate_risk=duplicate_risk,
            complexity=complexity,
            expression_hash=expr_hash,
            structure_hash=struct_hash
        )

    @classmethod
    def _detect_constant_signal_risk(
        cls,
        expr_clean: str,
        fields: List[str],
        operators: List[str],
        lookbacks: List[int],
        temporal_behaviors: List[str]
    ) -> Tuple[str, Optional[str]]:
        """
        Specialized detector for expressions that yield zero cross-sectional variance or constant portfolios.
        """
        # Case A: Quarterly fundamental lookback with short rolling ratio:
        # e.g. ts_mean(capex, 10) / ts_mean(capex, 30) - 1 or ts_mean(debt, 10) / ts_mean(debt, 5) - 1
        has_slow = any(tb == TemporalBehavior.SLOW for tb in temporal_behaviors)
        has_ts_mean = "ts_mean" in operators or "ts_sum" in operators or "ts_decay_linear" in operators
        
        if has_slow and has_ts_mean:
            if lookbacks and max(lookbacks) <= 30:
                return ConstantSignalRisk.HIGH, (
                    f"Fundamental field(s) '{fields}' update on quarterly cadence. Rolling daily windows "
                    f"({lookbacks} <= 30d) evaluate to constant values over daily bars, generating 0 trades and an empty portfolio."
                )
            if len(lookbacks) >= 2 and all(lb < 45 for lb in lookbacks):
                return ConstantSignalRisk.HIGH, (
                    f"Ratio of short rolling windows {lookbacks} on fundamental fields {fields} yields 0.0 variance on daily series."
                )

        # Case B: Tautological identity: field / field or field - field
        for f in fields:
            # Check for pattern f / f or f - f
            pattern_div = rf'\b{re.escape(f)}\s*/\s*{re.escape(f)}\b'
            pattern_sub = rf'\b{re.escape(f)}\s*-\s*{re.escape(f)}\b'
            if re.search(pattern_div, expr_clean) or re.search(pattern_sub, expr_clean):
                return ConstantSignalRisk.HIGH, f"Tautological arithmetic identity on field '{f}' produces constant values."

        # Case C: Bare group_neutralize on raw unranked constant
        if "group_neutralize" in operators and len(operators) == 1:
            if has_slow:
                return ConstantSignalRisk.HIGH, "group_neutralize applied directly to raw slow fundamental field without cross-sectional ranking or ratio."

        # Case D: Moderate lookback on slow fundamental
        if has_slow and lookbacks and min(lookbacks) < 60:
            return ConstantSignalRisk.MEDIUM, "Lookback window is below recommended quarterly threshold (60d) for fundamental data."

        return ConstantSignalRisk.LOW, None

    @staticmethod
    def _build_report(
        expression: str,
        decision: str,
        reason: str,
        constant_risk: str,
        compatibility: float,
        field_categories: Optional[List[str]] = None,
        temporal_behaviors: Optional[List[str]] = None,
        operators: Optional[List[str]] = None,
        lookbacks: Optional[List[int]] = None,
        duplicate_risk: str = "LOW",
        complexity: int = 1,
        expression_hash: Optional[str] = None,
        structure_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        return {
            "expression": expression,
            "field_categories": field_categories or [],
            "temporal_behavior": temporal_behaviors or [],
            "operators": operators or [],
            "lookbacks": lookbacks or [],
            "compatibility_score": round(compatibility, 2),
            "constant_signal_risk": constant_risk,
            "duplicate_risk": duplicate_risk,
            "complexity": complexity,
            "decision": decision,
            "reason": reason,
            "expression_hash": expression_hash,
            "structure_hash": structure_hash
        }
