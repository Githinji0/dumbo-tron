# WorldQuant BRAIN - Alpha Farming Platform

An enterprise-grade, asynchronous, and modular Alpha Farming Platform for WorldQuant BRAIN. The application automates the discovery of quantitative Alphas, conducts backtests concurrently using semaphores, polls status asynchronously with adaptive timers, validates expressions using bracket and syntax rules, maintains dynamic data field caching, and integrates genetic algorithms, mutations, and AI heuristic optimizations.

---

## 🛠️ Architecture Stack

- **Frontend**: Tailwind CSS & Vanilla JS FastAPI Web UI / Streamlit Dashboard
- **Backend ORM**: SQLAlchemy 2.0 with Async SQLite (`aiosqlite`)
- **Async client**: `httpx` async communication core
- **Security**: Symmetry Cryptography Fernet keys encryption
- **Analytical Metrics**: Walk-forward stability, Volatility-regime Sharpe, Pearson sensitivity correlations, and Rank IC Calculator.
- **Formula Engines**: Templates, Recursive AST Generator (with Research Family specs), Mutation Parser, Genetic Crossover, and LLM Optimizer.

---

## 🚀 Installation & Launch

### Option 1: Native Python (Locally)

1. **Install Dependencies**:
```bash
pip install -r requirements.txt
```

2. **Configure Environment Variables (Optional)**:
Create a `.env` file in the root directory:
```env
DATABASE_URL=sqlite+aiosqlite:///c:/Users/Admin/dumbo-tron/brain_farm.db
ENCRYPTION_KEY=3k89gHJKasdfjkl_1234567890abcdefghijklm=
MOCK_MODE=True
# Optional AI keys
OPENAI_API_KEY=your_openai_key
GEMINI_API_KEY=your_gemini_key
```

3. **Start the FastAPI Application Server**:
```bash
uvicorn brain_farm.app.server:app --reload --port 8502
```
This serves the API backend and the interactive Web UI Dashboard at `http://localhost:8502`.

4. **Start the Streamlit UI Dashboard (Optional)**:
```bash
streamlit run brain_farm/app/ui/main.py --server.port 8501
```
This opens the Streamlit frontend interface at `http://localhost:8501`.

---

### Option 2: Using Docker Container

1. **Build and Start Container**:
```bash
docker-compose up --build
```
This runs the application inside the docker environment, binding container port 8501 to host port 8501.

2. **Stop Container**:
```bash
docker-compose down
```

---

## 🧪 Running Pytest Verification Suite

To execute the unit and mock API client tests:
```bash
python -m pytest tests/
```

---

## 💡 Farming Engines & Optimization

1. **Recursive AST Generator**: Models arithmetic operators, lookbacks, and cross-sectional functions as node objects. Generates family-specific formulas (e.g., trend following, mean reversion) up to a target depth limit, automatically simplifying duplicate expressions (e.g., `rank(rank(x)) -> rank(x)`).
2. **Genetic Crossover Engine**: Performs tournament selections over mock historical simulation records, runs subtree switches to cross parents, and introduces random mutations.
3. **Mutation Generator**: Applies window parameters tweaks, operator interchanges, neutralisation changes, or wraps expressions in time-decays to control turnover.
4. **Auto-Optimizer**: Spawns automatically on failed simulations, applies custom mutation heuristics in real-time, and queues improved candidates.
5. **Dynamic Priority Allocation Engine**: Follows a Bayesian allocation framework. Evaluates historical performance metrics of different Research Families and dynamically adjusts slot priorities to focus computation on high-performing alpha styles.

---

## 📊 Advanced Metrics & Alpha Inspector

Upon simulation completion, candidate alphas undergo rigorous statistical validation before staging:

*   **Rank IC & Information Ratio (IR):** Estimates daily cross-sectional Spearman Rank IC, mean, median, standard deviation, and IC IR to measure predictive power stability.
*   **Walk-Forward Out-of-Sample evaluation:** Partitions historical returns into training/test phases to verify that performance remains stable on unseen data.
*   **Volatility Regime Performance:** Categorizes returns under low and high volatility regimes, computing conditional Sharpe ratios to identify market regime sensitivity.
*   **Parameter Sensitivity & AST Perturbation:** Extracts lookback window parameters, introduces structural perturbations, and measures signal correlation stability.
*   **Weighted Composite Scorer:** Integrates Research, Robustness (stability + regime score + sensitivity safety), Diversity (cross-correlation avoidance), and Simplicity (complexity overhead penalty) into a single unified rating.
*   **Advanced Alpha Inspector Dashboard:** Visualized on the FastAPI Web UI interface, allowing researchers to click any passed candidate to view detailed stability stats, parameter variations, and economic hypothesis lineage.
