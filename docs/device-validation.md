# Device-validation ledger

> Every `VALIDATING` row in `docs/audit-register.md` points here. A fix is not
> closed until its steps pass **on a Steam Deck**, per
> `validation-means-user-installs-and-tests`.
>
> Consolidated 2026-08-26 from 13 separate session plans in `~/.claude/plans/`,
> each of which restarted its own `V`/`TV`/`D` numbering — `TV-1` meant five
> different tests. **IDs here are globally unique and permanent.**

## How to run

```bash
pnpm run build && ./build-plugin.sh dev quick-install
sudo systemctl restart plugin_loader
# logs: ~/homebrew/logs/Unifideck/   ·  bundles: QAM Settings → Capture Logs
```

Record what you actually observed in the Evidence column, not "ok". A step with
no evidence is not a passed step.

**⚠ Before running anything marked `DESTRUCTIVE`, ask.** Those can delete a real
install.

## Status key

`( )` not run · `(P)` passed · `(F)` failed · `(B)` blocked · `(R)` retired

---

## Standing post-change sweep — SW1…SW5

Run after **any** change in this programme. These replace the near-identical
"nothing else moved" steps that appeared separately in five different plans.

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| SW1 | Full library sync across all six stores | Reconcile tally line: no unexpected `removed=`; game count unchanged | ( ) | |
| SW2 | Open App Details for one game per store | Panel renders; no missing metadata, size or artwork | ( ) | |
| SW3 | Launch one already-installed game | Launches; correct per-game prefix in `game.log` | ( ) | |
| SW4 | QAM → Store Connections after `systemctl restart plugin_loader` | All six rows, correct connected/disconnected state | ( ) | |
| SW5 | QAM → Capture Logs | Bundle builds clean; no traceback | ( ) | |

---

## DV-A — item 1, `GAME_INSTALLED` retired

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| DV-A1 | Install any game, then check the `[Unifideck] Installed` collection | The game appears **without** a full re-sync — this is the bug the retirement fixed | ( ) | |

## DV-B — item 3, `TOAST_NOTIFICATION` → `LAUNCHER_STAGE`

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| DV-B1 | Trip the circuit breaker (3 failed launches in 10 min), press Play | A toast naming the game, not silence | ( ) | |
| DV-B2 | Force a terminal `LauncherError` | Toast with the error's own key | ( ) | |
| DV-B3 | Force a shortcut-write refusal | Toast, visible for ~12s not 7.5s | ( ) | |
| DV-B4 | Existing launcher toasts | No regression | ( ) | |
| DV-B5 | Repeat DV-B1 in **Gaming Mode** | Toast renders there too | ( ) | |

## DV-C — item 4, `DOWNLOAD_*` single-emitter

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| DV-C1 | Fail an **Epic** install | **One** toast, carrying the game's name (was two, one unnamed) | ( ) | |
| DV-C2 | Fail an **Amazon** install | Same shape | ( ) | |
| DV-C3 | Successful Epic install | `download_completed` increments **once** in the bundle | ( ) | |
| DV-C4 | Successful Amazon install | Same | ( ) | |
| DV-C5 | GOG control | Unchanged — proves nothing moved for the other four stores | ( ) | |
| DV-C6 | Cancel an install | No `_pending_timers` leak; `download_duration_ms` absent, not wrong | ( ) | |
| DV-C7 | Epic **update** path | Same as DV-C1/C3 | ( ) | |
| DV-C8 | Ubisoft + Battle.net install smoke test | Manual phase still indeterminate, no regression | ( ) | |

## DV-D — §1.3, event-bus mismatches

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| **DV-D1** | **Suspend mid-game and wake** — play ~2 min, suspend ~10 min, wake, quit | Session records ~2 min, **not ~12**. The one that must pass. | ( ) | |
| DV-D2 | Play across local midnight | Day attribution unchanged | ( ) | |
| DV-D3 | Ordinary session | Still recorded | ( ) | |
| DV-D4 | Make the Game Pass subscription probe fail (drop network mid-sync) | A toast explains the skip; the xCloud library is not silently dropped | ( ) | |
| DV-D5 | Sync the other five stores | Skip toast does **not** fire for them | ( ) | |
| DV-D6 | Sign in to Battle.net | Its sign-in tile has artwork, not a bare tile | ( ) | |

