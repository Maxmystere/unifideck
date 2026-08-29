"""core/binaries/bundled.py — where a bundled tool lives on THIS machine.

The plugin ships four store CLIs that are built per architecture —
legendary and gogdl as Python zipapps carrying native wheels, nile and
comet as plain ELFs — plus winetricks and the umu zipapp, which are not.
Every caller used to spell the path the same way::

    plugin_dir / "bin" / "gogdl"

which is right exactly as long as one build can be the only build. It no
longer can: an x86_64 tree on an ARM host resolves that path happily and
then fails at exec time (``Exec format error``) or, worse, at *import*
time inside a zipapp, several layers below anything that knows what an
architecture is.

So the layout gained one degree of freedom and this module owns it:

``bin/<tool>``
    The canonical path, and what a single-architecture build writes. Its
    contents are whatever ``build-plugin.sh`` was told to target.
``bin/<tool>-<arch>``
    An optional architecture-explicit copy, preferred over the canonical
    path when it matches this host. It is what makes a *universal* tree
    possible — one install directory serving both architectures — and
    what a store-side installer can drop in beside an existing x86_64
    binary without overwriting it.

Resolution therefore reads: the arch-explicit copy if there is one, else
the canonical path, and an ELF that is provably built for another machine
is skipped rather than handed out (see :func:`unifideck.utils.arch
.runnable_here` for why "provably" is doing real work in that sentence).
The last resort is still ``bin/<tool>``: a caller that is about to log
"not found" should name the path the user expects to see, not one of the
variants they have never heard of.
"""

from __future__ import annotations

import logging
from pathlib import Path

from unifideck.utils.arch import Arch, host_arch, normalize_arch, runnable_here

logger = logging.getLogger(__name__)

#: The bundled tools that have a per-architecture build. winetricks (a
#: shell script), the umu zipapp and the Windows helper EXEs under
#: ``bin/`` are deliberately absent — they are the same file everywhere,
#: and inventing arch variants for them would only add paths that never
#: exist.
ARCH_SPECIFIC_TOOLS = frozenset({"legendary", "gogdl", "nile", "comet"})

#: One line naming the architecture ``build-plugin.sh`` targeted, written
#: into the zip next to the binaries. Diagnostics read it to answer "was
#: this plugin even built for this machine?" — a question no other file
#: in the install can answer once the binaries are in place.
BUILD_ARCH_STAMP = "ARCH"


def bin_dir(plugin_dir: str | Path) -> Path:
    """The plugin's ``bin/`` directory."""
    return Path(plugin_dir) / "bin"


def build_arch(plugin_dir: str | Path) -> Arch:
    """The architecture this install was built for, per its ``bin/ARCH`` stamp.

    :attr:`Arch.OTHER` when the stamp is missing (every build before ARM
    support existed) or unreadable — never a guess, so a caller reporting
    it says "unknown" rather than naming an architecture nobody wrote
    down.
    """
    try:
        stamped = (bin_dir(plugin_dir) / BUILD_ARCH_STAMP).read_text(
            encoding="utf-8",
        )
    except OSError:
        return Arch.OTHER
    return normalize_arch(stamped.strip())


def bundled_binary_candidates(
    plugin_dir: str | Path, name: str,
) -> list[Path]:
    """Every path ``name`` could occupy, most specific first.

    Ordering is the whole contract: an arch-explicit copy that matches
    this host beats the canonical path, because in a universal tree the
    canonical path holds the *other* architecture's build.
    """
    base = bin_dir(plugin_dir)
    arch = host_arch()
    candidates: list[Path] = []
    if name in ARCH_SPECIFIC_TOOLS and arch is not Arch.OTHER:
        candidates.append(base / f"{name}-{arch.value}")
    candidates.append(base / name)
    return candidates


def bundled_binary_path(plugin_dir: str | Path, name: str) -> Path:
    """The path a caller should use for bundled tool ``name``.

    The first candidate that exists and is not provably foreign wins. If
    nothing qualifies the canonical ``bin/<tool>`` comes back regardless
    — callers report "missing"/"not executable" against the path a user
    can actually look for, and a foreign binary that is the only one
    present is worth naming in that message too.
    """
    candidates = bundled_binary_candidates(plugin_dir, name)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if not runnable_here(candidate):
            logger.warning(
                "[bundled] %s is built for another architecture — this host "
                "is %s. Install the %s build of the plugin, or drop an "
                "architecture-specific copy at %s-<arch>.",
                candidate, host_arch().value, host_arch().value,
                bin_dir(plugin_dir) / name,
            )
            continue
        return candidate
    return candidates[-1]


def bundled_binary_search_paths(
    plugin_dir: str | Path, name: str,
) -> list[str]:
    """:func:`bundled_binary_candidates` as strings, for ``CLITool.search_paths``.

    :class:`~unifideck.core.binaries.binary_resolver.BinaryResolver` walks
    Tier-1 paths in order and takes the first executable one, so handing
    it the ordered candidate list gives arch preference for free — and
    keeps its own "not found" fall-through to PATH intact.
    """
    return [str(p) for p in bundled_binary_candidates(plugin_dir, name)]
