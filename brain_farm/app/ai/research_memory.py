import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from brain_farm.app.database.models import ResearchMemoryEntry, Expression, Simulation, Metric, Project
from brain_farm.app.generators.family_info import FAMILIES

logger = logging.getLogger("brain_farm.ai.research_memory")

class ResearchMemoryManager:
    """Aggregates and persists empirical research findings across alpha families and transformations."""

    @staticmethod
    async def record_simulation_outcome(
        db: AsyncSession,
        family: Optional[str],
        transformation: Optional[str],
        sharpe: float,
        fitness: float,
        turnover: float,
        stability: float,
        passed: bool,
        project_id: Optional[int] = None
    ):
        if not family:
            family = "UNCLASSIFIED"

        try:
            # Query existing memory entry
            stmt = select(ResearchMemoryEntry).where(
                ResearchMemoryEntry.family == family,
                ResearchMemoryEntry.transformation == transformation,
                ResearchMemoryEntry.project_id == project_id
            )
            result = await db.execute(stmt)
            entry = result.scalar_one_or_none()

            if not entry:
                entry = ResearchMemoryEntry(
                    project_id=project_id,
                    family=family,
                    transformation=transformation,
                    applications_count=1,
                    fitness_improved_count=1 if fitness >= 1.0 else 0,
                    turnover_reduced_count=1 if turnover <= 0.70 else 0,
                    sharpe_preserved_count=1 if sharpe >= 1.25 else 0,
                    avg_stability=stability,
                    notes=f"Initial empirical record for {family} / {transformation or 'RAW'}"
                )
                db.add(entry)
            else:
                entry.applications_count += 1
                if fitness >= 1.0:
                    entry.fitness_improved_count += 1
                if turnover <= 0.70:
                    entry.turnover_reduced_count += 1
                if sharpe >= 1.25:
                    entry.sharpe_preserved_count += 1
                # Exponential moving average for stability
                entry.avg_stability = float(0.8 * entry.avg_stability + 0.2 * stability)
                entry.updated_at = datetime.utcnow()

            await db.commit()
        except Exception as e:
            logger.error(f"Error recording research memory: {e}")

    @staticmethod
    async def get_memory_summary(db: AsyncSession, project_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Generates a concise statistical summary of historical research for the AI Director.
        """
        summary: Dict[str, Any] = {
            "families": {},
            "top_transformations": [],
            "promising_rate_overall": 0.0,
            "total_recorded_experiments": 0
        }

        try:
            # Aggregation by research_family
            for fam in FAMILIES:
                expr_count_res = await db.execute(
                    select(func.count(Expression.id))
                    .where(Expression.research_family == fam)
                    .where(Expression.project_id == project_id if project_id else True)
                )
                total_fam = expr_count_res.scalar() or 0

                passed_count_res = await db.execute(
                    select(func.count(Expression.id))
                    .where(Expression.research_family == fam)
                    .where(Expression.status == "PASSED")
                    .where(Expression.project_id == project_id if project_id else True)
                )
                passed_fam = passed_count_res.scalar() or 0

                summary["families"][fam] = {
                    "total_experiments": total_fam,
                    "passed_count": passed_fam,
                    "pass_rate": round(passed_fam / max(1, total_fam), 3),
                    "promising_rate": round((passed_fam * 1.5) / max(1, total_fam), 3)
                }
                summary["total_recorded_experiments"] += total_fam

            # Transformation efficacy summary
            stmt_trans = (
                select(ResearchMemoryEntry)
                .where(ResearchMemoryEntry.project_id == project_id if project_id else True)
                .order_by(ResearchMemoryEntry.applications_count.desc())
                .limit(8)
            )
            res_trans = await db.execute(stmt_trans)
            entries = res_trans.scalars().all()
            for e in entries:
                summary["top_transformations"].append({
                    "family": e.family,
                    "transformation": e.transformation or "RAW",
                    "applications": e.applications_count,
                    "sharpe_success_rate": round(e.sharpe_preserved_count / max(1, e.applications_count), 2),
                    "turnover_success_rate": round(e.turnover_reduced_count / max(1, e.applications_count), 2),
                    "avg_stability": round(e.avg_stability, 2)
                })

        except Exception as e:
            logger.error(f"Error compiling research memory summary: {e}")

        return summary
