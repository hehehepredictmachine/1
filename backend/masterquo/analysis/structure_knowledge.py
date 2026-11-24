"""Compatibility shim (1.46 arch, I0079): the Structure Intelligence knowledge for the agent moved to masterquo/agent/structure_knowledge.py.

It was the only module of analysis/ importing lab/ (lab.context_ind / lab.flow_context knowledge), and its only consumer is the agent - so
analysis/ is now a base layer without a dependency on lab/ or agent/. Old imports (`from masterquo.analysis import structure_knowledge`)
keep working: every attribute is resolved lazily (PEP 562) from the new module, so importing this shim creates no analysis -> agent edge
at module level. Texts and KNOWLEDGE_VERSION are unchanged (same module object behind the attributes).
"""
from __future__ import annotations

import importlib

_TARGET = "..agent.structure_knowledge"


def __getattr__(name: str):
    return getattr(importlib.import_module(_TARGET, __package__), name)


def __dir__() -> list[str]:
    return sorted(dir(importlib.import_module(_TARGET, __package__)))
