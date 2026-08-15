"""
Field and Operator Semantic Metadata Registry for Dumbo-Tron.

Provides structured semantic categorization, temporal characteristics,
reporting frequency, recommended horizons, and operator compatibility matrices.
"""
from typing import Dict, Any, List, Optional, Tuple
import logging

logger = logging.getLogger("brain_farm.field_semantics")


class FieldCategory:
    PRICE = "PRICE"
    MARKET_ACTIVITY = "MARKET_ACTIVITY"
    FUNDAMENTAL = "FUNDAMENTAL"
    ANALYST = "ANALYST"
    VALUATION = "VALUATION"
    LEVERAGE = "LEVERAGE"
    UNKNOWN = "UNKNOWN"


class TemporalBehavior:
    FAST = "FAST"              # Daily/intraday changes (e.g. close, volume, vwap)
    MEDIUM = "MEDIUM"          # Short-to-medium rolling or weekly aggregates
    SLOW = "SLOW"              # Quarterly/annual reporting items (e.g. capex, debt, ebit)
    EVENT_DRIVEN = "EVENT_DRIVEN"  # Irregular corporate events, revisions
    UNKNOWN = "UNKNOWN"


class Frequency:
    DAILY = "DAILY"
    REPORTING = "REPORTING"    # Quarterly/Annual reporting cadence
    EVENT = "EVENT"
    UNKNOWN = "UNKNOWN"


class OperatorType:
    TIME_SERIES = "TIME_SERIES"
    CROSS_SECTIONAL = "CROSS_SECTIONAL"
    GROUP_TRANSFORMATION = "GROUP_TRANSFORMATION"
    ARITHMETIC = "ARITHMETIC"
    LOGICAL = "LOGICAL"


