"""Bundled store CLIs resolve to a binary THIS machine can execute.

The plugin ships four architecture-specific tools. Before ARM support
every caller spelled their location ``<plugin>/bin/<tool>`` and that was
the end of it; now the same install tree can hold two builds of the same
tool, and the wrong one is not an error anyone sees — legendary and gogdl
are zipapps that start under the host's own Python and die importing a
native module, and nile and comet fail at ``exec`` with an errno the
store layer reports as "unavailable".

So what is pinned here is the resolution order, the refusal to hand out a
provably foreign binary, and the fallback that keeps a single-architecture
tree (every build that exists today) working exactly as it did.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from unifideck.core.binaries.bundled import (
    ARCH_SPECIFIC_TOOLS,
    build_arch,
    bundled_binary_path,
    bundled_binary_search_paths,
)
from unifideck.utils.arch import Arch

_ELF_X86_64 = bytes(bytearray(b"\x7fELF" + b"\x00" * 14 + b"\x3e\x00" + b"\x00" * 44))
_ELF_AARCH64 = bytes(bytearray(b"\x7fELF" + b"\x00" * 14 + b"\xb7\x00" + b"\x00" * 44))


def _plugin(tmp_path: Path) -> Path:
    (tmp_path / "bin").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _tool(plugin: Path, name: str, content: bytes = b"#!/bin/sh\n") -> Path:
    path = plugin / "bin" / name
    path.write_bytes(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


# --------------------------------------------------------------------------
# Search order
# --------------------------------------------------------------------------


def test_the_arch_specific_copy_is_preferred_over_the_canonical_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In a tree carrying both builds, ``bin/<tool>`` is the OTHER one."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    plugin = _plugin(tmp_path)
    _tool(plugin, "nile", _ELF_X86_64)
    arm = _tool(plugin, "nile-aarch64", _ELF_AARCH64)
    assert bundled_binary_path(plugin, "nile") == arm


def test_the_canonical_path_is_used_when_there_is_no_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The layout every build ships today: one architecture, one file."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    plugin = _plugin(tmp_path)
    native = _tool(plugin, "nile", _ELF_AARCH64)
    assert bundled_binary_path(plugin, "nile") == native


def test_a_foreign_binary_is_not_handed_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An x86_64-only tree on ARM: the store must not be given that file.

    The canonical path still comes back — a caller about to log "missing"
    should name the path a user can look for — but it is the path, not a
    promise, and :class:`BinaryResolver` skips it for the same reason.
    """
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    plugin = _plugin(tmp_path)
    _tool(plugin, "nile", _ELF_X86_64)
    resolved = bundled_binary_path(plugin, "nile")
    assert resolved == plugin / "bin" / "nile"

    from unifideck.core.binaries.binary_resolver import binary_resolver
    from unifideck.core.types.domain import CLITool

    assert binary_resolver.resolve(CLITool("nile", [str(resolved)])) is None


def test_a_zipapp_is_never_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """legendary and gogdl are ZIPs; their architecture is unreadable."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    plugin = _plugin(tmp_path)
    zipapp = _tool(plugin, "legendary", b"PK\x03\x04" + b"\x00" * 40)
    assert bundled_binary_path(plugin, "legendary") == zipapp


def test_an_architecture_neutral_tool_has_no_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """winetricks is one shell script everywhere — no ``-aarch64`` path."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    plugin = _plugin(tmp_path)
    assert "winetricks" not in ARCH_SPECIFIC_TOOLS
    assert bundled_binary_search_paths(plugin, "winetricks") == [
        str(plugin / "bin" / "winetricks"),
    ]


def test_search_paths_are_ordered_most_specific_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BinaryResolver takes the first executable Tier-1 hit, so order IS policy."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "x86_64")
    plugin = _plugin(tmp_path)
    assert bundled_binary_search_paths(plugin, "comet") == [
        str(plugin / "bin" / "comet-x86_64"),
        str(plugin / "bin" / "comet"),
    ]


