import re
import numpy as np
import logging
from typing import List, Set

logger = logging.getLogger("brain_farm.correlation_filter")

class CorrelationFilter:
    """
    Combines Jaccard structural text distance and synthetic signal Pearson correlation
    to prune redundant alpha formulas prior to simulation submission.
    """

    @staticmethod
    def calculate_ast_similarity(expr1: str, expr2: str) -> float:
        """
        Computes a simple Jaccard index based on string word tokens.
        Useful for quick syntactic overlaps.
        """
        tokens1: Set[str] = set(re.findall(r"\b\w+\b", expr1.lower()))
        tokens2: Set[str] = set(re.findall(r"\b\w+\b", expr2.lower()))
        
        if not tokens1 or not tokens2:
            return 0.0
            
        intersection = tokens1.intersection(tokens2)
        union = tokens1.union(tokens2)
        return len(intersection) / len(union)

    @staticmethod
    def generate_synthetic_signal(expr: str, length: int = 250) -> np.ndarray:
        """
        Generates a deterministic synthetic time-series of signal daily outputs.
        Ensures identical expressions yield identical signal paths.
        """
        # Generate stable mock seed from expression string
        # Mask to 32-bit unsigned int to satisfy numpy seed generator
        seed = hash(expr) & 0xffffffff
        rng = np.random.default_rng(seed)
        
        # Base signal: Mean-reverting random process (Ar(1) like structure)
        signal = np.zeros(length)
        val = 0.0
        for i in range(length):
            val = 0.95 * val + rng.normal(0, 0.1)
            signal[i] = val
            
        # Parse modifiers to differentiate mathematical shapes
        expr_clean = expr.lower()
        if "rank" in expr_clean:
            # Ranks scale signals
            signal = np.tanh(signal)
        if "ts_decay_linear" in expr_clean:
            # Linear decay applies smoothing convolver
            window = 5
            kernel = np.arange(1, window + 1) / np.sum(np.arange(1, window + 1))
            signal = np.convolve(signal, kernel, mode="same")
        if "group_neutralize" in expr_clean:
            # Demean to reflect cross-sectional neutrality
            signal = signal - np.mean(signal)
            
        return signal

    @classmethod
    def calculate_correlation(cls, expr1: str, expr2: str) -> float:
        """
        Computes a Pearson correlation coefficient on synthetic signals generated from two expressions.
        """
        try:
            s1 = cls.generate_synthetic_signal(expr1)
            s2 = cls.generate_synthetic_signal(expr2)
            
            std1 = np.std(s1)
            std2 = np.std(s2)
            if std1 == 0.0 or std2 == 0.0:
                return 0.0
                
            corr_mat = np.corrcoef(s1, s2)
            corr = float(corr_mat[0, 1])
            return corr if not np.isnan(corr) else 0.0
        except Exception as e:
            logger.error(f"Error calculating correlation between '{expr1}' and '{expr2}': {e}")
            return 0.0
