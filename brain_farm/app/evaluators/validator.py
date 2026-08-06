import re
from typing import Tuple, List

# List of allowed quant operators in BRAIN platform
ALLOWED_OPERATORS = {
    "rank", "group_neutralize", "ts_zscore", "ts_decay_linear", "ts_delta", 
    "ts_mean", "ts_std_dev", "ts_rank", "ts_corr", "ts_covariance",
    "abs", "log", "sign", "signed_power", "min", "max", "sum", "product"
}

class FormulaValidator:
    """Validates FastExpr alpha expression syntax and semantics before API submission."""

    @staticmethod
    def validate_parentheses(expr: str) -> bool:
        """Verifies balanced open and close parentheses."""
        stack = []
        for char in expr:
            if char == "(":
                stack.append(char)
            elif char == ")":
                if not stack:
                    return False
                stack.pop()
        return len(stack) == 0

    @staticmethod
    def validate(expr: str, allowed_fields: List[str]) -> Tuple[bool, str]:
        """Runs syntax checks on expression string. Returns (is_valid, reason)."""
        if not expr or not expr.strip():
            return False, "Expression is empty."

        # 1. Balanced brackets check
        if not FormulaValidator.validate_parentheses(expr):
            return False, "Mismatched parentheses."

        # 2. Syntax sanitization: Prevent arbitrary python execution (security)
        forbidden_keywords = ["import", "sys", "os", "lambda", "eval", "exec", "class", "def", "getattr", "subprocess"]
        for kw in forbidden_keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", expr):
                return False, f"Forbidden keyword '{kw}' detected. Security violation."

        # 3. Operators and tokens validation
        # Find all alpha tokens matching word structures [a-zA-Z_0-9]+
        tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr)
        
        # Verify that all alphabetic tokens are either known operators, known fields, or keywords like subindustry/industry/sector
        reserved_params = {"subindustry", "industry", "sector", "none", "SUBINDUSTRY", "INDUSTRY", "SECTOR", "NONE"}
        
        for token in tokens:
            # Check if token is numeric (skip)
            if token.isdigit():
                continue
            
            # Check if token is in allowed operators, fields, or parameters
            if (token not in ALLOWED_OPERATORS and 
                token not in allowed_fields and 
                token not in reserved_params):
                # We also allow standard math variables or arguments inside brackets
                return False, f"Unknown field or operator '{token}'."

        # 4. Check for nested neutralizing structures
        # Neutralization is expensive and WQ BRAIN does not allow nested neutralization
        neut_matches = re.findall(r"\bgroup_neutralize\b", expr)
        if len(neut_matches) > 1:
            # Wait, multiple neutralizations are not allowed unless they are side-by-side (which is rare).
            # But nested group_neutralize(group_neutralize(...)) is definitely invalid.
            # Simple containment check:
            if re.search(r"group_neutralize\s*\(.*group_neutralize", expr):
                return False, "Nested 'group_neutralize' operators are not permitted."

        # 5. Lookback window sizes validation
        # Find all operators taking lookback window params, like ts_operators and check if the digits are valid positive numbers.
        # Operators like: ts_decay_linear(rank(close), 10)
        # Regex to find window arguments: e.g. operator_name(..., \s*\d+\s*) or ts_xx(..., window)
        window_operators = ["ts_zscore", "ts_decay_linear", "ts_delta", "ts_mean", "ts_std_dev", "ts_rank", "ts_corr", "ts_covariance"]
        for op in window_operators:
            pattern = re.escape(op) + r"\s*\(([^)]+)\)"
            for match in re.finditer(pattern, expr):
                args_str = match.group(1)
                # Split by commas that are outside parentheses
                args = []
                current_arg = []
                paren_level = 0
                for char in args_str:
                    if char == "(":
                        paren_level += 1
                    elif char == ")":
                        paren_level -= 1
                    if char == "," and paren_level == 0:
                        args.append("".join(current_arg).strip())
                        current_arg = []
                    else:
                        current_arg.append(char)
                args.append("".join(current_arg).strip())
                
                # Window is typically the last argument
                if len(args) >= 2:
                    last_arg = args[-1]
                    if last_arg.isdigit():
                        window_val = int(last_arg)
                        if window_val <= 1 or window_val > 500:
                            return False, f"Lookback window '{window_val}' for operator '{op}' is out of range (must be > 1 and <= 500)."
                    elif not last_arg.replace(".", "", 1).isdigit():
                        # If window is not a literal number (perhaps another operator?), skip check or warn
                        pass

        return True, "Validation successful."
