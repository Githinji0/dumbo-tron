import re
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("brain_farm.ai.security")

# Sensitive patterns to redact from logs and prompts
SENSITIVE_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{15,}"), r"\1[REDACTED_TOKEN]"),
    (re.compile(r"(?i)(api[_-]?key[\"'\s:=]+)[a-zA-Z0-9_\-]{15,}"), r"\1[REDACTED_API_KEY]"),
    (re.compile(r"(?i)(sk-[a-zA-Z0-9_\-]{15,})"), r"[REDACTED_OPENAI_KEY]"),
    (re.compile(r"(?i)(AIza[0-9A-Za-z-_]{35})"), r"[REDACTED_GEMINI_KEY]"),
    (re.compile(r"(?i)(password[\"'\s:=]+)[\"']?[^\"'\s,]+[\"']?"), r"\1[REDACTED_PASSWORD]"),
    (re.compile(r"(?i)(cookie[\"'\s:=]+)[\"']?[^\"'\s,]+[\"']?"), r"\1[REDACTED_COOKIE]"),
    (re.compile(r"(?i)(authorization[\"'\s:=]+)[\"']?[^\"'\s,]+[\"']?"), r"\1[REDACTED_AUTH]"),
]

def redact_sensitive_text(text: Optional[str]) -> str:
    """Removes API keys, passwords, cookies, and tokens from any string."""
    if not text:
        return ""
    redacted = str(text)
    for pattern, replacement in SENSITIVE_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted

def log_safe_event(event_type: str, details: Optional[Dict[str, Any]] = None):
    """
    Logs an AI observability lifecycle event without any credential exposure.
    Events:
      AI_PROVIDER_SELECTED
      AI_VALIDATION_STARTED
      AI_VALIDATION_SUCCESS
      AI_VALIDATION_FAILED
      AI_REQUEST_STARTED
      AI_REQUEST_SUCCESS
      AI_REQUEST_FAILED
      AI_FALLBACK_ACTIVATED
    """
    safe_details = {}
    if details:
        for k, v in details.items():
            # Filter out sensitive keys completely
            if any(s in k.lower() for s in ["key", "password", "token", "secret", "auth", "cookie"]):
                continue
            if isinstance(v, str):
                safe_details[k] = redact_sensitive_text(v)
            else:
                safe_details[k] = v

    now_utc = datetime.now(timezone.utc).isoformat()
    logger.info(f"[{now_utc}] EVENT={event_type} | DETAILS={safe_details}")
