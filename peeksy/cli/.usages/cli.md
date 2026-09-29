# cli — Running the peeksy CLI

## Domain

How to invoke the `peeksy` commands from the shell. Target audience: the end user and CI.

## Commands

```bash
# Capture baselines for all pages/components — from the project root
# (--config/-c defaults to ./peeksy.yml, the project-root suite file)
peeksy generate
peeksy generate -c ./peeksy.yml          # same, explicit

# Or point at a site folder / its suite.yml explicitly
peeksy generate --config sites/example.com

# Capture baselines for selected pages/components (both flags repeatable)
peeksy generate --page home --component header --component sidebar
peeksy generate --config sites/example.com --page home --component header --component sidebar

# Compare against baselines; exit code != 0 on any regression (CI-friendly)
peeksy test
peeksy test --config sites/example.com --page home --component header

# Build the browsable Allure HTML report
peeksy report --config sites/example.com
```

- `--config` (short `-c`) defaults to `./peeksy.yml` — the suite file in the project root
  (one repository = one site; `pages/` and the artifact paths resolve next to it).
  An explicitly passed `*.yml` path is the suite file directly; a folder argument falls
  back to looking up `suite.yml` inside it.
- `--page` and `--component` are repeatable and combine as an AND; omit them to process everything.
- An unknown `--page`/`--component` value is an error (exit 1): peeksy names every unknown
  value and touches nothing — a typo never becomes a green run comparing fewer components.
- `test` is read-only on baselines, prints a one-line summary, and raises `typer.Exit` with a non-zero code on any regression or BROKEN.
- Infrastructure failures are reported as `BROKEN`, not as visual regressions.
- `report` requires the external `allure` CLI (Java/JDK) on PATH; if it is missing, peeksy prints a clear install message instead of a traceback.