# Audit remediation register

> **This file is the tracker.** The narrative it came from is
> `docs/architecture-audit.md` (historical, do not edit). The device-validation
> steps every `VALIDATING` row depends on are in `docs/device-validation.md`.
>
> Last updated: 2026-08-26 · Source review: 2026-08-24 against v0.7.5
>
> **Progress this pass:** 15 CLOSED · 31 VALIDATING (fixed, awaiting the Deck)
> · 17 OPEN. Seven gate blind spots were the durable half; see the gate table.

## States

| State | Meaning |
|---|---|
| `OPEN` | Not started, or started and not finished. |
| `VALIDATING` | Code landed and gates pass, but **not yet confirmed on a Deck**. Not closed. See `device-validation.md`. |
| `CLOSED` | Fixed and confirmed — on device where the change is user-visible, by gate/test where it is not. |
| `DECLINED` | Deliberately not doing it. The reason is recorded in the tree, not only here. |
| `BLOCKED` | Cannot proceed until a **decision** is made — not until other code lands. The blocking question is named in the row. |

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
| 4a | Circuit breaker is user-invisible and unresettable | VALIDATING | Built 2026-08-26 (G2). New `useCircuitState` subscribes `circuit_state_changed` — written from the **corrected** payload contract, since the enum docstring had documented four keys that were never sent — with `get_launch_failures` as the mount fallback, because the event only fires on a *change*. Badge + Force-launch + Reset render in `PlayMeta`, gated on the breaker actually being open. Three routes added; **three `# no-frontend-caller:` exemptions removed** (5 → 2) and the event's `# unwired:` exemption removed (5 → 4). **Zero new strings** — all of `library.circuitBreaker.*` already existed in 16 locales; 3 keys drained from the dead-key baseline. Depends on **46**, without which the badge would show failures that never clear. |
| 4b | No frontend renders a toast action | VALIDATING | **Unblocked and built 2026-08-26** once 37 was decided — before that a generic renderer would have had nothing to render. New `resolveToastAction` shared by both listeners; Decky toasts take an `onClick`, not a button, so the toast is the affordance and the label sits in the subtext. **Three producers of one field had drifted into three shapes**: `_emit_save_conflict` sent `{verb,args}`, `cloud_failure` sent `{i18n_label_key,target_url}`, and `launcherToasts.tsx` redeclared the type a third time. All converged on `{verb,args,i18n_label_key}`; a Steam deep link is the `open-url` verb so one shape covers both. **The trap:** `retry-sync` now has two producers with opposite intent — a real conflict (with snapshots, needs the pick modal) and a transient failure (nothing to choose). Branching on the verb alone would open a pick modal with two empty sides on every dropped Wi-Fi, so both renderers discriminate on the snapshots via `isConflictAction`. Unknown verbs fail closed. Three action labels became reachable for the first time; the dead `openSaveFolder`/`showLogs` pair was deleted (their modals do not exist) and the baseline shrank. |
| 4c | `Result.error_code` never set on launch failures | VALIDATING | Fixed 2026-08-26 at all three sites, so `CIRCUIT_BREAKER_OPEN` (9) stops being a dead branch and the classification is no longer discarded. **The second half resolved the other way:** `ExitCode.user_message_key()` was deleted, not wired — eight of the nine `toasts.launcher.*` keys it returned **were never written into any locale**, so wiring it would have shown users raw key names. That is the inverse of §1.1.2 and nothing could catch it, which is why `check_orphan_keys` gained **check 4** (backend-named keys must have a string; all 48 real `i18n_key=` literals resolve). Specific per-failure messages are a deliberate 8×16-translation feature, filed with **28**/**49**. |
| 4d | `check_hardcoded_strings` positional-key false positive | CLOSED | Call site now names the argument. |
| 4e | Event coalescing configured but never runs | OPEN | **Decision 2026-08-26: wire it** (plan G1d). `COALESCE_KEY[DOWNLOAD_PROGRESS]` names a kwarg no emitter sends. |
| 4f | No `download_cancelled` counter | VALIDATING | Done 2026-08-26. Incremented inside `_on_download_cancelled`, **not** as a `counter_events` row — that event already has a `@subscribe` handler and a row wires it twice (`test_every_handler_is_wired_exactly_once` catches it). Guard: `test_a_cancelled_download_is_counted`, verified against a planted violation. DV-C6 covers it. |
| 4g | `HandlerWatchdog` inert | VALIDATING | Wired 2026-08-26 (G1a + G1b). **Not by editing 20 call sites** — services get a bus, not the pipeline, so threading it by hand meant a new parameter on every service with 20 chances to miss one. `pipeline_factory` attaches the watchdog to the **bus** and `auto_wire` falls back to it: one assignment, no call-site churn. Boot order asserted (layer 2 pipeline before layer 5 services), since a service built earlier would silently miss registration — the same bug one layer up. `EventBus._invoke` now runs handlers through `watchdog.invoke`, with a thunk so **sync** handlers still go to a thread (`invoke` awaits directly and would have raised on every one) and a fallback so a stub watchdog can never block delivery. A quarantine skip logs at WARNING, not ERROR — it is a deliberate skip and the other handlers still run. Corrected `priority_dispatcher`'s docstring, which claimed "the bus uses the watchdog internally" from the start. `emit()` hit the 80-line cap and was **split**, not allowlisted. 9 tests, verified against a planted removal of the fallback. Needs DV-N1. |
| 4h | Probe quarantine calls a method that does not exist | CLOSED | Fixed 2026-08-26 — call site and `hasattr` string both now `quarantine_preemptive`. Signature already matched. Still unreachable until 4i, but no longer wrong; gate-verified (mypy over 565 files). |
| 4i | Runtime-probe pipeline unbuilt end to end | OPEN | **Decision: build** (G1e), but scoped after 4e/4g prove the layer carries traffic. |
| 4j | `LaunchLogsService.export` callerless | VALIDATING | Done 2026-08-26: `export` deleted, and **both** docstrings that asserted an `export_launch_logs` RPC corrected (`launch_logs.py` and `service_defs.py`) — the RPC was deleted in the §1.2 pass and Capture Logs already collects the same `launches/*.log` files. `read`/`get_launch_logs` kept but recorded as unreachable pending 4b/37. Corrected a third false comment found alongside: `service_defs.py` called the plugin's `LaunchHistoryService` "read-only by convention" — item 46 made it the **only** writer that can clear a tripped breaker. |
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
| 44 | `BinaryResolver.check_version` / `CLITool.min_version` unused | VALIDATING | Decided 2026-08-26: **deleted**, as one unit — `check_version`, `min_version`, `version_flag`, the three per-store `version_flag=` literals, the `_version_timeout` knob, its `binary_resolver.version_check_timeout_seconds` config key (defaults + schema + `RUNTIME_REQUIRED_KEYS`) and both vulture-whitelist rows. The only apparent call site was inside the class's own `Usage::` docstring. Deleted rather than built because SHA-256 pinning in `package.json` is the stronger guarantee, and the tree's one real version constraint is a **maximum** (nile pinned at 1.1.2) that `min_version` could not express. |

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
| 21 | Strip the `OP-XX` markers | VALIDATING | Done 2026-08-26. **Zero `OP-` references remain** in `py_modules/`, `main.py`, `src/`, `scripts/` or `tests/`; `docs/archive/` is untouched by design. 151 files: 147 banner lines (`OP-09 | <path>` — a stale plan id plus a path restating the file's own) deleted outright, 71 inline parentheticals stripped in four measured shapes (` (OP-x)`, `, OP-x)`, ` from OP-x)`, `(owned by OP-x)`), 2 handled by hand. **Not a `sed` job, as the audit warned** — only 3 of 220 were `#` comments; the rest were inside docstrings, where a line-delete would have corrupted the prose. |
| 22 | Re-verify stale skill `Last verified:` stamps | OPEN (partly done) | 2026-08-26: `unifideck-ci-gates` re-derived against `.github/workflows/*.yml` and bumped (its content already tracked — an old stamp on current content is still a false signal, audit C-4); `unifideck-drift-guard` given the stamp it never had. **Still open:** `unifidb-pipeline.md` (the only genuinely stale one), `unifideck-dev-loop` ×2, `unifideck-bug-triage` ×2 (one has no stamp), `unifideck-release`, `CLAUDE.md`. The durable fix is a check that every skill carries a stamp — nothing enforces existence today. |
| 23 | Wire the launch-options parser | VALIDATING | DV-K4 is the one that matters. DV-K7/K8/K10/K11 are unsatisfiable — see 23a/23b. |
| 23a | Wire `state.game_args` | VALIDATING | Done 2026-08-26, **after fixing the precondition at its source**. `extractUserParams` preserved the user's `mangohud`/`gamemoderun` into the tail, so populating `game_args` would have handed them to the *game*. It now keeps only `KEY=value` assignments — a bare word after the game key was never a wrapper, because Steam applies wrappers pre-exec (§2.9, measured). With that and 23b, a bare token in the tail is honestly a game argument, which is what Steam delivers it as. 3 tests incl. the no-options regression guard. Needs DV-Q. |
| 23b | Delete `ParsedOptions.wrappers` / `RuntimeState.wrappers` | VALIDATING | Done 2026-08-26. Both fields deleted, 6 argv builders now start empty, and the parser **drops** tokens before a `%command%` instead of re-homing them into `game_args` — re-homing them would be the §2.9 hazard, which my first simplification reintroduced and the tests caught. 12 tests updated to assert the field's **absence** rather than its emptiness, so it cannot quietly return. Needs DV-Q. |
| 24 | Vulture cannot see an unimported module | VALIDATING | Done 2026-08-26. New **check 12** in `validate_architecture.py` (hard) + **8 dead modules deleted**: `launcher/diagnostics/{telemetry,save_folder_inspector}.py`, `launcher/proton/fixes/auth_args_stripper.py`, `launcher/signals.py`, `security/audit_decorators.py` (a duplicate definition of the live `audit_emitter.audit_auth_flow`), `services/cloud_save/{fs_ops,paths}.py`, `steam/steamgriddb/match.py`. Verified: a planted orphan fails check 12 and vulture at 80 stays silent on it. 10 tests. Two opt-outs, `# entry-point:` and `# unimported:`, deliberately distinct. |
| 24a | `_update_existing_shortcut` wiped launch options | CLOSED | Severity corrected on device: a settled library takes the reclaim path, so the wipe was real code on an unreached path. |
| 25 | Steam-exported env dropped by the container escape | OPEN | Low priority; the working route is documented and verified. |
| 27 | `vulture_whitelist.py` group comments false per-member | VALIDATING | Rewritten 2026-08-26 with per-name reasons. Every entry was tested **empirically** — delete the line, re-run vulture at confidence 60, see whether a report appears — rather than by reading. Result: **22 of 51 entries suppressed nothing even at 60** and were deleted; the surviving 29 each earn their place, and the suppressed set is byte-identical before and after. Two survivors are labelled as deletion candidates rather than dressed up as live. **The headline finding is new:** at the gate's own `min_confidence = 80` the whitelist suppresses **nothing at all** — 0 hits with it and 0 without — so the entire file is inert against the check CI runs. That is why it rotted, and it is item **24**'s blind spot from the other side. |
| 42 | Delete the dead root artifacts | **DECLINED — premise wrong** | Re-derived 2026-08-26: all six are **untracked and gitignored** (`build-plugin_old*.sh`, `main.py.backup` 244 KB, `.gitignore.backup`, `task.md`, root `test_ubisoft_launch.py`). Roadmap #8 asks to delete them as clutter that misleads contributors — but nothing reaches a contributor: they are not in the repo and never were. Deleting them changes the repo not at all, is **not recoverable from git**, and destroys what are plainly the maintainer's own local backups. That is absolute rule 2 (never delete user data; ask first). Nothing to do here; roadmap #8's part (c) should be struck. |

## Store behaviour and convergence

| ID | Title | State | Notes |
|---|---|---|---|
| 28 | Stall message reaches the user in English | OPEN | Needs one `errors.download.stalled` key × 16 manual translations. |
| 29 | Build the Battle.net `game_accounts` producer | OPEN | Every F2P and subscription title is invisible. **Measure DV-J4 before building.** |
| 30 | Stale-sweep invariant not machine-checked | VALIDATING | Done 2026-08-26 with the **nominal** form, not a check: `valid_stores` is a `NewType("SweepableStores", frozenset[str])` that only `_sweepable_stores` builds. Verified against a planted `reconcile(games, valid_stores=set(registry.store_ids()))` — the exact line that caused §3.5 finding B — which mypy now rejects. Also deleted a comment in `reconcile_phases.py` that still **recommended** the widening ("a caller can widen this to every registered store"). 2 guard tests. |
| 31 | `_ACHIEVEMENT_STORES` has an unlinked frontend twin | VALIDATING | Done 2026-08-26 with **26**. Four TS lists deleted — both copies of `CLOUD_SAVE_STORES` (`useCloudSaveStatus.ts` and `PlayMeta.tsx`, the second admitting in a comment that it mirrored the first), the inline `gog||epic` achievements condition, and `LANGUAGE_STORES`' gate half. New `useStoreCapability` / `storeHasCapability` read the payload and **fail closed**. `LANGUAGE_ROUTE` survives because it maps store→route, which the payload does not carry. |
| 32 | Ubisoft update path has no trigger; GOG DLC has no route | OPEN | Decide each as one unit: build the missing half or delete it. |
| 33 | No pre-install size or space guard for the wrapper stores | OPEN | A 90 GB vendor install can start with 1 GB free. |
| 45 | Progress phases exist for GOG only | VALIDATING | Resolved 2026-08-26, and the framing was half wrong. Epic/Amazon needed **nothing**: `worker.py` already stamps `download_phase="preparing"` centrally for every store, and the UI localizes from the phase alone. What was real was six **decorative** `phase_message` producers in GOG (`"Extracting…"`, `"Verifying… 12.3%"`) restating the localized label in hardcoded English — deleted. |
| **49** | **A measured wrapper-store wait explanation is computed and discarded** | OPEN | New, found while doing 45 — and the reason 45 was *not* a blanket delete. `battlenet/install_watch.status_message` reads the Agent's log and reports "queued behind the self-update", which is the known `battlenet-agent-one-operation-queued` failure the user otherwise sees as a permanent "Queued". It reaches the queue item as `phase_message` and **no frontend renders it** (`DownloadProgressRow.tsx` ignores the field on purpose because it is English). Wiring it is an i18n decision, same shape as **28**. |
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
| 35 | `inject_game_to_appinfo` wastes an RPC per overview read | VALIDATING — deleted 2026-08-26: the stub, its `rpcRoutes` row, and both round-trips. Kept the local `forceInjectMetadataForShortcut`, which does the real work, renamed the wrapper `reinjectMetadataWhenLoaded`, and gated the hot `GetAppOverviewByAppID` path on `patchedOverviews` so it no longer re-spoofs on every read. Persistence was redundant, not missing: `applyAppStorePatch` re-spoofs from the backend cache on every plugin load. |
| 36 | A `%command%`-leading `LaunchOptions` never launches, and sync preserves it | VALIDATING — fixed 2026-08-26 in `rewrite_for_sync`, the one path that can heal an already-broken shortcut. Dropping a `%command%` that nothing precedes is lossless: it is only meaningful as a separator, and `mangohud %command% gog:123` is untouched. 6 tests covering both the repaired and the must-not-touch forms. |
| 37 | Cloud-sync failures were silent | VALIDATING — **decided 2026-08-26: upload failures surface.** The module was fully written and unimported; the missing call was at `services/launcher/helpers.py:372`, a bare `logger.warning(... ignoring ...)`. A failed upload was **completely silent**: the user quit believing progress had reached the cloud. Two traps found before shipping it, both of which would have gone out with the wiring: the strings interpolate `{{error}}` while the payload sends `error_code` + `error_i18n_key`, so the message would have read *"…failed for gog ()."* — now resolved by a shared `buildToastParams`, which also de-duplicated the two renderers' param logic. `# unimported:` marker removed. |
| 38 | `set_bus_collaborators` has zero callers (check 4 misses sync methods) | CLOSED — deleted 2026-08-26; `pipeline_factory` already assigned those attributes directly. **Check 4 was NOT widened**: its docstring is right that a sync method is not RPC surface, so reporting one as a dead *RPC* would be a false claim. The blind spot is real but belongs to check 12 / vulture, not to the RPC arm. |
| 39 | `ROW_CONFIG` waits for status strings no backend emits | VALIDATING — deleted 2026-08-26, and it was worse than recorded. It could **never** fire: `StoreStatus` is a closed union of `connected \| disconnected \| expired \| error`, so `status === "legendary_not_installed"` compared against a value the type cannot hold. It also covered 2 of the 3 CLI stores — GOG gained a `CLITool` in the §3.2 pass and never got a row. Removed with its two locale keys; the capability is refiled as **50**. |
| **50** | **No store tells the user which bundled CLI is missing** | OPEN | Opened by 39. A lost exec bit is a real failure mode (`scripts/ensure_executable_bits.py` exists for it), and since §3.5 a missing `gogdl` makes GOG unavailable — which the stale-sweep fix now makes safe but still silent. Needs a real reason on the `check_store_status` payload for **all three** CLI stores, not a frontend-only map. |
| 40 | `assert_all_keys_resolve` has zero callers; CI comments describe it as the boot check | VALIDATING — fixed 2026-08-26. Deleted the strict variant and `KeyPresenceError` (44 lines, zero callers, docstring claiming it ran at boot and was fatal). `collect_missing_keys` **is** the boot check and deliberately warns into degraded mode rather than aborting. Corrected **five** false statements: its own docstring, `collect_missing_keys`' docstring, three in `check_config_keys.py`, one in `quality.yml`. |
| 41 | Two dead defensive fallbacks on `POST_SYNC_PHASE_CHANGED` | CLOSED — deleted 2026-08-26. All four emitters send `sync_kwargs` or omit it; no emitter has ever sent a flat `games`/`is_force`. `TOLERATED_SUBSCRIBER_READS` is back to empty, which is the goal — an exemption is a place for a defect to hide. |
| 46 | Circuit breaker never resets on success | VALIDATING — see the P0 table above; needs DV-L1 |
| 47 | `SHARED_HELPERS` is name-exact, so a renamed copy escapes check 11 | VALIDATING | Closed 2026-08-26 with **check 13**, matching on body *shape* — identifiers and literals erased, structure and attribute names kept — so a rename cannot hide a copy. Verified against a planted `_appid_key_candidates`, the exact historical escape. **A name-variant matcher was tried first and rejected on measurement**: it fired on seven unrelated `_write_marker*` functions with different signatures, the `fix_pfx_symlink` trap of §3.3, and a gate that reds untouched code gets switched off. Body-shape found **16 real groups** over 2357 functions, grandfathered shrink-only in `duplicate_bodies_baseline.json` — including the `epic/sessions.py` ↔ `epic/achievements.py` mirroring the convergence map flagged, and a genuine twin pair (`winetricks._write_marker` ↔ `epic_prerequisites._write_marker_sync`). 7 tests. |

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
