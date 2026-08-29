"""Host architecture: one answer, and never a guess.

Everything architecture-dependent in the plugin — which store CLI to run,
which GE-Proton tarball to fetch, which release zip the updater offers —
funnels through :mod:`unifideck.utils.arch`. The behaviours pinned here
are the ones whose failure mode is silent: an unrecognised machine that
gets rounded up to x86_64, or a foreign binary that looks perfectly fine
right up until ``exec`` refuses it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from unifideck.utils.arch import (
    Arch,
    elf_arch,
    host_arch,
    host_arch_name,
    is_arm,
    normalize_arch,
    runnable_here,
)


# Real ELF headers: magic, then e_machine at offset 0x12. 0x3E is
# EM_X86_64, 0xB7 is EM_AARCH64, 0xF3 is EM_RISCV (a machine we ship
# nothing for).
def _elf(machine: int) -> bytes:
    header = bytearray(b"\x7fELF" + b"\x00" * 60)
    header[0x12] = machine & 0xFF
    header[0x13] = machine >> 8
    return bytes(header)


_ELF_X86_64 = _elf(0x3E)
_ELF_AARCH64 = _elf(0xB7)
_ELF_RISCV = _elf(0xF3)


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("x86_64", Arch.X86_64),
        ("AMD64", Arch.X86_64),
        ("x64", Arch.X86_64),
        ("aarch64", Arch.AARCH64),
        ("arm64", Arch.AARCH64),
        ("  ARM64 ", Arch.AARCH64),
        ("armv8l", Arch.AARCH64),
    ],
)
def test_every_spelling_of_an_architecture_maps_to_one_value(
    spelling: str, expected: Arch,
) -> None:
    """uname, dpkg, wheel tags and release assets all spell these differently."""
    assert normalize_arch(spelling) is expected


@pytest.mark.parametrize("machine", ["riscv64", "ppc64le", "armv7l", "", None])
def test_a_machine_we_ship_nothing_for_is_never_rounded_to_a_near_miss(
    machine: str | None,
) -> None:
    """OTHER is a real answer. armv7l is 32-bit ARM — not aarch64."""
    assert normalize_arch(machine) is Arch.OTHER


# --------------------------------------------------------------------------
# Host detection and the override
# --------------------------------------------------------------------------


def test_the_env_override_wins_over_the_real_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This is how a cross-build (and every test below) picks an architecture."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    assert host_arch() is Arch.AARCH64
    assert host_arch_name() == "aarch64"
    assert is_arm()


def test_a_nonsense_override_falls_back_to_the_real_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo'd override must not brick detection into OTHER."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "sparc")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    assert host_arch() is Arch.X86_64


def test_an_unknown_machine_still_reports_its_own_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``host_arch_name`` is for diagnostics, where "other" helps nobody."""
    monkeypatch.delenv("UNIFIDECK_ARCH", raising=False)
    monkeypatch.setattr("platform.machine", lambda: "riscv64")
    assert host_arch() is Arch.OTHER
    assert host_arch_name() == "riscv64"


# --------------------------------------------------------------------------
# Reading a binary's own architecture
# --------------------------------------------------------------------------


def test_an_elf_declares_the_machine_it_was_built_for(tmp_path: Path) -> None:
    x86 = tmp_path / "nile"
    x86.write_bytes(_ELF_X86_64)
    arm = tmp_path / "nile-aarch64"
    arm.write_bytes(_ELF_AARCH64)
    assert elf_arch(x86) is Arch.X86_64
    assert elf_arch(arm) is Arch.AARCH64


@pytest.mark.parametrize(
    ("name", "content"),
    [
        # legendary and gogdl are Python zipapps, not ELFs.
        ("legendary", b"PK\x03\x04" + b"\x00" * 40),
        # winetricks is a shell script.
        ("winetricks", b"#!/bin/sh\necho hi\n"),
        # An ELF for a machine outside the table.
        ("exotic", _ELF_RISCV),
        # Too short to hold a header at all.
        ("truncated", b"\x7fELF"),
    ],
)
def test_anything_that_is_not_a_known_elf_answers_i_cannot_tell(
    tmp_path: Path, name: str, content: bytes,
) -> None:
    """``None`` means "no answer" and must never be read as a mismatch."""
    path = tmp_path / name
    path.write_bytes(content)
    assert elf_arch(path) is None


