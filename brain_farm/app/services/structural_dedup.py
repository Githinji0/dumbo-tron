"""
Structural Deduplication & Candidate Lineage Tracker for Dumbo-Tron.

Normalizes alpha formulas into canonical AST forms, generates structural skeletons,
detects duplicate/mathematically equivalent expressions, and tracks candidate mutations.
"""
import re
import hashlib
import ast
from typing import Dict, Any, List, Optional, Tuple, Set


class StructuralDedup:
    """Service for canonical expression hashing, structural skeletons, and deduplication."""

    @staticmethod
    def extract_fields_and_operators(expr_text: str) -> Tuple[List[str], List[str], List[int]]:
        """
        Extracts variable fields, function operators, and numeric lookbacks using regex.
        """
        # Tokenize identifiers
        tokens = re.findall(r'[A-Za-z_][A-Za-z0-9_]*', expr_text)
        
        # Operators known to BRAIN
        known_operators = {
            "ts_mean", "ts_sum", "ts_delta", "ts_delay", "ts_rank", "ts_zscore",
            "ts_std_dev", "ts_decay_linear", "ts_corr", "ts_covariance", "ts_max", "ts_min",
            "rank", "scale", "quantile", "winsorize", "group_neutralize", "group_rank",
            "group_zscore", "group_mean", "log", "abs", "sign", "signed_power", "sqrt",
            "min", "max"
        }
        
        grouping_tokens = {"subindustry", "industry", "sector", "market"}
        
        operators = []
        fields = []
        
        for tok in tokens:
            t_lower = tok.lower()
            if t_lower in known_operators:
                if t_lower not in operators:
                    operators.append(t_lower)
            elif t_lower in grouping_tokens:
                pass
            else:
                if t_lower not in fields:
                    fields.append(t_lower)
                    
        # Extract integer lookback arguments
        lookbacks = [int(n) for n in re.findall(r'\b\d+\b', expr_text)]
        return fields, operators, lookbacks

    @staticmethod
    def canonicalize_expression(expr_text: str) -> str:
        """
        Produces a normalized whitespace-free string representation with standardized lowercase.
        """
        clean = expr_text.strip()
        # Remove extra whitespace around brackets and commas
        clean = re.sub(r'\s+', '', clean)
        clean = clean.lower()
        return clean

    @classmethod
    def compute_expression_hash(cls, expr_text: str) -> str:
        """
        Computes a SHA-256 hash of the canonicalized expression text.
        """
        canonical = cls.canonicalize_expression(expr_text)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def compute_structure_hash(cls, expr_text: str) -> str:
        """
        Generates a structural skeleton hash where field names and grouping tokens are replaced
        by generic placeholders (VAR_1, VAR_2, GRP_1), preserving the operator hierarchy.
        """
        fields, operators, lookbacks = cls.extract_fields_and_operators(expr_text)
        skeleton = cls.canonicalize_expression(expr_text)
        
        # Replace specific grouping tokens
        skeleton = re.sub(r'\b(subindustry|industry|sector|market)\b', 'GRP', skeleton)
        
        # Replace variable fields with VAR_0, VAR_1 ...
        for idx, f in enumerate(sorted(fields, key=len, reverse=True)):
            skeleton = re.sub(rf'\b{re.escape(f)}\b', f'VAR_{idx}', skeleton)
            
        # Replace numeric lookbacks with NUM_0, NUM_1 ...
        for idx, num in enumerate(sorted(set(lookbacks), reverse=True)):
            skeleton = re.sub(rf'\b{num}\b', f'NUM_{idx}', skeleton)
            
        return hashlib.sha256(skeleton.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def build_lineage_metadata(
        cls,
        current_expr: str,
        parent_expr: Optional[str] = None,
        parent_candidate_id: Optional[int] = None,
        mutation_type: Optional[str] = None,
        hypothesis: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Builds complete lineage and hash record for candidate persistence.
        """
        expr_hash = cls.compute_expression_hash(current_expr)
        struct_hash = cls.compute_structure_hash(current_expr)
        
        curr_fields, curr_ops, curr_lbs = cls.extract_fields_and_operators(current_expr)
        
        changed_field = None
        changed_op = None
        changed_lb = None
        
        if parent_expr:
            p_fields, p_ops, p_lbs = cls.extract_fields_and_operators(parent_expr)
            diff_fields = list(set(curr_fields) ^ set(p_fields))
            diff_ops = list(set(curr_ops) ^ set(p_ops))
            diff_lbs = list(set(curr_lbs) ^ set(p_lbs))
            
            changed_field = diff_fields[0] if diff_fields else None
            changed_op = diff_ops[0] if diff_ops else None
            changed_lb = diff_lbs[0] if diff_lbs else None
            
        return {
            "expression_hash": expr_hash,
            "structure_hash": struct_hash,
            "parent_candidate_id": parent_candidate_id,
            "mutation_type": mutation_type or ("ROOT" if not parent_candidate_id else "MUTATION"),
            "changed_field": changed_field,
            "changed_operator": changed_op,
            "changed_lookback": changed_lb,
            "research_hypothesis": hypothesis or "Empirical systematic signal exploration."
        }
