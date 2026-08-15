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

                # 1b. Multi-Stage Signal Preflight Validation (Temporal, Constant-Signal, Compatibility)
                from brain_farm.app.services.signal_preflight import SignalPreflight, PreflightDecision, ConstantSignalRisk
                preflight_res = SignalPreflight.evaluate(expr.expression_text, family=expr.research_family)
                
                # Persist preflight metadata
                expr.field_categories = preflight_res["field_categories"]
                expr.temporal_behavior = ", ".join(preflight_res["temporal_behavior"])
                expr.compatibility_score = preflight_res["compatibility_score"]
                expr.constant_signal_risk = preflight_res["constant_signal_risk"]
                expr.preflight_report = preflight_res
                expr.expression_hash = preflight_res.get("expression_hash")
                expr.structure_hash = preflight_res.get("structure_hash")
                
                if preflight_res["decision"] != PreflightDecision.PASS:
                    expr.status = "PREFLIGHT_REJECTED"
                    expr.preflight_status = "REJECTED"
                    expr.preflight_reason = preflight_res["reason"]
                    expr.diagnostic_category = "CONSTANT_SIGNAL_RISK" if preflight_res["constant_signal_risk"] == ConstantSignalRisk.HIGH else "PREFLIGHT_REJECTED"
                    
                    log = ProjectLog(
                        project_id=expr.project_id,
                        level="WARNING",
                        message=(
                            f"Signal Preflight Gatekeeper: Candidate Rejected Before Simulation!\n"
                            f"Formula: '{expr.expression_text}'\n"
                            f"Reason: {preflight_res['reason']}\n"
                            f"Constant Signal Risk: {preflight_res['constant_signal_risk']} | Compatibility Score: {preflight_res['compatibility_score']:.2f}\n"
                            f"Advice: Avoid short daily rolling windows on slow-moving quarterly fundamental data. Use fundamental ratios, cross-sectional ranking, or lookback >= 60d."
                        )
                    )
                    db.add(log)
                    logger.warning(f"Signal Preflight: Rejected expression {expr.id} -> {preflight_res['reason']}")
                    continue
                else:
                    expr.preflight_status = "PASSED"
                    expr.preflight_reason = preflight_res["reason"]

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
            # First, recover any stale SUBMITTING simulations that might have hung
            await db.execute(
                update(Simulation)
                .where(Simulation.status == "SUBMITTING")
                .values(status="QUEUED")
            )
            await db.commit()

            active_user_ids = [uid for uid, c in self._active_clients.items() if c and c.is_authenticated]
            query = (
                select(Simulation)
                .join(Expression)
                .join(Project)
                .options(selectinload(Simulation.expression).selectinload(Expression.project))
                .where(Simulation.status == "QUEUED")
            )
            if active_user_ids:
                query = query.order_by(Project.user_id.in_(active_user_ids).desc(), Simulation.id.asc())
            else:
                query = query.order_by(Simulation.id.asc())

            result = await db.execute(query.limit(10))
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
                        backoff = int(err.split(":")[-1])
                        logger.warning(f"Submission rate-limited. Setting back to QUEUED (retry in {backoff}s).")
                        sim.status = "QUEUED"
                        await db.commit()
                    elif "re-authenticate" in err.lower() or "session expired" in err.lower():
                        sim.status = "NEEDS_AUTH"
                        sim.error_message = err
                        expr.status = "PENDING"
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
                    sim.updated_at = datetime.utcnow()
                    await db.commit()

    async def poll_active_simulations(self):
        """Polls status of simulations currently in POLLING state.
        Also re-queues NEEDS_AUTH sims if a fresh session has been injected.
        """
        async with AsyncSessionLocal() as db:
            # 1. Re-queue NEEDS_AUTH sims if a fresh session has been injected for their user
            active_user_ids = [uid for uid, c in self._active_clients.items() if c and c.is_authenticated]
            if active_user_ids:
                requeue_res = await db.execute(
                    select(Simulation)
                    .join(Expression)
                    .join(Project)
                    .where(Simulation.status == "NEEDS_AUTH")
                    .where(Project.user_id.in_(active_user_ids))
                    .limit(50)
                )
                for sim in requeue_res.scalars().all():
                    sim.status = "QUEUED"
                    sim.error_message = None
                    logger.info(f"NEEDS_AUTH sim {sim.id} re-queued after session restored.")
                await db.commit()

            # 2. Query POLLING simulations specifically (so NEEDS_AUTH can never starve POLLING)
            result = await db.execute(
                select(Simulation)
                .join(Expression)
                .join(Project)
                .options(selectinload(Simulation.expression).selectinload(Expression.project))
                .where(Simulation.status == "POLLING")
                .order_by(Simulation.updated_at.asc())
                .limit(50)
            )
            sims = result.scalars().all()

            for sim in sims:
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
                sim.status = "NEEDS_AUTH"
                sim.error_message = "Session expired. Please re-authenticate in the UI Auth panel."
                await db.commit()
                return

            # Check status on BRAIN API
            data, err = await client.get_simulation_status(sim.brain_simulation_id)
            
            if err:
                sim.retry_count += 1
                if sim.retry_count > 10:
                    sim.status = "ERROR"
                    sim.error_message = f"Max polling failures reached: {err}"
                    expr.status = "ERROR"
                await db.commit()
                return

            from brain_farm.app.services.response_auditor import ResponseStructureAuditor
            audit = ResponseStructureAuditor.audit(data, http_status=200, expression_text=expr.expression_text)
            
            # Save raw structure and remote status
            sim.remote_status = audit["remote_status"]
            sim.raw_response_structure = audit["sanitized_response"]
            expr.raw_response_structure = audit["sanitized_response"]

            if audit["evaluation_status"] == "PENDING":
                # Still running on remote server — update timestamp
                sim.updated_at = datetime.utcnow()
                await db.commit()
                return

            if audit["evaluation_status"] == "TECHNICAL_FAILURE" or audit["metrics_status"] != "METRICS_AVAILABLE":
                # Isolate technical / parsing / empty portfolio failures from alpha performance evaluation
                sim.status = "NO_VALID_METRICS" if audit["remote_status"] == "COMPLETE" else "ERROR"
                sim.error_message = audit["failure_reason"]
                sim.diagnostic_details = {
                    "simulation_status": audit["remote_status"],
                    "brain_response_status": audit["remote_status"],
                    "parser_status": audit["parser_path_used"],
                    "portfolio_status": audit["portfolio_status"],
                    "metrics_status": audit["metrics_status"],
                    "evaluation_status": "TECHNICAL_FAILURE",
                    "result_availability": True,
                    "portfolio_availability": audit["portfolio_status"] == "PORTFOLIO_AVAILABLE",
                    "metric_availability": False,
                    "trade_availability": audit["has_trades"],
                    "top_level_keys": audit["top_level_keys"],
                    "relevant_nested_keys": audit["relevant_nested_keys"],
                    "message": audit["failure_reason"]
                }

                expr.status = "NO_VALID_METRICS" if audit["remote_status"] == "COMPLETE" else "ERROR"
                expr.diagnostic_category = "NO_VALID_METRICS"
                expr.evaluation_status = "TECHNICAL_FAILURE"
                expr.portfolio_status = audit["portfolio_status"]
                expr.metrics_status = audit["metrics_status"]
                expr.parser_status = audit["parser_path_used"]
                expr.failure_reason = audit["failure_reason"]

                log = ProjectLog(
                    project_id=proj.id,
                    level="WARNING",
                    message=(
                        f"Post-Simulation Technical Failure for '{expr.expression_text}'\n"
                        f"Remote Status: {audit['remote_status']} | Alpha ID: {data.get('alpha', 'N/A')}\n"
                        f"Portfolio Status: {audit['portfolio_status']} | Metrics Status: {audit['metrics_status']}\n"
                        f"Parser Path: {audit['parser_path_used']}\n"
                        f"Diagnostic: {audit['failure_reason']}"
                    )
                )
                db.add(log)
                
                # Empirical Memory Recording for Empty Portfolio / Technical Failures
                try:
                    from brain_farm.app.services.structural_dedup import StructuralDedup
                    from brain_farm.app.ai.research_memory import ResearchMemoryManager
                    fields, operators, _ = StructuralDedup.extract_fields_and_operators(expr.expression_text)
                    is_empty = audit["portfolio_status"] == "PORTFOLIO_EMPTY"
                    for f in fields:
                        await ResearchMemoryManager.record_field_outcome(
                            db=db,
                            field_name=f,
                            is_valid_metrics=False,
                            is_empty_portfolio=is_empty,
                            project_id=proj.id
                        )
                    for op in operators:
                        await ResearchMemoryManager.record_operator_outcome(
                            db=db,
                            operator_name=op,
                            is_valid_metrics=False,
                            is_empty_portfolio=is_empty,
                            project_id=proj.id
                        )
                except Exception as e:
                    logger.warning(f"Field/Operator failure memory recording skipped: {e}")

                await db.commit()
                return

            # Valid metrics present -> Set evaluation states
            extracted = audit["extracted_metrics"]
            sim.status = "COMPLETE"
            sim.brain_alpha_id = data.get("alpha")
            sim.diagnostic_details = {
                "simulation_status": "COMPLETED",
                "brain_response_status": audit["remote_status"],
                "parser_status": audit["parser_path_used"],
                "portfolio_status": "PORTFOLIO_AVAILABLE",
                "metrics_status": "METRICS_AVAILABLE",
                "evaluation_status": "EVALUATED",
                "result_availability": True,
                "portfolio_availability": True,
                "metric_availability": True,
                "trade_availability": audit["has_trades"],
                "top_level_keys": audit["top_level_keys"],
                "relevant_nested_keys": audit["relevant_nested_keys"]
            }

            expr.evaluation_status = "EVALUATED"
            expr.portfolio_status = "PORTFOLIO_AVAILABLE"
            expr.metrics_status = "METRICS_AVAILABLE"
            expr.parser_status = audit["parser_path_used"]
            expr.failure_reason = None
            
            # Fetch IS metrics details from auditor
            sharpe = extracted["sharpe"]
            fitness = extracted["fitness"]
            turnover = extracted["turnover"]
            returns = extracted["returns"]
            margin = extracted["margin"]
            drawdown = extracted["drawdown"]
                
            # Compute advanced Phase 3 metrics in thread pool to prevent event loop blocking
            def _compute_offline_metrics(expr_text: str, sharpe_val: float):
                from brain_farm.app.services.ic_calculator import ICCalculator
                from brain_farm.app.services.walk_forward import WalkForwardTester
                from brain_farm.app.services.regime_analyzer import RegimeAnalyzer
                from brain_farm.app.services.sensitivity import ParameterSensitivityTester
                from brain_farm.app.services.correlation_filter import CorrelationFilter
                import numpy as np
                
                ic_res = ICCalculator.calculate_ic_metrics(expr_text, sharpe_val)
                wf_res = WalkForwardTester.evaluate_walk_forward(expr_text, sharpe_val)
                reg_res = RegimeAnalyzer.evaluate_regimes(expr_text, sharpe_val)
                
                perturbed = ParameterSensitivityTester.generate_perturbed_expressions(expr_text)
                p_corrs = []
                for p_expr in perturbed:
                    p_corr = CorrelationFilter.calculate_correlation(expr_text, p_expr)
                    p_corrs.append({"expression": p_expr, "correlation": float(p_corr)})
                
                stab_score = float(np.mean([abs(c["correlation"]) for c in p_corrs])) if p_corrs else 1.0
                sens_penalty = float(ParameterSensitivityTester.evaluate_sensitivity_penalty(expr_text, sharpe_val))
                
                return {
                    "ic_m": ic_res,
                    "wf_m": wf_res,
                    "reg_m": reg_res,
                    "stability_score": stab_score,
                    "sens_penalty": sens_penalty,
                    "p_corrs": p_corrs
                }

            loop = asyncio.get_running_loop()
            offline = await loop.run_in_executor(None, _compute_offline_metrics, expr.expression_text, sharpe)
            
            ic_m = offline["ic_m"]
            wf_m = offline["wf_m"]
            reg_m = offline["reg_m"]
            stability_score = offline["stability_score"]
            
            from brain_farm.app.services.composite_scorer import WeightedCompositeScorer
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

            expr.parameter_sensitivity = {
                "penalty": offline["sens_penalty"],
                "correlations": offline["p_corrs"]
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
            
            # Determine Candidate Tier (0 to 6) and Diagnostic Category
            tier = 6
            if passed:
                tier = 0
                expr.diagnostic_category = "ROBUST_CANDIDATE" if robustness_score >= 0.80 else "HIGH_QUALITY"
            else:
                if (fitness >= proj.min_fitness and turnover <= proj.max_turnover and 
                    margin >= proj.min_margin and passed_sub_sharpe and 
                    1.10 <= sharpe < proj.min_sharpe):
                    tier = 1
                    expr.diagnostic_category = "NEAR_MISS"
                elif (sharpe >= proj.min_sharpe and turnover <= proj.max_turnover and 
                      margin >= proj.min_margin and passed_sub_sharpe and 
                      0.85 <= fitness < proj.min_fitness):
                    tier = 2
                    expr.diagnostic_category = "NEAR_MISS"
                elif (sharpe >= proj.min_sharpe and fitness >= proj.min_fitness and 
                      turnover > proj.max_turnover):
                    tier = 3
                    expr.diagnostic_category = "HIGH_SHARPE_HIGH_TURNOVER"
                elif (sharpe >= proj.min_sharpe and fitness >= proj.min_fitness and 
                      turnover <= proj.max_turnover and margin >= proj.min_margin and 
                      passed_sub_sharpe and stability_score < 0.85):
                    tier = 4
                    expr.diagnostic_category = "NEAR_MISS"
                elif sharpe >= 0.80:
                    tier = 5
                    expr.diagnostic_category = "WEAK_ALPHA"
                else:
                    expr.diagnostic_category = "WEAK_ALPHA"

            # Save metrics to DB
            metric = Metric(
                simulation_id=sim.id,
                has_valid_metrics=True,
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

            # AI Critic adversarial review for passed candidates (optional & advisory)
            if passed:
                try:
                    from brain_farm.app.ai.critic_agent import CriticAgent
                    critic = CriticAgent()
                    review = await critic.review_candidate(
                        expression_text=expr.expression_text,
                        sharpe=sharpe,
                        fitness=fitness,
                        turnover=turnover,
                        stability_score=stability_score,
                        robustness_score=robustness_score,
                        parameter_sensitivity=expr.parameter_sensitivity,
                        walk_forward_score=wf_m["walk_forward_score"]
                    )
                    metric.ai_critic_risk_level = review.risk_level
                    metric.ai_critic_review = review.model_dump()
                except Exception as e:
                    logger.warning(f"AI Critic evaluation skipped: {e}")

            db.add(metric)
            
            # Empirical Research Memory Recording
            try:
                from brain_farm.app.services.structural_dedup import StructuralDedup
                from brain_farm.app.ai.research_memory import ResearchMemoryManager
                
                await ResearchMemoryManager.record_simulation_outcome(
                    db=db,
                    family=expr.research_family,
                    transformation=expr.transformation_type,
                    sharpe=sharpe,
                    fitness=fitness,
                    turnover=turnover,
                    stability=stability_score,
                    passed=passed,
                    project_id=proj.id
                )
                
                # Empirical Field & Operator Memory Recording
                fields, operators, _ = StructuralDedup.extract_fields_and_operators(expr.expression_text)
                for f in fields:
                    await ResearchMemoryManager.record_field_outcome(
                        db=db,
                        field_name=f,
                        sharpe=sharpe,
                        fitness=fitness,
                        turnover=turnover,
                        margin=margin,
                        is_valid_metrics=True,
                        is_empty_portfolio=False,
                        project_id=proj.id
                    )
                for op in operators:
                    await ResearchMemoryManager.record_operator_outcome(
                        db=db,
                        operator_name=op,
                        sharpe=sharpe,
                        fitness=fitness,
                        turnover=turnover,
                        is_valid_metrics=True,
                        is_empty_portfolio=False,
                        project_id=proj.id
                    )
            except Exception as e:
                logger.warning(f"Research memory recording skipped: {e}")
            
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
            from brain_farm.app.ai.turnover_agent import TurnoverAgent

            fields = await FieldManager.get_all_fields(db)
            field_ids = [f.id for f in fields]

            agent = TurnoverAgent(field_ids)
            # Use candidate metrics if available
            sharpe_val = 1.30
            fitness_val = 1.05
            turnover_val = 0.85
            if hasattr(expr, "simulations") and expr.simulations:
                sim = expr.simulations[-1]
                if sim.metrics:
                    sharpe_val = sim.metrics.sharpe
                    fitness_val = sim.metrics.fitness
                    turnover_val = sim.metrics.turnover

            proposal = await agent.propose_turnover_reduction(
                expression_text=expr.expression_text,
                sharpe=sharpe_val,
                fitness=fitness_val,
                turnover=turnover_val
            )
            candidate_list = agent.generate_smoothed_candidates(expr.expression_text, proposal)

            for smoothed_expr in candidate_list[:2]:
                ok, _ = FormulaValidator.validate(smoothed_expr, field_ids)
                if ok and smoothed_expr != expr.expression_text:
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
                            generator_type="TurnoverOpt",
                            status="PENDING",
                            parent_id=expr.id,
                            transformation_parent=expr.id,
                            transformation_type="AI_TURNOVER_SMOOTHING",
                            ai_generated=True,
                            ai_research_reason=proposal.explanation,
                            research_family=expr.research_family,
                            hypothesis=expr.hypothesis,
                            expected_horizon="MEDIUM",
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
                            message=f"Turnover optimization: queued '{smoothed_expr[:30]}...' from parent '{expr.expression_text[:30]}...'. Rationale: {proposal.explanation[:80]}"
                        )
                        db.add(log)
            await db.commit()
