from brain_farm.app.generators.template import TemplateGenerator
from brain_farm.app.generators.ast_gen import ASTGenerator
from brain_farm.app.generators.mutation import MutationGenerator
from brain_farm.app.generators.genetic import GeneticGenerator

ALLOWED_FIELDS = ["close", "open", "volume", "vwap"]

def test_template_generator():
    gen = TemplateGenerator(ALLOWED_FIELDS)
    alphas = gen.generate(count=5)
    assert len(alphas) <= 5
    for alpha in alphas:
        assert isinstance(alpha, str)
        # Ensure it contains at least one of the allowed fields
        assert any(f in alpha for f in ALLOWED_FIELDS)

def test_ast_generator():
    # Use max depth 2 to keep expressions small and simple for test validation
    gen = ASTGenerator(ALLOWED_FIELDS, max_depth=2)
    alphas = gen.generate(count=5)
    assert len(alphas) <= 5
    for alpha in alphas:
         # Bracket balanced Check
         open_c = alpha.count("(")
         close_c = alpha.count(")")
         assert open_c == close_c
         assert "rank(rank(" not in alpha  # checking recursion simplification
         
def test_mutation_generator():
    gen = MutationGenerator(ALLOWED_FIELDS)
    
    # Test individual mutation
    base_expr = "ts_zscore(close, 20)"
    mutated = gen.mutate_expression(base_expr)
    
    assert mutated != base_expr
    # Check that it mutated window size or wrapped it in decay / neutralise
    assert "ts_zscore(" in mutated or "ts_decay_linear(" in mutated or "group_neutralize(" in mutated

def test_genetic_generator():
    gen = GeneticGenerator(ALLOWED_FIELDS)
    
    # Check crossover function
    parent1 = "group_neutralize(rank(close), subindustry)"
    parent2 = "ts_decay_linear(rank(open), 10)"
    
    child1, child2 = gen.crossover(parent1, parent2)
    assert child1 != parent1
    assert child2 != parent2
    
    # Check GA generation flow
    history = [("rank(close)", 1.2), ("group_neutralize(open, industry)", 1.5)]
    alphas = gen.generate(count=3, population_history=history)
    assert len(alphas) <= 3
