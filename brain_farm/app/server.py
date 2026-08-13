import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Response, Request, status, Query
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field as PydanticField

from sqlalchemy import select, desc, func, update
from sqlalchemy.orm import selectinload

from brain_farm.app.database.session import make_session_factory, init_db
from brain_farm.app.database.models import User, Project, Expression, Simulation, Metric, ProjectLog
from brain_farm.app.services.brain_client import BrainClient
from brain_farm.app.services.worker import SimulationWorker
from brain_farm.app.services.field_manager import FieldManager, DEFAULT_FIELDS
from brain_farm.app.evaluators.validator import FormulaValidator

# Generators
from brain_farm.app.generators.template import TemplateGenerator
from brain_farm.app.generators.ast_gen import ASTGenerator
from brain_farm.app.generators.mutation import MutationGenerator
from brain_farm.app.generators.genetic import GeneticGenerator
from brain_farm.app.generators.llm_gen import LLMGenerator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("brain_farm.server")

# Global async session factory
AsyncSessionLocal = make_session_factory()

# Background Simulation Worker instance
simulation_worker = SimulationWorker(concurrency_limit=5)

# Session state tracker in-memory dictionary.
# Tracks active user sessions, keeping mapping of user_id -> {client, username, mode, start_time}
# and OTP workflow states.
active_sessions: Dict[int, Dict[str, Any]] = {}
otp_auth_states: Dict[str, Dict[str, Any]] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables
    logger.info("Initializing database tables...")
    await init_db()
    
    # Start background loop
    logger.info("Starting background simulation worker...")
    await simulation_worker.start()
    
    yield
    
    # Stop background loop
    logger.info("Stopping background simulation worker...")
    await simulation_worker.stop()

app = FastAPI(title="WorldQuant BRAIN Alpha Farm Platform API", lifespan=lifespan)

# Helper to verify auth from request header
async def get_current_user_id(request: Request) -> int:
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        user_id_cookie = request.cookies.get("session_user_id")
        if not user_id_cookie:
            raise HTTPException(status_code=401, detail="Header X-User-ID or session_user_id cookie is required.")
        user_id_str = user_id_cookie
    try:
        return int(user_id_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user ID format.")

# API schemas
class LoginRequest(BaseModel):
    email: str
    password: str
    use_mock: bool = True

class OTPVerifyRequest(BaseModel):
    email: str
    otp_code: str

class ProjectCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    region: str = "USA"
    universe: str = "TOP3000"
    neutralization: str = "SUBINDUSTRY"
    delay: int = 1
    decay: int = 0
    min_sharpe: float = 1.25
    min_fitness: float = 1.00
    max_turnover: float = 0.70
    min_margin: float = 4.0
    min_sub_universe_sharpe: float = 1.00

class FieldFavoriteToggle(BaseModel):
    field_id: str

class FieldSyncRequest(BaseModel):
    region: str = "USA"
    universe: str = "TOP3000"

class LaunchFarmRequest(BaseModel):
    project_id: int
    engine: str
    count: int
    ast_depth: int = 3
    research_family: Optional[str] = None

class SingleSubmissionRequest(BaseModel):
    project_id: int
    expression: str

class RegistrySubmitRequest(BaseModel):
    alpha_id: str

class RegistrySubmitAllRequest(BaseModel):
    project_id: int

# Endpoints
@app.get("/")
def read_root():
    return RedirectResponse(url="/static/index.html")

@app.get("/api/auth/status")
async def auth_status(request: Request):
    try:
        user_id = await get_current_user_id(request)
        session = active_sessions.get(user_id)
        if not session:
            return {"authenticated": False, "username": "", "is_mock": True}
        
        # Calculate session age
        age_min = int((datetime.utcnow() - session["start_time"]).total_seconds() / 60)
        return {
            "authenticated": True,
            "username": session["username"],
            "is_mock": session["is_mock"],
            "session_age_minutes": age_min,
            "user_id": user_id
        }
    except HTTPException:
        return {"authenticated": False, "username": "", "is_mock": True}

@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
    email = req.email.strip()
    password = req.password
    use_mock = req.use_mock
    
    # Setup fresh client context
    client = BrainClient(email, password, use_mock=use_mock)
    success, msg = await client.authenticate_step1()
    
    if success and msg == "OTP_SENT":
        # Store state for step 2
        otp_auth_states[email] = {
            "client": client,
            "password": password,
            "use_mock": use_mock
        }
        return {"success": True, "otp_pending": True, "message": "OTP has been sent to your email."}
    
    if success:
        return await finalize_user_login(email, password, use_mock, client, "Live Session authenticated successfully!")
    
    # Map failure safe error category
    error_code = "BRAIN_AUTH_NETWORK_ERROR"
    status_code = 400
    if "401" in msg or "credentials" in msg.lower():
        error_code = "BRAIN_AUTH_INVALID_CREDENTIALS"
        status_code = 401
    elif "403" in msg or "forbidden" in msg.lower() or "rejected" in msg.lower():
        error_code = "BRAIN_AUTH_FORBIDDEN"
        status_code = 403
    elif "429" in msg or "rate" in msg.lower() or "attempts" in msg.lower():
        error_code = "BRAIN_AUTH_RATE_LIMITED"
        status_code = 429
    elif "timeout" in msg.lower():
        error_code = "BRAIN_AUTH_TIMEOUT"
        status_code = 408
    elif "network" in msg.lower() or "reach" in msg.lower():
        error_code = "BRAIN_AUTH_NETWORK_ERROR"
        status_code = 503
        
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "otp_pending": False, "message": msg, "error_code": error_code}
    )

@app.post("/api/auth/verify-otp")
async def auth_verify_otp(req: OTPVerifyRequest):
    email = req.email.strip()
    otp_code = req.otp_code.strip()
    
    saved_state = otp_auth_states.get(email)
    if not saved_state:
        raise HTTPException(status_code=400, detail="OTP state not found. Start Sign-in again.")
        
    client = saved_state["client"]
    password = saved_state["password"]
    use_mock = saved_state["use_mock"]
    
    success, msg = await client.authenticate_step2(otp_code)
    if success:
        otp_auth_states.pop(email, None)
        return await finalize_user_login(email, password, use_mock, client, msg)
        
    error_code = "BRAIN_AUTH_UNAUTHORIZED"
    status_code = 400
    if "401" in msg:
        error_code = "BRAIN_AUTH_INVALID_CREDENTIALS"
        status_code = 401
    elif "403" in msg or "rejected" in msg.lower():
        error_code = "BRAIN_AUTH_FORBIDDEN"
        status_code = 403
        
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "message": msg, "error_code": error_code}
    )

