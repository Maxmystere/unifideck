"""core/binaries/binary_signatures.py — SHA256 allowlist for bundled CLI tools.

Moved from core/ to core/binaries/ (colocated with
binary_resolver and cli_timeouts). Clean break: no shim in core/.

This module provides a simple allowlist of known-good SHA256
hashes for the bundled binaries that ship inside the plugin tree.
At plugin startup, `verify_bundled_binary()` computes the hash of
each bin/<tool> and compares it against the allowlist. Mismatches
are logged at ERROR and the tool is marked as untrusted so stores
can refuse to use it.

Scope limitation (by design):
  - Only bundled binaries under `bin/` are verified. System
    binaries resolved via PATH (e.g., user-installed legendary)
    are explicitly out of scope — they're trusted by the OS's
    own package manager, not by Unifideck.
  - The hash list is maintained by hand in `_KNOWN_HASHES` below.
    Updating a bundled binary requires updating this list in the
    same commit — otherwise the plugin will refuse to use the new
    binary and log an error. This is intentional friction.
  - Every entry is per-architecture. The same tool at the same
    version is a different file on x86_64 and on aarch64 — a
    different ELF for nile and comet, a different zipapp (the
    native wheels inside differ) for legendary and gogdl — so one
    hash per tool would report every ARM install as tampered. The
    architecture is taken from the file's own path when it carries
    one (``bin/nile-aarch64``) and from the host otherwise, which
    is what a single-architecture build ships.

Reference: Audit point C5 — BinaryResolver lacks signature/hash
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from unifideck.utils.arch import Arch, host_arch, normalize_arch

logger = logging.getLogger(__name__)


# Allowlist of known-good SHA256 hashes for bundled binaries.
#
# Maintenance protocol: when bumping a bundled binary, compute the
# New hash with `sha256sum bin/<tool>` and update the value here
# IN THE SAME COMMIT as the binary update. Keep old hashes out —
# the allowlist exists to block unknown binaries, not to
# grandfather past versions.
_KNOWN_HASHES: dict[str, dict[str, str]] = {
    # Populated per-release, keyed tool → architecture → hash. A
    # missing tool or architecture means "no reference hash declared
    # yet" — verify_bundled_binary returns None in that case so early
    # development doesn't fail builds.
    #
    # These MUST equal the ``sha256hash`` of the matching entry in
    # package.json's ``remote_binary`` / ``remote_binary_aarch64`` arrays:
    # Decky verifies the download against that value at install time, and
    # this verifies the file on disk at resolve time.
    # tests/unit/_tooling/test_binary_manifest_sync.py asserts the two
    # agree for both architectures, so a bump that updates only one side
    # fails CI.
    # legendary 0.20.43
    "legendary": {
        "x86_64": (
            "2b82497051afd95670994146e6038d6e1c98a1c60c21949def668b52aef7d3f7"
        ),
        "aarch64": (
            "e28d4bed5d7635e22093d62ed4686a4d66e9c1d8bc4f1b731f834cd16d43c86a"
        ),
    },
    # nile 1.1.2 — deliberately held back; 1.2.0 migrates auth to an
    # encrypted store and DELETES ~/.config/nile/user.json, which
    # AmazonStore._check_nile_authenticated reads to decide the store is
    # available. Bumping it without that migration silently empties the
    # Amazon library for authenticated users.
    "nile": {
        "x86_64": (
            "3a8c080c864a5952a01d7661693c60727b34a355ae21e9eab2047096b606c1df"
        ),
        "aarch64": (
            "f5ba63cfeb415ec1f07a980d6a2bbcdf8fc11411e5fa224f838a88fe78ad0008"
        ),
    },
    # gogdl 1.2.2
    "gogdl": {
        "x86_64": (
            "d1f9f9a730ff442409bc11b14ae9ec410e5e45492f32899076481e58dd451117"
        ),
        "aarch64": (
            "269361006f25023032058f0447bcc5028b05f419b0416501d32c8b1dd695f3cd"
        ),
    },
}


def _expected_hash(tool_name: str, path: str) -> str:
    """The declared hash for ``tool_name`` as installed at ``path``.

    A universal tree holds both architectures' copies of a tool, so the
    file's own name is the first authority on which one this is:
    ``bin/nile-aarch64`` is the ARM build no matter which machine is
    asking. The canonical ``bin/nile`` carries no such marker, and there
    the host architecture is the right assumption — a single-architecture
    build ships the binary for the machine it was built for, and a
    mismatch there is exactly what
    :func:`~unifideck.core.binaries.binary_resolver._is_foreign_arch`
    already refused to hand out.

    Returns ``""`` when nothing is declared for that pairing.
    """
    per_arch = _KNOWN_HASHES.get(tool_name)
    if not per_arch:
        return ""
    name = Path(path).name
    arch = Arch.OTHER
    if name.startswith(f"{tool_name}-"):
        arch = normalize_arch(name[len(tool_name) + 1:])
    if arch is Arch.OTHER:
        arch = host_arch()
    return per_arch.get(arch.value, "")


def compute_sha256(path: str, chunk_size: int = 65536) -> str | None:
    """Return the hex SHA256 of a file, or None if it can't be read.

    Streaming read with a 64KiB buffer — avoids pulling the whole
    binary into memory (legendary.exe is ~30MB). Returns None on
    any OSError so callers can treat "unreadable" and "mismatched"
    uniformly as "do not trust".
    """
    try:
        h = hashlib.sha256()
        with Path(path).open("rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError as e:
        logger.warning(
            "[binary_signatures] Cannot read %s: %s", path, e,
        )
        return None


def verify_bundled_binary(
    tool_name: str,
    path: str,
) -> bool | None:
    """Check a binary against the allowlist.

    Returns:
      True — hash matches the declared allowlist entry
      False — hash does NOT match (tampered or wrong version)
      None — no allowlist entry declared, or the file could not
              be read. Caller decides the policy (fail-open in
              dev, fail-closed in prod).

    The tri-state return lets production plugins enforce the
    allowlist (fail on None) while development builds ship with
    empty hashes and still work. Store code should treat False
    as "do NOT invoke this binary" and log at ERROR.

    """
    expected = _expected_hash(tool_name, path)
    if not expected:
        logger.debug(
            "[binary_signatures] No reference hash for %s at %s — "
            "returning None (caller decides policy)", tool_name, path,
        )
        return None

    if not Path(path).is_file():
        logger.warning(
            "[binary_signatures] %s not found at %s",
            tool_name, path,
        )
        return None

    actual = compute_sha256(path)
    if actual is None:
        return None

    if actual != expected:
        logger.error(
            "[binary_signatures] SECURITY: %s hash mismatch at %s. "
            "Expected %s, got %s. Refusing to trust this binary.",
            tool_name, path, expected, actual,
        )
        return False

    logger.info(
        "[binary_signatures] %s at %s verified (sha256=%s)",
        tool_name, path, actual,
    )
    return True
