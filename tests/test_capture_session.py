"""Task 7 — contract + logic tests for the `peeksy.capture` cell.

Contract source: `peeksy/capture/CODEMANIFEST` (read-only). Entity
`CaptureSession` lives at `session.py` and is importable from the
`peeksy.capture` facade.

Contract tests come first (TDD): facade exposure and the exact method
signatures. Logic tests below run REAL Chromium against the `file://`
fixture page built by `tests/conftest.py::fixture_site` — determinism,
deep-link navigation, mask overlay, and idempotence are observable only
through an actual render.
"""

import inspect
from pathlib import Path

from PIL import Image

import peeksy.capture as capture_facade
from peeksy.capture import CaptureSession
from peeksy.compare import compare
from peeksy.config import Action, Component, Page, Viewport
from tests.conftest import fixture_site

MASK_GRAY = (128, 128, 128, 255)  # #808080 — the exact overlay color
VP = Viewport(width=1280, height=720)  # keyword-only Pydantic init


# --------------------------------------------------------------------------
# Contract tests — facade + method signatures
# --------------------------------------------------------------------------


def test_facade_exposes_capture_session() -> None:
    exported = set(capture_facade.__all__)
    assert {"CaptureSession"} <= exported
    assert inspect.isclass(capture_facade.CaptureSession)
    assert capture_facade.CaptureSession.__module__ == "peeksy.capture.session"


def test_capture_session_method_signatures_match_contract() -> None:
    methods = {
        name: inspect.signature(getattr(CaptureSession, name))
        for name in ("open", "open_page", "capture_component", "close")
    }
    params = {name: dict(sig.parameters) for name, sig in methods.items()}

    # open() / close() take nothing beyond self.
    assert list(params["open"]) == ["self"]
    assert list(params["close"]) == ["self"]

    assert list(params["open_page"]) == ["self", "page", "viewport"]
    assert params["open_page"]["page"].annotation is Page
    assert params["open_page"]["viewport"].annotation is Viewport
    assert methods["open_page"].return_annotation is None

    assert list(params["capture_component"]) == ["self", "component", "out_path"]
    assert params["capture_component"]["component"].annotation is Component
    assert params["capture_component"]["out_path"].annotation is str
    assert methods["capture_component"].return_annotation is str

    assert all(
        p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        for sig in params.values()
        for p in sig.values()
    )


