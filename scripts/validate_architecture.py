#!/usr/bin/env python3
"""Validate the Unifideck architecture invariants that keep drifting.

Several silent drifts have recurred through the 0.7.x series and are worth
machine-enforcing rather than re-discovering by hand every release:

1. The RPC mixin set was documented inconsistently: at the 2026-08 audit
   ``main.py``'s docstring said "eleven", ``rpc/mixins/__init__.py``
   re-exported 13, and the docs said 18, against a class that composed 20.
   The one invariant that matters is that ``main.py``'s composed mixins and
   ``__init__.py``'s ``__all__`` agree; that is check 1, and it is the only
   place the set is stated. Check 5 keeps it that way (see below).

2. The store list drifts (docs said "five stores" long after Battle.net
   became the sixth). ``bootstrap/cache_registry._STORE_CACHES`` is the
   single code source of truth; it must match the store subdirectories
   on disk.

3. A store's ``StoreInfo.name`` must match its directory, since the registry
   auto-discovers by directory and every other check keys on that name.

   This check used to have a second arm, comparing each store's
   ``StoreInfo(uses_wine=...)`` against ``WRAPPER_STORES``. Audit §3.1 asked
   for that link; re-deriving it found ``uses_wine`` had no reader anywhere,
   so the gate was enforcing agreement on a value that could not change
   behaviour. The field is gone and ``get_store_infos`` derives
   ``client_runs_in_prefix`` from ``WRAPPER_STORES``, which makes the arm
   unfailable — a re-added literal now raises ``TypeError`` at construction.
   Check 9 replaces it with the wrapper-store link that was actually
   unguarded.

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

5. A mixin count written into prose goes stale on the next mixin churn, and
   check 1 cannot see it. This happened three times in 0.7.x: audit §2.1
   found four disagreeing figures, the remediation hand-corrected them all
   to 20, and the §1.2 dead-RPC pass then deleted three empty mixins in the
   same release, making every corrected site wrong again. Correcting the
   number is the approach that failed; not writing it down is check 5.

   The set is enumerated in exactly two places, both machine-checked by
   check 1: ``main.py``'s ``class Plugin(...)`` and ``__init__.py``'s
   ``__all__``. Everywhere else must name the source rather than the figure.

   Opt out with an inline ``mixin-count-ok: <reason>`` marker on the line or
   the line above it, for a deliberate historical citation. Same convention
   as ``# no-frontend-caller:`` above and ``# unwired:`` in
   ``validate_event_wiring.py``: the reason lives next to the text.

6. A layer count written into prose has the same failure mode, and audit §2.2
   found four mutually contradictory ones, two of them saying "five" while
   enumerating six. The diagram in ``docs/architecture.md`` is the single
   enumeration. Banned like the mixin count; opt out with
   ``layer-count-ok: <reason>``.

7. A store count in prose is *verified* rather than banned, which is the one
   place these checks differ. Many live sites state a count correctly while
   explaining something, so the figure is compared against the store
   directories on disk and only a wrong one fails. Only a total claim is
   examined ("all N stores", "N store connectors"), because a count below the
   total is nearly always naming a subset. Opt out with
   ``store-count-ok: <reason>``.

8. A subpackage missing from the layer map reads as nonexistent to whoever
   plans the next change. Audit §2.5 found the tables listing 6 of 20
   ``core/`` modules and 10 of 15 ``services/`` packages, with
   ``compatibility`` (the ProtonDB path) and ``support_bundle`` (Capture
   Logs) both invisible. Check 8 asserts membership rather than trusting a
   hand-maintained table, since those drift exactly the way a count does.

9. Adding a wrapper store means adding a row in several hand-written
   dispatch maps, and a missing row fails silently rather than loudly. The
   Python-side maps are pinned by tests (``wrapper_prefix_probe._SPECS``,
   ``tests/unit/test_wrapper_store_dispatch_coverage.py``); the frontend's
   ``CLIENT_STOREFRONTS`` in ``services/store/StorefrontLauncher.ts`` is not
   reachable from pytest, so it is checked here. A wrapper store missing
   from it makes the cart button do nothing at all — no error, no toast.

10. A store can declare where its vendor client writes logs and then never
    salvage them. Audit §3.3 filed this as redundancy ("only Battle.net
    consumes ``prefix_forensics``"); re-deriving it found a complete, measured
    Ubisoft row in ``VENDOR_LOG_GLOBS`` that nothing called, so every failed
    Ubisoft install deleted UPC's own logs with the prefix — for a wrapper
    store the prefix *is* the install. This is the audit's most repeated
    defect class: the material shipped, the delivery channel was never
    built. Check 10 asks whether the store's **own package** calls
    ``preserve_vendor_logs``, so one store cannot vouch for another. Opt out
    with ``# no-vendor-salvage: <reason>``.

Checks 5 to 7 share one scanner, ``scan_prose``. Their regexes are narrow on
purpose and each carries the false positive that shaped it: a gate that fires
on correct, untouched code gets switched off rather than fixed. See the
comment above each pattern, and the parametrised false-positive tests in
``tests/unit/test_validate_architecture.py``.

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

# --- Checks 5-7: architecture facts written into prose ----------------------

# Everything an agent or a contributor reads to learn the architecture.
# ``main.py`` and the mixin package are included deliberately: their
# docstrings are where the original defect lived.
_PROSE_GLOBS = (
    "CLAUDE.md",
    "docs/**/*.md",
    ".claude/skills/**/*.md",
    "main.py",
    "py_modules/unifideck/**/*.py",
    "scripts/*.py",
    ".github/workflows/*.yml",
)

# ``docs/archive/`` is superseded by definition (see CLAUDE.md) and
# ``architecture-audit.md`` is the register whose job is recording the
# historical figures. Both would be pure noise.
_PROSE_EXCLUDE = ("docs/archive/", "docs/architecture-audit.md")

# Kept under the old names: the guard test addresses check 5 by these.
_MIXIN_COUNT_GLOBS = _PROSE_GLOBS
_MIXIN_COUNT_EXCLUDE = _PROSE_EXCLUDE

_MIXIN_COUNT_OK = "mixin-count-ok:"
_LAYER_COUNT_OK = "layer-count-ok:"
_STORE_COUNT_OK = "store-count-ok:"

_CARDINAL = (
    r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty"
)

# Matches a count written next to the word. Every historical instance took
# one of these forms (mixin-count-ok: spec, not a claim about the tree):
# "eleven mixins" / "20 RPC mixins" / "the 20 mixin surfaces"
#
# The lookbehind is load-bearing: without it "Layer-6 RPC mixins" in
# services/__init__.py reads as a count of six, because \b sits happily
# between the hyphen and the digit. It also stops "someone mixins".
#
# A figure separated from the word by other prose is NOT caught. Widening
# the window costs more in false positives than it buys, and the opt-out
# marker covers the deliberate historical citation that would need it.
_MIXIN_COUNT_RE = re.compile(
    rf"(?<![-\w])({_CARDINAL})\s+(?:rpc\s+)?mixin", re.IGNORECASE,
)

# Check 6 — the layer count. Banned outright, like the mixin count: the
# diagram in docs/architecture.md is the single enumeration, and audit §2.2
# found four mutually contradictory prose counts feeding off each other.
#
# The trailing noun is load-bearing, and is the same lesson as the mixin
# lookbehind. ``config/`` legitimately describes a "3-layer merge" (defaults,
# user, code) in seven places, and ``config_manager.py`` a "3-layer
# configuration manager" -- all true, none of them about the architecture
# stack. Requiring an architecture noun after the word separates the two
# without needing seven opt-out markers on correct code. Every historical
# violation named one of those nouns, the last of them being
# layer-count-ok: the spec of this check, quoting the shape it catches
# "the plan's five-layer model" in event_bus/__init__.py.
_LAYER_COUNT_RE = re.compile(
    rf"(?<![-\w.])({_CARDINAL})[- ]layer(?:ed)?\s+"
    r"(?:backend|architecture|stack|model|design)",
    re.IGNORECASE,
)

# Check 7 — the store count. NOT banned, verified: unlike the mixin and layer
# counts, live sites state it as part of explaining something and are
# correct, so the figure is compared against the store directories on disk
# (the same source check 2 uses) and only a WRONG one fails. That catches the
# audit §2.4 defect -- every doc said "five" for a release after Battle.net
# landed -- and keeps catching it from the other side when a seventh arrives.
#
# Only a *total* claim is checked, in the forms below, which are how every
# historical violation was written.
# store-count-ok: the spec of this check, quoting the shapes it catches
#   ("The five store connectors" / "a five-store system")
#
# The narrowing matters more than it looks: a first version matched any
# cardinal before "store" and produced 23 false positives in one run, every
# one of them a correct subset statement -- "Amazon is the one store whose
# sign-in leaves the shared Edge profile", "four stores report credential
# permissions through one channel", "Two stores need this path". A count
# below the total is nearly always naming a subset, so requiring "all" or a
# collection noun is what separates the two. With this form the tree needs no
# opt-out anywhere else, including the drift-guard skill lines that quote
# "five stores" verbatim.
_STORE_COUNT_RE = re.compile(
    rf"\ball\s+({_CARDINAL})\s+stores?\b"
    rf"|(?<![-\w.])({_CARDINAL})[- ]store\s+(?:connector|system)"
    rf"|(?<![-\w.])({_CARDINAL})-store\s+(?:setup|architecture)",
    re.IGNORECASE,
)

_CARDINAL_VALUES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}


def _cardinal_to_int(text: str) -> int | None:
    """Return the integer a cardinal word or numeral denotes, else None."""
    stripped = text.strip().lower()
    if stripped.isdigit():
        return int(stripped)
    return _CARDINAL_VALUES.get(stripped)


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


def parse_store_info(store_file: Path) -> str | None:
    """Return the ``name=`` declared in a store's ``StoreInfo(...)`` block."""
    text = store_file.read_text()
    match = re.search(r"store_info\s*=\s*StoreInfo\((.*?)\n\s*\)", text, flags=re.DOTALL)
    if not match:
        return None
    name_match = re.search(r'name\s*=\s*"([^"]+)"', match.group(1))
    return name_match.group(1) if name_match else None


