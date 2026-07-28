# Image Diff — pixelmatch Comparison

## Domain

Comparing two component screenshots (baseline vs current) and deciding whether
the component regressed, using the **`pixelmatch`** Python port + **Pillow**.
Target audience: the cell that takes two PNGs and produces a verdict
(pass/fail), a numeric mismatch percentage, and a diff image.

This file covers *how to use pixelmatch*. It does not describe the cell contract.

---

## Why pixelmatch

- **Anti-aliasing aware** — treats AA edge pixels differently from real color
  changes, so font/edge rendering noise doesn't register as a regression.
- Returns an exact **mismatch pixel count** and paints a **diff overlay**
  (changed pixels in red) in one call.
- Tiny, dependency-light, designed exactly for visual regression.

## Setup

```bash
uv add pixelmatch pillow
```

> Pin the exact `pixelmatch` version in `pyproject.toml`. There are several
> Python ports under this name; the API below matches the maintained port that
> accepts Pillow images. Verify the call signature against the pinned version
> and adapt if it differs.

---

## Comparison routine

```python
from PIL import Image
from pixelmatch import pixelmatch


def compare(baseline_path: str, current_path: str, diff_path: str,
            threshold: float = 0.1) -> tuple[bool, float]:
    """Return (passed, mismatch_percent).

    `threshold` (0..1) is the per-pixel color sensitivity passed straight to
    pixelmatch — lower is stricter.
    """
    baseline = Image.open(baseline_path).convert("RGBA")
    current = Image.open(current_path).convert("RGBA")

    # Dimension guard: pixelmatch requires identical sizes.
    if baseline.size != current.size:
        # A size change IS a regression; report it explicitly rather than
        # letting pixelmatch error out.
        return False, 100.0

    diff = Image.new("RGBA", baseline.size)
    mismatched = pixelmatch(baseline, current, diff, threshold=threshold,
                            includeAA=True)
    total = baseline.size[0] * baseline.size[1]
    mismatch_percent = (mismatched / total) * 100.0

    if mismatched > 0:
        diff.save(diff_path)

    return mismatch_percent == 0.0, mismatch_percent
```

### Key points

- **Convert to RGBA** before comparing — different source modes (RGB vs RGBA vs
  P) skew the delta.
- **Size mismatch = regression.** A component whose box grew/shrank has changed;
  surface it as a definite failure (100%) instead of crashing.
- **`includeAA=True`** keeps anti-aliased edges out of the diff count, reducing
  flakiness across font-hinting / sub-pixel differences.
- **Save the diff only when there are changes** — no point storing an empty
  overlay for passing components.

---

## Threshold model

There are two thresholds; do not conflate them:

1. **pixelmatch `threshold`** — per-pixel color sensitivity (0..1). Controls
   which individual pixels count as "different." Configured per component or
   globally in YAML.
2. **`tolerance` / allowed mismatch %** — the suite-level rule: *a component
   passes when `mismatch_percent <= tolerance`*. This is the regression
   decision the Allure status is derived from.

Example: `threshold=0.1` (pixelmatch, strict-ish per-pixel) and
`tolerance=0.5` (component passes if ≤ 0.5% of pixels differ).

---

## Output contract for the diff cell

- Inputs: baseline PNG path, current PNG path, configured `threshold` and
  `tolerance`, output path for the diff image.
- Outputs: `passed: bool`, `mismatch_percent: float`, `diff_path: str | None`
  (only when not passed).
- Deterministic: same inputs → same verdict and same diff image.