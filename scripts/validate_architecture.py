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

4. RPC methods accumulate with no frontend caller. The 2026-08 audit found
   29 of 102 — 28% of the surface — including a whole "DiagnosticsPanel"
   that was never built. This check *used* to be report-only and asked only
   "does the snake_case name appear anywhere in ``src/`` text", which missed
   14 of the 29: a method declared in ``rpcRoutes`` whose constant nothing
   references passed. It now asks both questions and is a hard gate.

   Opt out per method with an inline ``# no-frontend-caller: <reason>``
   comment on the ``async def`` line or the line above it. The reason lives
   next to the code rather than in an allowlist file, and the exemption
   count is printed on every run so growth is visible rather than silent.

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


NO_CALLER_RE = re.compile(r"#\s*no-frontend-caller:\s*\S")


def _has_no_caller_marker(lines: list[str], def_lineno: int) -> bool:
    """Is this ``async def`` exempted by a ``# no-frontend-caller:`` marker?

    Checks the ``def`` line itself, then walks upward through the contiguous
    run of comment lines directly above it. Walking the whole block (rather
    than a fixed one-line window) is what lets a real explanation span
    several lines — and these exemptions need explaining, so a one-liner
    limit would just push the reason somewhere it can rot.

    ``def_lineno`` is ast's 1-based line number for the ``async def``.
    """
    idx = def_lineno - 1
    if idx < 0 or idx >= len(lines):
        return False
    if NO_CALLER_RE.search(lines[idx]):
        return True
    for i in range(idx - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped.startswith("#"):
            break
        if NO_CALLER_RE.search(lines[i]):
            return True
    return False


def collect_rpc_methods(mixins_path: Path) -> set[str]:
    """Return public ``async def`` method names on ``*Mixin`` classes.

    ``@auto_wrap_rpc_methods`` wraps every public coroutine on a mixin, so
    a public ``async def`` on a ``*Mixin`` class is the RPC surface. Module
    level helpers (``cleanup_sweeps.py`` etc.) and sync methods are not.

    Methods carrying an inline ``# no-frontend-caller: <reason>`` marker —
    on the ``async def`` line or the line directly above it — are excluded
    from the dead-RPC check. The marker is named for exactly what the check
    tests, so it stays honest whether the reason is "only the launcher
    subprocess calls this" or "dead, tracked by audit register 4a".
    """
    names: set[str] = set()
    for file in mixins_path.glob("*.py"):
        if file.name == "__init__.py":
            continue
        source = file.read_text()
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Mixin"):
                continue
            for item in node.body:
                if (
                    not isinstance(item, ast.AsyncFunctionDef)
                    or item.name.startswith("_")
                ):
                    continue
                if _has_no_caller_marker(lines, item.lineno):
                    continue
                names.add(item.name)
    return names


def count_exempt_rpc(mixins_path: Path) -> int:
    """Count methods carrying a ``# no-frontend-caller:`` marker.

    Printed on every clean run so the exemption set cannot grow quietly —
    the failure mode of any allowlist. A rising number here is the signal
    that the gate is being worked around rather than satisfied.
    """
    total = 0
    for file in mixins_path.glob("*.py"):
        if file.name == "__init__.py":
            continue
        total += sum(
            1 for line in file.read_text().splitlines() if NO_CALLER_RE.search(line)
        )
    return total


def _route_constants() -> dict[str, str]:
    """Map ``snake_case`` RPC name → its ``rpcRoutes`` camelCase key.

    Parsed from ``src/api/rpc-routes.ts``, the single source of truth for
    the route table. A method absent from this map has no declared route.
    """
    routes = SRC / "api" / "rpc-routes.ts"
    if not routes.is_file():
        return {}
    pairs = re.findall(r"(\w+):\s*\"([a-z0-9_]+)\"", routes.read_text())
    return {snake: camel for camel, snake in pairs}


def find_dead_rpc(methods: set[str]) -> list[str]:
    """Return RPC methods with no live frontend caller.

    Two independent ways a method can be dead, and the original version of
    this check only caught the first:

    1. **Undeclared** — the name appears nowhere in ``src/`` at all.
    2. **Declared but unreferenced** — it has an ``rpcRoutes`` entry, but no
       component mentions that constant. The route table alone keeps the
       name "present" in ``src/`` text, which is exactly how 14 dead methods
       hid from the pre-2026-08 version of this check.

    ``rpc-routes.ts`` is excluded from the haystack for both questions, so a
    row in the table can never vouch for itself.
    """
    haystack = ""
    for file in sorted(SRC.rglob("*")):
        if not file.is_file() or file.suffix not in (".ts", ".tsx"):
            continue
        if file.name == "rpc-routes.ts":
            continue
        try:
            haystack += file.read_text() + "\n"
        except UnicodeDecodeError:
            continue

    routes = _route_constants()
    dead: list[str] = []
    for name in methods:
        camel = routes.get(name)
        if camel is not None:
            # Declared: the route constant must be referenced somewhere.
            if not re.search(rf"rpcRoutes\.{re.escape(camel)}\b", haystack):
                dead.append(name)
            continue
        # Undeclared: a raw quoted string is the only remaining way in.
        if not re.search(rf"[\"']{re.escape(name)}[\"']", haystack):
            dead.append(name)
    return sorted(dead)


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

    # Check 4 (hard): dead RPC.
    methods = collect_rpc_methods(mixins_dir)
    dead = find_dead_rpc(methods)
    if dead:
        hard_failures += len(dead)
        for name in dead:
            _fail(f"RPC '{name}' has no frontend caller")
        print(
            "\n  Delete the method and its rpcRoutes row, or mark it at the\n"
            "  definition with the reason nothing in src/ calls it:\n"
            "      # no-frontend-caller: <reason>\n"
            "      async def "
            + dead[0]
            + "(self, ...)"
        )
    else:
        exempt = count_exempt_rpc(mixins_dir)
        note = f" ({exempt} exempt)" if exempt else ""
        print(
            f"OK: all {len(methods)} checked RPC methods "
            f"have a frontend caller{note}"
        )

    if hard_failures:
        print(f"\n{hard_failures} architecture invariant(s) violated")
        return 1
    print("\narchitecture invariants OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
