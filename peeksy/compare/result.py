"""`ComparisonResult` — the verdict of one image comparison.

Pure record: `passed`, `mismatch_percent` (0..100), and `diff_path` which is
None whenever the comparison passed (no diff overlay is written for a pass).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ComparisonResult:
    """Verdict of one baseline-vs-current comparison."""

    passed: bool
    mismatch_percent: float
    diff_path: str | None
