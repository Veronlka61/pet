# Allure — Programmatic Results & HTML Report (without pytest)

## Domain

Emitting **Allure Report** result data from a standalone CLI — i.e. *without*
pytest or `allure-pytest` — and building the browsable HTML report. Target
audience: the cell that turns component comparison outcomes into Allure test
results and renders the report.

This file covers *how to produce Allure output*. It does not describe the cell
contract.

---

## Two stages

1. **Write result JSON + attachments** into an Allure *results directory* — one
   test result file per component check, plus the baseline/current/diff PNGs as
   attachments.
2. **Build the HTML report** from that directory using the external `allure`
   CLI (`allure generate` / `allure open`).

Stage 1 is pure Python; Stage 2 shells out to the `allure` binary.

---

## Dependencies

- Python: `allure-python-commons` provides the typed result model. Optionally
  skip it and hand-write the JSON dicts (the Allure v2 schema is stable) — see
  "Format reference" below.
- System: the **`allure` CLI** must be on `PATH` to render HTML. It is Java-based
  → a JDK is required. Install via the package manager (`brew install allure`,
  `sdkman`, etc.).

```bash
uv add allure-python-commons
```

---

## Stage 1 — model a component check as a result

Each component check → one `<uuid>-result.json` in the results dir. Use the
commons model so statuses/labels stay correct:

```python
import uuid, time
from pathlib import Path
import json
from allure_commons.model2 import (
    TestResult, Label, Attachment, Status, TestStepResult,
)

results_dir = Path("build/allure-results")
results_dir.mkdir(parents=True, exist_ok=True)


def write_component_result(component_name: str, passed: bool,
                           baseline_png: Path, current_png: Path,
                           diff_png: Path | None, mismatch_percent: float):
    case_id = f"peeksy::{component_name}"
    # Attachments: copy/write each PNG into the results dir under a uuid name,
    # then reference that name in Attachment.source.
    attachments = [
        Attachment(source=copy_attachment(results_dir, baseline_png),
                   name="baseline", type="image/png"),
        Attachment(source=copy_attachment(results_dir, current_png),
                   name="current", type="image/png"),
    ]
    if diff_png is not None:
        attachments.append(
            Attachment(source=copy_attachment(results_dir, diff_png),
                       name="diff", type="image/png"))

    result = TestResult(
        uuid=str(uuid.uuid4()),
        name=component_name,
        historyId=case_id,
        testCaseId=case_id,
        status=Status.PASSED if passed else Status.FAILED,
        start=int(time.time() * 1000),
        stop=int(time.time() * 1000),
        labels=[
            Label(name="suite", value="peeksy"),
            Label(name="feature", value="visual-regression"),
            Label(name="severity", value="critical" if not passed else "normal"),
        ],
        attachments=attachments,
        # Put the verdict in the status detail so it shows in the report body.
        statusDetails=StatusDetails(
            message=f"mismatch={mismatch_percent:.2f}%") if not passed else None,
    )
    (results_dir / f"{result.uuid}-result.json").write_text(
        json.dumps(result.to_dict() if hasattr(result, "to_dict") else
                   as_allure_dict(result), default=str))
```

`copy_attachment` writes the PNG into the results dir as `<new-uuid>-attachment`
and returns that filename — the report resolves an attachment by matching its
`source` to a file in the results dir.

### Conventions

- **One test result per `(component, viewport)`** — `name = f"{component} [{WxH}]"`,
  so the report lists each viewport as its own row.
- **`historyId` / `testCaseId`** must be stable across runs (derive from the
  component name) so Allure trends and history stitch runs together.
- **`Status.FAILED`** = regression (mismatch above tolerance). Use
  **`Status.BROKEN`** for capture errors (page didn't load, selector missing) —
  those are infrastructure failures, not visual regressions.
- Attach the **diff image only when the check failed.**

---

## Stage 2 — build the HTML report

```python
import subprocess

def build_report(results_dir: str, report_dir: str):
    subprocess.run(["allure", "generate", "--clean",
                    "-o", report_dir, results_dir], check=True)

def open_report(report_dir: str):
    subprocess.run(["allure", "open", "-p", "0", report_dir])  # 0 = random free port
```

`--clean` wipes a stale report dir first. `allure open` serves the report on a
local HTTP server (random port) so attachments and history render correctly —
opening the HTML straight from disk breaks some browsers.

---

## Format reference (hand-written fallback)

If the commons model churns, write the dicts directly — Allure reads them the
same. Minimal test result:

```json
{
  "uuid": "<uuid>",
  "historyId": "peeksy::header",
  "name": "header [1280x720]",
  "status": "failed",
  "statusDetails": { "message": "mismatch=2.34%" },
  "start": 1719200000000,
  "stop": 1719200001234,
  "labels": [
    {"name": "suite", "value": "peeksy"},
    {"name": "feature", "value": "visual-regression"}
  ],
  "attachments": [
    {"name": "baseline", "type": "image/png", "source": "<uuid>-attachment"},
    {"name": "current",  "type": "image/png", "source": "<uuid>-attachment"},
    {"name": "diff",     "type": "image/png", "source": "<uuid>-attachment"}
  ]
}
```

Each attachment `source` is a file in the results dir containing the raw PNG
bytes. Containers (`*-container.json`) are optional for a flat suite and can be
omitted.

---

## Contract for the reporting cell

- Input: a list of per-component outcomes (passed, mismatch %, image paths),
  the results dir, and the report dir.
- Output: the populated results dir (Stage 1) and, on request, a built HTML
  report (Stage 2).
- Must be append-safe across `generate` and `test` invocations — clear or version
  the results dir deliberately, never silently mix runs.