async def finalize_user_login(email: str, password: str, use_mock: bool, client: BrainClient, success_msg: str):
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(User.email == email))
        user = res.scalar_one_or_none()
        if use_mock and user:
            if user.get_password() != password:
                raise HTTPException(status_code=400, detail="Password does not match registered mock credentials.")
        if not user:
            user = User(email=email)
            user.set_password(password)
            db.add(user)
        else:
            user.set_password(password)
        await db.commit()
        user_id = user.id

    # Inject client to background worker
    simulation_worker.inject_client(user_id, client)
    
    # Store session details
    active_sessions[user_id] = {
        "client": client,
        "username": email,
        "is_mock": use_mock,
        "start_time": datetime.utcnow()
    }
    
    # Silently seed/sync data fields cache in the background
    async def run_cache_sync():
        async with AsyncSessionLocal() as db:
            fields = await FieldManager.get_all_fields(db)
            if len(fields) <= len(DEFAULT_FIELDS) or use_mock:
                await FieldManager.sync_cache_with_api(db, client, "USA", "TOP3000")
                
    asyncio.create_task(run_cache_sync())
    
    response = JSONResponse({
        "success": True,
        "otp_pending": False,
        "message": success_msg,
        "user_id": user_id,
        "username": email,
        "is_mock": use_mock
    })
    response.set_cookie(key="session_user_id", value=str(user_id), max_age=86400)
    return response

@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    user_id = await get_current_user_id(request)
    
    # Cancel all active user simulations
    async with AsyncSessionLocal() as db:
        stmt = (
            select(Simulation)
            .join(Expression)
            .join(Project)
            .options(selectinload(Simulation.expression))
            .where(Project.user_id == user_id)
            .where(Simulation.status.in_(["QUEUED", "SUBMITTING", "POLLING", "NEEDS_AUTH"]))
        )
        result = await db.execute(stmt)
        sims = result.scalars().all()
        for sim in sims:
            sim.status = "ERROR"
            sim.error_message = "Cancelled manually by user (Session Logout)"
            sim.expression.status = "ERROR"
        await db.commit()

    session = active_sessions.pop(user_id, None)
    if session and session["client"] and session["client"].client:
        try:
            await session["client"].client.aclose()
        except Exception:
            pass
    # Clean client from worker
    simulation_worker._active_clients.pop(user_id, None)
    
    response.delete_cookie(key="session_user_id")
    return {"success": True}

@app.get("/api/brain/health")
async def brain_health(request: Request):
    import time
    import os
    import httpx
    brain_debug = os.environ.get("BRAIN_DEBUG", "false").lower() == "true"
    
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    
    # Optional session-check: if request has active session, check session
    user_id = None
    try:
        user_id = await get_current_user_id(request)
    except Exception:
        pass
        
    if user_id and user_id in active_sessions:
        session = active_sessions[user_id]
        if session.get("client"):
            start_time = time.time()
            alive, msg = await session["client"].check_session()
            latency = round((time.time() - start_time) * 1000, 2)
            if brain_debug:
                logger.info(f"[BRAIN_DEBUG] Session Health Check | Alive: {alive} | Latency: {latency}ms | Reason: {msg}")
            return {
                "reachable": True,
                "session_active": alive,
                "latency_ms": latency,
                "message": msg
            }

    url = "https://api.worldquantbrain.com"
    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
            res = await client.get(url)
            latency = round((time.time() - start_time) * 1000, 2)
            if brain_debug:
                logger.info(f"[BRAIN_DEBUG] Reachability GET {url} | Status: {res.status_code} | Latency: {latency}ms")
            
            if res.status_code < 500:
                return {
                    "reachable": True,
                    "session_active": False,
                    "latency_ms": latency,
                    "message": "WorldQuant BRAIN is reachable."
                }
            else:
                return {
                    "reachable": False,
                    "session_active": False,
                    "latency_ms": latency,
                    "message": f"WorldQuant BRAIN base URL returned status {res.status_code}."
                }
    except Exception as e:
        latency = round((time.time() - start_time) * 1000, 2)
        if brain_debug:
            logger.error(f"[BRAIN_DEBUG] Reachability GET {url} failed | Latency: {latency}ms | Error: {str(e)}")
        return {
            "reachable": False,
            "session_active": False,
            "latency_ms": latency,
            "message": f"Could not reach WorldQuant BRAIN: {str(e)}"
        }

@app.post("/api/brain/auth/test")
async def brain_auth_test(req: LoginRequest):
    email = req.email.strip()
    password = req.password
    use_mock = req.use_mock
    
    import time
    import os
    brain_debug = os.environ.get("BRAIN_DEBUG", "false").lower() == "true"
    
    client = BrainClient(email, password, use_mock=use_mock)
    start_time = time.time()
    try:
        if not use_mock:
            async with client:
                success, msg = await client.authenticate_step1()
        else:
            success, msg = await client.authenticate_step1()
            
        latency = round((time.time() - start_time) * 1000, 2)
        
        if brain_debug:
            logger.info(f"[BRAIN_DEBUG] Auth test for {email} | Success: {success} | Message: {msg} | Latency: {latency}ms")
            
        if success:
            return {
                "success": True,
                "otp_pending": msg == "OTP_SENT",
                "message": "Credentials verified." if msg != "OTP_SENT" else "OTP sent to email.",
                "error_code": None
            }
            
        error_code = "BRAIN_AUTH_NETWORK_ERROR"
        status_code = 400
        if "401" in msg or "credentials" in msg.lower():
            error_code = "BRAIN_AUTH_INVALID_CREDENTIALS"
            status_code = 401
        elif "403" in msg or "forbidden" in msg.lower() or "rejected" in msg.lower():
            error_code = "BRAIN_AUTH_FORBIDDEN"
            status_code = 403
        elif "429" in msg or "rate" in msg.lower() or "attempts" in msg.lower():
            error_code = "BRAIN_AUTH_RATE_LIMITED"
            status_code = 429
        elif "timeout" in msg.lower():
            error_code = "BRAIN_AUTH_TIMEOUT"
            status_code = 408
        elif "network" in msg.lower() or "reach" in msg.lower():
            error_code = "BRAIN_AUTH_NETWORK_ERROR"
            status_code = 503
            
        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "otp_pending": False,
                "message": msg,
                "error_code": error_code
            }
        )
    except Exception as e:
        latency = round((time.time() - start_time) * 1000, 2)
        if brain_debug:
            logger.exception(f"[BRAIN_DEBUG] Auth test exception for {email}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "otp_pending": False,
                "message": f"Unexpected error: {str(e)}",
                "error_code": "BRAIN_AUTH_SYSTEM_ERROR"
            }
        )

