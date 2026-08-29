"""Which CPU architecture is this — x86_64, aarch64, or neither.

py_modules/unifideck/utils/arch.py

Unifideck was written for the Steam Deck, where "the architecture" was a
constant nobody had to name. It is not one any more: Valve's ARM hardware
runs the same SteamOS session, the same Decky Loader and the same plugins,
and every asset this plugin fetches or ships has a per-architecture build —
the store CLIs (legendary, gogdl, nile, comet), GE-Proton's release
tarballs, umu's Steam Runtime variants, the Python wheels vendored into
``py_modules/``.

Picking the wrong one does not fail cleanly. A foreign ELF is ``OSError:
[Errno 8] Exec format error`` from deep inside a store connector; a foreign
zipapp gets *further* — it runs under the host's native Python and then
dies importing a native module built for the other machine. Neither
message says "wrong architecture", which is why this module exists: one
answer to "what is this machine", shared by everything that has to choose.

Three verdicts, not two, for the same reason :mod:`unifideck.utils.vulkan`
has three: an architecture we have no builds for is a real answer and must
not be rounded to x86_64. A caller that would have to guess should say so
and degrade instead.

``UNIFIDECK_ARCH`` overrides the detected value. It exists for developers
building or testing a foreign-arch tree on an x86_64 workstation — the
build script exports it — and is deliberately the highest-priority signal
so a test never has to monkeypatch ``platform.machine``.

Stdlib only, never raises. Imported from the out-of-process launcher under
the SYSTEM python (3.10-3.14) as well as from the backend.
"""

from __future__ import annotations

import logging
import os
import platform
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class Arch(Enum):
    """A CPU architecture Unifideck ships builds for.

    ``.value`` is the *canonical spelling* — the one upstream projects
    use in their Linux asset names (``legendary_linux_x86_64``,
    ``comet-aarch64-unknown-linux-gnu``) and the one this plugin uses in
    filenames, so a value can be interpolated into a path or a URL
    without a second translation table.

    A plain ``Enum``, like :class:`unifideck.utils.device.DeviceType`:
    every comparison in the tree is on identity (``arch is
    Arch.X86_64``), and ``.value`` is read only where a name is being
    formatted into a path, a URL or a log line.
    """

    X86_64 = "x86_64"
    AARCH64 = "aarch64"
    OTHER = "other"


#: Every spelling of an architecture we may be handed, mapped to its
#: canonical :class:`Arch`. ``uname -m`` alone would need only the first
#: entry of each group, but the same question gets answered by Debian's
#: package arch (``amd64``/``arm64``), by Python's own ``sysconfig``
#: platform tags, and by a 32-bit userspace on a 64-bit ARM kernel
#: (``armv8l``) — all of which reach here through config, env vars or
#: manifests. Compared lower-cased.
_ALIASES: dict[str, Arch] = {
    "x86_64": Arch.X86_64,
    "amd64": Arch.X86_64,
    "x64": Arch.X86_64,
    "x86-64": Arch.X86_64,
    "aarch64": Arch.AARCH64,
    "arm64": Arch.AARCH64,
    "armv8l": Arch.AARCH64,
    "armv8b": Arch.AARCH64,
    "arm64e": Arch.AARCH64,
}

#: Env var that wins over detection. See the module docstring.
_ARCH_ENV = "UNIFIDECK_ARCH"

# ── ELF identification ───────────────────────────────────────
# e_ident[0:4] then e_machine at offset 0x12 (little-endian ELF; the
# only kind either of these architectures produces). We read the header
# rather than shelling out to ``file(1)``, which is not installed on a
# stock SteamOS image.
_ELF_MAGIC = b"\x7fELF"
_E_MACHINE_OFFSET = 0x12
_E_MACHINE = {
    0x3E: Arch.X86_64,  # EM_X86_64
    0xB7: Arch.AARCH64,  # EM_AARCH64
}


def normalize_arch(machine: str | None) -> Arch:
    """Map any spelling of an architecture onto a canonical :class:`Arch`.

    Unknown or empty input is :attr:`Arch.OTHER` — never a guess. See
    :data:`_ALIASES` for why one plugin needs this many spellings.
    """
    if not machine:
        return Arch.OTHER
    return _ALIASES.get(machine.strip().lower(), Arch.OTHER)


def host_arch() -> Arch:
    """Return the architecture this process is running on.

    ``UNIFIDECK_ARCH`` first (developer/build override), then
    ``platform.machine()``. An unrecognised machine resolves to
    :attr:`Arch.OTHER` and logs once at INFO — a plugin on a machine we
    have no builds for should say so in the log it will be asked for,
    not pretend to be a Deck.
    """
    override = os.environ.get(_ARCH_ENV)
    if override:
        forced = normalize_arch(override)
        if forced is not Arch.OTHER:
            return forced
        logger.warning(
            "[arch] %s=%r is not an architecture Unifideck knows — ignoring it",
            _ARCH_ENV, override,
        )
    machine = platform.machine()
    arch = normalize_arch(machine)
    if arch is Arch.OTHER:
        logger.info(
            "[arch] unsupported machine %r — architecture-specific assets "
            "(store CLIs, Proton, umu) have no build for it", machine,
        )
    return arch


def host_arch_name() -> str:
    """The canonical name of the host architecture, or the raw ``uname -m``.

    Diagnostics want a *string*, and on an unsupported machine
    ``"other"`` throws away the one fact worth reporting. So the raw
    machine name is passed through when it maps to no known
    architecture.
    """
    arch = host_arch()
    if arch is not Arch.OTHER:
        return str(arch.value)
    raw: str = os.environ.get(_ARCH_ENV) or platform.machine() or "unknown"
    return raw.strip()


def is_arm() -> bool:
    """True on 64-bit ARM.

    A convenience for the many call sites whose only question is "is this
    the machine where the x86_64 asset would be the wrong one".
    """
    return host_arch() is Arch.AARCH64


def elf_arch(path: str | Path) -> Arch | None:
    """Return the architecture an ELF file was built for.

    ``None`` means "no answer": the file is unreadable, is not an ELF at
    all (legendary and gogdl ship Python zipapps — a ZIP, not an ELF —
    and winetricks is a shell script), or is an ELF for a machine outside
    :data:`_E_MACHINE`. Callers must treat ``None`` as "cannot tell", not
    as a mismatch; refusing to run everything we cannot classify would
    reject the majority of what we bundle.
    """
    try:
        with Path(path).open("rb") as fh:
            header = fh.read(_E_MACHINE_OFFSET + 2)
    except OSError:
        return None
    if len(header) < _E_MACHINE_OFFSET + 2 or not header.startswith(_ELF_MAGIC):
        return None
    machine = int.from_bytes(
        header[_E_MACHINE_OFFSET:_E_MACHINE_OFFSET + 2], "little",
    )
    return _E_MACHINE.get(machine)


def runnable_here(path: str | Path) -> bool:
    """False only when ``path`` is provably an ELF for another architecture.

    The asymmetry is the point. A wrong-arch ELF is worth catching early
    — the alternative is ``Exec format error`` surfacing as a store
    outage — but "cannot tell" (a zipapp, a script, an unreadable file)
    must stay runnable, because that is what most of the bundled tools
    are.
    """
    built_for = elf_arch(path)
    if built_for is None:
        return True
    return built_for is host_arch()