def parse_client_storefronts(storefront_launcher_path: Path) -> set[str]:
    """Return the store ids keyed in ``CLIENT_STOREFRONTS``.

    The frontend's map of "stores whose shop is a tab inside their own
    Windows client" — i.e. the wrapper stores, restated in TypeScript where
    no pytest can reach it.
    """
    text = storefront_launcher_path.read_text()
    # ``.*?=\s*\{`` rather than ``[^=]*=``: the declaration's type annotation
    # is ``Partial<Record<StoreId, () => Promise<...>>>``, so a no-equals scan
    # stops inside the arrow. ``=\s*\{`` cannot match ``=>`` (no ``{`` after
    # it), so the first hit is the real assignment.
    match = re.search(
        r"const CLIENT_STOREFRONTS\b.*?=\s*\{(.*?)\n\};", text, flags=re.DOTALL
    )
    if not match:
        raise SystemExit(
            f"{storefront_launcher_path}: could not locate CLIENT_STOREFRONTS"
        )
    # Keys sit at exactly two spaces of indent; the arrow bodies below them are
    # indented four, so this cannot pick up a call argument by mistake.
    return set(re.findall(r"^ {2}(\w+):", match.group(1), flags=re.M))


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


NO_SALVAGE_RE = re.compile(r"#\s*no-vendor-salvage:\s*\S")


