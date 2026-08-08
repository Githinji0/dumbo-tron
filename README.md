# WorldQuant BRAIN - Alpha Farming Platform

An enterprise-grade, asynchronous, and modular Alpha Farming Platform for WorldQuant BRAIN. The application automates the discovery of quantitative Alphas, conducts backtests concurrently using semaphores, polls status asynchronously with adaptive timers, validates expressions using bracket and syntax rules, maintains dynamic data field caching, and integrates genetic algorithms, mutations, and AI heuristic optimizations.

---

## 🛠️ Architecture Stack

- **Frontend**: Streamlit Dashboard
- **Backend ORM**: SQLAlchemy 2.0 with Async SQLite (`aiosqlite`)
- **Async client**: `httpx` async communication core
- **Security**: Symmetry Cryptography Fernet keys encryption
- **Formula Engines**: Templates, Recursive AST Generator, Mutation Parser, Genetic Crossover, and LLM Optimizer.

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
uvicorn brain_farm.app.server:app --reload --port 8501
```
This opens the clean green charcoal interface at `http://localhost:8501`.

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

## 💡 Farming Engines Explained

1. **Recursive AST Generator**: Models arithmetic operators, lookbacks, and cross-sectional functions as node objects. Recursively joins structures up to a target depth limits, automatically simplifying duplicate expressions (e.g. `rank(rank(x)) -> rank(x)`).
2. **Genetic Crossover Engine**: Performs tournament selections over mock historical simulation records, runs subtree switches to cross parents, and introduces random mutations.
3. **Mutation Generator**: Applies window parameters tweaks, operator interchanges, neutralisation changes, or wraps expressions in time-decays to control turnover.
4. **Auto-Optimizer**: Spawns automatically on failed simulations. Inspects failing targets (e.g., Turnover exceeded, Sharpe too low) and applies custom heuristics (e.g. adding decays, group neutralisation) to queue improved candidates in real-time.
