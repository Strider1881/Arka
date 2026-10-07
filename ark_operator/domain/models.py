"""Pydantic domain models for goals, plans, evidence, and reports.

STUB: full field definitions land in P2 (runtime skeleton).
"""

from pydantic import BaseModel, Field


class Goal(BaseModel):
    """User-supplied goal / request text."""

    text: str = Field(..., min_length=1)


class Interpretation(BaseModel):
    """Structured understanding of a Goal (SPEC §6.3).

    STUB: fields expanded in P4.
    """

    intended_outcome: str = ""
    assumptions: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    """Typed plan of steps (SPEC §6.4).

    STUB: full Step graph in P2/P4.
    """

    steps: list[str] = Field(default_factory=list)


class Step(BaseModel):
    """Single plan step.

    STUB: tool/args/postcondition fields in P2.
    """

    id: str
    description: str = ""


class Action(BaseModel):
    """A concrete tool action to execute."""

    name: str
    args: dict[str, object] = Field(default_factory=dict)


class Observation(BaseModel):
    """Result of executing an Action."""

    summary: str = ""


class Failure(BaseModel):
    """Typed failure returned by tools or recovery."""

    kind: str
    message: str


class Approval(BaseModel):
    """Durable human approval / question record."""

    id: str
    prompt: str = ""


class Evidence(BaseModel):
    """Artifact proving an action or verification check (e.g. screenshot)."""

    label: str
    path: str = ""


class VerificationResult(BaseModel):
    """Independent verifier output (SPEC §7).

    STUB: per-criterion checks in P7.
    """

    passed: bool = False
    confidence: str = "LOW"


class RunReport(BaseModel):
    """Final one-screen proof report payload."""

    summary: str = ""
