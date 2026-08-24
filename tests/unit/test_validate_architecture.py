"""Guard test — scripts/validate_architecture.py.

Audit §1.1.4's lesson applied to the guard itself: a gate nobody has watched
fail is indistinguishable from one that passes everything. Every check here
is exercised against a planted violation, not only against a clean tree.

Why this file exists at all is audit §2.1. The RPC mixin count was written
into prose in five places, went stale, was hand-corrected to a single agreed
figure, and went stale again in the same release when the §1.2 dead-RPC pass
deleted three emptied mixins. Correcting the number is the approach that
failed twice. Check 1 owns the one statement of the set that has to be right
(``main.py`` vs ``__all__``); check 5 stops a third statement appearing
anywhere else.

What is pinned:

1. the real repo passes all five checks, and the live mixin count is printed
   so the set cannot change silently;
2. check 1 flips the exit code and names the offending class in BOTH
   directions — composed-but-not-exported and exported-but-not-composed —
   because the fix differs per direction;
3. check 5 catches a count written next to the word, names file, line and
   the live figure, and honours its ``mixin-count-ok:`` opt-out on the line
   and on the line above;
4. check 5's exclusions and its lookbehind hold, since a checker that fires
   on ``Layer-6 RPC mixins`` gets switched off rather than fixed.

The clean-tree case runs the script as a subprocess against the real repo.
The failure cases build a throwaway mirror of the repo — symlinks for every
directory, a rewritten ``main.py`` — and repoint the module's roots at it,
so no test ever mutates the working tree.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _find_script() -> Path | None:
    from tests.unit._repo_root import find_repo_file

    return find_repo_file("scripts/validate_architecture.py")


@pytest.fixture(scope="module")
def script_path() -> Path:
    p = _find_script()
    if p is None:
        pytest.skip(
            "scripts/validate_architecture.py not found "
            "(set UNIFIDECK_REPO_ROOT to the checkout root)")
    return p


@pytest.fixture(scope="module")
def repo_root() -> Path:
    from tests.unit._repo_root import find_repo_root

    root = find_repo_root()
    if root is None:
        pytest.skip(
            "repo checkout not found "
            "(set UNIFIDECK_REPO_ROOT to the checkout root)")
    return root


def _load(script: Path):
    """Fresh module instance so a test's root patch cannot leak."""
    spec = importlib.util.spec_from_file_location("_va_under_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod(script_path: Path):
    return _load(script_path)


def _run(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=180, check=False,
    )


# Directories the script reads. Symlinked rather than copied: the real
# stores/, src/ and docs/ must be the ones under test, so that only the
# planted defect distinguishes the mirror from the checkout.
_MIRRORED = (
    "py_modules", "src", "docs", "scripts", ".github", ".claude", "CLAUDE.md",
)


def _mirror(tmp_path: Path, repo_root: Path, main_py: str) -> Path:
    """A repo whose only difference from the real one is ``main.py``."""
    root = tmp_path / "mirror"
    root.mkdir()
    for entry in _MIRRORED:
        source = repo_root / entry
        if source.exists():
            (root / entry).symlink_to(
                source, target_is_directory=source.is_dir())
    (root / "main.py").write_text(main_py, encoding="utf-8")
    return root


def _repoint(mod, root: Path) -> None:
    mod.REPO_ROOT = root
    mod.PY = root / "py_modules" / "unifideck"
    mod.SRC = root / "src"


# ========================================================= #
# 1. Clean run against the real source
# ========================================================= #
def test_passes_against_real_source(script_path: Path) -> None:
    res = _run(script_path)
    assert res.returncode == 0, (
        "architecture gate failed against real source:\n"
        f"{res.stdout}\n{res.stderr}")
    assert "architecture invariants OK" in res.stdout


def test_every_check_reports(script_path: Path) -> None:
    """A check that stops printing has stopped running."""
    res = _run(script_path)
    for expected in (
        "mixins composed == __all__",
        "stores agree (cache registry == disk)",
        "uses_wine agrees with WRAPPER_STORES",
        "have a frontend caller",
        "no mixin count restated in prose",
    ):
        assert expected in res.stdout, f"no output line for: {expected}"


def test_the_live_mixin_count_is_printed(
    script_path: Path, repo_root: Path, mod,
) -> None:
    """The count is printed, and it is the count main.py actually composes.

    Derived from the tree rather than written down here: a literal in this
    test would be the sixth stale copy of the number §2.1 is about.
    """
    composed = mod.parse_mixin_bases(repo_root / "main.py")
    res = _run(script_path)
    assert f"OK: {len(composed)} mixins composed == __all__" in res.stdout


def test_mirror_alone_does_not_change_the_verdict(
    tmp_path: Path, repo_root: Path, mod, capsys,
) -> None:
    """Pins the harness, not the script.

    Every failure case below is a mirror plus one planted defect. If an
    unmodified mirror did not pass, those tests would prove nothing about
    the defect they plant.
    """
    root = _mirror(
        tmp_path, repo_root, (repo_root / "main.py").read_text())
    _repoint(mod, root)
    assert mod.main() == 0, capsys.readouterr().out


# ========================================================= #
# 2. Check 1 — main.py vs __all__, both directions
# ========================================================= #
def _main_py_dropping(repo_root: Path, mixin: str) -> str:
    text = (repo_root / "main.py").read_text()
    needle = f"    {mixin},\n"
    assert needle in text, f"{mixin} is not a base of class Plugin(...)"
    return text.replace(needle, "")


def test_check1_catches_a_mixin_left_in_all_but_not_composed(
    tmp_path: Path, repo_root: Path, mod, capsys,
) -> None:
    """Deleting a mixin from main.py and forgetting __all__.

    This is the live half: the §1.2 pass deleted three mixins, and this is
    the check that made that safe.
    """
    root = _mirror(
        tmp_path, repo_root, _main_py_dropping(repo_root, "AchievementsRPCMixin"))
    _repoint(mod, root)

    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "mixin set drift" in out
    assert "in __all__ but not composed: ['AchievementsRPCMixin']" in out


def test_check1_catches_a_mixin_composed_but_not_exported(
    tmp_path: Path, repo_root: Path, mod, capsys,
) -> None:
    """Adding a mixin to main.py and forgetting __all__ — the other half.

    Named separately because the remedy differs: here __all__ needs the new
    import, there main.py needs the base removed.
    """
    text = (repo_root / "main.py").read_text()
    planted = text.replace(
        "    UpdaterRPCMixin,\n",
        "    UpdaterRPCMixin,\n    NewlyAddedRPCMixin,\n",
        1,
    )
    assert planted != text
    _repoint(mod, _mirror(tmp_path, repo_root, planted))

    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "missing from __all__: ['NewlyAddedRPCMixin']" in out


def test_check1_reports_the_two_figures_it_compared(
    tmp_path: Path, repo_root: Path, mod, capsys,
) -> None:
    """"They disagree" is not a usable diagnosis without both numbers."""
    composed = mod.parse_mixin_bases(repo_root / "main.py")
    root = _mirror(
        tmp_path, repo_root, _main_py_dropping(repo_root, "EdgeRPCMixin"))
    _repoint(mod, root)

    mod.main()
    out = capsys.readouterr().out
    assert f"main.py composes {len(composed) - 1} mixins" in out
    assert f"__all__ re-exports {len(composed)}" in out


def test_parse_mixin_bases_ignores_a_commented_out_base(
    tmp_path: Path, mod,
) -> None:
    """A commented-out base must read as absent, or check 1 sees no drift."""
    src = tmp_path / "main.py"
    src.write_text(
        "class Plugin(\n"
        "    AlphaRPCMixin,\n"
        "    # BetaRPCMixin,\n"
        "    GammaRPCMixin,\n"
        "):\n"
        "    pass\n",
        encoding="utf-8",
    )
    assert mod.parse_mixin_bases(src) == {"AlphaRPCMixin", "GammaRPCMixin"}


# ========================================================= #
# 3. Check 5 — no mixin count restated in prose
# ========================================================= #
def _doc(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_check5_catches_a_count_next_to_the_word(tmp_path: Path, mod) -> None:
    _doc(tmp_path, "docs/architecture.md",
         "intro\nThe Plugin class is composed from 20 RPC mixin classes.\n")

    hits = mod.find_prose_mixin_counts(tmp_path)
    assert [(rel, line) for rel, line, _ in hits] == [
        ("docs/architecture.md", 2)]
    assert "20 RPC mixin" in hits[0][2]


@pytest.mark.parametrize("phrasing", [
    "composed from 20 RPC mixin classes",
    "Plugin = 20 RPC mixins (@auto_wrap_rpc_methods)",
    "class Plugin(<20 RPC mixins>)",
    'the docstring says "eleven mixins"',
    "which are the 20 mixin surfaces",
    "re-exports seventeen mixins",
])
def test_check5_catches_every_form_the_defect_actually_took(
    tmp_path: Path, mod, phrasing: str,
) -> None:
    """The parametrised strings are the real §2.1 sites, verbatim."""
    _doc(tmp_path, "docs/architecture.md", phrasing + "\n")
    assert mod.find_prose_mixin_counts(tmp_path), (
        f"not caught: {phrasing!r}")


def test_check5_honours_the_marker_on_the_line(tmp_path: Path, mod) -> None:
    _doc(tmp_path, "docs/engineering-roadmap.md",
         "<!-- mixin-count-ok: historical -->  It said 20 RPC mixins.\n")
    assert mod.find_prose_mixin_counts(tmp_path) == []


def test_check5_honours_the_marker_on_the_line_above(
    tmp_path: Path, mod,
) -> None:
    _doc(tmp_path, "docs/engineering-roadmap.md",
         "<!-- mixin-count-ok: historical -->\nIt said 20 RPC mixins.\n")
    assert mod.find_prose_mixin_counts(tmp_path) == []


def test_check5_marker_does_not_exempt_the_line_below_it(
    tmp_path: Path, mod,
) -> None:
    """Two lines of reach, not three — an unbounded marker is an allowlist."""
    _doc(tmp_path, "docs/architecture.md",
         "It said 20 RPC mixins.\nfiller\n<!-- mixin-count-ok: x -->\n")
    assert len(mod.find_prose_mixin_counts(tmp_path)) == 1


def test_check5_reports_both_counts_on_one_line(tmp_path: Path, mod) -> None:
    """Fixing one of two must not need a second run to see the other."""
    _doc(tmp_path, "docs/architecture.md",
         "It said eleven mixins, then 20 RPC mixins.\n")
    assert len(mod.find_prose_mixin_counts(tmp_path)) == 2


def test_check5_does_not_fire_on_a_layer_number(tmp_path: Path, mod) -> None:
    """``Layer-6 RPC mixins`` is live prose in services/__init__.py.

    A word boundary sits between the hyphen and the digit, so without the
    lookbehind this reads as a count of six and the gate cries wolf on
    untouched code — which is how a checker gets switched off.
    """
    _doc(tmp_path, "docs/architecture.md",
         "the services layer sits below the Layer-6 RPC mixins\n")
    assert mod.find_prose_mixin_counts(tmp_path) == []


def test_check5_does_not_fire_mid_word(tmp_path: Path, mod) -> None:
    _doc(tmp_path, "docs/architecture.md", "someone mixins things up\n")
    assert mod.find_prose_mixin_counts(tmp_path) == []


def test_check5_does_not_fire_on_a_countless_mention(
    tmp_path: Path, mod,
) -> None:
    """The wording every fixed site now uses must stay clean."""
    _doc(tmp_path, "docs/architecture.md",
         "composed from the RPC mixin classes enumerated in the table below\n")
    assert mod.find_prose_mixin_counts(tmp_path) == []


@pytest.mark.parametrize("excluded", [
    "docs/archive/ARCHITECTURE_TREE.md",
    "docs/architecture-audit.md",
])
def test_check5_skips_the_historical_records(
    tmp_path: Path, mod, excluded: str,
) -> None:
    """Superseded docs and the audit register exist to hold the old figures.

    Scanning them would produce noise the only fix for is an exemption on
    every line, which trains people to add exemptions.
    """
    _doc(tmp_path, excluded, "Thin Plugin router — 11 RPC mixins\n")
    assert mod.find_prose_mixin_counts(tmp_path) == []


def test_check5_scans_the_agent_facing_surfaces(tmp_path: Path, mod) -> None:
    """The stale count that mattered lived in a skill, not in docs/.

    SKILL.md is loaded as context for every architecture task, so leaving it
    out of scope would miss the highest-consequence copy.
    """
    for relative in (
        "CLAUDE.md",
        "docs/architecture.md",
        ".claude/skills/unifideck-architecture/SKILL.md",
        "main.py",
        "py_modules/unifideck/rpc/mixins/__init__.py",
        "scripts/validate_architecture.py",
        ".github/workflows/tests.yml",
    ):
        root = tmp_path / relative.replace("/", "_")
        root.mkdir()
        _doc(root, relative, "composed of 20 RPC mixins\n")
        assert mod.find_prose_mixin_counts(root), f"not scanned: {relative}"


def test_check5_failure_names_the_file_line_and_live_count(
    tmp_path: Path, repo_root: Path, mod, capsys,
) -> None:
    """End to end: the error has to say where, what, and what is true.

    Driven through ``main()`` rather than the helper so the exit code and
    the remediation block are pinned too.
    """
    root = _mirror(
        tmp_path, repo_root, (repo_root / "main.py").read_text())
    composed = mod.parse_mixin_bases(repo_root / "main.py")

    # docs/ is a symlink to the real tree; shadow one file with a real
    # directory so the planted count cannot touch the checkout.
    (root / "docs").unlink()
    _doc(root, "docs/architecture.md", "composed from 20 RPC mixin classes\n")
    _repoint(mod, root)

    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "docs/architecture.md:1" in out
    assert "'20 RPC mixin'" in out
    assert f"main.py composes {len(composed)}" in out
    assert "mixin-count-ok: <reason>" in out
