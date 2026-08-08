import asyncio
import threading
import time
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime
from sqlalchemy import select, desc
from brain_farm.app.database.session import make_session_factory
from brain_farm.app.database.models import User, Project, Expression, Simulation, Metric, ProjectLog, DataFieldCache
from brain_farm.app.services.field_manager import FieldManager, DEFAULT_FIELDS
from brain_farm.app.generators.template import TemplateGenerator
from brain_farm.app.generators.ast_gen import ASTGenerator
from brain_farm.app.generators.mutation import MutationGenerator
from brain_farm.app.generators.genetic import GeneticGenerator
from brain_farm.app.generators.llm_gen import LLMGenerator

# App Page Layout
st.set_page_config(
    page_title="WorldQuant BRAIN Alpha Farm Platform",
    layout="wide",
    initial_sidebar_state="expanded"
)

# A fresh session factory created per Streamlit render to avoid cross-loop binding.
AsyncSessionLocal = make_session_factory()

# Bridge helper to execute async functions inside sync Streamlit code
def run_async(coro):
    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(coro)
    finally:
        loop.close()

# Initialize background worker daemon thread
if "worker_thread" not in st.session_state:
    st.session_state.worker_running = True
    
    def run_worker_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Import worker
        from brain_farm.app.services.worker import SimulationWorker
        worker = SimulationWorker(concurrency_limit=5)
        st.session_state.simulation_worker = worker
        
        # Init DB schema
        from brain_farm.app.database.session import init_db
        loop.run_until_complete(init_db())
        
        # Start worker loop
        loop.run_until_complete(worker.start())
        
        while st.session_state.get("worker_running", True):
            loop.run_until_complete(asyncio.sleep(1.0))
            
        loop.run_until_complete(worker.stop())

    thread = threading.Thread(target=run_worker_loop, daemon=True)
    thread.start()
    st.session_state.worker_thread = thread

# Session State Cache properties
if "current_user_id" not in st.session_state:
    st.session_state.current_user_id = None
if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None
if "current_username" not in st.session_state:
    st.session_state.current_username = ""
if "is_mock_mode" not in st.session_state:
    st.session_state.is_mock_mode = True
if "session_start_time" not in st.session_state:
    st.session_state.session_start_time = None
if "auth_logs" not in st.session_state:
    st.session_state.auth_logs = []

# CSS Styling for Premium Aesthetics
st.markdown("""
<style>
    .metric-card {
        background-color: #1e293b;
        border-radius: 8px;
        padding: 15px;
        border: 1px solid #334155;
    }
    .main-title {
        font-family: 'Inter', sans-serif;
        color: #f8fafc;
        font-size: 2.2rem;
        font-weight: 700;
    }
    .custom-sidebar {
        background-color: #0f172a;
    }
</style>
""", unsafe_allow_html=True)

