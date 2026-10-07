"""Ingest knowledge/*.md into chunks + FTS5 retrieval with citations.

STUB: P3/P4.
"""


class KnowledgeStore:
    """FTS5 BM25 over chunked markdown with file+heading citations."""

    def ingest(self, root: str) -> None:
        """Index markdown under root. STUB."""
        raise NotImplementedError("STUB: KnowledgeStore.ingest (P3)")

    def search(self, query: str, top_k: int = 5) -> list[dict[str, object]]:
        """Return cited chunks. STUB."""
        raise NotImplementedError("STUB: KnowledgeStore.search (P3)")
