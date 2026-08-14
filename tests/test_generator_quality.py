import pytest
from brain_farm.app.generators.ast_gen import ASTGenerator
from brain_farm.app.generators.template import TemplateGenerator
from brain_farm.app.generators.family_gen import FamilyGenerator
from brain_farm.app.evaluators.signal_classifier import SignalQualityClassifier

def test_ast_generator_produces_predictive_signals():
    allowed_fields = ["close", "open", "volume", "vwap", "subindustry", "industry"]
    gen = ASTGenerator(allowed_fields=allowed_fields)
    candidates = gen.generate(count=10)
    
    assert len(candidates) > 0
    for expr in candidates:
        classification = SignalQualityClassifier.classify(expr)
        # None of the generated formulas should be naked neutralizations
        assert not classification["is_naked_neutralization"]
        assert classification["signal_type"] in ("TRANSFORMED_SIGNAL", "PREDICTIVE_SIGNAL")


def test_template_generator_produces_predictive_signals():
    allowed_fields = ["close", "open", "volume", "vwap", "subindustry", "industry"]
    gen = TemplateGenerator(allowed_fields=allowed_fields)
    candidates = gen.generate(count=10)
    
    assert len(candidates) > 0
    for expr in candidates:
        classification = SignalQualityClassifier.classify(expr)
        assert not classification["is_naked_neutralization"]
        assert classification["signal_type"] in ("TRANSFORMED_SIGNAL", "PREDICTIVE_SIGNAL")


def test_family_generator_attaches_research_metadata():
    allowed_fields = ["close", "open", "volume", "vwap", "subindustry", "industry"]
    gen = FamilyGenerator(allowed_fields=allowed_fields, family_name="MOMENTUM")
    candidates = gen.generate(count=5)
    
    assert len(candidates) > 0
    for expr in candidates:
        meta = gen.generated_metadata.get(expr)
        assert meta is not None
        assert meta["research_family"] == "MOMENTUM"
        assert "hypothesis" in meta
        assert "signal_type" in meta
        assert "research_quality_score" in meta
        assert meta["research_quality_score"] > 0
