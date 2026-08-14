"""
AI Abstraction & Research Layer for WorldQuant BRAIN Alpha Research Platform.
Provides optional, modular, and fail-safe AI research acceleration.
"""
from brain_farm.app.ai.manager import ai_manager, AIManager
from brain_farm.app.ai.provider import AIProvider, AIProviderState

__all__ = ["ai_manager", "AIManager", "AIProvider", "AIProviderState"]
