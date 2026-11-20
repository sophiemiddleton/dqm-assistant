"""The detector plugin contract and its registry.

Adding a method = one subclass of `Detector` with a `card`, decorated with `@register`.
The assessor, the store and the MCP tools never change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Type

from dqm_assistant.context import RunContext
from dqm_assistant.findings import Finding, MethodCard

REGISTRY: Dict[str, Type["Detector"]] = {}


def register(name: str) -> Callable[[Type["Detector"]], Type["Detector"]]:
    def deco(cls: Type["Detector"]) -> Type["Detector"]:
        cls.name = name
        REGISTRY[name] = cls
        return cls
    return deco


class Detector(ABC):
    name: str = "?"
    version: str = "0"
    card: MethodCard

    def __init__(self, **options):
        self.options = options

    @property
    def method_id(self) -> str:
        return self.name

    @abstractmethod
    def assess(self, ctx: RunContext) -> List[Finding]:
        """Judge one run. Must not raise for a single bad item: return UNSURE for it."""


def build(spec: Dict) -> Detector:
    """`{"type": "ks", ...options}` from the config -> a detector instance."""
    spec = dict(spec)
    kind = spec.pop("type")
    if kind not in REGISTRY:
        raise KeyError(f"unknown detector {kind!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[kind](**spec)
