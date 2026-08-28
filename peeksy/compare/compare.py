"""`compare` — pixelmatch-based baseline-vs-current comparison.

Two thresholds, never conflated: `threshold` is the per-pixel color sensitivity
forwarded to pixelmatch; `tolerance` is the allowed mismatch % that decides the
verdict (`passed` iff `mismatch_percent <= tolerance`).
"""

import os
from pathlib import Path

from PIL import Image
from pixelmatch.contrib.PIL import pixelmatch

from peeksy.compare.result import ComparisonResult


def compare(
    baseline: str,
    current: str,
    diff_dir: str,
    threshold: float,
    tolerance: float,
) -> ComparisonResult:
    """Compare a baseline PNG against a current PNG and decide whether the component regressed."""
    baseline_img = Image.open(baseline).convert("RGBA")
    current_img = Image.open(current).convert("RGBA")

    # A size change IS a regression; report it as a definite failure instead of
    # letting pixelmatch error out on mismatched dimensions.
    if baseline_img.size != current_img.size:
        return ComparisonResult(passed=False, mismatch_percent=100.0, diff_path=None)

    diff_img = Image.new("RGBA", baseline_img.size)
    # `includeAA=True` per the contract — pixelmatch's flag is inverted relative
    # to its name (`if not includeAA` guards the detector), so True DISABLES the
    # anti-aliasing filter and counts every AA edge pixel a real shift moved.
    # Flapping is not a risk: an unchanged re-capture is byte-identical and hits
    # pixelmatch's fast path (0 mismatched) before the detector ever runs.
    mismatched = pixelmatch(
        baseline_img, current_img, diff_img, threshold=threshold, includeAA=True
    )
    total = baseline_img.size[0] * baseline_img.size[1]
    mismatch_percent = (mismatched / total) * 100.0

    if mismatch_percent > tolerance:
        # Diff name derives from the BASELINE stem so the runner's page-namespaced
        # path convention holds: {name}_{WxH}.png -> {name}_{WxH}.diff.png.
        diff_path = os.path.join(diff_dir, Path(baseline).stem + ".diff.png")
        os.makedirs(diff_dir, exist_ok=True)
        diff_img.save(diff_path)
        return ComparisonResult(
            passed=False, mismatch_percent=mismatch_percent, diff_path=diff_path
        )

    return ComparisonResult(passed=True, mismatch_percent=mismatch_percent, diff_path=None)