# Source of truth metadata for known WorldQuant BRAIN dataset fields
FIELD_METADATA_REGISTRY: Dict[str, Dict[str, Any]] = {
    # Fast Market & Price Fields
    "close": {
        "category": FieldCategory.PRICE,
        "temporal_behavior": TemporalBehavior.FAST,
        "typical_frequency": Frequency.DAILY,
        "recommended_horizons": [1, 2, 5, 10, 20, 60],
        "recommended_families": ["MOMENTUM", "MEAN_REVERSION", "VOLATILITY", "TREND"],
        "description": "Daily closing price adjusted for splits and dividends"
    },
    "open": {
        "category": FieldCategory.PRICE,
        "temporal_behavior": TemporalBehavior.FAST,
        "typical_frequency": Frequency.DAILY,
        "recommended_horizons": [1, 2, 5, 10, 20, 60],
        "recommended_families": ["MOMENTUM", "MEAN_REVERSION", "INTRADAY"],
        "description": "Daily opening price"
    },
    "high": {
        "category": FieldCategory.PRICE,
        "temporal_behavior": TemporalBehavior.FAST,
        "typical_frequency": Frequency.DAILY,
        "recommended_horizons": [1, 5, 10, 20, 60],
        "recommended_families": ["VOLATILITY", "PRICE_EXTREMES", "MOMENTUM"],
        "description": "Daily highest traded price"
    },
    "low": {
        "category": FieldCategory.PRICE,
        "temporal_behavior": TemporalBehavior.FAST,
        "typical_frequency": Frequency.DAILY,
        "recommended_horizons": [1, 5, 10, 20, 60],
        "recommended_families": ["VOLATILITY", "PRICE_EXTREMES", "MOMENTUM"],
        "description": "Daily lowest traded price"
    },
    "vwap": {
        "category": FieldCategory.PRICE,
        "temporal_behavior": TemporalBehavior.FAST,
        "typical_frequency": Frequency.DAILY,
        "recommended_horizons": [1, 2, 5, 10, 20, 60],
        "recommended_families": ["MOMENTUM", "MEAN_REVERSION", "MICROSTRUCTURE", "EXECUTION"],
        "description": "Volume-weighted average price"
    },
    "volume": {
        "category": FieldCategory.MARKET_ACTIVITY,
        "temporal_behavior": TemporalBehavior.FAST,
        "typical_frequency": Frequency.DAILY,
        "recommended_horizons": [1, 5, 10, 20, 60],
        "recommended_families": ["VOLUME", "LIQUIDITY", "MOMENTUM", "MICROSTRUCTURE"],
        "description": "Daily traded share volume"
    },
    "returns": {
        "category": FieldCategory.PRICE,
        "temporal_behavior": TemporalBehavior.FAST,
        "typical_frequency": Frequency.DAILY,
        "recommended_horizons": [1, 5, 10, 20, 60],
        "recommended_families": ["MOMENTUM", "MEAN_REVERSION", "VOLATILITY"],
        "description": "Daily total return"
    },
    "turnover": {
        "category": FieldCategory.MARKET_ACTIVITY,
        "temporal_behavior": TemporalBehavior.FAST,
        "typical_frequency": Frequency.DAILY,
        "recommended_horizons": [1, 5, 10, 20, 60],
        "recommended_families": ["LIQUIDITY", "MICROSTRUCTURE", "VOLUME"],
        "description": "Daily dollar turnover"
    },

    # Slow-Moving Fundamental Fields (Quarterly Reporting)
    "capex": {
        "category": FieldCategory.FUNDAMENTAL,
        "temporal_behavior": TemporalBehavior.SLOW,
        "typical_frequency": Frequency.REPORTING,
        "recommended_horizons": [60, 120, 252],
        "recommended_families": ["VALUE", "QUALITY", "INVESTMENT"],
        "description": "Capital expenditures (quarterly reporting)"
    },
    "debt": {
        "category": FieldCategory.FUNDAMENTAL,
        "temporal_behavior": TemporalBehavior.SLOW,
        "typical_frequency": Frequency.REPORTING,
        "recommended_horizons": [60, 120, 252],
        "recommended_families": ["VALUE", "QUALITY", "LEVERAGE"],
        "description": "Total debt obligations (quarterly reporting)"
    },
    "book_value": {
        "category": FieldCategory.VALUATION,
        "temporal_behavior": TemporalBehavior.SLOW,
        "typical_frequency": Frequency.REPORTING,
        "recommended_horizons": [60, 120, 252],
        "recommended_families": ["VALUE", "FUNDAMENTAL"],
        "description": "Total book value of equity"
    },
    "ebit": {
        "category": FieldCategory.FUNDAMENTAL,
        "temporal_behavior": TemporalBehavior.SLOW,
        "typical_frequency": Frequency.REPORTING,
        "recommended_horizons": [60, 120, 252],
        "recommended_families": ["QUALITY", "PROFITABILITY", "VALUE"],
        "description": "Earnings before interest and taxes"
    },
    "fcf": {
        "category": FieldCategory.FUNDAMENTAL,
        "temporal_behavior": TemporalBehavior.SLOW,
        "typical_frequency": Frequency.REPORTING,
        "recommended_horizons": [60, 120, 252],
        "recommended_families": ["VALUE", "QUALITY", "CASH_FLOW"],
        "description": "Free cash flow"
    },
    "net_income": {
        "category": FieldCategory.FUNDAMENTAL,
        "temporal_behavior": TemporalBehavior.SLOW,
        "typical_frequency": Frequency.REPORTING,
        "recommended_horizons": [60, 120, 252],
        "recommended_families": ["QUALITY", "EARNINGS", "VALUE"],
        "description": "Net income attributable to common shareholders"
    },
    "revenue": {
        "category": FieldCategory.FUNDAMENTAL,
        "temporal_behavior": TemporalBehavior.SLOW,
        "typical_frequency": Frequency.REPORTING,
        "recommended_horizons": [60, 120, 252],
        "recommended_families": ["GROWTH", "VALUE", "QUALITY"],
        "description": "Total top-line revenue"
    },
    "assets": {
        "category": FieldCategory.FUNDAMENTAL,
        "temporal_behavior": TemporalBehavior.SLOW,
        "typical_frequency": Frequency.REPORTING,
        "recommended_horizons": [60, 120, 252],
        "recommended_families": ["QUALITY", "INVESTMENT", "SIZE"],
        "description": "Total assets"
    },
    "shares_out": {
        "category": FieldCategory.FUNDAMENTAL,
        "temporal_behavior": TemporalBehavior.SLOW,
        "typical_frequency": Frequency.REPORTING,
        "recommended_horizons": [60, 120, 252],
        "recommended_families": ["CAPITAL_STRUCTURE", "DILUTION"],
        "description": "Total shares outstanding"
    },
    "eps": {
        "category": FieldCategory.FUNDAMENTAL,
        "temporal_behavior": TemporalBehavior.SLOW,
        "typical_frequency": Frequency.REPORTING,
        "recommended_horizons": [60, 120, 252],
        "recommended_families": ["EARNINGS", "VALUE", "QUALITY"],
        "description": "Earnings per share reported"
    },

    # Analyst & Estimate Fields
    "eps_estimate": {
        "category": FieldCategory.ANALYST,
        "temporal_behavior": TemporalBehavior.EVENT_DRIVEN,
        "typical_frequency": Frequency.EVENT,
        "recommended_horizons": [20, 60, 120],
        "recommended_families": ["ANALYST_REVISIONS", "SENTIMENT", "EARNINGS_SURPRISE"],
        "description": "Consensus analyst EPS estimate"
    },
    "target_price": {
        "category": FieldCategory.ANALYST,
        "temporal_behavior": TemporalBehavior.EVENT_DRIVEN,
        "typical_frequency": Frequency.EVENT,
        "recommended_horizons": [20, 60, 120],
        "recommended_families": ["ANALYST_REVISIONS", "SENTIMENT", "VALUE"],
        "description": "Consensus target price"
    }
}


