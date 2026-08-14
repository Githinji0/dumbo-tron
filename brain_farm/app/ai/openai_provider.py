import json
import re
import time
import httpx
import logging
from typing import Tuple, Dict, Any, Optional, List
from brain_farm.app.ai.provider import AIProvider
from brain_farm.app.ai.security import redact_sensitive_text, log_safe_event

logger = logging.getLogger("brain_farm.ai.openai")

class OpenAIProvider(AIProvider):
    def __init__(self):
        super().__init__(provider_name="openai", default_model="gpt-4o-mini")

    def get_supported_models(self) -> List[str]:
        return ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo", "o1-mini"]

    async def validate_key(self, api_key: str, model: Optional[str] = None) -> Tuple[bool, str, Dict[str, Any]]:
        if not api_key or not api_key.strip():
            return False, "API key cannot be empty.", {}

        cleaned_key = api_key.strip()
        headers = {
            "Authorization": f"Bearer {cleaned_key}",
            "Content-Type": "application/json"
        }
        target_model = model.strip() if model and model.strip() else self.default_model

        log_safe_event("AI_VALIDATION_STARTED", {"provider": self.provider_name, "model": target_model})
        start_t = time.perf_counter()

        try:
            # Minimal model list verification or 1-token query
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://api.openai.com/v1/models", headers=headers)
                latency = round(time.perf_counter() - start_t, 3)

                if res.status_code == 200:
                    log_safe_event("AI_VALIDATION_SUCCESS", {"provider": self.provider_name, "latency": latency})
                    return True, "OpenAI API connection verified successfully.", {"latency": latency}
                elif res.status_code in (401, 403):
                    log_safe_event("AI_VALIDATION_FAILED", {"provider": self.provider_name, "status_code": res.status_code})
                    return False, "The OpenAI API rejected the supplied API key (Authentication Error).", {"status_code": res.status_code}
                elif res.status_code == 429:
                    log_safe_event("AI_VALIDATION_FAILED", {"provider": self.provider_name, "status_code": 429})
                    return False, "OpenAI Rate limit exceeded or insufficient quota.", {"status_code": 429}
                else:
                    err_msg = f"OpenAI validation returned HTTP {res.status_code}"
                    return False, err_msg, {"status_code": res.status_code}
        except httpx.TimeoutException:
            return False, "Connection to OpenAI API timed out.", {"error": "timeout"}
        except Exception as e:
            safe_err = redact_sensitive_text(str(e))
            logger.error(f"OpenAI validation error: {safe_err}")
            return False, f"Connection failed: {safe_err}", {"error": safe_err}

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
        if not api_key:
            return None, "No OpenAI API key provided.", {}

        target_model = model.strip() if model and model.strip() else self.default_model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"}
        }

        log_safe_event("AI_REQUEST_STARTED", {"provider": self.provider_name, "model": target_model})
        start_t = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
                latency = round(time.perf_counter() - start_t, 3)

                if res.status_code == 200:
                    data = res.json()
                    content_str = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    tokens_in = usage.get("prompt_tokens", 0)
                    tokens_out = usage.get("completion_tokens", 0)
                    total_tokens = usage.get("total_tokens", 0)
                    # Approximate cost calculation for gpt-4o-mini ($0.15/1M input, $0.60/1M output)
                    cost = (tokens_in * 0.00000015) + (tokens_out * 0.00000060)

                    parsed_json = self._extract_json(content_str)
                    if parsed_json is not None:
                        log_safe_event("AI_REQUEST_SUCCESS", {"provider": self.provider_name, "latency": latency, "tokens": total_tokens})
                        return parsed_json, None, {
                            "latency": latency,
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                            "total_tokens": total_tokens,
                            "estimated_cost": cost,
                            "model": target_model
                        }
                    else:
                        return None, "Model response was not valid JSON.", {"latency": latency}
                elif res.status_code in (401, 403):
                    return None, "OpenAI Authentication failed. Check your API key.", {"status_code": res.status_code}
                elif res.status_code == 429:
                    return None, "OpenAI rate limit or quota exceeded.", {"status_code": 429}
                else:
                    return None, f"OpenAI API error (HTTP {res.status_code})", {"status_code": res.status_code}
        except httpx.TimeoutException:
            log_safe_event("AI_REQUEST_FAILED", {"provider": self.provider_name, "error": "timeout"})
            return None, f"OpenAI request timed out after {timeout}s.", {"error": "timeout"}
        except Exception as e:
            safe_err = redact_sensitive_text(str(e))
            log_safe_event("AI_REQUEST_FAILED", {"provider": self.provider_name, "error": safe_err})
            return None, f"OpenAI error: {safe_err}", {"error": safe_err}

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Safely parses JSON even if wrapped in markdown markdown fences."""
        if not text:
            return None
        text = text.strip()
        # Strip markdown ```json ... ``` fences if present
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1).strip()
        try:
            return json.loads(text)
        except Exception:
            # Try to find first { and last }
            first_brace = text.find("{")
            last_brace = text.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                try:
                    return json.loads(text[first_brace:last_brace + 1])
                except Exception:
                    pass
        return None
