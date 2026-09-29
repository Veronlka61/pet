# Cell: compare

`peeksy.compare` — pixelmatch-based comparison of two component screenshots.

- **Contract:** [`peeksy/compare/CODEMANIFEST`](https://github.com/Veronlka61/pet/tree/main/peeksy/compare)
- **Depends on:** nothing (leaf)

## API

| Entity | Signature | Location |
|---|---|---|
| `ComparisonResult` | `ComparisonResult(passed: bool, mismatch_percent: float, diff_path: str \| None)` | `result.py` |
| `compare` | `compare(baseline: str, current: str, diff_dir: str, threshold: float, tolerance: float) -> ComparisonResult` | `compare.py` |

## Algorithm

1. open both PNGs, convert to RGBA
2. **size mismatch ⇒ definite failure**: `ComparisonResult(False, 100.0, None)`
3. pixelmatch with `threshold`, `includeAA=True` → mismatched pixel count
4. `mismatch_percent = mismatched / total * 100`
5. `passed = mismatch_percent <= tolerance` (non-strict `<=`)
6. the diff overlay is saved into `diff_dir` **only when not passed**
   (`diff_path=None` otherwise)

The import is the PIL-aware entry point: `from pixelmatch.contrib.PIL import pixelmatch`.

Note: in pixelmatch 0.4.0 the `includeAA` flag is inverted relative to its
name — peeksy passes `True` per contract, which counts anti-aliased edge
shifts as mismatches (verified by `test_compare_counts_anti_aliased_edge_shifts`).