st.title("WorldQuant BRAIN Alpha Farm Platform")
# Sidebar - Navigation, Context & Project
with st.sidebar:
    # 1. Profile header
    if st.session_state.current_user_id:
        username = st.session_state.current_username
        display_name = username.split("@")[0].capitalize() if "@" in username else "Developer"
        initials = username[0].upper() if username else "D"
        is_mock = st.session_state.is_mock_mode
        mode_label = "SIMULATED" if is_mock else "LIVE"
        mode_color = "#f59e0b" if is_mock else "#22c55e"

        # Session age string
        session_info = ""
        if st.session_state.session_start_time:
            age_min = int((datetime.utcnow() - st.session_state.session_start_time).total_seconds() / 60)
            session_info = f'<div style="font-size: 11px; color: #64748b; margin-top:2px;">Session: {age_min}m ago</div>'

        # Session expiry warning (>23h)
        expiry_warning = ""
        if st.session_state.session_start_time:
            age_h = (datetime.utcnow() - st.session_state.session_start_time).total_seconds() / 3600
            if age_h > 23:
                expiry_warning = '<div style="font-size: 11px; color: #ef4444; font-weight:bold;">Session Expired - Please re-login</div>'
    else:
        display_name = "Guest"
        username = "Not signed in"
        initials = "?"
        mode_label = "OFFLINE"
        mode_color = "#94a3b8"
        session_info = ""
        expiry_warning = ""

    st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 12px; padding: 10px 0 4px 0;">
            <div style="
                width: 50px; height: 50px; border-radius: 50%;
                background-color: #1e3a5f;
                color: white; display: flex; align-items: center;
                justify-content: center; font-size: 20px; font-weight: bold;
                border: 2px solid #2563eb; flex-shrink: 0;
            ">{initials}</div>
            <div style="overflow: hidden;">
                <div style="font-weight: 600; font-size: 15px; color: #f1f5f9; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{display_name}</div>
                <div style="font-size: 11px; color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{username}</div>
                <span style="
                    font-size: 10px; font-weight: 700; letter-spacing: 0.05em;
                    color: {mode_color}; border: 1px solid {mode_color};
                    border-radius: 4px; padding: 1px 6px; display: inline-block; margin-top: 3px;
                ">{mode_label}</span>
                {session_info}
                {expiry_warning}
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    
    # 2. Navigation List
    st.subheader("Platform Views")
    if "active_view" not in st.session_state:
        st.session_state.active_view = "Auth and Setup"
        
    view_options = [
        "Auth and Setup",
        "Projects Config",
        "Alpha Farming Run",
        "Live Queue",
        "Analytics",
        "Passed Results"
    ]
    
    for opt in view_options:
        is_active = (opt == st.session_state.active_view)
        btn_type = "primary" if is_active else "secondary"
        if st.button(opt, key=f"sidebar_nav_{opt}", type=btn_type, use_container_width=True):
            st.session_state.active_view = opt
            st.rerun()
            
    nav_selection = st.session_state.active_view
    
    st.divider()
    
    # 3. Project Selector
    if st.session_state.current_user_id:
        async def fetch_projects():
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Project).where(Project.user_id == st.session_state.current_user_id)
                )
                return list(result.scalars().all())
        
        projects_list = run_async(fetch_projects())
        if projects_list:
            proj_dict = {p.name: p.id for p in projects_list}
            selected_proj_name = st.selectbox(
                "Active Farming Project",
                options=list(proj_dict.keys()),
                index=0
            )
            # Update session state ID
            proj_id = proj_dict[selected_proj_name]
            st.session_state.current_project_id = proj_id
            
            # Fetch active project settings
            async def get_project(pid):
                async with AsyncSessionLocal() as db:
                    res = await db.execute(select(Project).where(Project.id == pid))
                    return res.scalar_one_or_none()
            active_proj = run_async(get_project(proj_id))
            if active_proj:
                st.info(f"Settings:\n- Universe: {active_proj.universe}\n- Region: {active_proj.region}\n- Threshold: Sharpe >= {active_proj.min_sharpe}\n- Sub-Universe Sharpe >= {active_proj.min_sub_universe_sharpe}")
        else:
            st.warning("No projects. Please create one.")
            st.session_state.current_project_id = None
            
        st.write("") # spacer
        st.write("")
        if st.button("Log Out", key="logout_btn", use_container_width=True):
            st.session_state.current_user_id = None
            st.session_state.current_project_id = None
            st.session_state.current_username = ""
            st.rerun()