## DV-E — item 5, `merge_install_status` + browser-auth rebuild

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| DV-E1 | Install an Epic game → Force Sync | Tile stays INSTALLED and launches | ( ) | |
| DV-E2 | `rm -rf` an installed Epic game's directory by hand → Force Sync | Tile flips to **not installed** (the strict-check convergence) | ( ) | |
| **DV-E3** | **GOG installed → Force Sync** | Still INSTALLED, `exe_path` intact — the one thing consolidation could break | ( ) | |
| DV-E4 | Amazon install → Force Sync | INSTALLED and launches | ( ) | |
| DV-E5 | Blank one entry's `path` in `~/.config/nile/installed.json` → sync | That row is **not** marked installed (the deliberate behaviour change) | ( ) | |
| DV-E6 | Sign out and back in via QAM on one browser-auth store | Full CDP flow completes | ( ) | |
| DV-E7 | Ubisoft sign-in from the QAM | Works — proves its own hook was not swept into the shared mixin | ( ) | |
| **DV-E8** | **Start a GOG install after a plugin restart** | Spawns — proves `_after_auth_flow_built` still populates `_gogdl_bin`. Highest-risk row. | ( ) | |
| DV-E9 | Boot log after restart | `[prefix_bridge] reclaimed …` present | ( ) | |
| DV-E10 | QAM compatdata cleanup panel | Every prefix size matches the shared `dir_size_bytes` walk | ( ) | |

## DV-F — item 6, CLI-store drift

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| DV-F1 | Cancel a **GOG** install at ~20% | Row flips to Cancelled **and no `gogdl` process survives** | ( ) | |
| DV-F2 | Cancel an **Amazon** install, stopwatch it | Returns in **under ~2s** (was blocking up to 3600s) and no `nile` survives | ( ) | |
| DV-F3 | Cancel an **Epic** install | Control — unchanged, still clean | ( ) | |
| DV-F4 | Uninstall the DV-F1 game, then `ls` its directory | Gone and stays gone — no orphan rewriting files | ( ) | |
| DV-F5 | Drop Wi-Fi during a GOG install | Error is **localized and specific**, not the bare token `download_failed` | ( ) | |
| DV-F5b | Repeat DV-F5 with a non-English UI language | Still localized | ( ) | |
| DV-F6 | `pkill -STOP -f gogdl` at ~30%, resume at 60s | Nothing happens — a live-but-slow install is never killed | ( ) | |
| DV-F7 | Same, left stopped past 120s | Fails with a stall message at ~120s | ( ) | |
| **DV-F8** | **Repeat DV-F7 on Epic, then Amazon** | Each fails at ~120s — **the new behaviour**; these two had no stall detection at all | ( ) | |
| DV-F9 | Large GOG install through extraction | Not killed during the quiet tail (finalize window) | ( ) | |
| DV-F10 | One install on each of GOG/Epic/Amazon, screenshot at ~50% | No negative transfer rate; consistent formatting | ( ) | |
| DV-F11 | `grep -i 'BinaryResolver.*gogdl' ~/homebrew/logs/Unifideck/*.log` | Tier-1 hit — GOG now goes through the resolver, so SHA256 and the exec-bit test run | ( ) | |
| DV-F12 | Sign out and in on Epic and Amazon, then `stat -c '%a %n' ~/.config/{legendary,nile}/user.json` | Both `600` | ( ) | |

