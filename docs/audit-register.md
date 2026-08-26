# Audit remediation register

> **This file is the tracker.** The narrative it came from is
> `docs/architecture-audit.md` (historical, do not edit). The device-validation
> steps every `VALIDATING` row depends on are in `docs/device-validation.md`.
>
> Last updated: 2026-08-26 · Source review: 2026-08-24 against v0.7.5

## States

| State | Meaning |
|---|---|
| `OPEN` | Not started, or started and not finished. |
| `VALIDATING` | Code landed and gates pass, but **not yet confirmed on a Deck**. Not closed. See `device-validation.md`. |
| `CLOSED` | Fixed and confirmed — on device where the change is user-visible, by gate/test where it is not. |
| `DECLINED` | Deliberately not doing it. The reason is recorded in the tree, not only here. |

A row moves to `CLOSED` only when every device-validation step it names has
passed. Ticking a box without that is the failure this file exists to stop.

## ID rules

IDs are permanent and never reused. The 2026-08-24 register issued `26` three
times and `27` twice; those were resolved on 2026-08-26 as below, and the old
numbers must not be cited again.

| Old | Topic | Now |
|---|---|---|
| 26 (§3.3 pass) | legacy Ubisoft bootstrap markers | **43** |
| 26 (§3.1 pass) | `StoreInfo` write-only descriptor | **26** |
| 26 (§3.2 pass) | `check_version` / `min_version` | **44** |
| 27 (§3.1 pass) | `vulture_whitelist` group comments | **27** |
| 27 (§3.2 pass) | GOG-only progress phases | **45** |

`24` and `24a` were never parent and child — `24` is the vulture blind spot,
`24a` is the launch-options wipe. Both keep their ids.

---

## P0 — silent correctness

| ID | Title | State | Notes |
|---|---|---|---|
| 1 | Retire the phantom `GAME_INSTALLED` event | VALIDATING | DV-A1 |
| 2 | `MetricsCollector` timers/gauges wired | CLOSED | Fixed by `8b62be5` before the register was worked; verified both sides. |
| 3 | `TOAST_NOTIFICATION` retired onto `LAUNCHER_STAGE` | VALIDATING | DV-B1…B5 |
| 4 | `DOWNLOAD_*` single-emitter | VALIDATING | DV-C1…C8 |
| 4a | Circuit breaker is user-invisible and unresettable | OPEN | Blocked on **46**. Build per plan G2. Strings already in 16 locales. |
| 4b | No frontend renders a toast action | OPEN | Premise corrected: the only backend builder (`cloud_failure.py`) is dead — see **37**. Define the shape on the `{verb,args}` side. |
| 4c | `Result.error_code` never set on launch failures | OPEN | Every classified failure collapses to `GAME_FAILED` (8). |
| 4d | `check_hardcoded_strings` positional-key false positive | CLOSED | Call site now names the argument. |
| 4e | Event coalescing configured but never runs | OPEN | **Decision 2026-08-26: wire it** (plan G1d). `COALESCE_KEY[DOWNLOAD_PROGRESS]` names a kwarg no emitter sends. |
| 4f | No `download_cancelled` counter | VALIDATING | Done 2026-08-26. Incremented inside `_on_download_cancelled`, **not** as a `counter_events` row — that event already has a `@subscribe` handler and a row wires it twice (`test_every_handler_is_wired_exactly_once` catches it). Guard: `test_a_cancelled_download_is_counted`, verified against a planted violation. DV-C6 covers it. |
| 4g | `HandlerWatchdog` inert | OPEN | **Decision: wire it** (G1a/G1b). All 20 `auto_wire` sites pass `watchdog=None`. |
| 4h | Probe quarantine calls a method that does not exist | CLOSED | Fixed 2026-08-26 — call site and `hasattr` string both now `quarantine_preemptive`. Signature already matched. Still unreachable until 4i, but no longer wrong; gate-verified (mypy over 565 files). |
| 4i | Runtime-probe pipeline unbuilt end to end | OPEN | **Decision: build** (G1e), but scoped after 4e/4g prove the layer carries traffic. |
| 4j | `LaunchLogsService.export` callerless | OPEN | Two docstrings assert an `export_launch_logs` RPC that does not exist. |
| §1.3 | Event-bus mismatches | VALIDATING | DV-D1…D8 |
| §1.2 | Dead RPC methods (29 of 102) | CLOSED | User-validated on device 2026-08-25. |
| **46** | **Circuit breaker never resets on a successful launch** | VALIDATING | **P0, found and fixed 2026-08-26.** Reads `exit_code`/`elapsed_seconds` now — the names the emitter sends and `CANONICAL_SCHEMA` declares. Elapsed is measured by a new `_on_game_launched` monotonic stamp rather than by changing any payload, so no emitter, RPC or frontend call changed. New `tests/unit/test_launch_history_game_stopped_contract.py` (7 tests, the service had **none** before); 4 of them fail against the original `rc`/`elapsed` code — verified by planting it. Needs DV-L1. |

