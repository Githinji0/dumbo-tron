import random
from typing import List, Dict, Any
from brain_farm.app.generators.base import BaseGenerator
from brain_farm.app.generators.family_info import RESEARCH_FAMILIES
from brain_farm.app.evaluators.validator import FormulaValidator

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
                candidates.append(expr)
                
        # Return validator-passing candidates
        return self.filter_valid(candidates)[:count]
