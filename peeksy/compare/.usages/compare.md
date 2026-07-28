# compare — Comparing Two Component Screenshots

## Domain

How to compare a baseline PNG against a current PNG and read the verdict. Target
audience: the `runner` cell.

## Compare two images

```python
from peeksy.compare import compare

result = compare(
    baseline="baselines/home/header_1280x720.png",
    current="results/home/header_1280x720.current.png",
    diff_dir="results/home",
    threshold=0.1,
    tolerance=0.5,
)
```

## Read the verdict

```python
if result.passed:
    ...  # mismatch_percent <= tolerance
else:
    diff = result.diff_path  # path to the red-overlay diff PNG
```

- `threshold` (0..1) is the per-pixel sensitivity forwarded to pixelmatch.
- `tolerance` is the allowed mismatch % that decides `passed`.
- `diff_path` is set only when the comparison failed; a size change is a definite failure (100%).
