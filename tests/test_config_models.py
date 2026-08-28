"""Task 2 — contract + logic tests for the `peeksy.config` models.

Contract source: `peeksy/config/CODEMANIFEST` (read-only). The five entities
`Viewport`, `Action`, `Component`, `Page`, `Suite` all live at `models.py` and
must be importable from the `peeksy.config` facade.

Contract tests come first (TDD): they pin facade exposure, constructor
signatures, and property types. Logic tests below them pin the validators —
kind Literal, numeric ranges, per-page name uniqueness, wait_until enum,
url<->open exclusivity, name-sorted components, and the short-form Action
parsing rules.
"""

import inspect
from typing import Annotated, get_args, get_origin

import pytest
from pydantic import BaseModel, ValidationError

import peeksy.config as config_facade
from peeksy.config import Action, Component, Page, Suite, Viewport


def declared(annotation: object) -> object:
    """Strip Pydantic constraint metadata (`Field(gt=...)` surfaces as Annotated)."""
    if get_origin(annotation) is Annotated:
        return get_args(annotation)[0]
    return annotation


ACTION_KINDS = (
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
)
WAIT_UNTIL_VALUES = ("networkidle", "domcontentloaded", "load")


# --------------------------------------------------------------------------
# Contract tests — facade + signatures + property types
# --------------------------------------------------------------------------


def test_facade_exposes_all_five_models() -> None:
    # Task 3 adds `load_config` to the same facade, so assert the five models
    # as a superset rather than exact equality.
    exported_models = {"Viewport", "Action", "Component", "Page", "Suite"}
    assert exported_models <= set(config_facade.__all__)
    for name in exported_models:
        exported = getattr(config_facade, name)
        assert inspect.isclass(exported)
        assert issubclass(exported, BaseModel)
        assert exported.__module__ == "peeksy.config.models"


def _params(cls: type) -> dict[str, inspect.Parameter]:
    return dict(inspect.signature(cls).parameters)


def test_viewport_signature_matches_contract() -> None:
    params = _params(Viewport)
    assert list(params) == ["width", "height"]
    assert declared(params["width"].annotation) is int
    assert declared(params["height"].annotation) is int


def test_action_signature_matches_contract() -> None:
    params = _params(Action)
    assert list(params) == ["kind", "target", "value"]
    assert declared(params["kind"].annotation) is not None
    assert get_args(params["kind"].annotation) == ACTION_KINDS
    assert declared(params["target"].annotation) == (str | None)
    assert declared(params["value"].annotation) == (str | None)


def test_component_signature_matches_contract() -> None:
    params = _params(Component)
    assert list(params) == [
        "name",
        "selector",
        "mask_selectors",
        "viewports",
        "threshold",
        "tolerance",
        "setup",
    ]
    assert declared(params["name"].annotation) is str
    assert declared(params["selector"].annotation) is str
    assert declared(params["mask_selectors"].annotation) == list[str]
    assert declared(params["viewports"].annotation) == list[Viewport]
    assert params["viewports"].default is inspect.Parameter.empty
    assert declared(params["threshold"].annotation) == (float | None)
    assert declared(params["tolerance"].annotation) == (float | None)
    assert declared(params["setup"].annotation) == list[Action]


def test_page_signature_matches_contract() -> None:
    params = _params(Page)
    assert list(params) == ["name", "url", "wait_until", "setup", "components"]
    assert declared(params["name"].annotation) is str
    assert declared(params["url"].annotation) == (str | None)
    assert declared(params["wait_until"].annotation) is not None
    assert get_args(params["wait_until"].annotation) == WAIT_UNTIL_VALUES
    assert declared(params["setup"].annotation) == list[Action]
    assert declared(params["components"].annotation) == list[Component]


def test_suite_signature_matches_contract() -> None:
    params = _params(Suite)
    assert list(params) == [
        "name",
        "pages",
        "baseline_path",
        "results_path",
        "report_path",
        "threshold",
        "tolerance",
    ]
    assert declared(params["name"].annotation) is str
    assert declared(params["pages"].annotation) == list[Page]
    assert declared(params["baseline_path"].annotation) is str
    assert declared(params["results_path"].annotation) is str
    assert declared(params["report_path"].annotation) is str
    assert declared(params["threshold"].annotation) is float
    assert declared(params["tolerance"].annotation) is float