def parse_vendor_log_stores() -> set[str]:
    """Store keys declared in ``prefix_forensics.VENDOR_LOG_GLOBS``."""
    source = (
        PY / "stores" / "shared" / "prefix_forensics.py"
    ).read_text()
    match = re.search(
        r"VENDOR_LOG_GLOBS[^=]*=\s*\{(.*?)\n\}", source, flags=re.S,
    )
    if match is None:
        _fail("prefix_forensics.py: could not locate VENDOR_LOG_GLOBS")
        raise SystemExit(1)
    # Store keys sit at exactly four spaces of indent; the glob strings
    # inside each tuple are indented eight, so this cannot mistake a glob
    # for a key.
    return set(re.findall(r'^ {4}"(\w+)":', match.group(1), flags=re.M))


def find_unsalvaged_vendor_logs() -> set[str]:
    """Stores that declare vendor log globs but never salvage them.

    The defect class this closes is the most repeated one in the 2026-08
    audit: material written, shipped and documented, with the call site
    never built. ``VENDOR_LOG_GLOBS`` carried a full Ubisoft row — measured
    log paths, ready to use — while nothing in ``stores/ubisoft/`` called
    ``preserve_vendor_logs``, so every failed Ubisoft install deleted UPC's
    own logs along with the prefix. A grep for the globs found them and read
    as covered, which is exactly how it survived a release.

    Deliberately asks whether the *store's own package* calls it, not
    whether the symbol appears anywhere: Battle.net vouching for Ubisoft is
    the failure this is written to prevent.

    Opt out with an inline ``# no-vendor-salvage: <reason>`` marker anywhere
    in the store package, in the house style of ``# no-frontend-caller:``.
    """
    unsalvaged: set[str] = set()
    for store in parse_vendor_log_stores():
        package = PY / "stores" / store
        if not package.is_dir():
            continue
        salvages = False
        exempt = False
        for file in package.rglob("*.py"):
            text = file.read_text()
            if "preserve_vendor_logs(" in text:
                salvages = True
            if NO_SALVAGE_RE.search(text):
                exempt = True
        if not salvages and not exempt:
            unsalvaged.add(store)
    return unsalvaged