## DV-G — item 7, wrapper/CLI tables

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| DV-G1 | QAM → Store Connections | Six rows | ( ) | |
| DV-G2 | `storeInfoStore.getSnapshot()` in the console | `uses_wine` **absent**, `client_runs_in_prefix` **present** | ( ) | |
| DV-G3 | Launch a Ubisoft game | Skips the generic redistributable step (~90s saved) | ( ) | |
| DV-G4 | Launch a GOG game | Still **runs** generic compat — the inverse guard | ( ) | |
| DV-G5 | Wrapper-store install | Progress is indeterminate (manual phase), not a fake % | ( ) | |
| DV-G6 | Cart button on Ubisoft and Battle.net | Opens the client storefront | ( ) | |
| DV-G7 | Cart button on Epic | Opens the Edge storefront | ( ) | |
| DV-G8 | Sign out/in on one wrapper and one CLI store | Both complete | ( ) | |
| DV-G9 | **DESTRUCTIVE** — Proton-family-change regression guard | Prefix reset does **not** delete a Ubisoft install. **Ask before running.** | ( ) | |

## DV-H — item 8, wrapper-store drift (Ubisoft)

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| DV-H1 | Cancel a Ubisoft install mid-download | UPC's own logs **survive** in `launches/*.vendor.txt` | ( ) | |
| DV-H2 | Force a Ubisoft install to fail | Same | ( ) | |
| DV-H3 | Capture Logs after DV-H1 | Bundle contains the `.vendor.txt` | ( ) | |
| DV-H4 | Cancel before the UPC window appears | Nothing to salvage is not an error | ( ) | |
| **DV-H5** | **Identity repair on an installed Ubisoft game** (the `--checksum` proof) | The identity files are actually rewritten, not skipped by the quick check | ( ) | |
| DV-H6 | Fresh Ubisoft install | First clone not slowed (~12s / 1.6 GB band) | ( ) | |
| DV-H7 | Sign out of Ubisoft, sign back in | `deriving template …` — template refresh realigns | ( ) | |
| **DV-H8** | **Play a Ubisoft game ~1 min, quit via Steam** | Capture waits for UPC to exit, then succeeds — no torn vault read | ( ) | |
| DV-H9 | Immediately launch a **different** Ubisoft game | Opens already signed in — the symptom DV-H8 prevents | ( ) | |
| DV-H10 | During DV-H8, watch playtime and library | The bounded wait does not starve other `GAME_STOPPED` work | ( ) | |
| **DV-H11** | **Legacy markers still read as installed** — check a prefix created before this build | Ubisoft games installed on the old plaintext marker are still detected. **The only step that can regress an existing install, and the precondition for item 43.** | ( ) | |
| DV-H12 | Trigger a fresh clone or repair, read the marker | JSON content, **same filename** | ( ) | |
| DV-H13 | Restart `plugin_loader`, let the orphan sweep run | No prefix reported as unowned | ( ) | |
| DV-H14 | After DV-H1…H13, re-count prefixes | No prefix lost | ( ) | |

## DV-I — items 9 and 12, token persistence and the security split

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| DV-I1 | Epic/Amazon credential permissions after sign-in | `600` | ( ) | |
| DV-I2 | Permissions after a token rotation | Still `600` — the CLIs rewrite at 0644 on every refresh | ( ) | |
| DV-I3 | Sign-out / sign-in round trip | Clean | ( ) | |
| **DV-I4** | **GOG token round trip survives the `EncryptedTokenFile` extraction** | Still signed in after a restart. Flagged highest risk of that pass. | ( ) | |
| DV-I5 | Microsoft/xCloud token round trip | Still signed in | ( ) | |
| DV-I6 | Support bundle `security` block | Reports permission checks for **four** stores through one channel | ( ) | |
| DV-I7 | Force Compatibility on a game | Still resolves to the chosen Proton | ( ) | |
| DV-I8 | Wrapper-store prefix bridging | Cloud saves / size / forensics read the real prefix | ( ) | |
| DV-I9 | Auth shortcut cleanup | Temp sign-in tiles removed after sign-in | ( ) | |
| DV-I10 | Orphan sweep | Removes nothing real. **DESTRUCTIVE-adjacent — ask.** | ( ) | |
| DV-I11 | Uninstall a game installed to a **custom path / SD card** | Manifest still drives the sweep; directory actually goes | ( ) | |

