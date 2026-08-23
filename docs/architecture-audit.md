# Architecture Audit — Drift, Divergence, and Redundancy

> **Audited:** 2026-08-24 · **Against:** v0.7.5 working tree (package 0.7.4) · **Status:** living register — tick items off as they are resolved; do not archive until the register is empty.

This is the detailed record of a three-lens adversarial review: (1) a general correctness/dead-code pass, (2) intended-design vs current-state drift, and (3) store-logic drift and redundancy. It is the source material for the remediation register at the end. The companion guard is the `unifideck-drift-guard` skill plus `scripts/validate_architecture.py`, which machine-enforce the drift classes found here.

Two facts frame every section:

1. **The code is ahead of its documentation by a full store and roughly a full release.** Battle.net is implemented but every doc and skill still says "five stores." Version strings disagree (§2.6).
2. **There is no single agreed layer model or store-type model.** Four incompatible layer maps exist, and the wrapper/CLI distinction is maintained in two separate hand-written tables with no linking field.

---

## Part 1 — General adversarial review

### 1.1 P0 correctness bugs (silent failures)

1. ~~**`GAME_INSTALLED` payload contract mismatch.**~~ **RESOLVED — and the original diagnosis was wrong.** The finding claimed the emitter at `core/manifest.py:463-470` sent `game_id` while both subscribers read `app_id`, killing artwork-on-install and Proton-on-install "despite the event firing". Validation showed the event **never fired at all**, and that fixing the payload would have changed no behaviour:

   - The only emit site was `_scan_one_root` inside `discover_all`, whose two wrappers (`discover_installed_games`, `discover_and_log`) had zero callers — their only references were `vulture_whitelist.py` entries. The dead code had already been noticed and silenced rather than deleted.
   - Artwork-on-install was **redundant, not missing**: a game's shortcut and its cover art are created at *sync* time, and installing only flips that shortcut's install tag while preserving its appid (`services/shortcut/events.py:163-178`). `download/worker.py` documents the same reasoning where it declines to emit.
   - Proton-on-install had **four** independent reasons it could never work: no live emitter; the payload key mismatch; `DEFAULT_TOOLS` empty for all six stores by design; and in the plugin the writer was pointed at `localconfig.vdf` (`bootstrap/paths.py:166`, re-bound by `steam/current_user.py`) while `CompatToolMapping` lives in `config/config.vdf`.
   - **The real user-facing bug was on the frontend and this audit missed it.** `src/lib/steam-bridge/collection-manager.ts` subscribed to `GAME_INSTALLED` to rebuild the `[Unifideck] Installed` collection. That never fired, while `GAME_UNINSTALLED` on the next line did — so the collection (and any TabMaster tab on it) dropped games on uninstall but never picked them up on install until the next full sync. Its own comment claimed to have fixed exactly that.
   - Both guards locked in **opposite halves** of the mismatch and so caught nothing: `tests/unit/test_proton_ge.py` asserted the subscriber's `app_id` contract while `scripts/validate_event_schemas.py` asserted the emitter's `game_id` contract.

   Fix: repointed the collection manager at `SHORTCUT_INSTALL_STATE_CHANGED` (the event that actually fires, in both directions), then deleted the phantom event and everything hanging off it — both dead subscribers, the dead discovery half of `core/manifest.py` (520→257 lines), the entire ProtonService compat-tool path (243→120 lines, resolving half of §1.4), and the two `vulture_whitelist.py` entries. `Events.GAME_INSTALLED` no longer exists, so nothing can subscribe to it again.

   **Lesson for the rest of this register:** "emitted but with the wrong payload" and "not emitted at all" look identical from a grep of emit sites. Check that the *enclosing function* has callers before trusting an emit site, and check whether a dead subscriber's job is already done elsewhere before restoring it.

