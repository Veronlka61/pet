"""Shared pytest fixtures for the peeksy test suite.

Two responsibilities:

- Export the Chromium shared-library prefix (unpacked from Debian packages into
  a local directory, since this host gives us no root) through LD_LIBRARY_PATH
  BEFORE any Playwright subprocess is spawned. Chromium on Linux reads
  LD_LIBRARY_PATH at exec time, so setting it here in conftest (imported by
  pytest before any test module) is early enough.
- Make fonts renderable at all. This host has no `/usr/share/fonts`, so
  fontconfig's default `<dir>` list finds nothing and Chromium rasterizes NO
  text — every glyph-based diff silently collapses to 0.0%. When that is the
  case, point FONTCONFIG_FILE at a generated config that declares the DejaVu
  fonts unpacked under `/tmp/chromium-libs`.
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

# Fonts unpacked next to the Chromium libs. Without an explicit FONTCONFIG_FILE
# that names this directory, no font is findable and text does not render.
_BUNDLED_FONTS = "/tmp/chromium-libs/usr/share/fonts"
_FONTCONFIG_DIRS = ("/usr/share/fonts", "/usr/local/share/fonts")
# fontconfig's built-in defaults, minus the ones that do not exist here.
_XDG_DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def _host_has_fonts() -> bool:
    """Whether any default fontconfig directory actually contains a font."""
    candidates = [Path(d) for d in (*_FONTCONFIG_DIRS, _XDG_DATA_HOME + "/fonts")]
    return any(
        any(font.is_file() for font in directory.rglob("*.[ot]tf"))
        for directory in candidates
        if directory.is_dir()
    )


def _activate_bundled_fonts() -> None:
    """Generate a minimal fonts.conf over the bundled fonts and export it."""
    config_dir = Path(f"/tmp/peeksy-test-fontconfig-{os.getuid()}")
    (config_dir / "cache").mkdir(parents=True, exist_ok=True)
    (config_dir / "fonts.conf").write_text(
        '<?xml version="1.0"?>\n'
        "<fontconfig>\n"
        f"  <dir>{_BUNDLED_FONTS}</dir>\n"
        f"  <cachedir>{config_dir / 'cache'}</cachedir>\n"
        "</fontconfig>\n",
        encoding="utf-8",
    )
    os.environ["FONTCONFIG_FILE"] = str(config_dir / "fonts.conf")


if (
    not os.environ.get("FONTCONFIG_FILE")
    and Path(_BUNDLED_FONTS).is_dir()
    and not _host_has_fonts()
):
    _activate_bundled_fonts()

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
             border-top: 1px solid #eeeeee; color: #1a3a5c; }}
  .timestamp {{ display: inline-block; width: 240px; overflow: hidden;
                vertical-align: bottom; }}
  .header-strip {{ width: 100%; height: 40px; margin-top: 4px;
                   background: #d6d6d6; border: 1px solid #b0b0b0; }}
  #x {{ width: 40px; height: 40px; background: #dddddd; }}
  {extra_css}
</style>
</head>
<body>
  <div id="header"{header_attrs}>header <span class="timestamp">{timestamp}</span>
    <div class="header-strip"{strip_attrs}></div>
  </div>
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
    header_strip_style: str = "",
    media_shift: bool = False,
    randomize_timestamp: bool = False,
) -> Path:
    """Write the `index.html` fixture page into `target_dir` and return its path.

    The page carries `#header` with a `.timestamp` span and a full-width
    `.header-strip`, a static `#footer`, and an `#x` click target. Tests mutate
    the returned file ON DISK between generate and test runs — rewriting it
    through this factory with different keyword arguments is the intended way.

    `header_style` / `header_strip_style` are inlined as style attributes (used
    to force a regression); `media_shift` adds a `@media (max-width: 500px)`
    rule that shifts `.header-strip` by 2px on narrow viewports only;
    `randomize_timestamp` fills the span with a fresh `Date.now()` value on
    every load, turning it into the dynamic region the masking tests mask.

    Two rendering facts shaped this fixture, both verified against a real
    Chromium on this host:

    - `locator.screenshot()` crops by the element's TRANSFORMED box, so a
      `translateY` on `#header` itself is invisible in the shot. The shift
      therefore targets `.header-strip` INSIDE the header, which really moves
      within the fixed crop.
    - Antialiased text can hit exactly #808080 — the mask gray the leakage
      scan looks for. The footer text is therefore a blue that no test can
      mistake for a mask overlay, and only gray-free regions are scanned.

    The timestamp span is a FIXED-WIDTH clipped box: its mask overlay covers
    exactly the same rectangle on every load, so masking it really does remove
    the variation (a content-sized span would resize its own mask and leak).
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    extra_css = (
        "@media (max-width: 500px) { .header-strip { transform: translateY(2px); } }"
        if media_shift
        else ""
    )
    header_attrs = f' style="{header_style}"' if header_style else ""
    strip_attrs = f' style="{header_strip_style}"' if header_strip_style else ""
    html = _FIXTURE_TEMPLATE.format(
        extra_css=extra_css,
        header_attrs=header_attrs,
        strip_attrs=strip_attrs,
        timestamp="",
        extra_body=_RANDOMIZE_SCRIPT if randomize_timestamp else "",
    )
    out = target_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


__all__: list[str] = ["fixture_site"]
