"""`peeksy.cli` — Typer facade: `generate` / `test` / `report` / `main`.

Cell facade: the four routines (`app.py`) plus the module-level Typer `app`
declared in `peeksy/cli/CODEMANIFEST`.
"""

from peeksy.cli.app import app, generate, main, report, test

__all__ = ["app", "generate", "main", "report", "test"]
