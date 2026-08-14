import json
import re
import time
import httpx
import logging
from typing import Tuple, Dict, Any, Optional, List
from brain_farm.app.ai.provider import AIProvider
from brain_farm.app.ai.security import redact_sensitive_text, log_safe_event

logger = logging.getLogger("brain_farm.ai.gemini")

class GeminiProvider(AIProvider):
    def __init__(self):
        super().__init__(provider_name="gemini", default_model="gemini-1.5-flash")

    def get_supported_models(self) -> List[str]:
        return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash", "gemini-1.0-pro"]

    async def validate_key(self, api_key: str, model: Optional[str] = None) -> Tuple[bool, str, Dict[str, Any]]:
        if not api_key or not api_key.strip():
            return False, "API key cannot be empty.", {}

        cleaned_key = api_key.strip()
        target_model = model.strip() if model and model.strip() else self.default_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent"

        headers = {
            "x-goog-api-key": cleaned_key,
            "Content-Type": "application/json"
        }
        # Minimal probe payload
        payload = {
            "contents": [{"parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 2}
        }

        log_safe_event("AI_VALIDATION_STARTED", {"provider": self.provider_name, "model": target_model})
        start_t = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                latency = round(time.perf_counter() - start_t, 3)

                if res.status_code == 200:
                    log_safe_event("AI_VALIDATION_SUCCESS", {"provider": self.provider_name, "latency": latency})
                    return True, "Google Gemini connection verified successfully.", {"latency": latency}
                elif res.status_code in (400, 401, 403):
                    log_safe_event("AI_VALIDATION_FAILED", {"provider": self.provider_name, "status_code": res.status_code})
                    return False, "Gemini API key rejected or invalid model name.", {"status_code": res.status_code}
                elif res.status_code == 429:
                    log_safe_event("AI_VALIDATION_FAILED", {"provider": self.provider_name, "status_code": 429})
                    return False, "Gemini Rate limit or quota exceeded.", {"status_code": 429}
                else:
                    return False, f"Gemini validation returned HTTP {res.status_code}", {"status_code": res.status_code}
        except httpx.TimeoutException:
            return False, "Connection to Google Gemini API timed out.", {"error": "timeout"}
        except Exception as e:
            safe_err = redact_sensitive_text(str(e))
            logger.error(f"Gemini validation error: {safe_err}")
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
            return None, "No Gemini API key provided.", {}

        target_model = model.strip() if model and model.strip() else self.default_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent"

        headers = {
            "x-goog-api-key": api_key.strip(),
            "Content-Type": "application/json"
        }

        full_prompt = prompt
        if system_prompt:
            full_prompt = f"System Instructions:\n{system_prompt}\n\nUser Request:\n{prompt}\n\nIMPORTANT: Output ONLY a valid JSON object. Do not include markdown codeblocks or conversational text."

        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json"
            }
        }

        log_safe_event("AI_REQUEST_STARTED", {"provider": self.provider_name, "model": target_model})
        start_t = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(url, headers=headers, json=payload)
                latency = round(time.perf_counter() - start_t, 3)

                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        return None, "No candidate response from Gemini.", {"latency": latency}

                    parts = candidates[0].get("content", {}).get("parts", [])
                    content_str = parts[0].get("text", "") if parts else ""

                    usage = data.get("usageMetadata", {})
                    tokens_in = usage.get("promptTokenCount", 0)
                    tokens_out = usage.get("candidatesTokenCount", 0)
                    total_tokens = usage.get("totalTokenCount", 0)
                    # Gemini 1.5 Flash is very cost-effective (~$0.075 / 1M prompt, $0.30 / 1M output)
                    cost = (tokens_in * 0.000000075) + (tokens_out * 0.00000030)

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
                elif res.status_code in (400, 401, 403):
                    return None, "Gemini Authentication failed. Check your API key.", {"status_code": res.status_code}
                elif res.status_code == 429:
                    return None, "Gemini rate limit or quota exceeded.", {"status_code": 429}
                else:
                    return None, f"Gemini API error (HTTP {res.status_code})", {"status_code": res.status_code}
        except httpx.TimeoutException:
            log_safe_event("AI_REQUEST_FAILED", {"provider": self.provider_name, "error": "timeout"})
            return None, f"Gemini request timed out after {timeout}s.", {"error": "timeout"}
        except Exception as e:
            safe_err = redact_sensitive_text(str(e))
            log_safe_event("AI_REQUEST_FAILED", {"provider": self.provider_name, "error": safe_err})
            return None, f"Gemini error: {safe_err}", {"error": safe_err}

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        text = text.strip()
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1).strip()
        try:
            return json.loads(text)
        except Exception:
            first_brace = text.find("{")
            last_brace = text.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                try:
                    return json.loads(text[first_brace:last_brace + 1])
                except Exception:
                    pass
        return None
