"""
Unit tests for Field and Operator Empirical Memory tracking.
"""
import pytest
from brain_farm.app.database.session import make_session_factory, init_db
from brain_farm.app.ai.research_memory import ResearchMemoryManager


@pytest.mark.asyncio
async def test_field_and_operator_memory_recording():
    await init_db()
    factory = make_session_factory()
    async with factory() as db:
        # Record valid simulation for vwap
        await ResearchMemoryManager.record_field_outcome(
            db=db,
            field_name="vwap",
            sharpe=1.65,
            fitness=1.20,
            turnover=0.25,
            margin=15.0,
            is_valid_metrics=True,
            is_empty_portfolio=False,
            project_id=1
        )
        
        # Record empty portfolio simulation for capex
        await ResearchMemoryManager.record_field_outcome(
            db=db,
            field_name="capex",
            is_valid_metrics=False,
            is_empty_portfolio=True,
            project_id=1
        )
        
        # Record operator outcome for ts_decay_linear
        await ResearchMemoryManager.record_operator_outcome(
            db=db,
            operator_name="ts_decay_linear",
            sharpe=1.45,
            fitness=1.10,
            turnover=0.30,
            is_valid_metrics=True,
            is_empty_portfolio=False,
            project_id=1
        )
        
        # Fetch stats
        field_stats = await ResearchMemoryManager.get_field_statistics(db, project_id=1)
        assert len(field_stats) >= 2
        
        vwap_stat = next((f for f in field_stats if f["field_name"] == "vwap"), None)
        assert vwap_stat is not None
        assert vwap_stat["valid_rate"] > 0
        assert vwap_stat["avg_sharpe"] > 0
        
        capex_stat = next((f for f in field_stats if f["field_name"] == "capex"), None)
        assert capex_stat is not None
        assert capex_stat["empty_portfolio_rate"] > 0
        
        operator_stats = await ResearchMemoryManager.get_operator_statistics(db, project_id=1)
        assert len(operator_stats) >= 1
        ts_decay_stat = next((o for o in operator_stats if o["operator_name"] == "ts_decay_linear"), None)
        assert ts_decay_stat is not None
        assert ts_decay_stat["valid_rate"] > 0
