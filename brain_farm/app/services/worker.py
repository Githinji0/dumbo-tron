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

    async def get_client_for_user(self, user_id: int) -> Optional[BrainClient]:
        """Gets or creates an authenticated BrainClient for a given user ID."""
        if user_id in self._active_clients:
            return self._active_clients[user_id]

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return None

            # Decrypt password
            password = user.get_password()
            # If Password is empty or mock-like, default client to mock mode
            client = BrainClient(email=user.email, password=password)
            success, msg = await client.authenticate()
            if success:
                self._active_clients[user_id] = client
                return client
            else:
                logger.error(f"Worker auth failed for user {user.email}: {msg}")
                # Create a client forced in mock mode as safety fallback
                mock_client = BrainClient(email=user.email, password=password, use_mock=True)
                await mock_client.authenticate()
                self._active_clients[user_id] = mock_client
                return mock_client

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
                # Query already PASSED expressions in the projects pool to match against
                passed_res = await db.execute(
                    select(Expression.expression_text)
                    .where(Expression.project_id == expr.project_id)
                    .where(Expression.status == "PASSED")
                )
                passed_formulas = [r[0] for r in passed_res.all()]
                
                is_redundant = False
                reason = ""
                for passed in passed_formulas:
                    if expr.expression_text.strip() == passed.strip():
                        is_redundant = True
                        reason = "Exact duplicate of a passed Alpha expression"
                        break
                    
                    # Calculate synthetic Pearson correlation
                    corr = CorrelationFilter.calculate_correlation(expr.expression_text, passed)
                    if abs(corr) > 0.85:
                        is_redundant = True
                        reason = f"Highly correlated (Pearson = {corr:.2f}) with passed Alpha: '{passed[:30]}...'"
                        break
                        
                    # Calculate Jaccard similarity
                    jacc = CorrelationFilter.calculate_ast_similarity(expr.expression_text, passed)
                    if jacc > 0.90:
                        is_redundant = True
                        reason = f"Syntactically redundant (Jaccard = {jacc:.2f}) with passed Alpha: '{passed[:30]}...'"
                        break
                
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

                expr = sim.expression
                proj = expr.project
                
                # Get authenticated client
                client = await self.get_client_for_user(proj.user_id)
                if not client:
                    sim.status = "ERROR"
                    sim.error_message = "Authentication credentials unavailable for processing."
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
                        # Log and delay submitting again (leave status as QUEUED for retries)
                        logger.warning(f"Submission rate-limited. Backing off for {backoff} seconds.")
                        await asyncio.sleep(backoff)
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
        """Polls status of simulations currently in POLLING state."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Simulation)
                .join(Expression)
                .join(Project)
                .options(selectinload(Simulation.expression).selectinload(Expression.project))
                .where(Simulation.status == "POLLING")
                .limit(20)
            )
            sims = result.scalars().all()

            for sim in sims:
                # Launch async status checker
                asyncio.create_task(self._poll_simulation_task(sim.id))

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
            if status in ["COMPLETE", "OK"]:
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
                    short_count=int(data.get("shortCount", 0)) if data.get("shortCount") else None
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
                    
            elif status == "ERROR":
                sim.status = "ERROR"
                sim.error_message = data.get("message", "Unknown simulation runtime error.")
                expr.status = "ERROR"
                
                log = ProjectLog(
                    project_id=proj.id,
                    level="ERROR",
                    message=f"Simulation error for '{expr.expression_text[:30]}...': {sim.error_message}"
                )
                db.add(log)
                await db.commit()
                
            else:
                # Still RUNNING or QUEUED on target server, update timestamp
                sim.updated_at = datetime.utcnow()
                await db.commit()

    async def _optimize_rejected_alpha(self, project_id: int, expr_id: int, fail_reason: str):
        """Optimizes a failed expression and re-submits it into the queue."""
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
