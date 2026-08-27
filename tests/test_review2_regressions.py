"""Second-review regressions — each test pins one defect found in review.

Run through pytest (not a bare script) so `tests/conftest.py` exports the
Chromium library/font environment these browser-driven cases need.
"""

from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from peeksy.capture import CaptureSession
from peeksy.compare import compare
from peeksy.config import Action, Component, Page, Suite, Viewport
from tests.conftest import fixture_site

VP = Viewport(width=1280, height=720)
MASK_GRAY = (128, 128, 128, 255)

# A masked element with an absolutely-positioned child: forcing `position:
# relative` on the parent re-anchors that child — the exact false diff the
# leaked inline style caused.
_ABS_CHILD_HTML = """<!DOCTYPE html><html><body style="margin:0">
<div id="holder" style="width:300px; height:80px; background:#eeeeee;">
  <span class="ts" style="display:inline-block; width:120px; height:30px;">time</span>
  <span class="badge" style="position:absolute; left:240px; top:20px; width:40px;
                               height:30px; background:#333333;"></span>
</div>
<div id="panel" style="width:300px; height:120px; background:#fafafa;">
  <div id="holder2" style="width:300px; height:80px; background:#eeeeee;">
    <span class="ts2" style="display:inline-block; width:120px; height:30px;">time</span>
    <span class="badge2" style="position:absolute; left:240px; top:20px; width:40px;
                                 height:30px; background:#333333;"></span>
  </div>
</div>
</body></html>"""


def _write_page(tmp_path: Path, body: str) -> Path:
    html = tmp_path / "index.html"
    html.parent.mkdir(parents=True, exist_ok=True)
    html.write_text(body, encoding="utf-8")
    return html


# --------------------------------------------------------------------------
# Mask teardown — no inline `position` leakage onto later captures
# --------------------------------------------------------------------------


def test_unmask_restores_inline_position(tmp_path: Path) -> None:
    """Regression: `_MASK_OFF` removed only the class, leaving the inline
    `position: relative` that `_MASK_ON` had injected."""
    html = _write_page(tmp_path, _ABS_CHILD_HTML)
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        session.capture_component(
            Component(name="masked", selector="#holder", mask_selectors=[".ts"], viewports=[VP]),
            str(tmp_path / "masked.png"),
        )
        state = session.page.evaluate(
            """() => {
                const el = document.querySelector('.ts');
                return {
                    position: getComputedStyle(el).position,
                    inline: el.getAttribute('style') ?? '',
                    dataset: Object.keys(el.dataset),
                    className: el.className,
                };
            }"""
        )
        # The fixture's `.ts` is position:static and carries no inline position.
        assert state["position"] == "static", f"leaked position: {state['position']!r}"
        assert "position" not in state["inline"], f"leaked inline style: {state['inline']!r}"
        assert state["dataset"] == []
        assert "peeksy-mask" not in state["className"]
    finally:
        session.close()


def test_mask_leak_does_not_shift_later_component(tmp_path: Path) -> None:
    """Regression: the leaked `position: relative` re-anchored absolutely
    positioned descendants of a masked element, so a component captured after
    any masked sibling differed from the same component on a pristine page."""
    html = _write_page(tmp_path, _ABS_CHILD_HTML)
    session = CaptureSession()
    session.open()
    try:
        page = Page(name="home", url=html.as_uri(), wait_until="load")
        masked = Component(
            name="masked", selector="#holder", mask_selectors=[".ts"], viewports=[VP]
        )
        clean = Component(name="clean", selector="#holder2", viewports=[VP])

        session.open_page(page, VP)
        session.capture_component(masked, str(tmp_path / "r1_masked.png"))
        session.capture_component(clean, str(tmp_path / "r1_clean.png"))

        # Same component on a freshly loaded page: nothing was ever masked.
        session.open_page(page, VP)
        session.capture_component(clean, str(tmp_path / "r2_clean.png"))

        result = compare(
            str(tmp_path / "r1_clean.png"),
            str(tmp_path / "r2_clean.png"),
            str(tmp_path / "diffs"),
            threshold=0.1,
            tolerance=0.0,
        )
        assert result.passed is True
        assert result.mismatch_percent == 0.0
    finally:
        session.close()