@app.get("/api/projects")
async def get_projects(request: Request):
    user_id = await get_current_user_id(request)
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Project).where(Project.user_id == user_id).order_by(desc(Project.created_at)))
        projects = res.scalars().all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "region": p.region,
                "universe": p.universe,
                "neutralization": p.neutralization,
                "delay": p.delay,
                "decay": p.decay,
                "min_sharpe": p.min_sharpe,
                "min_fitness": p.min_fitness,
                "max_turnover": p.max_turnover,
                "min_margin": p.min_margin,
                "min_sub_universe_sharpe": p.min_sub_universe_sharpe,
                "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S")
            }
            for p in projects
        ]

@app.post("/api/projects")
async def create_project(request: Request, req: ProjectCreateRequest):
    user_id = await get_current_user_id(request)
    async with AsyncSessionLocal() as db:
        proj = Project(
            user_id=user_id,
            name=req.name,
            description=req.description,
            region=req.region,
            universe=req.universe,
            neutralization=req.neutralization,
            delay=req.delay,
            decay=req.decay,
            min_sharpe=req.min_sharpe,
            min_fitness=req.min_fitness,
            max_turnover=req.max_turnover,
            min_margin=req.min_margin,
            min_sub_universe_sharpe=req.min_sub_universe_sharpe
        )
        db.add(proj)
        await db.commit()
        return {"success": True, "project_id": proj.id}

@app.get("/api/fields")
async def get_fields(query: Optional[str] = None, favorite_only: bool = False):
    async with AsyncSessionLocal() as db:
        fields = await FieldManager.search_fields(db, query or "", favorite_only)
        return [
            {
                "id": f.id,
                "name": f.name,
                "dataset": f.dataset,
                "category": f.category,
                "region": f.region,
                "universe": f.universe,
                "description": f.description,
                "type": f.type,
                "is_favorite": f.is_favorite
            }
            for f in fields
        ]

@app.post("/api/fields/toggle-favorite")
async def toggle_field_favorite(req: FieldFavoriteToggle):
    async with AsyncSessionLocal() as db:
        is_fav = await FieldManager.toggle_favorite(db, req.field_id)
        return {"success": True, "is_favorite": is_fav}

@app.post("/api/fields/sync")
async def sync_fields(request: Request, req: FieldSyncRequest):
    user_id = await get_current_user_id(request)
    session = active_sessions.get(user_id)
    if not session:
        raise HTTPException(status_code=401, detail="Active auth context missing.")
    
    async with AsyncSessionLocal() as db:
        count = await FieldManager.sync_cache_with_api(db, session["client"], req.region, req.universe)
        return {"success": True, "count": count}

def calculate_complexity_score(expr: str) -> float:
    """Computes a token-based complexity score for an expression."""
    import re
    from brain_farm.app.evaluators.validator import ALLOWED_OPERATORS
    words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr)
    op_count = sum(1 for w in words if w in ALLOWED_OPERATORS)
    math_symbols = sum(expr.count(c) for c in ["+", "-", "*", "/", "<", ">", "="])
    paren_count = expr.count("(")
    complexity = float(op_count * 2 + math_symbols + paren_count + len(words) * 0.5)
    return max(1.0, complexity)