# PAGE CONTROLLERS SELECTOR SWITCH
if nav_selection == "Auth and Setup":
    st.header("Authorization Setup")

    # OTP state trackers (initialised once per session)
    if "otp_pending"  not in st.session_state: st.session_state.otp_pending  = False
    if "otp_client"   not in st.session_state: st.session_state.otp_client   = None
    if "otp_email"    not in st.session_state: st.session_state.otp_email    = ""
    if "otp_password" not in st.session_state: st.session_state.otp_password = ""
    if "otp_mode"     not in st.session_state: st.session_state.otp_mode     = True

    # Helper: finalize login after successful auth (step1 direct or step2 OTP)
    def _finalize_login(email, password, mode, success_msg, client, ts):
        async def sync_user_db():
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(User).where(User.email == email))
                user = res.scalar_one_or_none()
                if mode and user:
                    if user.get_password() != password:
                        return None, "Password does not match registered mock credentials."
                if not user:
                    user = User(email=email)
                    user.set_password(password)
                    db.add(user)
                else:
                    user.set_password(password)
                await db.commit()
                return user.id, None

        user_res = run_async(sync_user_db())
        if user_res is None or user_res[0] is None:
            err = user_res[1] if user_res else "Authentication failed."
            st.session_state.auth_logs.insert(0, {"time": ts, "level": "error", "msg": err})
            st.error(err)
        else:
            st.session_state.current_user_id   = user_res[0]
            st.session_state.current_username  = email
            st.session_state.is_mock_mode      = mode
            st.session_state.session_start_time = datetime.utcnow()
            mode_str = "SIMULATED" if mode else "LIVE"
            st.session_state.auth_logs.insert(0, {"time": ts, "level": "success",
                                                   "msg": f"[{mode_str}] {success_msg}"})
            # ── Share the live session with the background worker ──────────────
            worker = st.session_state.get("simulation_worker")
            if worker and client:
                worker.inject_client(user_res[0], client)
            # ──────────────────────────────────────────────────────────────────
            async def _cache():
                async with AsyncSessionLocal() as db:
                    fields = await FieldManager.get_all_fields(db)
                    if len(fields) <= len(DEFAULT_FIELDS) or mode:
                        await FieldManager.sync_cache_with_api(db, client, "USA", "TOP3000")
            run_async(_cache())
            st.rerun()


    col_auth_left, col_auth_right = st.columns([1, 1])

    with col_auth_left:
        if not st.session_state.otp_pending:
            # ---- STEP 1: Credentials ----
            st.subheader("Credentials")
            email_in = st.text_input("BRAIN Account Email",
                                     value=st.session_state.current_username or "")
            pass_in  = st.text_input("Password", type="password")
            mode_in  = st.checkbox("Simulated / Offline Mode", value=True,
                                   help="Uncheck to connect to the real WorldQuant BRAIN API.")

            col_b1, col_b2 = st.columns([1, 1])
            with col_b1:
                do_auth  = st.button("Sign In", type="primary", use_container_width=True)
            with col_b2:
                do_check = st.button("Check Session", use_container_width=True,
                                     disabled=not st.session_state.current_user_id)

            if do_auth:
                from brain_farm.app.services.brain_client import BrainClient
                client = BrainClient(email_in, pass_in, use_mock=mode_in)
                ok, msg = run_async(client.authenticate_step1())
                ts = datetime.now().strftime("%H:%M:%S")

                if ok and msg == "OTP_SENT":
                    st.session_state.otp_pending  = True
                    st.session_state.otp_client   = client
                    st.session_state.otp_email    = email_in
                    st.session_state.otp_password = pass_in
                    st.session_state.otp_mode     = mode_in
                    st.session_state.auth_logs.insert(0, {"time": ts, "level": "success",
                                                          "msg": "[LIVE] OTP sent to your email."})
                    st.rerun()

                elif ok:
                    _finalize_login(email_in, pass_in, mode_in, msg, client, ts)

                else:
                    st.session_state.auth_logs.insert(0, {"time": ts, "level": "error", "msg": msg})
                    st.error(msg)

            if do_check and st.session_state.current_user_id:
                from brain_farm.app.services.brain_client import BrainClient
                _chk = BrainClient(st.session_state.current_username, "",
                                   use_mock=st.session_state.is_mock_mode)
                _chk.is_authenticated = True
                _chk._auth_time = st.session_state.session_start_time
                alive, chk_msg = run_async(_chk.check_session())
                ts  = datetime.now().strftime("%H:%M:%S")
                lvl = "success" if alive else "error"
                st.session_state.auth_logs.insert(0, {"time": ts, "level": lvl, "msg": chk_msg})
                if alive:
                    st.success(chk_msg)
                else:
                    st.error(chk_msg)

        else:
            # ---- STEP 2: OTP Verification ----
            st.subheader("Email Verification")
            st.info(f"A one-time code was sent to **{st.session_state.otp_email}**. Check your inbox.")
            otp_code = st.text_input("OTP Code", max_chars=10, placeholder="e.g. 123456")

            col_o1, col_o2 = st.columns([1, 1])
            with col_o1:
                do_verify = st.button("Verify OTP", type="primary", use_container_width=True)
            with col_o2:
                if st.button("Cancel", use_container_width=True):
                    st.session_state.otp_pending = False
                    st.session_state.otp_client  = None
                    st.rerun()

            if do_verify:
                client = st.session_state.otp_client
                ts = datetime.now().strftime("%H:%M:%S")
                if not client or not otp_code.strip():
                    st.error("Please enter the OTP code.")
                else:
                    ok, msg = run_async(client.authenticate_step2(otp_code))
                    if ok:
                        st.session_state.otp_pending = False
                        _finalize_login(st.session_state.otp_email,
                                        st.session_state.otp_password,
                                        st.session_state.otp_mode,
                                        msg, client, ts)
                    else:
                        st.session_state.auth_logs.insert(0, {"time": ts, "level": "error", "msg": msg})
                        st.error(msg)

    with col_auth_right:
        st.subheader("Activity Log")
        if not st.session_state.auth_logs:
            st.caption("No activity yet. Sign in to begin.")
        else:
            for entry in st.session_state.auth_logs[:20]:
                lvl   = entry["level"]
                icon  = "✔" if lvl == "success" else "✖"
                color = "#22c55e" if lvl == "success" else "#ef4444"
                st.markdown(
                    f'<div style="border-left:3px solid {color}; padding:4px 10px; margin-bottom:6px; font-size:13px;">'
                    f'<span style="color:#64748b;">[{entry["time"]}]</span> '
                    f'<span style="color:{color}; font-weight:600;">{icon}</span> '
                    f'{entry["msg"]}</div>',
                    unsafe_allow_html=True
                )

        st.divider()
        st.subheader("Architecture")
        st.markdown("""
        - **Secure Enclave**: Passwords cipher-stored using Fernet encryption.
        - **Async Pipelines**: Simulations queued and polled asynchronously.
        - **Session Guard**: Sessions validated against BRAIN API; expiry at 23h.
        - **Mock Sandbox**: Offline mode — no BRAIN server contact.
        """)




