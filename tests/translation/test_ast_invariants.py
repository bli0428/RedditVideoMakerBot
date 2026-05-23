"""Static AST tests asserting architectural invariants.

These tests walk Python source files with the ``ast`` module and assert that
import-removal and isolation invariants introduced by the claude-translation
spec are preserved.

Validates: Requirements 1.5, 1.6, 2.1, 4.6, 9.4, 10.2, 10.3, 10.4,
           10.7, 10.8, 15.2, 15.3, 16.5
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Iterator

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]  # repo root

_EXCLUDE_DIRS = {".git", "venv", "__pycache__", ".hypothesis", ".mypy_cache"}


def _iter_py_files(base: Path) -> Iterator[Path]:
    """Yield every *.py file under *base*, skipping excluded directories."""
    for dirpath, dirnames, filenames in os.walk(base):
        # Prune excluded directories in-place so os.walk doesn't descend
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
        for fname in filenames:
            if fname.endswith(".py"):
                yield Path(dirpath) / fname


def _parse(path: Path) -> ast.Module:
    """Parse *path* and return its AST, raising AssertionError on syntax error."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise AssertionError(f"Syntax error in {path}: {exc}") from exc


def _imported_names(tree: ast.Module, module_level_only: bool = False) -> set[str]:
    """Return the set of module names imported in *tree*.

    Handles both ``import foo`` and ``from foo import bar`` (and dotted names
    like ``import foo.bar`` — the root ``foo`` is recorded).

    Args:
        tree: Parsed AST module.
        module_level_only: When True, only consider imports that appear
            directly at module scope (i.e., as direct children of the
            ``ast.Module`` body), not imports inside function or class bodies.
            This is used to distinguish a module-level ``import posttextparser``
            (forbidden) from a local import inside an orchestrator function
            (permitted per Req 16.1/16.3).
    """
    names: set[str] = set()
    nodes: list[ast.AST]
    if module_level_only:
        nodes = list(tree.body)
    else:
        nodes = list(ast.walk(tree))

    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                # "import translators" → "translators"
                # "import foo.bar"     → "foo"
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # "from utils.posttextparser import …" → "utils"
                # We also record the full dotted name for precise matching.
                names.add(node.module.split(".")[0])
                names.add(node.module)
    return names


def _has_attribute(tree: ast.Module, attr: str) -> bool:
    """Return True if any ``Attribute`` node in *tree* has ``attr == attr``."""
    return any(
        isinstance(node, ast.Attribute) and node.attr == attr
        for node in ast.walk(tree)
    )


# ---------------------------------------------------------------------------
# 1. No `translators` import in the four legacy call-site modules
#    Req 10.2, 10.3, 10.4
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel_path", [
    "TTS/engine_wrapper.py",
    "video_creation/screenshot_downloader.py",
    "TTS/GTTS.py",
])
def test_no_translators_import_in_legacy_modules(rel_path: str) -> None:
    """Req 10.2, 10.3, 10.4 — legacy call-site modules must not import translators."""
    path = ROOT / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path} does not exist in this checkout")
    tree = _parse(path)
    imported = _imported_names(tree)
    assert "translators" not in imported, (
        f"{rel_path} still imports 'translators'. "
        "Remove the import per Req 10.2/10.3/10.4."
    )


def test_no_translators_import_in_final_video() -> None:
    """Req 10.4 — video_creation/final_video.py must not import translators."""
    path = ROOT / "video_creation" / "final_video.py"
    if not path.exists():
        # The file was removed / renamed as part of the card-rendering-refactor;
        # the invariant is trivially satisfied.
        pytest.skip("video_creation/final_video.py does not exist — invariant trivially satisfied")
    tree = _parse(path)
    imported = _imported_names(tree)
    assert "translators" not in imported, (
        "video_creation/final_video.py still imports 'translators'. "
        "Remove the import per Req 10.4."
    )


