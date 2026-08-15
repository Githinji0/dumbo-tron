import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from brain_farm.app.database.models import Expression, Metric, Simulation
from brain_farm.app.services.correlation_filter import CorrelationFilter

class WeightedCompositeScorer:
    """
    Calculates a composite rating score for alpha candidates using a multi-factor model:
    Score = 0.40 * Research + 0.25 * Robustness + 0.20 * Diversity + 0.15 * Simplicity
    """

    @staticmethod
    def calculate_research_score(sharpe: float, fitness: float) -> float:
        """
        Combines Sharpe and Fitness. Scales to [0.0, 1.0].
        A Sharpe of 3.0 and Fitness of 3.0 represent a perfect 1.0 research score.
        """
        s_score = max(0.0, min(1.0, sharpe / 3.0))
        f_score = max(0.0, min(1.0, fitness / 3.0))
        return float((s_score + f_score) / 2.0)

    @staticmethod
    def calculate_robustness_score(walk_forward_score: float, regime_score: float) -> float:
        """
        Averages walk-forward test stability and regime consistency.
        """
        return float((walk_forward_score + regime_score) / 2.0)

    @classmethod
    async def calculate_diversity_score(cls, expr_text: str, project_id: int, db: AsyncSession) -> float:
        """
        Computes diversity as: 1.0 - mean absolute correlation to other PASSED alphas in the project.
        If no other PASSED alphas exist, returns 1.0.
        """
        stmt = (
            select(Expression.expression_text)
            .where(Expression.project_id == project_id)
            .where(Expression.status == "PASSED")
            .where(Expression.expression_text != expr_text)
            .limit(30)
        )
        res = await db.execute(stmt)
        other_exprs = res.scalars().all()

        if not other_exprs:
            return 1.0

        def _calc_corrs(target: str, pool: list) -> float:
            corrs = []
            for other in pool:
                c = CorrelationFilter.calculate_correlation(target, other)
                corrs.append(abs(c))
            return float(np.mean(corrs)) if corrs else 0.0

        import asyncio
        loop = asyncio.get_running_loop()
        mean_corr = await loop.run_in_executor(None, _calc_corrs, expr_text, list(other_exprs))
        return max(0.0, min(1.0, 1.0 - mean_corr))

    @staticmethod
    def calculate_simplicity_score(complexity_score: float) -> float:
        """
        Linear decay: simplicity decreases as complexity increases.
        Complexity of 1.0 yields 1.0 simplicity. Complexity >= 20.0 yields 0.05 simplicity.
        """
        if complexity_score is None:
            complexity_score = 3.0
        score = 1.0 - (complexity_score - 1.0) / 19.0
        return float(max(0.05, min(1.0, score)))

    @classmethod
    async def compute_composite_score(
        cls,
        expr_text: str,
        project_id: int,
        sharpe: float,
        fitness: float,
        walk_forward_score: float,
        regime_score: float,
        complexity_score: float,
        db: AsyncSession
    ) -> dict:
        """
        Performs full composite scoring and returns all breakdown metrics.
        """
        from brain_farm.app.services.sensitivity import ParameterSensitivityTester

        research = cls.calculate_research_score(sharpe, fitness)
        robustness = cls.calculate_robustness_score(walk_forward_score, regime_score)
        
        # Calculate parameter sensitivity penalty
        sensitivity_penalty = ParameterSensitivityTester.evaluate_sensitivity_penalty(expr_text, sharpe)
        robustness = robustness * sensitivity_penalty

        diversity = await cls.calculate_diversity_score(expr_text, project_id, db)
        simplicity = cls.calculate_simplicity_score(complexity_score)

        composite = (
            0.40 * research +
            0.25 * robustness +
            0.20 * diversity +
            0.15 * simplicity
        )

        return {
            "research_score": research,
            "robustness_score": robustness,
            "diversity_score": diversity,
            "simplicity_score": simplicity,
            "composite_score": float(composite)
        }

    @classmethod
    async def compute_alpha_research_score(
        cls,
        expr_text: str,
        project_id: int,
        sharpe: float,
        fitness: float,
        turnover: float,
        stability: float,
        robustness: float,
        complexity_score: float,
        db: AsyncSession
    ) -> dict:
        """
        Calculates the upgraded ALPHA_RESEARCH_SCORE:
        0.30 * Sharpe + 0.25 * Fitness + 0.15 * Turnover + 0.10 * Stability + 0.10 * Robustness + 0.05 * Diversity + 0.05 * Simplicity
        Also returns all normalized metrics.
        """
        # 1. Normalization
        norm_sharpe = float(min(max(sharpe, 0.0), 3.0) / 3.0)
        norm_fitness = float(min(max(fitness, 0.0), 3.0) / 3.0)
        # Lower turnover -> higher value
        norm_turnover = float(max(0.0, 1.0 - min(turnover, 1.0)))
        norm_stability = float(min(max(stability, 0.0), 1.0))
        norm_robustness = float(min(max(robustness, 0.0), 1.0))
        
        # Reuse existing functions for diversity and simplicity
        norm_diversity = await cls.calculate_diversity_score(expr_text, project_id, db)
        norm_simplicity = cls.calculate_simplicity_score(complexity_score)
        
        score = (
            0.30 * norm_sharpe +
            0.25 * norm_fitness +
            0.15 * norm_turnover +
            0.10 * norm_stability +
            0.10 * norm_robustness +
            0.05 * norm_diversity +
            0.05 * norm_simplicity
        )
        
        return {
            "normalized_sharpe": norm_sharpe,
            "normalized_fitness": norm_fitness,
            "normalized_turnover": norm_turnover,
            "normalized_stability": norm_stability,
            "normalized_robustness": norm_robustness,
            "normalized_diversity": norm_diversity,
            "normalized_simplicity": norm_simplicity,
            "alpha_research_score": float(score)
        }