def test_unmask_preserves_user_inline_position(tmp_path: Path) -> None:
    """An element the site itself positioned inline must not be clobbered."""
    body = """<!DOCTYPE html><html><body style="margin:0">
<div id="holder" style="width:300px; height:80px; background:#eeeeee;">
  <span class="ts" style="position:absolute; top:10px; left:10px; width:120px;
                          height:30px;">time</span>
</div>
</body></html>"""
    html = _write_page(tmp_path, body)
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        session.capture_component(
            Component(name="masked", selector="#holder", mask_selectors=[".ts"], viewports=[VP]),
            str(tmp_path / "masked.png"),
        )
        state = session.page.evaluate(
            """() => {
                const el = document.querySelector('.ts');
                return {
                    position: getComputedStyle(el).position,
                    top: el.style.top,
                    left: el.style.left,
                    className: el.className,
                    dataset: Object.keys(el.dataset),
                };
            }"""
        )
        assert state["position"] == "absolute"
        assert state["top"] == "10px" and state["left"] == "10px"
        assert "peeksy-mask" not in state["className"]
        assert state["dataset"] == []
    finally:
        session.close()


# --------------------------------------------------------------------------
# Iframe components — determinism/mask CSS must reach the frame
# --------------------------------------------------------------------------


def test_mask_inside_iframe_applies_overlay(tmp_path: Path) -> None:
    """Regression: the overlay style was injected into the main frame only, so
    a `frame >>> inner` mask selector added a class no CSS could reach."""
    body = """<!DOCTYPE html><html><body style="margin:0">
<iframe id="frame" style="width:300px; height:80px; border:0;"
        srcdoc='<div id="in-frame" style="width:280px; height:60px; background:#eeeeee;">
                  <span id="clock" style="display:inline-block; width:120px; height:30px;">12:00</span>
                </div>'>
</iframe>
</body></html>"""
    html = _write_page(tmp_path, body)
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        component = Component(
            name="in-frame",
            selector="iframe#frame >>> #in-frame",
            mask_selectors=["iframe#frame >>> #clock"],
            viewports=[VP],
        )
        out_path = str(tmp_path / "frame.png")
        session.capture_component(component, out_path)

        with Image.open(out_path) as image:
            image.load()
            raw = image.convert("RGBA").tobytes()
        needle = bytes(MASK_GRAY)
        gray = sum(1 for i in range(0, len(raw), 4) if raw[i : i + 4] == needle)
        # The 120x30 clock region must be covered by the opaque overlay.
        assert gray >= 120 * 30, f"mask overlay missing inside iframe: {gray} gray pixels"
    finally:
        session.close()


def test_animation_disable_css_reaches_iframe(tmp_path: Path) -> None:
    """The animation-disable style must be present inside the frame document."""
    body = """<!DOCTYPE html><html><body style="margin:0">
<iframe id="frame" style="width:300px; height:80px; border:0;"
        srcdoc='<div id="in-frame" style="width:280px; height:60px;">x</div>'>
</iframe>
</body></html>"""
    html = _write_page(tmp_path, body)
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        session.capture_component(
            Component(name="in-frame", selector="iframe#frame >>> #in-frame", viewports=[VP]),
            str(tmp_path / "frame.png"),
        )
        frame = session.page.frame_locator("iframe#frame")
        animation = frame.locator("#in-frame").evaluate("el => getComputedStyle(el).animationName")
        assert animation == "none"
    finally:
        session.close()


# --------------------------------------------------------------------------
# Mask coverage — a selector matching nothing is an actionable error
# --------------------------------------------------------------------------


def test_mask_selector_matching_nothing_raises(tmp_path: Path) -> None:
    html = fixture_site(tmp_path / "site")
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        with pytest.raises(ValueError, match="matched no elements"):
            session.capture_component(
                Component(
                    name="header",
                    selector="#header",
                    mask_selectors=[".timestammp"],
                    viewports=[VP],
                ),
                str(tmp_path / "header.png"),
            )
    finally:
        session.close()


