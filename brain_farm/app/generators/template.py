import random
from typing import List, Dict, Any
from brain_farm.app.generators.base import BaseGenerator
from brain_farm.app.evaluators.pre_screen import StatisticalPreScreen
from brain_farm.app.evaluators.signal_classifier import SignalQualityClassifier, ResearchQualityScorer

class TemplateGenerator(BaseGenerator):
    """Farming engine that replaces keywords in pre-defined hypothesis-driven trading templates."""

    TEMPLATES = [
        # Momentum / Trend templates
        "group_neutralize(ts_decay_linear(rank(ts_delta({field}, {window})), {window1}), subindustry)",
        "ts_decay_linear(rank(ts_delta({field}, {window})), {window1})",
        # Mean Reversion / Normalized deviation templates
        "-rank(ts_zscore({field}, {window}))",
        "group_neutralize(-rank(ts_zscore({field}, {window})), subindustry)",
        # Relative Spread / Multi-lookback templates
        "group_neutralize(rank({field} / ts_mean({field}, {window}) - 1), subindustry)",
        "rank(ts_mean({field}, {window1}) / ts_mean({field}, {window2}) - 1)",
        # Multi-factor correlation & Interaction templates
        "group_neutralize(ts_corr({field1}, {field2}, {window}), subindustry)",
        "group_neutralize(rank(ts_delta({field1}, {window})) - rank(ts_delta({field2}, {window})), subindustry)",
        "-rank(ts_rank({field}, {window}))"
    ]

    def generate(self, count: int = 10, **kwargs) -> List[str]:
        candidates = []
        fields = self.allowed_fields or ["close", "open", "volume", "vwap"]
        
        attempts = 0
        max_attempts = count * 20
        
        while len(candidates) < count and attempts < max_attempts:
            attempts += 1
            template = random.choice(self.TEMPLATES)
            
            field1 = random.choice(fields)
            field2 = random.choice(fields)
            
            window = random.choice([5, 10, 20, 40, 60])
            window1 = random.choice([5, 10, 20])
            window2 = random.choice([20, 40, 60])
            
            expr = template.format(
                field=field1,
                field1=field1,
                field2=field2,
                window=window,
                window1=window1,
                window2=window2
            )
            
            if expr not in candidates:
                passed, _ = StatisticalPreScreen.pre_screen(expr, self.allowed_fields)
                if passed:
                    candidates.append(expr)
                    
        return candidates[:count]