# ----------------- VIEW 2: PROJECTS CONFIG -----------------
elif nav_selection == "Projects Config":
    st.header("Project Configurations Manager")
    
    if not st.session_state.current_user_id:
        st.warning("Please log in in Auth and Setup to create or manage projects.")
    else:
        col_p1, col_p2 = st.columns([1, 1])
        
        with col_p1:
            st.subheader("Create New Project Context")
            proj_name = st.text_input("Project Name", value="US Equities Momentum")
            proj_desc = st.text_area("Project Description", value="Farming alphas targeting US Mid&Large Cap equities using momentum lookbacks.")
            
            p_region = st.selectbox("Region Pool", ["USA", "GLB", "CHN", "EUR"], index=0)
            p_univ = st.selectbox("Universe Size", ["TOP3000", "TOP2000", "TOP1000", "TOP500"], index=0)
            p_neut = st.selectbox("Cross Neutralization", ["SUBINDUSTRY", "INDUSTRY", "SECTOR", "NONE"], index=0)
            p_delay = st.slider("Signal Delay", 0, 2, 1)
            p_decay = st.number_input("Linear signal decay days", value=0, min_value=0, max_value=30)
            
            st.subheader("Target Success Thresholds (Pass/Fail)")
            p_sharpe = st.number_input("Min Sharpe Ratio Requirement", value=1.25, step=0.05)
            p_fit = st.number_input("Min Fitness Score Requirement", value=1.00, step=0.05)
            p_turn = st.number_input("Max Turnover Rate Limit", value=0.70, step=0.05)
            p_margin = st.number_input("Min Margin (in Basis Points)", value=4.0, step=0.5)
            p_sub_sharpe = st.number_input("Min Sub-Universe Sharpe Requirement", value=1.00, step=0.05)
            
            if st.button("Submit Project Definition", type="primary"):
                async def add_project():
                    async with AsyncSessionLocal() as db:
                        proj = Project(
                            user_id=st.session_state.current_user_id,
                            name=proj_name,
                            description=proj_desc,
                            region=p_region,
                            universe=p_univ,
                            neutralization=p_neut,
                            delay=p_delay,
                            decay=p_decay,
                            min_sharpe=p_sharpe,
                            min_fitness=p_fit,
                            max_turnover=p_turn,
                            min_margin=p_margin,
                            min_sub_universe_sharpe=p_sub_sharpe
                        )
                        db.add(proj)
                        await db.commit()
                run_async(add_project())
                st.success(f"Project '{proj_name}' created successfully!")
                st.rerun()
                
        with col_p2:
            st.subheader("Data Fields Catalog")
            async def load_fields():
                async with AsyncSessionLocal() as db:
                    return await FieldManager.get_all_fields(db)
            fields = run_async(load_fields())
            
            fields_data = [
                {
                    "Field ID": f.id,
                    "Name": f.name,
                    "Dataset": f.dataset,
                    "Category": f.category,
                    "Favorite": "Favorite" if f.is_favorite else "Standard"
                }
                for f in fields
            ]
            df_fields = pd.DataFrame(fields_data)
            st.dataframe(df_fields, use_container_width=True, height=400)
            
            st.write("Toggle Favourite State:")
            f_name = st.selectbox("Select Field ID", [f.id for f in fields])
            if st.button("Add/Remove Favourite"):
                async def toggle_fav(fid):
                    async with AsyncSessionLocal() as db:
                        return await FieldManager.toggle_favorite(db, fid)
                is_fav = run_async(toggle_fav(f_name))
                st.success(f"Toggled fav status for {f_name}. Current: {is_fav}")
                st.rerun()

