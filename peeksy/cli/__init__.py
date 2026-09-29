"""`peeksy.cli` — Typer facade: `generate` / `test` / `report` / `main`.

Cell facade: the four routines (`app.py`) declared in `peeksy/cli/CODEMANIFEST`,
plus the module-level Typer `app` used by tests (CliRunner) — intentionally
not a contract entity.
"""

from peeksy.cli.app import app, generate, main, report, test

__all__ = ["app", "generate", "main", "report", "test"]
