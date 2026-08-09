import random
import numpy as np
from typing import Dict, List, Any
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from brain_farm.app.database.models import Expression, Simulation, Metric
from brain_farm.app.generators.family_info import RESEARCH_FAMILIES

class ResearchPriorityEngine:
    """
    Tracks success rates and performance statistics per research family,
    and dynamically allocates generation slots based on:
    - 70% Exploitation of successful families
    - 20% Exploration of random families
    - 10% Neglected families
    """

    @classmethod
    async def get_family_performance_stats(cls, project_id: int, db: AsyncSession) -> Dict[str, Dict[str, Any]]:
        """
        Queries all expressions in the project and groups them by family to calculate:
        count, success_rate, and mean_sharpe.
        """
        stmt = (
            select(Expression)
            .options(selectinload(Expression.simulations).selectinload(Simulation.metrics))
            .where(Expression.project_id == project_id)
            .where(Expression.research_family.isnot(None))
        )
        res = await db.execute(stmt)
        exprs = res.scalars().all()

        stats = {fam: {"count": 0, "passed": 0, "sharpes": []} for fam in RESEARCH_FAMILIES.keys()}

        for expr in exprs:
            fam = expr.research_family
            if fam not in stats:
                stats[fam] = {"count": 0, "passed": 0, "sharpes": []}
            
            stats[fam]["count"] += 1
            if expr.status == "PASSED":
                stats[fam]["passed"] += 1
            
            # Find associated metrics
            for sim in expr.simulations:
                if sim.metrics:
                    stats[fam]["sharpes"].append(sim.metrics.sharpe)

        output = {}
        for fam, data in stats.items():
            count = data["count"]
            passed = data["passed"]
            sharpes = data["sharpes"]
            
            success_rate = (passed / count) if count > 0 else 0.0
            mean_sharpe = float(np.mean(sharpes)) if sharpes else 0.0
            
            output[fam] = {
                "count": count,
                "success_rate": success_rate,
                "mean_sharpe": mean_sharpe
            }
            
        return output

    @classmethod
    async def allocate_generation_slots(cls, project_id: int, count: int, db: AsyncSession) -> Dict[str, int]:
        """
        Allocates 'count' generation slots to research families.
        Returns a mapping of family_name -> number of slots allocated.
        """
        stats = await cls.get_family_performance_stats(project_id, db)
        families = list(RESEARCH_FAMILIES.keys())

        # Determine exploitation, exploration, and neglected families
        # Top-performing: sorted by mean sharpe then success rate
        sorted_by_perf = sorted(
            families,
            key=lambda f: (stats[f]["mean_sharpe"], stats[f]["success_rate"]),
            reverse=True
        )
        
        # Successful families: those with positive Sharpe or success > 0
        successful = [f for f in sorted_by_perf if stats[f]["mean_sharpe"] > 0.0 or stats[f]["success_rate"] > 0.0]
        
        allocations = {fam: 0 for fam in families}

        for _ in range(count):
            r = random.random()
            
            # 1. 70% Exploitation
            if r < 0.70 and successful:
                # Randomly pick from top 3 successful or all successful if < 3
                top_size = min(3, len(successful))
                chosen = random.choice(successful[:top_size])
                
            # 2. 10% Neglected (or if no successful families yet)
            elif r >= 0.90 or not successful:
                # Sort families by count ascending to find neglected ones
                neglected_candidates = sorted(families, key=lambda f: stats[f]["count"])
                # Select randomly among the ones with the lowest count (tie-breaker)
                min_count = stats[neglected_candidates[0]]["count"]
                min_count_fams = [f for f in families if stats[f]["count"] == min_count]
                chosen = random.choice(min_count_fams)
                
            # 3. 20% Exploration
            else:
                chosen = random.choice(families)

            allocations[chosen] += 1

        # Filter out families with 0 allocations
        return {fam: n for fam, n in allocations.items() if n > 0}
