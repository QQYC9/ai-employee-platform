from __future__ import annotations

"""
Provider-neutral AI Task Planner module.

Exposes AITaskPlanner (aliased to GeminiTaskPlanner) which works with any
AIProvider (Groq, OpenAI, Gemini, etc.) that implements generate_json().
"""

from packages.services.gemini_task_planner import (
    GeminiTaskPlanner,
    GeminiTaskPlanner as AITaskPlanner,
)

__all__ = [
    "AITaskPlanner",
    "GeminiTaskPlanner",
]