# ----------------- VIEW 3: ALPHA FARMING RUN -----------------
elif nav_selection == "Alpha Farming Run":
    st.header("Generator Farm Controller")
    
    if not st.session_state.current_project_id:
        st.warning("Please define and select an Active Project in the sidebar.")
    else:
        st.write("Construct and queue thousands of candidate alphas into backtester queues.")
        
        col_g1, col_g2 = st.columns([1, 1])
        
        with col_g1:
            st.subheader("Farming Parameters")
            gen_engine = st.selectbox(
                "Generation Approach Engine",
                ["Template Generator", "Recursive AST Generator", "Mutation Engine", "Genetic Crossover Engine", "LLM-AI Optimizer"]
            )
            
            batch_qty = st.slider("Candidate Count to Queue", 1, 200, 10)
            
            # Engine detailed widgets
            ast_depth = 3
            if gen_engine == "Recursive AST Generator":
                ast_depth = st.slider("Max Syntax Tree depth", 2, 5, 3)
                
            st.subheader("Validator Pre-check Details")
            st.markdown("""
            * Syntactical validators parse candidates **before submission**.
            * Validates lookback windows ($1 < d < 500$).
            * Filters out illegal operations (re-ranking already ranked parameters).
            """)
            
            if st.button("Launch & Queue Farm Job", type="primary"):
                async def gather_fields():
                    async with AsyncSessionLocal() as db:
                        res = await FieldManager.get_all_fields(db)
                        return [f.id for f in res]
                p_fields = run_async(gather_fields())
                
                # Instance generator
                if gen_engine == "Template Generator":
                    generator = TemplateGenerator(p_fields)
                    candidates = generator.generate(batch_qty)
                elif gen_engine == "Recursive AST Generator":
                    generator = ASTGenerator(p_fields, max_depth=ast_depth)
                    candidates = generator.generate(batch_qty)
                elif gen_engine == "Mutation Engine":
                    # Load top formulas to mutate from db
                    async def fetch_mut_parents():
                        async with AsyncSessionLocal() as db:
                            result = await db.execute(
                                select(Expression.expression_text)
                                .where(Expression.project_id == st.session_state.current_project_id)
                                .limit(20)
                            )
                            return [r[0] for r in result.all()]
                    parents = run_async(fetch_mut_parents())
                    generator = MutationGenerator(p_fields)
                    candidates = generator.generate(batch_qty, base_formulas=parents)
                elif gen_engine == "Genetic Crossover Engine":
                    # Fetch formulas with metrics
                    async def fetch_ga_pool():
                        async with AsyncSessionLocal() as db:
                            result = await db.execute(
                                select(Expression.expression_text, Metric.sharpe)
                                .join(Simulation)
                                .join(Metric)
                                .where(Expression.project_id == st.session_state.current_project_id)
                            )
                            return [(r[0], r[1]) for r in result.all()]
                    pool = run_async(fetch_ga_pool())
                    generator = GeneticGenerator(p_fields)
                    candidates = generator.generate(batch_qty, population_history=pool)
                else:  # LLM Optimizer
                    generator = LLMGenerator(p_fields)
                    candidates = generator.generate(batch_qty)
                
                # Insert Expressions to DB as PENDING
                async def add_candidates(list_expr):
                    async with AsyncSessionLocal() as db:
                        for text in list_expr:
                            expr_db = Expression(
                                project_id=st.session_state.current_project_id,
                                expression_text=text,
                                generator_type=gen_engine.split()[0],
                                status="PENDING"
                            )
                            db.add(expr_db)
                        await db.commit()
                
                run_async(add_candidates(candidates))
                st.success(f"Generated {len(candidates)} valid Alpha candidates and placed in DB queue!")
                st.balloons()
                
        with col_g2:
            st.subheader("Manual Expression Submission")
            manual_expr = st.text_input("FastExpr Code", value="group_neutralize(ts_decay_linear(rank(close), 10), subindustry)")
            if st.button("Validate and Queue Single Alpha"):
                async def check_and_add():
                    async with AsyncSessionLocal() as db:
                        res = await FieldManager.get_all_fields(db)
                        p_fields = [f.id for f in res]
                        from brain_farm.app.evaluators.validator import FormulaValidator
                        ok, reason = FormulaValidator.validate(manual_expr, p_fields)
                        if not ok:
                            return False, f"Syntax Error: {reason}"
                        
                        expr = Expression(
                            project_id=st.session_state.current_project_id,
                            expression_text=manual_expr,
                            generator_type="MANUAL",
                            status="PENDING"
                        )
                        db.add(expr)
                        await db.commit()
                        return True, "Enqueued manually submitted expression."
                        
                ok, msg_val = run_async(check_and_add())
                if ok:
                    st.success(msg_val)
                else:
                    st.error(msg_val)