def test_an_unsupported_host_asks_only_for_the_canonical_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is no ``bin/nile-riscv64`` to look for, so don't invent one."""
    monkeypatch.delenv("UNIFIDECK_ARCH", raising=False)
    monkeypatch.setattr("platform.machine", lambda: "riscv64")
    plugin = _plugin(tmp_path)
    assert bundled_binary_search_paths(plugin, "nile") == [
        str(plugin / "bin" / "nile"),
    ]


# --------------------------------------------------------------------------
# The build stamp
# --------------------------------------------------------------------------


def test_the_build_stamp_reports_what_the_tree_was_built_for(
    tmp_path: Path,
) -> None:
    plugin = _plugin(tmp_path)
    (plugin / "bin" / "ARCH").write_text("aarch64\n", encoding="utf-8")
    assert build_arch(plugin) is Arch.AARCH64


def test_a_tree_with_no_stamp_reports_unknown_rather_than_guessing(
    tmp_path: Path,
) -> None:
    """Every build cut before ARM support has no stamp; that is not x86_64."""
    assert build_arch(_plugin(tmp_path)) is Arch.OTHER


# --------------------------------------------------------------------------
# Signature verification follows the architecture too
# --------------------------------------------------------------------------


def test_the_expected_hash_follows_the_variant_in_the_filename() -> None:
    """``bin/nile-aarch64`` is the ARM build whichever machine is asking."""
    from unifideck.core.binaries.binary_signatures import (
        _KNOWN_HASHES,
        _expected_hash,
    )

    assert _expected_hash("nile", "/p/bin/nile-aarch64") == (
        _KNOWN_HASHES["nile"]["aarch64"]
    )
    assert _expected_hash("nile", "/p/bin/nile-x86_64") == (
        _KNOWN_HASHES["nile"]["x86_64"]
    )


def test_the_canonical_path_is_verified_against_the_host_architecture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single-architecture build ships the binary for the machine it targets."""
    from unifideck.core.binaries.binary_signatures import (
        _KNOWN_HASHES,
        _expected_hash,
    )

    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    assert _expected_hash("nile", "/p/bin/nile") == _KNOWN_HASHES["nile"]["aarch64"]
    monkeypatch.setenv("UNIFIDECK_ARCH", "x86_64")
    assert _expected_hash("nile", "/p/bin/nile") == _KNOWN_HASHES["nile"]["x86_64"]


def test_an_undeclared_tool_has_no_expected_hash() -> None:
    """comet is bundled but deliberately unpinned here; that must stay legal."""
    from unifideck.core.binaries.binary_signatures import _expected_hash

    assert _expected_hash("comet", "/p/bin/comet") == ""


# --------------------------------------------------------------------------
# Store descriptors get the expansion for free
# --------------------------------------------------------------------------


def test_a_store_declaring_bin_legendary_gets_both_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Epic and Amazon declare ``bin/<tool>``; neither should know about ARM.

    Called unbound against a duck-typed ``self``: the method only reads
    ``_plugin_dir``, and building a concrete StoreBase would mean stubbing
    a dozen abstract coroutines to test one path expansion.
    """
    from types import SimpleNamespace

    from unifideck.stores.shared.store_base import StoreBase

    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    store = SimpleNamespace(_plugin_dir="/plugin")
    assert StoreBase._expand_search_path(store, "bin/legendary") == [
        "/plugin/bin/legendary-aarch64",
        "/plugin/bin/legendary",
    ]


def test_an_absolute_search_path_is_taken_as_written() -> None:
    """A store that hardcodes a path means that exact file."""
    from types import SimpleNamespace

    from unifideck.stores.shared.store_base import StoreBase

    store = SimpleNamespace(_plugin_dir="/plugin")
    assert StoreBase._expand_search_path(store, "/usr/bin/legendary") == [
        "/usr/bin/legendary",
    ]
