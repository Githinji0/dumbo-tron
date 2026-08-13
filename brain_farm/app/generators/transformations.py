import re
from typing import Optional

def apply_volatility_normalization(field_or_expr: str, window: int = 20) -> str:
    """
    Applies volatility normalization to a field or expression.
    Concept: field_or_expr / (ts_std_dev(field_or_expr, window) + 0.000001)
    """
    return f"({field_or_expr} / (ts_std_dev({field_or_expr}, {window}) + 0.000001))"

def apply_velocity_smoothing(field_or_expr: str, window: int = 20) -> str:
    """
    Applies velocity-deviation based smoothing.
    Concept: (field_or_expr - ts_mean(field_or_expr, window)) / (ts_std_dev(field_or_expr, window) + 0.000001)
    """
    return f"(({field_or_expr} - ts_mean({field_or_expr}, {window})) / (ts_std_dev({field_or_expr}, {window}) + 0.000001))"

def apply_linear_decay(field_or_expr: str, decay_window: int = 5) -> str:
    """
    Applies ts_decay_linear to the expression.
    Concept: ts_decay_linear(field_or_expr, decay_window)
    """
    return f"ts_decay_linear({field_or_expr}, {decay_window})"

def apply_conditional_gating(raw_signal: str, condition: str) -> str:
    """
    Applies conditional gating to raw_signal confirmation:
    Concept: (condition) * raw_signal
    Uses sign or absolute values / math operators if boolean operators are restricted.
    For example: (condition) * (raw_signal)
    """
    return f"(({condition}) * ({raw_signal}))"