# ----------------- VIEW 4: LIVE QUEUE -----------------
elif nav_selection == "Live Queue":
    st.header("Background Simulations Status Monitor")
    
    if not st.session_state.current_project_id:
        st.warning("Please choose a Project first.")
    else:
        @st.fragment(run_every=5)
        def show_live_queue():
            # Pull live metrics
            async def fetch_queue_stats():
                async with AsyncSessionLocal() as db:
                    tot_pending = (await db.execute(
                        select(Expression).where(Expression.project_id == st.session_state.current_project_id, Expression.status == "PENDING")
                    )).scalars().all()
                    tot_simulating = (await db.execute(
                        select(Expression).where(Expression.project_id == st.session_state.current_project_id, Expression.status == "SIMULATING")
                    )).scalars().all()
                    return len(tot_pending), len(tot_simulating)
                    
            pending_cnt, active_cnt = run_async(fetch_queue_stats())
            
            col_q1, col_q2, col_q3 = st.columns(3)
            col_q1.metric("Pending Queue Length", pending_cnt)
            col_q2.metric("Running Simulations", active_cnt)
            col_q3.metric("Task Engine Concurrency Limit", "5 Workers")

            st.divider()
            st.subheader("Active Simulations Status")
            
            async def load_sim_list():
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Simulation.brain_simulation_id, Expression.expression_text, Simulation.status, Simulation.updated_at, Simulation.error_message)
                        .select_from(Simulation)
                        .join(Expression, Simulation.expression_id == Expression.id)
                        .where(Expression.project_id == st.session_state.current_project_id)
                        .order_by(desc(Simulation.updated_at))
                        .limit(20)
                    )
                    return list(result.all())
                    
            sims_grid = run_async(load_sim_list())
            if sims_grid:
                grid_data = [
                    {
                        "Sim ID": s[0] if s[0] else "N/A",
                        "Alpha Formula": s[1],
                        "API Status": s[2],
                        "Last Checked": s[3].strftime("%H:%M:%S") if s[3] else "N/A",
                        "Status Message": s[4] if s[4] else "Normal"
                    }
                    for s in sims_grid
                ]
                st.dataframe(pd.DataFrame(grid_data), use_container_width=True, height=350)
            else:
                st.info("No active simulations currently polling.")
                
            # Display Logs Expanders
            st.divider()
            with st.expander("📄 Mining Farm Action Logs"):
                async def get_logs_db():
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(
                            select(ProjectLog.created_at, ProjectLog.level, ProjectLog.message)
                            .where(ProjectLog.project_id == st.session_state.current_project_id)
                            .order_by(desc(ProjectLog.created_at))
                            .limit(30)
                        )
                        return list(result.all())
                logs_list = run_async(get_logs_db())
                
                for log_row in logs_list:
                    ts = log_row[0].strftime("%Y-%m-%d %H:%M:%S")
                    level = log_row[1]
                    msg = log_row[2]
                    
                    if level == "SUCCESS":
                        st.write(f"[SUCCESS] [{ts}] **{msg}**")
                    elif level == "WARNING":
                        st.write(f"[WARNING] [{ts}] {msg}")
                    elif level == "ERROR":
                        st.write(f"[ERROR] [{ts}] **{msg}**")
                    else:
                        st.write(f"[INFO] [{ts}] {msg}")
                        
        show_live_queue()

