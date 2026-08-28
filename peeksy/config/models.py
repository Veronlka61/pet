"""Pydantic v2 models for the peeksy site configuration.

Contract source: `peeksy/config/CODEMANIFEST` (read-only). All five entities
(`Viewport`, `Action`, `Component`, `Page`, `Suite`) live in this module per
the `location: models.py` declarations and are re-exported by the cell facade.

`Action` is data only — the capture cell interprets each `kind` via Playwright.
The short YAML form (`- click: "#x"`, `- fill: ["#q", "shoes"]`, ...) is parsed
into `(kind, target, value)` here by `model_validator` per the per-kind rules.
"""

import os
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

# Per-kind arity of the CONSTRUCTED fields (CODEMANIFEST "Requirements"),
# applied whatever form the action was written in. `press` keeps `target`
# optional (a keyboard-level press targets no element); `wait` legitimately
# carries target-only, value-only, or neither.
_REQUIRED_BY_KIND: dict[str, frozenset[str]] = {
    "click": frozenset({"target"}),
    "hover": frozenset({"target"}),
    "scroll_to": frozenset({"target"}),
    "scroll_by": frozenset({"value"}),
    "fill": frozenset({"target", "value"}),
    "press": frozenset({"value"}),
    "select": frozenset({"target", "value"}),
    "wait": frozenset(),
    "open": frozenset({"value"}),
    "reload": frozenset(),
}
# Fields a kind must NOT carry, even though the model types allow them — the
# CODEMANIFEST "Requirements" list verbatim (`value = None` for click/hover/
# scroll_to, `target = None` for scroll_by/open, neither for reload).
_FORBIDDEN_BY_KIND: dict[str, frozenset[str]] = {
    "click": frozenset({"value"}),
    "hover": frozenset({"value"}),
    "scroll_to": frozenset({"value"}),
    "scroll_by": frozenset({"target"}),
    "fill": frozenset(),
    "press": frozenset(),
    "select": frozenset(),
    "wait": frozenset(),
    "open": frozenset({"target"}),
    "reload": frozenset({"target", "value"}),
}


class Viewport(BaseModel):
    """A single viewport dimension in CSS pixels."""

    width: int = Field(gt=0, description="Viewport width in CSS pixels.")
    height: int = Field(gt=0, description="Viewport height in CSS pixels.")


class Action(BaseModel):
    """One setup action to perform on a page or component before a screenshot.

    Data only — carries no behaviour. Parsed from the short YAML form by
    `model_validator`, which fills `target`/`value` per `kind`.
    """

    # A typo'd key (`- click: {taget: "#x"}`) must fail HERE as a config error,
    # not surface later as a Playwright locator error mid-run.
    model_config = ConfigDict(extra="forbid")

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
        # Siblings the parser does not recognize would be silently DROPPED by
        # the fresh dict below (`taget:` never reaches `extra="forbid"`) — a
        # typo'd key must fail as a config error, not disable the feature.
        strays = sorted(set(data) - {kind})
        if strays:
            raise ValueError(
                f"unknown key(s) {strays} alongside {kind!r} — expected one action per list item"
            )
        return _argument_for(kind, arg)

    @model_validator(mode="after")
    def _validate_kind_fields(self) -> "Action":
        """Enforce the per-kind `target`/`value` rules on the CONSTRUCTED fields.

        The short form is checked shape-first in `_argument_for`, but the long
        form (`{kind: fill, target: "#q"}`) skips that path entirely — without
        this pass a missing `value` would surface as a Playwright `fill(None)`
        TypeError mid-run instead of a load-time config error.
        """
        problems: list[str] = []
        for label, forbidden in (("target", self.target), ("value", self.value)):
            if forbidden is None:
                if label in _REQUIRED_BY_KIND[self.kind]:
                    problems.append(f"{label} is required for {self.kind!r}")
            elif label in _FORBIDDEN_BY_KIND[self.kind]:
                problems.append(f"{self.kind!r} takes no {label}, got {forbidden!r}")
            elif not forbidden.strip():
                # An empty (or whitespace) string validates today and dies as a
                # Playwright locator error mid-run — or, for `press`, silently
                # becomes a keyboard-level press with no element at all.
                problems.append(f"{label} cannot be empty for {self.kind!r}")
        if self.kind == "scroll_by" and self.value is not None:
            problems.extend(_scroll_by_problems(self.value))
        if self.kind == "wait" and self.value is not None:
            problems.extend(_wait_problems(self.target, self.value))
        if problems:
            raise ValueError("; ".join(problems))
        return self


def _scroll_by_problems(value: str) -> list[str]:
    """The capture cell splits `scroll_by` on `,` and `int()`s each part — a
    part `int()` would reject must fail HERE as a config error. `str.isdigit`
    is not the test (it accepts Unicode digits like `"²"` that `int()` rejects);
    parsing is the only faithful oracle."""
    parts = value.split(",")
    if len(parts) not in (1, 2) or any(_int_fails(part) for part in parts):
        return [f"scroll_by takes whole pixels or [x, y], got {value!r}"]
    return []


def _wait_problems(target: str | None, value: str) -> list[str]:
    """`wait`'s value is either `"hidden"` (only WITH a target) or whole
    milliseconds. A target-present action never pauses, so any other value
    there is a config mistake, not a no-op to shoot through."""
    if target is not None:
        # Only "hidden" changes what a targeted wait does; a numeric value here
        # (`wait for #m, then settle 500 ms` is the natural misreading) would
        # be silently discarded by `run_wait`.
        if value == "hidden":
            return []
        return [f"wait with a target takes 'hidden' or nothing, got {value!r}"]
    if value == "hidden":
        return ['wait "hidden" needs a target selector']
    if _int_fails(value):
        return [f"wait takes whole milliseconds, got {value!r}"]
    return []


