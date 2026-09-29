# peeksy

Playwright-based visual regression CLI. `peeksy` reads a YAML site configuration,
opens pages in headless Chromium, locates UI components by CSS selector and takes
deterministic element-level screenshots.

- `peeksy generate` — capture baselines per (page, component, viewport)
- `peeksy test` — re-capture, compare via pixelmatch against the baselines,
  write Allure results; exit code 0 only when every component PASSED
- `peeksy report` — build the browsable Allure HTML report

One Allure test case is produced per (page, component, viewport) — with
baseline/current/diff attachments, stable history IDs, and a clear separation
between **FAILED** (visual regression) and **BROKEN** (infrastructure failure).

## Pipeline

```
peeksy/cli (Typer) ──load_config──► peeksy/config (Pydantic models)
        │                                   │
        └──────────► peeksy/runner ─────────┼──► peeksy/capture (Playwright)
                     (orchestration)        ├──► peeksy/compare (pixelmatch)
                                            └──► peeksy/reporting (Allure)
```

The package is six cells (packages), each with a read-only `CODEMANIFEST`
contract; see the [per-cell API reference](cells/config.md).

## Install

```bash
uv sync                                   # install deps (creates uv.lock)
uv run playwright install chromium        # the browser, once
```

`peeksy report` additionally needs the external `allure` CLI (Java/JDK):

```bash
brew install allure     # or sdkman; optional — only the report stage uses it
```

## Where to go next

- [CLI Usage](usage.md) — commands, flags, exit codes
- [Configuration](configuration.md) — the site folder layout and concepts
- [YAML DSL](yaml-dsl.md) — exhaustive field-by-field format reference
- [Example](example.md) — a runnable example site