# Operator Semantic Registry
OPERATOR_METADATA_REGISTRY: Dict[str, Dict[str, Any]] = {
    # Time-series rolling operators
    "ts_mean": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 2,
        "max_recommended_lookback": 252,
        "description": "Time-series rolling average"
    },
    "ts_sum": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 2,
        "max_recommended_lookback": 252,
        "description": "Time-series rolling sum"
    },
    "ts_delta": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 1,
        "max_recommended_lookback": 252,
        "description": "Time-series difference: x - ts_delay(x, d)"
    },
    "ts_delay": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 1,
        "max_recommended_lookback": 252,
        "description": "Time-series lag"
    },
    "ts_rank": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 5,
        "max_recommended_lookback": 252,
        "description": "Time-series percentile rank over lookback window"
    },
    "ts_zscore": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 5,
        "max_recommended_lookback": 252,
        "description": "Time-series normalized score: (x - ts_mean) / ts_std_dev"
    },
    "ts_std_dev": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 5,
        "max_recommended_lookback": 252,
        "description": "Time-series rolling standard deviation"
    },
    "ts_decay_linear": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 2,
        "max_recommended_lookback": 252,
        "description": "Linear weighted moving average decay"
    },
    "ts_corr": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 10,
        "max_recommended_lookback": 252,
        "description": "Time-series rolling correlation between two fields"
    },
    "ts_covariance": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 10,
        "max_recommended_lookback": 252,
        "description": "Time-series rolling covariance"
    },
    "ts_max": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 2,
        "max_recommended_lookback": 252,
        "description": "Time-series rolling maximum"
    },
    "ts_min": {
        "type": OperatorType.TIME_SERIES,
        "requires_temporal_variation": True,
        "lookback_sensitive": True,
        "min_recommended_lookback_slow": 60,
        "min_recommended_lookback_fast": 2,
        "max_recommended_lookback": 252,
        "description": "Time-series rolling minimum"
    },

    # Cross-sectional operators
    "rank": {
        "type": OperatorType.CROSS_SECTIONAL,
        "requires_cross_sectional_variation": True,
        "description": "Cross-sectional percentile ranking across current universe [0, 1]"
    },
    "scale": {
        "type": OperatorType.CROSS_SECTIONAL,
        "requires_cross_sectional_variation": True,
        "description": "Cross-sectional scaling to sum of absolute weights = 1"
    },
    "quantile": {
        "type": OperatorType.CROSS_SECTIONAL,
        "requires_cross_sectional_variation": True,
        "description": "Cross-sectional bucket quantile assignment"
    },
    "winsorize": {
        "type": OperatorType.CROSS_SECTIONAL,
        "requires_cross_sectional_variation": True,
        "description": "Cross-sectional outlier capping"
    },

    # Group transformation operators
    "group_neutralize": {
        "type": OperatorType.GROUP_TRANSFORMATION,
        "requires_cross_sectional_variation": True,
        "description": "Demean alpha signal within specified grouping (e.g., subindustry, sector)"
    },
    "group_rank": {
        "type": OperatorType.GROUP_TRANSFORMATION,
        "requires_cross_sectional_variation": True,
        "description": "Cross-sectional rank within specified group"
    },
    "group_zscore": {
        "type": OperatorType.GROUP_TRANSFORMATION,
        "requires_cross_sectional_variation": True,
        "description": "Group-wise standardized z-score"
    },
    "group_mean": {
        "type": OperatorType.GROUP_TRANSFORMATION,
        "requires_cross_sectional_variation": True,
        "description": "Group-wise cross-sectional mean"
    }
}