def test_playwright_imports_stay_inside_capture_cell() -> None:
    # The contract pins Playwright to `peeksy/capture` — no other cell may import it.
    import peeksy

    root = Path(peeksy.__file__).parent
    offenders = [
        str(source.relative_to(root))
        for source in sorted(root.rglob("*.py"))
        if source.parent.name != "capture" and "playwright" in source.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"playwright leaked outside peeksy/capture: {offenders}"


# --------------------------------------------------------------------------
# Logic tests — real Chromium against the file:// fixture
# --------------------------------------------------------------------------


def test_open_and_capture_component_writes_png(tmp_path: Path) -> None:
    html = fixture_site(tmp_path / "site")
    session = CaptureSession()
    session.open()
    try:
        session.open_page(
            Page(name="home", url=html.as_uri(), wait_until="networkidle"),
            VP,
        )
        out_path = str(tmp_path / "header_1280x720.png")
        returned = session.capture_component(
            Component(name="header", selector="#header", viewports=[VP]),
            out_path,
        )
        assert returned == out_path
        with Image.open(out_path) as image:
            image.load()
            assert image.size[0] > 0
            assert image.size[1] > 0
    finally:
        session.close()


def test_open_action_navigates_mid_setup(tmp_path: Path) -> None:
    html = fixture_site(tmp_path / "site")
    session = CaptureSession()
    session.open()
    try:
        calls: list[str] = []
        real_goto = session.page.goto

        def spying_goto(url: str, **kwargs: object) -> object:
            calls.append(url)
            return real_goto(url, **kwargs)

        session.page.goto = spying_goto  # type: ignore[method-assign]
        session.open_page(
            Page(
                name="deep",
                url=None,
                setup=[
                    Action(kind="open", target=None, value=html.as_uri()),
                    Action(kind="click", target="#x"),
                ],
            ),
            VP,
        )
        assert calls == [html.as_uri()]
        assert session.page.url.startswith("file://")
    finally:
        session.close()


def test_determinism_survives_open_in_deep_link_setup(tmp_path: Path) -> None:
    """`open_page` injects the determinism CSS on `about:blank` in the
    deep-link flow, so the leading `open` used to discard it — every setup
    action after the navigation ran with animations and transitions live.
    The re-injection after `open`/`reload` keeps the invariant across the
    whole action list, not just at shot time."""
    html = fixture_site(tmp_path / "site")
    session = CaptureSession()
    session.open()
    try:
        session.open_page(
            Page(
                name="deep",
                url=None,
                setup=[Action(kind="open", target=None, value=html.as_uri())],
            ),
            VP,
        )
        injected = session.page.evaluate(
            "() => [...document.styleSheets].some(sheet => { try {"
            "return sheet.ownerNode.textContent.includes('peeksy') || "
            "sheet.ownerNode.textContent.includes('animation: none')"
            "} catch { return false } })"
        )
        assert injected is True
    finally:
        session.close()


def test_capture_is_idempotent_pixelmatch_clean(tmp_path: Path) -> None:
    html = fixture_site(tmp_path / "site")
    session = CaptureSession()
    session.open()
    try:
        page = Page(name="home", url=html.as_uri(), wait_until="networkidle")
        component = Component(name="header", selector="#header", viewports=[VP])
        session.open_page(page, VP)
        first = str(tmp_path / "first.png")
        second = str(tmp_path / "second.png")
        session.capture_component(component, first)
        session.capture_component(component, second)
        result = compare(first, second, str(tmp_path / "diffs"), threshold=0.1, tolerance=0.0)
        assert result.passed is True
        assert result.mismatch_percent == 0.0
    finally:
        session.close()


def test_masked_dynamic_region_stable_and_no_mask_leakage(tmp_path: Path) -> None:
    html = fixture_site(tmp_path / "site")
    session = CaptureSession()
    session.open()
    try:
        page = Page(name="home", url=html.as_uri(), wait_until="networkidle")
        header = Component(
            name="header",
            selector="#header",
            mask_selectors=[".timestamp"],
            viewports=[VP],
        )
        footer = Component(name="footer", selector="#footer", viewports=[VP])
        first_dir = tmp_path / "run1"
        second_dir = tmp_path / "run2"
        for out_dir in (first_dir, second_dir):
            out_dir.mkdir()
            session.open_page(page, VP)
            session.capture_component(header, str(out_dir / "header.png"))
            session.capture_component(footer, str(out_dir / "footer.png"))

        # Masked header: identical across two page loads (timestamp re-randomized).
        header_result = compare(
            str(first_dir / "header.png"),
            str(second_dir / "header.png"),
            str(tmp_path / "diffs"),
            threshold=0.1,
            tolerance=0.0,
        )
        assert header_result.passed is True
        assert header_result.mismatch_percent == 0.0

        # The overlay must not leak onto the footer captured right afterwards.
        assert not _has_pixel(str(first_dir / "footer.png"), MASK_GRAY)
        assert not _has_pixel(str(second_dir / "footer.png"), MASK_GRAY)
    finally:
        session.close()


def test_reload_setup_recaptures_deterministically(tmp_path: Path) -> None:
    html = fixture_site(tmp_path / "site")
    session = CaptureSession()
    session.open()
    try:
        page = Page(name="home", url=html.as_uri(), wait_until="networkidle")
        plain = Component(name="header", selector="#header", viewports=[VP])
        reloading = Component(
            name="header-reload",
            selector="#header",
            viewports=[VP],
            setup=[Action(kind="reload", target=None, value=None)],
        )
        session.open_page(page, VP)
        session.capture_component(plain, str(tmp_path / "plain.png"))
        session.capture_component(reloading, str(tmp_path / "reloaded.png"))
        result = compare(
            str(tmp_path / "plain.png"),
            str(tmp_path / "reloaded.png"),
            str(tmp_path / "diffs"),
            threshold=0.1,
            tolerance=0.0,
        )
        assert result.passed is True
        assert result.mismatch_percent == 0.0
    finally:
        session.close()


def test_close_is_idempotent(tmp_path: Path) -> None:
    html = fixture_site(tmp_path / "site")
    session = CaptureSession()
    session.open()
    session.open_page(
        Page(name="home", url=html.as_uri(), wait_until="networkidle"),
        VP,
    )
    session.close()
    session.close()  # second call must not raise


def test_locate_resolves_piercing_and_iframe_selectors(tmp_path: Path) -> None:
    # The SAME helper serves the component selector and every mask selector —
    # plain CSS, a shadow-piercing `a >> b`, and content inside an <iframe>.
    html = tmp_path / "site" / "index.html"
    html.parent.mkdir(parents=True)
    html.write_text(
        """<!DOCTYPE html><html><body>
        <my-widget></my-widget>
        <iframe id="frame" style="width: 300px; height: 60px; border: 0;"
                srcdoc='<div id="in-frame" style="width: 200px; height: 40px;">frame content</div>'>
        </iframe>
        <script>
          const shadow = document.querySelector("my-widget").attachShadow({mode: "open"});
          shadow.innerHTML = '<button class="save">save <span class="date">today</span></button>';
        </script>
        </body></html>""",
        encoding="utf-8",
    )
    session = CaptureSession()
    session.open()
    try:
        session.open_page(
            Page(name="home", url=html.as_uri(), wait_until="load"),
            VP,
        )
        # Piercing selector crosses the shadow boundary; masked the same way.
        widget = Component(
            name="widget",
            selector="my-widget >> button.save",
            mask_selectors=["my-widget >> .date"],
            viewports=[VP],
        )
        out_path = str(tmp_path / "widget.png")
        assert session.capture_component(widget, out_path) == out_path
        with Image.open(out_path) as image:
            image.load()
            assert image.size[0] > 0

        # Iframe selector routes through frame_locator.
        in_frame = Component(
            name="in-frame",
            selector="iframe#frame >>> #in-frame",
            viewports=[VP],
        )
        assert session.capture_component(in_frame, str(tmp_path / "frame.png")) != ""
        assert (tmp_path / "frame.png").exists()
    finally:
        session.close()


def test_mask_selector_matching_several_elements(tmp_path: Path) -> None:
    """A mask selector matching N elements masks ALL of them — not a crash.

    Regression: strict-mode `evaluate` aborted the capture on the second match,
    even though masking every timestamp/ad-slot is the normal masking case.
    """
    html = tmp_path / "site" / "index.html"
    html.parent.mkdir(parents=True)
    html.write_text(
        """<!DOCTYPE html><html><body>
        <div id="widget" style="width: 300px; height: 60px;">
          <span class="ts" style="display:inline-block;width:60px;height:20px">1:00</span>
          <span class="ts" style="display:inline-block;width:60px;height:20px">2:00</span>
          <span class="ts" style="display:inline-block;width:60px;height:20px">3:00</span>
        </div>
        </body></html>""",
        encoding="utf-8",
    )
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        widget = Component(
            name="widget",
            selector="#widget",
            mask_selectors=[".ts"],
            viewports=[VP],
        )
        out_path = str(tmp_path / "widget.png")
        session.capture_component(widget, out_path)
        # Every match carries the opaque overlay — all three became mask-gray.
        with Image.open(out_path) as image:
            raw = image.convert("RGBA").tobytes()
        needle = bytes(MASK_GRAY)
        gray = sum(1 for i in range(0, len(raw), 4) if raw[i : i + 4] == needle)
        assert gray >= 3 * 60 * 20
    finally:
        session.close()


def test_locate_routes_iframe_element_plain_css(tmp_path: Path) -> None:
    """Plain CSS targeting the <iframe> element itself must reach page.locator.

    Regression: keying the iframe branch on a literal `iframe` prefix parsed
    `iframe.ad` as frame+empty-inner and crashed in Playwright's selector
    parser. The `>>>` separator — not the prefix — is the iframe marker.
    """
    from peeksy.capture.session import locate

    html = tmp_path / "site" / "index.html"
    html.parent.mkdir(parents=True)
    html.write_text(
        """<!DOCTYPE html><html><body>
        <iframe class="ad" style="width: 200px; height: 50px;" src="about:blank"></iframe>
        </body></html>""",
        encoding="utf-8",
    )
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        assert locate(session.page, "iframe.ad").count() == 1
        assert locate(session.page, "iframe").count() == 1
        # The iframe form still routes through frame_locator.
        assert locate(session.page, "iframe.ad >>> body").count() == 1
    finally:
        session.close()


def test_component_setup_uses_page_wait_until(tmp_path: Path) -> None:
    """open/reload inside a component setup navigates with the PAGE's strategy.

    Regression: the component setup hardcoded networkidle, so a page configured
    `domcontentloaded` (live pages never reach networkidle) timed out on every
    component whose setup starts with reload.
    """
    html = fixture_site(tmp_path / "site")
    session = CaptureSession()
    session.open()
    try:
        page = Page(name="live", url=html.as_uri(), wait_until="domcontentloaded")
        component = Component(
            name="header-reload",
            selector="#header",
            viewports=[VP],
            setup=[Action(kind="reload", target=None, value=None)],
        )
        session.open_page(page, VP)
        session.capture_component(component, str(tmp_path / "reloaded.png"))
        # The stored strategy — not a hardcoded networkidle — reached reload.
        assert session._wait_until == "domcontentloaded"
        assert (tmp_path / "reloaded.png").exists()
    finally:
        session.close()


def _has_pixel(png_path: str, rgba: tuple[int, int, int, int]) -> bool:
    """Whether any pixel of the PNG is exactly `rgba` (the mask-gray scan).

    Exact by construction: RGBA `tobytes()` is 4 bytes per pixel, so a chunked
    comparison over 4-byte boundaries can only match a whole pixel — unlike a
    plain substring test, which could straddle two adjacent pixels.
    """
    needle = bytes(rgba)
    with Image.open(png_path) as image:
        raw = image.convert("RGBA").tobytes()
    return any(raw[i : i + 4] == needle for i in range(0, len(raw), 4))
