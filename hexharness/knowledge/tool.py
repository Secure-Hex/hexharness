"""Passive RAG search over bundled pentest playbooks. Read-only, not scope-sensitive —
safe in any phase. Wraps KnowledgeBase over the markdown files in corpus/.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from hexharness.knowledge.rag import KnowledgeBase
from hexharness.tools.base import RiskLevel, Tool

_CORPUS = Path(__file__).parent / "corpus"


@lru_cache(maxsize=1)
def _kb() -> KnowledgeBase:
    kb = KnowledgeBase()
    docs = [(p.name, p.read_text(encoding="utf-8")) for p in sorted(_CORPUS.glob("*.md"))]
    kb.index(docs)
    return kb


class KnowledgeSearchInput(BaseModel):
    query: str = Field(description="Natural-language question or keywords to search the playbook corpus")


class KnowledgeSearchTool(Tool):
    name = "knowledge_search"
    description = (
        "Search the local pentest playbook corpus (RAG) for guidance. "
        "Returns the top matching playbooks with a relevant snippet from each."
    )
    input_model = KnowledgeSearchInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    async def run(self, tool_input: dict) -> str:
        q = str(tool_input.get("query", "")).strip()
        if not q:
            return "knowledge_search: empty query."
        hits = _kb().search(q, k=3)
        if not hits:
            return f"No playbook matched '{q}'."
        return "\n\n".join(f"[{doc_id}] (score {score:.3f})\n{snippet}" for doc_id, score, snippet in hits)
