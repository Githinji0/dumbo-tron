import logging
from typing import Dict, Any, Optional, List
from brain_farm.app.ai.manager import ai_manager
from brain_farm.app.ai.schemas import ResearchDirectorPlan, ResearchHypothesis
from brain_farm.app.ai.prompts import RESEARCH_DIRECTOR_SYSTEM_PROMPT
from brain_farm.app.generators.family_info import FAMILIES

logger = logging.getLogger("brain_farm.ai.director")

class ResearchDirector:
    """Strategic AI Research Director synthesizing research memory into allocation plans and agendas."""

    async def formulate_research_plan(
        self,
        memory_summary: Dict[str, Any],
        total_budget: int = 100,
        allowed_fields: Optional[List[str]] = None
    ) -> ResearchDirectorPlan:
        if not ai_manager.is_available("director"):
            return self._heuristic_director_plan(memory_summary, total_budget)

        prompt = (
            f"Current Empirical Research Summary across Alpha Families:\n"
            f"{memory_summary}\n\n"
            f"Available Simulation Budget: {total_budget} experiments.\n\n"
            f"Synthesize a prioritized allocation plan and 2-3 novel hypotheses across families.\n"
            f"Respond strictly in JSON matching the ResearchDirectorPlan schema."
        )

        try:
            data, err = await ai_manager.execute_structured_request(
                feature_name="director",
                prompt=prompt,
                system_prompt=RESEARCH_DIRECTOR_SYSTEM_PROMPT,
                temperature=0.3
            )
            if data and not err:
                alloc = data.get("recommended_allocation", {})
                # Normalize allocation to total_budget if needed
                sum_alloc = sum(alloc.values()) if alloc else 0
                if sum_alloc > 0:
                    normalized_alloc = {k: int((v / sum_alloc) * total_budget) for k, v in alloc.items()}
                else:
                    normalized_alloc = self._default_allocation(total_budget)

                hypotheses = []
                for h in data.get("priority_hypotheses", []):
                    hypotheses.append(ResearchHypothesis(
                        family=h.get("family", "VALUE"),
                        hypothesis=h.get("hypothesis", "Dynamic factor allocation hypothesis"),
                        horizon=h.get("horizon", "MEDIUM"),
                        preferred_fields=h.get("preferred_fields", ["close", "volume"]),
                        suggested_transformations=h.get("suggested_transformations", ["rank", "ts_decay_linear"]),
                        reasoning=h.get("reasoning", "Strategic director recommendation"),
                        priority=float(h.get("priority", 0.85))
                    ))

                return ResearchDirectorPlan(
                    strategic_summary=data.get("strategic_summary", "Strategic multi-family alpha exploration plan."),
                    recommended_allocation=normalized_alloc,
                    priority_hypotheses=hypotheses,
                    research_gaps=data.get("research_gaps", []),
                    confidence=float(data.get("confidence", 0.80))
                )
        except Exception as e:
            logger.warning(f"ResearchDirector AI execution failed: {e}. Falling back to heuristic strategy.")

        return self._heuristic_director_plan(memory_summary, total_budget)

    def _heuristic_director_plan(self, memory_summary: Dict[str, Any], total_budget: int) -> ResearchDirectorPlan:
        alloc = self._default_allocation(total_budget)
        return ResearchDirectorPlan(
            strategic_summary="Deterministic balanced allocation prioritizing established Value and Quality factors alongside Momentum exploration.",
            recommended_allocation=alloc,
            priority_hypotheses=[
                ResearchHypothesis(
                    family="VALUE",
                    hypothesis="Medium-term valuation signals combined with liquidity normalization provide consistent Sharpe ratio.",
                    horizon="MEDIUM",
                    preferred_fields=["close", "volume", "vwap"],
                    suggested_transformations=["rank", "ts_decay_linear"],
                    reasoning="Heuristic strategic baseline",
                    priority=0.85
                ),
                ResearchHypothesis(
                    family="QUALITY",
                    hypothesis="Fundamental quality factor stability across market sub-industries.",
                    horizon="LONG",
                    preferred_fields=["close", "cap"],
                    suggested_transformations=["group_neutralize", "rank"],
                    reasoning="Heuristic strategic baseline",
                    priority=0.80
                )
            ],
            research_gaps=["Exploration of novel analyst sentiment combinations", "Short-term mean-reversion stability"],
            confidence=0.75
        )

    def _default_allocation(self, total_budget: int) -> Dict[str, int]:
        """Provides balanced deterministic allocation across core families."""
        weights = {"VALUE": 0.30, "QUALITY": 0.25, "MOMENTUM": 0.20, "REVERSAL": 0.15, "ANALYST": 0.10}
        return {fam: max(1, int(w * total_budget)) for fam, w in weights.items()}
