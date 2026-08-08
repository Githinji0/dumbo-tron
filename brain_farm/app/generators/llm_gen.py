import logging
import re
import httpx
from typing import List, Dict, Any, Tuple
from brain_farm.app.generators.base import BaseGenerator
from brain_farm.app.core.config import settings
from brain_farm.app.evaluators.validator import FormulaValidator

logger = logging.getLogger("brain_farm.llm_generator")

class LLMGenerator(BaseGenerator):
    """Accesses LLMs (OpenAI/Gemini) or utilizes a rule-based quantitative parser when keys are absent."""

    def __init__(self, allowed_fields: List[str]):
        super().__init__(allowed_fields)
        self.headers_openai = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        self.headers_gemini = {
            "x-goog-api-key": settings.GEMINI_API_KEY,
            "Content-Type": "application/json"
        }

    async def optimize_alpha(self, expression: str, reason: str) -> Tuple[str, str]:
        """
        Submits an alpha candidate and its validation failures to LLM for optimizations.
        Returns Tuple[optimized_expression, explanation_summary]
        """
        # Validate LLM availability, else use our heuristic optimization engine
        if not settings.OPENAI_API_KEY and not settings.GEMINI_API_KEY:
            return self._heuristic_local_optimization(expression, reason)

        # 1. OpenAI completion route if configured
        if settings.OPENAI_API_KEY:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    prompt = self._compile_optimization_prompt(expression, reason)
                    payload = {
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": "You are a quantitative researcher on WorldQuant BRAIN. You optimize alpha expression formulas to improve metrics like Sharpe, Fitness, and Turnover."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2
                    }
                    res = await client.post("https://api.openai.com/v1/chat/completions", headers=self.headers_openai, json=payload)
                    if res.status_code == 200:
                        content = res.json()["choices"][0]["message"]["content"]
                        return self._parse_llm_response(content, expression)
            except Exception as e:
                logger.error(f"OpenAI completion call failed: {e}. Falling back to heuristics.")

        # 2. Gemini execution route if configured
        if settings.GEMINI_API_KEY:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    prompt = self._compile_optimization_prompt(expression, reason)
                    payload = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.2}
                    }
                    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
                    res = await client.post(url, headers=self.headers_gemini, json=payload)
                    if res.status_code == 200:
                        content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                        return self._parse_llm_response(content, expression)
            except Exception as e:
                logger.error(f"Gemini API execution failed: {e}. Falling back to heuristics.")

        return self._heuristic_local_optimization(expression, reason)

    def _compile_optimization_prompt(self, expression: str, reason: str) -> str:
        fields_csv = ", ".join(self.allowed_fields)
        return f"""
        Optimize the following WorldQuant BRAIN Alpha formula to resolve its failure.
        Failing Formula: {expression}
        Failure Reason: {reason}
        
        Available Data Fields: {fields_csv}
        
        Please provide the response in the following format:
        OPTIMIZED_FORMULA: [Insert new formula here]
        EXPLANATION: [Brief explanation of why the check resolves the failure]
        """

    def _parse_llm_response(self, text: str, fallback_expr: str) -> Tuple[str, str]:
        """Parses output containing: OPTIMIZED_FORMULA and EXPLANATION."""
        formula = fallback_expr
        explanation = "No explanation provided."
        
        formula_match = re.search(r"OPTIMIZED_FORMULA:\s*(.+)", text, re.IGNORECASE)
        if formula_match:
            formula = formula_match.group(1).strip()
            
        explanation_match = re.search(r"EXPLANATION:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
        if explanation_match:
            explanation = explanation_match.group(1).strip()
            
        return formula, explanation

    def _heuristic_local_optimization(self, expression: str, reason: str) -> Tuple[str, str]:
        """Heuristics rules engine simulating local optimizers when API keys are absent."""
        reason_lower = reason.lower()
        
        # 1. Turnover failure
        if "turnover" in reason_lower:
            if "ts_decay_linear" not in expression:
                optimized = f"ts_decay_linear({expression}, 11)"
                explanation = "Applied ts_decay_linear with lookback 11 to smooth alpha signals, successfully reducing extreme turnover rate."
            elif "group_neutralize" not in expression:
                optimized = f"group_neutralize({expression}, subindustry)"
                explanation = "Added subindustry neutralisation to cancel sector exposures and lower overall turnover."
            else:
                # Modify lookback window
                optimized = re.sub(r"ts_decay_linear\((.+),\s*(\d+)\)", r"ts_decay_linear(\1, 20)", expression)
                explanation = "Increased decay lookback window to 20 to smooth signals further."
                
        # 2. Sharpe ratio failure
        elif "sharpe" in reason_lower or "fitness" in reason_lower:
            # Try incorporating a momentum factor or scaling
            if "rank" not in expression:
                optimized = f"rank({expression})"
                explanation = "Wrapped formula in cross-sectional rank to stabilize output distribution and improve Sharpe."
            else:
                optimized = f"({expression} - rank(volume))"
                explanation = "Subtracted cross-sectional rank of volume to penalize high-liquid tickers and capture small-firm premium."
                
        # 3. Syntax / parenthesis mismatch
        elif "mismatched" in reason_lower or "parentheses" in reason_lower:
            # Auto-balance parentheses if simple
            open_cnt = expression.count("(")
            close_cnt = expression.count(")")
            optimized = expression + (")" * (open_cnt - close_cnt)) if open_cnt > close_cnt else expression
            explanation = "Balanced expression parentheses count automatically."
            
        else:
            # Generic fallback: mutate the parameters
            optimized = f"group_neutralize(ts_decay_linear(rank({expression}), 8), subindustry)"
            explanation = "Wrapped formula with rank, decay, and subindustry neutralization to improve general metrics."

        # Safety validation checks
        ok, _ = FormulaValidator.validate(optimized, self.allowed_fields)
        if not ok:
            # If the optimization fails validation, return original
            return expression, "Local optimizer suggestion failed syntax checks; keeping original."
            
        return optimized, explanation

    def generate(self, count: int = 10, **kwargs) -> List[str]:
        # LLMGenerator can also operate as a batch builder
        # Creates templates and wraps them in decay/neutralizations
        from brain_farm.app.generators.template import TemplateGenerator
        tg = TemplateGenerator(self.allowed_fields)
        base_formulas = tg.generate(count)
        
        results = []
        for formula in base_formulas:
            # Simulate optimization cycle
            opt_formula, _ = self._heuristic_local_optimization(formula, "turnover value exceeds 0.70 limit")
            results.append(opt_formula)
        return self.filter_valid(results)[:count]
