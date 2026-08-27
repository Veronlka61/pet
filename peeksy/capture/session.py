"""`CaptureSession` — owns the Playwright lifecycle for one capture run.

One headless Chromium browser, one context (`device_scale_factor=1` — a Retina
context renders the same component at double resolution and every diff
explodes), and a single reused page. `open_page` navigates and runs the
page-level setup once per viewport; `capture_component` runs the component
setup, masks dynamic regions, and shoots the element's bounding box.

Contract source: `peeksy/capture/CODEMANIFEST` (read-only); execution details
follow `.goga/usages/cooks/playwright.md`.
"""

from playwright.sync_api import Locator, sync_playwright
from playwright.sync_api import Page as PlaywrightPage

from peeksy.config import Action, Component, Page, Viewport

# Kills time-dependent rendering: animations, transitions, and the text caret.
ANIM_DISABLE_CSS = (
    "*, *::before, *::after {"
    "animation: none !important;"
    "transition: none !important;"
    "caret-color: transparent !important;}"
)

# Opaque gray overlay driven by a class, so a masked region is pixel-identical
# across runs regardless of what is underneath — while the element keeps its
# layout box (never `display: none`, which would reflow neighbours).
MASK_CSS = (
    ".peeksy-mask { position: relative; }"
    ".peeksy-mask::after {"
    'content: ""; position: absolute; inset: 0;'
    "background: #808080; z-index: 99999;}"
)

# Playwright's own default action timeout; surfaced as a capture error (the
# runner records BROKEN) rather than hanging the run.
ACTION_TIMEOUT_MS = 30_000


class CaptureSession:
    """Deterministic element-level screenshots for a suite of components."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page: PlaywrightPage | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def page(self) -> PlaywrightPage:
        """The single reused page; requires `open()` first."""
        if self._page is None:
            raise RuntimeError("CaptureSession.open() must be called before use")
        return self._page

    def open(self) -> None:
        """Launch headless Chromium and create one DPR=1 context with one page."""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            device_scale_factor=1,
        )
        self._context.set_default_timeout(ACTION_TIMEOUT_MS)
        self._page = self._context.new_page()

    def close(self) -> None:
        """Tear down the context, browser, and Playwright; safe to call twice."""
        for teardown, target in (
            (lambda: self._context.close(), self._context),
            (lambda: self._browser.close(), self._browser),
            (lambda: self._playwright.stop(), self._playwright),
        ):
            if target is None:
                continue
            teardown()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    # -- two-level setup ---------------------------------------------------

    def open_page(self, page: Page, viewport: Viewport) -> None:
        """Navigate to `page.url` at `viewport` and run its setup once."""
        target = self.page
        target.set_viewport_size({"width": viewport.width, "height": viewport.height})

        # url=None is the deep-link flow: validation guarantees setup starts
        # with an `open` action, which performs the navigation below.
        if page.url is not None:
            target.goto(page.url, wait_until=page.wait_until)

        _apply_determinism(target)
        run_actions(target, page.setup, page.wait_until)

    def capture_component(self, component: Component, out_path: str) -> str:
        """Capture one component on the currently open page into `out_path`."""
        target = self.page

        run_actions(target, component.setup, wait_strategy="networkidle")

        # An `open`/`reload` inside the setup navigates away and drops the
        # style tag injected by open_page (and the deep-link flow injects it on
        # a blank page) — determinism must be re-established after the setup.
        _apply_determinism(target)

        # Wait for the component FIRST: the page must be settled so masked
        # zones exist in the DOM before the overlay goes on.
        component_locator = locate(target, component.selector).first
        component_locator.wait_for(state="visible")

        for mask_selector in component.mask_selectors:
            locate(target, mask_selector).evaluate("el => el.classList.add('peeksy-mask')")

        try:
            component_locator.screenshot(type="png", path=out_path)
        finally:
            # No mask leakage onto the next component's shot.
            for mask_selector in component.mask_selectors:
                locate(target, mask_selector).evaluate("el => el.classList.remove('peeksy-mask')")

        return out_path


# --------------------------------------------------------------------------
# Private helpers — action dispatch, localization, waits, determinism
# --------------------------------------------------------------------------


def _apply_determinism(page: PlaywrightPage) -> None:
    """Inject the animation-disable CSS (+ mask style) and wait for fonts."""
    page.add_style_tag(content=ANIM_DISABLE_CSS)
    page.add_style_tag(content=MASK_CSS)
    page.evaluate("document.fonts.ready")


def locate(page: PlaywrightPage, selector: str) -> Locator:
    """Resolve a selector the same way for components AND masks.

    Plain CSS goes straight to `page.locator`. A piercing selector `a >> b`
    crosses shadow-DOM boundaries (Playwright's `>>` chaining handles this
    natively). A selector addressing content inside an `<iframe>` is routed
    through `frame_locator`.
    """
    if ">>" in selector and ">>>" not in selector:
        # Playwright's `>>` chaining resolves shadow-piercing selectors.
        return page.locator(selector)

    if selector.startswith("iframe"):
        # `<iframe selector> >>> <inner selector>` — the design's iframe form.
        frame_part, _, inner = selector.partition(">>>")
        frame_locator = page.frame_locator(frame_part.strip())
        return frame_locator.locator(inner.strip())

    return page.locator(selector)


def run_actions(page: PlaywrightPage, actions: list[Action], wait_strategy: str) -> None:
    """Execute setup `Action`s in list order, dispatching per `kind`."""
    for action in actions:
        kind = action.kind

        if kind == "click":
            page.locator(action.target).click()
        elif kind == "hover":
            page.locator(action.target).hover()
        elif kind == "scroll_to":
            page.locator(action.target).scroll_into_view_if_needed()
        elif kind == "scroll_by":
            x, y = _parse_xy(action.value)
            page.mouse.wheel(x, y)
        elif kind == "fill":
            page.locator(action.target).fill(action.value)
        elif kind == "press":
            (page.locator(action.target) if action.target else page.keyboard).press(action.value)
        elif kind == "select":
            page.locator(action.target).select_option(action.value)
        elif kind == "wait":
            run_wait(page, action, wait_strategy)
        elif kind == "open":
            page.goto(action.value, wait_until=wait_strategy)
        elif kind == "reload":
            page.reload(wait_until=wait_strategy)
        else:  # pragma: no cover — `kind` is a closed Literal in the config
            raise ValueError(f"unknown action kind: {kind!r}")


def run_wait(page: PlaywrightPage, action: Action, wait_strategy: str) -> None:
    """`wait` is overloaded: selector / {selector, hidden} / ms / settle."""
    if action.target is not None:
        state = "hidden" if action.value == "hidden" else "visible"
        page.wait_for_selector(action.target, state=state)
        return

    if action.value is not None:
        page.wait_for_timeout(int(action.value))
        return

    # Default stabilization between steps.
    page.wait_for_load_state(wait_strategy)
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(50)


def _parse_xy(value: str | None) -> tuple[int, int]:
    """`"300"` -> (0, 300); `"0,300"` -> (0, 300); None -> (0, 0)."""
    if value is None:
        return (0, 0)
    parts = [part.strip() for part in str(value).split(",")]
    if len(parts) == 1:
        return (0, int(parts[0]))
    if len(parts) == 2:
        return (int(parts[0]), int(parts[1]))
    raise ValueError(f"scroll_by takes pixels or [x, y], got {value!r}")
