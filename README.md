# peeksy

Playwright-based visual regression CLI.

- `peeksy generate` — capture deterministic Playwright baselines per (page, component, viewport)
- `peeksy test` — re-capture, compare via pixelmatch against baselines, write Allure results
- `peeksy report` — build the browsable Allure HTML report

Contract source: the six `peeksy/*/CODEMANIFEST` files (read-only, authoritative).

## Development

```bash
uv sync                                   # install deps (creates uv.lock)
uv run playwright install chromium        # download the browser once
uv run pytest                             # full test suite
uv run ruff check peeksy tests            # lint
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