def test_mask_selector_matching_nothing_still_unmasks_page(tmp_path: Path) -> None:
    """A failed masked capture must not leave earlier masks on the page."""
    html = _write_page(tmp_path, _ABS_CHILD_HTML)
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        session.capture_component(
            Component(name="masked", selector="#holder", mask_selectors=[".ts"], viewports=[VP]),
            str(tmp_path / "masked.png"),
        )
        with pytest.raises(ValueError):
            session.capture_component(
                Component(
                    name="panel",
                    selector="#panel",
                    mask_selectors=[".ts", ".nonexistent"],
                    viewports=[VP],
                ),
                str(tmp_path / "panel.png"),
            )
        # `.ts` was masked by the FIRST selector before the second one failed.
        state = session.page.evaluate(
            """() => {
                const el = document.querySelector('.ts');
                return {
                    position: getComputedStyle(el).position,
                    className: el.className,
                    dataset: Object.keys(el.dataset),
                };
            }"""
        )
        assert state["position"] == "static"
        assert "peeksy-mask" not in state["className"]
        assert state["dataset"] == []
    finally:
        session.close()


# --------------------------------------------------------------------------
# Config — unknown keys and fractional scroll_by are load-time errors
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "raw"),
    [
        (Action, {"kind": "click", "taget": "#x"}),
        (
            Component,
            {
                "name": "header",
                "selector": "#header",
                "viewports": [{"width": 1280, "height": 720}],
                "mask_selector": [".ts"],
            },
        ),
        (Page, {"name": "home", "viewport": {"width": 1280, "height": 720}}),
        (
            Suite,
            {
                "name": "s",
                "baseline_path": "b",
                "results_path": "r",
                "report_path": "p",
                "threshold": 0.1,
                "tolerance": 1.0,
                "treshold": 0.1,
            },
        ),
    ],
)
def test_unknown_config_keys_are_rejected(model: type, raw: dict) -> None:
    """Regression: pydantic's default `extra="ignore"` turned a typo'd key into
    a silently disabled feature (or a Playwright locator error mid-run)."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate(raw)


@pytest.mark.parametrize("arg", [300.5, [10, 300.5], [10.5, 300]])
def test_fractional_scroll_by_is_rejected(arg: object) -> None:
    """Regression: `scroll_by: 300.5` validated, then crashed `int()` at capture
    time — reported as BROKEN infrastructure instead of a config error."""
    with pytest.raises(ValidationError, match="whole pixels"):
        Action.model_validate({"scroll_by": arg})


@pytest.mark.parametrize(
    ("arg", "expected"),
    [(300, "300"), (300.0, "300"), ([10, 300], "10,300"), ([10, 300.0], "10,300")],
)
def test_whole_pixel_scroll_by_still_parses(arg: object, expected: str) -> None:
    assert Action.model_validate({"scroll_by": arg}).value == expected


def test_suite_file_may_not_define_pages(tmp_path: Path) -> None:
    """A hand-written `pages:` key was silently overridden by the folder walk."""
    from peeksy.config import load_config

    site = tmp_path / "site"
    (site / "pages" / "home").mkdir(parents=True)
    (site / "suite.yml").write_text(
        "name: s\nbaseline_path: b\nresults_path: r\nreport_path: p\n"
        "threshold: 0.1\ntolerance: 1.0\npages: []\n",
        encoding="utf-8",
    )
    (site / "pages" / "home" / "page.yml").write_text("url: https://x.test/\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must not define 'pages'"):
        load_config(str(site))


# --------------------------------------------------------------------------
# Runner — BROKEN outcomes carry the baseline when it exists
# --------------------------------------------------------------------------


def test_broken_capture_error_keeps_existing_baseline(tmp_path: Path) -> None:
    from peeksy.runner import run_test

    suite = Suite(
        name="s",
        pages=[
            Page(
                name="home",
                url="https://invalid.invalid/",
                setup=[Action(kind="click", target="#nope")],
                components=[
                    Component(name="header", selector="#header", viewports=[VP]),
                ],
            )
        ],
        baseline_path=str(tmp_path / "baseline"),
        results_path=str(tmp_path / "results"),
        report_path=str(tmp_path / "report"),
        threshold=0.1,
        tolerance=1.0,
    )
    baseline = tmp_path / "baseline" / "home" / "header_1280x720.png"
    baseline.parent.mkdir(parents=True)
    Image.new("RGB", (10, 10), (255, 255, 255)).save(baseline)

    assert run_test(suite) == 1
    import json

    results = sorted((tmp_path / "results").glob("*-result.json"))
    assert len(results) == 1
    payload = json.loads(results[0].read_text(encoding="utf-8"))
    # Allure's Status enum serializes lowercase; the contract form is uppercase.
    assert payload["status"] == "broken"
    assert payload["statusDetails"]["message"], "BROKEN must carry the error"
    # The baseline exists — it must be attached even though capture failed
    # (run_policy: baseline_path is None only when the image does not exist).
    names = [attachment["name"] for attachment in payload["attachments"]]
    assert names == ["baseline"], names
    assert (tmp_path / "results" / payload["attachments"][0]["source"]).exists()


# --------------------------------------------------------------------------
# Review 3 — long-form Action arity, typo'd siblings, string pixel values
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param({"kind": "click"}, id="click-no-target"),
        pytest.param({"kind": "hover"}, id="hover-no-target"),
        pytest.param({"kind": "scroll_to"}, id="scroll-to-no-target"),
        pytest.param({"kind": "fill", "target": "#q"}, id="fill-no-value"),
        pytest.param({"kind": "select", "target": "#c"}, id="select-no-value"),
        pytest.param({"kind": "press"}, id="press-no-value"),
        pytest.param({"kind": "open"}, id="open-no-value"),
        pytest.param({"kind": "scroll_by"}, id="scroll-by-no-value"),
        pytest.param({"kind": "reload", "target": "#x"}, id="reload-with-target"),
        pytest.param({"kind": "reload", "value": "x"}, id="reload-with-value"),
        pytest.param(
            {"kind": "open", "target": "#x", "value": "https://x/"}, id="open-with-target"
        ),
    ],
)
def test_long_form_action_missing_fields_are_rejected(raw: dict) -> None:
    """Regression: the long form skipped `_argument_for` entirely, so a missing
    `target`/`value` surfaced as a Playwright `locator(None)` / `fill(None)`
    TypeError mid-run instead of a load-time config error."""
    with pytest.raises(ValidationError, match="is required for|takes no "):
        Action.model_validate(raw)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param({"kind": "click", "target": "#x"}, id="click"),
        pytest.param({"kind": "fill", "target": "#q", "value": "shoes"}, id="fill"),
        pytest.param({"kind": "press", "value": "Enter"}, id="press-keyboard"),
        pytest.param({"kind": "press", "target": "#q", "value": "Enter"}, id="press-element"),
        pytest.param({"kind": "open", "value": "https://x/"}, id="open"),
        pytest.param({"kind": "reload"}, id="reload"),
        pytest.param({"kind": "wait"}, id="wait-default"),
        pytest.param({"kind": "wait", "target": "#m"}, id="wait-selector"),
        pytest.param({"kind": "wait", "target": "#m", "value": "hidden"}, id="wait-hidden"),
        pytest.param({"kind": "wait", "value": "500"}, id="wait-ms"),
    ],
)
def test_long_form_action_valid_shapes_still_parse(raw: dict) -> None:
    """The arity check must not reject any shape the CODEMANIFEST allows."""
    Action.model_validate(raw)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param({"click": "#x", "taget": "#y"}, id="typo-sibling"),
        pytest.param({"wait": {"selector": "#m", "hidde": True}}, id="typo-in-wait-dict"),
        pytest.param({"wait": {"selector": "#m", "hidden": "true"}}, id="hidden-as-string"),
    ],
)
def test_short_form_stray_keys_are_rejected(raw: dict) -> None:
    """Regression: `_argument_for` rebuilt the dict from recognized keys only, so
    a typo'd sibling never reached `extra="forbid"` and was silently dropped —
    `hidden: "true"` even flipped the wait to VISIBLE."""
    with pytest.raises(ValidationError):
        Action.model_validate(raw)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param({"scroll_by": "300.5"}, id="fractional-string"),
        pytest.param({"scroll_by": "abc"}, id="non-numeric-string"),
        pytest.param({"kind": "scroll_by", "value": "300.5"}, id="long-form-fractional"),
        pytest.param({"kind": "wait", "value": "500.5"}, id="wait-fractional-ms"),
        pytest.param({"kind": "wait", "value": "abc"}, id="wait-non-numeric-ms"),
    ],
)
def test_string_pixel_and_ms_values_are_validated(raw: dict) -> None:
    """Regression: quoted YAML scalars bypassed `_pixels` and crashed `int()` at
    capture time (a BROKEN outcome) instead of failing at load."""
    with pytest.raises(ValidationError, match="whole pixels|whole milliseconds"):
        Action.model_validate(raw)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param({"scroll_by": "300"}, id="string-pixels"),
        pytest.param({"scroll_by": "10,300"}, id="string-xy"),
        pytest.param({"kind": "scroll_by", "value": "300"}, id="long-form-pixels"),
    ],
)
def test_valid_string_pixel_values_still_parse(raw: dict) -> None:
    Action.model_validate(raw)


# --------------------------------------------------------------------------
# Review 3 — shadow-DOM masking and iframe-addressable setup actions
# --------------------------------------------------------------------------


def test_mask_inside_shadow_dom_applies_overlay(tmp_path: Path) -> None:
    """Regression: the overlay CSS was injected into the main document only, and
    a document stylesheet never cascades into a shadow tree — so the
    CODEMANIFEST's own documented case (`my-widget >> form.order .date`) added
    a class no rule could render, and the dynamic region kept flapping."""
    body = """<!DOCTYPE html><html><body style="margin:0">