@app.post("/api/farm/launch")
async def launch_farm(request: Request, req: LaunchFarmRequest):
    user_id = await get_current_user_id(request)
    
    async with AsyncSessionLocal() as db:
        # Load fields
        res_fields = await FieldManager.get_all_fields(db)
        p_fields = [f.id for f in res_fields]
        
        # We store candidates as a list of tuples: (expression_text, parent_obj, family_name, hypothesis_text)
        candidates_with_meta = []
        
        # Generator initialization
        if req.engine == "Template Generator":
            generator = TemplateGenerator(p_fields)
            texts = generator.generate(req.count)
            candidates_with_meta = [(t, None, None, None) for t in texts]
            
        elif req.engine == "Research Family Generator":
            from brain_farm.app.generators.family_gen import FamilyGenerator
            from brain_farm.app.generators.family_info import RESEARCH_FAMILIES
            from brain_farm.app.services.priority_engine import ResearchPriorityEngine
            
            selected_family = req.research_family
            if not selected_family or selected_family == "ALL":
                # Compute Bayesian slots allocation
                allocations = await ResearchPriorityEngine.allocate_generation_slots(req.project_id, req.count, db)
                for fam, fam_cnt in allocations.items():
                    gen = FamilyGenerator(p_fields, family_name=fam)
                    fam_cands = gen.generate(fam_cnt)
                    for t in fam_cands:
                        candidates_with_meta.append((t, None, fam, RESEARCH_FAMILIES[fam].get("description", "")))
            else:
                # Direct single family generation
                gen = FamilyGenerator(p_fields, family_name=selected_family)
                fam_cands = gen.generate(req.count)
                for t in fam_cands:
                    candidates_with_meta.append((t, None, selected_family, RESEARCH_FAMILIES[selected_family].get("description", "")))
            
            # Fallback retry loop if the generator is short on candidates
            if len(candidates_with_meta) < req.count:
                import random
                families_to_use = list(RESEARCH_FAMILIES.keys()) if (not selected_family or selected_family == "ALL") else [selected_family]
                attempts = 0
                max_attempts = req.count * 10
                while len(candidates_with_meta) < req.count and attempts < max_attempts:
                    attempts += 1
                    fam = random.choice(families_to_use)
                    gen = FamilyGenerator(p_fields, family_name=fam)
                    fam_cands = gen.generate(1)
                    if fam_cands and fam_cands[0] not in [c[0] for c in candidates_with_meta]:
                        candidates_with_meta.append((fam_cands[0], None, fam, RESEARCH_FAMILIES[fam].get("description", "")))
                
        elif req.engine == "Recursive AST Generator":
            generator = ASTGenerator(p_fields, max_depth=req.ast_depth)
            texts = generator.generate(req.count)
            candidates_with_meta = [(t, None, None, None) for t in texts]
            
        elif req.engine == "Mutation Engine":
            # Load parent Expression objects instead of raw strings to carry parent id & lineage id
            result = await db.execute(
                select(Expression)
                .where(Expression.project_id == req.project_id)
                .where(Expression.status.in_(["PASSED", "REJECTED"]))
                .limit(20)
            )
            parents = result.scalars().all()
            
            generator = MutationGenerator(p_fields)
            
            # If parents are available, mutate them
            if parents:
                import random
                attempts = 0
                max_attempts = req.count * 20
                while len(candidates_with_meta) < req.count and attempts < max_attempts:
                    attempts += 1
                    parent = random.choice(parents)
                    child_text = generator.mutate_expression(parent.expression_text)
                    if child_text and child_text != parent.expression_text and child_text not in [c[0] for c in candidates_with_meta]:
                        ok, _ = FormulaValidator.validate(child_text, p_fields)
                        if ok:
                            candidates_with_meta.append((child_text, parent, parent.research_family, parent.hypothesis))
            else:
                # Fallback to templates if no parent expressions exist yet
                from brain_farm.app.generators.template import TemplateGenerator
                tg = TemplateGenerator(p_fields)
                texts = tg.generate(req.count)
                candidates_with_meta = [(t, None, None, None) for t in texts]
                
        elif req.engine == "Genetic Crossover Engine":
            # Fetch expressions with their metrics
            result = await db.execute(
                select(Expression, Metric.sharpe)
                .join(Simulation, Expression.id == Simulation.expression_id)
                .join(Metric, Simulation.id == Metric.simulation_id)
                .where(Expression.project_id == req.project_id)
            )
            pool = [(r[0], r[1]) for r in result.all()]
            
            generator = GeneticGenerator(p_fields)
            
            if len(pool) >= 4:
                import random
                pop_with_fitness = [(item[0].expression_text, item[1]) for item in pool]
                expr_map = {item[0].expression_text: item[0] for item in pool}
                
                attempts = 0
                max_attempts = req.count * 20
                while len(candidates_with_meta) < req.count and attempts < max_attempts:
                    attempts += 1
                    p1_text, p2_text = generator.select_parents(pop_with_fitness)
                    c1, c2 = generator.crossover(p1_text, p2_text)
                    
                    if random.random() < 0.3:
                        c1 = generator.mutator.mutate_expression(c1)
                    if random.random() < 0.3:
                        c2 = generator.mutator.mutate_expression(c2)
                        
                    for child in [c1, c2]:
                        if child and child not in [c[0] for c in candidates_with_meta] and child not in expr_map:
                            ok, _ = FormulaValidator.validate(child, p_fields)
                            if ok:
                                parent_obj = expr_map[p1_text]
                                candidates_with_meta.append((child, parent_obj, parent_obj.research_family, parent_obj.hypothesis))
            
            if len(candidates_with_meta) < req.count:
                # Add template fallbacks
                from brain_farm.app.generators.template import TemplateGenerator
                tg = TemplateGenerator(p_fields)
                texts = tg.generate(req.count - len(candidates_with_meta))
                for t in texts:
                    candidates_with_meta.append((t, None, None, None))
                    
        elif req.engine == "LLM-AI Optimizer":
            generator = LLMGenerator(p_fields)
            texts = generator.generate(req.count)
            candidates_with_meta = [(t, None, None, None) for t in texts]
        else:
            raise HTTPException(status_code=400, detail="Invalid generator engine.")
            
        # Insert Expressions to DB as PENDING
        created_exprs = []
        for text, parent_obj, family_name, hypothesis_text in candidates_with_meta:
            # Check if FamilyGenerator populated detailed metadata
            meta = {}
            if req.engine == "Research Family Generator" and 'gen' in locals():
                meta = getattr(gen, "generated_metadata", {}).get(text, {})
            
            # If not populated, generate basic metadata
            if not meta:
                from brain_farm.app.generators.expression_analyzer import analyze_expression
                analysis = analyze_expression(text, p_fields)
                
                # Determine horizon
                max_w = 20
                if analysis.get("parameters"):
                    m_vals = list(analysis["parameters"].values())
                    if m_vals:
                        max_w = max(m_vals)
                horizon = "SHORT" if max_w <= 5 else "LONG" if max_w >= 30 else "MEDIUM"
                
                # Setup expected turnover category
                from brain_farm.app.generators.family_info import RESEARCH_FAMILIES
                avg_turnover = 0.20
                if family_name and family_name in RESEARCH_FAMILIES:
                    turnover_range = RESEARCH_FAMILIES[family_name].get("turnover_range", (0.05, 0.40))
                    avg_turnover = sum(turnover_range) / 2.0
                expected_turnover_category = "HIGH_RETURN_HIGH_TURNOVER" if avg_turnover > 0.40 else "HIGH_RETURN_LOW_TURNOVER"
                
                meta = {
                    "research_family": family_name,
                    "hypothesis": hypothesis_text or f"Exploratory search using {req.engine}.",
                    "expected_horizon": horizon,
                    "selected_fields": ", ".join(analysis["fields"]),
                    "selected_operators": ", ".join(analysis["operators"]),
                    "operator_parameters": analysis["parameters"],
                    "expected_turnover_category": expected_turnover_category,
                    "expected_signal_behavior": f"Automatically generated signal using {req.engine}.",
                    "expression_depth": analysis["expression_depth"],
                    "operator_count": analysis["operator_count"],
                    "field_count": analysis["field_count"],
                    "complexity_score": analysis["complexity_score"]
                }
                
            # If parent exists, set mutation and generation details
            generation_number = 1
            parent_alpha_id = None
            mutation_type = None
            mutation_parameters = None
            
            if parent_obj:
                generation_number = getattr(parent_obj, "generation_number", 1) + 1
                parent_alpha_id = str(parent_obj.id)
                # Determine mutation type from generator type if applicable
                if req.engine == "Mutation Engine":
                    mutation_type = "MUTATION"
                elif req.engine == "Genetic Crossover Engine":
                    mutation_type = "CROSSOVER"
            
            expr_db = Expression(
                project_id=req.project_id,
                expression_text=text,
                generator_type=req.engine.split()[0],
                status="PENDING",
                complexity_score=meta.get("complexity_score", calculate_complexity_score(text)),
                research_family=meta.get("research_family"),
                hypothesis=meta.get("hypothesis"),
                expected_horizon=meta.get("expected_horizon"),
                selected_fields=meta.get("selected_fields"),
                selected_operators=meta.get("selected_operators"),
                operator_parameters=meta.get("operator_parameters"),
                expected_turnover_category=meta.get("expected_turnover_category"),
                parent_alpha_id=parent_alpha_id,
                generation_number=generation_number,
                mutation_type=mutation_type,
                mutation_parameters=mutation_parameters,
                expression_depth=meta.get("expression_depth", 1),
                operator_count=meta.get("operator_count", 0),
                field_count=meta.get("field_count", 0),
                parent_id=parent_obj.id if parent_obj else None
            )
            if parent_obj:
                expr_db.lineage_id = parent_obj.lineage_id if parent_obj.lineage_id else parent_obj.id
            
            db.add(expr_db)
            created_exprs.append(expr_db)
            
        await db.flush()
        
        # Set lineage_id = id for root expressions (where lineage_id is None)
        for expr_db in created_exprs:
            if expr_db.lineage_id is None:
                expr_db.lineage_id = expr_db.id
                
        await db.commit()
        return {"success": True, "queued_count": len(candidates_with_meta)}

