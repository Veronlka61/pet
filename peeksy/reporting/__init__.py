"""peeksy.reporting — Allure result writer and HTML report builder.

Cell facade: the `Outcome` record (`outcome.py`) and the `write_results`
routine (`writer.py`). `build_report` (`report.py`) joins in Task 6.
"""

from peeksy.reporting.outcome import Outcome
from peeksy.reporting.writer import write_results

__all__ = ["Outcome", "write_results"]