<my-widget></my-widget>
<script>
  const shadow = document.querySelector("my-widget").attachShadow({mode: "open"});
  shadow.innerHTML = '<div id="w" style="display:inline-block; width:300px; height:80px; background:#eeeeee;"><span class="date" style="display:inline-block; width:120px; height:30px;">today</span></div>';
</script>
</body></html>"""
    html = _write_page(tmp_path, body)
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        component = Component(
            name="widget",
            selector="my-widget >> #w",
            mask_selectors=["my-widget >> .date"],
            viewports=[VP],
        )
        out_path = str(tmp_path / "widget.png")
        session.capture_component(component, out_path)

        with Image.open(out_path) as image:
            image.load()
            raw = image.convert("RGBA").tobytes()
        needle = bytes(MASK_GRAY)
        gray = sum(1 for i in range(0, len(raw), 4) if raw[i : i + 4] == needle)
        # The 120x30 date region must be covered by the opaque overlay.
        assert gray >= 120 * 30, f"mask overlay missing inside shadow DOM: {gray} gray pixels"
    finally:
        session.close()


def test_animation_disable_css_reaches_shadow_dom(tmp_path: Path) -> None:
    """The animation-disable style must be present inside the shadow tree."""
    body = """<!DOCTYPE html><html><body style="margin:0">
