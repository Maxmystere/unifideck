"""Downloads chosen for the machine, not for the maintainer's machine.

Two places fetch a whole build over the network and hand it to the user:
the GE-Proton installer and the in-app updater. Both used to take the
first plausible asset in the release, which was correct exactly while one
architecture existed.

Both failure modes are quiet. A GE-Proton tarball for the wrong machine
installs fine and then cannot execute, and because the installer records
the tag as "installed" the plugin stops looking. A release zip for the
wrong machine installs fine too, and then every store reports itself
unavailable. So the rule pinned here is the same on both sides: prefer
this architecture, accept an unmarked asset only where "unmarked" has
always meant x86_64, and never take one marked for the other machine.
"""

from __future__ import annotations

import pytest

from unifideck.launcher.proton.infrastructure import ge_installer
from unifideck.services.updater.service import _asset_arch, _select_asset

# ── GE-Proton ─────────────────────────────────────────────────────

_GE_BOTH = [
    {"name": "GE-Proton11-5-aarch64.sha512sum", "browser_download_url": "http://x/arm.sha"},
    {"name": "GE-Proton11-5-aarch64.tar.gz", "browser_download_url": "http://x/arm.tar.gz"},
    {"name": "GE-Proton11-5-x86_64.sha512sum", "browser_download_url": "http://x/x86.sha"},
    {"name": "GE-Proton11-5-x86_64.tar.gz", "browser_download_url": "http://x/x86.tar.gz"},
]

# GE-Proton11-3 and earlier: the x86_64 build wore no architecture at all.
_GE_LEGACY = [
    {"name": "GE-Proton11-3.sha512sum", "browser_download_url": "http://x/x86.sha"},
    {"name": "GE-Proton11-3.tar.gz", "browser_download_url": "http://x/x86.tar.gz"},
]


def test_an_arm_host_takes_the_aarch64_tarball(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    url = ge_installer._select_tarball(_GE_BOTH, "GE-Proton11-5")
    assert url == "http://x/arm.tar.gz"


def test_an_x86_host_still_takes_the_x86_tarball(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNIFIDECK_ARCH", "x86_64")
    url = ge_installer._select_tarball(_GE_BOTH, "GE-Proton11-5")
    assert url == "http://x/x86.tar.gz"


def test_an_arm_host_refuses_a_release_that_only_ships_x86(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point: an unmarked tarball is x86_64 wearing no label.

    Returning it would install a Proton that cannot run and record it as
    the latest, so the plugin would stop looking for a real one. ``None``
    keeps the caller on whatever Proton Steam already has.
    """
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    assert ge_installer._select_tarball(_GE_LEGACY, "GE-Proton11-3") is None


def test_an_x86_host_accepts_the_unmarked_legacy_tarball(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNIFIDECK_ARCH", "x86_64")
    url = ge_installer._select_tarball(_GE_LEGACY, "GE-Proton11-3")
    assert url == "http://x/x86.tar.gz"


def test_the_arch_can_be_named_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parameter exists so a caller can ask about the other machine."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "x86_64")
    url = ge_installer._select_tarball(_GE_BOTH, "GE-Proton11-5", arch="aarch64")
    assert url == "http://x/arm.tar.gz"


def test_a_tag_mismatch_still_finds_the_right_architecture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tag is a hint, not a requirement — the suffix scan is the backstop."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    url = ge_installer._select_tarball(_GE_BOTH, "GE-Proton12-1")
    assert url == "http://x/arm.tar.gz"


# ── The in-app updater ────────────────────────────────────────────


def _asset(name: str) -> dict[str, str]:
    return {"name": name, "browser_download_url": f"http://x/{name}"}


_RELEASE_BOTH = [
    _asset("unifideck.prod.v0.8.0.aarch64.zip"),
    _asset("unifideck.prod.v0.8.0.x86_64.zip"),
    _asset("Source code (zip)"),
]


@pytest.mark.parametrize(
    ("arch", "expected"),
    [
        ("aarch64", "unifideck.prod.v0.8.0.aarch64.zip"),
        ("x86_64", "unifideck.prod.v0.8.0.x86_64.zip"),
    ],
)
def test_the_updater_offers_the_zip_for_this_machine(
    arch: str, expected: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNIFIDECK_ARCH", arch)
    asset = _select_asset(_RELEASE_BOTH)
    assert asset is not None
    assert asset["name"] == expected


def test_a_release_predating_arm_support_installs_everywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unmarked asset is not exclusive to anything, so it stays offered."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    asset = _select_asset([_asset("unifideck.prod.v0.7.4.zip")])
    assert asset is not None
    assert asset["name"] == "unifideck.prod.v0.7.4.zip"


def test_a_release_built_only_for_the_other_machine_is_not_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Better no update than one that installs and then breaks every store."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    assert _select_asset([_asset("unifideck.prod.v0.8.0.x86_64.zip")]) is None


def test_source_archives_are_still_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNIFIDECK_ARCH", "x86_64")
    assert _select_asset([_asset("Source code (zip)")]) is None


def test_a_version_number_is_not_mistaken_for_an_architecture() -> None:
    """Segment matching, not substring: ``v1.2.3`` must stay unmarked."""
    assert _asset_arch("unifideck.prod.v1.2.3.zip") is None
    assert _asset_arch("unifideck.dev.0.7.1.g3f9a1c2.zip") is None
