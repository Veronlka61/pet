# Cell: cli

`peeksy.cli` — Typer facade for the peeksy commands. Owns no capture or
comparison logic: it loads the config and delegates to the runner.

- **Contract:** [`peeksy/cli/CODEMANIFEST`](https://github.com/Veronlka61/pet/tree/main/peeksy/cli)
- **Depends on:** [`config`](config.md), [`runner`](runner.md)

## API

| Entity | Signature | Location |
|---|---|---|
| `generate` | `generate(config, page, component)` | `app.py` |
| `test` | `test(config, page, component)` | `app.py` |
| `report` | `report(config)` | `app.py` |
| `main` | `main()` — console-script entry point | `app.py` |

Options: `--config`/`-c` (default `./peeksy.yml`), repeatable `--page` and
`--component` combined as AND. The facade also exports the module-level
Typer `app` used by tests (CliRunner) — intentionally not a contract entity.

## Error policy

- ONE shared handler covers every configuration error path —
  `pydantic.ValidationError`, `yaml.YAMLError`, `FileNotFoundError`/
  `NotADirectoryError` — printing a human-readable message (no Python
  traceback) and exiting 1; shared by all three commands
- the runner's unknown-filter `ValueError` surfaces through the same
  handler
- `test` prints a one-line summary and `raise typer.Exit(code=exit_code)`
  — **never `sys.exit`**, so pytest can intercept it
- `report` catches the missing-allure `RuntimeError` and a failing allure
  subprocess, printing install hints / the allure stderr respectively
