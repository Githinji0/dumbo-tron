import numpy as np
from brain_farm.app.services.ic_calculator import ICCalculator

class WalkForwardTester:
    """
    Handles rolling out-of-sample tests by slicing history into Train/Test partitions
    and validating parameter persistence.
    """

    @staticmethod
    def evaluate_walk_forward(expr: str, overall_sharpe: float, windows_count: int = 3) -> dict:
        """
        Slices the simulated 252-day IC series into rolling train/test partitions.
        Returns a composite walk-forward score representing performance stability.
        """
        ic_series = ICCalculator.generate_daily_ic_series(expr, overall_sharpe)
        
        # Partition parameters
        total_len = len(ic_series)
        window_size = total_len // (windows_count + 1)
        
        scores = []
        
        for w in range(windows_count):
            train_end = (w + 1) * window_size
            test_end = (w + 2) * window_size
            
            train_span = ic_series[:train_end]
            test_span = ic_series[train_end:test_end]
            
            if len(train_span) == 0 or len(test_span) == 0:
                continue
                
            train_mean = np.mean(train_span)
            test_mean = np.mean(test_span)
            
            train_std = np.std(train_span)
            test_std = np.std(test_span)
            
            train_sharpe = train_mean / train_std * np.sqrt(252) if train_std > 0 else 0.0
            test_sharpe = test_mean / test_std * np.sqrt(252) if test_std > 0 else 0.0
            
            # Ratio of OOS Sharpe to IS Sharpe
            if train_sharpe > 0:
                stability = test_sharpe / train_sharpe
            else:
                stability = 0.0
                
            scores.append(stability)
            
        # Overall walk-forward score: mean stability ratio, capped between 0.0 and 1.0 (to avoid outliers)
        if scores:
            mean_score = float(np.mean(scores))
            walk_forward_score = max(0.0, min(1.0, mean_score)) if not np.isnan(mean_score) else 0.0
        else:
            walk_forward_score = 0.0
            
        return {
            "walk_forward_score": walk_forward_score
        }
