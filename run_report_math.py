import asyncio
import numpy as np
from brain_farm.app.services.ic_calculator import ICCalculator
from brain_farm.app.services.regime_analyzer import RegimeAnalyzer
from brain_farm.app.services.walk_forward import WalkForwardTester
from brain_farm.app.services.sensitivity import ParameterSensitivityTester
from brain_farm.app.services.composite_scorer import WeightedCompositeScorer
from brain_farm.app.services.correlation_filter import CorrelationFilter

def test_math():
    expr = "ts_zscore(close, 10)"
    sharpe = 1.8
    fitness = 1.5
    complexity = 4.0
    
    # 1. IC Metrics
    ic_metrics = ICCalculator.calculate_ic_metrics(expr, sharpe)
    print("--- IC METRICS ---")
    for k, v in ic_metrics.items():
        print(f"{k}: {v:.6f}")
        
    # 2. Regime Analysis
    regime_metrics = RegimeAnalyzer.evaluate_regimes(expr, sharpe)
    print("\n--- REGIME METRICS ---")
    for k, v in regime_metrics.items():
        print(f"{k}: {v:.6f}")
        
    # 3. Walk Forward
    wf_metrics = WalkForwardTester.evaluate_walk_forward(expr, sharpe)
    print("\n--- WALK FORWARD METRICS ---")
    for k, v in wf_metrics.items():
        print(f"{k}: {v:.6f}")
        
    # 4. Lookbacks & Perturbation
    lookbacks = ParameterSensitivityTester.extract_lookbacks(expr)
    print("\n--- LOOKBACKS ---")
    print(lookbacks)
    
    perturbed = ParameterSensitivityTester.generate_perturbed_expressions(expr)
    print("\n--- PERTURBED EXPRESSIONS ---")
    print(perturbed)
    
    # Correlation between original and perturbed
    correlations = []
    print("\n--- PERTURBED CORRELATIONS ---")
    for p in perturbed:
        corr = CorrelationFilter.calculate_correlation(expr, p)
        correlations.append(corr)
        print(f"Corr to '{p}': {corr:.6f}")
        
    penalty = ParameterSensitivityTester.evaluate_sensitivity_penalty(expr, sharpe)
    print(f"Sensitivity Penalty Factor: {penalty:.6f}")
    
    # 5. Composite Score Steps
    research = WeightedCompositeScorer.calculate_research_score(sharpe, fitness)
    # Robustness (wf + regime) / 2
    raw_robustness = (wf_metrics["walk_forward_score"] + regime_metrics["regime_score"]) / 2.0
    robustness_with_penalty = raw_robustness * penalty
    
    # Diversity (we assume 1.0 here for mock, i.e., no other passed alphas)
    diversity = 1.0
    simplicity = WeightedCompositeScorer.calculate_simplicity_score(complexity)
    
    composite = (
        0.40 * research +
        0.25 * robustness_with_penalty +
        0.20 * diversity +
        0.15 * simplicity
    )
    
    print("\n--- COMPOSITE SCORE BREAKDOWN ---")
    print(f"Research Score: {research:.6f}")
    print(f"Raw Robustness Score: {raw_robustness:.6f}")
    print(f"Robustness Score (w/ Penalty): {robustness_with_penalty:.6f}")
    print(f"Diversity Score (assuming no other alphas): {diversity:.6f}")
    print(f"Simplicity Score (complexity={complexity}): {simplicity:.6f}")
    print(f"Composite Score: {composite:.6f}")

if __name__ == "__main__":
    test_math()
