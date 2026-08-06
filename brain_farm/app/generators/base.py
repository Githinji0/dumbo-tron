from abc import ABC, abstractmethod
from typing import List
from brain_farm.app.evaluators.validator import FormulaValidator

class BaseGenerator(ABC):
    """Abstract interface and helper structure for quantitative Alpha generator engines."""
    
    def __init__(self, allowed_fields: List[str]):
        self.allowed_fields = allowed_fields

    @abstractmethod
    def generate(self, count: int = 10, **kwargs) -> List[str]:
        """Generates candidate alpha expression strings."""
        pass

    def filter_valid(self, expressions: List[str]) -> List[str]:
        """Filters generated strings to retain only those passing validation checks."""
        valid_expressions = []
        for expr in expressions:
            ok, _ = FormulaValidator.validate(expr, self.allowed_fields)
            if ok:
                valid_expressions.append(expr)
        return valid_expressions
