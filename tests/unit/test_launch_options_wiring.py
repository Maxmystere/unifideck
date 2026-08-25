"""Guard test — the launch-options parser is now on the launch path.

Audit §2.9. ``launcher/types/options.py`` had zero importers for a release
while its destination was fully built: ``ctx.env_overrides`` was consumed in
two places and ``state.wrappers`` / ``state.game_args`` in eleven, and nothing
wrote any of them. This file pins the half that is now wired, and, just as
importantly, pins the half that is deliberately NOT.

What is pinned:

1. the no-options baseline is untouched, because that is what every existing
   launch does and it is the only regression that would matter;
2. a user ``KEY=value`` token reaches ``ctx.env_overrides``, which both env
   builders already apply last;
3. LSFG opt-in is detected, and the overlay merges *under* an explicit user
   value rather than over it;
4. ``promote_env_tokens`` survives a quoted value containing a space, which
   its old ``raw_options.split()`` truncated;
5. ``state.wrappers`` / ``state.game_args`` stay EMPTY. Wiring them would
   append the user's wrapper words to the game's own argv -- see the test at
   the bottom, which is the measurement that stopped it.
"""
from __future__ import annotations

import os

import pytest

from unifideck.launcher.argv_options import env_overrides_from, promote_env_tokens
from unifideck.launcher.types.context import LaunchContext, RuntimeState
from unifideck.launcher.types.options import parse_launch_options, tokenize_options
from unifideck.services.launcher.service import LauncherService


def _ctx(raw_options: str, tmp_path) -> LaunchContext:
    """A launch context carrying ``raw_options``, as the dispatcher builds it."""
    return LaunchContext(
        store="epic",
        game_id="abc123",
        exe_path=tmp_path / "game.exe",
        work_dir=tmp_path,
        plugin_dir=tmp_path,
        raw_options=raw_options,
        env_overrides=env_overrides_from(raw_options),
    )


# ========================================================= #
# 1. The baseline: no options at all
# ========================================================= #
@pytest.mark.parametrize("raw", ["", "   "])
def test_no_options_changes_nothing(raw: str, tmp_path) -> None:
    """The overwhelmingly common case. If this moves, the wiring is wrong.

    A Unifideck shortcut's ``LaunchOptions`` is just ``store:game_id``, which
    lands in ``argv[1]`` and never reaches ``raw_options`` (that is
    ``argv[2:]``). So the normal launch parses an empty string.
    """
    ctx = _ctx(raw, tmp_path)
    state = LauncherService._build_runtime_state(ctx)

    assert ctx.env_overrides == {}
    assert state.wrappers == []
    assert state.game_args == []
    assert state.lsfg_requested is False


# ========================================================= #
# 2. Env overrides now reach the game
# ========================================================= #
def test_user_env_token_reaches_env_overrides(tmp_path) -> None:
    """Before §2.9 this dict was always empty, so the token was dropped."""
    ctx = _ctx("WINEDLLOVERRIDES=winemenubuilder.exe=d", tmp_path)
    assert ctx.env_overrides == {"WINEDLLOVERRIDES": "winemenubuilder.exe=d"}


def test_lowercase_token_is_not_an_env_override(tmp_path) -> None:
    """The regex is uppercase-only, which is load-bearing.

    ``service.py`` used to read ``ctx.env_overrides["started_at"]`` as an
    internal data channel. That read is gone, but the dict is user-controlled
    now, so a lowercase key must not be able to arrive through it.
    """
    ctx = _ctx("started_at=999 lowercase=x", tmp_path)
    assert ctx.env_overrides == {}


def test_env_override_wins_over_the_lsfg_overlay(tmp_path, monkeypatch) -> None:
    """Merge order: the explicit token beats the script's value."""
    script = tmp_path / "lsfg"
    script.write_text('export ENABLE_LSFG="0"\nexport LSFG_MULTIPLIER="2"\n')
    monkeypatch.setenv("HOME", str(tmp_path))

    overrides = env_overrides_from("ENABLE_LSFG=1")
    # Non-vacuous: prove the script was actually read before checking who won.
    assert overrides["LSFG_MULTIPLIER"] == "2"
    assert overrides["ENABLE_LSFG"] == "1", "script value beat the user's token"


# ========================================================= #
# 3. LSFG opt-in
# ========================================================= #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [("LSFG=1", True), ("ENABLE_LSFG=1", True), ("", False), ("LSFG=0", False)],
)
def test_lsfg_opt_in_is_detected(raw: str, expected: bool, tmp_path) -> None:
    state = LauncherService._build_runtime_state(_ctx(raw, tmp_path))
    assert state.lsfg_requested is expected


