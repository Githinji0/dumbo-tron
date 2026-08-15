import logging
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger("brain_farm.response_auditor")

SENSITIVE_KEYS = {
    "password", "token", "auth", "authorization", "cookie", 
    "set-cookie", "api_key", "secret", "credentials", "session"
}

class ResponseStructureAuditor:
    """
    Audits and parses WorldQuant BRAIN post-simulation response structures.
    Decouples remote simulation status from metric and portfolio availability:
    - Remote Status: SUBMITTED, RUNNING, COMPLETE, ERROR, FAILED
    - Portfolio Status: PORTFOLIO_AVAILABLE, PORTFOLIO_EMPTY, NOT_APPLICABLE
    - Metrics Status: METRICS_AVAILABLE, METRICS_MISSING, METRICS_PARSE_ERROR, NOT_APPLICABLE
    - Evaluation Status: EVALUATED, TECHNICAL_FAILURE, PENDING
    """

    @classmethod
    def sanitize(cls, obj: Any) -> Any:
        """Recursively removes sensitive keys from diagnostic payloads."""
        if isinstance(obj, dict):
            clean = {}
            for k, v in obj.items():
                if any(s in str(k).lower() for s in SENSITIVE_KEYS):
                    clean[k] = "[REDACTED]"
                else:
                    clean[k] = cls.sanitize(v)
            return clean
        elif isinstance(obj, list):
            return [cls.sanitize(item) for item in obj]
        return obj

    @classmethod
    def audit(
        cls, 
        response_data: Optional[Dict[str, Any]], 
        http_status: int = 200,
        expression_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Audits the raw simulation response dictionary and extracts metrics safely.
        """
        if not response_data or not isinstance(response_data, dict):
            return {
                "http_status": http_status,
                "remote_status": "ERROR" if http_status >= 400 else "INVALID_RESPONSE",
                "portfolio_status": "NOT_APPLICABLE",
                "metrics_status": "METRICS_PARSE_ERROR",
                "evaluation_status": "TECHNICAL_FAILURE",
                "parser_path_used": "NONE",
                "has_is_block": False,
                "has_portfolio_block": False,
                "has_statistics": False,
                "has_trades": False,
                "top_level_keys": [],
                "relevant_nested_keys": {},
                "failure_reason": f"Response data is null or not a valid dictionary (HTTP {http_status}).",
                "extracted_metrics": None,
                "sanitized_response": {}
            }

        sanitized = cls.sanitize(response_data)
        top_keys = list(response_data.keys())
        nested_keys = {}
        for k, v in response_data.items():
            if isinstance(v, dict):
                nested_keys[k] = list(v.keys())

        # Determine remote status
        raw_status = response_data.get("status")
        if (not raw_status or str(raw_status).upper() in ("UNSUBMITTED", "SUBMITTED")) and "is" in response_data and response_data["is"]:
            raw_status = "COMPLETE"
        remote_status = str(raw_status or "UNKNOWN").upper().strip()

        TERMINAL_SUCCESS = {"COMPLETE", "COMPLETED", "OK", "DONE", "WARNING", "SUCCESS", "FINISHED", "UNSUBMITTED", "SUBMITTED"}
        TERMINAL_FAILURE = {"ERROR", "FAILED", "CANCELLED", "CANCELED", "FAIL"}

        if remote_status in TERMINAL_FAILURE:
            err_msg = response_data.get("message") or response_data.get("error") or f"Remote failure status: {remote_status}"
            return {
                "http_status": http_status,
                "remote_status": remote_status,
                "portfolio_status": "NOT_APPLICABLE",
                "metrics_status": "NOT_APPLICABLE",
                "evaluation_status": "TECHNICAL_FAILURE",
                "parser_path_used": "NONE",
                "has_is_block": "is" in response_data,
                "has_portfolio_block": bool(response_data.get("alpha")),
                "has_statistics": False,
                "has_trades": False,
                "top_level_keys": top_keys,
                "relevant_nested_keys": nested_keys,
                "failure_reason": str(err_msg),
                "extracted_metrics": None,
                "sanitized_response": sanitized
            }

        if remote_status not in TERMINAL_SUCCESS:
            # Still in-progress e.g. RUNNING, QUEUED, PENDING
            return {
                "http_status": http_status,
                "remote_status": remote_status,
                "portfolio_status": "PORTFOLIO_PENDING",
                "metrics_status": "NOT_APPLICABLE",
                "evaluation_status": "PENDING",
                "parser_path_used": "NONE",
                "has_is_block": False,
                "has_portfolio_block": bool(response_data.get("alpha")),
                "has_statistics": False,
                "has_trades": False,
                "top_level_keys": top_keys,
                "relevant_nested_keys": nested_keys,
                "failure_reason": None,
                "extracted_metrics": None,
                "sanitized_response": sanitized
            }

        # Remote simulation is COMPLETE -> audit potential metric locations
        # Paths to search: response["is"], response["stats"], response["performance"], response["metrics"], response["records"]
        candidate_paths = [
            ("response['is']", response_data.get("is")),
            ("response['stats']", response_data.get("stats")),
            ("response['performance']", response_data.get("performance")),
            ("response['metrics']", response_data.get("metrics")),
            ("response['records']", response_data.get("records"))
        ]

        target_dict = None
        parser_path_used = "NONE"

        for path_name, cand in candidate_paths:
            if isinstance(cand, dict) and len(cand) > 0:
                # Check if it contains core metric keys
                if any(k in cand for k in ("sharpe", "fitness", "turnover", "returns", "margin")):
                    target_dict = cand
                    parser_path_used = path_name
                    break

        # Check trades count if reported
        long_count = response_data.get("longCount") or (target_dict.get("longCount") if target_dict else None)
        short_count = response_data.get("shortCount") or (target_dict.get("shortCount") if target_dict else None)
        has_trades = bool((long_count is not None and long_count > 0) or (short_count is not None and short_count > 0))

        if not target_dict:
            # No metric dictionary found anywhere in response
            # Check why: empty IS block or zero trades
            alpha_id = response_data.get("alpha")
            reason = "WorldQuant BRAIN returned complete simulation status, but the in-sample (IS) portfolio dictionary is empty or null."
            if expression_text and ("ts_mean" in expression_text or "ts_delay" in expression_text):
                reason += " Common cause: Lookback formula evaluated to constant values across all stocks, generating 0 long/short positions and 0 trades."

            return {
                "http_status": http_status,
                "remote_status": "COMPLETE",
                "portfolio_status": "PORTFOLIO_EMPTY",
                "metrics_status": "METRICS_MISSING",
                "evaluation_status": "TECHNICAL_FAILURE",
                "parser_path_used": "NONE",
                "has_is_block": "is" in response_data and response_data["is"] is not None,
                "has_portfolio_block": bool(alpha_id),
                "has_statistics": False,
                "has_trades": has_trades,
                "top_level_keys": top_keys,
                "relevant_nested_keys": nested_keys,
                "failure_reason": reason,
                "extracted_metrics": None,
                "sanitized_response": sanitized
            }

        # Target dictionary exists -> extract and validate metrics
        # Distinguish explicit numerical 0.0 from missing (None)
        sharpe_raw = target_dict.get("sharpe")
        fitness_raw = target_dict.get("fitness")
        turnover_raw = target_dict.get("turnover")
        returns_raw = target_dict.get("returns")
        margin_raw = target_dict.get("margin")
        drawdown_raw = target_dict.get("drawdown")

        # Validate that essential metrics are present and convertable to float
        try:
            if sharpe_raw is None or fitness_raw is None or turnover_raw is None:
                missing_keys = [k for k, v in [("sharpe", sharpe_raw), ("fitness", fitness_raw), ("turnover", turnover_raw)] if v is None]
                return {
                    "http_status": http_status,
                    "remote_status": "COMPLETE",
                    "portfolio_status": "PORTFOLIO_AVAILABLE",
                    "metrics_status": "METRICS_MISSING",
                    "evaluation_status": "TECHNICAL_FAILURE",
                    "parser_path_used": parser_path_used,
                    "has_is_block": True,
                    "has_portfolio_block": bool(response_data.get("alpha")),
                    "has_statistics": True,
                    "has_trades": has_trades,
                    "top_level_keys": top_keys,
                    "relevant_nested_keys": nested_keys,
                    "failure_reason": f"Incomplete metrics block: Missing required keys {missing_keys}.",
                    "extracted_metrics": None,
                    "sanitized_response": sanitized
                }

            metrics = {
                "sharpe": float(sharpe_raw),
                "fitness": float(fitness_raw),
                "turnover": float(turnover_raw),
                "returns": float(returns_raw) if returns_raw is not None else 0.0,
                "margin": float(margin_raw) if margin_raw is not None else 0.0,
                "drawdown": float(drawdown_raw) if drawdown_raw is not None else 0.0,
                "long_count": int(long_count) if long_count is not None else None,
                "short_count": int(short_count) if short_count is not None else None,
            }

            return {
                "http_status": http_status,
                "remote_status": "COMPLETE",
                "portfolio_status": "PORTFOLIO_AVAILABLE",
                "metrics_status": "METRICS_AVAILABLE",
                "evaluation_status": "EVALUATED",
                "parser_path_used": parser_path_used,
                "has_is_block": True,
                "has_portfolio_block": bool(response_data.get("alpha")),
                "has_statistics": True,
                "has_trades": True,
                "top_level_keys": top_keys,
                "relevant_nested_keys": nested_keys,
                "failure_reason": None,
                "extracted_metrics": metrics,
                "sanitized_response": sanitized
            }

        except (ValueError, TypeError) as parse_err:
            return {
                "http_status": http_status,
                "remote_status": "COMPLETE",
                "portfolio_status": "PORTFOLIO_AVAILABLE",
                "metrics_status": "METRICS_PARSE_ERROR",
                "evaluation_status": "TECHNICAL_FAILURE",
                "parser_path_used": parser_path_used,
                "has_is_block": True,
                "has_portfolio_block": bool(response_data.get("alpha")),
                "has_statistics": False,
                "has_trades": has_trades,
                "top_level_keys": top_keys,
                "relevant_nested_keys": nested_keys,
                "failure_reason": f"Failed to parse numerical metrics from {parser_path_used}: {parse_err}",
                "extracted_metrics": None,
                "sanitized_response": sanitized
            }