<my-widget></my-widget>
<script>
  const shadow = document.querySelector("my-widget").attachShadow({mode: "open"});
  shadow.innerHTML = '<div id="w" style="width:300px; height:80px;">x</div>';
</script>
</body></html>"""
    html = _write_page(tmp_path, body)
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        session.capture_component(
            Component(name="widget", selector="my-widget >> #w", viewports=[VP]),
            str(tmp_path / "widget.png"),
        )
        widget = session.page.locator("my-widget")
        animation = widget.locator("#w").evaluate("el => getComputedStyle(el).animationName")
        assert animation == "none"
    finally:
        session.close()


def test_setup_actions_can_target_iframe_content(tmp_path: Path) -> None:
    """Regression: `run_actions` used `page.locator(target)` directly instead of
    the cell's own `locate` helper, so no action could address content inside an
    `<iframe>` — each one burned the full 30 s timeout and reported BROKEN."""
    body = """<!DOCTYPE html><html><body style="margin:0">
<iframe id="frame" style="width:300px; height:80px; border:0;"
  srcdoc='<button id="btn" style="width:100px; height:30px;">go</button>'>
</iframe>
</body></html>"""
    html = _write_page(tmp_path, body)
    session = CaptureSession()
    session.open()
    try:
        # A click AND a wait inside the frame must both resolve, not time out.
        session.open_page(
            Page(
                name="home",
                url=html.as_uri(),
                wait_until="load",
                setup=[
                    Action(kind="click", target="iframe#frame >>> #btn"),
                    Action(kind="wait", target="iframe#frame >>> #btn"),
                ],
            ),
            VP,
        )
    finally:
        session.close()


# --------------------------------------------------------------------------
# Review 3 — a failed launch must not destroy the previous run's evidence
# --------------------------------------------------------------------------


def test_run_test_launch_failure_preserves_prior_results(monkeypatch, tmp_path: Path) -> None:
    """Regression: `_reset_page_results` wiped the page's `*.current.png` /
    `*.diff.png` BEFORE `CaptureSession.open()` — an unlaunchable browser (the
    normal state before `playwright install chromium`) left the previous run's
    `*-result.json` files pointing at attachments that no longer existed."""
    from peeksy.runner import run_test
    from tests.test_runner import (
        FakeCaptureSession,
        install_fake,
        make_component,
        make_page,
        make_suite,
    )

    suite = make_suite(tmp_path, pages=[make_page("home", [make_component("header")])])

    class NoBrowser(FakeCaptureSession):
        def open(self) -> None:
            raise RuntimeError("Executable doesn't exist — run `playwright install chromium`")

    install_fake(monkeypatch, lambda: NoBrowser())

    # Prior-run evidence: a current PNG and its result JSON.
    page_results = Path(suite.results_path) / "home"
    page_results.mkdir(parents=True, exist_ok=True)
    current = page_results / "header_1280x720.current.png"
    Image.new("RGB", (8, 8), (200, 200, 200)).save(current)

    with pytest.raises(RuntimeError, match="playwright install"):
        run_test(suite, None, None)

    assert current.exists(), "a failed launch must not delete the previous run's images"


# --------------------------------------------------------------------------
# Review 4 — long-form wait/scroll_by values that `int()` would reject
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param({"kind": "wait", "value": "hidden"}, id="hidden-without-target"),
        pytest.param({"kind": "wait", "target": "#m", "value": "purple"}, id="target-plus-junk"),
        pytest.param({"kind": "wait", "value": "²²"}, id="unicode-digits"),
        pytest.param({"kind": "wait", "value": "--5"}, id="double-sign"),
        pytest.param({"kind": "scroll_by", "value": "--5"}, id="scroll-double-sign"),
        pytest.param({"kind": "scroll_by", "value": "²²"}, id="scroll-unicode-digits"),
        pytest.param({"kind": "scroll_by", "value": "+-5"}, id="scroll-mixed-sign"),
    ],
)
def test_int_rejecting_scalars_fail_at_load(raw: dict) -> None:
    """Regression: the guards tested `str.isdigit`/`lstrip("+-")`, which accept
    Unicode digits and doubled signs that `int()` rejects — and the `wait` guard
    exempted the target-present case entirely, so `value: hidden` with no
    target validated and then crashed `int("hidden")` mid-capture."""
    with pytest.raises(ValidationError, match="whole milliseconds|whole pixels|needs a target"):
        Action.model_validate(raw)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param({"kind": "wait", "target": "#m", "value": "hidden"}, id="hidden-with-target"),
        pytest.param({"kind": "wait", "target": "#m"}, id="selector-only"),
        pytest.param({"kind": "wait", "value": "500"}, id="ms"),
        pytest.param({"kind": "wait", "value": "-500"}, id="negative-ms"),
        pytest.param({"kind": "scroll_by", "value": "-5"}, id="scroll-negative"),
        pytest.param({"kind": "scroll_by", "value": "+5"}, id="scroll-plus"),
        pytest.param({"kind": "scroll_by", "value": "10,-300"}, id="scroll-xy-signed"),
    ],
)
def test_valid_signed_scalars_still_parse(raw: dict) -> None:
    """Negative and `+`-prefixed pixel/millisecond counts are legitimate; the
    real-`int()` oracle must accept exactly what capture's `int()` accepts."""
    Action.model_validate(raw)