def test_properties_readable_with_declared_types() -> None:
    viewport = Viewport(width=1280, height=720)
    action = Action(kind="click", target="#cookie", value=None)
    component = Component(
        name="header",
        selector="#header",
        mask_selectors=[".timestamp"],
        viewports=[viewport],
        threshold=0.2,
        tolerance=1.5,
        setup=[action],
    )
    page = Page(
        name="home",
        url="https://example.com/",
        wait_until="networkidle",
        setup=[],
        components=[component],
    )
    suite = Suite(
        name="example",
        pages=[page],
        baseline_path="/tmp/baselines",
        results_path="/tmp/results",
        report_path="/tmp/report",
        threshold=0.1,
        tolerance=0.5,
    )

    assert viewport.width == 1280
    assert viewport.height == 720
    assert action.kind == "click"
    assert action.target == "#cookie"
    assert action.value is None
    assert component.name == "header"
    assert component.selector == "#header"
    assert component.mask_selectors == [".timestamp"]
    assert component.viewports == [Viewport(width=1280, height=720)]
    assert component.threshold == 0.2
    assert component.tolerance == 1.5
    assert component.setup == [Action(kind="click", target="#cookie", value=None)]
    assert page.name == "home"
    assert page.url == "https://example.com/"
    assert page.wait_until == "networkidle"
    assert page.components == [component]
    assert suite.name == "example"
    assert suite.pages == [page]
    assert suite.baseline_path == "/tmp/baselines"
    assert suite.results_path == "/tmp/results"
    assert suite.report_path == "/tmp/report"
    assert suite.threshold == 0.1
    assert suite.tolerance == 0.5

    assert isinstance(viewport.width, int)
    assert isinstance(component.threshold, float)
    assert isinstance(suite.tolerance, float)
    assert isinstance(page.components, list)
    assert isinstance(component.viewports[0], Viewport)


# --------------------------------------------------------------------------
# Logic tests — positive
# --------------------------------------------------------------------------

VP = Viewport(width=1280, height=720)


def make_component(name: str = "header", **overrides) -> Component:
    fields: dict[str, object] = {
        "name": name,
        "selector": "#header",
        "mask_selectors": [],
        "viewports": [VP],
        "threshold": None,
        "tolerance": None,
        "setup": [],
    }
    fields.update(overrides)
    return Component(**fields)  # type: ignore[arg-type]


def make_page(name: str = "home", **overrides) -> Page:
    fields: dict[str, object] = {
        "name": name,
        "url": "https://example.com/",
        "wait_until": "networkidle",
        "setup": [],
        "components": [],
    }
    fields.update(overrides)
    return Page(**fields)  # type: ignore[arg-type]


def make_suite(**overrides) -> Suite:
    fields: dict[str, object] = {
        "name": "example",
        "pages": [],
        "baseline_path": "/tmp/baselines",
        "results_path": "/tmp/results",
        "report_path": "/tmp/report",
        "threshold": 0.1,
        "tolerance": 0.5,
    }
    fields.update(overrides)
    return Suite(**fields)  # type: ignore[arg-type]


def test_every_action_kind_constructs_with_explicit_fields() -> None:
    explicit = {
        "click": ("#x", None),
        "hover": (".menu", None),
        "scroll_to": ("#main", None),
        "scroll_by": (None, "300"),
        "fill": ("#search", "shoes"),
        "press": (None, "Enter"),
        "select": ("#country", "RU"),
        "wait": (None, "500"),
        "open": (None, "https://example.com/login"),
        "reload": (None, None),
    }
    for kind, (target, value) in explicit.items():
        action = Action(kind=kind, target=target, value=value)  # type: ignore[arg-type]
        assert action.kind == kind
        assert action.target == target
        assert action.value == value


def test_every_wait_until_value_accepted() -> None:
    for strategy in WAIT_UNTIL_VALUES:
        assert make_page(wait_until=strategy).wait_until == strategy


def test_page_and_suite_defaults_apply() -> None:
    page = make_page()
    assert page.wait_until == "networkidle"
    assert page.setup == []
    assert page.components == []
    component = make_component()
    assert component.mask_selectors == []
    assert component.setup == []
    assert component.threshold is None
    assert component.tolerance is None


# --------------------------------------------------------------------------
# Logic tests — negative (parametrized ValidationError)
# --------------------------------------------------------------------------

BAD_VIEWPORTS = [
    pytest.param({"width": 0, "height": 720}, id="width-zero"),
    pytest.param({"width": 1280, "height": -1}, id="height-negative"),
    pytest.param({"width": 1280}, id="height-missing"),
]


@pytest.mark.parametrize("bad_viewport", BAD_VIEWPORTS)
def test_viewport_rejects_non_positive_dimensions(bad_viewport: dict) -> None:
    with pytest.raises(ValidationError):
        Viewport(**bad_viewport)


@pytest.mark.parametrize("kind", ["explode", "Click", "", "goto"])
def test_action_rejects_kind_outside_the_closed_set(kind: str) -> None:
    with pytest.raises(ValidationError):
        Action(kind=kind, target=None, value=None)


