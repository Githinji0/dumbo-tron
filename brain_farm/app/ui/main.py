import asyncio
import threading
import time
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime
from sqlalchemy import select, desc
from brain_farm.app.database.session import AsyncSessionLocal
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
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Bridge helper to execute async functions inside sync Streamlit code
def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

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

st.title("⚡ WorldQuant BRAIN Alpha Farm Platform")

# Sidebar - Project Selector & Status
with st.sidebar:
    st.header("🏢 Session Context")
    
    if st.session_state.current_user_id:
        st.success(f"Connected as: {st.session_state.current_username}")
        if st.button("Disconnect Credentials"):
            st.session_state.current_user_id = None
            st.session_state.current_project_id = None
            st.session_state.current_username = ""
            st.rerun()
    else:
        st.warning("Not Connected. Please login in Tab 1.")
        
    st.divider()
    
    # Project pick selector
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
                st.info(f"📍 Settings:\n- Universe: {active_proj.universe}\n- Region: {active_proj.region}\n- Threshold: Sharpe ≥ {active_proj.min_sharpe}")
        else:
            st.warning("No projects. Please create one.")
            st.session_state.current_project_id = None

# Tabs setup
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🔑 Auth & Setup", 
    "📂 Projects Config", 
    "🚀 Alpha Farming Run", 
    "⏳ Live Queue",
    "📊 Analytics",
    "🏆 Passed Results"
])

# ----------------- TAB 1: AUTHENTICATION -----------------
with tab1:
    st.header("🔒 WorldQuant BRAIN Authorization Setup")
    
    col_auth_left, col_auth_right = st.columns([1, 1])
    
    with col_auth_left:
        st.subheader("Login Credentials")
        email_in = st.text_input("BRAIN Account Email", value="developer@mock.com")
        pass_in = st.text_input("Password", type="password", value="developer_password")
        
        mode_in = st.checkbox("Simulated/Offline Mode", value=True, help="Operates without hit WQ BRAIN API servers, utilizing locally simulated simulation polling.")
        
        if st.button("Authenticate API Connection", type="primary"):
            from brain_farm.app.services.brain_client import BrainClient
            client = BrainClient(email_in, pass_in, use_mock=mode_in)
            
            # Verify credentials
            ok, msg = run_async(client.authenticate())
            if ok:
                st.success(msg)
                
                # Write/Update user in db
                async def sync_user_db():
                    async with AsyncSessionLocal() as db:
                        res = await db.execute(select(User).where(User.email == email_in))
                        user = res.scalar_one_or_none()
                        if not user:
                            user = User(email=email_in)
                            user.set_password(pass_in)
                            db.add(user)
                        else:
                            user.set_password(pass_in)
                        await db.commit()
                        return user.id
                        
                user_id = run_async(sync_user_db())
                st.session_state.current_user_id = user_id
                st.session_state.current_username = email_in
                
                # Cache fields list if empty
                async def cache_fields():
                    async with AsyncSessionLocal() as db:
                        res = await FieldManager.get_all_fields(db)
                        if len(res) <= len(DEFAULT_FIELDS) or mode_in:
                            # Trigger offline/api field sync
                            await FieldManager.sync_cache_with_api(db, client, "USA", "TOP3000")
                run_async(cache_fields())
                
                st.rerun()
            else:
                st.error(msg)
                
    with col_auth_right:
        st.subheader("Platform Architecture")
        st.markdown("""
        * **Secure Enclave**: Passwords and secrets are cipher-stored in DB using cryptography Fernet keys.
        * **Async Pipelines**: All backtests are queued, processed, and polled asynchronously.
        * **Mock Simulator**: Fallback sandbox executes AST mutation combinations, rate limit responses, and auto-optimization cycles offline.
        """)

# ----------------- TAB 2: PROJECTS CONFIG -----------------
with tab2:
    st.header("📂 Project Configurations Manager")
    
    if not st.session_state.current_user_id:
        st.warning("Please log in in Tab 1 to create or manage projects.")
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
                            min_margin=p_margin
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
                    "Favorite": "⭐️" if f.is_favorite else "☆"
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

# ----------------- TAB 3: ALPHA FARMING RUN -----------------
with tab3:
    st.header("🚀 Generator Farm Controller")
    
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

# ----------------- TAB 4: LIVE QUEUE -----------------
with tab4:
    st.header("⏳ Background Simulations Status Monitor")
    
    if not st.session_state.current_project_id:
        st.warning("Please choose a Project first.")
    else:
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
                    st.write(f"🟢 [{ts}] **{msg}**")
                elif level == "WARNING":
                    st.write(f"🟡 [{ts}] {msg}")
                elif level == "ERROR":
                    st.write(f"🔴 [{ts}] **{msg}**")
                else:
                    st.write(f"⚪ [{ts}] {msg}")

# ----------------- TAB 5: ANALYTICS -----------------
with tab5:
    st.header("📊 Batch Analytics Performance Overview")
    
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

# ----------------- TAB 6: PASSED RESULTS -----------------
with tab6:
    st.header("🏆 Qualified Alpha Discoveries")
    
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
                label="📥 Export passing Alphas as CSV",
                data=csv,
                file_name=f"passed_alphas_{st.session_state.current_project_id}_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
            col_ex2.download_button(
                label="📥 Export passing Alphas as JSON",
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
