"""`peeksy.runner` — orchestrates generate/test/report over a `Suite` of pages.

Cell facade: the three routines (`runner.py`) declared in
`peeksy/runner/CODEMANIFEST`.
"""

from peeksy.runner.runner import run_generate, run_report, run_test

__all__ = ["run_generate", "run_report", "run_test"]