# ----------------- VIEW 5: ANALYTICS -----------------
elif nav_selection == "Analytics":
    st.header("Batch Analytics Performance Overview")
    
    st.write(f"DEBUG: Active Project ID = {st.session_state.current_project_id}")
    if not st.session_state.current_project_id:
        st.warning("Please choose a Project.")
    else:
        async def get_all_metrics():
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Metric.sharpe, Metric.fitness, Metric.turnover, Metric.returns, Metric.margin, Expression.generator_type)
                    .select_from(Metric)
                    .join(Simulation, Metric.simulation_id == Simulation.id)
                    .join(Expression, Simulation.expression_id == Expression.id)
                    .where(Expression.project_id == st.session_state.current_project_id)
                )
                return list(result.all())
                
        metrics_rows = run_async(get_all_metrics())
        st.write(f"DEBUG: Metrics query returned {len(metrics_rows)} rows.")
        
        if len(metrics_rows) < 1:
            st.info("Farming analytics reports will populate once backtests begin completing.")
        else:
            df_metrics = pd.DataFrame([
                {
                    "Sharpe": m[0],
                    "Fitness": m[1],
                    "Turnover": m[2] * 100,  # represent in percent
                    "Returns": m[3] * 100,
                    "Margin": m[4],  # bps
                    "Generator": m[5]
                }
                for m in metrics_rows
            ])
            
            col_an1, col_an2 = st.columns(2)
            
            with col_an1:
                st.subheader("Sharpe vs Turnover Scatter")
                fig1 = px.scatter(
                    df_metrics,
                    x="Turnover",
                    y="Sharpe",
                    color="Generator",
                    hover_data=["Fitness", "Margin"],
                    title="Alpha Sharpe Ratio vs Turnover (%)",
                    labels={"Turnover": "Turnover (%)", "Sharpe": "Sharpe Ratio"}
                )
                st.plotly_chart(fig1, use_container_width=True)
                
            with col_an2:
                st.subheader("Fitness Score Density")
                fig2 = px.histogram(
                    df_metrics,
                    x="Fitness",
                    color="Generator",
                    nbins=20,
                    marginal="box",
                    title="Fitness Score Distributions"
                )
                st.plotly_chart(fig2, use_container_width=True)
                
            col_an3, col_an4 = st.columns(2)
            
            with col_an3:
                st.subheader("Daily discover Sharpe Density")
                fig3 = px.box(
                    df_metrics,
                    x="Generator",
                    y="Sharpe",
                    color="Generator",
                    title="Alpha Sharpe Range by Gen Engine"
                )
                st.plotly_chart(fig3, use_container_width=True)
                
            with col_an4:
                st.subheader("Generator Performance Averages")
                df_grp = df_metrics.groupby("Generator").mean().reset_index()
                st.dataframe(df_grp, use_container_width=True)
                
            st.divider()
            st.subheader("Passed Alphas Mutual Correlation Matrix")
            async def get_passed_for_corr():
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Expression.expression_text)
                        .where(Expression.project_id == st.session_state.current_project_id, Expression.status == "PASSED")
                    )
                    return [r[0] for r in result.all()]
            
            passed_exprs = run_async(get_passed_for_corr())
            if len(passed_exprs) < 2:
                st.info("Passed alphas correlation matrix will appear once at least 2 alphas pass validation.")
            else:
                from brain_farm.app.services.correlation_filter import CorrelationFilter
                corr_matrix = []
                for e1 in passed_exprs:
                    row = {}
                    for e2 in passed_exprs:
                        if e1 == e2:
                            row[e2[:25]+"..."] = 1.0
                        else:
                            row[e2[:25]+"..."] = round(CorrelationFilter.calculate_correlation(e1, e2), 3)
                    corr_matrix.append(row)
                df_corr = pd.DataFrame(corr_matrix, index=[e[:25]+"..." for e in passed_exprs])
                st.dataframe(df_corr, use_container_width=True)

