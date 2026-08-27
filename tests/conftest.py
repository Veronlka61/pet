"""Shared pytest fixtures for the peeksy test suite.

Two responsibilities:

- Export the Chromium shared-library prefix (unpacked from Debian packages into
  a local directory, since this host gives us no root) through LD_LIBRARY_PATH
  BEFORE any Playwright subprocess is spawned. Chromium on Linux reads
  LD_LIBRARY_PATH at exec time, so setting it here in conftest (imported by
  pytest before any test module) is early enough.
- `fixture_site` — the file:// HTML fixture factory used by the capture cell
  tests (Task 7) and the integration tests (Task 10).
"""

import os
from pathlib import Path

# Local Chromium shared-library prefix (no root on this host: debs unpacked,
# not installed). Prepend every lib dir that actually exists.
_CHROMIUM_LIB_DIRS = [
    "/tmp/chromium-libs/lib/aarch64-linux-gnu",
    "/tmp/chromium-libs/usr/lib/aarch64-linux-gnu",
    "/tmp/chromium-libs/usr/lib",
]

_lib_dirs = [d for d in _CHROMIUM_LIB_DIRS if Path(d).is_dir()]
if _lib_dirs:
    _existing = os.environ.get("LD_LIBRARY_PATH", "")
    if not all(d in _existing.split(":") for d in _lib_dirs):
        os.environ["LD_LIBRARY_PATH"] = ":".join([*_lib_dirs, _existing]).rstrip(":")

_FIXTURE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>peeksy fixture</title>
<style>
  body {{ margin: 0; font-family: sans-serif; background: #ffffff; }}
  #header, #footer {{ padding: 16px; box-sizing: border-box; }}
  #header {{ width: 100%; height: 120px; background: #f0f0f0;
             border-bottom: 1px solid #cccccc; }}
  #footer {{ width: 100%; height: 80px; background: #fafafa;
             border-top: 1px solid #eeeeee; }}
  .timestamp {{ display: inline-block; min-width: 120px; }}
  #x {{ width: 40px; height: 40px; background: #dddddd; }}
  {extra_css}
</style>
</head>
<body>
  <div id="header"{header_attrs}>header <span class="timestamp">{timestamp}</span></div>
  <div id="footer">footer — static content</div>
  <div id="x"></div>
{extra_body}
</body>
</html>
"""

# Randomizes .timestamp on every load — the "dynamic region" tests rely on it.
_RANDOMIZE_SCRIPT = """<script>
  document.querySelector(".timestamp").textContent =
    String(Date.now()) + "-" + Math.random().toString(36).slice(2, 10);
</script>"""


def fixture_site(
    target_dir: Path,
    *,
    header_style: str = "",
    media_shift: bool = False,
) -> Path:
    """Write the `index.html` fixture page into `target_dir` and return its path.

    The page carries `#header` with a `.timestamp` span randomized by JS on
    every load, a static `#footer`, and an `#x` click target. Tests mutate the
    returned file ON DISK between generate and test runs.

    `header_style` is inlined as a style attribute on `#header` (used to force
    a regression); `media_shift` adds a `@media (max-width: 500px)` rule that
    shifts `#header` by 2px on narrow viewports only.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    extra_css = (
        "@media (max-width: 500px) { #header { transform: translateY(2px); } }"
        if media_shift
        else ""
    )
    header_attrs = f' style="{header_style}"' if header_style else ""
    html = _FIXTURE_TEMPLATE.format(
        extra_css=extra_css,
        header_attrs=header_attrs,
        timestamp="",
        extra_body=_RANDOMIZE_SCRIPT,
    )
    out = target_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


__all__: list[str] = ["fixture_site"]
