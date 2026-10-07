"""Ingest knowledge/*.md into chunks + FTS5 retrieval with citations."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any


class KnowledgeStore:
    """FTS5 BM25 over chunked markdown with file+heading citations."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL,
                    heading TEXT NOT NULL,
                    body TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    path, heading, body, content='chunks', content_rowid='id'
                );
                """
            )

    def ingest(self, root: str | Path) -> int:
        """Index markdown under root. Returns chunk count."""
        root_p = Path(root)
        files = sorted(root_p.glob("*.md"))
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM chunks_fts")
            count = 0
            for path in files:
                text = path.read_text(encoding="utf-8")
                for heading, body in _chunk_markdown(text):
                    cur = conn.execute(
                        "INSERT INTO chunks (path, heading, body) VALUES (?, ?, ?)",
                        (path.name, heading, body),
                    )
                    rowid = cur.lastrowid
                    conn.execute(
                        "INSERT INTO chunks_fts(rowid, path, heading, body) VALUES (?, ?, ?, ?)",
                        (rowid, path.name, heading, body),
                    )
                    count += 1
            conn.commit()
        return count

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Return cited chunks."""
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT c.path, c.heading, c.body,
                           bm25(chunks_fts) AS score
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.rowid
                    WHERE chunks_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (_fts_query(query), top_k),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows:
                rows = conn.execute(
                    "SELECT path, heading, body, 0 AS score FROM chunks LIMIT ?",
                    (top_k,),
                ).fetchall()
        return [
            {
                "file": r["path"],
                "heading": r["heading"],
                "text": r["body"][:800],
                "score": float(r["score"] or 0),
            }
            for r in rows
        ]


def _chunk_markdown(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^(#{1,3}\s+.+)$", text)
    chunks: list[tuple[str, str]] = []
    if parts and parts[0].strip() and not parts[0].startswith("#"):
        chunks.append(("Introduction", parts[0].strip()))
    i = 1
    while i + 1 < len(parts):
        heading = parts[i].lstrip("# ").strip()
        body = parts[i + 1].strip()
        if body:
            chunks.append((heading, body))
        i += 2
    if not chunks and text.strip():
        chunks.append(("Document", text.strip()))
    return chunks


def _fts_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", query)
    if not tokens:
        return "invoice"
    return " OR ".join(tokens)
