#!/usr/bin/env python3
"""Validate the Unifideck architecture invariants that keep drifting.

Three silent drifts have recurred through the 0.7.x series and are worth
machine-enforcing rather than re-discovering by hand every release:

1. The RPC mixin set is documented inconsistently (the docstring says
   "eleven", ``rpc/mixins/__init__.py`` re-exports 13, the docs say 18,
   ``main.py`` composes 20). The one invariant that matters is that
   ``main.py``'s composed mixins and ``__init__.py``'s ``__all__`` agree.

2. The store list drifts (docs said "five stores" long after Battle.net
   became the sixth). ``bootstrap/cache_registry._STORE_CACHES`` is the
   single code source of truth; it must match the store subdirectories
   on disk.

3. The wrapper/CLI distinction is maintained in two hand-written tables:
   each store's ``StoreInfo(uses_wine=...)`` and the ``WRAPPER_STORES``
   frozenset in ``launcher/wrapper_stores.py``. Nothing links them, so a
   new store can set one without the other.

A fourth check (dead RPC) is heuristic and report-only: it prints methods
with no obvious frontend caller but does not fail the gate, because a name
can legitimately be invoked through a dynamically-keyed route.

Stdlib-only on purpose: the script runs in CI before dependencies are
installed and must not import the plugin (which would execute store
constructors and touch the network).

Usage::

    python3 scripts/validate_architecture.py

Exit 0 when clean, 1 on a hard mismatch.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PY = REPO_ROOT / "py_modules" / "unifideck"
SRC = REPO_ROOT / "src"

# Directories under stores/ that are not stores.
_NON_STORE_DIRS = {"shared", "__pycache__"}


def _fail(msg: str) -> None:
    print(f"::error::{msg}")


def parse_mixin_bases(main_path: Path) -> set[str]:
    """Return the mixin base names composed in ``class Plugin(...)``."""
    tree = ast.parse(main_path.read_text(), filename=str(main_path))
    bases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Plugin":
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id.endswith("Mixin"):
                    bases.add(base.id)
    return bases


def parse_all(mixins_init_path: Path) -> set[str]:
    """Return the names listed in ``rpc/mixins/__init__.py``'s ``__all__``."""
    tree = ast.parse(mixins_init_path.read_text(), filename=str(mixins_init_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "__all__" in targets and isinstance(node.value, ast.List):
                return {
                    elt.value
                    for elt in node.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                }
    return set()


def parse_store_caches(cache_registry_path: Path) -> set[str]:
    """Return the store names from ``_STORE_CACHES`` in cache_registry.py."""
    text = cache_registry_path.read_text()
    match = re.search(
        r"_STORE_CACHES[^=]*=\s*\(([^)]*)\)", text, flags=re.DOTALL
    )
    if not match:
        raise SystemExit(
            f"{cache_registry_path}: could not locate _STORE_CACHES"
        )
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def discover_store_dirs(stores_path: Path) -> set[str]:
    """Return store subdirectories that contain a store module."""
    found: set[str] = set()
    for child in stores_path.iterdir():
        if not child.is_dir() or child.name in _NON_STORE_DIRS:
            continue
        has_store_module = (child / "store.py").exists() or (
            child / f"{child.name}_store.py"
        ).exists()
        if has_store_module:
            found.add(child.name)
    return found


def parse_wrapper_stores(wrapper_stores_path: Path) -> set[str]:
    """Return the contents of ``WRAPPER_STORES`` in launcher/wrapper_stores.py."""
    text = wrapper_stores_path.read_text()
    match = re.search(r"WRAPPER_STORES[^=]*=\s*frozenset\((\{[^}]*\})\)", text)
    if not match:
        raise SystemExit(
            f"{wrapper_stores_path}: could not locate WRAPPER_STORES"
        )
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def find_store_file(stores_path: Path, name: str) -> Path | None:
    """Locate the store module for a store directory name."""
    for candidate in (
        stores_path / name / f"{name}_store.py",
        stores_path / name / "store.py",
    ):
        if candidate.exists():
            return candidate
    return None


def parse_store_info(store_file: Path) -> tuple[str | None, bool]:
    """Return ``(name, uses_wine)`` from a store's ``StoreInfo(...)`` block.

    ``uses_wine`` defaults to ``False`` (the dataclass default) when the
    descriptor omits it, matching ``core/types/domain.py``.
    """
    text = store_file.read_text()
    match = re.search(r"store_info\s*=\s*StoreInfo\((.*?)\n\s*\)", text, flags=re.DOTALL)
    if not match:
        return None, False
    block = match.group(1)
    name_match = re.search(r'name\s*=\s*"([^"]+)"', block)
    name = name_match.group(1) if name_match else None
    wine_match = re.search(r"uses_wine\s*=\s*(True|False)", block)
    uses_wine = wine_match.group(1) == "True" if wine_match else False
    return name, uses_wine


def collect_rpc_methods(mixins_path: Path) -> set[str]:
    """Return public ``async def`` method names on ``*Mixin`` classes.

    ``@auto_wrap_rpc_methods`` wraps every public coroutine on a mixin, so
    a public ``async def`` on a ``*Mixin`` class is the RPC surface. Module
    level helpers (``cleanup_sweeps.py`` etc.) and sync methods are not.
    """
    names: set[str] = set()
    for file in mixins_path.glob("*.py"):
        if file.name == "__init__.py":
            continue
        tree = ast.parse(file.read_text(), filename=str(file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Mixin"):
                continue
            for item in node.body:
                if (
                    isinstance(item, ast.AsyncFunctionDef)
                    and not item.name.startswith("_")
                ):
                    names.add(item.name)
    return names


def find_dead_rpc(methods: set[str]) -> list[str]:
    """Return methods that appear nowhere under ``src/`` (report-only)."""
    haystack = ""
    for file in SRC.rglob("*"):
        if file.is_file() and file.suffix in (".ts", ".tsx"):
            try:
                haystack += file.read_text() + "\n"
            except UnicodeDecodeError:
                continue
    return sorted(name for name in methods if name not in haystack)


def main() -> int:
    main_path = REPO_ROOT / "main.py"
    mixins_init = PY / "rpc" / "mixins" / "__init__.py"
    mixins_dir = PY / "rpc" / "mixins"
    cache_registry = PY / "bootstrap" / "cache_registry.py"
    stores_path = PY / "stores"
    wrapper_stores = PY / "launcher" / "wrapper_stores.py"

    hard_failures = 0

    # Check 1: main.py composed mixins == __all__.
    composed = parse_mixin_bases(main_path)
    exported = parse_all(mixins_init)
    missing = composed - exported
    extra = exported - composed
    if missing or extra:
        hard_failures += 1
        _fail(
            "mixin set drift: "
            f"main.py composes {len(composed)} mixins but "
            f"rpc/mixins/__init__.py __all__ re-exports {len(exported)}"
        )
        if missing:
            _fail(f"  missing from __all__: {sorted(missing)}")
        if extra:
            _fail(f"  in __all__ but not composed: {sorted(extra)}")
    else:
        print(f"OK: {len(composed)} mixins composed == __all__")

    # Check 2: _STORE_CACHES == store directories on disk.
    canonical_stores = parse_store_caches(cache_registry)
    discovered = discover_store_dirs(stores_path)
    if canonical_stores != discovered:
        hard_failures += 1
        _fail(
            "store list drift: "
            f"_STORE_CACHES = {sorted(canonical_stores)} but disk has "
            f"{sorted(discovered)}"
        )
    else:
        print(f"OK: {len(canonical_stores)} stores agree (cache registry == disk)")

    # Check 3: uses_wine == WRAPPER_STORES membership, per store.
    wrapper_set = parse_wrapper_stores(wrapper_stores)
    for name in sorted(discovered):
        store_file = find_store_file(stores_path, name)
        if store_file is None:
            hard_failures += 1
            _fail(f"store '{name}': no store module found")
            continue
        declared_name, uses_wine = parse_store_info(store_file)
        if declared_name is not None and declared_name != name:
            hard_failures += 1
            _fail(
                f"store '{name}': StoreInfo.name = '{declared_name}' "
                f"(should match directory)"
            )
        expected_wrapper = name in wrapper_set
        if uses_wine != expected_wrapper:
            hard_failures += 1
            _fail(
                f"store '{name}': uses_wine={uses_wine} but "
                f"WRAPPER_STORES membership is {expected_wrapper}"
            )
    if hard_failures == 0:
        print("OK: uses_wine agrees with WRAPPER_STORES for every store")

    # Check 4 (report-only): dead RPC.
    methods = collect_rpc_methods(mixins_dir)
    dead = find_dead_rpc(methods)
    if dead:
        print(
            "NOTE (report-only): RPC methods with no obvious frontend caller: "
            + ", ".join(dead)
        )
    else:
        print("OK: no obviously-dead RPC methods found")

    if hard_failures:
        print(f"\n{hard_failures} architecture invariant(s) violated")
        return 1
    print("\narchitecture invariants OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
