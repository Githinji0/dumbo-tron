import logging
import random
from typing import List, Dict, Any, Optional, Tuple
from brain_farm.app.ai.manager import ai_manager
from brain_farm.app.ai.schemas import ResearchHypothesis
from brain_farm.app.ai.prompts import HYPOTHESIS_SYSTEM_PROMPT
from brain_farm.app.evaluators.validator import FormulaValidator
from brain_farm.app.generators.family_info import FAMILY_CONFIGS, FAMILIES
from brain_farm.app.generators.family_gen import FamilyGenerator

logger = logging.getLogger("brain_farm.ai.hypothesis")

class HypothesisAgent:
    """Generates structured economic/quantitative research hypotheses and translates them into BRAIN expressions."""

    def __init__(self, allowed_fields: Optional[List[str]] = None):
        self.allowed_fields = allowed_fields or ["close", "open", "high", "low", "volume", "vwap", "returns", "cap"]

    async def generate_hypothesis(
        self,
        target_family: Optional[str] = None,
        market_regime: Optional[str] = None,
        context_notes: Optional[str] = None
    ) -> ResearchHypothesis:
        """
        Generates a validated structured hypothesis using AI or deterministic quantitative heuristics.
        """
        family = target_family if target_family in FAMILIES else random.choice(FAMILIES)
        fam_meta = FAMILY_CONFIGS.get(family, {})

        if not ai_manager.is_available("hypothesis"):
            return self._heuristic_hypothesis(family, fam_meta)

        fields_sample = random.sample(self.allowed_fields, min(len(self.allowed_fields), 10))
        prompt = (
            f"Generate a quantitative alpha hypothesis for research family: {family}.\n"
            f"Family Description: {fam_meta.get('description', '')}\n"
            f"Available Data Fields: {', '.join(fields_sample)}\n"
            f"Market Regime context: {market_regime or 'Normal / Cross-Sectional'}\n"
            f"Additional Context: {context_notes or 'Focus on robust information coefficient and low turnover.'}\n\n"
            f"Respond with a JSON object conforming strictly to the ResearchHypothesis schema."
        )

        try:
            data, err = await ai_manager.execute_structured_request(
                feature_name="hypothesis",
                prompt=prompt,
                system_prompt=HYPOTHESIS_SYSTEM_PROMPT,
                temperature=0.4
            )
            if data and not err:
                # Sanitize preferred fields against allowed fields
                valid_preferred = [f for f in data.get("preferred_fields", []) if f in self.allowed_fields]
                if not valid_preferred:
                    valid_preferred = fields_sample[:2]

                hypo = ResearchHypothesis(
                    family=family,
                    hypothesis=data.get("hypothesis", f"Hypothesis on {family} dynamics."),
                    horizon=data.get("horizon", "MEDIUM"),
                    preferred_fields=valid_preferred,
                    suggested_transformations=data.get("suggested_transformations", ["rank", "ts_decay_linear"]),
                    suggested_operators=data.get("suggested_operators", ["ts_mean", "rank"]),
                    reasoning=data.get("reasoning", "Economic foundation based on market microstructure."),
                    priority=float(data.get("priority", 0.8))
                )
                return hypo
        except Exception as e:
            logger.warning(f"HypothesisAgent AI generation failed: {e}. Falling back to heuristic hypothesis.")

        return self._heuristic_hypothesis(family, fam_meta)

    def _heuristic_hypothesis(self, family: str, fam_meta: Dict[str, Any]) -> ResearchHypothesis:
        """Deterministic research hypothesis generator when AI is disabled."""
        fields_sample = random.sample(self.allowed_fields, min(len(self.allowed_fields), 3))
        desc = fam_meta.get("description", f"Empirical {family} quantitative factor signals.")
        return ResearchHypothesis(
            family=family,
            hypothesis=f"Cross-sectional {family} variations provide statistically persistent risk-adjusted returns: {desc}",
            horizon="MEDIUM",
            preferred_fields=fields_sample,
            suggested_transformations=["rank", "ts_decay_linear", "group_neutralize"],
            suggested_operators=["ts_mean", "ts_delta", "rank"],
            reasoning=f"Established quantitative literature on {family} factors and cross-sectional asset pricing.",
            priority=0.75
        )

    def convert_hypothesis_to_expressions(
        self,
        hypothesis: ResearchHypothesis,
        count: int = 5
    ) -> List[str]:
        """
        Deterministically converts a structured hypothesis into validated WorldQuant BRAIN expressions.
        """
        family_gen = FamilyGenerator(self.allowed_fields)
        candidates: List[str] = []

        # Generate candidates from the targeted family
        generated = family_gen.generate(count=count * 3, family=hypothesis.family)

        for expr in generated:
            # Apply suggested transformations if appropriate
            transformed = expr
            if "ts_decay_linear" in hypothesis.suggested_transformations and "ts_decay_linear" not in transformed:
                transformed = f"ts_decay_linear({transformed}, 10)"
            elif "rank" in hypothesis.suggested_transformations and not transformed.startswith("rank("):
                transformed = f"rank({transformed})"

            ok, _ = FormulaValidator.validate(transformed, self.allowed_fields)
            if ok and transformed not in candidates:
                candidates.append(transformed)
            elif expr not in candidates:
                candidates.append(expr)

            if len(candidates) >= count:
                break

        return candidates[:count]
