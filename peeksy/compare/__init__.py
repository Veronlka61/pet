"""peeksy.compare — pixelmatch comparison with a tolerance-based verdict.

Cell facade: the `ComparisonResult` record (`result.py`) and the `compare`
routine (`compare.py`).
"""

from peeksy.compare.compare import compare
from peeksy.compare.result import ComparisonResult

__all__ = ["ComparisonResult", "compare"]