@pytest.mark.parametrize(
    ("threshold", "tolerance"),
    [
        pytest.param(5, None, id="threshold-above-1"),
        pytest.param(0, None, id="threshold-zero"),
        pytest.param(1, None, id="threshold-equals-1"),
        pytest.param(-0.1, None, id="threshold-negative"),
    ],
)
def test_component_rejects_out_of_range_threshold(threshold: float, tolerance: None) -> None:
    with pytest.raises(ValidationError):
        make_component(threshold=threshold)


@pytest.mark.parametrize("tolerance", [150, 0, -1, 101])
def test_component_rejects_out_of_range_tolerance(tolerance: float) -> None:
    with pytest.raises(ValidationError):
        make_component(tolerance=tolerance)


@pytest.mark.parametrize(
    "viewports",
    [
        pytest.param([], id="empty"),
        pytest.param([{"width": 0, "height": 720}], id="non-positive-dimension"),
    ],
)
def test_component_rejects_empty_or_invalid_viewports(viewports: list) -> None:
    with pytest.raises(ValidationError):
        make_component(viewports=viewports)


def test_component_viewports_is_required() -> None:
    with pytest.raises(ValidationError):
        Component(name="header", selector="#header")


def test_page_rejects_duplicate_component_names() -> None:
    with pytest.raises(ValidationError):
        make_page(components=[make_component("header"), make_component("header")])


def test_page_rejects_wait_until_outside_enum() -> None:
    with pytest.raises(ValidationError):
        make_page(wait_until="eager")


def test_page_without_url_requires_leading_open() -> None:
    with pytest.raises(ValidationError):
        make_page(url=None, setup=[Action(kind="click", target="#x", value=None)])


def test_page_without_url_and_empty_setup_rejected() -> None:
    with pytest.raises(ValidationError):
        make_page(url=None, setup=[])


def test_page_with_url_rejects_leading_open() -> None:
    with pytest.raises(ValidationError):
        make_page(
            url="https://example.com/",
            setup=[Action(kind="open", target=None, value="https://other.example/")],
        )


@pytest.mark.parametrize("threshold", [5, 0, 1, -0.5])
def test_suite_rejects_out_of_range_threshold(threshold: float) -> None:
    with pytest.raises(ValidationError):
        make_suite(threshold=threshold)


@pytest.mark.parametrize("tolerance", [150, 0, -1])
def test_suite_rejects_out_of_range_tolerance(tolerance: float) -> None:
    with pytest.raises(ValidationError):
        make_suite(tolerance=tolerance)


# --------------------------------------------------------------------------
# Logic tests — edge
# --------------------------------------------------------------------------


def test_same_component_name_on_two_pages_is_accepted() -> None:
    suite = make_suite(
        pages=[
            make_page("home", components=[make_component("header")]),
            make_page("about", components=[make_component("header")]),
        ],
    )
    assert [page.name for page in suite.pages] == ["home", "about"]
    for page in suite.pages:
        assert [component.name for component in page.components] == ["header"]


def test_components_come_out_name_sorted_regardless_of_input_order() -> None:
    page = make_page(
        components=[
            make_component("sidebar"),
            make_component("header"),
            make_component("footer"),
            make_component("actions"),
        ]
    )
    assert [component.name for component in page.components] == [
        "actions",
        "footer",
        "header",
        "sidebar",
    ]


def test_deep_link_page_with_leading_open_is_valid() -> None:
    page = make_page(
        url=None,
        setup=[
            Action(kind="open", target=None, value="https://example.com/login"),
            Action(kind="click", target="#x", value=None),
        ],
    )
    assert page.url is None
    assert page.setup[0].kind == "open"


def test_open_may_appear_mid_setup_when_url_is_set() -> None:
    """Only a LEADING open conflicts with a set url — mid-setup open is a redirect."""
    page = make_page(
        setup=[
            Action(kind="click", target="#x", value=None),
            Action(kind="open", target=None, value="https://example.com/next"),
        ],
    )
    assert page.setup[1].kind == "open"


def test_suite_tolerance_boundary_values_accepted() -> None:
    """tolerance is (0..100] — 100 is inclusive; threshold is (0..1) — both ends open."""
    assert make_suite(tolerance=100).tolerance == 100
    assert make_component(tolerance=100).tolerance == 100
    assert make_suite(threshold=0.99).threshold == 0.99


