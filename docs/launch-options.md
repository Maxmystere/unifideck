# Launch Options Guide

This guide explains how to pass extra options (performance overlays, Proton/Wine tweaks,
debug flags) to a Unifideck game, **what currently works**, and **what is planned but not
yet wired up**.

> [!IMPORTANT]
> Unifideck used to parse rich launch options (wrapper programs, `~/lsfg`, `PROTON=`)
> itself. After the 0.7 architecture rewrite that parser is **present but not yet connected
> to the launcher**, so today only **environment-variable** tweaks take effect, and they do
> so through Steam's standard `%command%` mechanism — not through Unifideck. See
> [Planned / not yet wired](#planned--not-yet-wired) for the rest.

---

## How a Unifideck game launches

Every Unifideck game is a **non-Steam shortcut** whose target (`Exe`) is the Unifideck
launcher and whose **Launch Options** hold the game's identifier, e.g.:

```
epic:Salt
```

When you press Play, Steam runs `unifideck-launcher epic:Salt`. The launcher reads **only**
the `store:game_id` token (plus internal `UNIFIDECK_*` flags); it then sets up the Wine
prefix and hands off to Proton/umu, **inheriting the current environment**. That last part
is the key: anything in the launcher's environment is passed through to the game.

---

## What works today — environment-variable tweaks

Because the game inherits the launcher's environment, you can set environment variables for
a game using Steam's standard **`%command%`** convention. Edit the shortcut's launch
options:

1. Steam **Library** → right-click the game → **Properties**
2. **Shortcut** → **Launch Options**
3. Put your `VAR=value` assignments **before** `%command%`, and keep the `store:game_id`
   token **after** it:

```
MANGOHUD=1 DXVK_HUD=fps %command% epic:Salt
```

Steam exports the leading `VAR=value` assignments into the environment and replaces
`%command%` with the launcher, so it runs `MANGOHUD=1 … unifideck-launcher epic:Salt` — the
launcher inherits `MANGOHUD`/`DXVK_HUD` and the game picks them up.

> [!TIP]
> After editing, launch once to confirm it took effect (e.g. `MANGOHUD=1` should show the
> overlay). Behavior depends on Steam's `%command%` handling for non-Steam shortcuts.

Since 0.7.5 there is a second route that does not depend on Steam's `%command%` handling:
any `VAR=value` token you leave **after** the `store:game_id` token is read by the launcher
itself and applied to the game's environment. So both of these work:

```
WINEDLLOVERRIDES="icuuc=b" %command% epic:Salt     ← Steam sets it
epic:Salt WINEDLLOVERRIDES="icuuc=b"               ← the launcher sets it
```

The launcher applies its own overrides **last**, so a variable you set this way wins over
the one Unifideck would have chosen for that game. That is the point (it is how you override
a bad default) and also the risk, so change one variable at a time.

### Useful variables

| Variable | Effect |
| --- | --- |
| `MANGOHUD=1` | Enable the MangoHud performance overlay |
| `MANGOHUD_CONFIG=fps_limit=60,...` | Configure MangoHud |
| `DXVK_HUD=fps,frametime` | DXVK's built-in stats overlay |
| `DXVK_FRAME_RATE=60` | Cap the frame rate via DXVK |
| `PROTON_USE_WINED3D=1` | Use OpenGL (WineD3D) instead of DXVK/VKD3D |
| `PROTON_NO_ESYNC=1` / `PROTON_NO_FSYNC=1` | Disable esync/fsync (workaround for some games) |
| `PROTON_ENABLE_NVAPI=1` | Enable NVAPI emulation |
| `WINEDLLOVERRIDES="dxgi=n,b"` | Override specific Wine DLLs |

> [!NOTE]
> Quote values containing spaces: `WINEDLLOVERRIDES="..."`.

### What you cannot override this way

The launcher sets these itself and will **overwrite** any value you provide, so don't bother
setting them in launch options:

```
PROTONPATH  WINEPREFIX  STEAM_COMPAT_DATA_PATH  STEAM_COMPAT_INSTALL_PATH
GAMEID  STORE  PROTON_VERB  DXVK_NVAPI_ALLOW_OTHER_DRIVERS
```

In particular, you **cannot** pick a Proton version with `PROTONPATH=`/`PROTON=` — see
[Choosing a Proton version](#choosing-a-proton-version).

### Persistence across library sync

- A normal **library sync keeps** your edited launch options (existing shortcuts are matched
  and left alone).
- A **Force Sync resets** a managed shortcut's launch options back to the plain
  `store:game_id`, **removing your customizations**. Re-add them after a Force Sync.
- Whatever you set, the `store:game_id` token must remain present — Unifideck finds the game
  by searching the launch options for it. Remove it and Unifideck will treat the shortcut as
  unmanaged and create a duplicate.

---

## Choosing a Proton version

Proton is **not** selected via launch options. Use Steam's native compatibility setting —
see **[Proton Compatibility](proton-compatibility.md)** for the full guide. In short: open
the game's **Properties → Compatibility**, tick *"Force the use of a specific Steam Play
compatibility tool"*, and choose a tool. Unifideck detects your choice and applies it at
launch. The default (no choice) is the latest GE-Proton.

---

## LSFG frame generation

[lsfg-vk](https://github.com/xXJSONDeruloXx/decky-lsfg-vk) is opted into with either env
flag, after the `store:game_id` token:

```
epic:Salt LSFG=1
epic:Salt ENABLE_LSFG=1
```

The launcher reads the `export` lines out of the plugin's `~/lsfg` script and applies them
to the game, so a configured profile is picked up. Anything you set explicitly in launch
options still wins over the script's value. Requires Lossless Scaling (Steam) plus the Decky
LSFG-VK plugin plus a configured profile.

## Not supported

- **Wrapper programs as launch-option words** — `gamemoderun` or `mangohud` written as a
  bare word. Use Steam's own `%command%` form (`mangohud %command% epic:Salt`), which Steam
  applies before the launcher ever runs, or the `MANGOHUD=1` env var. A bare word left after
  the `store:game_id` token is ignored: by the time Steam has expanded `%command%`, the
  launcher cannot tell a wrapper program from a game argument, and guessing wrong would pass
  `mangohud` to the game as an argument.
- **Game arguments** — same reason. Tracked in `docs/architecture-audit.md` §2.9.
- **`PROTON=GE-ProtonX-Y`** — never implemented. Use Steam's Compatibility dropdown, above.

---

## Troubleshooting

**An environment variable isn't applied** — make sure you used the
`VAR=value %command% store:game_id` form (the `%command%` is required for Steam to export
the variable), the name is `ALL_CAPS` with no spaces around `=`, and it isn't one of the
launcher-managed variables listed above. Launch once and check.

**My options vanished** — a **Force Sync** resets launch options to `store:game_id`. Re-add
your customizations afterward. (A normal sync preserves them.)

**The game won't start** — don't remove the `store:game_id` token, and don't change the
shortcut's target (the launcher path). If you suspect a Proton/prefix problem, see
[Proton Compatibility → Troubleshooting](proton-compatibility.md#troubleshooting--quick-fixes).

**Wrappers / `~/lsfg` / `PROTON=` do nothing** — these are
[not yet wired up](#planned--not-yet-wired) in the current build.
