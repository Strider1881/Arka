"""CLI placeholder behavior."""

from ark_operator.cli import main


def test_cli_no_args_exits_zero() -> None:
    assert main([]) == 0


def test_cli_stub_subcommand() -> None:
    assert main(["run"]) == 0