# --------------------------------------------------------------------------
# Logic tests — short-form Action parsing (feeds Task 3's loader)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param({"click": "#cookie"}, ("click", "#cookie", None), id="click"),
        pytest.param({"hover": ".menu"}, ("hover", ".menu", None), id="hover"),
        pytest.param({"scroll_to": "#main"}, ("scroll_to", "#main", None), id="scroll_to"),
        pytest.param(
            {"open": "https://example.com/login"},
            ("open", None, "https://example.com/login"),
            id="open",
        ),
        pytest.param({"press": "Enter"}, ("press", None, "Enter"), id="press"),
        pytest.param({"scroll_by": "300"}, ("scroll_by", None, "300"), id="scroll_by"),
        pytest.param({"fill": ["#search", "shoes"]}, ("fill", "#search", "shoes"), id="fill"),
        pytest.param({"select": ["#country", "RU"]}, ("select", "#country", "RU"), id="select"),
        pytest.param(
            {"press": ["#search", "Enter"]}, ("press", "#search", "Enter"), id="press-on-element"
        ),
        pytest.param({"scroll_by": [0, 300]}, ("scroll_by", None, "0,300"), id="scroll_by-xy"),
        pytest.param({"wait": {}}, ("wait", None, None), id="wait-default"),
        pytest.param({"wait": None}, ("wait", None, None), id="wait-none"),
        pytest.param({"wait": "#loader"}, ("wait", "#loader", None), id="wait-selector"),
        pytest.param(
            {"wait": {"selector": "#modal", "hidden": True}},
            ("wait", "#modal", "hidden"),
            id="wait-hidden",
        ),
        pytest.param({"reload": {}}, ("reload", None, None), id="reload"),
        pytest.param(
            {"kind": "click", "target": "#x", "value": None}, ("click", "#x", None), id="explicit"
        ),
    ],
)
def test_short_form_action_parses_per_kind_rules(raw: dict, expected: tuple) -> None:
    action = Action(**raw) if "kind" in raw else Action.model_validate(raw)
    assert (action.kind, action.target, action.value) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param({"fill": "#search"}, id="fill-bare-string"),
        pytest.param({"select": "#country"}, id="select-bare-string"),
        pytest.param({"fill": ["#search"]}, id="fill-one-element"),
        pytest.param({"fill": ["#search", "a", "b"]}, id="fill-three-elements"),
        pytest.param({"click": ["#a", "#b"]}, id="click-list"),
        pytest.param({"reload": "#x"}, id="reload-with-target"),
        pytest.param({"wait": {"hidden": True}}, id="wait-hidden-no-selector"),
        pytest.param({"wait": True}, id="wait-bool"),
        pytest.param({"click": "#a", "hover": "#b"}, id="two-kinds-one-item"),
    ],
)
def test_short_form_action_rejects_malformed_shapes(raw: dict) -> None:
    with pytest.raises(ValidationError):
        Action.model_validate(raw)


def test_action_field_dict_passes_through_untouched() -> None:
    """The validator must not mangle an already-explicit field dict."""
    action = Action.model_validate({"kind": "wait", "target": "#x", "value": "hidden"})
    assert action.kind == "wait"
    assert action.target == "#x"
    assert action.value == "hidden"


def test_wait_with_target_rejects_discardable_values() -> None:
    """`wait` + `target` never pauses, so a millisecond value would be silently
    discarded by `run_wait` — the natural "wait for it, then settle" reading is
    a config error instead."""
    with pytest.raises(ValidationError, match="takes 'hidden'"):
        Action.model_validate({"kind": "wait", "target": "#x", "value": "500"})


@pytest.mark.parametrize(
    ("raw", "field"),
    [
        pytest.param({"kind": "click", "target": "", "value": None}, "target", id="click"),
        pytest.param({"kind": "fill", "target": "#q", "value": ""}, "value", id="fill"),
        pytest.param({"kind": "open", "target": None, "value": ""}, "value", id="open"),
        pytest.param({"kind": "press", "target": None, "value": " "}, "value", id="press-space"),
    ],
)
def test_action_rejects_empty_strings(raw: dict, field: str) -> None:
    """An empty `target`/`value` validated today and surfaced as a Playwright
    locator error mid-run — or, for `press`, silently became a keyboard-level
    press with no element. It must fail at load, like every other config typo."""
    with pytest.raises(ValidationError, match=f"{field} cannot be empty"):
        Action.model_validate(raw)


def test_component_rejects_empty_selector_and_suite_rejects_empty_name() -> None:
    """Same failure class as an empty action field: a `selector: ""` is a
    Playwright error mid-run, an empty suite name writes blank Allure labels."""
    with pytest.raises(ValidationError, match="selector"):
        Component.model_validate(
            {"name": "header", "selector": "", "viewports": [{"width": 1, "height": 1}]}
        )
    with pytest.raises(ValidationError, match="name"):
        Suite.model_validate(
            {
                "name": "",
                "pages": [],
                "baseline_path": "/b",
                "results_path": "/r",
                "report_path": "/rep",
                "threshold": 0.1,
                "tolerance": 0.5,
            }
        )