# --------------------------------------------------------------------------
# Review 4 — repeated shadow roots and repeated iframes
# --------------------------------------------------------------------------

# Two instances of the same custom element, each with its own shadow tree, and
# two iframes whose frame part matches both — the shapes `.first`-only code
# covers just one of.
_MULTI_INSTANCE_HTML = """<!DOCTYPE html><html><body style="margin:0">
<style>
  my-widget { display: block; }
  iframe.ad { width: 240px; height: 60px; border: 0; display: block; }
</style>
<my-widget id="w1"></my-widget>
<my-widget id="w2"></my-widget>
<iframe class="ad" srcdoc="<div id='in' style='width:100px; height:40px;'></div>"></iframe>
<iframe class="ad" srcdoc="<div id='in' style='width:100px; height:40px;'></div>"></iframe>
<script>
  for (const id of ["w1", "w2"]) {
    const root = document.getElementById(id).attachShadow({mode: "open"});
    root.innerHTML = '<div id="w" style="width:300px; height:80px; background:#eeeeee;">'
      + '<span class="date" style="display:inline-block; width:120px; height:30px;">today</span>'
      + "</div>";
  }
</script>
</body></html>"""


def test_mask_reaches_every_shadow_root_of_a_repeated_widget(tmp_path: Path) -> None:
    """Regression: determinism CSS was injected via `.first.evaluate`, so only
    the first instance of a repeated custom element got the overlay rule — the
    second widget's dynamic region kept flapping with the `peeksy-mask` class
    applied and nothing rendering it."""
    html = _write_page(tmp_path, _MULTI_INSTANCE_HTML)
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        component = Component(
            name="widgets",
            selector="body",
            mask_selectors=["my-widget >> .date"],
            viewports=[VP],
        )
        out_path = str(tmp_path / "widgets.png")
        session.capture_component(component, out_path)

        with Image.open(out_path) as image:
            image.load()
            raw = image.convert("RGBA").tobytes()
        needle = bytes(MASK_GRAY)
        gray = sum(1 for i in range(0, len(raw), 4) if raw[i : i + 4] == needle)
        # BOTH 120x30 date regions must be covered, not just the first.
        assert gray >= 2 * 120 * 30, f"only one shadow root masked: {gray} gray pixels"
    finally:
        session.close()


