"""`CaptureSession` — owns the Playwright lifecycle for one capture run.

One headless Chromium browser, one context (`device_scale_factor=1` — a Retina
context renders the same component at double resolution and every diff
explodes), and a single reused page. `open_page` navigates and runs the
page-level setup once per viewport; `capture_component` runs the component
setup, masks dynamic regions, and shoots the element's bounding box.

Contract source: `peeksy/capture/CODEMANIFEST` (read-only); execution details
follow `.goga/usages/cooks/playwright.md`.
"""

import contextlib

from playwright.sync_api import Frame, Locator, sync_playwright
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
# layout box (never `display: none`, which would reflow neighbours). `position`
# is only forced on static elements: overwriting an existing absolute/fixed
# position would move the element (and reflow its neighbours) — a false diff.
# `_MASK_OFF` restores the prior inline value, so the single reused page is
# byte-identical after a masked capture — a leaked `position: relative` would
# re-anchor later components' absolutely-positioned descendants.
_MASK_ON = (
    "els => els.forEach(el => {"
    "if (getComputedStyle(el).position === 'static'){"
    "el.dataset.peeksyPos = el.style.position;"
    "el.style.position = 'relative';}"
    "el.classList.add('peeksy-mask');})"
)
_MASK_OFF = (
    "els => els.forEach(el => {"
    "if ('peeksyPos' in el.dataset){"
    "el.style.position = el.dataset.peeksyPos;"
    "delete el.dataset.peeksyPos;}"
    "el.classList.remove('peeksy-mask');})"
)
MASK_CSS = (
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
        self._wait_until = "networkidle"

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
        try:
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context(
                device_scale_factor=1,
            )
            self._context.set_default_timeout(ACTION_TIMEOUT_MS)
            self._page = self._context.new_page()
        except Exception:
            # A partial start must not leak the driver or browser process.
            self.close()
            raise

    def close(self) -> None:
        """Tear down the context, browser, and Playwright; safe to call twice.

        Each step is isolated: a teardown failure (plausible when the browser
        process already died) must not skip the remaining steps or replace a
        capture error raised through the runner's `finally: session.close()`.
        """
        with contextlib.suppress(Exception):
            if self._context is not None:
                self._context.close()
        with contextlib.suppress(Exception):
            if self._browser is not None:
                self._browser.close()
        with contextlib.suppress(Exception):
            if self._playwright is not None:
                self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    # -- two-level setup ---------------------------------------------------

    def open_page(self, page: Page, viewport: Viewport) -> None:
        """Navigate to `page.url` at `viewport` and run its setup once."""
        target = self.page
        target.set_viewport_size({"width": viewport.width, "height": viewport.height})
        self._wait_until = page.wait_until

        # url=None is the deep-link flow: validation guarantees setup starts
        # with an `open` action, which performs the navigation below.
        if page.url is not None:
            target.goto(page.url, wait_until=page.wait_until)

        _apply_determinism(target)
        run_actions(target, page.setup, page.wait_until)

    def capture_component(self, component: Component, out_path: str) -> str:
        """Capture one component on the currently open page into `out_path`."""
        target = self.page

        # The page's wait_until applies here too (open_page stored it): the
        # contract requires open/reload inside a component setup to navigate
        # with the SAME strategy as open_page — hardcoding networkidle would
        # hang a live page configured for domcontentloaded.
        run_actions(target, component.setup, wait_strategy=self._wait_until)

        # An `open`/`reload` inside the setup navigates away and drops the
        # style tag injected by open_page (and the deep-link flow injects it on
        # a blank page) — determinism must be re-established after the setup.
        _apply_determinism(target, component.selector)

        # Wait for the component FIRST: the page must be settled so masked
        # zones exist in the DOM before the overlay goes on.
        component_locator = locate(target, component.selector).first
        component_locator.wait_for(state="visible")

        try:
            for mask_selector in component.mask_selectors:
                # A mask selector that matches nothing is a config mistake (a
                # typo, or a redesign dropped the element) — silently shooting
                # anyway would let the "dynamic" region keep producing
                # run-to-run diffs that read as visual regressions.
                mask_locators = _mask_locators(target, mask_selector)
                if sum(locator.count() for locator in mask_locators) == 0:
                    raise ValueError(f"mask selector {mask_selector!r} matched no elements")
                # The frame or shadow root holding the masked element needs the
                # overlay style too — CSS never crosses an iframe boundary, and
                # a document stylesheet never cascades into a shadow tree.
                _apply_determinism(target, mask_selector)
                # evaluate_all, not evaluate: a mask selector legitimately
                # matches several elements (every timestamp, every ad slot),
                # and strict-mode evaluate would abort the capture on the 2nd.
                for locator in mask_locators:
                    locator.evaluate_all(_MASK_ON)

            component_locator.screenshot(type="png", path=out_path)
        except Exception:
            # Any failure here — a mask that matched nothing, a screenshot
            # error — must not leave the masks already applied on the page, and
            # a failing unmask must not mask the original error either.
            self._unmask(target, component.mask_selectors)
            raise
        # No mask leakage onto the next component's shot.
        self._unmask(target, component.mask_selectors)

        return out_path

    @staticmethod
    def _unmask(target: PlaywrightPage, mask_selectors: list[str]) -> None:
        """Strip the mask class (and its injected inline `position`)."""
        for mask_selector in mask_selectors:
            with contextlib.suppress(Exception):
                for locator in _mask_locators(target, mask_selector):
                    locator.evaluate_all(_MASK_OFF)


# --------------------------------------------------------------------------
# Private helpers — action dispatch, localization, waits, determinism
# --------------------------------------------------------------------------


def _apply_determinism(page: PlaywrightPage, selector: str | None = None) -> None:
    """Inject the animation-disable CSS (+ mask style) and wait for fonts.

    `selector` covers components (and mask selectors) living inside an
    `<iframe>`: CSS does not cascade across document boundaries, so the frame
    holding the element gets its own injection. Without it, `mask_selectors`
    inside an iframe would apply the class to nothing the overlay style can
    reach — the dynamic region would keep rendering into the screenshot.
    """
    targets: list[PlaywrightPage | Frame] = [page]
    if selector is not None and ">>>" in selector:
        # Every matching frame needs its own injection — CSS does not cascade
        # across frame boundaries, and a frame part legitimately matches
        # several iframes (every ad slot on a page).
        targets.extend(_resolve_frames(page, selector))
    for target in targets:
        target.add_style_tag(content=ANIM_DISABLE_CSS)
        target.add_style_tag(content=MASK_CSS)
        target.evaluate("document.fonts.ready")

    # A piercing part (`a >> b`, alone or after a `>>>` frame hop) crosses into
    # shadow roots, which the frame loop above cannot reach — a document (or
    # frame) stylesheet never cascades into one. `_mask_locators` fans the
    # selector out per frame, so the `>>>` case is covered here too.
    if selector is not None and ">>" in selector:
        _apply_shadow_determinism(page, selector)


def _apply_shadow_determinism(page: PlaywrightPage, selector: str) -> None:
    """Inject the styles into the shadow roots a piercing selector crosses.

    A document stylesheet never cascades into a shadow tree, so a masked
    element inside one (`my-widget >> form.order .date`) would carry the
    `peeksy-mask` class with no overlay rule to render it — the CODEMANIFEST's
    own documented masking case, silently inert. `evaluate_all`, not
    `evaluate`: a page with several instances of the same custom element has
    the same shadow tree repeated, and only the first would get the styles.
    The per-root `peeksy-determinism` guard keeps re-injection idempotent.
    """
    css = ANIM_DISABLE_CSS + MASK_CSS
    for locator in _mask_locators(page, selector):
        locator.evaluate_all(
            "(els, css) => els.forEach(el => {"
            "const root = el.getRootNode();"
            "if (root instanceof ShadowRoot && !root.querySelector('style.peeksy-determinism')) {"
            "const style = document.createElement('style');"
            "style.className = 'peeksy-determinism';"
            "style.textContent = css;"
            "root.appendChild(style);"
            "}"
            "})",
            css,
        )


def _resolve_frames(page: PlaywrightPage, selector: str) -> list[Frame]:
    """Every `Frame` a `frame >>> inner` selector addresses.

    A frame part can legitimately match several iframes, so all of them are
    returned — determinism CSS must reach each one. Non-frame matches of the
    frame part are skipped rather than fatal: the mask/component locator
    reports the real problem (matched no elements) once the caller gets there.

    `element_handles` does NOT auto-wait (it returns [] immediately for an
    element not yet attached), and this runs before the component's own
    `wait_for` — with `wait_until: domcontentloaded` an iframe that attaches
    after DCL would otherwise resolve zero frames and silently skip the
    determinism/mask CSS. Waiting for attachment first closes that window; a
    frame that never appears still fails through the caller's timeout.
    """
    frame_part = selector.partition(">>>")[0].strip()
    owner = page.locator(frame_part).first
    owner.wait_for(state="attached")
    frames: list[Frame] = []
    for handle in page.locator(frame_part).element_handles():
        frame = handle.content_frame()
        handle.dispose()
        if frame is not None:
            frames.append(frame)
    return frames


def _mask_locators(page: PlaywrightPage, selector: str) -> list[Locator]:
    """One locator per frame a mask selector spans, or the single page locator.

    `locate()` scopes an iframe selector to its FIRST matching frame (strict
    mode demands an owner), but masking must reach the masked region in EVERY
    matching frame — "every ad slot", the CODEMANIFEST's own motivating case.
    """
    if ">>>" not in selector:
        return [locate(page, selector)]
    inner = selector.partition(">>>")[2]
    return [frame.locator(inner.strip()) for frame in _resolve_frames(page, selector)]


def locate(page: PlaywrightPage, selector: str) -> Locator:
    """Resolve a selector the same way for components AND masks.

    Plain CSS goes straight to `page.locator` — including a piercing selector
    `a >> b`, whose `>>` chaining Playwright resolves natively. A selector
    addressing content inside an `<iframe>` (`<frame> >>> <inner>`) is routed
    through `frame_locator`. The `>>>` separator is the iframe marker: keying
    on a literal `iframe` prefix would misroute plain CSS that targets the
    `<iframe>` element itself (`iframe.ad` has no inner selector to split).

    `.first` on the FrameLocator is load-bearing: `frame_locator(...)` is
    strict about its OWNER selector, so a frame part matching several iframes
    (every ad slot, every embedded player) would raise a strict-mode violation
    on the first `.wait_for`/`.screenshot`/`.evaluate`. `.first` scopes to the
    first matching frame; `_apply_determinism` still injects into every frame.
    """
    if ">>>" in selector:
        frame_part, _, inner = selector.partition(">>>")
        return page.frame_locator(frame_part.strip()).first.locator(inner.strip())
    return page.locator(selector)


def run_actions(page: PlaywrightPage, actions: list[Action], wait_strategy: str) -> None:
    """Execute setup `Action`s in list order, dispatching per `kind`."""
    for action in actions:
        kind = action.kind

        if kind == "click":
            locate(page, action.target).click()
        elif kind == "hover":
            locate(page, action.target).hover()
        elif kind == "scroll_to":
            locate(page, action.target).scroll_into_view_if_needed()
        elif kind == "scroll_by":
            x, y = _parse_xy(action.value)
            page.mouse.wheel(x, y)
        elif kind == "fill":
            locate(page, action.target).fill(action.value)
        elif kind == "press":
            (locate(page, action.target) if action.target else page.keyboard).press(action.value)
        elif kind == "select":
            locate(page, action.target).select_option(action.value)
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
        # `locate`, not `page.wait_for_selector`: a target inside an <iframe>
        # (`frame >>> inner`) must resolve through frame_locator — the raw form
        # would burn the whole 30 s timeout matching nothing.
        target = locate(page, action.target).first
        if state == "hidden":
            target.wait_for(state="hidden")
        else:
            target.wait_for(state="visible")
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
