# Cell: reporting

`peeksy.reporting` — Allure result writer and HTML report builder. One result
per (page, component, viewport).

- **Contract:** [`peeksy/reporting/CODEMANIFEST`](https://github.com/Veronlka61/pet/tree/main/peeksy/reporting)
- **Depends on:** nothing (leaf)

## API

| Entity | Signature | Location |
|---|---|---|
| `Outcome` | record with 10 fields: suite, page, name, viewport, status, mismatch_percent, baseline_path, current_path, diff_path, error | `outcome.py` |
| `write_results` | `write_results(outcomes: list[Outcome], results_dir: str)` | `writer.py` |
| `build_report` | `build_report(results_dir: str, report_dir: str)` | `report.py` |

## `write_results` — stage 1

- creates `results_dir` (parents included) if absent
- per `Outcome`: stable `testCaseId`/`historyId` =
  `peeksy::{suite}::{page}::{name}[{viewport}]` — one history row per
  (suite, page, component, viewport); display name
  `{suite} / {page} / {name} [{viewport}]`; Allure suite label = the real
  site name
- attachments copied for non-None paths only (BROKEN outcomes omit missing
  images cleanly) as `<uuid>-attachment`
- status mapping: PASSED/FAILED = visual verdict, BROKEN = infrastructure;
  `statusDetails` carries the mismatch % when FAILED or the error when BROKEN
  — `mismatch_percent` is `None` for BROKEN, never a fake `0.0`
- does **not** clear prior artifacts — that is the runner's responsibility

## `build_report` — stage 2

- `shutil.which("allure")` guard → human-readable install error instead of a
  `FileNotFoundError` from subprocess
- canonical invocation:
  `["allure", "generate", <results_dir>, "--clean", "-o", <report_dir>]`
  with `check=True, capture_output=True`
