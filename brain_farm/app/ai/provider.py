from abc import ABC, abstractmethod
from enum import Enum
from typing import Tuple, Dict, Any, Optional

class AIProviderState(str, Enum):
    NOT_CONFIGURED = "AI_NOT_CONFIGURED"
    CONFIGURED = "AI_CONFIGURED"
    VALIDATING = "AI_VALIDATING"
    AVAILABLE = "AI_AVAILABLE"
    INVALID = "AI_INVALID"
    RATE_LIMITED = "AI_RATE_LIMITED"
    PROVIDER_ERROR = "AI_PROVIDER_ERROR"
    DISABLED = "AI_DISABLED"

class AIProvider(ABC):
    """Abstract interface for AI model providers (OpenAI, Gemini, Anthropic, Local, etc.)."""

    def __init__(self, provider_name: str, default_model: str):
        self.provider_name = provider_name
        self.default_model = default_model

    @abstractmethod
    async def validate_key(self, api_key: str, model: Optional[str] = None) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates API key with a minimal authenticated request.
        Returns: Tuple[is_valid, status_message, safe_metadata]
        """
        pass

    @abstractmethod
    async def generate_json(
        self,
        api_key: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: float = 20.0
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Dict[str, Any]]:
        """
        Executes an authenticated generation request expecting structured JSON.
        Returns: Tuple[parsed_json_dict, error_message, usage_metadata]
        """
        pass

    @abstractmethod
    def get_supported_models(self) -> list[str]:
        """Returns list of supported/recommended model IDs."""
        pass