2. **`TOAST_NOTIFICATION` is emitted but consumed nowhere.** Emitted at `services/launcher/circuit_breaker.py:59`, `services/launcher/error_toasts.py:48`, and `services/shortcut/service.py:272`. No Python subscriber, and it is absent from `src/types/events.ts` and `WATCHED_EVENTS`. Launcher error and circuit-breaker toasts never reach the UI. The working channel is `LAUNCHER_STAGE` via `launcher/frontend_bridge.py`; these two emit the dead channel instead. Its payload also uses `params=`, while the frontend contract reads `i18n_params`.

3. **`MetricsCollector` timers/gauges are never wired.** In `core/metrics_collector.py:_subscribe_all` (lines 87-104), `auto_wire(self, self._bus)` and the `logger.info(...)` sit inside the `for event, name in counter_events:` loop, so they run 7 times. The timer/gauge `_on_*` handlers carry no `@subscribe` metadata, so `auto_wire` wires nothing for them. Result: `_timers`/`_gauges` stay empty forever and `get_plugin_metrics()` returns permanently-empty metrics.

4. **Double emission of `DOWNLOAD_*` with incompatible payloads.** For Epic/Amazon each phase emits two events: the `DownloadWorker` shape (`item=`/`game=` objects, `download/worker.py:234,336,490`) and the store shape (`store=, game_id=` top-level, `epic/install.py:184,425,468`). The frontend `src/stores/download-store.ts` parses only the worker shape, so store-emitted terminal events yield `null` ids and the game-info refresh silently no-ops.

### 1.2 Dead RPC methods (implemented, zero frontend callers)

Cross-referenced `rpc/mixins/*.py` against `src/api/rpc-routes.ts` and call sites. Roughly 13 implemented methods have no caller. Largest clusters:

- `ObservabilityRPCMixin`: `get_bus_health` (`observability.py:57`), `get_plugin_metrics` (`:46`), `get_feature_flags` (`:141`).
- `PlaytimeRPCMixin`: `get_all_playtimes` (`playtime.py:32`), `sync_playtime_now` (`:36`).
- `CloudFailureRPCMixin`: `set_cloud_failure_behavior` (`cloud_failure.py:59`), `get_cloud_failure_behaviors` (`:40`).
- Singles: `is_edge_installed` (`edge.py:43`), `save_proton_setting` (`auth_shortcuts.py:142`), `get_sync_status` (`sync.py:83`), `check_game_update` (`download.py:267`), `get_game_metadata` (`ui.py:84`; its sibling `get_game_metadata_display` is the one used), `inject_hide_css` (`ui.py:139`), `get_release_notes` (`updater.py:85`).

`scripts/validate_architecture.py` reports a broader, more conservative list (methods with zero occurrences in `src/` text): `arm_circuit_bypass`, `clear_launch_failures`, `clear_security_audit_log`, `export_launch_logs`, `get_config_validation_status`, `get_launch_failures`, `get_launch_logs`, `get_probe_history`, `get_security_audit_log`, `get_security_bruteforce_status`, `get_security_counters`, `list_save_folder`, `release_quarantine`, `report_runtime_probes`, `reset_security_bruteforce`. These are mostly observability/security/launch-diagnostic surfaces.

### 1.3 Event-bus mismatches

**Subscribed but never emitted (dead handlers):**

- `SUSPEND`/`RESUME`: subscribed by `services/playtime/service.py:274,286`, emitted nowhere. Playtime suspend/resume accounting never runs.
- `ARTWORK_REQUEST`: subscribed `services/artwork/event_handlers.py:141`, never emitted.
- `SHORTCUT_CREATED`: subscribed `services/artwork/event_handlers.py:163`, never emitted. The auth-shortcut-artwork feature is dead.

**Emitted but never consumed:**

