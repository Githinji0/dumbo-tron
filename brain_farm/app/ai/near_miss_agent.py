import logging
import re
from typing import Dict, Any, Optional, List, Tuple
from brain_farm.app.ai.manager import ai_manager
from brain_farm.app.ai.schemas import NearMissProposal, ExperimentProposal
from brain_farm.app.ai.prompts import NEAR_MISS_SYSTEM_PROMPT
from brain_farm.app.evaluators.validator import FormulaValidator

logger = logging.getLogger("brain_farm.ai.near_miss")

class NearMissAgent:
    """Analyzes Tier 1 and Tier 2 near-miss candidates and proposes controlled surgical experiments."""

    def __init__(self, allowed_fields: Optional[List[str]] = None):
        self.allowed_fields = allowed_fields or ["close", "open", "high", "low", "volume", "vwap", "returns", "cap"]

    async def propose_experiments(
        self,
        expression_text: str,
        sharpe: float,
        fitness: float,
        turnover: float,
        margin: float,
        target_metric: str = "SHARPE"
    ) -> NearMissProposal:
        if not ai_manager.is_available("near_miss"):
            return self._heuristic_near_miss(expression_text, sharpe, fitness, turnover)

        prompt = (
            f"Candidate Expression: '{expression_text}'\n"
            f"Current Performance: Sharpe={sharpe:.3f}, Fitness={fitness:.3f}, Turnover={turnover:.2%}, Margin={margin:.2f} bps\n"
            f"Target to Improve: {target_metric}\n\n"
            f"Propose 1 to 3 controlled experiments to push candidate over target thresholds (Sharpe >= 1.25, Fitness >= 1.0, Turnover <= 0.70).\n"
            f"Respond strictly in JSON matching the NearMissProposal schema."
        )

        try:
            data, err = await ai_manager.execute_structured_request(
                feature_name="near_miss",
                prompt=prompt,
                system_prompt=NEAR_MISS_SYSTEM_PROMPT,
                temperature=0.2
            )
            if data and not err:
                experiments = []
                for exp in data.get("experiments", []):
                    experiments.append(ExperimentProposal(
                        type=exp.get("type", "SMOOTHING"),
                        transformation=exp.get("transformation", "ts_decay_linear"),
                        parameters=exp.get("parameters", {"window": 10}),
                        rationale=exp.get("rationale", "Near-miss refinement")
                    ))
                return NearMissProposal(
                    candidate_expression=expression_text,
                    target_metric_to_improve=target_metric,
                    experiments=experiments,
                    confidence=float(data.get("confidence", 0.75)),
                    reasoning=data.get("reasoning", "AI proposed surgical parameter and smoothing experiments.")
                )
        except Exception as e:
            logger.warning(f"NearMissAgent failed: {e}. Falling back to heuristic proposals.")

        return self._heuristic_near_miss(expression_text, sharpe, fitness, turnover)

    def _heuristic_near_miss(
        self,
        expression_text: str,
        sharpe: float,
        fitness: float,
        turnover: float
    ) -> NearMissProposal:
        experiments = []
        if turnover > 0.70:
            experiments.append(ExperimentProposal(
                type="SMOOTHING",
                transformation="ts_decay_linear",
                parameters={"window": 12},
                rationale="Apply linear decay to dampen trading turnover."
            ))
        if sharpe < 1.25:
            experiments.append(ExperimentProposal(
                type="RANKING",
                transformation="rank",
                parameters={},
                rationale="Wrap signal in cross-sectional rank to neutralize market beta."
            ))

        return NearMissProposal(
            candidate_expression=expression_text,
            target_metric_to_improve="SHARPE",
            experiments=experiments,
            confidence=0.70,
            reasoning="Heuristic near-miss refinement rules applied."
        )

    def apply_experiment_to_expression(
        self,
        expression_text: str,
        experiment: ExperimentProposal
    ) -> Optional[str]:
        """Applies a proposed experiment to generate a valid mutated child expression."""
        transformed = expression_text
        t_type = experiment.transformation.lower().strip()

        if t_type == "ts_decay_linear" or experiment.type == "SMOOTHING":
            win = experiment.parameters.get("window", 10)
            if "ts_decay_linear" not in expression_text:
                transformed = f"ts_decay_linear({expression_text}, {win})"
            else:
                transformed = re.sub(r"ts_decay_linear\((.+),\s*(\d+)\)", f"ts_decay_linear(\\1, {win})", expression_text)

        elif t_type == "rank" or experiment.type == "RANKING":
            if not expression_text.startswith("rank("):
                transformed = f"rank({expression_text})"

        elif t_type == "group_neutralize":
            if "group_neutralize" not in expression_text:
                transformed = f"group_neutralize({expression_text}, subindustry)"

        elif t_type == "ts_mean":
            win = experiment.parameters.get("window", 5)
            transformed = f"ts_mean({expression_text}, {win})"

        ok, _ = FormulaValidator.validate(transformed, self.allowed_fields)
        return transformed if ok else None
