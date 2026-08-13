import pytest
import asyncio
from unittest.mock import MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from brain_farm.app.generators.transformations import (
    apply_volatility_normalization,
    apply_velocity_smoothing,
    apply_linear_decay,
    apply_conditional_gating
)
from brain_farm.app.evaluators.pre_screen import StatisticalPreScreen
from brain_farm.app.services.worker import SimulationWorker
from brain_farm.app.database.models import Metric, Simulation, Expression

def test_volatility_normalization():
    res = apply_volatility_normalization("close", 20)
    assert res == "(close / (ts_std_dev(close, 20) + 0.000001))"

def test_velocity_smoothing():
    res = apply_velocity_smoothing("close", 20)
    assert res == "((close - ts_mean(close, 20)) / (ts_std_dev(close, 20) + 0.000001))"

def test_linear_decay():
    res = apply_linear_decay("close", 5)
    assert res == "ts_decay_linear(close, 5)"

def test_conditional_gating():
    res = apply_conditional_gating("close", "open > close")
    assert res == "((open > close) * (close))"

def test_statistical_pre_screen():
    allowed_fields = ["close", "open", "volume", "vwap"]
    # Check valid
    ok, reason = StatisticalPreScreen.pre_screen("rank(close)", allowed_fields)
    assert ok is True
    # Check invalid field
    ok, reason = StatisticalPreScreen.pre_screen("rank(unknown)", allowed_fields)
    assert ok is False
    assert "FormulaValidator failed" in reason
    # Trivial expression check
    ok, reason = StatisticalPreScreen.pre_screen("close - close", allowed_fields)
    assert ok is False
    assert "trivial" in reason
    # Nested neutralizing check
    ok, reason = StatisticalPreScreen.pre_screen("group_neutralize(group_neutralize(open))", allowed_fields)
    assert ok is False
    assert "neutralize" in reason

@pytest.mark.asyncio
async def test_recalculate_pareto_frontier():
    # Setup list of mock models mimicking database select results
    m1 = Metric(sharpe=1.5, fitness=1.2, turnover=0.3)
    e1 = Expression()
    
    m2 = Metric(sharpe=1.8, fitness=1.5, turnover=0.2) # Dominates m1
    e2 = Expression()
    
    m3 = Metric(sharpe=1.6, fitness=1.3, turnover=0.4) # Not dominated by m2, but doesn't dominate m2
    e3 = Expression()
    
    class MockRow:
        def __init__(self, e, m):
            self.Expression = e
            self.Metric = m
        def __iter__(self):
            return iter((self.Expression, self.Metric))

    mock_db = MagicMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.all.return_value = [MockRow(e1, m1), MockRow(e2, m2), MockRow(e3, m3)]
    mock_db.execute.return_value = mock_result

    worker = SimulationWorker(concurrency_limit=1)
    await worker._recalculate_pareto_frontier(project_id=1, db=mock_db)

    # m2 is Pareto-optimal
    assert m2.pareto_optimal is True
    # m1 is dominated by m2
    assert m1.pareto_optimal is False
    # m3 is dominated by m2
    assert m3.pareto_optimal is False
