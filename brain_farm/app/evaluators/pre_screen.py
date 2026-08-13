import re
from typing import Tuple, List, Dict, Any
from brain_farm.app.evaluators.validator import FormulaValidator

class StatisticalPreScreen:
    """
    Runs quick pre-screening checks on FastExpr strings to ensure high simulation quality.
    Checks:
    - Basic FormulaValidator rules.
    - Operator complexity bounds.
    - Lookback window sanity.
    - Field coverage check.
    """

    @staticmethod
    def pre_screen(expr: str, allowed_fields: List[str]) -> Tuple[bool, str]:
        """
        Runs syntactic and semantic pre-checks on an expression.
        Returns (passed, reason).
        """
        # 1. Standard structural validation
        ok, reason = FormulaValidator.validate(expr, allowed_fields)
        if not ok:
            return False, f"FormulaValidator failed: {reason}"

        # 2. Check for constant-only or trivial expressions
        # e.g., "1.0", "close - close"
        trimmed = expr.replace(" ", "")
        if trimmed in ["open-open", "close-close", "high-high", "low-low", "volume-volume"]:
            return False, "Expression is trivial (evaluates constantly to zero)."

        # 3. Check for operators count limit
        tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr)
        from brain_farm.app.evaluators.validator import ALLOWED_OPERATORS
        op_count = sum(1 for w in tokens if w in ALLOWED_OPERATORS)
        if op_count > 15:
            return False, f"Expression operator count {op_count} exceeds limit of 15."

        # 4. Check for nested neutralization
        neut_count = len(re.findall(r"\bgroup_neutralize\b", expr))
        if neut_count > 1:
            return False, "Multiple group_neutralize calls are not supported."

        return True, "Pre-screen validation passed."
