"""Pydantic v2 models for the peeksy site configuration.

Contract source: `peeksy/config/CODEMANIFEST` (read-only). All five entities
(`Viewport`, `Action`, `Component`, `Page`, `Suite`) live in this module per
the `location: models.py` declarations and are re-exported by the cell facade.

`Action` is data only — the capture cell interprets each `kind` via Playwright.
The short YAML form (`- click: "#x"`, `- fill: ["#q", "shoes"]`, ...) is parsed
into `(kind, target, value)` here by `model_validator` per the per-kind rules.
"""

from typing import Literal, get_args

from pydantic import BaseModel, Field, model_validator

ActionKind = Literal[
    "click",
    "hover",
    "scroll_to",
    "scroll_by",
    "fill",
    "press",
    "select",
    "wait",
    "open",
    "reload",
]
WaitUntil = Literal["networkidle", "domcontentloaded", "load"]

# Kinds whose short-form string argument is the CSS `target` selector.
_TARGET_FROM_STRING = frozenset({"click", "hover", "scroll_to"})
# Kinds whose short-form string argument is the `value`.
_VALUE_FROM_STRING = frozenset({"press", "scroll_by", "open"})
# Kinds accepting the two-element `[target, value]` list form.
_TARGET_VALUE_FROM_LIST = frozenset({"fill", "select", "press"})


class Viewport(BaseModel):
    """A single viewport dimension in CSS pixels."""

    width: int = Field(gt=0, description="Viewport width in CSS pixels.")
    height: int = Field(gt=0, description="Viewport height in CSS pixels.")


class Action(BaseModel):
    """One setup action to perform on a page or component before a screenshot.

    Data only — carries no behaviour. Parsed from the short YAML form by
    `model_validator`, which fills `target`/`value` per `kind`.
    """

    kind: ActionKind = Field(description="Which Playwright operation to run.")
    target: str | None = Field(default=None, description="CSS selector of the action target.")
    value: str | None = Field(
        default=None,
        description="Auxiliary value: text/key/option/pixels/milliseconds/URL.",
    )

    @model_validator(mode="before")
    @classmethod
    def _parse_short_form(cls, data: object) -> object:
        """Normalize the short YAML form `{kind: argument}` into a field dict."""
        if not isinstance(data, dict) or "kind" in data:
            return data

        items = [(k, v) for k, v in data.items() if k in get_args(ActionKind)]
        if not items:
            return data  # no kind key at all — let Pydantic report `kind` as missing
        if len(items) > 1:
            kinds = sorted(k for k, _ in items)
            raise ValueError(f"one action per list item, got several kinds: {kinds}")
        kind, arg = items[0]
        return _argument_for(kind, arg)


def _argument_for(kind: str, arg: object) -> dict[str, object]:
    """Map one short-form `(kind, argument)` pair onto Action fields."""
    if kind == "reload":
        if arg not in (None, {}):
            raise ValueError(f"reload takes no target and no value, got {arg!r}")
        return {"kind": "reload", "target": None, "value": None}

    if kind == "wait":
        return _wait_argument(arg)

    if kind == "scroll_by" and isinstance(arg, list):
        if len(arg) != 2:
            raise ValueError(f"scroll_by takes pixels or [x, y], got {arg!r}")
        x, y = arg
        return {"kind": "scroll_by", "target": None, "value": f"{x},{y}"}

    if isinstance(arg, str):
        if kind in _TARGET_FROM_STRING:
            return {"kind": kind, "target": arg, "value": None}
        if kind in _VALUE_FROM_STRING:
            return {"kind": kind, "target": None, "value": arg}
        raise ValueError(
            f"action {kind!r} takes a [target, value] list, got the bare string {arg!r}"
        )

    if isinstance(arg, list):
        if kind not in _TARGET_VALUE_FROM_LIST:
            raise ValueError(f"action {kind!r} does not take a list argument, got {arg!r}")
        if len(arg) != 2:
            raise ValueError(
                f"action {kind!r} needs exactly [target, value], got a list of {len(arg)}"
            )
        target, value = arg
        return {"kind": kind, "target": target, "value": value}

    raise ValueError(f"action {kind!r} needs an argument, got {arg!r}")


