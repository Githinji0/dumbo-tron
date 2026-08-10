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

            for expr in exprs:
                # 1. Fast local database checking against ALL expressions (not just PASSED)
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
                        message=f"Duplicate Checker: Rejected '{expr.expression_text[:35]}...' -> {reason}"
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
                        message=f"Correlation Filter: Rejected '{expr.expression_text[:35]}...' -> {reason}"
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
                perturbed = ParameterSensitivityTester.generate_perturbed_expressions(expr.expression_text)
                p_corrs = []
                for p_expr in perturbed:
                    p_corr = CorrelationFilter.calculate_correlation(expr.expression_text, p_expr)
                    p_corrs.append({"expression": p_expr, "correlation": float(p_corr)})
                
                expr.parameter_sensitivity = {
                    "penalty": float(ParameterSensitivityTester.evaluate_sensitivity_penalty(expr.expression_text, sharpe)),
                    "correlations": p_corrs
                }
                
                expr.regime_performance = {
                    "sharpe_run_low": float(reg_m["sharpe_run_low"]),
                    "sharpe_run_high": float(reg_m["sharpe_run_high"])
                }
                
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
                    correlation_score=comp_res["diversity_score"],
                    composite_research_score=comp_res["composite_score"]
                )
                db.add(metric)
                
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
                
                if passed:
                    expr.status = "PASSED"
                    level = "SUCCESS"
                    msg = f"Alpha Mined Passed! {expr.expression_text[:30]}... Sharpe: {sharpe:.2f}, Fitness: {fitness:.2f}, Turnover: {turnover:.2%}"
                else:
                    expr.status = "REJECTED"
                    level = "WARNING"
                    reasons = []
                    if sharpe < proj.min_sharpe: reasons.append(f"Sharpe {sharpe:.2f} < {proj.min_sharpe}")
                    if fitness < proj.min_fitness: reasons.append(f"Fitness {fitness:.2f} < {proj.min_fitness}")
                    if turnover > proj.max_turnover: reasons.append(f"Turnover {turnover:.2%} > {proj.max_turnover}")
                    if margin < proj.min_margin: reasons.append(f"Margin {margin:.2f} bps < {proj.min_margin}")
                    if not passed_sub_sharpe: reasons.append(f"Sub-Universe (Min: {proj.min_sub_universe_sharpe}) failed: {', '.join(failing_sub_universes)}")
                    msg = f"Alpha Rejected! {expr.expression_text[:30]}... Reason: {', '.join(reasons)}"
                
                log = ProjectLog(
                    project_id=proj.id,
                    level=level,
                    message=msg
                )
                db.add(log)
                await db.commit()
                
                # Close the loop optimizer: if alpha rejected, trigger optimization recommend candidates!
                if not passed:
                    # Spawn optimization task in the background
                    asyncio.create_task(self._optimize_rejected_alpha(proj.id, expr.id, msg))
                    
            elif status in TERMINAL_FAILURE:
                sim.status = "ERROR"
                sim.error_message = data.get("message", f"Simulation ended with status: {status}")
                expr.status = "ERROR"
                
                log = ProjectLog(
                    project_id=proj.id,
                    level="ERROR",
                    message=f"Simulation {status} for '{expr.expression_text[:30]}...': {sim.error_message}"
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