@app.post("/api/farm/submit-single")
async def submit_single(request: Request, req: SingleSubmissionRequest):
    user_id = await get_current_user_id(request)
    
    async with AsyncSessionLocal() as db:
        res = await FieldManager.get_all_fields(db)
        p_fields = [f.id for f in res]
        
        ok, reason = FormulaValidator.validate(req.expression, p_fields)
        if not ok:
            return JSONResponse(status_code=400, content={"success": False, "message": f"Syntax Error: {reason}"})
            
        expr = Expression(
            project_id=req.project_id,
            expression_text=req.expression,
            generator_type="MANUAL",
            status="PENDING",
            complexity_score=calculate_complexity_score(req.expression)
        )
        db.add(expr)
        await db.flush()
        expr.lineage_id = expr.id
        await db.commit()
        return {"success": True, "message": "Enqueued manually submitted expression."}

def classify_error_string(error_msg: str) -> Dict[str, str]:
    if not error_msg:
        return {"category": "NORMAL", "detail": "Normal"}
        
    import re
    import json
    
    # Check rate limit
    if "RATE_LIMIT" in error_msg:
        return {
            "category": "RATE_LIMIT_ERROR",
            "detail": error_msg
        }
        
    # Check session/auth
    if "session expired" in error_msg.lower() or "please re-authenticate" in error_msg.lower() or "not authenticated" in error_msg.lower():
        return {
            "category": "AUTHENTICATION_ERROR",
            "detail": error_msg
        }

    # Check network timeout/error
    if "http request error" in error_msg.lower() or "http status error" in error_msg.lower() or "connection timed out" in error_msg.lower() or "network error" in error_msg.lower():
        return {
            "category": "NETWORK_ERROR",
            "detail": error_msg
        }

    # Match API Error format: "API Error <status>: <content>"
    match = re.match(r"API Error (\d+):\s*(.*)", error_msg, re.DOTALL)
    if not match:
        # Fallback keyword checks on the full message
        txt = error_msg.lower()
        if "syntax" in txt:
            return {"category": "ALPHA_SYNTAX_ERROR", "detail": error_msg}
        if "field" in txt:
            return {"category": "UNKNOWN_FIELD", "detail": error_msg}
        if "operator" in txt:
            return {"category": "INVALID_OPERATOR", "detail": error_msg}
        if "parameter" in txt:
            return {"category": "INVALID_PARAMETER", "detail": error_msg}
        return {"category": "SERVER_ERROR", "detail": error_msg}

    status_code = int(match.group(1))
    content = match.group(2).strip()

    if status_code in (401, 403):
        return {
            "category": "AUTHENTICATION_ERROR",
            "detail": "Session expired or invalid. Please re-authenticate."
        }
    if status_code == 429:
        return {
            "category": "RATE_LIMIT_ERROR",
            "detail": "Rate limit exceeded. Please wait before retrying."
        }
    if status_code >= 500:
        return {
            "category": "SERVER_ERROR",
            "detail": f"WorldQuant BRAIN service error ({status_code})."
        }

    # Attempt to parse json body
    try:
        data = json.loads(content)
    except Exception:
        data = None

    if isinstance(data, dict):
        if "regular" in data:
            reg_err = data["regular"]
            # Look for payload structure error
            if isinstance(reg_err, list) and any("required" in str(x).lower() for x in reg_err):
                return {
                    "category": "SIMULATION_PAYLOAD_ERROR",
                    "detail": "Simulation payload missing 'regular' expression object."
                }
            # Look for formula error or detail dict
            if isinstance(reg_err, dict) and "code" in reg_err:
                code_msgs = reg_err["code"]
                msg = " ".join(str(m) for m in code_msgs) if isinstance(code_msgs, list) else str(code_msgs)
                msg_lower = msg.lower()
                
                category = "ALPHA_SYNTAX_ERROR"
                if "syntax" in msg_lower or "parse" in msg_lower or "unbalanced" in msg_lower:
                    category = "ALPHA_SYNTAX_ERROR"
                elif "unknown field" in msg_lower or "field not found" in msg_lower or "invalid field" in msg_lower or "does not exist" in msg_lower:
                    category = "UNKNOWN_FIELD"
                elif "unknown operator" in msg_lower or "invalid operator" in msg_lower or "function not found" in msg_lower:
                    category = "INVALID_OPERATOR"
                elif "parameter" in msg_lower or "arguments" in msg_lower or "count mismatch" in msg_lower:
                    category = "INVALID_PARAMETER"
                
                return {"category": category, "detail": msg}
            if isinstance(reg_err, list):
                msg = " ".join(str(m) for m in reg_err)
                category = "ALPHA_SYNTAX_ERROR" if "syntax" in msg.lower() else "SIMULATION_PAYLOAD_ERROR"
                return {"category": category, "detail": msg}

        if "code" in data and isinstance(data["code"], list) and any("unexpected" in str(x).lower() for x in data["code"]):
            return {
                "category": "SIMULATION_PAYLOAD_ERROR",
                "detail": "Simulation payload contains unexpected top-level property."
            }
        if "settings" in data:
            return {
                "category": "INVALID_SETTINGS",
                "detail": f"Invalid settings configuration: {data['settings']}"
            }
            
    # Fallback to simple keyword parsing
    txt = content.lower()
    if "syntax" in txt or "parse" in txt:
        return {"category": "ALPHA_SYNTAX_ERROR", "detail": content}
    if "field" in txt:
        return {"category": "UNKNOWN_FIELD", "detail": content}
    if "operator" in txt:
        return {"category": "INVALID_OPERATOR", "detail": content}
    if "parameter" in txt:
        return {"category": "INVALID_PARAMETER", "detail": content}
        
    return {"category": "SERVER_ERROR", "detail": content}


