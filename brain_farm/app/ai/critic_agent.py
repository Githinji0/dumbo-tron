import logging
from typing import Dict, Any, Optional, List
from brain_farm.app.ai.manager import ai_manager
from brain_farm.app.ai.schemas import CriticReview
from brain_farm.app.ai.prompts import CRITIC_SYSTEM_PROMPT

logger = logging.getLogger("brain_farm.ai.critic")

class CriticAgent:
    """Adversarial AI research critic that evaluates candidates for overfitting, parameter sensitivity, and complexity."""

    async def review_candidate(
        self,
        expression_text: str,
        sharpe: float,
        fitness: float,
        turnover: float,
        stability_score: float,
        robustness_score: float,
        parameter_sensitivity: Optional[Dict[str, Any]] = None,
        walk_forward_score: float = 0.0
    ) -> CriticReview:
        # Check for obvious parameter sensitivity red flags deterministically first
        has_sensitivity_penalty = False
        if parameter_sensitivity and parameter_sensitivity.get("penalty", 0.0) > 0.3:
            has_sensitivity_penalty = True

        if not ai_manager.is_available("critic"):
            return self._heuristic_critic_review(
                sharpe, fitness, turnover, stability_score, robustness_score, has_sensitivity_penalty, walk_forward_score
            )

        prompt = (
            f"Review Candidate Alpha Expression:\n"
            f"Formula: '{expression_text}'\n"
            f"Metrics: Sharpe={sharpe:.3f}, Fitness={fitness:.3f}, Turnover={turnover:.2%}\n"
            f"Stability Score: {stability_score:.2f}, Robustness: {robustness_score:.2f}, Walk-Forward: {walk_forward_score:.2f}\n"
            f"Parameter Sensitivity Details: {parameter_sensitivity or 'No sensitivity data'}\n\n"
            f"Critique this candidate for data mining bias, parameter cliffs, or overfitting risks.\n"
            f"Respond strictly in JSON adhering to the CriticReview schema."
        )

        try:
            data, err = await ai_manager.execute_structured_request(
                feature_name="critic",
                prompt=prompt,
                system_prompt=CRITIC_SYSTEM_PROMPT,
                temperature=0.2
            )
            if data and not err:
                return CriticReview(
                    risk_level=data.get("risk_level", "LOW"),
                    overfitting_probability=float(data.get("overfitting_probability", 0.2)),
                    parameter_sensitivity_warning=bool(data.get("parameter_sensitivity_warning", has_sensitivity_penalty)),
                    data_mining_bias_warning=bool(data.get("data_mining_bias_warning", False)),
                    critique=data.get("critique", "Adversarial review completed."),
                    recommendation=data.get("recommendation", "PASS_ROBUST"),
                    suggested_stress_tests=data.get("suggested_stress_tests", ["Walk-forward out-of-sample", "Sub-universe stability"])
                )
        except Exception as e:
            logger.warning(f"CriticAgent failed: {e}. Using heuristic review.")

        return self._heuristic_critic_review(
            sharpe, fitness, turnover, stability_score, robustness_score, has_sensitivity_penalty, walk_forward_score
        )

    def _heuristic_critic_review(
        self,
        sharpe: float,
        fitness: float,
        turnover: float,
        stability_score: float,
        robustness_score: float,
        has_sensitivity_penalty: bool,
        walk_forward_score: float
    ) -> CriticReview:
        if has_sensitivity_penalty or stability_score < 0.70:
            return CriticReview(
                risk_level="HIGH",
                overfitting_probability=0.65,
                parameter_sensitivity_warning=True,
                data_mining_bias_warning=False,
                critique="Candidate exhibits noticeable parameter sensitivity. Performance may degrade significantly under small perturbations.",
                recommendation="REQUIRE_ADDITIONAL_WALKFORWARD",
                suggested_stress_tests=["Parameter grid perturbation", "Sub-period walk-forward"]
            )
        elif sharpe > 2.2 and fitness > 1.8 and walk_forward_score < 0.6:
            return CriticReview(
                risk_level="MODERATE",
                overfitting_probability=0.50,
                parameter_sensitivity_warning=False,
                data_mining_bias_warning=True,
                critique="Exceptionally high in-sample performance combined with moderate walk-forward stability indicates potential curve-fitting.",
                recommendation="FLAG_SUSPICIOUS",
                suggested_stress_tests=["Extended out-of-sample test", "Sector rotation stress test"]
            )
        else:
            return CriticReview(
                risk_level="LOW",
                overfitting_probability=0.15,
                parameter_sensitivity_warning=False,
                data_mining_bias_warning=False,
                critique="Metrics indicate balanced performance and parameter stability across test regimes.",
                recommendation="PASS_ROBUST",
                suggested_stress_tests=["Standard sub-universe check"]
            )