# ----------------- VIEW 6: PASSED RESULTS -----------------
elif nav_selection == "Passed Results":
    st.header("Qualified Alpha Discoveries")
    
    st.write(f"DEBUG: Active Project ID = {st.session_state.current_project_id}")
    if not st.session_state.current_project_id:
        st.warning("Please choose a Project.")
    else:
        async def fetch_passed_alphas():
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Expression.expression_text, Simulation.brain_alpha_id, Metric.sharpe, Metric.fitness, Metric.turnover, Metric.margin, Expression.generator_type, Expression.id)
                    .select_from(Expression)
                    .join(Simulation, Expression.id == Simulation.expression_id)
                    .join(Metric, Simulation.id == Metric.simulation_id)
                    .where(Expression.project_id == st.session_state.current_project_id, Expression.status == "PASSED")
                    .order_by(desc(Metric.sharpe))
                )
                return list(result.all())
                
        passed_rows = run_async(fetch_passed_alphas())
        st.write(f"DEBUG: Passed results query returned {len(passed_rows)} rows.")
        
        if not passed_rows:
            st.info("No Alphas meet all passing criteria filters yet. Start a mining batch tab above!")
        else:
            df_pass_data = [
                {
                    "Alpha ID": p[1] if p[1] else "Pending Registry",
                    "Expression Formula": p[0],
                    "Sharpe": round(p[2], 3),
                    "Fitness": round(p[3], 3),
                    "Turnover (%)": f"{p[4]*100:.2f}%",
                    "Margin (bps)": round(p[5], 3),
                    "Generator": p[6],
                    "DB ID": p[7]
                }
                for p in passed_rows
            ]
            
            df_show = pd.DataFrame(df_pass_data)
            st.dataframe(df_show, use_container_width=True)
            
            # Export Controls
            st.subheader("📥 Export & Report Controls")
            
            csv = df_show.to_csv(index=False).encode('utf-8')
            json_str = df_show.to_json(orient="records", indent=2).encode('utf-8')
            
            col_ex1, col_ex2, col_ex3 = st.columns(3)
            col_ex1.download_button(
                label="Export passing Alphas as CSV",
                data=csv,
                file_name=f"passed_alphas_{st.session_state.current_project_id}_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
            col_ex2.download_button(
                label="Export passing Alphas as JSON",
                data=json_str,
                file_name=f"passed_alphas_{st.session_state.current_project_id}_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json"
            )
            
            # 1-Click Submission
            st.subheader("⚡ WorldQuant BRAIN Registry Submission")
            alpha_to_submit = st.selectbox(
                "Select Passed Alpha ID to Submit",
                options=[p["Alpha ID"] for p in df_pass_data if p["Alpha ID"] != "Pending Registry"]
            )
            
            if st.button("Submit Alpha to WorldQuant BRAIN Registry"):
                from brain_farm.app.services.brain_client import BrainClient
                # Find password of user
                async def get_user_creds():
                    async with AsyncSessionLocal() as db:
                        res = await db.execute(
                            select(User).where(User.id == st.session_state.current_user_id)
                        )
                        u = res.scalar_one_or_none()
                        return u.email, u.get_password()
                email, pwd = run_async(get_user_creds())
                
                # Setup client context
                client = BrainClient(email, pwd, use_mock=email.lower().endswith("mock.com"))
                run_async(client.authenticate())
                
                success, msg = run_async(client.submit_alpha_for_review(alpha_to_submit))
                if success:
                    st.success(f"WorldQuant BRAIN Registry: {msg}")
                else:
                    st.error(f"Registry Submission Failed: {msg}")
