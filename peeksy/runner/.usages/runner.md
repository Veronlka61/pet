# runner — Orchestrating generate / test / report

## Domain

How to run a peeksy generate/test/report pass over a loaded `Suite` of pages. Target audience:
the `cli` cell.

## Generate baselines

```python
from peeksy.config import load_config
from peeksy.runner import run_generate

suite = load_config("sites/example.com")
run_generate(suite, pages=None, components=None)  # everything
run_generate(suite, pages=["home"], components=["header"])  # one component on one page
```

`generate` writes baseline PNGs into `suite.baseline_path` as `{page}/{name}_{WxH}.png`.

## Test against baselines

```python
from peeksy.runner import run_test

exit_code = run_test(suite, pages=["home"], components=["header", "sidebar"])
```

- `test` is read-only on baselines.
- Returns `0` when every component PASSES, otherwise `1` (CI-friendly).
- Capture is grouped by (page, viewport): page setup runs once per viewport, not per component.
- Infrastructure failures (page did not load, selector missing) become `BROKEN`, not regressions.
- A component with no baseline file is reported as `BROKEN` ("baseline not found; run `peeksy generate`"), not as a regression.
- `BROKEN` outcomes carry a human-readable `error`; their image paths are `None` where no file exists.
- The results directory is cleared of prior `*-result.json`/attachment files before each `test` write, so consecutive runs never silently mix.

## Build the report

```python
from peeksy.runner import run_report

run_report(suite)
```

Builds the Allure HTML into `suite.report_path` (requires the `allure` CLI).