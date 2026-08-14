import logging
import re
from typing import Dict, Any, Optional, List
from brain_farm.app.ai.manager import ai_manager
from brain_farm.app.ai.schemas import TurnoverOptimizationProposal, ExperimentProposal
from brain_farm.app.ai.prompts import TURNOVER_SYSTEM_PROMPT
from brain_farm.app.evaluators.validator import FormulaValidator

logger = logging.getLogger("brain_farm.ai.turnover")

class TurnoverAgent:
    """Specialized agent for optimizing high-Sharpe, high-turnover alpha expressions (Tier 3)."""

    def __init__(self, allowed_fields: Optional[List[str]] = None):
        self.allowed_fields = allowed_fields or ["close", "open", "high", "low", "volume", "vwap", "returns", "cap"]

    async def propose_turnover_reduction(
        self,
        expression_text: str,
        sharpe: float,
        fitness: float,
        turnover: float
    ) -> TurnoverOptimizationProposal:
        if not ai_manager.is_available("turnover_opt"):
            return self._heuristic_turnover_optimization(expression_text, sharpe, fitness, turnover)

        prompt = (
            f"High Quality / High Turnover Alpha:\n"
            f"Formula: '{expression_text}'\n"
            f"Sharpe: {sharpe:.3f} (PASSED), Fitness: {fitness:.3f} (PASSED), Turnover: {turnover:.2%} (EXCEEDED > 70% limit)\n\n"
            f"Propose controlled smoothing, exponential decay, or group neutralization experiments to reduce turnover while maintaining alpha.\n"
            f"Respond strictly with a JSON object adhering to TurnoverOptimizationProposal schema."
        )

        try:
            data, err = await ai_manager.execute_structured_request(
                feature_name="turnover_opt",
                prompt=prompt,
                system_prompt=TURNOVER_SYSTEM_PROMPT,
                temperature=0.2
            )
            if data and not err:
                experiments = []
                for exp in data.get("experiments", []):
                    experiments.append(ExperimentProposal(
                        type=exp.get("type", "SMOOTHING"),
                        transformation=exp.get("transformation", "ts_decay_linear"),
                        parameters=exp.get("parameters", {"window": 15}),
                        rationale=exp.get("rationale", "Turnover dampening")
                    ))
                return TurnoverOptimizationProposal(
                    candidate_expression=expression_text,
                    current_sharpe=sharpe,
                    current_fitness=fitness,
                    current_turnover=turnover,
                    recommended_techniques=data.get("recommended_techniques", ["ts_decay_linear", "group_neutralize"]),
                    experiments=experiments,
                    confidence=float(data.get("confidence", 0.85)),
                    explanation=data.get("explanation", "AI suggested decay and neutralization smoothing experiments.")
                )
        except Exception as e:
            logger.warning(f"TurnoverAgent failed: {e}. Using heuristic turnover mitigation.")

        return self._heuristic_turnover_optimization(expression_text, sharpe, fitness, turnover)

    def _heuristic_turnover_optimization(
        self,
        expression_text: str,
        sharpe: float,
        fitness: float,
        turnover: float
    ) -> TurnoverOptimizationProposal:
        experiments = [
            ExperimentProposal(
                type="SMOOTHING",
                transformation="ts_decay_linear",
                parameters={"window": 12},
                rationale="Apply 12-day linear decay to reduce transaction turnover."
            ),
            ExperimentProposal(
                type="NEUTRALIZATION",
                transformation="group_neutralize",
                parameters={"group": "subindustry"},
                rationale="Neutralize subindustry factor exposure to dampen sector rotations."
            )
        ]
        return TurnoverOptimizationProposal(
            candidate_expression=expression_text,
            current_sharpe=sharpe,
            current_fitness=fitness,
            current_turnover=turnover,
            recommended_techniques=["ts_decay_linear", "group_neutralize"],
            experiments=experiments,
            confidence=0.80,
            explanation="Deterministic heuristic smoothing rules applied to mitigate high turnover."
        )

    def generate_smoothed_candidates(
        self,
        expression_text: str,
        proposal: TurnoverOptimizationProposal
    ) -> List[str]:
        """Generates valid candidate child expressions based on the turnover optimization proposal."""
        results = []
        # Strategy 1: Decay linear wrap
        cand1 = f"ts_decay_linear({expression_text}, 11)"
        ok, _ = FormulaValidator.validate(cand1, self.allowed_fields)
        if ok and cand1 not in results:
            results.append(cand1)

        # Strategy 2: Group neutralize wrap
        if "group_neutralize" not in expression_text:
            cand2 = f"group_neutralize({expression_text}, subindustry)"
            ok, _ = FormulaValidator.validate(cand2, self.allowed_fields)
            if ok and cand2 not in results:
                results.append(cand2)

        # Strategy 3: Decay + neutralize combo
        cand3 = f"group_neutralize(ts_decay_linear({expression_text}, 10), subindustry)"
        ok, _ = FormulaValidator.validate(cand3, self.allowed_fields)
        if ok and cand3 not in results:
            results.append(cand3)

        return results