def count_exempt_vendor_salvage() -> int:
    """Count ``# no-vendor-salvage:`` markers, printed on every clean run."""
    total = 0
    for store in parse_vendor_log_stores():
        package = PY / "stores" / store
        if not package.is_dir():
            continue
        for file in package.rglob("*.py"):
            total += sum(
                1
                for line in file.read_text().splitlines()
                if NO_SALVAGE_RE.search(line)
            )
    return total


def collect_rpc_methods(mixins_path: Path) -> set[str]:
    """Return public ``async def`` method names on ``*Mixin`` classes.

    ``@auto_wrap_rpc_methods`` wraps every public coroutine on a mixin, so
    a public ``async def`` on a ``*Mixin`` class is the RPC surface. Module
    level helpers and sync methods are not. The class filter is what does
    that work, so a helper module landing in this directory is skipped
    without an allowlist; ``cleanup_sweeps.py`` was the one such module and
    has since moved to ``core/``, where it belonged.

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


def scan_prose(
    root: Path, pattern: re.Pattern[str], marker: str,
) -> list[tuple[str, int, re.Match[str]]]:
    """Return ``(relpath, lineno, match)`` for every hit of ``pattern``.

    Shared by checks 5, 6 and 7 so one scanner owns the file walk, the
    exclusions and the opt-out semantics. Lines carrying ``marker``, on the
    line itself or the line above, are exempt; the line-above form is what
    lets a marker sit in a comment over the line it excuses.
    """
    hits: list[tuple[str, int, re.Match[str]]] = []
    seen: set[Path] = set()
    for glob in _PROSE_GLOBS:
        for path in sorted(root.glob(glob)):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            rel = path.relative_to(root).as_posix()
            if rel.startswith(_PROSE_EXCLUDE):
                continue
            lines = path.read_text(
                encoding="utf-8", errors="replace",
            ).splitlines()
            for lineno, line in enumerate(lines, start=1):
                if marker in line:
                    continue
                if lineno >= 2 and marker in lines[lineno - 2]:
                    continue
                # finditer, not search: a line carrying two counts should
                # report both, or fixing one just re-reds the gate.
                for match in pattern.finditer(line):
                    hits.append((rel, lineno, match))
    return hits


def find_prose_mixin_counts(root: Path) -> list[tuple[str, int, str]]:
    """Return ``(relpath, lineno, matched_text)`` per prose mixin count.

    The mixin set is enumerated in ``main.py``'s ``class Plugin(...)`` and
    ``__init__.py``'s ``__all__``, which check 1 keeps in agreement. Any
    third statement of the figure is unowned by that check and goes stale on
    the next mixin churn -- see the module docstring for the three times it
    did. Lines carrying a ``mixin-count-ok:`` marker, on the line itself or
    the line above, are exempt.
    """
    return [
        (rel, lineno, match.group(0))
        for rel, lineno, match in scan_prose(
            root, _MIXIN_COUNT_RE, _MIXIN_COUNT_OK,
        )
    ]


def find_prose_layer_counts(root: Path) -> list[tuple[str, int, str]]:
    """Return ``(relpath, lineno, matched_text)`` per prose layer count.

    The layer model is drawn once, in ``docs/architecture.md``. Audit §2.2
    found four prose counts contradicting each other and the diagram, two of
    them saying "five" while enumerating six. Opt-out:
    ``layer-count-ok: <reason>``.
    """
    return [
        (rel, lineno, match.group(0))
        for rel, lineno, match in scan_prose(
            root, _LAYER_COUNT_RE, _LAYER_COUNT_OK,
        )
    ]


def find_wrong_store_counts(
    root: Path, actual: int,
) -> list[tuple[str, int, str, int]]:
    """Return ``(relpath, lineno, text, stated)`` per WRONG prose store count.

    A correct figure passes: see ``_STORE_COUNT_RE`` for why this check
    verifies rather than bans. ``actual`` comes from the store directories on
    disk. Opt-out: ``store-count-ok: <reason>``.
    """
    wrong: list[tuple[str, int, str, int]] = []
    for rel, lineno, match in scan_prose(
        root, _STORE_COUNT_RE, _STORE_COUNT_OK,
    ):
        # One group per alternative in _STORE_COUNT_RE; exactly one is set.
        captured = next((g for g in match.groups() if g), None)
        if captured is None:
            continue
        stated = _cardinal_to_int(captured)
        if stated is not None and stated != actual:
            wrong.append((rel, lineno, match.group(0), stated))
    return wrong


def find_undocumented_subpackages(
    root: Path, doc: Path,
) -> list[str]:
    """Return subpackage/module names absent from the architecture doc.

    Audit §2.5: the layer tables listed 6 of 20 ``core/`` modules and 10 of
    15 ``services/`` packages, so whole subsystems (``compatibility``, the
    ProtonDB path; ``support_bundle``, the Capture Logs path) read as
    nonexistent to anyone planning a change. Hand-maintained tables drift the
    same way a hand-maintained count does, so the membership is checked
    rather than trusted.
    """
    if not doc.is_file():
        return []
    text = doc.read_text(encoding="utf-8", errors="replace")
    expected: list[str] = []
    services = root / "py_modules" / "unifideck" / "services"
    if services.is_dir():
        expected += [
            f"services/{p.name}"
            for p in sorted(services.iterdir())
            if p.is_dir() and p.name != "__pycache__"
        ]
    for package in ("core", "event_bus"):
        pkg_dir = root / "py_modules" / "unifideck" / package
        if not pkg_dir.is_dir():
            continue
        expected += [
            f"{package}/{p.name}"
            for p in sorted(pkg_dir.glob("*.py"))
            if p.name != "__init__.py"
        ]
    # Match on the bare name: the doc's tables key on ``artwork/`` or
    # ``cache_manager.py``, not on the full path from the package root.
    return [name for name in expected if name.split("/")[-1] not in text]


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

    # Check 3: StoreInfo.name == its directory name, per store.
    name_failures = 0
    for name in sorted(discovered):
        store_file = find_store_file(stores_path, name)
        if store_file is None:
            name_failures += 1
            _fail(f"store '{name}': no store module found")
            continue
        declared_name = parse_store_info(store_file)
        if declared_name is not None and declared_name != name:
            name_failures += 1
            _fail(
                f"store '{name}': StoreInfo.name = '{declared_name}' "
                f"(should match directory)"
            )
    hard_failures += name_failures
    if name_failures == 0:
        # Counted separately rather than off the running total: gating this
        # line on ``hard_failures == 0`` meant a check-1 or check-2 failure
        # silently suppressed check 3's own result.
        print(f"OK: StoreInfo.name matches its directory for all {len(discovered)} stores")

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

    # Check 5 (hard): the mixin count is not restated in prose.
    prose_counts = find_prose_mixin_counts(REPO_ROOT)
    if prose_counts:
        hard_failures += len(prose_counts)
        for rel, lineno, text in prose_counts:
            _fail(
                f"{rel}:{lineno}: mixin count written into prose "
                f"({text.strip()!r}; main.py composes {len(composed)})"
            )
        print(
            "\n  The mixin set belongs in main.py's class Plugin(...) and\n"
            "  rpc/mixins/__init__.py __all__, and nowhere else. Name that\n"
            "  source instead of the figure, or, for a deliberate historical\n"
            "  citation, mark the line or the line above it:\n"
            "      mixin-count-ok: <reason>"
        )
    else:
        print("OK: no mixin count restated in prose")

    # Check 6 (hard): the layer count is not restated in prose.
    layer_counts = find_prose_layer_counts(REPO_ROOT)
    if layer_counts:
        hard_failures += len(layer_counts)
        for rel, lineno, text in layer_counts:
            _fail(
                f"{rel}:{lineno}: layer count written into prose "
                f"({text.strip()!r})"
            )
        print(
            "\n  The layer model is drawn once, in docs/architecture.md.\n"
            "  Point at that diagram instead of restating a figure, or, for\n"
            "  a deliberate historical citation, mark the line or the line\n"
            "  above it:\n"
            "      layer-count-ok: <reason>"
        )
    else:
        print("OK: no layer count restated in prose")

    # Check 7 (hard): a prose store count agrees with the tree.
    wrong_stores = find_wrong_store_counts(REPO_ROOT, len(discovered))
    if wrong_stores:
        hard_failures += len(wrong_stores)
        for rel, lineno, text, stated in wrong_stores:
            _fail(
                f"{rel}:{lineno}: store count says {stated} "
                f"({text.strip()!r}) but the tree has {len(discovered)}"
            )
        print(
            "\n  Correct the figure, or, for a deliberate historical\n"
            "  citation, mark the line or the line above it:\n"
            "      store-count-ok: <reason>"
        )
    else:
        print(f"OK: every prose store count agrees ({len(discovered)})")

    # Check 8 (hard): every subpackage appears in the architecture doc.
    arch_doc = REPO_ROOT / "docs" / "architecture.md"
    undocumented = find_undocumented_subpackages(REPO_ROOT, arch_doc)
    if undocumented:
        hard_failures += len(undocumented)
        for name in undocumented:
            _fail(f"{name} is absent from docs/architecture.md")
        print(
            "\n  A subsystem missing from the layer map reads as nonexistent\n"
            "  to whoever plans the next change. Add a row for it."
        )
    else:
        print("OK: every services/, core/ and event_bus/ module is documented")

    # Check 9 (hard): the frontend's wrapper-store map covers WRAPPER_STORES.
    wrapper_set = parse_wrapper_stores(wrapper_stores)
    storefronts = parse_client_storefronts(
        SRC / "services" / "store" / "StorefrontLauncher.ts"
    )
    if storefronts != wrapper_set:
        hard_failures += 1
        _fail(
            "wrapper storefront drift: CLIENT_STOREFRONTS = "
            f"{sorted(storefronts)} but WRAPPER_STORES = {sorted(wrapper_set)}"
        )
        print(
            "\n  A wrapper store missing from CLIENT_STOREFRONTS makes its cart\n"
            "  button do nothing — hasStorefront() returns false and the press\n"
            "  is dropped with no error and no toast. A non-wrapper store\n"
            "  present there opens a Windows client that store does not have."
        )
    else:
        print(
            f"OK: CLIENT_STOREFRONTS covers all {len(wrapper_set)} wrapper stores"
        )

    # Check 10 (hard): a store with vendor-log globs actually salvages them.
    unsalvaged = find_unsalvaged_vendor_logs()
    if unsalvaged:
        hard_failures += len(unsalvaged)
        for store in sorted(unsalvaged):
            _fail(
                f"store '{store}' has VENDOR_LOG_GLOBS but never calls "
                "preserve_vendor_logs"
            )
        print(
            "\n  For a wrapper store the prefix IS the install, so a failed\n"
            "  install deletes the vendor client's own logs — the only\n"
            "  first-hand account of why it failed. Writing the globs without\n"
            "  the call reads as covered and collects nothing: Ubisoft's row\n"
            "  sat there unused for a release. Add the call at the site that\n"
            "  removes the prefix, or opt out with '# no-vendor-salvage:'."
        )
    else:
        exempt = count_exempt_vendor_salvage()
        suffix = f" ({exempt} exempt)" if exempt else ""
        print(
            "OK: every store with vendor log globs salvages them"
            f"{suffix}"
        )

    if hard_failures:
        print(f"\n{hard_failures} architecture invariant(s) violated")
        return 1
    print("\narchitecture invariants OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
