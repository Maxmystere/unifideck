"""Guard test — bundled-binary versions must agree across all three sources.

A bundled store CLI is pinned in three places that nothing links together:

1. ``package.json`` ``remote_binary[]`` / ``remote_binary_aarch64[]`` — URL +
   ``sha256hash``, one array per architecture. Decky reads the first at
   install time and verifies the download against the hash.
2. ``build-plugin.sh`` ``<TOOL>_URL_<ARCH>`` — the same URLs, hardcoded a
   second time because ``prebuild_binaries()`` runs before any JSON parsing
   is available to it. Its own header comment says the two "must stay in
   sync" and points at this test.
3. ``core/binaries/binary_signatures.py`` ``_KNOWN_HASHES`` — the runtime
   check that the file on disk is the pinned version, whose docstring
   requires updating "IN THE SAME COMMIT as the binary update".

Three hand-maintained copies of the same fact drift the moment someone
bumps a version and updates two of them. The failure is quiet and nasty:
the build downloads one version while the manifest advertises another, so
Decky's install-time hash check rejects it, or the runtime signature check
reports a mismatch on a binary that is perfectly fine.

Two architectures double every one of those opportunities, and add a new
one: a tool that exists for x86_64 and was never added to the ARM manifest
produces an ARM zip that is simply missing a store. So the arrays are
checked against each other as well.

De-duplicating these properly is roadmap item #7. Until then this test is
the seam that makes a partial bump fail loudly, in CI, immediately.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

# Tools pinned in all three places. umu is deliberately absent: it is
# committed to the repo rather than downloaded, so it has no remote_binary
# entry and no URL in build-plugin.sh (its version lives in bin/umu/VERSION).
_TRIPLE_PINNED = ("legendary", "gogdl", "nile")

# Architecture → the package.json key holding its manifest. x86_64 keeps the
# bare ``remote_binary`` name because that is the key Decky itself reads.
_MANIFEST_KEYS = {
    "x86_64": "remote_binary",
    "aarch64": "remote_binary_aarch64",
}


def _repo_file(relative: str) -> Path | None:
    """Locate ``relative`` in the checkout, or ``None``."""
    from tests.unit._repo_root import find_repo_file

    return find_repo_file(relative)


@pytest.fixture(scope="module")
def package_json() -> dict[str, Any]:
    """The parsed package.json."""
    path = _repo_file("package.json")
    if path is None:
        pytest.skip(
            "package.json not found in any candidate location "
            "(set UNIFIDECK_REPO_ROOT to point at the checkout root)")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifests(
    package_json: dict[str, Any],
) -> dict[str, dict[str, dict[str, str]]]:
    """``{arch: {tool: entry}}`` for every architecture we ship."""
    parsed: dict[str, dict[str, dict[str, str]]] = {}
    for arch, key in _MANIFEST_KEYS.items():
        entries = package_json.get(key) or []
        parsed[arch] = {e["name"]: e for e in entries if "name" in e}
    return parsed


@pytest.fixture(scope="module")
def shell_urls() -> dict[str, dict[str, str]]:
    """``{arch: {tool: url}}`` from build-plugin.sh's ``<TOOL>_URL_<ARCH>``."""
    path = _repo_file("build-plugin.sh")
    if path is None:
        pytest.skip(
            "build-plugin.sh not found in any candidate location "
            "(set UNIFIDECK_REPO_ROOT to point at the checkout root)")
    text = path.read_text(encoding="utf-8")
    found = re.findall(
        r'^([A-Z0-9]+)_URL_(X86_64|AARCH64)="([^"]+)"',
        text,
        flags=re.MULTILINE,
    )
    urls: dict[str, dict[str, str]] = {arch: {} for arch in _MANIFEST_KEYS}
    for tool, arch, url in found:
        urls[arch.lower()][tool.lower()] = url
    return urls


@pytest.mark.parametrize("arch", sorted(_MANIFEST_KEYS))
def test_every_manifest_entry_has_a_shell_url(
    arch: str,
    manifests: dict[str, dict[str, dict[str, str]]],
    shell_urls: dict[str, dict[str, str]],
) -> None:
    """Every remote_binary tool is also downloadable by build-plugin.sh."""
    missing = sorted(set(manifests[arch]) - set(shell_urls[arch]))
    assert not missing, (
        f"package.json pins {missing} for {arch} but build-plugin.sh has no "
        f"<TOOL>_URL_{arch.upper()} for them — prebuild_binaries() will not "
        f"fetch them"
    )


