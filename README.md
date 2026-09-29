# peeksy

Playwright-based visual regression CLI.

- `peeksy generate` — capture deterministic Playwright baselines per (page, component, viewport)
- `peeksy test` — re-capture, compare via pixelmatch against baselines, write Allure results
- `peeksy report` — build the browsable Allure HTML report

Contract source: the six `peeksy/*/CODEMANIFEST` files (read-only, authoritative).

## Usage

```
peeksy generate|test [--config PATH] [--page NAME]... [--component NAME]...
peeksy report [--config PATH]
```

- `--config` / `-c` — suite file or site folder. Default `./peeksy.yml`; a folder
  looks up its `suite.yml`.
- `--page`, `--component` — repeatable name filters, combined as AND. `test`
  applies them to decide which baselines to re-capture and compare. Any filter
  value no page/component answers to is an error (exit 1) — a typo must never
  become a green run that silently compares fewer components.
- Exit codes: `test` exits 0 only when every selected component PASSED; any
  FAILED (visual regression) or BROKEN (infrastructure failure — missing
  baseline, selector not found, unreadable image) outcome exits 1.

Configuration is a site folder: `suite.yml` plus `pages/<page>/page.yml` and
sibling `<component>.yml` files. Full reference: `peeksy/config/.usages/config.md`.

```yaml
# peeksy.yml (or sites/example.com/suite.yml)
name: example.com
baseline_path: baselines   # relative paths resolve against the site folder
results_path: results
report_path: report
threshold: 0.1             # per-pixel color sensitivity, (0..1)
tolerance: 0.5             # allowed mismatch %, (0..100]
```

```yaml
# pages/home/page.yml
url: https://example.com/
wait_until: networkidle    # or domcontentloaded / load for live pages
```

```yaml
# pages/home/header.yml
selector: "#header"
mask_selectors: [".timestamp"]  # dynamic regions covered with a gray overlay
viewports: [{width: 1280, height: 720}]
```

## Requirements

- Python >= 3.10
- Chromium — `peeksy` drives it via Playwright; `generate` and `test` need it
- `allure` CLI + a JDK — only for `peeksy report` (optional for the other two)

## Development

```bash
uv sync                                   # install deps (creates uv.lock)
uv run playwright install chromium        # download the browser once
uv run pytest                             # full test suite
uv run ruff check peeksy tests            # lint
```

### Docs

```bash
uv sync --group docs                      # mkdocs + mkdocs-material
uv run mkdocs serve                       # live preview at http://127.0.0.1:8000
uv run mkdocs build --strict              # validate + build (site/ by default)
```

### Host note: Chromium shared libraries (no-root environments)

On hosts without root, `playwright install chromium` downloads the browser but
cannot `apt-get install` its shared libraries. Unpack them into a local prefix
instead and export it before running tests:

```bash
apt-get download libglib2.0-0 libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
  libdbus-1-3 libcups2 libxcb1 libxkbcommon0 libasound2 libgbm1 libx11-6 \
  libxext6 libcairo2 libpango-1.0-0 libxcomposite1 libxdamage1 libxfixes3 \
  libxrandr2 libatspi2.0-0 libxi6 libfreetype6 libxcb-render0 libxcb-shm0 \
  libdrm2 libwayland-server0 libpixman-1-0 libfontconfig1 fonts-dejavu-core
for f in *.deb; do dpkg-deb -x "$f" /tmp/chromium-libs; done

export LD_LIBRARY_PATH="/tmp/chromium-libs/lib/aarch64-linux-gnu:\
/tmp/chromium-libs/usr/lib/aarch64-linux-gnu:/tmp/chromium-libs/usr/lib"
```

`tests/conftest.py` re-exports this prefix automatically when it finds it, so
plain `pytest` works too. Use `file://` fixtures (see `fixture_site` in
`tests/conftest.py`) — on minimal hosts `data:` URLs may not paint.

