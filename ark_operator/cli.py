"""CLI entrypoints: run, approve, status, replay, eval (SPEC §3).

STUB: commands wired in later phases; P0 exposes a placeholder main.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    """Parse CLI args and dispatch. STUB for most subcommands."""
    parser = argparse.ArgumentParser(prog="operator", description="Operator CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="STUB: start a run (P2+)")
    sub.add_parser("approve", help="STUB: approve/reject a step (P6)")
    sub.add_parser("status", help="STUB: show run status (P2)")
    sub.add_parser("replay", help="STUB: replay a run from events (P2)")
    sub.add_parser("eval", help="STUB: run evals (P10)")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    print(f"STUB: operator {args.command} not implemented yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