def _int_fails(value: str) -> bool:
    """Whether the capture cell's `int()` would reject this scalar."""
    try:
        int(value.strip())
    except ValueError:
        return True
    return False


def _pixels(value: object) -> int:
    """Whole CSS pixels only — a fractional scroll is a config error, not a
    capture-time `int()` crash (`.5` pixels are not addressable anyway)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(  # noqa: TRY004 — config error, not a programming error
            f"scroll_by takes whole pixels, got {value!r}"
        )
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"scroll_by takes whole pixels, got {value!r}")
        return int(value)
    return value


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
        return {"kind": "scroll_by", "target": None, "value": f"{_pixels(x)},{_pixels(y)}"}

    if kind == "scroll_by" and isinstance(arg, (int, float)) and not isinstance(arg, bool):
        # The documented form is an unquoted YAML number: `- scroll_by: 300`.
        return {"kind": "scroll_by", "target": None, "value": str(_pixels(arg))}

    if kind == "scroll_by" and isinstance(arg, str):
        return {"kind": "scroll_by", "target": None, "value": _pixels_string(arg)}

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


def _pixels_string(value: str) -> str:
    """A quoted YAML pixel count — same rule as `_pixels`, for the string form.

    `_pixels` guards the numeric branch, but `- scroll_by: "300.5"` reaches this
    one and must fail HERE, not as a capture-time `int()` crash. The `[x, y]`
    form is also writable as `"10,300"` (`_parse_xy` splits on the comma).
    """
    if "," not in value:
        return str(_pixels(_int_or_fail(value, "scroll_by")))
    parts = value.split(",")
    if len(parts) != 2:
        raise ValueError(f"scroll_by takes pixels or [x, y], got {value!r}")
    x, y = (_int_or_fail(part, "scroll_by") for part in parts)
    return f"{_pixels(x)},{_pixels(y)}"


def _int_or_fail(value: str, kind: str) -> int:
    """Parse a whole-pixel integer, reporting a config error on failure."""
    stripped = value.strip()
    try:
        return int(stripped)
    except ValueError:
        raise ValueError(f"{kind} takes whole pixels, got {value!r}") from None


def _wait_argument(arg: object) -> dict[str, object]:
    """`wait` is overloaded: selector / {selector, hidden} / milliseconds / nothing."""
    if arg is None or arg == {}:
        return {"kind": "wait", "target": None, "value": None}
    if isinstance(arg, str):
        return {"kind": "wait", "target": arg, "value": None}
    if isinstance(arg, dict):
        # Reject unknown keys: `hidde: true` / `hidden: "true"` would otherwise
        # silently mean "wait for VISIBLE" — the opposite of the intent.
        unknown = sorted(set(arg) - {"selector", "hidden"})
        if unknown:
            raise ValueError(f"wait takes 'selector' and 'hidden' only, got {unknown} in {arg!r}")
        selector = arg.get("selector")
        if not isinstance(selector, str) or not selector:
            raise ValueError(f"wait needs a 'selector' string, got {arg!r}")
        hidden = arg.get("hidden")
        if not isinstance(hidden, bool):
            raise ValueError(  # noqa: TRY004 — config error, not a programming error
                f"wait 'hidden' must be a boolean, got {hidden!r} in {arg!r}"
            )
        if hidden:
            return {"kind": "wait", "target": selector, "value": "hidden"}
        return {"kind": "wait", "target": selector, "value": None}
    if isinstance(arg, int) and not isinstance(arg, bool):
        return {"kind": "wait", "target": None, "value": str(arg)}
    raise ValueError(f"wait takes a selector, {{selector, hidden}}, ms, or nothing, got {arg!r}")


class Component(BaseModel):
    """Specification of one UI component on a page."""

    # `mask_selector:` (singular) or `tollerance:` would otherwise silently
    # disable the feature the user meant to configure.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Component identifier; unique within its page.")
    selector: str = Field(
        min_length=1,
        description="CSS selector locating the component element.",
    )
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

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        description="Suite/site name; used as the Allure suite label.",
    )
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

    @model_validator(mode="after")
    def _paths_must_not_overlap(self) -> "Suite":
        """Reject two of the three run directories resolving to the same tree.

        `test` deletes `{results_path}/{page}` and `report` regenerates
        `report_path` wholesale, so an overlap (`results_path == baseline_path`)
        silently destroys the committed baselines — every later run reports
        `BROKEN: baseline not found`. Nesting is rejected too: writing results
        under `baseline_path/` makes `generate` adopt last run's outputs as the
        new baselines. `normpath` collapses `.`, `..`, and duplicate separators
        first, so those spellings cannot smuggle a collision through.
        """
        resolved = {
            label: os.path.normpath(getattr(self, label))
            for label in ("baseline_path", "results_path", "report_path")
        }
        for label, path in resolved.items():
            for other, other_path in resolved.items():
                if label >= other:
                    continue  # each pair once
                # Either direction of nesting is fatal, so both are checked —
                # results inside report_path is as destructive as the reverse.
                nested = path.startswith(other_path + os.sep) or other_path.startswith(
                    path + os.sep
                )
                if path == other_path or nested:
                    raise ValueError(
                        f"{label} {path!r} overlaps {other} {other_path!r} — the run "
                        "directories must be separate: test clears results and report "
                        "regenerates its tree, so an overlap destroys the other's files"
                    )
        return self
