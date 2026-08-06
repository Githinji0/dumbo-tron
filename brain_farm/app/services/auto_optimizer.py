from typing import List, Tuple
from brain_farm.app.generators.llm_gen import LLMGenerator

class AutoOptimizer:
    """Service class for coordinating the quantitative optimization loops on failed alpha formulas."""
    
    def __init__(self, allowed_fields: List[str]):
        self.allowed_fields = allowed_fields
        self.llm_generator = LLMGenerator(allowed_fields)

    async def optimize(self, expression: str, fail_reason: str) -> Tuple[str, str]:
        """
        Coordinates parsing of failures and generating optimized candidates.
        Returns Tuple[optimized_expression, explanation]
        """
        # Call the underlying LLM generator (which falls back to heuristics locally)
        return await self.llm_generator.optimize_alpha(expression, fail_reason)
