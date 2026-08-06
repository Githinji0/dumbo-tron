import asyncio
import httpx
import logging
import random
import time
from typing import Dict, Any, Tuple, Optional
from brain_farm.app.core.config import settings

logger = logging.getLogger("brain_farm.brain_client")

class BrainClient:
    """Async HTTP Client for WorldQuant BRAIN API with backoff rates and mock mode support."""
    def __init__(self, email: str, password: str, use_mock: bool = False):
        self.email = email
        self.password = password
        self.base_url = settings.BRAIN_API_URL
        self.use_mock = use_mock or email.lower().endswith("mock.com") or settings.MOCK_MODE
        self.client: Optional[httpx.AsyncClient] = None
        self.is_authenticated = False
        
        # In-memory storage for active mock simulations to support polling
        self._mock_simulations: Dict[str, Dict[str, Any]] = {}
        
    async def __aenter__(self):
        if not self.use_mock:
            self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def authenticate(self) -> Tuple[bool, str]:
        """Authenticates with the WorldQuant BRAIN API."""
        if self.use_mock:
            await asyncio.sleep(0.5)  # Simulate network latency
            if "fail" in self.email.lower():
                return False, "Auth failed: user credentials rejected."
            self.is_authenticated = True
            logger.info("Mock authentication successful.")
            return True, "Mock Session authenticated successfully!"

        if not self.client:
            self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

        try:
            auth_url = f"{self.base_url}/authentication"
            # WorldQuant BRAIN API authentication uses Basic Authentication
            res = await self.client.post(auth_url, auth=(self.email, self.password))
            
            if res.status_code == 201:
                self.is_authenticated = True
                logger.info("BRAIN Authentication successful!")
                return True, "Authentication successful!"
            
            logger.warning(f"Auth failed with status {res.status_code}: {res.text}")
            return False, f"Auth failed with status {res.status_code}: {res.text}"
        except Exception as e:
            logger.exception("Error during authentication")
            return False, f"Network error during authentication: {str(e)}"

    async def get_data_fields(self, region: str = "USA", universe: str = "TOP3000", limit: int = 50) -> Dict[str, Any]:
        """Fetch available data fields from the BRAIN data API."""
        if self.use_mock:
            await asyncio.sleep(0.2)
            # Return high-quality mock data fields
            mock_fields = [
                {"id": "close", "name": "Close Price", "dataset": "PRICES", "category": "Technical", "type": "FLOAT"},
                {"id": "open", "name": "Open Price", "dataset": "PRICES", "category": "Technical", "type": "FLOAT"},
                {"id": "volume", "name": "Volume", "dataset": "PRICES", "category": "Technical", "type": "FLOAT"},
                {"id": "vwap", "name": "Volume Weighted Average Price", "dataset": "PRICES", "category": "Technical", "type": "FLOAT"},
                {"id": "ebit", "name": "Earnings Before Interest and Taxes", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
                {"id": "capex", "name": "Capital Expenditures", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
                {"id": "total_assets", "name": "Total Assets", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
                {"id": "revenue", "name": "Revenue", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
                {"id": "net_income", "name": "Net Income", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
                {"id": "eps_estimate", "name": "EPS Estimate", "dataset": "ANALYST_ESTIMATES", "category": "Estimates", "type": "FLOAT"},
                {"id": "sales", "name": "Total Sales", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
                {"id": "debt", "name": "Long-Term Debt", "dataset": "FUNDAMENTALS", "category": "Balance Sheet", "type": "FLOAT"},
                {"id": "cash", "name": "Cash and Equivalents", "dataset": "FUNDAMENTALS", "category": "Balance Sheet", "type": "FLOAT"},
                {"id": "fcf", "name": "Free Cash Flow", "dataset": "FUNDAMENTALS", "category": "Cash Flow", "type": "FLOAT"},
                {"id": "book_value", "name": "Book Value Per Share", "dataset": "FUNDAMENTALS", "category": "Financials", "type": "FLOAT"},
                {"id": "shares_out", "name": "Shares Outstanding", "dataset": "STRUCTURE", "category": "Corporate", "type": "INTEGER"}
            ]
            return {"results": mock_fields[:limit], "count": len(mock_fields)}

        if not self.is_authenticated or not self.client:
            raise Exception("Client is not authenticated.")

        # Real Brain API v2 query for finding data-fields
        # URL pattern: https://api.worldquantbrain.com/api/v2/data-fields
        url = f"{self.base_url}/api/v2/data-fields"
        params = {
            "region": region,
            "universe": universe,
            "limit": limit
        }
        
        try:
            res = await self.client.get(url, params=params)
            if res.status_code == 200:
                return res.json()
            else:
                logger.error(f"Error fetching data fields: {res.status_code} - {res.text}")
                return {"results": [], "count": 0}
        except Exception as e:
            logger.exception("Error fetching data fields from API")
            return {"results": [], "count": 0}

    async def submit_simulation(self, expression: str, settings_dict: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """
        Submits an alpha expression to WorldQuant BRAIN simulation engine.
        Returns: Tuple[simulation_id or None, error_message or None]
        """
        if self.use_mock:
            await asyncio.sleep(0.1)
            sim_id = f"sim-{random.randint(10000000, 99999999)}"
            # Setup initial state for mock polling
            self._mock_simulations[sim_id] = {
                "id": sim_id,
                "status": "QUEUED",
                "code": expression,
                "created_at": time.time(),
                "metrics": None
            }
            logger.info(f"Mock simulation submitted. ID: {sim_id}")
            return sim_id, None

        if not self.is_authenticated or not self.client:
            return None, "Client is not authenticated."

        payload = {
            "type": "REGULAR",
            "settings": {
                "instrumentType": settings_dict.get("instrumentType", "EQUITY"),
                "region": settings_dict.get("region", "USA"),
                "universe": settings_dict.get("universe", "TOP3000"),
                "delay": int(settings_dict.get("delay", 1)),
                "decay": int(settings_dict.get("decay", 0)),
                "neutralization": settings_dict.get("neutralization", "SUBINDUSTRY"),
                "truncation": 0.08,
                "pasteurization": "ON",
                "unitHandling": "VERIFY",
                "nanHandling": "OFF",
                "language": "FASTEXPR",
                "visualization": False
            },
            "code": expression
        }
        
        headers = {"Content-Type": "application/json"}
        url = f"{self.base_url}/simulations"

        try:
            res = await self.client.post(url, headers=headers, json=payload)
            
            # WQ BRAIN returns 201 Created and provides simulation details URL in 'Location' header
            if res.status_code == 201:
                location = res.headers.get("Location")
                if not location:
                    return None, "Simulation started but Location header is missing."
                # Extract simulation ID from location url
                sim_id = location.split("/")[-1]
                logger.info(f"Simulation successfully submitted to WQ BRAIN. ID: {sim_id}")
                return sim_id, None
            
            # Handle rate limiting or error states
            if res.status_code == 429:
                retry_after = res.headers.get("Retry-After", "10")
                logger.error(f"Rate limited by WQ API. Retry-After header: {retry_after}s")
                return None, f"RATE_LIMIT:{retry_after}"
                
            return None, f"API Error {res.status_code}: {res.text}"
        except Exception as e:
            logger.exception("HTTP simulation submit failed")
            return None, f"HTTP request error: {str(e)}"

    async def get_simulation_status(self, sim_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Polls the status of an ongoing simulation.
        Returns: Tuple[simulation_data_dict or None, error_message or None]
        """
        if self.use_mock:
            await asyncio.sleep(0.1)
            mock_sim = self._mock_simulations.get(sim_id)
            if not mock_sim:
                return None, f"Mock simulation {sim_id} not found."
            
            # Progress mock state machine based on elapsed time
            elapsed = time.time() - mock_sim["created_at"]
            if mock_sim["status"] == "QUEUED" and elapsed > 2.0:
                mock_sim["status"] = "RUNNING"
            if mock_sim["status"] == "RUNNING" and elapsed > 5.0:
                mock_sim["status"] = "COMPLETE"
                
                # Determine metric properties based on expression structures to make it look realistic
                expr = mock_sim["code"]
                
                # Dynamic performance based on formula elements
                random.seed(hash(expr))
                
                # Default mock performance ranges
                sharpe = random.uniform(-0.5, 2.5)
                fitness = random.uniform(-0.2, 3.0)
                turnover = random.uniform(0.01, 1.20)
                margin = random.uniform(-2.0, 45.0)  # bps
                returns = sharpe * turnover * 0.1  # rough estimation
                
                # AST terms adjustments (reward complex neutralizations / decays)
                if "group_neutralize" in expr:
                    turnover *= 0.7  # neutralizing lowers turnover
                    sharpe += 0.5
                    fitness += 0.6
                if "ts_decay_linear" in expr:
                    turnover *= 0.55  # decay dampens turnover significantly
                    sharpe += 0.3
                if "rank" in expr:
                    sharpe += 0.2
                    fitness += 0.2
                    
                # Store mock metrics
                alpha_id = f"alpha-{random.randint(100000, 999999)}"
                mock_sim["metrics"] = {
                    "status": "COMPLETE",
                    "alpha": alpha_id,
                    "is": {
                        "sharpe": round(sharpe, 3),
                        "fitness": round(fitness, 3),
                        "turnover": round(turnover, 3),
                        "returns": round(returns, 4),
                        "margin": round(margin, 5),
                        "drawdown": round(random.uniform(0.01, 0.25), 4)
                    }
                }
                
            if mock_sim["status"] == "COMPLETE":
                return mock_sim["metrics"], None
            
            return {"status": mock_sim["status"]}, None

        if not self.is_authenticated or not self.client:
            return None, "Client is not authenticated."

        url = f"{self.base_url}/simulations/{sim_id}"
        try:
            res = await self.client.get(url)
            if res.status_code == 200:
                data = res.json()
                return data, None
            
            if res.status_code == 424:
                return None, "Dependency failed error."
            
            return None, f"API Error {res.status_code}: {res.text}"
        except Exception as e:
            logger.exception("HTTP status poll failed")
            return None, f"HTTP status error: {str(e)}"
            
    async def submit_alpha_for_review(self, alpha_id: str) -> Tuple[bool, str]:
        """
        Submits a qualified alpha to the BRAIN registry registry.
        Returns: Tuple[is_successful, message_or_error]
        """
        if self.use_mock:
            await asyncio.sleep(0.3)
            return True, f"Mock Alpha {alpha_id} submitted for review successfully!"

        if not self.is_authenticated or not self.client:
            return False, "Client is not authenticated."

        # The WorldQuant Brain API submission workflow involves posting the alpha ID to the registrations endpoint
        url = f"{self.base_url}/registrations"
        payload = {"alpha": alpha_id}
        
        try:
            res = await self.client.post(url, json=payload)
            if res.status_code in [200, 201]:
                return True, "Alpha submitted for review successfully!"
            return False, f"Failed to submit: API returned code {res.status_code}: {res.text}"
        except Exception as e:
            logger.exception("Failed submitting alpha record")
            return False, f"Request exception: {str(e)}"
