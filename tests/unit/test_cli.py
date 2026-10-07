"""CLI placeholder / help behavior."""

from ark_operator.cli import main


def test_cli_no_args_exits_zero() -> None:
    assert main([]) == 0


def test_cli_help_subcommand() -> None:
    # argparse --help exits via SystemExit(0)
    try:
        main(["run", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
