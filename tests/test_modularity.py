"""Guards that keep the reusable packages reusable.

``fsx.anonymize`` and ``fsx.extract`` are meant to be lifted into other
applications. That only holds if they never reach back into the financial-
statement domain (``fsx.hgb`` / ``fsx.analysis``) or the Level-1/2/3 schemas.
These tests scan the actual imports so the boundary cannot rot silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

import fsx

_ROOT = Path(fsx.__file__).parent


def _imported_modules(package: str) -> set[str]:
    """Every module name imported (absolute or relative) anywhere in a package."""
    pkg_dir = _ROOT / package
    names: set[str] = set()
    for path in pkg_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                # Resolve a relative import (level>0) to its absolute target.
                if node.level:
                    parts = ["fsx", package]
                    # one extra level climbs out of the package itself
                    climb = node.level - 1
                    base = parts[: len(parts) - climb] if climb else parts
                    mod = ".".join(base + ([node.module] if node.module else []))
                    names.add(mod)
                elif node.module:
                    names.add(node.module)
    return names


_FORBIDDEN = ("fsx.hgb", "fsx.analysis", "fsx.schemas")


def test_extract_does_not_depend_on_domain():
    imported = _imported_modules("extract")
    # Domain-free *and* free of its anonymise sibling (anonymiser is duck-typed),
    # so the generic table extractor can be reused with no other fsx package.
    forbidden = (*_FORBIDDEN, "fsx.anonymize")
    leaks = [m for m in imported if any(m.startswith(f) for f in forbidden)]
    assert leaks == [], f"fsx.extract must stay self-contained, but imports {leaks}"


def test_anonymize_is_self_contained():
    imported = _imported_modules("anonymize")
    # No domain coupling and no heavy/optional runtime deps (pure stdlib core):
    forbidden = (*_FORBIDDEN, "fitz", "ocrmypdf")
    leaks = [m for m in imported if any(m.startswith(f) for f in forbidden)]
    assert leaks == [], f"fsx.anonymize must stay self-contained, but imports {leaks}"


def test_reusable_packages_import_without_domain():
    # Importing the reusable facades must not require the domain layer.
    import importlib

    for pkg in ("fsx.extract", "fsx.anonymize"):
        importlib.import_module(pkg)
