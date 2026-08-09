import pytest
from brain_farm.app.generators.family_info import RESEARCH_FAMILIES
from brain_farm.app.generators.family_gen import FamilyGenerator

def test_research_families_metadata():
    # Verify that all 17 families exist and have valid keys
    required_keys = {"description", "allowed_fields", "preferred_operators", "neutralization", "turnover_range", "templates"}
    assert len(RESEARCH_FAMILIES) == 17
    for name, info in RESEARCH_FAMILIES.items():
        assert required_keys.issubset(info.keys())
        assert isinstance(info["allowed_fields"], list)
        assert isinstance(info["templates"], list)

def test_family_generator_all_families():
    allowed_fields = ["close", "open", "volume", "vwap", "book_value", "ebit", "sales", "net_income", "total_assets", "debt", "revenue", "fcf", "cash", "eps_estimate", "shares_out"]
    
    # Test generation for each of the 17 families
    for family in RESEARCH_FAMILIES.keys():
        gen = FamilyGenerator(allowed_fields=allowed_fields, family_name=family)
        assert gen.family_name == family
        
        candidates = gen.generate(count=3)
        # Ensure it generated up to 3 candidates
        assert len(candidates) > 0
        for expr in candidates:
            assert isinstance(expr, str)
            # Assert it doesn't contain incompatible operators if any are defined
            incompat = RESEARCH_FAMILIES[family].get("incompatible_operators", [])
            for op in incompat:
                assert op not in expr

def test_family_generator_incompatible_ops():
    # Value family lists 'ts_delta' as incompatible
    allowed_fields = ["close", "book_value"]
    gen = FamilyGenerator(allowed_fields=allowed_fields, family_name="VALUE")
    candidates = gen.generate(count=5)
    for expr in candidates:
        assert "ts_delta" not in expr

def test_family_generator_invalid_family_fallback():
    # If an unrecognized family name is passed, it should default to MOMENTUM
    gen = FamilyGenerator(allowed_fields=["close"], family_name="INVALID_FAMILY_NAME")
    assert gen.family_name == "MOMENTUM"