- `TOAST_NOTIFICATION` (see 1.1.2).
- `STORE_REGISTERED`: emitted `stores/shared/store_registry.py:47`, no consumer (the docstring claims `metrics_collector` consumes it; it does not).
- `STORE_ERROR`: subscribed by the frontend `boot-event-listener.tsx:117`, never emitted backend-side. The frontend `store_error` toast can never fire. Do not confuse with the `StoreError` *exception* in `store_base.py:17`, an unrelated RPC-envelope type.
- `PLAYTIME_SYNC_COMPLETE`: emitted `services/playtime_sync/service.py:198`, no toast-bridge subscriber.
- `SUBSCRIPTION_DETECTED`/`SUBSCRIPTION_EXPIRED`/`SUBSCRIPTION_CHECK_FAILED`: emitted in `microsoft_subscription/`, no consumer.

### 1.4 Redundancy outside stores

- ~~**Two `config.vdf` CompatToolMapping injectors**~~ **RESOLVED (item #1).** `services/proton_service.py`'s `_inject_compat_tool` (weaker regex, unreachable) was deleted along with the rest of that service's compat-tool path. `compatibility/proton_helpers.py:65` (`ProtonToolsManager`) is now the only writer.
- **`resolve_proton_path` name collision**: `compatibility/proton_helpers.py:330` is a "legacy passthrough" that returns its input; `launcher/proton/infrastructure/selector.py:158` is the real `str -> Path`. Two public functions, same name, incompatible semantics.
- **Duplicated encrypted-token persistence**: `stores/gog/tokens/storage.py` (~272 lines) and `stores/microsoft/tokens/persistence.py` (~251 lines) both implement `SecureTokenStore`-backed load/persist/clear with legacy-plaintext migration. A third store (EA App is anticipated in `wrapper_signals.py`) would be a third copy.
- **Duplicated `find_umu_run`**: `stores/shared/wine_env.py:52` and `stores/ubisoft/binaries.py:72`.
- **Three appid-to-u32 conversions**: `core/compat_bridge.py:61`, `services/shortcut/orphan_scan.py:54`, and inline in `services/shortcut/events.py:22`.
- **Security package split with a circular import**: `security/ephemeral_creds.py` (440 lines) and `security/ephemeral_creds_inplace.py` (310 lines) import each other to "break a cycle". Also `device_fingerprint.py` vs `device_identity.py` overlap.
- **Write-only install manifest** *(new, found while resolving item #1)*: `core/manifest.py`'s `write_manifest` is called by `epic/install.py` and `amazon/amazon_install.py` at the end of a successful install, but its only reader was `read_manifest`, consumed solely by the dead `discover_all` pass. With that pass deleted, `.unifideck_manifest.json` is written and never read anywhere in the tree. This may be deliberate (support bundles, external tooling, forward compat), so it was left in place — but either give it a reader or drop the write.
- **`steam/current_user.localconfig_path` has no production caller** *(new, minor, found while resolving item #1)*: item #1 removed its last one (the ProtonService re-bind). Kept deliberately — unlike the phantom emitter it is a correct, exported, unit-tested path helper symmetric with `shortcuts_path` / `grid_dir` in a module whose job is per-user Steam paths, and vulture accepts it via `__all__`. Noted so it is not mistaken for live wiring.
- **Frontend event names maintained in three places**: backend `core/types/events.py`, frontend `src/types/events.ts`, and `src/api/event-bus-client.ts:36-77` (`WATCHED_EVENTS`). An omission (not a typo) slips through, and already has (`LIBRARY_SYNC_*` are deliberately absent from `WATCHED_EVENTS`).

---

## Part 2 — Intended design vs current state

### 2.1 Mixin count: four contradictory numbers

| Where | Claims | Actual |
|---|---|---|
| `main.py:17` docstring | "eleven mixins" | 20 |
| `rpc/mixins/__init__.py` `__all__` | 13 | 20 (missing Account, Achievements, AuthShortcuts, Edge, Executable, LibraryFacets, Storage) |
| `docs/architecture.md:127` | 18 | 20 |
| `SKILL.md:19` / `backend.md:15` | 20 | correct |

`main.py` composes 20 mixins. Two more (`CleanupRPCMixin`, `_CleanupFinalizeMixin`) ride in transitively through `SyncRPCMixin`'s inheritance and are counted nowhere.

### 2.2 Four incompatible layer maps

No single agreed layer model exists:

1. `py_modules/unifideck/__init__.py` — "5 layers", no RPC layer, L3 named `stores/store_base` (the file is actually `stores/shared/store_base.py`).
2. `docs/architecture.md:39-128` — titled "5-Layer" but draws **six** (L6 RPC → L1 Types).
3. `main.py:20-24` — says "five-layer" but lists **six**, with L3 = "event bus/cache/config" and L1 = "paths/I/O".
4. `CLAUDE.md:17` — non-numbered: `rpc/ (leaf) → services/ → stores/ + core/ + event_bus/`.

Direct contradictions: "five" vs six enumerated layers; Layer 1 is `core/types` vs `paths/I/O`; Layer 3 is `store_base` vs `stores/shared` vs `event_bus/cache/config`.

### 2.3 StoreBase contract is documented wrong

`docs/architecture.md:90-91` says StoreBase "defines the five abstract methods … `get_library()`, `install()`, `uninstall()`, `launch()`, `get_updates()`." The real `store_base.py:51-97` defines **10** abstract methods (`is_available`, `start_auth`, `complete_auth`, `logout`, `get_library`, `install_game`, `uninstall_game`, `update_game`, `check_for_updates`, `get_game_size`) and has **no `launch()`** (launch lives in `launcher/dispatcher.py`, not the store contract). None of the four documented method names matches reality.

### 2.4 Battle.net is a sixth store the docs deny

`docs/architecture.md` ("five store connectors"), `stores.md`, `launcher.md`, `CLAUDE.md`, and multiple in-code "five stores" comments all describe a five-store system. The code has six: `stores/battlenet/` is a full connector (store, library, install, agent_status, id_map, ownership, product_db, prefix), plus 8 `launcher/proton/handlers/battlenet*.py` files, and `bootstrap/cache_registry.py:18` already says "Six stores". The only Battle.net doc is `docs/feasibility/battlenet.md`, still framed as a feasibility study of an unimplemented store.

### 2.5 Undocumented subpackages and self-contradictions

- **`accounts/` is absent from every doc and skill** but fully implemented (`account_manager.py`, `AccountRPCMixin`).
- **`accounts/__init__.py` contradicts `accounts/account.py`**: the `__init__` docstring says `check_account_switch`/`migrate_account_data` "were never carried over"; `account.py` says it "Restores" them. They exist.
- **`services/` table is ~50% of reality**: `architecture.md` lists 13 service packages; `services/bootstrap/service_defs.py` registers 21 plus `LauncherService`. Missing from docs: `compatibility`, `activity_log`, `feature_flags`, `probe_reaction`, `launch_logs`, `support_bundle`, `achievements`, `playtime_sync`, `metrics`.
- **`core/` has ~30 modules vs ~11 documented**; notably six `sync_*_mixin.py` modules moved RPC-mixin logic *into* `core/`, blurring the documented "rpc is thin" boundary.
- **`event_bus/` has five undocumented modules** (`event_bus_devex`, `event_bus_extensions`, `event_bus_reliability`, `event_bus_scaling`, `event_priority`); `event_priority.py` vs the documented `priority_dispatcher.py` suggests two priority mechanisms.

### 2.6 Version drift

- `py_modules/unifideck/__init__.py:22` = `0.7.1`.
- `docs/architecture.md` and `CLAUDE.md` = `v0.7.0`.
- `package.json` and `plugin.json` = `0.7.4`.
- Current branch = `0.7.5`.
- Every skill file says "Last verified 2026-07-02 against v0.7.0" and has not been re-verified against the current tree.

### 2.7 Machine enforcement is narrower than claimed

`docs/architecture.md:41-42` claims the stack is "enforced by `.importlinter`." The `.importlinter` file itself admits "The full 5-layer stack doesn't cleanly map to the current tree" and enforces only two invariants (`rpc-is-leaf`, `types-is-leaf`), which §9 of the same doc correctly states. §3 and §9 of `architecture.md` disagree with each other.

### 2.8 Dead code / phantom design vocabulary

- `launcher/types/options.py:71` `parse_launch_options` — dead, imported nowhere (correctly flagged in `launcher.md`).
- `rpc/mixins/__init__.py`, `store.py`, and `auto_wire.py` docstrings describe a "handler group" / `composer.bind_handlers` / `handlers/` design that does not exist. `handlers/` has no directory under `rpc/`. The guidance "add new RPC methods to a handler group" points at a structure that was never built. (Fixed in `mixins/__init__.py` as part of this audit; `store.py` and `auto_wire.py` remain.)
- `OP-24c` / `OP-25g` / `OP-26k` plan-reference markers threaded through mixin docstrings reference an operational plan numbering absent from living docs.
- `store.py:182` `inject_game_to_appinfo` is an explicit no-op stub returning `success=True`.
- `cleanup_sweeps.py` in `rpc/mixins/` defines no mixin; it is filesystem sweep I/O sitting in the "thin adapter" RPC leaf.
- `architecture.md:129-148` mixin method table is ~half wrong: `get_library`, `sync_library`, `launch_game`, `kill_game`, `get_store_status`, `rotate_device_key`, `get_downloads`, `get_play_sessions`, `get_ui_state`, `set_locale`, `get_cloud_failures`, `retry_cloud_sync` do not exist as RPC methods.

---

## Part 3 — Store logic drift and redundancy

### 3.1 The wrapper/CLI distinction is two hand-maintained tables with no link

- Canonical wrapper identity is a string frozenset in `launcher/wrapper_stores.py:37`: `WRAPPER_STORES = {"ubisoft", "battlenet"}` with predicates `is_wrapper_store`, `prefix_owns_game_install`, `skips_generic_compat`, `uses_manual_download_phase`.
- Each store's `store_info` separately declares `uses_wine: bool` (ubisoft `store.py:65`, battlenet `store.py:70` = `True`; the other four = `False`). There is **no field linking** the two. Today `uses_wine` happens to correlate 1:1 with `WRAPPER_STORES`, but nothing enforces it, and a future wrapper store (EA App) could set one and not the other.

The predicates were deliberately separated ("EA App will be a wrapper store that does not own its installs"), which is sound reasoning, but the identity source-of-truth is still split across `launcher/` and six `store_info` descriptors. `scripts/validate_architecture.py` now machine-checks the `uses_wine ↔ WRAPPER_STORES` agreement.

### 3.2 CLI-store drift (Epic = reference, GOG diverges, Amazon partial)

`shared/cli_install_helpers.py` exists to unify CLI stores but is consumed by only 2 of 3.

- **Binary resolution 2-of-3 break**: Epic and Amazon declare a `CLITool` descriptor and resolve via `StoreBase._find_binary` → `binary_resolver`. GOG hardcodes `bin/gogdl` in `_resolve_gogdl_bin` (`gog/store.py:476-494`), bypassing the resolver, its version check, and its multi-path search.
- **Subprocess/output 2-of-3 break**: Epic and Amazon use `drain_install_output`/`TailRingBuffer`/`wait_with_timeout`. GOG reimplements its own `_read_progress_loop`, two-phase stall watchdog, and `_terminate_gogdl` in `gog/install/progress.py`.
- **Three ETA parsers, three speed parsers, near-verbatim copies**: `shared/cli_install_helpers.py:196/219` (Epic only), `gog/install/progress.py:275/296`, `amazon/amazon_progress.py:23/44`. `amazon_progress.py`'s own docstring admits it was "kept store-local rather than folded into shared" because the shared versions are "close but not byte-identical."
- **Cancellation**: only Epic uses shared `terminate_process_tree`. Amazon re-raises without killing the tree; GOG uses its own `terminate(); sleep(1); kill()`.
- **`StoreBase._run_cli` is dead code** (`store_base.py:161-211`): defined, never called. Every CLI store inlines `asyncio.create_subprocess_exec` instead.
- **Auth/token idioms diverge**: Epic/Amazon share near-identical `_check_*_authenticated` `user.json` readers; GOG and Microsoft instead have full `tokens/` manager subpackages (structurally parallel but not in `shared/`).

### 3.3 Wrapper-store drift (Ubisoft mature, Battle.net consumes shared, half-migrated)

What **is** genuinely shared (both stores use it): `shared/wrapper_install` (`watch_manual_install` + `InstallProbe`), `shared/prefix_placement`, `shared/wrapper_auth_monitor`, `shared/installed_size.dir_size_bytes`, `shared/wine_path`.

What is **not** shared, where Ubisoft keeps a private duplicate of what Battle.net gets from `shared/`:

- **Prefix cloning**: Battle.net uses `shared/prefix_clone`; Ubisoft reimplements `rsync_clone`, `fix_pfx_symlink`, `write_bootstrap_marker` in `ubisoft/prefix/helpers.py:275,319,347`. `prefix_clone.py`'s header says "moved here from stores/ubisoft/prefix/helpers.py", but the move was one-way: the originals remain and now drift.
- **Session capture/purge**: Battle.net inherits `WrapperSessionHooks` (`_capture_wrapper_session_on_stop`); Ubisoft reimplements `_capture_upc_session_on_stop` (`ubisoft/store.py:107-145`) over its own `session/facade.py`.
- **Auth shortcut**: Battle.net uses `shared/auth_shortcut`; Ubisoft keeps its own richer `auth/shortcut.py` + `shortcut_ops.py` (~430 lines). `shared/auth_shortcut.py:25-28` admits this: "Ubisoft keeps its own richer implementation for now."
- **Prefix forensics and `wine_env`**: only Battle.net consumes `shared/prefix_forensics` and `shared/wine_env` (which itself delegates to `UbisoftBinaryResolver`).

One shared docstring overstates reality: `shared/install_base.py:14-16` claims Battle.net is the "second consumer" of `detect_sdcard_install_base`, but grep shows only `ubisoft/config.py:37` imports it.

### 3.4 Cross-store copy-paste redundancies

- **`merge_install_status`**: 3 near-identical copies (`epic/library.py:159`, `gog/library.py:465`, `amazon/amazon_library.py:214`).
- **`_rebuild_auth_after_injection`**: 5 copies (4 browser-auth stores + a same-name-different-body Ubisoft variant).
- **`_check_*_authenticated`**: 2 near-identical `user.json` readers (`epic/store.py:197`, `amazon/amazon_store.py:164`).
- The prefix-clone/pfx-symlink/marker trio (§3.3) — 2 copies each.
- **`dir_size_bytes` duplicated into services**: `shared/installed_size.py:21` vs `services/shortcut/compatdata_scan.py:185`.

### 3.5 Partial-implementation flags

- **microsoft** (xCloud) is correctly stub-shaped for a subscription store, but its `install_game`/`uninstall_game`/`update_game` return `success=True` no-ops (`microsoft_store.py:383-424`) rather than an explicit `not_supported`.
- **battlenet** lacks (relative to Ubisoft): pre-install `get_game_size` (relies on `product.db` populated only at completion), `check_for_updates` (intentional, client self-updates), web-library fallback, achievements, playtime, DLC.
- **ubisoft** lacks (relative to Epic/GOG): `check_for_updates` (`[]`), `get_game_size` (`None`), achievements, playtime.
- **amazon** lacks DLC, achievements, playtime.

---

## Part 4 — Remediation register

Ordered by risk-to-value. Tick the box when a fix lands and the user has validated it.

### P0 — silent correctness bugs (fix first; make dead paths actually run)

- [x] 1. ~~Fix the `GAME_INSTALLED` payload~~ → **the event had no live emitter at all; retired it entirely.** Repointed `collection-manager.ts` at `SHORTCUT_INSTALL_STATE_CHANGED` (fixing a real user-facing bug this audit missed: the `[Unifideck] Installed` collection never picked up installs), deleted both dead subscribers, the dead discovery half of `core/manifest.py`, the whole ProtonService compat-tool path, and 2 vulture allowlist entries. See the rewritten §1.1.1. *(awaiting user device validation)*
- [ ] 2. Wire `MetricsCollector` timers/gauges: move `auto_wire`/`logger.info` out of the counter loop, add `@subscribe` to the `_on_*` handlers.
- [ ] 3. Resolve `TOAST_NOTIFICATION`: add a real consumer or route the two emitters through `LAUNCHER_STAGE`/`frontend_bridge`; align `params` vs `i18n_params`.
- [ ] 4. Make `DOWNLOAD_*` single-emitter: pick the worker shape, stop store installers emitting terminal events.

### P1 — consolidation (reduces drift, medium risk, needs per-store testing)

- [ ] 5. Promote `merge_install_status` and `_rebuild_auth_after_injection` into `shared/` as base-class hooks; delete the 3 and 5 copies.
- [ ] 6. Unify the three ETA parsers and three speed parsers into `shared/cli_install_helpers.py`; make GOG consume the shared helpers (and route `_resolve_gogdl_bin` through `_find_binary`).
- [ ] 7. Link the two wrapper/CLI tables: derive the wrapper predicates from a single `store_info` field so one cannot drift.
- [ ] 8. Migrate Ubisoft onto `shared/prefix_clone`, `shared/wrapper_session_hooks`, and `shared/auth_shortcut`; delete the private duplicates; fix the `install_base.py` "second consumer" docstring.
- [ ] 9. Extract the duplicated token persistence (`gog/tokens/storage.py` + `microsoft/tokens/persistence.py`) into one `shared/` primitive.
- [ ] 10. Delete `StoreBase._run_cli` (dead) or make the CLI stores actually use it.
- [ ] 11. Make microsoft's install/uninstall/update stubs return an explicit `not_supported` instead of `success=True`.
- [ ] 12. Resolve the `resolve_proton_path` name collision and the security-package circular-import split. *(the two-`config.vdf`-injector half of §1.4 is already resolved: item #1 deleted `proton_service.py`'s `_inject_compat_tool`, leaving `ProtonToolsManager` in `compatibility/proton_helpers.py` as the sole writer. The name collision and the security split remain.)*

### P2 — documentation re-sync (zero code risk)

- [x] 13. Standardize on one layer model; delete the "5-layer"/"six-layer" prose counts in `docs/architecture.md` (diagram is authoritative). *(done this audit)*
- [x] 14. Correct the mixin count and complete `rpc/mixins/__init__.py.__all__` to all 20. *(done this audit)*
- [ ] 15. Update every "five stores" reference to six; re-frame `docs/feasibility/battlenet.md` as implemented. *(docs/architecture.md, skill, and in-code comments done this audit; `docs/feasibility/battlenet.md` still framed as feasibility)*
- [x] 16. Correct the StoreBase contract in `architecture.md` (10 methods, no `launch()`). *(done this audit)*
- [ ] 17. Remove the phantom "handler groups" docstrings and `OP-XX` markers; document the five undocumented `event_bus/` and `core/sync_*_mixin` modules; add `accounts/` to the layer map. *(mixins/__init__.py docstring + accounts/ done this audit; `store.py`/`auto_wire.py` docstrings + event_bus/core module docs remain)*
- [x] 18. Re-verify the `unifideck-architecture` skill against the current tree and bump its "Last verified" line. *(done this audit)* Remaining version-string reconciliation (`__init__.py.__version__` 0.7.1 vs `package.json` 0.7.4) is deferred to the next release (see `unifideck-release` skill).
