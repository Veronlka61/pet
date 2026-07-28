# cli — Running the peeksy CLI

## Domain

How to invoke the `peeksy` commands from the shell. Target audience: the end user and CI.

## Commands

```bash
# Capture baselines for all pages/components
peeksy generate --config sites/example.com

# Capture baselines for selected pages/components (both flags repeatable)
peeksy generate --config sites/example.com --page home --component header --component sidebar

# Compare against baselines; exit code != 0 on any regression (CI-friendly)
peeksy test --config sites/example.com
peeksy test --config sites/example.com --page home --component header

# Build the browsable Allure HTML report
peeksy report --config sites/example.com
```

- `--config` takes the site folder (or its `suite.yml`).
- `--page` and `--component` are repeatable and combine as an AND; omit them to process everything.
- `test` is read-only on baselines, prints a one-line summary, and raises `typer.Exit` with a non-zero code on any regression or BROKEN.
- Infrastructure failures are reported as `BROKEN`, not as visual regressions.
- `report` requires the external `allure` CLI (Java/JDK) on PATH; if it is missing, peeksy prints a clear install message instead of a traceback.