class FieldSemantics:
    """Helper service to inspect field and operator semantics."""

    @staticmethod
    def get_field_info(field_name: str) -> Dict[str, Any]:
        """Returns metadata for a field or safe defaults for unknown fields."""
        norm_name = field_name.strip().lower()
        if norm_name in FIELD_METADATA_REGISTRY:
            return FIELD_METADATA_REGISTRY[norm_name]
        return {
            "category": FieldCategory.UNKNOWN,
            "temporal_behavior": TemporalBehavior.UNKNOWN,
            "typical_frequency": Frequency.UNKNOWN,
            "recommended_horizons": [5, 10, 20, 60],
            "recommended_families": ["MOMENTUM", "VALUE"],
            "description": "Dynamic or user-provided catalog field"
        }

    @staticmethod
    def get_operator_info(op_name: str) -> Dict[str, Any]:
        """Returns metadata for an operator."""
        norm_op = op_name.strip().lower()
        if norm_op in OPERATOR_METADATA_REGISTRY:
            return OPERATOR_METADATA_REGISTRY[norm_op]
        return {
            "type": OperatorType.ARITHMETIC,
            "requires_temporal_variation": False,
            "requires_cross_sectional_variation": False,
            "description": "Standard arithmetic or mathematical operator"
        }

    @classmethod
    def evaluate_compatibility(
        cls,
        fields: List[str],
        operators: List[str],
        lookbacks: List[int],
        family: Optional[str] = None
    ) -> Tuple[float, List[str]]:
        """
        Evaluates the semantic compatibility score (0.0 to 1.0) and lists any warnings.
        """
        score = 1.0
        warnings = []

        if not fields:
            return 0.0, ["No valid dataset fields identified in expression."]

        field_infos = [cls.get_field_info(f) for f in fields]
        slow_fields = [f for f, info in zip(fields, field_infos) if info["temporal_behavior"] == TemporalBehavior.SLOW]
        fast_fields = [f for f, info in zip(fields, field_infos) if info["temporal_behavior"] == TemporalBehavior.FAST]

        # Check 1: Time-series operators applied to slow-moving fundamental fields with short lookbacks
        ts_ops = [op for op in operators if cls.get_operator_info(op).get("type") == OperatorType.TIME_SERIES]
        if slow_fields and ts_ops:
            min_lookback = min(lookbacks) if lookbacks else 0
            if min_lookback < 20:
                score -= 0.50
                warnings.append(
                    f"Slow-moving fundamental field(s) {slow_fields} combined with time-series operator(s) {ts_ops} "
                    f"using short lookback window ({min_lookback} < 20d). High risk of zero variation and empty portfolio."
                )
            elif min_lookback < 60:
                score -= 0.20
                warnings.append(
                    f"Fundamental field(s) {slow_fields} with intermediate lookback ({min_lookback}d). "
                    f"Consider lookback >= 60d or quarterly delta."
                )

        # Check 2: Short rolling lookback ratios on identical slow fields: e.g. ts_mean(capex, 10) / ts_mean(capex, 30) - 1
        if len(slow_fields) >= 1 and len(lookbacks) >= 2:
            if all(lb < 40 for lb in lookbacks):
                score -= 0.35
                warnings.append(
                    f"Rolling ratio between short lookbacks {lookbacks} on slow fundamental field {slow_fields} "
                    f"evaluates to constant 0.0 on daily bars due to quarterly reporting cadence."
                )

        # Check 3: Family affinity check
        if family:
            fam_upper = family.upper()
            for f, info in zip(fields, field_infos):
                rec_families = info.get("recommended_families", [])
                if rec_families and fam_upper not in rec_families:
                    score -= 0.05

        # Check 4: Cross-sectional operators check
        has_cs_or_group = any(cls.get_operator_info(op).get("type") in (OperatorType.CROSS_SECTIONAL, OperatorType.GROUP_TRANSFORMATION) for op in operators)
        if not has_cs_or_group and len(fields) == 1:
            score -= 0.15
            warnings.append("Expression lacks cross-sectional ranking (rank/scale/group_neutralize).")

        return max(0.0, min(1.0, float(score))), warnings