def _wait_argument(arg: object) -> dict[str, object]:
    """`wait` is overloaded: selector / {selector, hidden} / milliseconds / nothing."""
    if arg is None or arg == {}:
        return {"kind": "wait", "target": None, "value": None}
    if isinstance(arg, str):
        return {"kind": "wait", "target": arg, "value": None}
    if isinstance(arg, dict):
        selector = arg.get("selector")
        if not isinstance(selector, str) or not selector:
            raise ValueError(f"wait needs a 'selector' string, got {arg!r}")
        if arg.get("hidden") is True:
            return {"kind": "wait", "target": selector, "value": "hidden"}
        return {"kind": "wait", "target": selector, "value": None}
    if isinstance(arg, int) and not isinstance(arg, bool):
        return {"kind": "wait", "target": None, "value": str(arg)}
    raise ValueError(f"wait takes a selector, {{selector, hidden}}, ms, or nothing, got {arg!r}")


class Component(BaseModel):
    """Specification of one UI component on a page."""

    name: str = Field(description="Component identifier; unique within its page.")
    selector: str = Field(description="CSS selector locating the component element.")
    mask_selectors: list[str] = Field(
        default_factory=list,
        description="CSS selectors of dynamic regions to hide before the shot.",
    )
    viewports: list[Viewport] = Field(
        min_length=1,
        description="Viewports to capture at; non-empty (none means never captured).",
    )
    threshold: float | None = Field(
        default=None,
        gt=0,
        lt=1,
        description="Per-pixel sensitivity override in (0..1); None inherits the suite default.",
    )
    tolerance: float | None = Field(
        default=None,
        gt=0,
        le=100,
        description="Allowed mismatch % override in (0..100]; None inherits the suite default.",
    )
    setup: list[Action] = Field(
        default_factory=list,
        description="Component-level actions to run before this component's shot.",
    )


class Page(BaseModel):
    """One page of the site: URL, wait strategy, setup actions, components."""

    name: str = Field(description="Page identifier, derived from its folder name.")
    url: str | None = Field(
        default=None,
        description="Page URL; None for the deep-link flow (setup starts with open).",
    )
    wait_until: WaitUntil = Field(
        default="networkidle",
        description="Navigation wait strategy forwarded to page.goto.",
    )
    setup: list[Action] = Field(
        default_factory=list,
        description="Page-level actions run once per viewport after navigation.",
    )
    components: list[Component] = Field(
        default_factory=list,
        description="Components on this page; kept name-sorted for deterministic capture.",
    )

    @model_validator(mode="after")
    def _validate_page(self) -> "Page":
        names = [component.name for component in self.components]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise ValueError(
                f"duplicate component name(s) {sorted(duplicates)} in page {self.name!r}"
            )

        starts_with_open = bool(self.setup) and self.setup[0].kind == "open"
        if self.url is None and not starts_with_open:
            raise ValueError(
                f"page {self.name!r} has no url and its setup does not start with an "
                "'open' action (deep-link flow required)"
            )
        if self.url is not None and starts_with_open:
            raise ValueError(
                f"page {self.name!r} sets a url and its setup starts with an 'open' "
                "action (mutually exclusive — the page would be navigated twice)"
            )

        self.components.sort(key=lambda component: component.name)
        return self


class Suite(BaseModel):
    """The whole peeksy configuration loaded from a site folder."""

    name: str = Field(description="Suite/site name; used as the Allure suite label.")
    pages: list[Page] = Field(default_factory=list, description="Pages to capture and compare.")
    baseline_path: str = Field(description="Directory for baseline PNGs (organized by page).")
    results_path: str = Field(description="Directory for Allure results and current/diff PNGs.")
    report_path: str = Field(description="Directory for the built HTML report.")
    threshold: float = Field(
        gt=0,
        lt=1,
        description="Suite-default per-pixel sensitivity in (0..1).",
    )
    tolerance: float = Field(
        gt=0,
        le=100,
        description="Suite-default allowed mismatch % in (0..100].",
    )
