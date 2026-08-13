from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from brain_farm.app.database.session import Base
from brain_farm.app.core.security import encrypt_data, decrypt_data

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    encrypted_password: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    projects: Mapped[List["Project"]] = relationship("Project", back_populates="user")

    def set_password(self, password: str):
        self.encrypted_password = encrypt_data(password)

    def get_password(self) -> str:
        return decrypt_data(self.encrypted_password)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Simulation Parameters
    region: Mapped[str] = mapped_column(String(50), default="USA")
    universe: Mapped[str] = mapped_column(String(50), default="TOP3000")
    neutralization: Mapped[str] = mapped_column(String(50), default="SUBINDUSTRY")
    delay: Mapped[int] = mapped_column(Integer, default=1)
    decay: Mapped[int] = mapped_column(Integer, default=0)
    
    # Target Thresholds
    min_sharpe: Mapped[float] = mapped_column(Float, default=1.25)
    min_fitness: Mapped[float] = mapped_column(Float, default=1.00)
    max_turnover: Mapped[float] = mapped_column(Float, default=0.70)
    min_margin: Mapped[float] = mapped_column(Float, default=4.0)  # bps
    min_sub_universe_sharpe: Mapped[float] = mapped_column(Float, default=1.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="projects")
    expressions: Mapped[List["Expression"]] = relationship("Expression", back_populates="project", cascade="all, delete-orphan")
    logs: Mapped[List["ProjectLog"]] = relationship("ProjectLog", back_populates="project", cascade="all, delete-orphan")


class Expression(Base):
    __tablename__ = "expressions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"))
    expression_text: Mapped[str] = mapped_column(Text)
    generator_type: Mapped[str] = mapped_column(String(50))  # AST, LLM, GENETIC, TEMPLATE, MUTATION
    status: Mapped[str] = mapped_column(String(50), default="PENDING")  # PENDING, SIMULATING, PASSED, REJECTED, ERROR
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("expressions.id"), nullable=True)  # For mutations/GA/LLM track origin
    
    # Research Memory Schema additions
    research_family: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hypothesis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lineage_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    complexity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    parameter_sensitivity: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    regime_performance: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Hypothesis-Driven additions
    expected_horizon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    selected_fields: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    selected_operators: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    operator_parameters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    expected_turnover_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Lineage and mutation tracking additions
    parent_alpha_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    generation_number: Mapped[int] = mapped_column(Integer, default=1)
    mutation_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    mutation_parameters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Complexity tracking additions
    expression_depth: Mapped[int] = mapped_column(Integer, default=1)
    operator_count: Mapped[int] = mapped_column(Integer, default=0)
    field_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Transformation tracking additions
    transformation_parent: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transformation_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="expressions")
    simulations: Mapped[List["Simulation"]] = relationship("Simulation", back_populates="expression", cascade="all, delete-orphan")


class Simulation(Base):
    __tablename__ = "simulations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expression_id: Mapped[int] = mapped_column(Integer, ForeignKey("expressions.id"))
    brain_simulation_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True, nullable=True)
    brain_alpha_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="QUEUED")  # QUEUED, SENT, POLLING, COMPLETE, ERROR
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    expression: Mapped["Expression"] = relationship("Expression", back_populates="simulations")
    metrics: Mapped[Optional["Metric"]] = relationship("Metric", back_populates="simulation", cascade="all, delete-orphan")


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    simulation_id: Mapped[int] = mapped_column(Integer, ForeignKey("simulations.id"), unique=True)
    
    # In-Sample (IS) Metrics
    sharpe: Mapped[float] = mapped_column(Float, default=0.0)
    fitness: Mapped[float] = mapped_column(Float, default=0.0)
    turnover: Mapped[float] = mapped_column(Float, default=0.0)
    returns: Mapped[float] = mapped_column(Float, default=0.0)
    margin: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Bookkeeping details
    sub_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    long_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    short_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Statistical validation metrics additions
    rank_ic: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    mean_ic: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    median_ic: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    ic_std_dev: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    ic_ir: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    positive_ic_ratio: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    walk_forward_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    regime_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    correlation_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    composite_research_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)

    # Upgraded Metric fields
    stability_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    robustness_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    diversity_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    simplicity_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    alpha_research_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)

    walk_forward_mean_sharpe: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    walk_forward_median_sharpe: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    walk_forward_min_sharpe: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    walk_forward_variance: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    parameter_stability_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)

    experiment_count: Mapped[int] = mapped_column(Integer, default=1)
    family_experiment_count: Mapped[int] = mapped_column(Integer, default=1)
    lineage_experiment_count: Mapped[int] = mapped_column(Integer, default=1)

    pareto_optimal: Mapped[bool] = mapped_column(Boolean, default=False)
    candidate_tier: Mapped[int] = mapped_column(Integer, default=0)
    multiple_testing_adjusted_score: Mapped[Optional[float]] = mapped_column(Float, default=0.0, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    simulation: Mapped["Simulation"] = relationship("Simulation", back_populates="metrics")


class ProjectLog(Base):
    __tablename__ = "project_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"))
    level: Mapped[str] = mapped_column(String(20), default="INFO")  # INFO, WARNING, ERROR, SUCCESS
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped["Project"] = relationship("Project", back_populates="logs")


class DataFieldCache(Base):
    __tablename__ = "data_field_cache"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # Field ID
    name: Mapped[str] = mapped_column(String(255))
    dataset: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100))
    region: Mapped[str] = mapped_column(String(50))
    universe: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(50), default="UNKNOWN")  # e.g., INTEGER, FLOAT
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