## DV-J — items 11 and 29, partial-implementation flags

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| **DV-J1** | **Make one store fail to answer during a sync** (sign out, or block its network) | Its shortcuts **survive**. The most serious defect in Part 3. | ( ) | |
| DV-J2 | Move `bin/gogdl` aside, sync | GOG shortcuts survive — the regression path the §3.2 fix opened | ( ) | |
| DV-J3 | A genuinely **empty** store | Still swept — the phantom-cleanup case that must not be lost | ( ) | |
| **DV-J4** | **Battle.net library baseline** — record the title count and name the missing F2P/subscription titles | This is a **measurement, not a test**, and it is the precondition for item 29 | ( ) | |
| DV-J5 | Open App Details for an xCloud game | No Install button mounts | ( ) | |
| DV-J6 | Force the Microsoft install path | Refuses with a **translated** message, and the queue row reaches "failed" | ( ) | |
| DV-J7 | Install one Ubisoft and one Battle.net game end to end | Works | ( ) | |

## DV-K — item 23, launch-options parser

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| DV-K1 | Plugin imports after the `dispatcher.py` split | No import error | ( ) | |
| DV-K2 | Version reporting | Reads `package.json` | ( ) | |
| DV-K3 | Account-switch path | Modal still appears | ( ) | |
| **DV-K4** | **Launch a game with NO launch options** | Launches exactly as before. **The regression guard — the one that matters.** | ( ) | |
| DV-K5 | `<store>:<id> MY_VAR=hello` | `MY_VAR` present in `/proc/<pid>/environ` of the **game** process | ( ) | |
| DV-K6 | `<store>:<id> WINEDLLOVERRIDES=…` | User's entry first, Proton's appended after | ( ) | |
| DV-K7 | `<store>:<id> LSFG=1` | `ENABLE_LSFG=1` plus the three `~/lsfg` exports on the game process | ( ) | |
| DV-K8 | `<store>:<id> MY_QUOTED="alpha beta"` | Arrives intact, not truncated to `alpha` | ( ) | |
| DV-K9 | Native Linux game path | Unaffected | ( ) | |
| DV-K10 | Force-Compat re-prepare | Still resolves | ( ) | |
| DV-K11 | *(retired)* wrapper words populate `state.wrappers` | **RETIRED** — item 23b established wrappers are unreachable; Steam applies them pre-exec | (R) | Retired 2026-08-26 |
| DV-K12 | *(retired)* game args populate `state.game_args` | **RETIRED** — deferred to item 23a; wiring it today passes `mangohud` to the game | (R) | Retired 2026-08-26 |

## DV-L — item 46, the circuit breaker resets on success (P0)

| ID | Step | Expected | Status | Evidence |
|---|---|---|---|---|
| **DV-L1** | Trip the breaker on one game (3 failed launches inside 10 min), then make it launch successfully and quit normally | The next Play is **not** refused. Log shows `Wiped failures after success for <store>:<id>`. Before the fix this line could never appear. | ( ) | |
| DV-L2 | `cat ~/.local/share/unifideck/launch_history.json` after DV-L1 | The game's `failures` array is gone, not merely expired | ( ) | |
| DV-L3 | Launch and quit a game that was never failing | No failures recorded; no spurious entry created | ( ) | |
| DV-L4 | Press Stop mid-game (signal termination) | Not recorded as a launch failure | ( ) | |

---

## Lost baselines

`~/.claude/plans/…lively-rain.md` required DV-F1…DV-F4 to be captured **once on
the pre-fix build** as a before/after comparison. The build has moved, so that
baseline no longer exists. Run DV-F1…F4 as absolute assertions ("no process
survives") rather than as a comparison — the assertion is the real requirement
and it stands on its own.

## Decisive steps

If time is short, these are the ones the original plans named as deciding their
change: **DV-D1, DV-E3, DV-E8, DV-F8, DV-H5, DV-H8, DV-H11, DV-I4, DV-J1,
DV-J4, DV-K4.** DV-H11 is the only one that can regress an existing install.
