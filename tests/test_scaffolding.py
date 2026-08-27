"""Task 1 scaffolding smoke tests.

These verify the project skeleton created by Task 1: root package importable,
facade shape, and dependency availability. Contract-level tests land with
Tasks 2-9.
Chromium on this host needs shared libs unpacked from debs (no root access);
conftest.py exports the local prefix through LD_LIBRARY_PATH before any launch.
"""

import importlib


def test_root_package_importable_with_empty_facade() -> None:
    peeksy = importlib.import_module("peeksy")
    assert peeksy.__all__ == []


def test_pixelmatch_pil_entry_point_available() -> None:
    from pixelmatch.contrib.PIL import pixelmatch  # noqa: F401


def test_runtime_dependencies_importable() -> None:
    import allure_commons  # noqa: F401
    import pydantic  # noqa: F401
    import typer  # noqa: F401
    import yaml  # noqa: F401
    from PIL import Image  # noqa: F401
    from playwright.sync_api import sync_playwright  # noqa: F401


def test_playwright_chromium_browser_installed(tmp_path) -> None:
    """Chromium was downloaded via `playwright install chromium` (Task 1 gate).

    Launches a real browser, loads a file:// page (the fixture transport the
    capture tests use), and asserts the page actually PAINTS — so a host that
    can launch but not render (missing fonts/compositor deps) fails here, not
    in ten capture tests.
    """
    from playwright.sync_api import sync_playwright

    html = tmp_path / "smoke.html"
    html.write_text(
        '<body style="margin:0">'
        '<div id="probe" style="background:#ff0000;width:100px;height:100px"></div>'
        "</body>",
        encoding="utf-8",
    )
    shot = tmp_path / "smoke.png"

    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(device_scale_factor=1).new_page()
        page.goto(html.as_uri())
        page.wait_for_timeout(200)
        page.screenshot(path=str(shot))
        browser.close()
    finally:
        p.stop()

    from PIL import Image

    img = Image.open(shot).convert("RGB")
    painted = any(
        r > 200 and g < 100 and b < 100 for _, (r, g, b) in img.getcolors(maxcolors=200000)
    )
    assert painted, "Chromium launched but did not paint the probe div"
