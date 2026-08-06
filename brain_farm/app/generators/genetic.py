import random
import re
from typing import List, Dict, Tuple
from brain_farm.app.generators.base import BaseGenerator
from brain_farm.app.generators.mutation import MutationGenerator
from brain_farm.app.generators.template import TemplateGenerator

class GeneticGenerator(BaseGenerator):
    """Evolves Alpha expressions over multiple generations using crossover, tournament selection, and mutations."""

    def __init__(self, allowed_fields: List[str]):
        super().__init__(allowed_fields)
        self.mutator = MutationGenerator(allowed_fields)
        self.templator = TemplateGenerator(allowed_fields)

    def crossover(self, parent1: str, parent2: str) -> Tuple[str, str]:
        """Swaps sub-expressions between two parents."""
        # Find sub-expressions surrounded by parentheses in both parent strings
        # A simple sub-expression regex matching balanced brackets is difficult,
        # but we can look for nested operator sub-strings, e.g. rank(...) or ts_xxx(...)
        pattern = r"\b(rank|group_neutralize|ts_zscore|ts_decay_linear|ts_delta|ts_mean|ts_std_dev|ts_rank)\([^)]+\)"
        
        matches1 = list(re.finditer(pattern, parent1))
        matches2 = list(re.finditer(pattern, parent2))
        
        if not matches1 or not matches2:
            # Fallback to simple midpoint split crossover if no standard operator functions found
            split_p1 = len(parent1) // 2
            split_p2 = len(parent2) // 2
            child1 = parent1[:split_p1] + parent2[split_p2:]
            child2 = parent2[:split_p2] + parent1[split_p1:]
            return child1, child2

        # Select random sub-expression match from each
        m1 = random.choice(matches1)
        m2 = random.choice(matches2)
        
        # Swap matches
        child1 = parent1[:m1.start()] + m2.group(0) + parent1[m1.end():]
        child2 = parent2[:m2.start()] + m1.group(0) + parent2[m2.end():]
        
        return child1, child2

    def select_parents(self, population_with_fitness: List[Tuple[str, float]], tournament_size: int = 3) -> Tuple[str, str]:
        """Selects two parents using tournament selection."""
        # Tournament 1
        sub1 = random.sample(population_with_fitness, min(len(population_with_fitness), tournament_size))
        parent1 = max(sub1, key=lambda x: x[1])[0]
        
        # Tournament 2
        sub2 = random.sample(population_with_fitness, min(len(population_with_fitness), tournament_size))
        parent2 = max(sub2, key=lambda x: x[1])[0]
        
        return parent1, parent2

    def generate(self, count: int = 10, **kwargs) -> List[str]:
        """
        Creates new expressions using genetic crossover/mutation.
        kwargs should provide:
            - "population_history": List of tuples (expression_text, fitness_score)
        """
        history = kwargs.get("population_history", [])
        
        # Filter out invalid entries and retain unique ones
        unique_history = {}
        for expr, fit in history:
            if expr and expr not in unique_history:
                # Default fitness to 0.0 if not scalar number
                try:
                    unique_history[expr] = float(fit) if fit is not None else 0.0
                except (ValueError, TypeError):
                    unique_history[expr] = 0.0
                    
        sorted_history = list(unique_history.items())
        
        # If historical pool is insufficient, seed with the template generator
        if len(sorted_history) < 4:
            seeded = self.templator.generate(count * 2)
            # Assign dummy fitness (random) for initial seeding
            sorted_history += [(s, random.uniform(0.1, 1.0)) for s in seeded]
            
        candidates = []
        attempts = 0
        max_attempts = count * 25
        mutation_rate = kwargs.get("mutation_rate", 0.3)
        
        while len(candidates) < count and attempts < max_attempts:
            attempts += 1
            # Select parents
            p1, p2 = self.select_parents(sorted_history)
            
            # Crossover
            c1, c2 = self.crossover(p1, p2)
            
            # Mutate
            if random.random() < mutation_rate:
                c1 = self.mutator.mutate_expression(c1)
            if random.random() < mutation_rate:
                c2 = self.mutator.mutate_expression(c2)
                
            for child in [c1, c2]:
                if child and child not in candidates and child not in unique_history:
                    # Verify syntax
                    candidates.append(child)

        return self.filter_valid(candidates)[:count]
