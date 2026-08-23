"""Regression: the metrics collector's timers and gauges were never wired.

``MetricsCollector._subscribe_all`` called ``auto_wire`` *inside* its
counter loop, and none of the ``_on_*`` handlers carried ``@subscribe``
metadata. Measured against a real bus before the fix: ``auto_wire``
returned 0, seven identical "wired" lines hit the log per plugin start
(confirmed on-device: ``grep -c`` on the live log gave 7), and
``get_plugin_metrics()`` returned ``timers_ms: {}`` / ``gauges: {}``
forever. ``sync_started``, ``sync_complete`` and ``download_started``
had no subscriber at all.

Two payload facts these tests pin down, because the handlers only became
reachable with the fix:

* ``DOWNLOAD_*`` is emitted in two shapes — ``DownloadWorker`` sends
  ``item=<dict>`` (the only shape GOG produces), the store installers
  send ``store=``/``game_id=`` at the top level. Both must resolve to
  one key, or every worker-shaped download shares ``"dl::"``.
* Failure events must drop the pending entry. Download keys carry a game
  id, so without that every cancelled install leaks one entry for the
  lifetime of the plugin process.
"""
from __future__ import annotations

from typing import Any

from unifideck.core.metrics_collector import MetricsCollector
from unifideck.core.types import Events
from unifideck.event_bus.event_bus import EventBus


def _collector() -> tuple[EventBus, MetricsCollector]:
    """A collector wired to its own fresh bus."""
    bus = EventBus()
    return bus, MetricsCollector(bus)


def _handler_counts(bus: EventBus) -> dict[str, int]:
    """Subscriber count per event key."""
    return {key: len(handlers) for key, handlers in bus._handlers.items()}


# ── V1: wiring happens exactly once ───────────────────────────────
async def test_every_handler_is_wired_exactly_once() -> None:
    """The guard for the original bug.

    Put ``auto_wire`` back inside the counter loop and every count
    below multiplies by seven.
    """
    bus, _collector_unused = _collector()
    assert _handler_counts(bus) == {
        # counter lambda + decorated handler
        "store_auth_started": 2,
        "store_auth_complete": 2,
        "store_auth_failed": 2,
        "sync_failed": 2,
        "download_complete": 2,
        "download_failed": 2,
        # decorated handlers only — no counter declared
        "sync_started": 1,
        "download_started": 1,
        # two decorated handlers: timer + gauges
        "sync_complete": 2,
        # counter only
        "download_queued": 1,
    }


async def test_each_counter_event_counts_once_per_emit() -> None:
    """V9 — double-wiring would show up here as inflated counters."""
    bus, metrics = _collector()
    await bus.emit(Events.DOWNLOAD_QUEUED, store="gog", game_id="g1")
    await bus.emit(Events.SYNC_FAILED, error="boom")
    counters = metrics.get_plugin_metrics()["counters"]
    assert counters["download_queued"] == 1
    assert counters["sync_failures"] == 1


# ── V2/V3: the pair timers and the sync gauges ────────────────────
async def test_auth_pair_records_a_duration() -> None:
    bus, metrics = _collector()
    await bus.emit(Events.STORE_AUTH_STARTED, store="epic")
    await bus.emit(Events.STORE_AUTH_COMPLETE, store="epic")
    snapshot = metrics.get_plugin_metrics()
    assert snapshot["counters"]["auth_attempts"] == 1
    assert snapshot["counters"]["auth_successes"] == 1
    assert snapshot["timers_ms"]["auth_duration_ms"] > 0
    assert metrics._pending_timers == {}


async def test_sync_pair_records_a_duration_and_both_gauges() -> None:
    """Payloads copied from the real emitters (``core/sync_run_mixin``)."""
    bus, metrics = _collector()
    await bus.emit(
        Events.SYNC_STARTED, stores=["epic"], scope="all", registered_phases=[],
    )
    await bus.emit(
        Events.SYNC_COMPLETE,
        games=[{"id": 1}, {"id": 2}, {"id": 3}],
        stores_synced=["epic"],
        errors={},
        duration_ms=5,
    )
    snapshot = metrics.get_plugin_metrics()
    assert snapshot["timers_ms"]["sync_duration_ms"] > 0
    assert snapshot["gauges"] == {
        "sync_games_total": 3.0,
        "sync_stores_count": 1.0,
    }


async def test_concurrent_auth_flows_do_not_share_a_timer() -> None:
    """Interleaved store logins each keep their own pending entry."""
    bus, metrics = _collector()
    await bus.emit(Events.STORE_AUTH_STARTED, store="epic")
    await bus.emit(Events.STORE_AUTH_STARTED, store="gog")
    assert sorted(metrics._pending_timers) == ["auth:epic", "auth:gog"]
    await bus.emit(Events.STORE_AUTH_COMPLETE, store="epic")
    await bus.emit(Events.STORE_AUTH_COMPLETE, store="gog")
    assert metrics._pending_timers == {}


# ── V4/V5/V6: both download payload shapes ────────────────────────
async def test_store_shaped_download_pair_records_a_duration() -> None:
    bus, metrics = _collector()
    await bus.emit(Events.DOWNLOAD_STARTED, store="epic", game_id="g1")
    await bus.emit(
        Events.DOWNLOAD_COMPLETE, store="epic", game_id="g1", install_path="/x",
    )
    assert metrics.get_plugin_metrics()["timers_ms"]["download_duration_ms"] > 0
    assert metrics._pending_timers == {}


