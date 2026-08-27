"""peeksy.reporting — Allure result writer and HTML report builder.

Cell facade: the `Outcome` record (`outcome.py`), the `write_results` routine
(`writer.py`), and the `build_report` routine (`report.py`).
"""

from peeksy.reporting.outcome import Outcome
from peeksy.reporting.report import build_report
from peeksy.reporting.writer import write_results

__all__ = ["Outcome", "build_report", "write_results"]
