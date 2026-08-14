import pytest
from brain_farm.app.ai.hypothesis_agent import HypothesisAgent
from brain_farm.app.ai.failure_agent import FailureAgent
from brain_farm.app.ai.near_miss_agent import NearMissAgent
from brain_farm.app.ai.turnover_agent import TurnoverAgent
from brain_farm.app.ai.research_director import ResearchDirector
from brain_farm.app.ai.critic_agent import CriticAgent
from brain_farm.app.ai.manager import ai_manager, AIProviderState

@pytest.mark.asyncio
async def test_hypothesis_agent_deterministic_fallback():
    # Force AI unavailable
    ai_manager.state = AIProviderState.NOT_CONFIGURED
    agent = HypothesisAgent(["close", "volume", "vwap"])
    hypo = await agent.generate_hypothesis(target_family="VALUE")
    
    assert hypo.family == "VALUE"
    assert "valuation" in hypo.hypothesis.lower() or "value" in hypo.hypothesis.lower()
    
    # Test formula compilation
    expressions = agent.convert_hypothesis_to_expressions(hypo, count=3)
    assert len(expressions) >= 1
    for expr in expressions:
        assert isinstance(expr, str)
        assert len(expr) > 0

@pytest.mark.asyncio
async def test_failure_agent_deterministic_classification():
    agent = FailureAgent()
    # 1. Toxic negative alpha
    toxic = await agent.analyze_failure("close / open", "VALUE", sharpe=-1.2, fitness=-0.8, turnover=0.5, margin=1.0)
    assert toxic.classification == "STRONG_FAILURE"
    assert toxic.recommended_action == "ABANDON"
    
    # 2. High turnover defect
    high_to = await agent.analyze_failure("ts_delta(close, 1)", "MOMENTUM", sharpe=1.1, fitness=0.7, turnover=1.5, margin=2.0)
    assert high_to.classification == "STRUCTURAL_DEFECT"
    assert high_to.recommended_action == "APPLY_TRANSFORMATION"

@pytest.mark.asyncio
async def test_near_miss_agent():
    agent = NearMissAgent(["close", "volume", "vwap"])
    proposal = await agent.propose_experiments("close / vwap", sharpe=1.21, fitness=0.98, turnover=0.45, margin=5.0)
    assert proposal.candidate_expression == "close / vwap"
    assert len(proposal.experiments) >= 1
    
    # Apply experiment
    child = agent.apply_experiment_to_expression("close / vwap", proposal.experiments[0])
    assert child is not None

@pytest.mark.asyncio
async def test_turnover_agent():
    agent = TurnoverAgent(["close", "volume", "vwap"])
    proposal = await agent.propose_turnover_reduction("ts_delta(close, 3)", sharpe=1.45, fitness=1.15, turnover=0.88)
    assert proposal.current_sharpe == 1.45
    assert len(proposal.experiments) >= 1
    
    cands = agent.generate_smoothed_candidates("ts_delta(close, 3)", proposal)
    assert len(cands) >= 1
    assert any("ts_decay_linear" in c or "group_neutralize" in c for c in cands)

@pytest.mark.asyncio
async def test_research_director_and_critic():
    # Director plan
    director = ResearchDirector()
    plan = await director.formulate_research_plan({"total_recorded_experiments": 50}, total_budget=100)
    assert sum(plan.recommended_allocation.values()) > 0
    assert len(plan.priority_hypotheses) >= 1
    
    # Critic review
    critic = CriticAgent()
    review = await critic.review_candidate("rank(ts_decay_linear(close, 10))", sharpe=1.40, fitness=1.10, turnover=0.45, stability_score=0.88, robustness_score=0.82)
    assert review.risk_level in ("LOW", "MODERATE", "HIGH")
    assert review.recommendation in ("PASS_ROBUST", "REQUIRE_ADDITIONAL_WALKFORWARD", "FLAG_SUSPICIOUS", "DO_NOT_PROMOTE")
