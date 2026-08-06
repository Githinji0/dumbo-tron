import re
import random
from typing import List
from brain_farm.app.generators.base import BaseGenerator

class MutationGenerator(BaseGenerator):
    """Mutates existing formulas by altering parameters, windows, neutralization, or adding operators."""

    def __init__(self, allowed_fields: List[str]):
        super().__init__(allowed_fields)

    def mutate_expression(self, expr: str) -> str:
        """Applies a random mutation operator to an expression."""
        if not expr:
            return ""

        mutations = [
            self._mutate_window,
            self._mutate_fields,
            self._mutate_neutralization,
            self._add_decay,
            self._add_noise_or_offset
        ]
        
        # Select single mutation randomly
        mutator = random.choice(mutations)
        try:
            mutated = mutator(expr)
            if mutated and mutated != expr:
                return mutated
        except Exception:
            pass
            
        return expr

    def _mutate_window(self, expr: str) -> str:
        """Finds integers inside of function window calls and changes them."""
        # Find integers that are preceded by a comma (like windows)
        matches = list(re.finditer(r",\s*(\d+)", expr))
        if not matches:
            return expr
        
        target = random.choice(matches)
        old_val = int(target.group(1))
        # Add or subtract window val
        delta = random.choice([-10, -5, 5, 10])
        new_val = max(2, min(old_val + delta, 250))
        
        start, end = target.span(1)
        return expr[:start] + str(new_val) + expr[end:]

    def _mutate_fields(self, expr: str) -> str:
        """Replaces an existing data field with another random field."""
        fields = self.allowed_fields or ["close", "open", "volume"]
        
        # Match only word tokens which are in allowed fields
        for field in sorted(fields, key=len, reverse=True):
            if field in expr:
                # Replace one occurrence randomly
                alternative = random.choice([f for f in fields if f != field])
                # Ensure word boundaries match
                pattern = r"\b" + re.escape(field) + r"\b"
                if re.search(pattern, expr):
                    return re.sub(pattern, alternative, expr, count=1)
        return expr

    def _mutate_neutralization(self, expr: str) -> str:
        """Swaps or introduces subindustry/industry/sector neutralization."""
        groups = ["subindustry", "industry", "sector"]
        
        # Check if already containing group_neutralize
        if "group_neutralize" in expr:
            for g in groups:
                if g in expr:
                    other_groups = [grp for grp in groups if grp != g]
                    return expr.replace(g, random.choice(other_groups))
            # If neutralize doesn't explicitly name a group, clean it
            return expr
        else:
            # Wrap whole expression in group_neutralize
            target_group = random.choice(groups)
            return f"group_neutralize({expr}, {target_group})"

    def _add_decay(self, expr: str) -> str:
        """Wraps the expression inside time-decay to lower turnover."""
        window = random.choice([5, 10, 15, 20])
        # Avoid double decay if already present
        if "ts_decay_linear" in expr:
            return expr
        return f"ts_decay_linear({expr}, {window})"

    def _add_noise_or_offset(self, expr: str) -> str:
        """Combines the formula with a minor modifier (e.g. rank(volume))."""
        modifier_ops = [
            "- rank(volume)",
            "+ rank(volume)",
            "* 0.9",
        ]
        modifier = random.choice(modifier_ops)
        # Check to verify volume is in allowed fields
        if "volume" not in self.allowed_fields:
            modifier = "* 0.95"
        return f"({expr} {modifier})"

    def generate(self, count: int = 10, **kwargs) -> List[str]:
        base_formulas = kwargs.get("base_formulas", [])
        if not base_formulas:
            # Fallback if no base formulas to mutate: generate templates
            from brain_farm.app.generators.template import TemplateGenerator
            tg = TemplateGenerator(self.allowed_fields)
            base_formulas = tg.generate(count)

        candidates = []
        attempts = 0
        max_attempts = count * 20
        
        while len(candidates) < count and attempts < max_attempts:
            attempts += 1
            parent = random.choice(base_formulas)
            child = self.mutate_expression(parent)
            
            if child and child not in candidates and child != parent:
                candidates.append(child)

        return self.filter_valid(candidates)[:count]
