import random
from typing import List, Dict, Any
from brain_farm.app.generators.base import BaseGenerator
from brain_farm.app.generators.family_info import RESEARCH_FAMILIES
from brain_farm.app.evaluators.validator import FormulaValidator
from brain_farm.app.evaluators.pre_screen import StatisticalPreScreen
from brain_farm.app.evaluators.signal_classifier import SignalQualityClassifier, ResearchQualityScorer
from brain_farm.app.generators.expression_analyzer import analyze_expression

class FamilyGenerator(BaseGenerator):
    """
    Generator that creates quantitative Alpha expressions tailored to a specific
    Research Family (e.g., MOMENTUM, VALUE, QUALITY) and its associated hypothesis/constraints.
    """

    def __init__(self, allowed_fields: List[str], family_name: str = "MOMENTUM"):
        super().__init__(allowed_fields)
        self.family_name = family_name.upper() if family_name else "MOMENTUM"
        if self.family_name not in RESEARCH_FAMILIES:
            self.family_name = "MOMENTUM"
        self.family_info = RESEARCH_FAMILIES[self.family_name]
        self.generated_metadata: Dict[str, Dict[str, Any]] = {}

    def generate(self, count: int = 10, **kwargs) -> List[str]:
        candidates = []
        
        # Intersect project-allowed fields with family-allowed fields to avoid invalid inputs
        family_fields = self.family_info.get("allowed_fields", [])
        fields = [f for f in self.allowed_fields if f in family_fields]
        if not fields:
            # Fallback to project-allowed fields if no overlap (e.g. custom catalog)
            fields = self.allowed_fields or ["close", "open", "volume"]
            
        templates = self.family_info.get("templates", ["rank({field})"])
        
        attempts = 0
        max_attempts = count * 20
        
        expected_relationship = self.family_info.get("description", "")
        turnover_range = self.family_info.get("turnover_range", (0.05, 0.40))
        avg_turnover = sum(turnover_range) / 2.0
        expected_turnover_category = "HIGH_RETURN_HIGH_TURNOVER" if avg_turnover > 0.40 else "HIGH_RETURN_LOW_TURNOVER"
        
        while len(candidates) < count and attempts < max_attempts:
            attempts += 1
            template = random.choice(templates)
            
            # Select target variables
            f1 = random.choice(fields)
            f2 = random.choice(fields)
            fund = random.choice([f for f in fields if f not in ["close", "open", "volume", "vwap"]] or fields)
            
            # Common windows
            w = random.choice([5, 10, 20, 44, 60])
            w1 = random.choice([5, 10, 22])
            w2 = random.choice([10, 20, 44])
            
            # Perform formatting
            try:
                expr = template.format(
                    field=f1,
                    field1=f1,
                    field2=f2,
                    fundamental=fund,
                    window=w,
                    window1=w1,
                    window2=w2
                )
            except Exception:
                expr = f"rank({f1})"
            
            # Simple post-checks
            # Check for forbidden operators
            incompat_ops = self.family_info.get("incompatible_operators", [])
            has_forbidden = False
            for op in incompat_ops:
                if op in expr:
                    has_forbidden = True
                    break
                    
            if has_forbidden:
                continue
            if expr not in candidates:
                passed, _ = StatisticalPreScreen.pre_screen(expr, self.allowed_fields, family=self.family_name)
                if passed:
                    candidates.append(expr)
                    
                    # Analyze and extract metrics
                    analysis = analyze_expression(expr, self.allowed_fields)
                    
                    # Determine horizon based on lookback windows used
                    max_w = max([w, w1, w2])
                    if max_w <= 5:
                        horizon = "SHORT"
                    elif max_w <= 30:
                        horizon = "MEDIUM"
                    else:
                        horizon = "LONG"
                        
                    hypo_text = f"{self.family_name} Hypothesis: {expected_relationship}"
                    quality_res = ResearchQualityScorer.compute_score(expr, hypo_text, self.family_name)

                    self.generated_metadata[expr] = {
                        "research_family": self.family_name,
                        "hypothesis": hypo_text,
                        "expected_relationship": expected_relationship,
                        "expected_horizon": horizon,
                        "signal_type": quality_res["signal_type"],
                        "generation_reason": quality_res["classification_reason"],
                        "research_quality_score": quality_res["research_quality_score"],
                        "selected_fields": ", ".join(analysis["fields"]),
                        "selected_operators": ", ".join(analysis["operators"]),
                        "operator_parameters": analysis["parameters"],
                        "construction_template": template,
                        "expected_turnover_category": expected_turnover_category,
                        "expected_signal_behavior": f"Statistically motivated {self.family_name} formula using {horizon} horizon.",
                        "lineage_id": None,
                        "parent_alpha_id": None,
                        "generation_number": 1,
                        "expression_depth": analysis["expression_depth"],
                        "operator_count": analysis["operator_count"],
                        "field_count": analysis["field_count"],
                        "complexity_score": analysis["complexity_score"]
                    }
                
        return candidates[:count]
