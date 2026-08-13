import re
from typing import List, Dict, Any
from brain_farm.app.evaluators.validator import ALLOWED_OPERATORS

def analyze_expression(expr: str, allowed_fields: List[str]) -> Dict[str, Any]:
    """
    Parses a FastExpr expression string to extract:
    - expression_depth (nesting level)
    - operator_count
    - field_count
    - complexity_score
    - list of operators
    - list of fields
    - parameters (window arguments)
    """
    if not expr:
        return {
            "expression_depth": 0,
            "operator_count": 0,
            "field_count": 0,
            "complexity_score": 0.0,
            "operators": [],
            "fields": [],
            "parameters": {}
        }

    # 1. Depth calculation
    current_depth = 0
    max_depth = 0
    for char in expr:
        if char == "(":
            current_depth += 1
            if current_depth > max_depth:
                max_depth = current_depth
        elif char == ")":
            current_depth = max_depth if current_depth <= 0 else current_depth - 1
            
    # 2. Extract tokens
    tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expr)
    
    found_ops = []
    found_fields = []
    
    for t in tokens:
        if t in ALLOWED_OPERATORS:
            found_ops.append(t)
        elif t in allowed_fields:
            found_fields.append(t)
            
    # 3. Parameters search (integers which are lookback windows, e.g. operators taking window sizes)
    # Find numbers that stand as separate arguments within parentheses
    window_args = []
    # Match numbers inside parentheses
    matches = re.findall(r"\(\s*([^()]+)\s*\)", expr)
    for m in matches:
        args = [arg.strip() for arg in m.split(",")]
        for arg in args:
            if arg.isdigit():
                window_args.append(int(arg))
                
    parameters = {}
    if len(window_args) == 1:
        parameters["window"] = window_args[0]
    elif len(window_args) > 1:
        for idx, w in enumerate(window_args):
            parameters[f"window{idx+1}"] = w
            
    op_count = len(found_ops)
    field_count = len(found_fields)
    
    # 4. Complexity score calculation
    # Formula: depth * 1.5 + operator_count * 1.0 + field_count * 0.5
    complexity = max_depth * 1.5 + op_count * 1.0 + field_count * 0.5
    
    return {
        "expression_depth": max_depth,
        "operator_count": op_count,
        "field_count": field_count,
        "complexity_score": round(max(1.0, complexity), 2),
        "operators": sorted(list(set(found_ops))),
        "fields": sorted(list(set(found_fields))),
        "parameters": parameters
    }
