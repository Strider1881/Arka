"""FTS5 knowledge search tool wrapping memory.knowledge."""

from __future__ import annotations

from typing import Any

from ark_operator.domain.enums import RiskLevel
from ark_operator.domain.models import Observation
from ark_operator.memory.knowledge import KnowledgeStore
from ark_operator.tools.base import BaseTool, ToolResult


class KnowledgeSearchTool(BaseTool):
    """Search company knowledge with citations."""

    name = "knowledge_search"
    risk_class = RiskLevel.READ
    timeout_seconds = 10.0
    description = "Search company knowledge base (FTS5) with file+heading citations"

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def _run(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query", ""))
        top_k = int(args.get("top_k", 5))
        hits = self.store.search(query, top_k=top_k)
        return ToolResult(
            ok=True,
            observation=Observation(
                summary=f"Found {len(hits)} knowledge chunks",
                data={"hits": hits},
            ),
            data={"hits": hits},
        )
