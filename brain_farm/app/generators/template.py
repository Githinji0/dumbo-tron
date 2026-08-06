import random
from typing import List
from brain_farm.app.generators.base import BaseGenerator

class TemplateGenerator(BaseGenerator):
    """Farming engine that replaces keywords in pre-defined trading expression templates."""

    TEMPLATES = [
        "rank({field})",
        "group_neutralize(rank({field}), subindustry)",
        "group_neutralize(rank({field}), industry)",
        "ts_decay_linear(rank({field}), {window})",
        "-rank(ts_delta({field}, {window}))",
        "group_neutralize(ts_decay_linear(rank({field}), {window}), industry)",
        "ts_zscore({field}, {window})",
        "-ts_rank({field}, {window})",
        "ts_corr({field1}, {field2}, {window})",
        "group_neutralize(ts_zscore({field}, {window}), subindustry)",
        "ts_decay_linear(ts_zscore({field1}, {window1}) - rank({field2}), {window2})",
        "group_neutralize(rank({field1}) / rank({field2}), subindustry)"
    ]

    def generate(self, count: int = 10, **kwargs) -> List[str]:
        candidates = []
        # Fallback to defaults if no fields provided
        fields = self.allowed_fields or ["close", "open", "volume"]
        
        attempts = 0
        max_attempts = count * 10
        
        while len(candidates) < count and attempts < max_attempts:
            attempts += 1
            template = random.choice(self.TEMPLATES)
            
            # Sub-fill variables
            field1 = random.choice(fields)
            field2 = random.choice(fields)
            
            window = random.choice([5, 10, 20, 40, 60])
            window1 = random.choice([5, 10, 20])
            window2 = random.choice([5, 10, 20])
            
            expr = template.format(
                field=field1,
                field1=field1,
                field2=field2,
                window=window,
                window1=window1,
                window2=window2
            )
            
            # Filter duplicates immediately
            if expr not in candidates:
                candidates.append(expr)
                
        # Return only syntactically validator-passing candidate elements
        return self.filter_valid(candidates)[:count]
