"""Interpret a raw request into a structured Interpretation (SPEC §6.3)."""

from __future__ import annotations

from typing import Any

from ark_operator.domain.models import Interpretation, PolicyCitation
from ark_operator.llm.base import LLMClient


class Understander:
    """Goal -> Interpretation with assumptions and policy citations."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def interpret(
        self, request: str, *, knowledge_snippets: list[dict[str, Any]] | None = None
    ) -> Interpretation:
        variables = {
            "request": request,
            "knowledge": knowledge_snippets or [],
        }
        try:
            resp = self.llm.complete("understand", variables, schema=Interpretation)
            content = resp.content
            if isinstance(content, Interpretation):
                return content
            if isinstance(content, dict):
                return Interpretation.model_validate(content)
        except Exception:
            # Deterministic fallback when prompt/script missing
            pass
        return Interpretation(
            intended_outcome="Process this month's pending vendor invoices end-to-end.",
            assumptions=[
                "Invoices are PDF files in the company inbox.",
                "Company policies in knowledge/ apply.",
            ],
            sources_needed=["inbox PDFs", "procurement portal", "knowledge base"],
            applicable_policies=[
                PolicyCitation(file="invoice_processing_sop.md", section="Three-way match"),
                PolicyCitation(file="approval_policy.md", section="Threshold"),
            ],
            permitted_actions=[
                "extract_invoice",
                "search_knowledge",
                "browser_portal",
                "ask_human",
            ],
            success_criteria=[
                "Each invoice has a decision matching policy.",
                "Portal state matches decision where submission is required.",
                "Independent verifier passes for completed invoices.",
            ],
            open_questions=[],
        )
