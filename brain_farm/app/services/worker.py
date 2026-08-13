import asyncio
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from brain_farm.app.database.session import AsyncSessionLocal
from brain_farm.app.database.models import Project, Expression, Simulation, Metric, User, ProjectLog
from brain_farm.app.services.brain_client import BrainClient
from brain_farm.app.services.auto_optimizer import AutoOptimizer

logger = logging.getLogger("brain_farm.worker")

class SimulationWorker:
    """Background task simulator worker executing posts, status polling loops, and metric extraction."""

    def __init__(self, concurrency_limit: int = 5):
        self.concurrency_limit = concurrency_limit
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._active_clients: Dict[int, BrainClient] = {}  # Cache clients by User ID to avoid re-auth

    def inject_client(self, user_id: int, client: "BrainClient") -> None:
        """
        Register an already-authenticated BrainClient from the UI session.
        This avoids the worker re-authenticating from scratch (which would hang
        on the live BRAIN streaming GET).
        Called immediately after a successful login in main.py.
        """
        self._active_clients[user_id] = client
        logger.info(f"Injected authenticated client for user_id={user_id} (live={not client.use_mock})")

    async def get_client_for_user(self, user_id: int) -> Optional[BrainClient]:
        """Returns the injected authenticated BrainClient for a user, or None.

        NOTE: The worker never attempts automatic re-authentication. The live
        BRAIN API requires an OTP delivered via email, which cannot be handled
        in the background. When the session is gone, simulations are marked as
        NEEDS_AUTH and will be retried automatically once the user logs in again
        through the UI Auth panel.
        """
        if user_id in self._active_clients:
            client = self._active_clients[user_id]
            if client.is_authenticated:
                return client
            # Session flagged as expired — evict so the UI can inject a fresh one.
            logger.warning(
                f"Worker: Cached session for user_id={user_id} is no longer valid. "
                "Please re-authenticate through the UI Auth panel."
            )
            del self._active_clients[user_id]

        # No valid session available — cannot re-auth automatically (OTP required).
        logger.error(
            f"Worker: No valid session for user_id={user_id}. "
            "Simulations will be held as NEEDS_AUTH until the user re-authenticates."
        )
        return None



    async def start(self):
        """Starts the background processing loops."""
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._main_loop())
        logger.info("Background simulation worker started.")

    async def stop(self):
        """Stops the worker loop."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Clear clients cache
        for client in self._active_clients.values():
            if client.client:
                await client.client.aclose()
        self._active_clients.clear()
        logger.info("Background simulation worker stopped.")

    async def _main_loop(self):
        while self.running:
            try:
                await self.process_pending_expressions()
                await self.process_queued_simulations()
                await self.poll_active_simulations()
            except Exception as e:
                logger.error(f"Error in worker main loop: {e}", exc_info=True)
            await asyncio.sleep(2.0)

    async def process_pending_expressions(self):
        """Finds Expression records in PENDING status and creates Simulation tasks for them."""
        async with AsyncSessionLocal() as db:
            # Query expressions needing simulation
            result = await db.execute(
                select(Expression)
                .where(Expression.status == "PENDING")
                .limit(20)
            )
            exprs = result.scalars().all()
            
            if not exprs:
                return

            from brain_farm.app.services.correlation_filter import CorrelationFilter
            from brain_farm.app.services.field_manager import FieldManager
            from brain_farm.app.evaluators.pre_screen import StatisticalPreScreen
            
            fields = await FieldManager.get_all_fields(db)
            field_ids = [f.id for f in fields]

            for expr in exprs:
                # 1. Run local pre-screening checks
                passed_screen, screen_reason = StatisticalPreScreen.pre_screen(expr.expression_text, field_ids)
                if not passed_screen:
                    expr.status = "REJECTED"
                    log = ProjectLog(
                        project_id=expr.project_id,
                        level="WARNING",
                        message=(
                            f"Pre-Screen Filter: Rejected custom expression!\n"
                            f"Formula: '{expr.expression_text}'\n"
                            f"Reason: {screen_reason}\n"
                            f"Advice: Adjust nesting depths, remove duplicate functions (e.g. rank(rank(x))), or utilize supported functions."
                        )
                    )
                    db.add(log)
                    logger.warning(f"Pre-Screen Filter: Rejected expression {expr.id} -> {screen_reason}")
                    continue

                # 2. Fast local database checking against ALL expressions (not just PASSED)
                dup_res = await db.execute(
                    select(Expression)
                    .where(Expression.project_id == expr.project_id)
                    .where(Expression.expression_text == expr.expression_text)
                    .where(Expression.id < expr.id)
                    .limit(1)
                )
                duplicate = dup_res.scalar_one_or_none()
                if duplicate:
                    expr.status = "REJECTED"
                    reason = f"Duplicate of existing expression ID {duplicate.id} (Status: {duplicate.status})"
                    log = ProjectLog(
                        project_id=expr.project_id,
                        level="WARNING",
                        message=(
                            f"Duplicate Checker: Rejected custom expression!\n"
                            f"Formula: '{expr.expression_text}'\n"
                            f"Reason: {reason}\n"
                            f"Advice: Modify parameters (e.g., lookback windows), swap operators, or pick distinct fields from the catalog."
                        )
                    )
                    db.add(log)
                    logger.warning(f"Duplicate Checker: Rejected expression {expr.id} -> {reason}")
                    continue

                # Query already PASSED expressions in the projects pool to match against
                passed_res = await db.execute(
                    select(Expression.expression_text)
                    .where(Expression.project_id == expr.project_id)
                    .where(Expression.status == "PASSED")
                )
                passed_formulas = [r[0] for r in passed_res.all()]
                
                is_redundant = False
                reason = ""

                def _run_correlation_check(expr_text: str, passed_list: list) -> tuple[bool, str]:
                    """CPU-bound correlation checks — run inside a thread pool."""
                    from brain_farm.app.services.correlation_filter import CorrelationFilter
                    for passed in passed_list:
                        if expr_text.strip() == passed.strip():
                            return True, "Exact duplicate of a passed Alpha expression"
                        corr = CorrelationFilter.calculate_correlation(expr_text, passed)
                        if abs(corr) > 0.85:
                            return True, f"Highly correlated (Pearson = {corr:.2f}) with passed Alpha: '{passed[:30]}...'"
                        jacc = CorrelationFilter.calculate_ast_similarity(expr_text, passed)
                        if jacc > 0.90:
                            return True, f"Syntactically redundant (Jaccard = {jacc:.2f}) with passed Alpha: '{passed[:30]}...'"
                    return False, ""

                loop = asyncio.get_event_loop()
                is_redundant, reason = await loop.run_in_executor(
                    None, _run_correlation_check, expr.expression_text, passed_formulas
                )

                if is_redundant:
                    expr.status = "REJECTED"
                    
                    # Add project warning log
                    log = ProjectLog(
                        project_id=expr.project_id,
                        level="WARNING",
                        message=(
                            f"Correlation Filter: Rejected custom expression!\n"
                            f"Formula: '{expr.expression_text}'\n"
                            f"Reason: {reason}\n"
                            f"Advice: Try adding decays, neutralize with distinct sector parameters, or use a crossover strategy to diversify correlation profiles."
                        )
                    )
                    db.add(log)
                    logger.warning(f"Correlation Filter: Rejected expression {expr.id} -> {reason}")
                    continue

                # Mark expression as SIMULATING
                expr.status = "SIMULATING"
                # Create a Simulation run record
                sim = Simulation(
                    expression_id=expr.id,
                    status="QUEUED"
                )
                db.add(sim)
                
                logger.info(f"Queued simulation for Alpha expr: {expr.expression_text}")
                
            await db.commit()

    async def process_queued_simulations(self):
        """Checks for QUEUED simulations and posts them to WorldQuant BRAIN."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Simulation)
                .join(Expression)
                .join(Project)
                .options(selectinload(Simulation.expression).selectinload(Expression.project))
                .where(Simulation.status == "QUEUED")
                .limit(10)
            )
            sims = result.scalars().all()

            for sim in sims:
                # Dispatch sim submission to run in background concurrently with semaphore protection
                asyncio.create_task(self._submit_simulation_task(sim.id))

    async def _submit_simulation_task(self, sim_id: int):
        async with self.semaphore:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Simulation)
                    .join(Expression)
                    .join(Project)
                    .options(selectinload(Simulation.expression).selectinload(Expression.project))
                    .where(Simulation.id == sim_id)
                )
                sim = result.scalar_one_or_none()
                if not sim or sim.status != "QUEUED":
                    return

                # Transition immediately to SUBMITTING to prevent other tasks from picking it up
                sim.status = "SUBMITTING"
                await db.commit()

                expr = sim.expression
                proj = expr.project
                
                # Get authenticated client
                client = await self.get_client_for_user(proj.user_id)
                if not client:
                    sim.status = "NEEDS_AUTH"
                    sim.error_message = "Session expired. Please re-authenticate in the UI Auth panel."
                    await db.commit()
                    return

                # Build simulation settings
                settings_dict = {
                    "region": proj.region,
                    "universe": proj.universe,
                    "neutralization": proj.neutralization,
                    "delay": proj.delay,
                    "decay": proj.decay
                }
                
                # Submit simulation
                brain_sim_id, err = await client.submit_simulation(expr.expression_text, settings_dict)
                
                if err:
                    if "RATE_LIMIT" in err:
                        # Extract backoff timer in headers
                        backoff = int(err.split(":")[-1])
                        logger.warning(f"Submission rate-limited. Backing off for {backoff} seconds.")
                        await asyncio.sleep(backoff)
                        
                        # Re-open session to transition back to QUEUED
                        async with AsyncSessionLocal() as db2:
                            await db2.execute(
                                update(Simulation)
                                .where(Simulation.id == sim_id)
                                .values(status="QUEUED")
                            )
                            await db2.commit()
                    elif "re-authenticate" in err.lower() or "session expired" in err.lower():
                        # Session died mid-flight — hold sim for retry, evict stale client
                        sim.status = "NEEDS_AUTH"
                        sim.error_message = err
                        expr.status = "PENDING"  # Reset so it's re-queued after re-auth
                        self._active_clients.pop(proj.user_id, None)
                        logger.warning(
                            f"Session expired for user_id={proj.user_id} during submission. "
                            "Sim held as NEEDS_AUTH. User must re-authenticate."
                        )
                        await db.commit()
                    else:
                        sim.status = "ERROR"
                        sim.error_message = err
                        expr.status = "ERROR"
                        
                        log = ProjectLog(
                            project_id=proj.id,
                            level="ERROR",
                            message=f"Simulation submit failed for '{expr.expression_text[:30]}...': {err}"
                        )
                        db.add(log)
                        await db.commit()
                else:
                    sim.brain_simulation_id = brain_sim_id
                    sim.status = "POLLING"
                    await db.commit()

    async def poll_active_simulations(self):
        """Polls status of simulations currently in POLLING state.
        Also re-queues NEEDS_AUTH sims if a fresh session has been injected.
        """
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Simulation)
                .join(Expression)
                .join(Project)
                .options(selectinload(Simulation.expression).selectinload(Expression.project))
                .where(Simulation.status.in_(["POLLING", "NEEDS_AUTH"]))
                .limit(20)
            )
            sims = result.scalars().all()

            for sim in sims:
                if sim.status == "NEEDS_AUTH":
                    # Only retry if a fresh session has been injected since the failure
                    proj = sim.expression.project
                    if proj.user_id in self._active_clients and self._active_clients[proj.user_id].is_authenticated:
                        sim.status = "QUEUED"
                        sim.error_message = None
                        logger.info(f"NEEDS_AUTH sim {sim.id} re-queued after session restored.")
                    continue  # Don't poll a sim with no brain_simulation_id

                # Launch async status checker for POLLING sims
                asyncio.create_task(self._poll_simulation_task(sim.id))

            await db.commit()

    async def _poll_simulation_task(self, sim_id: int):
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Simulation)
                .join(Expression)
                .join(Project)
                .options(selectinload(Simulation.expression).selectinload(Expression.project))
                .where(Simulation.id == sim_id)
            )
            sim = result.scalar_one_or_none()
            if not sim or sim.status != "POLLING" or not sim.brain_simulation_id:
                return

            expr = sim.expression
            proj = expr.project
            
            client = await self.get_client_for_user(proj.user_id)
            if not client:
                return

            # Check status on BRAIN API
            data, err = await client.get_simulation_status(sim.brain_simulation_id)
            
            if err:
                sim.retry_count += 1
                if sim.retry_count > 5:
                    sim.status = "ERROR"
                    sim.error_message = f"Max polling failures reached: {err}"
                    expr.status = "ERROR"
                await db.commit()
                return

            status = data.get("status")
            TERMINAL_SUCCESS = {"COMPLETE", "OK", "DONE", "WARNING"}
            TERMINAL_FAILURE = {"ERROR", "FAILED", "CANCELLED"}

            if status in TERMINAL_SUCCESS:
                # Simulation finished! Parse metrics
                sim.status = "COMPLETE"
                sim.brain_alpha_id = data.get("alpha")
                
                # Fetch IS metrics details
                is_data = data.get("is", {})
                sharpe = float(is_data.get("sharpe", 0.0))
                fitness = float(is_data.get("fitness", 0.0))
                turnover = float(is_data.get("turnover", 0.0))
                returns = float(is_data.get("returns", 0.0))
                margin = float(is_data.get("margin", 0.0))
                drawdown = float(is_data.get("drawdown", 0.0)) if is_data.get("drawdown") else 0.0
                
                # Compute advanced Phase 3 metrics
                from brain_farm.app.services.ic_calculator import ICCalculator
                from brain_farm.app.services.walk_forward import WalkForwardTester
                from brain_farm.app.services.regime_analyzer import RegimeAnalyzer
                from brain_farm.app.services.composite_scorer import WeightedCompositeScorer
                
                ic_m = ICCalculator.calculate_ic_metrics(expr.expression_text, sharpe)
                wf_m = WalkForwardTester.evaluate_walk_forward(expr.expression_text, sharpe)
                reg_m = RegimeAnalyzer.evaluate_regimes(expr.expression_text, sharpe)
                
                comp_res = await WeightedCompositeScorer.compute_composite_score(
                    expr_text=expr.expression_text,
                    project_id=proj.id,
                    sharpe=sharpe,
                    fitness=fitness,
                    walk_forward_score=wf_m["walk_forward_score"],
                    regime_score=reg_m["regime_score"],
                    complexity_score=expr.complexity_score,
                    db=db
                )

                # Compute and populate parameter sensitivity and regime Performance JSON values
                from brain_farm.app.services.sensitivity import ParameterSensitivityTester
                from brain_farm.app.services.correlation_filter import CorrelationFilter
                import numpy as np
                perturbed = ParameterSensitivityTester.generate_perturbed_expressions(expr.expression_text)
                p_corrs = []
                for p_expr in perturbed:
                    p_corr = CorrelationFilter.calculate_correlation(expr.expression_text, p_expr)
                    p_corrs.append({"expression": p_expr, "correlation": float(p_corr)})
                
                stability_score = float(np.mean([abs(c["correlation"]) for c in p_corrs])) if p_corrs else 1.0
                
                expr.parameter_sensitivity = {
                    "penalty": float(ParameterSensitivityTester.evaluate_sensitivity_penalty(expr.expression_text, sharpe)),
                    "correlations": p_corrs
                }
                
                expr.regime_performance = {
                    "sharpe_run_low": float(reg_m["sharpe_run_low"]),
                    "sharpe_run_high": float(reg_m["sharpe_run_high"])
                }
                
                # Robustness score combines walk forward, stability, and regime scores
                robustness_score = float(0.40 * wf_m["walk_forward_score"] + 0.30 * stability_score + 0.30 * reg_m["regime_score"])
                
                diversity_score = float(comp_res["diversity_score"])
                simplicity_score = float(comp_res["simplicity_score"])
                
                # Upgraded multi-factor research score
                alpha_res = await WeightedCompositeScorer.compute_alpha_research_score(
                    expr_text=expr.expression_text,
                    project_id=proj.id,
                    sharpe=sharpe,
                    fitness=fitness,
                    turnover=turnover,
                    stability=stability_score,
                    robustness=robustness_score,
                    complexity_score=expr.complexity_score,
                    db=db
                )
                alpha_research_reward = alpha_res["alpha_research_score"]
                
                # Evaluate against thresholds
                sub_universe_data = data.get("subUniverseSharpe", {})
                passed_sub_sharpe = True
                failing_sub_universes = []
                for sub_universe, sub_sharpe in sub_universe_data.items():
                    sub_sharpe_val = float(sub_sharpe)
                    if sub_sharpe_val < proj.min_sub_universe_sharpe:
                        passed_sub_sharpe = False
                        failing_sub_universes.append(f"{sub_universe}: {sub_sharpe_val:.2f}")

                passed = (
                    sharpe >= proj.min_sharpe and 
                    fitness >= proj.min_fitness and 
                    turnover <= proj.max_turnover and 
                    margin >= proj.min_margin and
                    passed_sub_sharpe
                )
                
                # Determine Candidate Tier (0 to 6)
                tier = 6
                if passed:
                    tier = 0
                else:
                    if (fitness >= proj.min_fitness and turnover <= proj.max_turnover and 
                        margin >= proj.min_margin and passed_sub_sharpe and 
                        1.10 <= sharpe < proj.min_sharpe):
                        tier = 1
                    elif (sharpe >= proj.min_sharpe and turnover <= proj.max_turnover and 
                          margin >= proj.min_margin and passed_sub_sharpe and 
                          0.85 <= fitness < proj.min_fitness):
                        tier = 2
                    elif (sharpe >= proj.min_sharpe and fitness >= proj.min_fitness and 
                          turnover > proj.max_turnover):
                        tier = 3
                    elif (sharpe >= proj.min_sharpe and fitness >= proj.min_fitness and 
                          turnover <= proj.max_turnover and margin >= proj.min_margin and 
                          passed_sub_sharpe and stability_score < 0.85):
                        tier = 4
                    elif sharpe >= 0.80:
                        tier = 5

                # Save metrics to DB
                metric = Metric(
                    simulation_id=sim.id,
                    sharpe=sharpe,
                    fitness=fitness,
                    turnover=turnover,
                    returns=returns,
                    margin=margin,
                    drawdown=drawdown,
                    long_count=int(data.get("longCount", 0)) if data.get("longCount") else None,
                    short_count=int(data.get("shortCount", 0)) if data.get("shortCount") else None,
                    
                    # Advanced metrics columns
                    rank_ic=ic_m["rank_ic"],
                    mean_ic=ic_m["mean_ic"],
                    median_ic=ic_m["median_ic"],
                    ic_std_dev=ic_m["ic_std_dev"],
                    ic_ir=ic_m["ic_ir"],
                    positive_ic_ratio=ic_m["positive_ic_ratio"],
                    walk_forward_score=wf_m["walk_forward_score"],
                    regime_score=reg_m["regime_score"],
                    correlation_score=diversity_score,
                    composite_research_score=comp_res["composite_score"],
                    
                    # Upgraded fields
                    stability_score=stability_score,
                    robustness_score=robustness_score,
                    diversity_score=diversity_score,
                    simplicity_score=simplicity_score,
                    alpha_research_score=alpha_research_reward,
                    
                    walk_forward_mean_sharpe=wf_m.get("mean_sharpe"),
                    walk_forward_median_sharpe=wf_m.get("median_sharpe"),
                    walk_forward_min_sharpe=wf_m.get("min_sharpe"),
                    walk_forward_variance=wf_m.get("variance"),
                    parameter_stability_score=stability_score,
                    
                    candidate_tier=tier
                )
                db.add(metric)
                
                if passed:
                    expr.status = "PASSED"
                    level = "SUCCESS"
                    msg = (
                        f"Alpha Mined Passed (Tier {tier})!\n"
                        f"Formula: '{expr.expression_text}'\n"
                        f"Metrics:\n"
                        f"  - Sharpe: {sharpe:.4f} (Expected >= {proj.min_sharpe:.2f})\n"
                        f"  - Fitness: {fitness:.4f} (Expected >= {proj.min_fitness:.2f})\n"
                        f"  - Turnover: {turnover:.2%} (Expected <= {proj.max_turnover:.2%})\n"
                        f"  - Margin: {margin:.2f} bps (Expected >= {proj.min_margin:.2f} bps)\n"
                        f"  - Sub-Universe Sharpe: {'Passed' if passed_sub_sharpe else 'Failed'} (Expected >= {proj.min_sub_universe_sharpe:.2f})\n"
                        f"Advice: Alpha meets all target thresholds. Ready for registry staging."
                    )
                else:
                    expr.status = "REJECTED"
                    level = "WARNING"
                    
                    advisor_tips = []
                    if sharpe < proj.min_sharpe:
                        advisor_tips.append("Low Sharpe: Try adding a lookback window (e.g. ts_delay) or applying cross-sectional ranking to neutralize market beta, or try a different research family style.")
                    if fitness < proj.min_fitness:
                        advisor_tips.append("Low Fitness: Improve return-to-turnover ratio by applying decay/smoothing (e.g. ts_decay_linear) to reduce excessive trades, or try combining it with a volume/liquidity filter.")
                    if turnover > proj.max_turnover:
                        advisor_tips.append("High Turnover: Apply linear decay (ts_decay_linear) or increase the lookback window of your signals to slow down transition rates.")
                    if margin < proj.min_margin:
                        advisor_tips.append("Low Margin: Focus on less liquid or high-spread industry groups, or combine with a price scaling factor, or apply subindustry neutralization.")
                    if not passed_sub_sharpe:
                        sub_details = ", ".join(failing_sub_universes)
                        advisor_tips.append(f"Sub-Universe Sharpe Failure ({sub_details}): The alpha lacks robustness across segments. Consider subindustry neutralization or applying a global cross-sectional rank (e.g., rank(expr)) to stabilize sub-portfolio dynamics.")
                    
                    advice_str = " | ".join(advisor_tips) if advisor_tips else "Examine custom formula constraints."
                    
                    msg = (
                        f"Alpha Rejected (Tier {tier})!\n"
                        f"Formula: '{expr.expression_text}'\n"
                        f"Metrics Comparison:\n"
                        f"  - Sharpe: {sharpe:.4f} (Expected >= {proj.min_sharpe:.2f}) -> {'PASS' if sharpe >= proj.min_sharpe else 'FAIL'}\n"
                        f"  - Fitness: {fitness:.4f} (Expected >= {proj.min_fitness:.2f}) -> {'PASS' if fitness >= proj.min_fitness else 'FAIL'}\n"
                        f"  - Turnover: {turnover:.2%} (Expected <= {proj.max_turnover:.2%}) -> {'PASS' if turnover <= proj.max_turnover else 'FAIL'}\n"
                        f"  - Margin: {margin:.2f} bps (Expected >= {proj.min_margin:.2f} bps) -> {'PASS' if margin >= proj.min_margin else 'FAIL'}\n"
                        f"  - Sub-Universe Sharpe: {'PASS' if passed_sub_sharpe else 'FAIL'} (Expected >= {proj.min_sub_universe_sharpe:.2f})\n"
                        f"Advice: {advice_str}"
                    )
                
                log = ProjectLog(
                    project_id=proj.id,
                    level=level,
                    message=msg
                )
                db.add(log)
                await db.commit()
                
                # Recalculate Pareto Optimization Frontier and commit
                await self._recalculate_pareto_frontier(proj.id, db)
                await db.commit()
                
                # Close the loop optimizer + queue routing based on Tier
                if tier in (1, 2):
                    # Spawn near-miss optimization task in the background
                    asyncio.create_task(self._optimize_rejected_alpha(proj.id, expr.id, msg))
                elif tier == 3:
                    # High Turnover post-process smoothing
                    asyncio.create_task(self._smooth_high_turnover_alpha(proj.id, expr.id))
                elif tier == 6:
                    logger.info(f"Toxic space research rejection (Tier 6) for expression ID={expr.id}")
                    
            elif status in TERMINAL_FAILURE:
                sim.status = "ERROR"
                sim.error_message = data.get("message", f"Simulation ended with status: {status}")
                expr.status = "ERROR"
                
                err_msg = sim.error_message
                advice = "Verify syntax, check for balanced brackets, and ensure all variables are correct."
                if "unknown variable" in err_msg.lower() or "variable" in err_msg.lower():
                    advice = "Ensure all database codes (e.g., closing price, specific data field) exist in the data catalog, are spelt correctly, and use the correct capitalization."
                elif "parse" in err_msg.lower() or "syntax" in err_msg.lower():
                    advice = "Check formula syntax and match parentheses/brackets, ensuring correct function formatting (e.g., ts_sum(x, 10))."
                elif "zero division" in err_msg.lower() or "divide by zero" in err_msg.lower():
                    advice = "Prevent zero division issues by adding a small constant or using safe operators."
                
                log = ProjectLog(
                    project_id=proj.id,
                    level="ERROR",
                    message=(
                        f"Simulation ERROR for '{expr.expression_text}'\n"
                        f"Error: {err_msg}\n"
                        f"Advice: {advice}"
                    )
                )
                db.add(log)
                await db.commit()
                
            else:
                # Still RUNNING or QUEUED on the remote server — update timestamp
                sim.updated_at = datetime.utcnow()

                # Safety timeout: if a simulation has been polling for too long, abort it.
                MAX_POLL_MINUTES = 60
                poll_start = sim.started_at if hasattr(sim, "started_at") and sim.started_at else sim.updated_at
                if poll_start:
                    age_minutes = (datetime.utcnow() - poll_start).total_seconds() / 60
                    if age_minutes > MAX_POLL_MINUTES:
                        sim.status = "ERROR"
                        sim.error_message = (
                            f"Timed out after {int(age_minutes)}m with remote status: {status!r}"
                        )
                        expr.status = "ERROR"
                        log = ProjectLog(
                            project_id=proj.id,
                            level="ERROR",
                            message=(
                                f"Simulation timed out ({int(age_minutes)}m) for "
                                f"'{expr.expression_text[:30]}...' — last status: {status!r}"
                            )
                        )
                        db.add(log)
                        logger.warning(
                            f"Sim {sim.id} timed out after {int(age_minutes)}m "
                            f"(brain_id={sim.brain_simulation_id}, last status={status!r})"
                        )

                await db.commit()

    async def _optimize_rejected_alpha(self, project_id: int, expr_id: int, fail_reason: str):
        """Optimizes a failed expression and re-submits it into the queue."""
        MAX_OPTIMIZER_DEPTH = 3  # Prevent infinite optimize → reject → optimize chains

        logger.info(f"Auto-optimizer: starting optimization for Expression ID={expr_id}")
        async with AsyncSessionLocal() as db:
            # Query expression and project criteria
            result = await db.execute(
                select(Expression)
                .join(Project)
                .options(selectinload(Expression.project))
                .where(Expression.id == expr_id)
            )
            expr = result.scalar_one_or_none()
            if not expr:
                return

            # --- Depth guard: count ancestor chain length ---
            depth = 0
            parent_id = expr.parent_id
            while parent_id is not None and depth < MAX_OPTIMIZER_DEPTH:
                depth += 1
                parent_res = await db.execute(
                    select(Expression.parent_id).where(Expression.id == parent_id)
                )
                parent_id = parent_res.scalar_one_or_none()

            if depth >= MAX_OPTIMIZER_DEPTH:
                logger.info(
                    f"Auto-optimizer: skipping expr {expr_id} — "
                    f"max optimizer depth ({MAX_OPTIMIZER_DEPTH}) reached."
                )
                return
            # -----------------------------------------------

            proj = expr.project
            
            # Fetch cache data fields to pass validation
            from brain_farm.app.services.field_manager import FieldManager
            fields = await FieldManager.get_all_fields(db)
            field_ids = [f.id for f in fields]
            
            # Call AutoOptimizer
            opt = AutoOptimizer(field_ids)
            optimized_expr, explanation = await opt.optimize(expr.expression_text, fail_reason)
            
            if optimized_expr and optimized_expr != expr.expression_text:
                # Add to queue
                new_expr = Expression(
                    project_id=project_id,
                    expression_text=optimized_expr,
                    generator_type="LLM",
                    status="PENDING",
                    parent_id=expr.id
                )
                db.add(new_expr)
                
                log = ProjectLog(
                    project_id=project_id,
                    level="INFO",
                    message=f"Auto-Optimized: '{expr.expression_text[:20]}...' -> '{optimized_expr[:20]}...'. Resolution: {explanation}"
                )
                db.add(log)
                await db.commit()
                logger.info(f"Auto-optimizer added new optimized Alpha into the queue: {optimized_expr}")

    async def _recalculate_pareto_frontier(self, project_id: int, db):
        """
        Recalculates the Pareto-frontier for all COMPLETE expressions in the project.
        Saves pareto_optimal status back to the Metric table.
        """
        from brain_farm.app.database.models import Metric, Simulation, Expression
        from sqlalchemy import select

        # Query all COMPLETE expressions and metrics
        stmt = (
            select(Expression, Metric)
            .join(Simulation, Expression.id == Simulation.expression_id)
            .join(Metric, Simulation.id == Metric.simulation_id)
            .where(Expression.project_id == project_id)
            .where(Simulation.status == "COMPLETE")
        )
        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return

        candidates = []
        for expr, metric in rows:
            candidates.append({
                "expr": expr,
                "metric": metric,
                "sharpe": metric.sharpe,
                "fitness": metric.fitness,
                "turnover": metric.turnover
            })

        for i, c1 in enumerate(candidates):
            dominated = False
            for j, c2 in enumerate(candidates):
                if i == j:
                    continue
                # A candidate c2 dominates c1 if:
                # 1. c2 is at least as good as c1 in all objectives
                # 2. c2 is strictly better than c1 in at least one objective
                c2_better_or_equal = (
                    c2["sharpe"] >= c1["sharpe"] and
                    c2["fitness"] >= c1["fitness"] and
                    c2["turnover"] <= c1["turnover"]
                )
                c2_strictly_better = (
                    c2["sharpe"] > c1["sharpe"] or
                    c2["fitness"] > c1["fitness"] or
                    c2["turnover"] < c1["turnover"]
                )
                if c2_better_or_equal and c2_strictly_better:
                    dominated = True
                    break

            c1["metric"].pareto_optimal = not dominated

    async def _smooth_high_turnover_alpha(self, project_id: int, expr_id: int):
        """Processes high Sharpe, high turnover Alpha by applying smoothing."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Expression).where(Expression.id == expr_id)
            )
            expr = result.scalar_one_or_none()
            if not expr:
                return

            from brain_farm.app.generators.transformations import apply_linear_decay
            from brain_farm.app.evaluators.validator import FormulaValidator
            from brain_farm.app.services.field_manager import FieldManager

            smoothed_expr = apply_linear_decay(expr.expression_text, 5)

            fields = await FieldManager.get_all_fields(db)
            field_ids = [f.id for f in fields]

            ok, _ = FormulaValidator.validate(smoothed_expr, field_ids)
            if ok:
                # Check duplication
                dup_check = await db.execute(
                    select(Expression)
                    .where(Expression.project_id == project_id)
                    .where(Expression.expression_text == smoothed_expr)
                )
                if not dup_check.scalar_one_or_none():
                    from brain_farm.app.generators.expression_analyzer import analyze_expression
                    analysis = analyze_expression(smoothed_expr, field_ids)

                    new_expr = Expression(
                        project_id=project_id,
                        expression_text=smoothed_expr,
                        generator_type="DecayOpt",
                        status="PENDING",
                        parent_id=expr.id,
                        transformation_parent=expr.id,
                        transformation_type="DECAY_SMOOTHING",
                        research_family=expr.research_family,
                        hypothesis=expr.hypothesis,
                        expected_horizon="SHORT",
                        selected_fields=expr.selected_fields,
                        selected_operators=expr.selected_operators,
                        operator_parameters=analysis["parameters"],
                        expected_turnover_category="HIGH_RETURN_LOW_TURNOVER",
                        expression_depth=analysis["expression_depth"],
                        operator_count=analysis["operator_count"],
                        field_count=analysis["field_count"],
                        complexity_score=analysis["complexity_score"],
                        generation_number=expr.generation_number + 1
                    )
                    db.add(new_expr)
                    
                    log = ProjectLog(
                        project_id=project_id,
                        level="INFO",
                        message=f"Smoothing optimization: queued '{smoothed_expr[:30]}...' from parent '{expr.expression_text[:30]}...'"
                    )
                    db.add(log)
                    await db.commit()