@app.get("/api/queue")
async def get_queue_stats(project_id: int):
    async with AsyncSessionLocal() as db:
        # Pending countdown
        res_pending = await db.execute(
            select(Expression).where(Expression.project_id == project_id, Expression.status == "PENDING")
        )
        pending_cnt = len(res_pending.scalars().all())
        
        # Count truly in-flight simulations from the Simulation table (QUEUED or POLLING).
        # Using Expression.status == "SIMULATING" is unreliable — it can get stuck
        # when a submission fails mid-flight (rate-limit, auth error, etc.).
        res_active = await db.execute(
            select(func.count()).select_from(Simulation)
            .join(Expression, Simulation.expression_id == Expression.id)
            .where(
                Expression.project_id == project_id,
                Simulation.status.in_(["QUEUED", "SUBMITTING", "POLLING"])
            )
        )
        active_cnt = res_active.scalar() or 0
        
        # Details grid
        result_sims = await db.execute(
            select(Simulation.brain_simulation_id, Expression.expression_text, Simulation.status, Simulation.updated_at, Simulation.error_message)
            .select_from(Simulation)
            .join(Expression, Simulation.expression_id == Expression.id)
            .where(Expression.project_id == project_id)
            .order_by(desc(Simulation.updated_at))
            .limit(25)
        )
        sim_list = []
        for s in result_sims.all():
            sim_id = s[0] if s[0] else "N/A"
            expr_text = s[1]
            status_val = s[2]
            updated_at = s[3].strftime("%H:%M:%S") if s[3] else "N/A"
            raw_msg = s[4]
            
            c_info = classify_error_string(raw_msg) if status_val == "ERROR" else {"category": "NORMAL", "detail": raw_msg or "Normal"}
            sim_list.append({
                "sim_id": sim_id,
                "expression": expr_text,
                "status": status_val,
                "last_checked": updated_at,
                "category": c_info.get("category", "NORMAL"),
                "message": c_info.get("detail", "Normal")
            })
        
        return {
            "pending_count": pending_cnt,
            "running_count": active_cnt,
            "concurrency_limit": 5,
            "simulations": sim_list
        }

@app.get("/api/logs")
async def get_logs(
    project_id: int,
    limit: int = 100,
    level: Optional[str] = None,
    search: Optional[str] = None
):
    async with AsyncSessionLocal() as db:
        query = select(ProjectLog.created_at, ProjectLog.level, ProjectLog.message).where(
            ProjectLog.project_id == project_id
        )
        if level and level.strip() and level.upper() != "ALL":
            query = query.where(ProjectLog.level == level.strip().upper())
        if search and search.strip():
            query = query.where(ProjectLog.message.ilike(f"%{search.strip()}%"))
        
        query = query.order_by(desc(ProjectLog.created_at)).limit(limit)
        result = await db.execute(query)
        return [
            {
                "timestamp": log[0].strftime("%Y-%m-%d %H:%M:%S"),
                "level": log[1],
                "message": log[2]
            }
            for log in result.all()
        ]

@app.get("/api/logs/report")
async def get_logs_report(project_id: int):
    async with AsyncSessionLocal() as db:
        proj_res = await db.execute(select(Project).where(Project.id == project_id))
        proj = proj_res.scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        res = await db.execute(
            select(ProjectLog.created_at, ProjectLog.level, ProjectLog.message)
            .where(ProjectLog.project_id == project_id)
            .order_by(desc(ProjectLog.created_at))
            .limit(1000)
        )
        logs = res.all()

        total_logs = len(logs)
        success_count = sum(1 for l in logs if l[1] == "SUCCESS")
        info_count = sum(1 for l in logs if l[1] == "INFO")
        warning_count = sum(1 for l in logs if l[1] == "WARNING")
        error_count = sum(1 for l in logs if l[1] == "ERROR")

        pre_screen_count = 0
        duplicate_count = 0
        correlation_count = 0
        metric_rejections = 0
        
        sharpe_failures = 0
        fitness_failures = 0
        turnover_failures = 0
        margin_failures = 0
        sub_universe_failures = 0
        sim_errors = 0
        
        for log in logs:
            msg = log[2]
            if "Pre-Screen Filter" in msg:
                pre_screen_count += 1
            elif "Duplicate Checker" in msg:
                duplicate_count += 1
            elif "Correlation Filter" in msg:
                correlation_count += 1
            elif "Alpha Rejected" in msg:
                metric_rejections += 1
                if "Sharpe" in msg and "FAIL" in msg:
                    sharpe_failures += 1
                if "Fitness" in msg and "FAIL" in msg:
                    fitness_failures += 1
                if "Turnover" in msg and "FAIL" in msg:
                    turnover_failures += 1
                if "Margin" in msg and "FAIL" in msg:
                    margin_failures += 1
                if "Sub-Universe Sharpe" in msg and "FAIL" in msg:
                    sub_universe_failures += 1
            elif "Simulation ERROR" in msg:
                sim_errors += 1

        advice_items = []
        if sharpe_failures > 0:
            advice_items.append(
                f"- **Sharpe Ratio ({sharpe_failures} occurrences)**: Recommending cross-sectional beta neutralization. "
                "Apply `group_neutralize(alpha, subindustry)` or rank-transform `rank(alpha)` to decouple the signal from broad index movements."
            )
        if fitness_failures > 0:
            advice_items.append(
                f"- **Fitness Score ({fitness_failures} occurrences)**: Recommend improving the signal-to-turnover ratio. "
                "Introduce volume decay or transaction-cost inhibitors to scale down weight changes on high-frequency noise."
            )
        if turnover_failures > 0:
            advice_items.append(
                f"- **Turnover ({turnover_failures} occurrences)**: Recommend slowing down alpha transitions. "
                "Use linear decay functions like `ts_decay_linear(alpha, 10)` or increase lookback lengths to stabilize positions."
            )
        if margin_failures > 0:
            advice_items.append(
                f"- **Margin ({margin_failures} occurrences)**: Margin requirements failed. Try scaling alpha weights "
                "proportionately to stock spreads, focusing on less liquid assets, or neutralizing by industry code."
            )
        if sub_universe_failures > 0:
            advice_items.append(
                f"- **Sub-Universe Sharpe ({sub_universe_failures} occurrences)**: Alpha is unstable/non-robust across subsegments. "
                "Verify neutralization layers or evaluate rank constraints to prevent single subindustries from driving all risk."
            )
        if duplicate_count > 10:
            advice_items.append(
                f"- **Duplicate Expressions ({duplicate_count} occurrences)**: A high duplicate rate indicates template saturation. "
                "Switch dynamic template parameters, use different operators (e.g. ts_std_dev, ts_product), or expand search depth boundary."
            )
        if correlation_count > 10:
            advice_items.append(
                f"- **Redundant Expressions ({correlation_count} occurrences)**: Candidates are highly correlated with previously mined alphas. "
                "Introduce factor neutralization against the existing passed alpha portfolio, or pick divergent dataset indicators."
            )
        if sim_errors > 0:
            advice_items.append(
                f"- **Simulation Errors ({sim_errors} occurrences)**: Ensure all catalog fields are spelled correctly, "
                "check parenthesis balance, and confirm that mathematical functions receive valid arguments (like non-zero lookbacks)."
            )

        if not advice_items:
            advice_items.append("- All parameters are in target ranges. If farming yield is low, consider relaxing the project threshold targets slightly.")

        advice_str = "\n".join(advice_items)

        markdown_report = f"""# Alpha Farm Diagnostics Report

**Project Profile**: {proj.name}
- Region: {proj.region}
- Universe: {proj.universe}
- Target Sharpe: >= {proj.min_sharpe:.2f}
- Target Fitness: >= {proj.min_fitness:.2f}
- Max Turnover: <= {proj.max_turnover:.2%}
- Min Margin: >= {proj.min_margin:.2f} bps
- Min Sub-Universe Sharpe: >= {proj.min_sub_universe_sharpe:.2f}

## Diagnostic Statistics (Last {total_logs} logs)
- **Total Logs**: {total_logs}
- **Successes (Passed Candidates)**: {success_count}
- **Warnings (Rejections)**: {warning_count}
- **Errors**: {error_count}
- **Info capture**: {info_count}

### Rejection Breakdown
- Pre-Screen Filter Rejections: {pre_screen_count}
- Duplicate Rejections: {duplicate_count}
- Correlation Rejections: {correlation_count}
- Metric Rejections: {metric_rejections}
  - Sharpe Failures: {sharpe_failures}
  - Fitness Failures: {fitness_failures}
  - Turnover Failures: {turnover_failures}
  - Margin Failures: {margin_failures}
  - Sub-Universe Sharpe Failures: {sub_universe_failures}
- Remote Simulation Failures/Errors: {sim_errors}

## Strategic Recommendations
Based on recent backtest failures, here are the most effective improvements:
{advice_str}
"""
        return {"report": markdown_report}