def test_a_missing_file_answers_i_cannot_tell(tmp_path: Path) -> None:
    assert elf_arch(tmp_path / "absent") is None


# --------------------------------------------------------------------------
# runnable_here: the asymmetry is the point
# --------------------------------------------------------------------------


def test_a_foreign_elf_is_not_runnable_here(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case that otherwise surfaces as ``Errno 8: Exec format error``."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "x86_64")
    arm = tmp_path / "nile"
    arm.write_bytes(_ELF_AARCH64)
    assert not runnable_here(arm)


def test_a_native_elf_is_runnable_here(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    arm = tmp_path / "nile"
    arm.write_bytes(_ELF_AARCH64)
    assert runnable_here(arm)


def test_a_zipapp_stays_runnable_because_we_cannot_tell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Most of what we bundle is not an ELF; refusing all of it is worse."""
    monkeypatch.setenv("UNIFIDECK_ARCH", "aarch64")
    zipapp = tmp_path / "legendary"
    zipapp.write_bytes(b"PK\x03\x04" + b"\x00" * 40)
    assert runnable_here(zipapp)


# --------------------------------------------------------------------------
# The entry-point preflight
# --------------------------------------------------------------------------


def _run_preflight(tmp_path: Path, stamp: str | None, machine: str) -> str | None:
    """Import main.py's guard in a subprocess; return its error, or None.

    A subprocess because ``main.py`` runs the check at module scope and
    then imports the whole plugin — neither of which belongs in this
    interpreter.
    """
    import subprocess
    import sys as _sys

    from tests.unit._repo_root import find_repo_file

    main_py = find_repo_file("main.py")
    if main_py is None:
        pytest.skip("main.py not found (set UNIFIDECK_REPO_ROOT)")
    plugin = tmp_path / "plugin"
    (plugin / "bin").mkdir(parents=True)
    (plugin / "main.py").write_bytes(main_py.read_bytes())
    if stamp is not None:
        (plugin / "bin" / "ARCH").write_text(stamp, encoding="utf-8")

    script = (
        "import platform, sys\n"
        f"platform.machine = lambda: {machine!r}\n"
        f"sys.path.insert(0, {str(plugin)!r})\n"
        "try:\n"
        "    import main\n"
        "except RuntimeError as e:\n"
        "    print('GUARD:' + str(e))\n"
        "except Exception:\n"
        "    pass\n"
    )
    out = subprocess.run(
        [_sys.executable, "-c", script],
        capture_output=True, text=True, timeout=60,
        env={"DECKY_PLUGIN_DIR": str(plugin), "PATH": "/usr/bin:/bin"},
        check=False,
    ).stdout
    for line in out.splitlines():
        if line.startswith("GUARD:"):
            return line[len("GUARD:"):]
    return None


def test_a_foreign_build_refuses_to_load_and_says_why(tmp_path: Path) -> None:
    """The real incident: an aarch64 zip installed on an x86_64 machine.

    Without this the plugin died eleven frames down on
    ``_rust.abi3.so: cannot open shared object file`` — naming a file
    that is present — which reads as a corrupt install rather than the
    wrong download.
    """
    error = _run_preflight(tmp_path, "aarch64\n", "x86_64")
    assert error is not None, "the guard did not fire on a foreign build"
    assert "aarch64" in error and "x86_64" in error
    assert "Install the x86_64 build" in error


def test_a_matching_build_loads(tmp_path: Path) -> None:
    assert _run_preflight(tmp_path, "x86_64\n", "x86_64") is None


def test_a_build_predating_the_stamp_is_never_blocked(tmp_path: Path) -> None:
    """Every 0.7.4-and-earlier install has no bin/ARCH. Silence is required."""
    assert _run_preflight(tmp_path, None, "x86_64") is None


def test_an_alias_spelling_in_the_stamp_still_matches(tmp_path: Path) -> None:
    """A hand-written ``arm64`` stamp must not read as a mismatch on ARM."""
    assert _run_preflight(tmp_path, "arm64\n", "aarch64") is None
