"""`Outcome` — one reportable result for a single (page, component, viewport) check.

Pure record. `mismatch_percent` is None for BROKEN — no comparison happened, and
a fake 0.0 would read as a perfect match in Allure's numeric filtering.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Outcome:
    """Verdict (or infrastructure failure) of one component check."""

    suite: str
    page: str
    name: str
    viewport: str
    status: str
    mismatch_percent: float | None
    baseline_path: str | None
    current_path: str | None
    diff_path: str | None
    error: str | None