async def test_worker_shaped_download_pair_records_a_duration() -> None:
    """The ids live inside ``item`` — the only shape GOG emits."""
    bus, metrics = _collector()
    item = {"store": "gog", "game_id": "g1", "title": "A Game"}
    await bus.emit(Events.DOWNLOAD_STARTED, item=item)
    await bus.emit(Events.DOWNLOAD_COMPLETE, item=item, game={})
    assert metrics.get_plugin_metrics()["timers_ms"]["download_duration_ms"] > 0
    assert metrics._pending_timers == {}


async def test_concurrent_worker_downloads_do_not_share_a_key() -> None:
    """Pre-fix both of these collapsed onto ``"dl::"``."""
    bus, metrics = _collector()
    first = {"store": "gog", "game_id": "g1"}
    second = {"store": "gog", "game_id": "g2"}
    await bus.emit(Events.DOWNLOAD_STARTED, item=first)
    await bus.emit(Events.DOWNLOAD_STARTED, item=second)
    assert sorted(metrics._pending_timers) == ["dl:gog:g1", "dl:gog:g2"]
    await bus.emit(Events.DOWNLOAD_COMPLETE, item=first, game={})
    await bus.emit(Events.DOWNLOAD_COMPLETE, item=second, game={})
    assert metrics._pending_timers == {}


# ── V8: the double emission Epic and Amazon produce ───────────────
async def test_double_emitted_download_measures_once() -> None:
    """Both shapes fire for Epic/Amazon; the timer must not double-write.

    The duplicate ``download_completed`` count asserted here is not this
    module's bug — it is the double ``DOWNLOAD_*`` emission tracked as
    audit item #4. Pinned so a future single-emitter fix trips this test
    deliberately instead of silently.
    """
    bus, metrics = _collector()
    item = {"store": "epic", "game_id": "g1"}
    await bus.emit(Events.DOWNLOAD_STARTED, item=item)
    await bus.emit(Events.DOWNLOAD_STARTED, store="epic", game_id="g1")
    await bus.emit(
        Events.DOWNLOAD_COMPLETE, store="epic", game_id="g1", install_path="/x",
    )
    await bus.emit(Events.DOWNLOAD_COMPLETE, item=item, game={})
    snapshot = metrics.get_plugin_metrics()
    assert snapshot["timers_ms"]["download_duration_ms"] > 0
    assert snapshot["counters"]["download_completed"] == 2
    assert metrics._pending_timers == {}


# ── V7: failures clear the pending entry ──────────────────────────
async def test_failed_auth_drops_the_pending_timer() -> None:
    bus, metrics = _collector()
    await bus.emit(Events.STORE_AUTH_STARTED, store="epic")
    await bus.emit(Events.STORE_AUTH_FAILED, store="epic", error="denied")
    snapshot = metrics.get_plugin_metrics()
    assert snapshot["counters"]["auth_failures"] == 1
    assert "auth_duration_ms" not in snapshot["timers_ms"]
    assert metrics._pending_timers == {}


async def test_failed_sync_drops_the_pending_timer() -> None:
    bus, metrics = _collector()
    await bus.emit(Events.SYNC_STARTED, stores=["epic"], scope="all")
    await bus.emit(Events.SYNC_FAILED, error="boom")
    snapshot = metrics.get_plugin_metrics()
    assert snapshot["counters"]["sync_failures"] == 1
    assert "sync_duration_ms" not in snapshot["timers_ms"]
    assert metrics._pending_timers == {}


async def test_failed_download_drops_the_pending_timer() -> None:
    """The leak that mattered: one stale entry per cancelled install."""
    bus, metrics = _collector()
    item = {"store": "gog", "game_id": "g1"}
    await bus.emit(Events.DOWNLOAD_STARTED, item=item)
    await bus.emit(Events.DOWNLOAD_FAILED, item=item, error="cancelled")
    snapshot = metrics.get_plugin_metrics()
    assert snapshot["counters"]["download_failed"] == 1
    assert "download_duration_ms" not in snapshot["timers_ms"]
    assert metrics._pending_timers == {}


async def test_repeated_failures_do_not_accumulate_pending_entries() -> None:
    bus, metrics = _collector()
    for index in range(5):
        item = {"store": "gog", "game_id": f"g{index}"}
        await bus.emit(Events.DOWNLOAD_STARTED, item=item)
        await bus.emit(Events.DOWNLOAD_FAILED, item=item, error="cancelled")
    assert metrics._pending_timers == {}


# ── unpaired events must stay harmless ────────────────────────────
async def test_completion_without_a_start_is_ignored() -> None:
    """A replayed or duplicated completion must not invent a timer."""
    bus, metrics = _collector()
    await bus.emit(Events.STORE_AUTH_COMPLETE, store="epic")
    await bus.emit(Events.DOWNLOAD_COMPLETE, store="epic", game_id="g1")
    await bus.emit(Events.SYNC_COMPLETE, games=[], stores_synced=[])
    assert metrics.get_plugin_metrics()["timers_ms"] == {}


async def test_snapshot_exposes_no_game_or_store_identifiers() -> None:
    """The bundle-safety property: keys are metric names, never ids.

    ``_pending_timers`` is the only structure holding a store or game id
    and it is deliberately absent from the snapshot, which is what makes
    this safe to fold into a support bundle a reporter posts publicly.
    """
    bus, metrics = _collector()
    item = {"store": "gog", "game_id": "secret-title-id"}
    await bus.emit(Events.DOWNLOAD_STARTED, item=item)
    await bus.emit(Events.STORE_AUTH_STARTED, store="gog")
    snapshot: dict[str, Any] = metrics.get_plugin_metrics()
    assert set(snapshot) == {"counters", "timers_ms", "gauges", "uptime_s"}
    rendered = repr(snapshot)
    assert "secret-title-id" not in rendered
    assert "gog" not in rendered