@app.get("/api/logs/export")
async def export_logs(
    project_id: int,
    format: str = "csv",
    level: Optional[str] = None,
    search: Optional[str] = None
):
    import io
    import csv
    async with AsyncSessionLocal() as db:
        query = select(ProjectLog.created_at, ProjectLog.level, ProjectLog.message).where(
            ProjectLog.project_id == project_id
        )
        if level and level.strip() and level.upper() != "ALL":
            query = query.where(ProjectLog.level == level.strip().upper())
        if search and search.strip():
            query = query.where(ProjectLog.message.ilike(f"%{search.strip()}%"))
        
        query = query.order_by(desc(ProjectLog.created_at)).limit(2000)
        result = await db.execute(query)
        logs = result.all()

        filename_prefix = f"alpha_farm_project_{project_id}"

        if format.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Timestamp", "Level", "Message"])
            for log in logs:
                writer.writerow([
                    log[0].strftime("%Y-%m-%d %H:%M:%S"),
                    log[1],
                    log[2]
                ])
            content = output.getvalue()
            output.close()
            return Response(
                content=content,
                media_type="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename={filename_prefix}_logs.csv"
                }
            )
        elif format.lower() == "md":
            lines = [f"# Alpha Farm Logs - Project {project_id}\n"]
            for log in logs:
                timestamp = log[0].strftime("%Y-%m-%d %H:%M:%S")
                level_str = log[1]
                msg = log[2].replace("\n", "  \n  ")
                lines.append(f"- **[{timestamp}]** `[{level_str}]`:\n  {msg}\n")
            
            content = "\n".join(lines)
            return Response(
                content=content,
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f"attachment; filename={filename_prefix}_logs.md"
                }
            )
        else:
            lines = []
            for log in logs:
                timestamp = log[0].strftime("%Y-%m-%d %H:%M:%S")
                level_str = log[1]
                msg = log[2]
                lines.append(f"[{timestamp}] [{level_str}] {msg}")
            content = "\n".join(lines)
            return Response(
                content=content,
                media_type="text/plain",
                headers={
                    "Content-Disposition": f"attachment; filename={filename_prefix}_logs.txt"
                }
            )

@app.post("/api/queue/stop")
async def stop_simulations(request: Request, project_id: int):
    user_id = await get_current_user_id(request)
    session = active_sessions.get(user_id)
    if not session:
        raise HTTPException(status_code=401, detail="Active auth context missing.")

    async with AsyncSessionLocal() as db:
        proj_res = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        if not proj_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Project not found or access denied.")

        # Cancel any PENDING expressions to prevent background worker from starting them
        await db.execute(
            update(Expression)
            .where(Expression.project_id == project_id, Expression.status == "PENDING")
            .values(status="ERROR")
        )

        stmt = (
            select(Simulation)
            .join(Expression)
            .options(selectinload(Simulation.expression))
            .where(Expression.project_id == project_id)
            .where(Simulation.status.in_(["QUEUED", "SUBMITTING", "POLLING", "NEEDS_AUTH"]))
        )
        result = await db.execute(stmt)
        sims = result.scalars().all()
        for sim in sims:
            sim.status = "ERROR"
            sim.error_message = "Cancelled manually by user"
            sim.expression.status = "ERROR"
        await db.commit()
        return {"success": True, "stopped_count": len(sims)}

@app.get("/api/analytics")
async def get_analytics(project_id: int):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(
                Metric.sharpe, Metric.fitness, Metric.turnover, Metric.returns, Metric.margin, 
                Expression.generator_type, Metric.pareto_optimal, Metric.candidate_tier
            )
            .select_from(Metric)
            .join(Simulation, Metric.simulation_id == Simulation.id)
            .join(Expression, Simulation.expression_id == Expression.id)
            .where(Expression.project_id == project_id)
        )
        rows = result.all()
        return [
            {
                "sharpe": r[0],
                "fitness": r[1],
                "turnover": r[2] * 100,  # format percentage
                "returns": r[3] * 100,
                "margin": r[4],
                "generator": r[5],
                "pareto_optimal": r[6],
                "candidate_tier": r[7]
            }
            for r in rows
        ]