## P1 — consolidation

| ID | Title | State | Notes |
|---|---|---|---|
| 5 | Promote `merge_install_status` + `_rebuild_auth_after_injection` | VALIDATING | DV-E1…E12 |
| 6 | Unify CLI progress parsers; lift GOG's stall watchdog into shared | VALIDATING | DV-F1…F13 |
| 7 | Link the wrapper/CLI tables | VALIDATING | DV-G1…G9 (+G10, destructive-adjacent) |
| 8 | Migrate Ubisoft onto `shared/prefix_clone` | VALIDATING | DV-H1…H14 |
| 9 | Extract encrypted-token persistence | VALIDATING | DV-I4, DV-I5 |
| 10 | Delete `StoreBase._run_cli` | CLOSED | Deleted; zero callers confirmed. |
| 11 | Microsoft stubs return `not_supported` | VALIDATING | DV-J5, DV-J6 |
| 12 | `resolve_proton_path` collision + security package split | VALIDATING | DV-I1, DV-I2, DV-I3 |
| 19 | Encrypt Epic/Amazon credentials at rest? | OPEN | Mode (0600) is done; encryption is a separate decision. Wraps every legendary/nile invocation. |
| 20 | Three copies of `appid_candidates` | VALIDATING | Done 2026-08-26. Canonical in `core/compat_bridge.py` beside `to_unsigned` — **not** in `rpc/`, which is a leaf package two of the copies could not import. Routed 4 call sites (mypy found a fourth the audit never listed, `_library_facets.py`). Both it and `to_unsigned` are now pinned in `SHARED_HELPERS`. |
| 26 | `StoreInfo` is a mostly write-only descriptor | VALIDATING | Done 2026-08-26 with **31**. New `core/store_capabilities.py` is the single source of truth; `get_store_infos` injects four capability flags beside `available`/`client_runs_in_prefix`. `src/types/api.ts` now mirrors the wire shape (it declared `icon` and `auth_status`, **neither ever sent**, and omitted four that were). **Found while doing it:** `supports_cloud_saves` was a `StoreInfo` field only Battle.net declared — as `False` — so GOG and Epic, the only stores with cloud saves, both advertised none. Field deleted; a re-added literal raises `TypeError`. 10 parity tests pin each set against the code that implements it (registered strategies, defined methods, exposed RPCs). |
| 43 | Upgrade legacy Ubisoft bootstrap markers in place | OPEN | Precondition: DV-H11 must pass first. |
| 44 | `BinaryResolver.check_version` / `CLITool.min_version` unused | OPEN | Decide as one unit: call it at resolve time, or delete both and `version_flag`. |

## P2 — documentation and tooling

