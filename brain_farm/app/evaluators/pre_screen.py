import re
from typing import Tuple, List, Dict, Any, Optional
from brain_farm.app.evaluators.validator import FormulaValidator, ALLOWED_OPERATORS
from brain_farm.app.evaluators.signal_classifier import SignalQualityClassifier, ResearchQualityScorer

class StatisticalPreScreen:
    """
    Comprehensive 8-point pre-simulation gate before submitting candidates to WorldQuant BRAIN:
    1. Syntax validation
    2. Field validation
    3. Operator validation
    4. Complexity validation
    5. Duplicate / trivial expression detection
    6. Lineage / redundancy validation
    7. Research-family validation
    8. Signal-quality classification & naked neutralization rejection
    """

    @staticmethod
    def pre_screen(
        expr: str, 
        allowed_fields: List[str],
        family: Optional[str] = None,
        allow_raw_signals: bool = False
    ) -> Tuple[bool, str]:
        """
        Runs syntactic, semantic, and signal-quality pre-checks on an expression.
        Returns (passed, reason).
        """
        if not expr or not expr.strip():
            return False, "Empty expression."

        # 1, 2, 3. Standard structural, field, and operator validation
        ok, reason = FormulaValidator.validate(expr, allowed_fields)
        if not ok:
            return False, f"FormulaValidator failed: {reason}"

        # 4. Operator complexity bounds
        tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr)
        op_count = sum(1 for w in tokens if w in ALLOWED_OPERATORS)
        if op_count > 15:
            return False, f"Expression operator count {op_count} exceeds limit of 15."

        # 5. Check for constant-only or trivial self-cancelling expressions
        trimmed = expr.replace(" ", "")
        trivial_patterns = ["open-open", "close-close", "high-high", "low-low", "volume-volume", "vwap-vwap"]
        if trimmed in trivial_patterns or re.search(r"([a-zA-Z_]+)\s*-\s*\1", expr):
            # Check if identical variable subtraction like close - close
            tokens_in_sub = re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*-\s*([a-zA-Z_][a-zA-Z0-9_]*)", expr)
            for t1, t2 in tokens_in_sub:
                if t1 == t2 and t1 in (allowed_fields or []):
                    return False, f"Expression contains trivial self-cancelling subtraction ({t1} - {t2})."

        # 6. Check for multiple / nested group_neutralize calls
        neut_count = len(re.findall(r"\bgroup_neutralize\b", expr))
        if neut_count > 1:
            return False, "Multiple group_neutralize calls are not permitted."

        # 7. Check research family compatibility if family provided
        if family:
            from brain_farm.app.generators.family_info import RESEARCH_FAMILIES
            fam_cfg = RESEARCH_FAMILIES.get(family.upper())
            if fam_cfg:
                incompat_ops = fam_cfg.get("incompatible_operators", [])
                for i_op in incompat_ops:
                    if re.search(rf"\b{i_op}\b", expr):
                        return False, f"Operator '{i_op}' is incompatible with research family '{family}'."

        # 8. Signal Quality Classification: Filter out naked single-field neutralizations & empty signals
        classification = SignalQualityClassifier.classify(expr, allowed_fields)
        if classification["is_naked_neutralization"]:
            return False, "Structurally weak candidate: naked group neutralization on raw field without temporal baseline or ranking."
        if not allow_raw_signals and classification["signal_type"] == "RAW_SIGNAL" and op_count == 0:
            return False, f"Structurally weak candidate ({classification['reason']}). Composite structure required."

        return True, "Pre-screen validation passed."

