from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field

class AIProviderStatus(BaseModel):
    configured: bool
    valid: bool
    state: str  # AI_NOT_CONFIGURED, AI_AVAILABLE, etc.
    provider: str
    model: str
    message: str
    last_validated: Optional[str] = None
    enabled_features: Dict[str, bool] = Field(default_factory=dict)
    daily_calls: int = 0
    monthly_calls: int = 0
    estimated_cost: float = 0.0

class ResearchHypothesis(BaseModel):
    family: str = Field(..., description="Target research family e.g. VALUE, MOMENTUM, QUALITY, REVERSAL, ANALYST")
    hypothesis: str = Field(..., description="Clear economic/quantitative hypothesis explanation")
    horizon: str = Field(default="MEDIUM", description="SHORT, MEDIUM, or LONG")
    preferred_fields: List[str] = Field(default_factory=list, description="List of validated data fields to use")
    suggested_transformations: List[str] = Field(default_factory=list, description="Suggested transformations like rank, smoothing, decay, zscore")
    suggested_operators: List[str] = Field(default_factory=list, description="Operators to emphasize e.g. ts_mean, ts_delta, rank, group_neutralize")
    reasoning: str = Field(default="", description="Theoretical and statistical rationale")
    priority: float = Field(default=0.75, ge=0.0, le=1.0, description="Priority score between 0.0 and 1.0")

class FailureAnalysis(BaseModel):
    classification: Literal["STRONG_FAILURE", "PARAMETER_MISMATCH", "OVERFITTING_RISK", "WEAK_SIGNAL", "STRUCTURAL_DEFECT"] = "WEAK_SIGNAL"
    likely_issue: str = Field(..., description="Identified failure cause")
    recommended_action: Literal["ABANDON", "CHANGE_FAMILY", "APPLY_TRANSFORMATION", "CHANGE_HYPOTHESIS", "TUNE_HORIZON"] = "CHANGE_HYPOTHESIS"
    avoid: List[str] = Field(default_factory=list, description="Patterns or variations to avoid")
    recommended_families: List[str] = Field(default_factory=list, description="Alternative families recommended")
    reasoning: str = Field(default="", description="Detailed quantitative rationale")

class ExperimentProposal(BaseModel):
    type: str = Field(..., description="Experiment type e.g. SMOOTHING, DECAY, HORIZON, RANKING, VOLATILITY_NORM")
    transformation: str = Field(..., description="Transformation rule or operator e.g. ts_decay_linear, ts_mean, rank")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameter map e.g. {'window': 20, 'decay': 5}")
    rationale: str = Field(default="", description="Why this experiment may improve metric")

class NearMissProposal(BaseModel):
    parent_alpha_id: Optional[str] = None
    candidate_expression: str
    target_metric_to_improve: str = "SHARPE"
    experiments: List[ExperimentProposal] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    reasoning: str = Field(default="")

class TurnoverOptimizationProposal(BaseModel):
    candidate_expression: str
    current_sharpe: float
    current_fitness: float
    current_turnover: float
    recommended_techniques: List[str] = Field(default_factory=list)  # e.g. ["ts_decay_linear", "ts_mean", "group_rank"]
    experiments: List[ExperimentProposal] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    explanation: str = Field(default="")

class ResearchDirectorPlan(BaseModel):
    strategic_summary: str
    recommended_allocation: Dict[str, int] = Field(default_factory=dict, description="Allocation of simulation budget per family, e.g. {'VALUE': 40, 'QUALITY': 30}")
    priority_hypotheses: List[ResearchHypothesis] = Field(default_factory=list)
    research_gaps: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)

class CriticReview(BaseModel):
    risk_level: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"] = "LOW"
    overfitting_probability: float = Field(default=0.2, ge=0.0, le=1.0)
    parameter_sensitivity_warning: bool = False
    data_mining_bias_warning: bool = False
    critique: str = Field(default="")
    recommendation: Literal["PASS_ROBUST", "REQUIRE_ADDITIONAL_WALKFORWARD", "FLAG_SUSPICIOUS", "DO_NOT_PROMOTE"] = "PASS_ROBUST"
    suggested_stress_tests: List[str] = Field(default_factory=list)
