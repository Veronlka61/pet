# CLAUDE.md

## Project

peeksy — Playwright-based visual regression CLI (`generate` baselines / `test` compare /
`report` Allure HTML). Python 3.10+, uv-managed.

## Architecture — six cells, contract-first

The package is six cells (packages) under `peeksy/`: `config` → `compare` / `reporting` →
`capture` → `runner` → `cli`. Each cell has:

- `CODEMANIFEST` — the **read-only, authoritative contract**. If code and CODEMANIFEST
  disagree, fix the implementation — never the contract.
- `.usages/<cell>.md` — consumer-facing docs for that cell.
- `__init__.py` — the facade; every contract entity is re-exported and listed in `__all__`.

Import direction is leaves → root (no cycles): `capture` imports only from `config`;
`runner` from `config`/`capture`/`compare`/`reporting`; `cli` from `config`/`runner`.
**Playwright never leaks outside `peeksy/capture`** (a test enforces this).

## Commands

```bash
uv sync                                   # install deps
uv run playwright install chromium        # browser, once
uv run pytest                             # full suite
uv run ruff check peeksy tests            # lint
uv run ruff format --check peeksy tests   # formatting
uv run peeksy --help                      # console-script smoke
```

## Conventions

- Exit codes: `test` exits 0 only when every selected component PASSED; FAILED (visual
  regression) and BROKEN (infrastructure: missing baseline, selector missing, unreadable
  image) both exit 1. `test` never aborts on capture errors — they become BROKEN outcomes.
- The CLI never calls `sys.exit` — always `raise typer.Exit(code=...)` so pytest can
  intercept it. One shared config-error handler prints human-readable messages (no
  tracebacks) for `ValidationError`/`YAMLError`/missing paths.
- Artifact paths are page-namespaced: `{baseline_path}/{page}/{name}_{WxH}.png`,
  `{results_path}/{page}/{name}_{WxH}.current.png` / `.diff.png`.
- Allure `testCaseId`/`historyId` = `peeksy::{suite}::{page}::{name}[{viewport}]` — one
  history row per (suite, page, component, viewport).
- `Viewport` is a Pydantic model, hence unhashable — viewport dedupe is an ordered
  first-seen list scan, never `set` iteration.
- Masking = opaque gray `::after` overlay, never `display: none` (keeps the layout box).

## Test environment notes

- Tests run real Chromium over `file://` fixtures (`fixture_site` in `tests/conftest.py`);
  on minimal hosts `data:` URLs may not paint.
- `tests/conftest.py` re-exports `/tmp/chromium-libs/*` via `LD_LIBRARY_PATH` and sets up
  a fontconfig fallback when it finds them — see the README host note for how that prefix
  is produced on no-root hosts.
