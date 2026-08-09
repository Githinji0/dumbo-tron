import numpy as np
from brain_farm.app.services.ic_calculator import ICCalculator

class RegimeAnalyzer:
    """
    Groups validation intervals into market regimes (e.g. high vs low volatility)
    and parses regime-conditional Sharpe ratios and scores.
    """

    @staticmethod
    def evaluate_regimes(expr: str, overall_sharpe: float) -> dict:
        """
        Calculates performance metrics under different simulated market volatility regimes.
        Segments 252 days of daily ICs into low-volatility and high-volatility environments.
        """
        ic_series = ICCalculator.generate_daily_ic_series(expr, overall_sharpe)
        length = len(ic_series)
        
        # Generate a deterministic synthetic market volatility index (e.g. VIX proxy)
        seed = (hash(expr) + 7) & 0xffffffff
        rng = np.random.default_rng(seed)
        vix_proxy = rng.uniform(10.0, 35.0, size=length)
        
        # Autocorrelation for regime persistence (smooth transition)
        for i in range(1, length):
            vix_proxy[i] = 0.9 * vix_proxy[i] + 0.1 * vix_proxy[i - 1]
            
        vix_median = np.median(vix_proxy)
        
        # Partition indices
        low_vol_mask = vix_proxy <= vix_median
        high_vol_mask = vix_proxy > vix_median
        
        ic_low = ic_series[low_vol_mask]
        ic_high = ic_series[high_vol_mask]
        
        # Metrics per regime
        mean_low = float(np.mean(ic_low)) if len(ic_low) > 0 else 0.0
        mean_high = float(np.mean(ic_high)) if len(ic_high) > 0 else 0.0
        
        std_low = float(np.std(ic_low)) if len(ic_low) > 0 else 1.0
        std_high = float(np.std(ic_high)) if len(ic_high) > 0 else 1.0
        
        sharpe_low = mean_low / std_low * np.sqrt(252) if std_low > 0 else 0.0
        sharpe_high = mean_high / std_high * np.sqrt(252) if std_high > 0 else 0.0
        
        # Consistency score: 1.0 - absolute difference in mean performance/Sharpe, capped/scaled
        diff = abs(sharpe_low - sharpe_high)
        regime_score = max(0.0, 1.0 - (diff / 2.0))
        
        return {
            "regime_score": regime_score,
            "sharpe_run_low": sharpe_low,
            "sharpe_run_high": sharpe_high
        }
