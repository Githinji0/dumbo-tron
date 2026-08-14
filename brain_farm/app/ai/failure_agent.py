import logging
from typing import Dict, Any, Optional, List
from brain_farm.app.ai.manager import ai_manager
from brain_farm.app.ai.schemas import FailureAnalysis
from brain_farm.app.ai.prompts import FAILURE_ANALYSIS_SYSTEM_PROMPT

logger = logging.getLogger("brain_farm.ai.failure")

class FailureAgent:
    """Analyzes failed alpha simulations, diagnoses failure modes, and recommends directional shifts."""

    async def analyze_failure(
        self,
        expression_text: str,
        family: Optional[str],
        sharpe: float,
        fitness: float,
        turnover: float,
        margin: float,
        stability_score: float = 0.0,
        fail_details: Optional[str] = None
    ) -> FailureAnalysis:
        # Cost-control gating: immediately classify extreme negative / toxic alphas deterministically
        if sharpe < -0.5 and fitness < 0.0:
            return FailureAnalysis(
                classification="STRONG_FAILURE",
                likely_issue="Severe negative predictive power / inverse relationship to asset returns.",
                recommended_action="ABANDON",
                avoid=["direct sign inversion without fundamental justification", "minor parameter tweaks"],
                recommended_families=["QUALITY", "VALUE"],
                reasoning="Candidate exhibits strong negative returns across time and should be pruned to conserve budget."
            )

        if not ai_manager.is_available("failure_analysis"):
            return self._heuristic_failure_analysis(sharpe, fitness, turnover, margin, stability_score)

        prompt = (
            f"Analyze failed Alpha expression:\n"
            f"Formula: '{expression_text}'\n"
            f"Research Family: {family or 'UNKNOWN'}\n"
            f"Metrics: Sharpe={sharpe:.3f}, Fitness={fitness:.3f}, Turnover={turnover:.2%}, Margin={margin:.2f} bps, Stability={stability_score:.2f}\n"
            f"Failure Details: {fail_details or 'Failed target thresholds'}\n\n"
            f"Provide a structured diagnostic JSON response adhering to the FailureAnalysis schema."
        )

        try:
            data, err = await ai_manager.execute_structured_request(
                feature_name="failure_analysis",
                prompt=prompt,
                system_prompt=FAILURE_ANALYSIS_SYSTEM_PROMPT,
                temperature=0.2
            )
            if data and not err:
                return FailureAnalysis(
                    classification=data.get("classification", "WEAK_SIGNAL"),
                    likely_issue=data.get("likely_issue", "Sub-threshold signal-to-noise ratio."),
                    recommended_action=data.get("recommended_action", "CHANGE_HYPOTHESIS"),
                    avoid=data.get("avoid", []),
                    recommended_families=data.get("recommended_families", ["QUALITY", "VALUE"]),
                    reasoning=data.get("reasoning", "Statistical diagnostic assessment.")
                )
        except Exception as e:
            logger.warning(f"FailureAgent AI execution failed: {e}. Using heuristic failure diagnosis.")

        return self._heuristic_failure_analysis(sharpe, fitness, turnover, margin, stability_score)

    def _heuristic_failure_analysis(
        self,
        sharpe: float,
        fitness: float,
        turnover: float,
        margin: float,
        stability_score: float
    ) -> FailureAnalysis:
        if turnover > 1.2:
            return FailureAnalysis(
                classification="STRUCTURAL_DEFECT",
                likely_issue="Excessive turnover causing transaction cost drag.",
                recommended_action="APPLY_TRANSFORMATION",
                avoid=["short lookback delays without smoothing"],
                recommended_families=["VALUE", "QUALITY"],
                reasoning="Heuristic check identified unsustainable trading frequency."
            )
        elif sharpe < 0.8:
            return FailureAnalysis(
                classification="WEAK_SIGNAL",
                likely_issue="Low cross-sectional information coefficient.",
                recommended_action="CHANGE_FAMILY",
                avoid=["over-optimizing lookback windows"],
                recommended_families=["QUALITY", "MOMENTUM"],
                reasoning="Heuristic check recommends shifting research family to explore distinct signal sources."
            )
        else:
            return FailureAnalysis(
                classification="PARAMETER_MISMATCH",
                likely_issue="Near target thresholds but sub-optimal parameter tuning.",
                recommended_action="TUNE_HORIZON",
                avoid=["drastic operator replacements"],
                recommended_families=["VALUE"],
                reasoning="Candidate metrics are close to target thresholds; recommend incremental parameter optimization."
            )
