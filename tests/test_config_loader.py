"""Task 3 — contract + logic tests for `load_config` (`peeksy/config/loader.py`).

Contract source: `peeksy/config/CODEMANIFEST` (read-only). The routine
`load_config(path: str) -> Suite` lives at `loader.py` and must be importable
from the `peeksy.config` facade.

Contract tests come first (TDD): facade exposure, signature, and return type.
Logic tests below pin the site-folder discovery rules (explicit `*.yml` vs
folder), the page/component walk (names from folder/file stems, name-sorted
components, non-`*.yml` files ignored), path normalization against the site
folder, and the rejection cases from the design's scenario table.
"""

import inspect
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import peeksy.config as config_facade
from peeksy.config import Suite, load_config

SUITE_META = {
    "name": "example.com",
    "baseline_path": "baselines",
    "results_path": "results",
    "report_path": "report",
    "threshold": 0.1,
    "tolerance": 0.5,
}

PAGE_META = {
    "url": "https://example.com/",
    "setup": [{"click": "#cookie"}],
}

COMPONENT_META = {
    "selector": "#header",
    "viewports": [{"width": 1280, "height": 720}],
}


def write_site(
    tmp_path: Path,
    *,
    suite_meta: dict | None = None,
    page_meta: dict | None = None,
    component_meta: dict | None = None,
    suite_filename: str = "suite.yml",
    page_name: str = "home",
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Materialize a minimal valid site under `tmp_path` and return its folder.

    `extra_files` maps site-relative paths to raw file bodies, written after
    the standard layout so a test can add pages/components or override files.
    """
    site = tmp_path / "sites" / "example.com"
    page_dir = site / "pages" / page_name
    page_dir.mkdir(parents=True)
    site.joinpath(suite_filename).write_text(
        yaml.safe_dump({**SUITE_META, **(suite_meta or {})}), encoding="utf-8"
    )
    page_dir.joinpath("page.yml").write_text(
        yaml.safe_dump(page_meta if page_meta is not None else PAGE_META), encoding="utf-8"
    )
    page_dir.joinpath("header.yml").write_text(
        yaml.safe_dump(component_meta if component_meta is not None else COMPONENT_META),
        encoding="utf-8",
    )
    for rel, body in (extra_files or {}).items():
        target = site / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return site


# --------------------------------------------------------------------------
# Contract tests — facade + signature + return type
# --------------------------------------------------------------------------


def test_facade_exposes_load_config() -> None:
    assert "load_config" in config_facade.__all__
    assert config_facade.load_config is load_config
    assert inspect.isfunction(load_config)


def test_load_config_signature_matches_contract() -> None:
    signature = inspect.signature(load_config)
    assert list(signature.parameters) == ["path"]
    assert signature.parameters["path"].annotation is str
    assert signature.return_annotation is Suite


def test_load_config_returns_suite_instance(tmp_path: Path) -> None:
    suite = load_config(str(write_site(tmp_path)))
    assert isinstance(suite, Suite)


# --------------------------------------------------------------------------
# Logic tests — site-folder discovery
# --------------------------------------------------------------------------


def test_load_config_builds_suite_from_site_folder(tmp_path: Path) -> None:
    """Design scenario: folder arg → suite.yml inside; names from folder/file."""
    site = write_site(tmp_path)
    suite = load_config(str(site))
    assert suite.name == "example.com"
    assert suite.threshold == 0.1
    assert suite.tolerance == 0.5
    assert [page.name for page in suite.pages] == ["home"]
    page = suite.pages[0]
    assert page.url == "https://example.com/"
    assert page.wait_until == "networkidle"
    assert [(action.kind, action.target, action.value) for action in page.setup] == [
        ("click", "#cookie", None)
    ]
    assert [component.name for component in page.components] == ["header"]
    component = page.components[0]
    assert component.selector == "#header"
    assert component.viewports[0].width == 1280
    assert component.viewports[0].height == 720
    assert component.mask_selectors == []
    assert component.threshold is None
    assert component.tolerance is None
    assert component.setup == []


def test_load_config_accepts_explicit_suite_file_under_any_name(tmp_path: Path) -> None:
    """An explicitly passed `*.yml` IS the suite file; its parent is the site dir."""
    site = write_site(tmp_path, suite_filename="peeksy.yml")
    suite = load_config(str(site / "peeksy.yml"))
    assert suite.name == "example.com"
    assert [page.name for page in suite.pages] == ["home"]
    assert suite.baseline_path == str(site / "baselines")


def test_load_config_accepts_suite_yml_path_inside_folder(tmp_path: Path) -> None:
    site = write_site(tmp_path)
    suite = load_config(str(site / "suite.yml"))
    assert suite.name == "example.com"
    assert [page.name for page in suite.pages] == ["home"]


def test_load_config_resolves_relative_paths_against_site_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CWD must not influence path resolution — the design's CWD-independence gate."""
    site = write_site(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    suite = load_config(str(site))
    assert suite.baseline_path == str(site / "baselines")
    assert suite.results_path == str(site / "results")
    assert suite.report_path == str(site / "report")
    for value in (suite.baseline_path, suite.results_path, suite.report_path):
        assert Path(value).is_absolute()
        assert value.startswith(str(site))
        assert not value.startswith(str(elsewhere))


def test_load_config_absolute_paths_pass_through_unchanged(tmp_path: Path) -> None:
    site = write_site(
        tmp_path,
        suite_meta={
            "baseline_path": "/abs/baselines",
            "results_path": "/abs/results",
            "report_path": "/abs/report",
        },
    )
    suite = load_config(str(site))
    assert suite.baseline_path == "/abs/baselines"
    assert suite.results_path == "/abs/results"
    assert suite.report_path == "/abs/report"


def test_load_config_relative_suite_path_is_resolved_from_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative `path` argument resolves against the CWD, then paths anchor to the site."""
    site = write_site(tmp_path)
    monkeypatch.chdir(site)
    suite = load_config("suite.yml")
    assert suite.baseline_path == str(site / "baselines")


# --------------------------------------------------------------------------
# Logic tests — the page/component walk
# --------------------------------------------------------------------------


def test_load_config_walks_multiple_pages_and_sorts_components(tmp_path: Path) -> None:
    site = write_site(
        tmp_path,
        extra_files={
            "pages/home/aaa.yml": yaml.safe_dump(COMPONENT_META),
            "pages/home/zzz.yml": yaml.safe_dump(COMPONENT_META),
            "pages/about/page.yml": yaml.safe_dump({"url": "https://example.com/about"}),
            "pages/about/nav.yml": yaml.safe_dump(COMPONENT_META),
        },
    )
    suite = load_config(str(site))
    assert [page.name for page in suite.pages] == ["about", "home"]
    assert [component.name for component in suite.pages[0].components] == ["nav"]
    # name-sorted regardless of the order the files happen to be listed in
    assert [component.name for component in suite.pages[1].components] == [
        "aaa",
        "header",
        "zzz",
    ]


def test_load_config_allows_same_component_name_across_pages(tmp_path: Path) -> None:
    site = write_site(
        tmp_path,
        extra_files={
            "pages/about/page.yml": yaml.safe_dump({"url": "https://example.com/about"}),
            "pages/about/header.yml": yaml.safe_dump(COMPONENT_META),
        },
    )
    suite = load_config(str(site))
    assert [page.name for page in suite.pages] == ["about", "home"]
    for page in suite.pages:
        assert [component.name for component in page.components] == ["header"]


def test_load_config_ignores_non_yml_files_and_nested_dirs(tmp_path: Path) -> None:
    site = write_site(
        tmp_path,
        extra_files={
            "pages/home/notes.txt": "not a component",
            "pages/home/header.yaml": yaml.safe_dump(COMPONENT_META),
            "pages/home/README.md": "# docs",
        },
    )
    suite = load_config(str(site))
    assert [component.name for component in suite.pages[0].components] == ["header"]


def test_load_config_reads_component_overrides_and_masks(tmp_path: Path) -> None:
    site = write_site(
        tmp_path,
        component_meta={
            "selector": "#header",
            "mask_selectors": [".timestamp"],
            "viewports": [{"width": 1280, "height": 720}, {"width": 375, "height": 667}],
            "threshold": 0.2,
            "tolerance": 1.5,
            "setup": [{"reload": {}}, {"fill": ["#search", "shoes"]}],
        },
    )
    component = load_config(str(site)).pages[0].components[0]
    assert component.mask_selectors == [".timestamp"]
    assert [f"{viewport.width}x{viewport.height}" for viewport in component.viewports] == [
        "1280x720",
        "375x667",
    ]
    assert component.threshold == 0.2
    assert component.tolerance == 1.5
    assert [(action.kind, action.target, action.value) for action in component.setup] == [
        ("reload", None, None),
        ("fill", "#search", "shoes"),
    ]


def test_load_config_supports_deep_link_page(tmp_path: Path) -> None:
    site = write_site(
        tmp_path,
        page_meta={"url": None, "setup": [{"open": "https://example.com/login"}]},
    )
    page = load_config(str(site)).pages[0]
    assert page.url is None
    assert [(action.kind, action.value) for action in page.setup] == [
        ("open", "https://example.com/login")
    ]


def test_load_config_empty_pages_dir_yields_empty_pages(tmp_path: Path) -> None:
    site = write_site(tmp_path)
    shutil.rmtree(site / "pages" / "home")
    suite = load_config(str(site))
    assert suite.pages == []
    assert suite.name == "example.com"


def test_load_config_missing_pages_dir_yields_empty_pages(tmp_path: Path) -> None:
    site = write_site(tmp_path)
    shutil.rmtree(site / "pages")
    suite = load_config(str(site))
    assert suite.pages == []


# --------------------------------------------------------------------------
# Logic tests — IO errors
# --------------------------------------------------------------------------


def test_load_config_missing_path_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "does-not-exist"))


def test_load_config_folder_without_suite_yml_raises_file_not_found(tmp_path: Path) -> None:
    site = write_site(tmp_path)
    (site / "suite.yml").unlink()
    with pytest.raises(FileNotFoundError, match="suite.yml"):
        load_config(str(site))


def test_load_config_missing_page_yml_raises_file_not_found(tmp_path: Path) -> None:
    site = write_site(tmp_path)
    (site / "pages" / "home" / "page.yml").unlink()
    with pytest.raises(FileNotFoundError, match="page.yml"):
        load_config(str(site))


def test_load_config_non_yml_file_arg_raises_not_a_directory(tmp_path: Path) -> None:
    stray = tmp_path / "config.json"
    stray.write_text("{}", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        load_config(str(stray))


def test_load_config_broken_yaml_raises_yaml_error(tmp_path: Path) -> None:
    """Syntactically broken YAML never reaches Pydantic — the CLI catches YAMLError."""
    site = write_site(tmp_path)
    (site / "suite.yml").write_text("name: [unclosed\n  - : :\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_config(str(site))


def test_load_config_non_mapping_suite_yml_raises_value_error(tmp_path: Path) -> None:
    """A non-mapping document is not a Pydantic shape error — the loader names the file."""
    site = write_site(tmp_path)
    (site / "suite.yml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="suite.yml"):
        load_config(str(site))


def test_load_config_missing_suite_meta_field_raises_validation_error(tmp_path: Path) -> None:
    site = write_site(tmp_path)
    (site / "suite.yml").write_text(
        yaml.safe_dump({"name": "x", "threshold": 0.1, "tolerance": 0.5}),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="baseline_path"):
        load_config(str(site))


# --------------------------------------------------------------------------
# Logic tests — the design's 8 invalid shapes + duplicate names
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("suite_meta", "page_meta", "component_meta", "expected"),
    [
        pytest.param(
            None,
            {"url": "https://example.com/", "wait_until": "eager"},
            None,
            "wait_until",
            id="1-bad-wait-until",
        ),
        pytest.param(
            None,
            {"url": None, "setup": [{"click": "#cookie"}]},
            None,
            "open",
            id="2-null-url-without-leading-open",
        ),
        pytest.param(
            None,
            {
                "url": "https://example.com/",
                "setup": [{"open": "https://example.com/login"}],
            },
            None,
            "open",
            id="3-url-with-leading-open",
        ),
        pytest.param(
            None,
            {"url": "https://example.com/", "setup": [{"fill": "#search"}]},
            None,
            "fill",
            id="4-fill-bare-string",
        ),
        pytest.param({"threshold": 5}, None, None, "threshold", id="5-threshold-out-of-range"),
        pytest.param({"tolerance": 150}, None, None, "tolerance", id="6-tolerance-out-of-range"),
        pytest.param(
            None,
            None,
            {"selector": "#header", "viewports": []},
            "viewports",
            id="7-empty-viewports",
        ),
        pytest.param(
            None,
            None,
            {"selector": "#header", "viewports": [{"width": 0, "height": 720}]},
            "width",
            id="8-non-positive-viewport",
        ),
    ],
)
def test_load_config_rejects_invalid_page_and_action_shapes(
    tmp_path: Path,
    suite_meta: dict | None,
    page_meta: dict | None,
    component_meta: dict | None,
    expected: str,
) -> None:
    site = write_site(
        tmp_path,
        suite_meta=suite_meta,
        page_meta=page_meta,
        component_meta=component_meta,
    )
    with pytest.raises(ValidationError) as excinfo:
        load_config(str(site))
    assert expected in str(excinfo.value)


def test_load_config_rejects_duplicate_component_name_within_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two same-named components in ONE page must not silently collide on the
    baseline path / testCaseId.

    Two `*.yml` entries cannot share a stem inside one directory, so the
    duplicate is injected at the discovery step (the only place the walk could
    ever yield one — e.g. a case-insensitive filesystem or a future recursive
    walk). The assertion is on what `load_config` surfaces, not on the helper.
    """
    from peeksy.config import loader

    site = write_site(tmp_path)
    real_component_files = loader._component_files

    def duplicated(page_dir: Path) -> list[Path]:
        files = real_component_files(page_dir)
        return files + files if files else files

    monkeypatch.setattr(loader, "_component_files", duplicated)
    with pytest.raises(ValidationError) as excinfo:
        load_config(str(site))
    message = str(excinfo.value)
    assert "header" in message
    assert "home" in message