@pytest.mark.parametrize("arch", sorted(_MANIFEST_KEYS))
def test_manifest_and_shell_urls_match(
    arch: str,
    manifests: dict[str, dict[str, dict[str, str]]],
    shell_urls: dict[str, dict[str, str]],
) -> None:
    """The URL in package.json is byte-identical to build-plugin.sh's."""
    drifted = {
        name: (entry["url"], shell_urls[arch][name])
        for name, entry in sorted(manifests[arch].items())
        if name in shell_urls[arch] and entry["url"] != shell_urls[arch][name]
    }
    assert not drifted, (
        f"package.json and build-plugin.sh disagree on a {arch} binary URL — "
        "the build would download a different version than the manifest "
        "advertises, and Decky's install-time hash check would reject it:\n"
        + "\n".join(
            f"  {n}:\n    package.json:     {a}\n    build-plugin.sh:  {b}"
            for n, (a, b) in drifted.items()
        )
    )


def test_both_architectures_pin_the_same_tools(
    manifests: dict[str, dict[str, dict[str, str]]],
) -> None:
    """No tool ships on one architecture and silently not on the other.

    A missing ARM entry does not fail the build — it produces a zip whose
    ``bin/`` is short one store CLI, and the store it belongs to simply
    reports itself unavailable on ARM hardware with nothing in the log
    pointing at the manifest.
    """
    per_arch = {arch: set(entries) for arch, entries in manifests.items()}
    baseline = per_arch["x86_64"]
    divergent = {
        arch: sorted(baseline.symmetric_difference(tools))
        for arch, tools in per_arch.items()
        if tools != baseline
    }
    assert not divergent, (
        "package.json's architecture manifests pin different tool sets — "
        f"these differ from the x86_64 set: {divergent}"
    )


@pytest.mark.parametrize("arch", sorted(_MANIFEST_KEYS))
def test_known_hashes_match_the_manifest(
    arch: str,
    manifests: dict[str, dict[str, dict[str, str]]],
) -> None:
    """``_KNOWN_HASHES`` agrees with package.json for every pinned tool.

    Both describe the same artifact: Decky verifies the download against
    the manifest, and ``verify_bundled_binary`` verifies the file on disk
    against ``_KNOWN_HASHES``. If they disagree, one of them is wrong and
    a correct binary gets reported as tampered.
    """
    from unifideck.core.binaries.binary_signatures import _KNOWN_HASHES

    mismatched = {
        name: (_KNOWN_HASHES[name][arch], manifests[arch][name]["sha256hash"])
        for name in _TRIPLE_PINNED
        if name in manifests[arch]
        # A missing tool or architecture means "intentionally undeclared".
        and _KNOWN_HASHES.get(name, {}).get(arch)
        and _KNOWN_HASHES[name][arch] != manifests[arch][name]["sha256hash"]
    }
    assert not mismatched, (
        f"binary_signatures._KNOWN_HASHES disagrees with package.json's "
        f"{arch} manifest — bump both in the same commit:\n"
        + "\n".join(
            f"  {n}:\n    _KNOWN_HASHES: {a}\n    package.json:  {b}"
            for n, (a, b) in mismatched.items()
        )
    )


def test_architectures_do_not_share_a_hash() -> None:
    """The same tool must not declare one hash for both architectures.

    A copy-paste that leaves the x86_64 hash in the ARM slot passes every
    check above — the manifests agree, the shell URLs agree — and fails
    only on a real ARM device, where the correctly-downloaded binary is
    reported as tampered. The one tool this could be legitimate for
    (winetricks, the same shell script everywhere) has no ``_KNOWN_HASHES``
    entry, so an equal pair here is always the mistake.
    """
    from unifideck.core.binaries.binary_signatures import _KNOWN_HASHES

    shared = sorted(
        name for name, per_arch in _KNOWN_HASHES.items()
        if len(per_arch) > 1 and len(set(per_arch.values())) == 1
    )
    assert not shared, (
        f"{shared} declare the same sha256 for every architecture — one of "
        "them was copied from the other"
    )


def test_bundled_umu_version_is_pinned() -> None:
    """``bin/umu/VERSION`` exists and names a plausible umu version.

    umu is the one bundled tool with no manifest entry, so this file is
    the only machine-readable record of which umu shipped — the support
    bundle reports it, and it is the first question on any launch failure
    (umu <=1.4.1 fetches the runtime from a URL that is now permanently
    403, so the version alone explains a whole class of reports).
    """
    path = _repo_file("bin/umu/VERSION")
    if path is None:
        pytest.skip(
            "bin/umu/VERSION not found in any candidate location "
            "(set UNIFIDECK_REPO_ROOT to point at the checkout root)")
    version = path.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"bin/umu/VERSION should hold a bare x.y.z version, got {version!r}"
    )
