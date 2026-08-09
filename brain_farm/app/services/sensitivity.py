import re
from typing import List, Tuple
from brain_farm.app.services.correlation_filter import CorrelationFilter

class ParameterSensitivityTester:
    """
    Identifies lookback parameters in time-series operations, perturbs them,
    and analyzes signal stability (correlation) of perturbed versions.
    Applies penalty factor to rating if adjacent parameters fail stability check.
    """

    @staticmethod
    def extract_lookbacks(expr: str) -> List[Tuple[str, int]]:
        """
        Finds lookback parameters of format ts_xxx(arg, L).
        Returns list of (full_match_string, lookback_value).
        """
        # Matches ts_something(arg, digits)
        pattern = r"\b(ts_[a-zA-Z_0-9]+)\s*\(\s*([^,]+)\s*,\s*(\d+)\s*\)"
        matches = re.findall(pattern, expr)
        
        results = []
        for match in re.finditer(pattern, expr):
            full_match = match.group(0)
            lookback_val = int(match.group(3))
            results.append((full_match, lookback_val))
            
        return results

    @classmethod
    def generate_perturbed_expressions(cls, expr: str) -> List[str]:
        """
        Generates expressions with perturbed lookback parameters (e.g. +/-20%).
        """
        lookbacks = cls.extract_lookbacks(expr)
        if not lookbacks:
            return []

        perturbed_exprs = []
        for full_match, val in lookbacks:
            # Perturb low and high (min adjustment of 1)
            p_low = max(1, int(val * 0.8))
            p_high = int(val * 1.2)
            if p_low == val:
                p_low = max(1, val - 1)
            if p_high == val:
                p_high = val + 1

            # Replace the specific lookback in the lookback function call
            # To avoid replacing all occurrences of the same integer, we replace within the full match context
            for p_val in (p_low, p_high):
                # Replace last occurrences of lookback integer in the match
                new_match = re.sub(r",\s*" + str(val) + r"\s*\)$", f", {p_val})", full_match)
                new_expr = expr.replace(full_match, new_match)
                perturbed_exprs.append(new_expr)

        return list(set(perturbed_exprs))

    @classmethod
    def evaluate_sensitivity_penalty(cls, expr: str, original_sharpe: float) -> float:
        """
        Computes a penalty multiplier (in [0.5, 1.0]).
        If perturbed versions are highly correlated to the original, returns 1.0 (no penalty).
        If correlation drops below 0.85, applies linear penalty.
        """
        perturbed_exprs = cls.generate_perturbed_expressions(expr)
        if not perturbed_exprs:
            return 1.0

        correlations = []
        for p_expr in perturbed_exprs:
            corr = CorrelationFilter.calculate_correlation(expr, p_expr)
            correlations.append(abs(corr))

        if not correlations:
            return 1.0

        # Mean correlation of perturbed signals
        mean_corr = sum(correlations) / len(correlations)

        # Cutoff: if mean correlation is >= 0.85, parameter is stable (1.0 factor)
        # If mean correlation is 0.0, penalty factor is 0.5 (maximum penalty)
        if mean_corr >= 0.85:
            return 1.0
        else:
            # Linear scaling down to 0.5
            penalty = 0.5 + 0.5 * (mean_corr / 0.85)
            return float(penalty)