@app.get("/api/passed")
async def get_passed_alphas(project_id: int):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(
                Expression.expression_text,
                Simulation.brain_alpha_id,
                Metric.sharpe,
                Metric.fitness,
                Metric.turnover,
                Metric.margin,
                Expression.generator_type,
                Expression.id,
                Metric.rank_ic,
                Metric.mean_ic,
                Metric.median_ic,
                Metric.ic_std_dev,
                Metric.ic_ir,
                Metric.positive_ic_ratio,
                Metric.walk_forward_score,
                Metric.regime_score,
                Metric.composite_research_score,
                Expression.complexity_score,
                Expression.research_family,
                Expression.hypothesis,
                Expression.parameter_sensitivity,
                Expression.regime_performance,
                Metric.pareto_optimal,
                Metric.candidate_tier,
                Metric.stability_score,
                Metric.robustness_score,
                Metric.diversity_score,
                Metric.simplicity_score,
                Metric.alpha_research_score,
                Metric.walk_forward_mean_sharpe,
                Metric.walk_forward_median_sharpe,
                Metric.walk_forward_min_sharpe,
                Metric.walk_forward_variance,
                Metric.parameter_stability_score
            )
            .select_from(Expression)
            .join(Simulation, Expression.id == Simulation.expression_id)
            .join(Metric, Simulation.id == Metric.simulation_id)
            .where(Expression.project_id == project_id)  # Enable viewing all completed stats for analysis/filtering
            .order_by(desc(Metric.sharpe))
        )
        return [
            {
                "alpha_id": p[1] if p[1] else "Pending Registry",
                "expression": p[0],
                "sharpe": round(p[2], 3),
                "fitness": round(p[3], 3),
                "turnover": round(p[4] * 100, 2),
                "margin": round(p[5], 3),
                "generator": p[6],
                "db_id": p[7],
                "rank_ic": round(p[8], 4) if p[8] is not None else 0.0,
                "mean_ic": round(p[9], 4) if p[9] is not None else 0.0,
                "median_ic": round(p[10], 4) if p[10] is not None else 0.0,
                "ic_std_dev": round(p[11], 4) if p[11] is not None else 0.0,
                "ic_ir": round(p[12], 4) if p[12] is not None else 0.0,
                "positive_ic_ratio": round(p[13], 4) if p[13] is not None else 0.0,
                "walk_forward_score": round(p[14], 3) if p[14] is not None else 0.0,
                "regime_score": round(p[15], 3) if p[15] is not None else 0.0,
                "composite_research_score": round(p[16], 3) if p[16] is not None else 0.0,
                "complexity_score": round(p[17], 2) if p[17] is not None else 0.0,
                "research_family": p[18] if p[18] else "N/A",
                "hypothesis": p[19] if p[19] else "N/A",
                "parameter_sensitivity": p[20],
                "regime_performance": p[21],
                "pareto_optimal": p[22],
                "candidate_tier": p[23],
                "stability_score": round(p[24], 3) if p[24] is not None else 0.0,
                "robustness_score": round(p[25], 3) if p[25] is not None else 0.0,
                "diversity_score": round(p[26], 3) if p[26] is not None else 0.0,
                "simplicity_score": round(p[27], 3) if p[27] is not None else 0.0,
                "alpha_research_score": round(p[28], 3) if p[28] is not None else 0.0,
                "walk_forward_mean_sharpe": round(p[29], 3) if p[29] is not None else 0.0,
                "walk_forward_median_sharpe": round(p[30], 3) if p[30] is not None else 0.0,
                "walk_forward_min_sharpe": round(p[31], 3) if p[31] is not None else 0.0,
                "walk_forward_variance": round(p[32], 4) if p[32] is not None else 0.0,
                "parameter_stability_score": round(p[33], 3) if p[33] is not None else 0.0
            }
            for p in result.all()
        ]

@app.post("/api/passed/submit-registry")
async def submit_passed_to_registry(request: Request, req: RegistrySubmitRequest):
    user_id = await get_current_user_id(request)
    session = active_sessions.get(user_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired.")
        
    client = session["client"]
    success, msg = await client.submit_alpha_for_review(req.alpha_id)
    if success:
        return {"success": True, "message": msg}
    return JSONResponse(status_code=400, content={"success": False, "message": msg})

@app.post("/api/passed/submit-all-registry")
async def submit_all_passed_to_registry(request: Request, req: RegistrySubmitAllRequest):
    user_id = await get_current_user_id(request)
    session = active_sessions.get(user_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired.")
        
    client = session["client"]
    
    async with AsyncSessionLocal() as db:
        # Fetch all passed expressions with a valid brain_alpha_id for this project
        result = await db.execute(
            select(Simulation.brain_alpha_id)
            .select_from(Expression)
            .join(Simulation, Expression.id == Simulation.expression_id)
            .where(Expression.project_id == req.project_id, Expression.status == "PASSED")
        )
        alpha_ids = [row[0] for row in result.all() if row[0]]
        
    if not alpha_ids:
        return {"success": True, "submitted_count": 0, "message": "No qualified passed alphas with active IDs found to submit."}
        
    success_count = 0
    failures = []
    
    for alpha_id in alpha_ids:
        success, msg = await client.submit_alpha_for_review(alpha_id)
        if success:
            success_count += 1
        else:
            failures.append(f"{alpha_id}: {msg}")
            
    if failures:
        return {
            "success": success_count > 0,
            "submitted_count": success_count,
            "message": f"Submitted {success_count}/{len(alpha_ids)} alphas. Failures: {'; '.join(failures[:3])}"
        }
        
    return {"success": True, "submitted_count": success_count, "message": f"Successfully submitted all {success_count} qualified alphas to the registry!"}

@app.get("/api/debug/state")
async def debug_state():
    sessions_info = {}
    for uid, sess in active_sessions.items():
        sessions_info[uid] = {
            "username": sess["username"],
            "is_mock": sess["is_mock"],
            "start_time": str(sess["start_time"]),
            "client_authed": sess["client"].is_authenticated if sess.get("client") else False
        }
    
    worker_clients = {}
    for uid, client in simulation_worker._active_clients.items():
        worker_clients[uid] = {
            "email": client.email,
            "is_mock": client.use_mock,
            "is_authed": client.is_authenticated
        }
        
    return {
        "active_sessions": sessions_info,
        "worker_clients": worker_clients
    }

# Mount the static files directory
app.mount("/static", StaticFiles(directory="brain_farm/app/static"), name="static")
