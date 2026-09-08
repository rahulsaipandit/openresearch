"""
Skill — a named behavior that operates over a candidate's shared
InterviewMemoryStore.

Per the requirements-doc discussion: the interview cognitive memory is one
system, but multiple skills can be applied to it — e.g. live_interview_coach
(real-time answer generation during a Pluely session) and pre_interview_drill
(SM-2 spaced-repetition practice of previously asked questions). Both skills
read/write the *same* memory, so a question answered live also becomes
drillable practice material later.

This is intentionally a thin, code-executed interface — not the
cognitiveBrain SKILL.md prompt-injection pattern (docs/packages/cognitiveBrain/
docs/designCognitiveBrain.md §5.6/§6.9), which augments agent behavior
through instruction text only. These skills need real logic (retrieval, SM-2
scheduling, judge dispatch), not just a prompt fragment.
"""

from abc import ABC, abstractmethod
from typing import Any

from memory.interview_memory import InterviewMemoryStore


class Skill(ABC):
    name: str
    description: str

    @abstractmethod
    def apply(self, memory: InterviewMemoryStore, **kwargs: Any) -> Any:
        """Execute this skill against the given candidate's memory."""
        raise NotImplementedError


_REGISTRY: dict[str, Skill] = {}


def register_skill(skill: Skill) -> Skill:
    _REGISTRY[skill.name] = skill
    return skill


def get_skill(name: str) -> Skill:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown skill '{name}'. Available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def list_skills() -> list[dict[str, str]]:
    return [{"name": s.name, "description": s.description} for s in _REGISTRY.values()]
