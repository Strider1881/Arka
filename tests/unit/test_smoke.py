"""P0 smoke tests: package importability and stub surface."""

from ark_operator import __version__
from ark_operator.config import Settings
from ark_operator.domain.enums import RunState
from ark_operator.domain.models import Goal
from ark_operator.llm.fake import FakeLLM


def test_version_present() -> None:
    assert __version__ == "0.1.0"


def test_goal_model() -> None:
    goal = Goal(text="Process this month's pending vendor invoices.")
    assert "invoices" in goal.text


def test_run_state_intake() -> None:
    assert RunState.INTAKE.value == "INTAKE"


def test_fake_llm_scripted() -> None:
    llm = FakeLLM(scripts={"ping": {"ok": True}})
    assert llm.complete("ping", {}).content == {"ok": True}


def test_settings_defaults() -> None:
    from ark_operator.config import DEFAULT_OPERATOR_MODEL

    settings = Settings()
    assert settings.session_expiry_n == 5
    assert settings.operator_model == DEFAULT_OPERATOR_MODEL
    assert DEFAULT_OPERATOR_MODEL.startswith("claude-haiku")
    assert "opus" not in DEFAULT_OPERATOR_MODEL
    assert "sonnet" not in DEFAULT_OPERATOR_MODEL