def test_animation_disable_css_reaches_every_shadow_root(tmp_path: Path) -> None:
    """The animation-disable style must land in each repeated widget's root."""
    html = _write_page(tmp_path, _MULTI_INSTANCE_HTML)
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        session.capture_component(
            Component(name="widgets", selector="my-widget >> #w", viewports=[VP]),
            str(tmp_path / "widgets.png"),
        )
        per_root = session.page.evaluate(
            "() => [...document.querySelectorAll('my-widget')].map("
            "h => h.shadowRoot.querySelectorAll('style.peeksy-determinism').length)"
        )
        assert per_root == [1, 1], f"determinism style missing from some roots: {per_root}"
    finally:
        session.close()


def test_mask_selector_matching_several_iframes_does_not_crash(tmp_path: Path) -> None:
    """Regression: `frame_locator(...)` is strict about its OWNER selector, so a
    frame part matching two iframes raised a strict-mode violation on the first
    `.evaluate` — every such component was reported BROKEN instead of tested."""
    html = _write_page(tmp_path, _MULTI_INSTANCE_HTML)
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        component = Component(
            name="frames",
            selector="body",
            mask_selectors=["iframe.ad >>> #in"],
            viewports=[VP],
        )
        out_path = str(tmp_path / "frames.png")
        session.capture_component(component, out_path)  # must not raise

        with Image.open(out_path) as image:
            image.load()
            raw = image.convert("RGBA").tobytes()
        needle = bytes(MASK_GRAY)
        gray = sum(1 for i in range(0, len(raw), 4) if raw[i : i + 4] == needle)
        # BOTH 100x40 in-frame regions must be covered by the overlay.
        assert gray >= 2 * 100 * 40, f"only one frame masked: {gray} gray pixels"
    finally:
        session.close()


def test_component_selector_matching_several_iframes_captures(tmp_path: Path) -> None:
    """The component selector's own `.wait_for`/`.screenshot` hit the same
    strict-mode violation — a multi-frame component could never be captured."""
    html = _write_page(tmp_path, _MULTI_INSTANCE_HTML)
    session = CaptureSession()
    session.open()
    try:
        session.open_page(Page(name="home", url=html.as_uri(), wait_until="load"), VP)
        out_path = str(tmp_path / "in_frame.png")
        session.capture_component(
            Component(name="in-frame", selector="iframe.ad >>> #in", viewports=[VP]),
            out_path,
        )
        assert Image.open(out_path).size == (100, 40)
    finally:
        session.close()