def test_lsfg_overlay_reads_the_script(tmp_path, monkeypatch) -> None:
    script = tmp_path / "lsfg"
    script.write_text(
        "#!/bin/sh\n"
        'export LSFG_MULTIPLIER="3"\n'
        "# a comment\n"
        "exec something\n",
    )
    monkeypatch.setenv("HOME", str(tmp_path))

    overlay = env_overrides_from("LSFG=1")
    assert overlay["ENABLE_LSFG"] == "1"
    assert overlay["LSFG_MULTIPLIER"] == "3"


def test_no_lsfg_overlay_without_the_opt_in(tmp_path, monkeypatch) -> None:
    (tmp_path / "lsfg").write_text('export LSFG_MULTIPLIER="3"\n')
    monkeypatch.setenv("HOME", str(tmp_path))
    assert env_overrides_from("") == {}


# ========================================================= #
# 4. The merged tokenizer
# ========================================================= #
def test_promote_env_tokens_keeps_a_quoted_value_intact() -> None:
    """The bug the tokenizer merge fixed.

    ``promote_env_tokens`` split on whitespace, so ``KEY="a b"`` promoted
    ``'"a'``. The frontend's ``extractUserParams`` regex already matches
    quoted values, so the two were one launch-options string apart.
    """
    os.environ.pop("UNIFIDECK_TEST_QUOTED", None)
    try:
        promote_env_tokens('UNIFIDECK_TEST_QUOTED="alpha beta"')
        assert os.environ["UNIFIDECK_TEST_QUOTED"] == "alpha beta"
    finally:
        os.environ.pop("UNIFIDECK_TEST_QUOTED", None)


def test_promote_env_tokens_ignores_foreign_keys() -> None:
    """Only ``UNIFIDECK_*`` is promoted into the launcher's own environment."""
    os.environ.pop("SOME_USER_VAR", None)
    promote_env_tokens("SOME_USER_VAR=1")
    assert "SOME_USER_VAR" not in os.environ


def test_tokenize_options_falls_back_on_malformed_input() -> None:
    """An unbalanced quote must not raise on the launch path."""
    assert tokenize_options('KEY="unterminated') == ['KEY="unterminated']


# ========================================================= #
# 5. What is deliberately NOT wired, and the measurement why
# ========================================================= #
def test_wrappers_and_game_args_stay_unpopulated(tmp_path) -> None:
    """Pins the deferral, so re-wiring it is a deliberate act with a red test.

    See :func:`test_bare_argv_tokens_would_become_game_args` for the reason.
    """
    ctx = _ctx("mangohud gamemoderun", tmp_path)
    state = LauncherService._build_runtime_state(ctx)
    assert state.wrappers == []
    assert state.game_args == []


def test_bare_argv_tokens_would_become_game_args() -> None:
    """The measurement that stopped the wrappers/game_args half of §2.9.

    ``parse_launch_options`` expects a full Steam ``LaunchOptions`` string, in
    which ``%command%`` separates wrapper words from game arguments. The
    dispatcher gets the post-expansion argv tail, which often has no
    ``%command%`` left -- and the parser's fallback then treats every bare
    token as a game argument.

    The input below is the argv tail of the frontend's own wrapper-store
    fixture (``wrapper-shortcut-launch.test.ts``), whose ``extractUserParams``
    deliberately preserves the user's ``mangohud`` / ``gamemoderun``. Feeding
    ``game_args`` from this would append them to the game's own command line,
    because every argv builder does ``argv.extend(state.game_args)``.
    """
    parsed = parse_launch_options(
        "UNIFIDECK_UBISOFT_ACTION=auth mangohud gamemoderun",
    )
    assert parsed.env_overrides == {"UNIFIDECK_UBISOFT_ACTION": "auth"}
    assert parsed.wrappers == []
    assert parsed.game_args == ["mangohud", "gamemoderun"]


def test_explicit_command_marker_does_split_correctly() -> None:
    """With ``%command%`` present the parser is right, which is the open question.

    The design call §2.9 defers is what a bare token *without* this marker
    means, not whether the marker itself works.
    """
    parsed = parse_launch_options("mangohud %command% -windowed --skip-intro")
    assert parsed.wrappers == ["mangohud"]
    assert parsed.game_args == ["-windowed", "--skip-intro"]


def test_runtime_state_no_longer_reads_started_at(tmp_path) -> None:
    """``started_at`` came off an always-empty dict and nothing read it.

    Elapsed time comes from ``LauncherService._launch_started_at``. Now that
    ``env_overrides`` carries user input, reading an internal timestamp out of
    it would be a trap.
    """
    ctx = _ctx("", tmp_path)
    assert LauncherService._build_runtime_state(ctx).started_at == 0.0
    assert isinstance(LauncherService._build_runtime_state(ctx), RuntimeState)