| ID | Title | State | Notes |
|---|---|---|---|
| 13 | Layer model stated only in the `architecture.md` diagram | CLOSED | Check 6 enforces; found two sites the audit missed. |
| 14 | Mixin count stated in exactly two machine-checked places | CLOSED | Check 5 enforces. |
| 15 | Six stores everywhere | CLOSED | Check 7 verifies rather than bans. |
| 16 | `StoreBase` contract documented correctly | CLOSED | Re-verified name by name. |
| 17 | Phantom "handler group" docstrings; undocumented subpackages | CLOSED | Check 8 enforces; caught 25 omissions on first run. |
| 18 | Version reconciliation | CLOSED | Closed by deleting `__version__`, not bumping it. |
| 20a | Move `cleanup_sweeps.py` out of the RPC leaf | CLOSED | `git mv`, no logic change, both import contracts KEPT. |
| 21 | Strip the `OP-XX` markers | OPEN | 234 occurrences / 149 ids / 164 files excluding `docs/archive/`. **Not a one-line sweep**: ~160 are docstring banners and ~69 are mid-sentence prose. Zero in executable code. |
| 22 | Re-verify stale skill `Last verified:` stamps | OPEN (partly done) | 2026-08-26: `unifideck-ci-gates` re-derived against `.github/workflows/*.yml` and bumped (its content already tracked — an old stamp on current content is still a false signal, audit C-4); `unifideck-drift-guard` given the stamp it never had. **Still open:** `unifidb-pipeline.md` (the only genuinely stale one), `unifideck-dev-loop` ×2, `unifideck-bug-triage` ×2 (one has no stamp), `unifideck-release`, `CLAUDE.md`. The durable fix is a check that every skill carries a stamp — nothing enforces existence today. |
| 23 | Wire the launch-options parser | VALIDATING | DV-K4 is the one that matters. DV-K7/K8/K10/K11 are unsatisfiable — see 23a/23b. |
| 23a | Wire `state.game_args` | OPEN | Fix `extractUserParams` first; it preserves `mangohud`/`gamemoderun` into the tail. |
| 23b | Delete `ParsedOptions.wrappers` / `RuntimeState.wrappers` | OPEN | 6 readers, 0 writers, unreachable by measurement — Steam applies wrappers pre-exec. |
| 24 | Vulture cannot see an unimported module | VALIDATING | Done 2026-08-26. New **check 12** in `validate_architecture.py` (hard) + **8 dead modules deleted**: `launcher/diagnostics/{telemetry,save_folder_inspector}.py`, `launcher/proton/fixes/auth_args_stripper.py`, `launcher/signals.py`, `security/audit_decorators.py` (a duplicate definition of the live `audit_emitter.audit_auth_flow`), `services/cloud_save/{fs_ops,paths}.py`, `steam/steamgriddb/match.py`. Verified: a planted orphan fails check 12 and vulture at 80 stays silent on it. 10 tests. Two opt-outs, `# entry-point:` and `# unimported:`, deliberately distinct. |
| 24a | `_update_existing_shortcut` wiped launch options | CLOSED | Severity corrected on device: a settled library takes the reclaim path, so the wipe was real code on an unreached path. |
| 25 | Steam-exported env dropped by the container escape | OPEN | Low priority; the working route is documented and verified. |
| 27 | `vulture_whitelist.py` group comments false per-member | OPEN | ~10× its recorded size: 9 of 14 groups false for a member, **6 named symbols do not exist**, 4 have real static callers. |
| 42 | Delete the dead root artifacts | OPEN | `build-plugin_old*.sh`, `main.py.backup`, `.gitignore.backup`, `task.md`, root `test_ubisoft_launch.py`. Needs maintainer sign-off. |

## Store behaviour and convergence

