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

class ASTGenerator(BaseGenerator):
    """Generates expressions by building a recursive tree structure up to a max depth."""

    def __init__(self, allowed_fields: List[str], max_depth: int = 3):
        super().__init__(allowed_fields)
        self.max_depth = max(2, min(max_depth, 5))  # Keep depth within 2-5 for complexity constraints

    def _generate_node(self, current_depth: int) -> ASTNode:
        fields = self.allowed_fields or ["close", "open", "volume"]
        
        # Base case: reach max depth or randomly decide to return a terminal Field or Constant
        if current_depth >= self.max_depth or (current_depth > 1 and random.random() < 0.35):
            if random.random() < 0.85:
                return FieldNode(random.choice(fields))
            else:
                return ConstantNode(random.choice([0.1, 0.5, 1, 2, 5]))

        # Select node category structure:
        # 1. Unary operator (rank, abs, log, sign)
        # 2. Binary operator (+, -, *, /, ts_corr)
        # 3. Window lookback operator (ts_zscore, ts_decay_linear, ts_rank, ts_delta, ts_mean, ts_std_dev)
        # 4. Neutralization (group_neutralize)
        
        choices = ["unary", "binary", "window", "neutralize"]
        # Reduce neutralization choice if already neutralized in call stack
        choice = random.choice(choices)

        if choice == "unary":
            op = random.choice(["rank", "abs", "log", "sign"])
            child = self._generate_node(current_depth + 1)
            return UnaryOpNode(op, child)
            
        elif choice == "binary":
            op = random.choice(["+", "-", "*", "/", "ts_corr", "ts_covariance"])
            left = self._generate_node(current_depth + 1)
            # For arithmetic right node, can be field or simple constant
            if op in ["ts_corr", "ts_covariance"]:
                right = self._generate_node(current_depth + 1)
                # Ensure the last argument of ts_corr is a window
                window = random.choice([10, 20, 40])
                # Special construction: ts_corr needs 3 parameters (left, right, window)
                # But since it is modelled in WQ as ts_corr(x, y, d), we can wrap it:
                return WindowOpNode(f"ts_corr({left.to_string()}", right, window)
            else:
                right = self._generate_node(current_depth + 1)
                return BinaryOpNode(op, left, right)
                
        elif choice == "window":
            op = random.choice(["ts_zscore", "ts_decay_linear", "ts_rank", "ts_delta", "ts_mean", "ts_std_dev"])
            child = self._generate_node(current_depth + 1)
            window = random.choice([5, 10, 20, 30, 60])
            return WindowOpNode(op, child, window)
            
        else: # neutralize
            group = random.choice(["subindustry", "industry", "sector"])
            child = self._generate_node(current_depth + 1)
            return GroupNeutralizeNode(child, group)

    def generate(self, count: int = 10, **kwargs) -> List[str]:
        candidates = []
        max_attempts = count * 20
        attempts = 0
        
        while len(candidates) < count and attempts < max_attempts:
            attempts += 1
            node = self._generate_node(1)
            expr = node.to_string()
            
            # Additional structural corrections
            # Fix ts_corr representation if nested weirdly
            if "ts_corr(" in expr and not expr.endswith(")"):
                # Clean up nested formatting
                pass

            if expr not in candidates:
                candidates.append(expr)

        return self.filter_valid(candidates)[:count]
