from typing import Dict, Any, List

RESEARCH_FAMILIES: Dict[str, Dict[str, Any]] = {
    "MOMENTUM": {
        "description": "Asset prices tend to persist in their recent direction; buy winners and sell losers.",
        "allowed_fields": ["close", "open", "vwap", "volume"],
        "preferred_operators": ["ts_decay_linear", "ts_delta", "rank", "group_neutralize"],
        "incompatible_operators": ["abs", "log"],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.05, 0.40),
        "templates": [
            "ts_decay_linear(rank(ts_delta({field}, {window})), {window})",
            "group_neutralize(ts_decay_linear(rank({field}) / rank(ts_mean({field}, {window})), {window}), subindustry)",
            "ts_delta(ts_decay_linear(rank({field}), {window1}), {window2})"
        ]
    },
    "REVERSAL": {
        "description": "Short-term extreme price moves overreact and tend to mean-revert.",
        "allowed_fields": ["close", "open", "vwap", "volume"],
        "preferred_operators": ["ts_zscore", "ts_rank", "rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.40, 0.90),
        "templates": [
            "-ts_rank({field}, {window})",
            "group_neutralize(-ts_zscore({field}, {window}), industry)",
            "-rank(ts_zscore({field}, {window1})) * ts_decay_linear(volume, {window2})"
        ]
    },
    "VALUE": {
        "description": "Undervalued securities (low price relative to fundamentals/book/earnings) outperform.",
        "allowed_fields": ["close", "book_value", "ebit", "sales", "revenue", "eps_estimate"],
        "preferred_operators": ["rank", "group_neutralize", "log"],
        "incompatible_operators": ["ts_delta", "ts_zscore"],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.01, 0.15),
        "templates": [
            "group_neutralize(rank({fundamental}) / rank(close), subindustry)",
            "group_neutralize(rank(log({fundamental}) - log(close)), subindustry)",
            "rank({fundamental}) / rank(close)"
        ]
    },
    "QUALITY": {
        "description": "High quality companies (high profitability, low leverage, strong margins) outperform.",
        "allowed_fields": ["net_income", "total_assets", "debt", "ebit", "sales"],
        "preferred_operators": ["rank", "group_neutralize"],
        "incompatible_operators": ["ts_delta"],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.01, 0.10),
        "templates": [
            "group_neutralize(rank(net_income) / rank(total_assets), subindustry)",
            "group_neutralize(rank(ebit) / rank(sales), industry)",
            "rank(net_income) - rank(debt)"
        ]
    },
    "EARNINGS": {
        "description": "Higher fundamental earnings and earnings yield lead to positive excess returns.",
        "allowed_fields": ["ebit", "net_income", "eps_estimate", "close"],
        "preferred_operators": ["rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.05, 0.20),
        "templates": [
            "group_neutralize(rank(ebit) / rank(close), subindustry)",
            "rank(eps_estimate) / rank(close)"
        ]
    },
    "ANALYST_ESTIMATE": {
        "description": "Analyst sentiment, revision patterns, and forward expectations contain directional information.",
        "allowed_fields": ["eps_estimate", "close", "volume"],
        "preferred_operators": ["ts_delta", "ts_mean", "rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "INDUSTRY",
        "turnover_range": (0.05, 0.30),
        "templates": [
            "group_neutralize(ts_delta(eps_estimate, {window}), industry)",
            "ts_decay_linear(rank(ts_delta(eps_estimate, {window1})), {window2})"
        ]
    },
    "VOLATILITY": {
        "description": "The low-volatility anomaly; high realized historical volatility is penalized.",
        "allowed_fields": ["close", "open", "vwap"],
        "preferred_operators": ["ts_std_dev", "ts_zscore", "rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.10, 0.40),
        "templates": [
            "-rank(ts_std_dev({field}, {window}))",
            "group_neutralize(-rank(ts_std_dev({field}, {window})), subindustry)"
        ]
    },
    "LIQUIDITY": {
        "description": "Asset turnover or low liquidity requires a premium; high volume/liquidity is a proxy.",
        "allowed_fields": ["volume", "close", "vwap"],
        "preferred_operators": ["ts_mean", "rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.10, 0.45),
        "templates": [
            "-rank(ts_mean(volume, {window}) / close)",
            "group_neutralize(rank(volume) / rank(ts_mean(volume, {window})), subindustry)"
        ]
    },
    "PRICE_VOLUME": {
        "description": "Interactions of price and volume, e.g. volume confirmation or cash flows.",
        "allowed_fields": ["close", "volume", "vwap"],
        "preferred_operators": ["ts_corr", "ts_covariance", "product", "rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.15, 0.60),
        "templates": [
            "ts_corr({field1}, {field2}, {window})",
            "group_neutralize(ts_corr(close, volume, {window}), subindustry)",
            "ts_covariance(rank(close), rank(volume), {window})"
        ]
    },
    "GROWTH": {
        "description": "Year-over-year or quarterly expansion of sales, income, and assets.",
        "allowed_fields": ["revenue", "net_income", "sales", "total_assets"],
        "preferred_operators": ["ts_delta", "rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.01, 0.15),
        "templates": [
            "group_neutralize(rank(ts_delta(revenue, 20)), subindustry)",
            "rank(ts_delta(net_income, 60)) / rank(total_assets)"
        ]
    },
    "CASH_FLOW": {
        "description": "Free cash flow indicators show real earnings quality.",
        "allowed_fields": ["fcf", "close", "total_assets"],
        "preferred_operators": ["rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.01, 0.12),
        "templates": [
            "group_neutralize(rank(fcf) / rank(close), subindustry)",
            "rank(fcf) / rank(total_assets)"
        ]
    },
    "BALANCE_SHEET": {
        "description": "Capital structure indicators, e.g. leverage ratios and cash cushions.",
        "allowed_fields": ["debt", "total_assets", "cash"],
        "preferred_operators": ["rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.01, 0.10),
        "templates": [
            "group_neutralize(rank(cash) - rank(debt), subindustry)",
            "rank(debt) / rank(total_assets)"
        ]
    },
    "SENTIMENT": {
        "description": "Sentiment proxy models using trading behavior or news metrics.",
        "allowed_fields": ["close", "volume", "vwap"],
        "preferred_operators": ["ts_zscore", "rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.20, 0.70),
        "templates": [
            "group_neutralize(ts_zscore(close, {window}), subindustry)",
            "-rank(ts_zscore(volume, {window}))"
        ]
    },
    "INSIDER": {
        "description": "Insider buying patterns or share buybacks (approximated via shares outstanding changes).",
        "allowed_fields": ["shares_out", "close"],
        "preferred_operators": ["ts_delta", "rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.01, 0.15),
        "templates": [
            "-rank(ts_delta(shares_out, {window}))",
            "group_neutralize(-ts_delta(shares_out, {window}), subindustry)"
        ]
    },
    "SHORT_INTEREST": {
        "description": "High short interest signals potential short squeezes or overvalued sentiment.",
        "allowed_fields": ["volume", "shares_out", "close"],
        "preferred_operators": ["ts_mean", "rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.05, 0.25),
        "templates": [
            "group_neutralize(rank(volume) / rank(shares_out), subindustry)"
        ]
    },
    "OPTIONS": {
        "description": "Option activity indicators (implied volatility mock proxies).",
        "allowed_fields": ["close", "volume", "vwap"],
        "preferred_operators": ["ts_std_dev", "ts_zscore", "rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.15, 0.50),
        "templates": [
            "group_neutralize(ts_std_dev(close, {window1}) / ts_mean(volume, {window2}), subindustry)"
        ]
    },
    "MULTI_FACTOR": {
        "description": "Combinations of Momentum and Value to construct high quality models.",
        "allowed_fields": ["close", "book_value", "ebit", "sales", "volume"],
        "preferred_operators": ["rank", "group_neutralize"],
        "incompatible_operators": [],
        "neutralization": "SUBINDUSTRY",
        "turnover_range": (0.02, 0.20),
        "templates": [
            "group_neutralize(rank(close) + rank(ebit) / rank(sales), subindustry)",
            "group_neutralize(rank(ts_decay_linear(rank(close), {window})) + rank(ebit) / rank(close), subindustry)"
        ]
    }
}
