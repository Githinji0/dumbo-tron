import random
from typing import List, Union

class ASTNode:
    """Base Node of the Abstract Syntax Tree."""
    def to_string(self) -> str:
        raise NotImplementedError()

    def depth(self) -> int:
        raise NotImplementedError()


class FieldNode(ASTNode):
    def __init__(self, field_name: str):
        self.field_name = field_name

    def to_string(self) -> str:
        return self.field_name

    def depth(self) -> int:
        return 1


class ConstantNode(ASTNode):
    def __init__(self, value: Union[int, float]):
        self.value = value

    def to_string(self) -> str:
        return str(self.value)

    def depth(self) -> int:
        return 1


class UnaryOpNode(ASTNode):
    def __init__(self, operator: str, child: ASTNode):
        self.operator = operator
        self.child = child

    def to_string(self) -> str:
        # Simplify rank(rank(x)) -> rank(x)
        if self.operator == "rank" and isinstance(self.child, UnaryOpNode) and self.child.operator == "rank":
            return self.child.to_string()
        return f"{self.operator}({self.child.to_string()})"

    def depth(self) -> int:
        return self.child.depth() + 1


class BinaryOpNode(ASTNode):
    def __init__(self, operator: str, left: ASTNode, right: ASTNode):
        self.operator = operator
        self.left = left
        self.right = right

    def to_string(self) -> str:
        # Standard arithmetic or logic math expressions
        if self.operator in ["+", "-", "*", "/"]:
            return f"({self.left.to_string()} {self.operator} {self.right.to_string()})"
        return f"{self.operator}({self.left.to_string()}, {self.right.to_string()})"

    def depth(self) -> int:
        return max(self.left.depth(), self.right.depth()) + 1


class WindowOpNode(ASTNode):
    def __init__(self, operator: str, child: ASTNode, window: int):
        self.operator = operator
        self.child = child
        self.window = window

    def to_string(self) -> str:
        return f"{self.operator}({self.child.to_string()}, {self.window})"

    def depth(self) -> int:
        return self.child.depth() + 1


class GroupNeutralizeNode(ASTNode):
    def __init__(self, child: ASTNode, group: str = "subindustry"):
        self.child = child
        self.group = group

    def to_string(self) -> str:
        # Avoid nested neutralizing: group_neutralize(group_neutralize(x, g1), g2) -> group_neutralize(x, g2)
        if isinstance(self.child, GroupNeutralizeNode):
            return f"group_neutralize({self.child.child.to_string()}, {self.group})"
        return f"group_neutralize({self.child.to_string()}, {self.group})"

    def depth(self) -> int:
        return self.child.depth() + 1


from brain_farm.app.generators.base import BaseGenerator
from brain_farm.app.evaluators.signal_classifier import SignalQualityClassifier, ResearchQualityScorer
from brain_farm.app.evaluators.pre_screen import StatisticalPreScreen

class ASTGenerator(BaseGenerator):
    """
    Generates structured, hypothesis-driven alpha signals via multi-stage signal construction:
    1. Factor selection (Price / Volume / Fundamental)
    2. Temporal structure / Deviation (ts_delta, ts_decay_linear, ts_zscore, ts_mean, ts_rank)
    3. Cross-sectional normalization / ranking (rank)
    4. Optional group neutralization (subindustry / industry)
    """

    def __init__(self, allowed_fields: List[str], max_depth: int = 3):
        super().__init__(allowed_fields)
        self.max_depth = max(2, min(max_depth, 5))

    def _generate_predictive_signal(self) -> str:
        fields = self.allowed_fields or ["close", "open", "volume", "vwap"]
        f1 = random.choice(fields)
        f2 = random.choice(fields)
        w1 = random.choice([5, 10, 20, 30, 60])
        w2 = random.choice([5, 10, 20])

        pattern = random.choice([
            "momentum_decay",
            "mean_reversion_zscore",
            "relative_spread",
            "volume_price_correlation",
            "normalized_trend",
            "dual_lookback_oscillator"
        ])

        if pattern == "momentum_decay":
            inner = f"rank(ts_delta({f1}, {w1}))"
            expr = f"ts_decay_linear({inner}, {w2})"
        elif pattern == "mean_reversion_zscore":
            expr = f"-rank(ts_zscore({f1}, {w1}))"
        elif pattern == "relative_spread":
            expr = f"rank({f1} / ts_mean({f1}, {w1}) - 1)"
        elif pattern == "volume_price_correlation":
            expr = f"ts_corr({f1}, {f2}, {w1})"
        elif pattern == "dual_lookback_oscillator":
            expr = f"rank(ts_mean({f1}, {w2}) / ts_mean({f1}, {w1}) - 1)"
        else: # normalized_trend
            expr = f"-ts_rank(ts_decay_linear({f1}, {w2}), {w1})"

        # Controlled Neutralization (35% probability, strictly on outer ranked composite)
        if random.random() < 0.35:
            expr = f"group_neutralize({expr}, subindustry)"

        return expr

    def generate(self, count: int = 10, **kwargs) -> List[str]:
        candidates = []
        max_attempts = count * 25
        attempts = 0
        
        while len(candidates) < count and attempts < max_attempts:
            attempts += 1
            expr = self._generate_predictive_signal()
            
            if expr not in candidates:
                # Pre-screen check
                passed, _ = StatisticalPreScreen.pre_screen(expr, self.allowed_fields)
                if passed:
                    candidates.append(expr)

        return candidates[:count]

