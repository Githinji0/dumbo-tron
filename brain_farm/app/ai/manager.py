import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List
from brain_farm.app.ai.provider import AIProvider, AIProviderState
from brain_farm.app.ai.openai_provider import OpenAIProvider
from brain_farm.app.ai.gemini_provider import GeminiProvider
from brain_farm.app.ai.security import redact_sensitive_text, log_safe_event
from brain_farm.app.core.config import settings
from brain_farm.app.core.security import encrypt_data, decrypt_data

logger = logging.getLogger("brain_farm.ai.manager")

class AIManager:
    """Central orchestrator for AI providers, credentials, feature flags, budgets, and fail-safe routing."""

    def __init__(self):
        self.providers: Dict[str, AIProvider] = {
            "openai": OpenAIProvider(),
            "gemini": GeminiProvider(),
        }
        self.current_provider_name: str = "gemini"
        self.current_model: str = "gemini-1.5-flash"
        self.state: AIProviderState = AIProviderState.NOT_CONFIGURED
        self.last_validated: Optional[str] = None
        self.validation_message: str = "AI features are optional. Dumbo-Tron operates normally without an AI key."

        # Encrypted in-memory storage of the API key
        self._encrypted_key: Optional[str] = None

        # Feature flags
        self.features: Dict[str, bool] = {
            "enabled": True,
            "hypothesis": True,
            "failure_analysis": True,
            "near_miss": True,
            "turnover_opt": True,
            "director": True,
            "critic": True,
            "summary": True
        }

        # Usage & Budget tracking
        self.daily_calls: int = 0
        self.monthly_calls: int = 0
        self.feature_calls: Dict[str, int] = {
            "hypothesis": 0,
            "failure_analysis": 0,
            "near_miss": 0,
            "turnover_opt": 0,
            "director": 0,
            "critic": 0,
            "summary": 0
        }
        self.estimated_total_cost: float = 0.0
        self.max_daily_budget_calls: int = 200

        # Load environment fallback key if present
        self._initialize_from_env()

    def _initialize_from_env(self):
        """Discovers any pre-configured environment variable keys safely."""
        if settings.GEMINI_API_KEY:
            self.set_credentials("gemini", settings.GEMINI_API_KEY, model="gemini-1.5-flash")
            self.state = AIProviderState.CONFIGURED
        elif settings.OPENAI_API_KEY:
            self.set_credentials("openai", settings.OPENAI_API_KEY, model="gpt-4o-mini")
            self.state = AIProviderState.CONFIGURED

    def get_provider(self, provider_name: Optional[str] = None) -> Optional[AIProvider]:
        name = provider_name or self.current_provider_name
        return self.providers.get(name.lower())

    def set_credentials(self, provider: str, raw_key: str, model: Optional[str] = None):
        """Encrypts and stores credential in server-side memory."""
        prov = provider.lower().strip()
        if prov in self.providers:
            self.current_provider_name = prov
            if model and model.strip():
                self.current_model = model.strip()
            else:
                self.current_model = self.providers[prov].default_model

        if raw_key and raw_key.strip():
            self._encrypted_key = encrypt_data(raw_key.strip())
            self.state = AIProviderState.CONFIGURED
        else:
            self._encrypted_key = None
            self.state = AIProviderState.NOT_CONFIGURED

    def get_decrypted_key(self) -> Optional[str]:
        """Internal backend-only decryption."""
        if not self._encrypted_key:
            return None
        return decrypt_data(self._encrypted_key)

    def is_available(self, feature_name: Optional[str] = None) -> bool:
        """Determines whether AI layer can be queried."""
        if not self.features.get("enabled", True):
            return False
        if feature_name and not self.features.get(feature_name, True):
            return False
        if self.state not in (AIProviderState.AVAILABLE, AIProviderState.CONFIGURED):
            return False
        if not self._encrypted_key:
            return False
        if self.daily_calls >= self.max_daily_budget_calls:
            logger.warning("AIManager: Daily AI call budget reached. Fallback to deterministic mode.")
            return False
        return True

    async def validate_active_provider(self) -> Tuple[bool, str]:
        """Validates current configured provider credentials."""
        provider = self.get_provider()
        if not provider:
            self.state = AIProviderState.PROVIDER_ERROR
            self.validation_message = f"Unknown provider: {self.current_provider_name}"
            return False, self.validation_message

        key = self.get_decrypted_key()
        if not key:
            self.state = AIProviderState.NOT_CONFIGURED
            self.validation_message = "No API key configured."
            return False, self.validation_message

        self.state = AIProviderState.VALIDATING
        is_valid, msg, meta = await provider.validate_key(key, self.current_model)
        self.last_validated = datetime.now(timezone.utc).isoformat()

        if is_valid:
            self.state = AIProviderState.AVAILABLE
            self.validation_message = msg
            return True, msg
        else:
            if meta.get("status_code") == 429:
                self.state = AIProviderState.RATE_LIMITED
            else:
                self.state = AIProviderState.INVALID
            self.validation_message = msg
            return False, msg

    async def execute_structured_request(
        self,
        feature_name: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: float = 20.0
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Executes structured generation using the active provider with automatic fallback and budget recording.
        """
        if not self.is_available(feature_name):
            log_safe_event("AI_FALLBACK_ACTIVATED", {"feature": feature_name, "reason": "AI unavailable or disabled"})
            return None, "AI is unavailable or feature is disabled."

        provider = self.get_provider()
        key = self.get_decrypted_key()
        if not provider or not key:
            return None, "Provider or key missing."

        try:
            data, err, usage = await provider.generate_json(
                api_key=key,
                prompt=prompt,
                system_prompt=system_prompt,
                model=self.current_model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout
            )

            if err:
                logger.warning(f"AIManager call failed for feature '{feature_name}': {err}")
                log_safe_event("AI_FALLBACK_ACTIVATED", {"feature": feature_name, "reason": err})
                return None, err

            # Update usage metrics
            self.daily_calls += 1
            self.monthly_calls += 1
            self.feature_calls[feature_name] = self.feature_calls.get(feature_name, 0) + 1
            self.estimated_total_cost += usage.get("estimated_cost", 0.0)

            return data, None

        except Exception as e:
            safe_err = redact_sensitive_text(str(e))
            logger.error(f"AIManager exception during '{feature_name}': {safe_err}")
            log_safe_event("AI_FALLBACK_ACTIVATED", {"feature": feature_name, "reason": safe_err})
            return None, safe_err

    def get_safe_status(self) -> Dict[str, Any]:
        """Returns safe status payload without exposing credentials."""
        return {
            "configured": bool(self._encrypted_key),
            "valid": self.state == AIProviderState.AVAILABLE,
            "state": self.state.value,
            "provider": self.current_provider_name,
            "model": self.current_model,
            "message": self.validation_message,
            "last_validated": self.last_validated,
            "enabled_features": self.features,
            "daily_calls": self.daily_calls,
            "monthly_calls": self.monthly_calls,
            "feature_calls": self.feature_calls,
            "estimated_cost": round(self.estimated_total_cost, 4),
            "available_providers": list(self.providers.keys()),
            "supported_models": {
                name: prov.get_supported_models() for name, prov in self.providers.items()
            }
        }

# Global singleton
ai_manager = AIManager()