| ID | Title | State | Notes |
|---|---|---|---|
| 28 | Stall message reaches the user in English | OPEN | Needs one `errors.download.stalled` key × 16 manual translations. |
| 29 | Build the Battle.net `game_accounts` producer | OPEN | Every F2P and subscription title is invisible. **Measure DV-J4 before building.** |
| 30 | Stale-sweep invariant not machine-checked | OPEN | A second caller (`rpc/mixins/account.py:87`) already passes its own policy. |
| 31 | `_ACHIEVEMENT_STORES` has an unlinked frontend twin | VALIDATING | Done 2026-08-26 with **26**. Four TS lists deleted — both copies of `CLOUD_SAVE_STORES` (`useCloudSaveStatus.ts` and `PlayMeta.tsx`, the second admitting in a comment that it mirrored the first), the inline `gog||epic` achievements condition, and `LANGUAGE_STORES`' gate half. New `useStoreCapability` / `storeHasCapability` read the payload and **fail closed**. `LANGUAGE_ROUTE` survives because it maps store→route, which the payload does not carry. |
| 32 | Ubisoft update path has no trigger; GOG DLC has no route | OPEN | Decide each as one unit: build the missing half or delete it. |
| 33 | No pre-install size or space guard for the wrapper stores | OPEN | A 90 GB vendor install can start with 1 GB free. |
| 45 | Progress phases exist for GOG only | OPEN | Note `phase_message` is never rendered — 5 producers of dead weight. |
| **48** | **`get_installed_path` duplicated across three stores** | VALIDATING | Done 2026-08-26. New `stores/shared/installed_path.install_path_from_record`, consumed by GOG, Ubisoft and Amazon (`key="path"` carries nile's field name). **Only the guard is shared, not the fetch** — §3.2's lesson; Epic and Battle.net keep their own resolvers because their sources differ in kind. The guard is where §3.4 found the live blank-path defect. 14 tests incl. the empty-string and JSON-array cases; check 11 verified to reject a re-added copy. |

## Declined, on the record

These are decisions, not unfinished work. Each reason is written into the tree
so it is not re-filed as drift.

| Topic | Why |
|---|---|
| Migrate Ubisoft onto `shared/wrapper_session_hooks` | `SPECS` has only a `battlenet` row, so the mixin is **inert** for Ubisoft. Migrating swaps working behaviour for a no-op. |
| Migrate Ubisoft onto `shared/auth_shortcut` | ~580 lines into `shared/` for one consumer, on the store with the longest sign-in incident history. **Re-affirmed 2026-08-26.** Revisit when a third wrapper store arrives — that is the trigger. |
| `ubisoft_recovery.clone_template_into` is not the shared clone | Runs under system Python, synchronous, needs a `cp -a` fallback, and restores the target's own Proton marker across the copy. |
| `ARTWORK_REQUEST` kept with no emitter | Deliberate entry point for a force-refetch trigger. Marked `# unwired:`. |
| `PLAYTIME_SYNC_COMPLETE` / `_FAILED` kept unwired | Surfacing "your playtime reached GOG" is wanted; it has no UI yet. |
| `cloud.failure_behavior` RPCs deleted rather than wired | **Reasoning invalidated 2026-08-26** — it rested on `cloud_failure.py` being live, and it is not (**37**). Re-open as a product question, not a code one. |

## New items found 2026-08-26

Found by re-deriving against the tree rather than reading the register.

| ID | Title | State |
|---|---|---|
| 34 | Shadow-package trap: `launcher/fixes/` + `launcher/language_setup/` | **CLOSED** — 13 stub files deleted 2026-08-26; gates green, real `launcher/proton/*` intact. |
| 35 | `inject_game_to_appinfo` wastes an RPC per overview read | OPEN |
| 36 | A `%command%`-leading `LaunchOptions` never launches, and sync preserves it | OPEN |
| 37 | `launcher/cloud/cloud_failure.py` is a dead 263-line module | OPEN |
| 38 | `set_bus_collaborators` has zero callers (check 4 misses sync methods) | CLOSED — deleted 2026-08-26; `pipeline_factory` already assigned those attributes directly. **Check 4 was NOT widened**: its docstring is right that a sync method is not RPC surface, so reporting one as a dead *RPC* would be a false claim. The blind spot is real but belongs to check 12 / vulture, not to the RPC arm. |
| 39 | `ROW_CONFIG` waits for status strings no backend emits | OPEN |
| 40 | `assert_all_keys_resolve` has zero callers; CI comments describe it as the boot check | VALIDATING — fixed 2026-08-26. Deleted the strict variant and `KeyPresenceError` (44 lines, zero callers, docstring claiming it ran at boot and was fatal). `collect_missing_keys` **is** the boot check and deliberately warns into degraded mode rather than aborting. Corrected **five** false statements: its own docstring, `collect_missing_keys`' docstring, three in `check_config_keys.py`, one in `quality.yml`. |
| 41 | Two dead defensive fallbacks on `POST_SYNC_PHASE_CHANGED` | CLOSED — deleted 2026-08-26. All four emitters send `sync_kwargs` or omit it; no emitter has ever sent a flat `games`/`is_force`. `TOLERATED_SUBSCRIBER_READS` is back to empty, which is the goal — an exemption is a place for a defect to hide. |
| 46 | Circuit breaker never resets on success (P0 — listed above) | OPEN |
| 47 | `SHARED_HELPERS` is name-exact, so a renamed copy escapes check 11 | OPEN |

## Gate blind spots to close

Each closes a defect class the audit hit repeatedly. These are the durable half.

| ID | Gate | First-run expectation |
|---|---|---|
| G-C1 | ✅ **DONE** — check 3 added, locale→code | 271 grandfathered in `scripts/i18n_unused_baseline.json` (**shrink-only**); a new dead key fails immediately. 8 tests. Verified: planting one key in all 16 locales exits 1; 85 backend-named keys correctly excluded. |
| G-C2 | ✅ **DONE** — subscribe-side arm added | Found exactly the predicted 3 over 57 handlers: the P0 (**46**) and two dead fallbacks (**41**, in `TOLERATED_SUBSCRIBER_READS`). 6 tests. Verified: re-planting `rc` fails the gate. |
| G-C3 | ✅ **DONE** — check 12 added | 9 orphans found, 8 deleted, 1 marked `# unimported:` (item **37**). 10 tests. Verified: a planted orphan fails check 12 while vulture at 80 stays silent. |
| G-C4 | ❌ **NOT DONE — and should not be** | Check 4's docstring is correct that a sync method is not RPC surface, so reporting one as a dead *RPC* would be a false claim. The one instance (**38**) was a redundant setter and is deleted. The real blind spot (a public method nothing calls) belongs to vulture/check 12. |
| G-C5 | Check 11 is name-exact | items **20**, **47** |
| G-C6 | Capability parity between the `get_store_infos` payload and `src/` | items **26**, **31** |

Every gate is tuned against **planted violations**, not just a clean tree. That
is the house rule and the reason the existing eleven checks survived.

---

## How to work this file

1. Pick a row. Re-derive it against the tree before doing anything — the
   2026-08-24 review found that of eleven lines in one section, one was outright
   wrong, one stale, one understated by an order of magnitude, and the two
   costliest defects were absent. **Do not work the list; work the tree.**
2. When the fix lands and gates pass, set `VALIDATING` and add its steps to
   `device-validation.md`.
3. When the steps pass on a Deck, set `CLOSED`.
4. If you decline it, move it to the declined table **and write the reason into
   the code**, not just here.