# ---------------------------------------------------------------------------
# 2. No `posttextparser` import in the scraper modules
#    Req 10.7, 10.8, 15.2, 15.3
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel_path", [
    "reddit/subreddit.py",
    "batch.py",
])
def test_no_posttextparser_import_in_scraper_modules(rel_path: str) -> None:
    """Req 10.7, 10.8, 15.2, 15.3 — scraper modules must not import posttextparser.

    Note: ``batch.py`` is both a scraper module (``build_reddit_object``) and
    an orchestrator (``make_one_video``).  Req 15.4 forbids the module-level
    import; Req 16.1/16.3 permit the orchestrator to call ``posttextparser``
    via a local import inside the orchestrator function.  This test therefore
    checks only module-level (top-of-file) imports, not local imports inside
    function bodies.
    """
    path = ROOT / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path} does not exist in this checkout")
    tree = _parse(path)
    # Only check module-level imports (direct children of ast.Module.body)
    imported = _imported_names(tree, module_level_only=True)
    # Check both the short module name and the full dotted path
    assert "posttextparser" not in imported, (
        f"{rel_path} has a module-level import of 'posttextparser'. "
        "Remove the top-level import per Req 10.7/10.8/15.2/15.3."
    )
    assert "utils.posttextparser" not in imported, (
        f"{rel_path} has a module-level import of 'utils.posttextparser'. "
        "Remove the top-level import per Req 10.7/10.8/15.2/15.3."
    )


# ---------------------------------------------------------------------------
# 3. No `posttextparser` reference anywhere under utils/translation/
#    Req 9.4
# ---------------------------------------------------------------------------

def test_no_posttextparser_in_translation_package() -> None:
    """Req 9.4 — utils/translation/ must not reference posttextparser."""
    translation_dir = ROOT / "utils" / "translation"
    assert translation_dir.is_dir(), (
        "utils/translation/ directory not found — package not yet created?"
    )
    violations: list[str] = []
    for py_file in _iter_py_files(translation_dir):
        tree = _parse(py_file)
        imported = _imported_names(tree)  # full walk — no local imports allowed either
        if "posttextparser" in imported or "utils.posttextparser" in imported:
            violations.append(str(py_file.relative_to(ROOT)))
    assert not violations, (
        "The following utils/translation/ files reference posttextparser "
        f"(Req 9.4): {violations}"
    )


# ---------------------------------------------------------------------------
# 4. Only utils/translation/anthropic_client.py may import the `anthropic` SDK
#    Req 1.5, 1.6, 2.1
# ---------------------------------------------------------------------------

def test_anthropic_sdk_only_in_anthropic_client() -> None:
    """Req 1.5, 1.6, 2.1 — only anthropic_client.py may import the anthropic SDK."""
    allowed = ROOT / "utils" / "translation" / "anthropic_client.py"
    violations: list[str] = []

    for py_file in _iter_py_files(ROOT):
        if py_file.resolve() == allowed.resolve():
            continue  # this file is explicitly allowed
        tree = _parse(py_file)
        imported = _imported_names(tree)
        if "anthropic" in imported:
            violations.append(str(py_file.relative_to(ROOT)))

    assert not violations, (
        "The following files import the 'anthropic' SDK outside of "
        f"utils/translation/anthropic_client.py (Req 1.5, 1.6, 2.1): {violations}"
    )


# ---------------------------------------------------------------------------
# 5. Translation_Service must not branch on `storymodemethod`
#    Req 4.6
# ---------------------------------------------------------------------------

def test_service_has_no_storymodemethod_attribute_access() -> None:
    """Req 4.6 — service.py must not access .storymodemethod."""
    service_path = ROOT / "utils" / "translation" / "service.py"
    assert service_path.exists(), "utils/translation/service.py not found"
    tree = _parse(service_path)
    assert not _has_attribute(tree, "storymodemethod"), (
        "utils/translation/service.py contains an Attribute node with "
        "attr == 'storymodemethod'. Translation_Service must not branch on "
        "storymodemethod (Req 4.6)."
    )
