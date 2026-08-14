import re
from typing import Dict, Any, List, Optional
from brain_farm.app.evaluators.validator import ALLOWED_OPERATORS

class SignalQualityClassifier:
    """
    Classifies alpha expressions by structural sophistication and predictive intent:
    - RAW_SIGNAL: Single field or single field + neutralization/unary (e.g. group_neutralize(vwap, subindustry), rank(close))
    - TRANSFORMED_SIGNAL: Single temporal or arithmetic transformation (e.g. ts_delta(close, 5), ts_zscore(volume, 20))
    - PREDICTIVE_SIGNAL: Complete multi-stage composite structure (temporal transformation + cross-sectional ranking + optional neutralization)
    """

    TEMPORAL_OPERATORS = {
        "ts_decay_linear", "ts_delta", "ts_zscore", "ts_rank", 
        "ts_mean", "ts_std_dev", "ts_corr", "ts_covariance", 
        "ts_delay", "ts_max", "ts_min", "ts_sum"
    }

    CROSS_SECTIONAL_OPERATORS = {"rank", "scale", "group_rank", "quantile"}

    @classmethod
    def classify(cls, expression: str, field_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        expr = expression.strip()
        
        # Tokenize operators and fields
        tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr)
        ops = [t for t in tokens if t in ALLOWED_OPERATORS]
        
        temporal_ops = [op for op in ops if op in cls.TEMPORAL_OPERATORS]
        cs_ops = [op for op in ops if op in cls.CROSS_SECTIONAL_OPERATORS]
        has_group_neut = "group_neutralize" in ops

        # Check if it's a naked group_neutralize on a single raw field
        # e.g., group_neutralize(vwap, subindustry), group_neutralize(close, industry)
        naked_neut_match = re.match(r"^group_neutralize\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*,\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\)$", expr)
        
        # Naked rank on single field: rank(close)
        naked_rank_match = re.match(r"^rank\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\)$", expr)

        if len(ops) == 0:
            classification = "RAW_SIGNAL"
            reason = "Raw unadjusted data field without mathematical transformation or ranking."
        elif naked_neut_match:
            classification = "RAW_SIGNAL"
            reason = "Naked group neutralization on raw unadjusted price/volume field without temporal baseline."
        elif naked_rank_match:
            classification = "RAW_SIGNAL"
            reason = "Single cross-sectional rank on raw field without temporal deviation."
        elif len(ops) == 1 and len(temporal_ops) == 1:
            classification = "TRANSFORMED_SIGNAL"
            reason = f"Single temporal transformation ({temporal_ops[0]}) without cross-sectional ranking."
        elif len(temporal_ops) >= 1 and (len(cs_ops) >= 1 or has_group_neut):
            classification = "PREDICTIVE_SIGNAL"
            reason = "Composite predictive alpha structure combining temporal dynamics and cross-sectional normalization."
        elif len(ops) >= 2:
            classification = "TRANSFORMED_SIGNAL"
            reason = "Multi-operator formula with basic arithmetic/statistical transformation."
        else:
            classification = "RAW_SIGNAL"
            reason = "Single operator transformation lacking temporal predictive structure."

        return {
            "signal_type": classification,
            "reason": reason,
            "operator_count": len(ops),
            "temporal_operator_count": len(temporal_ops),
            "cross_sectional_operator_count": len(cs_ops),
            "has_group_neutralization": has_group_neut,
            "is_naked_neutralization": bool(naked_neut_match)
        }


class ResearchQualityScorer:
    """
    Computes a pre-simulation structural research score (0-100) to prioritize
    and gate expressions before consuming simulation budget.
    """

    @classmethod
    def compute_score(
        cls, 
        expression: str, 
        hypothesis: Optional[str] = None,
        research_family: Optional[str] = None
    ) -> Dict[str, Any]:
        classification = SignalQualityClassifier.classify(expression)
        stype = classification["signal_type"]
        
        score = 20.0  # Base score
        breakdown = {"base": 20.0}

        # 1. Hypothesis clarity
        if hypothesis and len(hypothesis.strip()) > 10:
            score += 20.0
            breakdown["hypothesis_bonus"] = 20.0

        # 2. Temporal structure
        if classification["temporal_operator_count"] >= 1:
            score += 25.0
            breakdown["temporal_structure_bonus"] = 25.0

        # 3. Cross-sectional ranking
        if classification["cross_sectional_operator_count"] >= 1:
            score += 15.0
            breakdown["ranking_bonus"] = 15.0

        # 4. Balanced Neutralization
        if classification["has_group_neutralization"]:
            if classification["is_naked_neutralization"]:
                score -= 30.0
                breakdown["naked_neutralization_penalty"] = -30.0
            else:
                score += 10.0
                breakdown["neutralization_bonus"] = 10.0

        # 5. Signal classification category
        if stype == "PREDICTIVE_SIGNAL":
            score += 10.0
            breakdown["predictive_structure_bonus"] = 10.0
        elif stype == "RAW_SIGNAL":
            score -= 25.0
            breakdown["raw_signal_penalty"] = -25.0

        final_score = max(0.0, min(100.0, score))
        return {
            "research_quality_score": round(final_score, 1),
            "signal_type": stype,
            "classification_reason": classification["reason"],
            "score_breakdown": breakdown
        }
