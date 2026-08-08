import asyncio
import httpx
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional
from brain_farm.app.core.config import settings

logger = logging.getLogger("brain_farm.brain_client")

# WorldQuant BRAIN sessions expire after ~24 hours (same as website)
SESSION_TTL_HOURS = 23


class BrainClient:
    """Async HTTP Client for WorldQuant BRAIN API with session expiry and mock mode support."""

    def __init__(self, email: str, password: str, use_mock: bool = False):
        self.email = email
        self.password = password
        self.base_url = settings.BRAIN_API_URL
        self.use_mock = use_mock or email.lower().endswith("mock.com")
        self.client: Optional[httpx.AsyncClient] = None
        self.is_authenticated = False
        self._auth_time: Optional[datetime] = None   # timestamp of last successful auth

        # In-memory storage for active mock simulations to support polling
        self._mock_simulations: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self):
        if not self.use_mock:
            self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    def session_age_minutes(self) -> Optional[int]:
        """Return how many minutes ago the session was established, or None."""
        if self._auth_time is None:
            return None
        return int((datetime.utcnow() - self._auth_time).total_seconds() / 60)

    def is_session_expired(self) -> bool:
        """True if the session is older than SESSION_TTL_HOURS (matches website behaviour)."""
        if self._auth_time is None:
            return True
        return datetime.utcnow() - self._auth_time > timedelta(hours=SESSION_TTL_HOURS)

    async def check_session(self) -> Tuple[bool, str]:
        """
        Verify whether the current session is still valid against the live API.
        Returns (True, message) if okay, (False, reason) if expired or invalid.
        """
        if self.use_mock:
            if self.is_session_expired():
                self.is_authenticated = False
                return False, "Mock session expired. Please re-authenticate."
            return True, "Mock session is active."

        if not self.is_authenticated or not self.client:
            return False, "Not authenticated."

        if self.is_session_expired():
            self.is_authenticated = False
            return False, f"Session expired after {SESSION_TTL_HOURS}h. Please re-authenticate."

        # Ping a lightweight endpoint to verify live cookie validity
        try:
            res = await self.client.get(f"{self.base_url}/authentication")
            if res.status_code in (200, 201):
                return True, "Session is active."
            if res.status_code in (401, 403):
                self.is_authenticated = False
                return False, "Session expired (401 Unauthorised). Please re-authenticate."
            return False, f"Session check returned {res.status_code}."
        except Exception as e:
            return False, f"Session check network error: {str(e)}"

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self) -> Tuple[bool, str]:
        """
        Mock-mode shortcut: single-step authentication.
        For live mode use authenticate_step1() + authenticate_step2().
        """
        if self.use_mock:
            await asyncio.sleep(0.5)
            if "fail" in self.email.lower():
                return False, "Auth failed: user credentials rejected."
            self.is_authenticated = True
            self._auth_time = datetime.utcnow()
            logger.info("Mock authentication successful.")
            return True, "Mock Session authenticated successfully!"
        # Live: delegate to step1 (for code that still calls authenticate())
        return await self.authenticate_step1()

    async def authenticate_step1(self) -> Tuple[bool, str]:
        """
        Step 1: open a streaming GET /authentication with Basic Auth.
        The BRAIN API holds the TCP connection open after sending the 202 header
        (never delivers a response body until OTP is accepted). By using
        `stream()` we can read the status code / headers immediately and
        return (True, 'OTP_SENT') without blocking on the body.
        The open stream is stored so cookies are preserved for step 2.
        """
        if self.use_mock:
            return await self.authenticate()

        HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        if not self.client:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=120.0, write=10.0, pool=10.0),
                follow_redirects=True,
                headers=HEADERS,
            )

        auth_url = f"{self.base_url}/authentication"

        try:
            # Open streaming request — reads headers without waiting for body
            self._auth_stream = self.client.stream(
                "GET", auth_url, auth=(self.email, self.password)
            )
            res = await self._auth_stream.__aenter__()

            logger.info(f"Auth step1 stream headers: {res.status_code} | {dict(res.headers)}")

            if res.status_code in (200, 201, 204):
                # Direct success (no OTP needed)
                self.is_authenticated = True
                self._auth_time = datetime.utcnow()
                await self._auth_stream.__aexit__(None, None, None)
                return True, "Live session authenticated successfully!"

            if res.status_code == 202:
                # OTP sent — keep stream open in background; use cookies for step 2
                logger.info(f"BRAIN {res.status_code}: OTP sent to email, stream kept open.")
                return True, "OTP_SENT"


            # Error — read body for diagnostics
            body = ""
            async for chunk in res.aiter_text():
                body += chunk
                if len(body) > 300:
                    break
            await self._auth_stream.__aexit__(None, None, None)

            if res.status_code == 401:
                return False, f"Invalid credentials (401): {body[:200]}"
            if res.status_code == 403:
                return False, f"Forbidden (403): {body[:200]}"
            if res.status_code == 429:
                retry = res.headers.get("Retry-After", "60")
                return False, f"Too many attempts — retry in {retry}s."
            return False, f"Unexpected ({res.status_code}): {body[:200]}"

        except httpx.ConnectError:
            return False, "Network error: Cannot reach api.worldquantbrain.com."
        except Exception as e:
            logger.exception("Error during auth step1")
            return False, f"Error: {str(e)}"

    async def authenticate_step2(self, otp_code: str) -> Tuple[bool, str]:
        """
        Step 2: PATCH /authentication with the OTP code.
        The BRAIN API accepts the OTP via PATCH with JSON body {"otp": "<code>"}.
        This same-session PATCH resolves the pending streaming request from step1
        and grants the authenticated session cookie.
        """
        if not self.client:
            return False, "Session lost. Please restart authentication."

        try:
            auth_url = f"{self.base_url}/authentication"
            res = await self.client.patch(
                auth_url,
                json={"otp": otp_code.strip()},
            )

            logger.info(f"Auth step2 PATCH: {res.status_code} | {res.text[:200]}")

            if res.status_code in (200, 201):
                self.is_authenticated = True
                self._auth_time = datetime.utcnow()
                # Close the background stream now that auth is complete
                try:
                    await self._auth_stream.__aexit__(None, None, None)
                except Exception:
                    pass
                return True, "Live session authenticated successfully!"

            if res.status_code == 401:
                return False, f"Invalid or expired OTP (401): {res.text[:150]}"
            if res.status_code == 403:
                return False, f"OTP rejected (403): {res.text[:150]}"

            return False, f"OTP failed ({res.status_code}): {res.text[:200]}"

        except Exception as e:
            logger.exception("Error during auth step2")
            return False, f"Error: {str(e)}"


    async def get_data_fields(self, region: str = "USA", universe: str = "TOP3000", limit: int = 50) -> Dict[str, Any]:
        """Fetch available data fields from the BRAIN data API."""
        if self.use_mock:
            await asyncio.sleep(0.2)
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
                {"id": "shares_out", "name": "Shares Outstanding", "dataset": "STRUCTURE", "category": "Corporate", "type": "INTEGER"},
            ]
            return {"results": mock_fields[:limit], "count": len(mock_fields)}

        if not self.is_authenticated or not self.client:
            raise Exception("Client is not authenticated.")

        url = f"{self.base_url}/api/v2/data-fields"
        params = {"region": region, "universe": universe, "limit": limit}
        try:
            res = await self.client.get(url, params=params)
            if res.status_code == 200:
                return res.json()
            if res.status_code in (401, 403):
                self.is_authenticated = False
                raise Exception("Session expired. Please re-authenticate.")
            logger.error(f"Error fetching data fields: {res.status_code} - {res.text}")
            return {"results": [], "count": 0}
        except Exception as e:
            logger.exception("Error fetching data fields from API")
            return {"results": [], "count": 0}

    # ------------------------------------------------------------------
    # Simulation submission
    # ------------------------------------------------------------------

    async def submit_simulation(self, expression: str, settings_dict: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """Submit an alpha expression to the BRAIN simulation engine."""
        if self.use_mock:
            await asyncio.sleep(0.1)
            sim_id = f"sim-{random.randint(10000000, 99999999)}"
            self._mock_simulations[sim_id] = {
                "id": sim_id,
                "status": "QUEUED",
                "code": expression,
                "created_at": time.time(),
                "metrics": None,
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
                "visualization": False,
            },
            "code": expression,
        }

        try:
            res = await self.client.post(f"{self.base_url}/simulations",
                                         headers={"Content-Type": "application/json"},
                                         json=payload)
            if res.status_code == 201:
                location = res.headers.get("Location")
                if not location:
                    return None, "Simulation started but Location header is missing."
                sim_id = location.split("/")[-1]
                logger.info(f"Simulation submitted. ID: {sim_id}")
                return sim_id, None
            if res.status_code == 429:
                retry_after = res.headers.get("Retry-After", "10")
                return None, f"RATE_LIMIT:{retry_after}"
            if res.status_code in (401, 403):
                self.is_authenticated = False
                return None, "Session expired during submission. Please re-authenticate."
            return None, f"API Error {res.status_code}: {res.text}"
        except Exception as e:
            logger.exception("HTTP simulation submit failed")
            return None, f"HTTP request error: {str(e)}"

    # ------------------------------------------------------------------
    # Status polling
    # ------------------------------------------------------------------

    async def get_simulation_status(self, sim_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Poll the status of an ongoing simulation."""
        if self.use_mock:
            await asyncio.sleep(0.1)
            mock_sim = self._mock_simulations.get(sim_id)
            if not mock_sim:
                return None, f"Mock simulation {sim_id} not found."

            elapsed = time.time() - mock_sim["created_at"]
            if mock_sim["status"] == "QUEUED" and elapsed > 2.0:
                mock_sim["status"] = "RUNNING"
            if mock_sim["status"] == "RUNNING" and elapsed > 5.0:
                mock_sim["status"] = "COMPLETE"
                expr = mock_sim["code"]
                random.seed(hash(expr))
                sharpe = random.uniform(-0.5, 2.5)
                fitness = random.uniform(-0.2, 3.0)
                turnover = random.uniform(0.01, 1.20)
                margin = random.uniform(-2.0, 45.0)
                returns = sharpe * turnover * 0.1
                if "group_neutralize" in expr:
                    turnover *= 0.7
                    sharpe += 0.5
                    fitness += 0.6
                if "ts_decay_linear" in expr:
                    turnover *= 0.55
                    sharpe += 0.3
                if "rank" in expr:
                    sharpe += 0.2
                    fitness += 0.2
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
                        "drawdown": round(random.uniform(0.01, 0.25), 4),
                    },
                    "subUniverseSharpe": {
                        "TOP2000": round(sharpe * 0.88, 3),
                        "TOP1000": round(sharpe * 0.76, 3),
                    },
                }

            if mock_sim["status"] == "COMPLETE":
                return mock_sim["metrics"], None
            return {"status": mock_sim["status"]}, None

        if not self.is_authenticated or not self.client:
            return None, "Client is not authenticated."

        try:
            res = await self.client.get(f"{self.base_url}/simulations/{sim_id}")
            if res.status_code == 200:
                return res.json(), None
            if res.status_code == 424:
                return None, "Dependency failed."
            if res.status_code in (401, 403):
                self.is_authenticated = False
                return None, "Session expired. Please re-authenticate."
            return None, f"API Error {res.status_code}: {res.text}"
        except Exception as e:
            logger.exception("HTTP status poll failed")
            return None, f"HTTP status error: {str(e)}"

    # ------------------------------------------------------------------
    # Alpha registration
    # ------------------------------------------------------------------

    async def submit_alpha_for_review(self, alpha_id: str) -> Tuple[bool, str]:
        """Submit a qualified alpha to the BRAIN registry."""
        if self.use_mock:
            await asyncio.sleep(0.3)
            return True, f"Mock Alpha {alpha_id} submitted for review successfully!"

        if not self.is_authenticated or not self.client:
            return False, "Client is not authenticated."

        try:
            res = await self.client.post(f"{self.base_url}/registrations", json={"alpha": alpha_id})
            if res.status_code in (200, 201):
                return True, "Alpha submitted for review on WorldQuant BRAIN!"
            if res.status_code in (401, 403):
                self.is_authenticated = False
                return False, "Session expired. Please re-authenticate before submitting."
            return False, f"Submission failed ({res.status_code}): {res.text[:200]}"
        except Exception as e:
            logger.exception("Failed submitting alpha record")
            return False, f"Request error: {str(e)}"
