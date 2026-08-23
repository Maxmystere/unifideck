"""Session reconcile — re-running the exchange after a shop visit.

Signing into a DIFFERENT account inside the store browser changes the
web session but leaves the plugin's CLI tokens on the old account, so
the library would keep syncing the wrong one. Chromium's cookie DB
cannot tell us the new identity; re-running the OAuth exchange can.

The property that matters most here is negative: **a reconcile must
never emit ``STORE_AUTH_FAILED``**. That event flips the store's row to
``error``, where ``StoreAuthButton`` renders ``null`` — so a background
refresh nobody asked for would leave the user with no button at all,
neither "Sign in" nor "Sign out". A reconcile that fails must be silent
to the auth UI and let the frontend's own status re-check settle it.
"""
from __future__ import annotations

from typing import Any

import pytest

from unifideck.auth.flow_events import (
    AUTH_FLOW_EVENTS,
    RECONCILE_FLOW_EVENTS,
    RECONCILE_TIMEOUT_SECONDS,
)
from unifideck.auth.orchestrator import AuthOrchestrator
from unifideck.core.types import AuthResult, Events


class _RecordingBus:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event: Any, **kwargs: Any) -> None:
        name = getattr(event, "value", event)
        self.emitted.append((name, kwargs))

    def names(self) -> list[str]:
        return [n for n, _ in self.emitted]


class _Capture:
    def __init__(self, *, success: bool, code: str = "abcd1234") -> None:
        self.success = success
        self.code = code
        self.redirect_url = "https://callback/x?code=abcd1234"
        self.elapsed_seconds = 0.1
        self.error = None if success else "timeout"


class _Monitor:
    def __init__(self, capture: _Capture) -> None:
        self._capture = capture

    async def wait_for_redirect(self, **_k: Any) -> _Capture:
        return self._capture

    async def close_oauth_tab(self, _domain: str) -> None:
        return None


def _orch(bus: _RecordingBus, capture: _Capture) -> AuthOrchestrator:
    from unifideck.auth.orchestrator import OrchestratorConfig

    return AuthOrchestrator(
        bus,  # type: ignore[arg-type]
        _Monitor(capture),  # type: ignore[arg-type]
        "epic",
        OrchestratorConfig(browser_launch_grace=0.0),
    )


async def _url() -> str:
    return "https://oauth/authorize"


def _exchange(success: bool):
    async def _run(_code: str) -> AuthResult:
        return AuthResult(
            success=success,
            store="epic",
            error=None if success else "token_exchange_failed",
        )

    return _run


# ── The negative guarantee ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_failed_reconcile_never_emits_store_auth_failed() -> None:
    """Otherwise the row goes to `error` and loses BOTH its buttons."""
    bus = _RecordingBus()

    await _orch(bus, _Capture(success=False)).run_flow(
        get_url=_url,
        allowed_uris=["https://callback/"],
        exchange_code=_exchange(True),
        events=RECONCILE_FLOW_EVENTS,
    )

    assert Events.STORE_AUTH_FAILED.value not in bus.names()
    assert Events.STORE_SESSION_RECONCILE_FAILED.value in bus.names()


@pytest.mark.asyncio
async def test_a_failed_exchange_also_stays_off_the_auth_events() -> None:
    bus = _RecordingBus()

    await _orch(bus, _Capture(success=True)).run_flow(
        get_url=_url,
        allowed_uris=["https://callback/"],
        exchange_code=_exchange(False),
        events=RECONCILE_FLOW_EVENTS,
    )

    assert Events.STORE_AUTH_FAILED.value not in bus.names()
    assert Events.STORE_SESSION_RECONCILE_FAILED.value in bus.names()


@pytest.mark.asyncio
async def test_a_reconcile_announces_no_start() -> None:
    """It runs behind a window the user already closed — nothing to announce."""
    bus = _RecordingBus()

    await _orch(bus, _Capture(success=True)).run_flow(
        get_url=_url,
        allowed_uris=["https://callback/"],
        exchange_code=_exchange(True),
        events=RECONCILE_FLOW_EVENTS,
    )

    assert Events.STORE_AUTH_STARTED.value not in bus.names()


@pytest.mark.asyncio
async def test_a_successful_reconcile_reports_on_its_own_event() -> None:
    bus = _RecordingBus()

    await _orch(bus, _Capture(success=True)).run_flow(
        get_url=_url,
        allowed_uris=["https://callback/"],
        exchange_code=_exchange(True),
        events=RECONCILE_FLOW_EVENTS,
    )

    assert Events.STORE_SESSION_RECONCILED.value in bus.names()
    assert Events.STORE_AUTH_COMPLETE.value not in bus.names()


# ── Regression: a real sign-in is unchanged ─────────────────────────


@pytest.mark.asyncio
async def test_sign_in_still_uses_the_auth_events_by_default() -> None:
    bus = _RecordingBus()

    await _orch(bus, _Capture(success=True)).run_flow(
        get_url=_url,
        allowed_uris=["https://callback/"],
        exchange_code=_exchange(True),
    )

    assert Events.STORE_AUTH_STARTED.value in bus.names()
    assert Events.STORE_AUTH_COMPLETE.value in bus.names()


@pytest.mark.asyncio
async def test_a_failed_sign_in_still_emits_store_auth_failed() -> None:
    bus = _RecordingBus()

    await _orch(bus, _Capture(success=False)).run_flow(
        get_url=_url,
        allowed_uris=["https://callback/"],
        exchange_code=_exchange(True),
    )

    assert Events.STORE_AUTH_FAILED.value in bus.names()


# ── The event sets themselves ───────────────────────────────────────


def test_the_two_event_sets_share_nothing() -> None:
    auth = {AUTH_FLOW_EVENTS.started, AUTH_FLOW_EVENTS.complete,
            AUTH_FLOW_EVENTS.failed}
    rec = {RECONCILE_FLOW_EVENTS.complete, RECONCILE_FLOW_EVENTS.failed}
    assert auth & rec == set()
    assert RECONCILE_FLOW_EVENTS.started is None


def test_the_reconcile_deadline_outlasts_a_shopping_session() -> None:
    """Armed at open, redeemed at close — 300s would expire mid-browse."""
    from unifideck.launcher.flows.storefront import _MAX_STOREFRONT_SECONDS

    assert RECONCILE_TIMEOUT_SECONDS > _MAX_STOREFRONT_SECONDS


# ── A reconcile must not displace a live sign-in ────────────────────


@pytest.mark.asyncio
async def test_a_reconcile_stands_down_while_a_sign_in_is_in_flight() -> None:
    """Arming one runs ``cancel_background()``, which would kill the login.

    The user would be left staring at a filled-in login form with
    nothing waiting to capture the code — and no error anywhere.
    """
    bus = _RecordingBus()
    orch = _orch(bus, _Capture(success=True))

    started = await orch.run_flow(
        get_url=_url,
        allowed_uris=["https://callback/"],
        exchange_code=_exchange(True),
        background=True,
    )
    assert started.success is True
    assert orch.has_active_flow() is True

    result = await orch.run_flow(
        get_url=_url,
        allowed_uris=["https://callback/"],
        exchange_code=_exchange(True),
        events=RECONCILE_FLOW_EVENTS,
    )

    assert result.success is False
    assert result.error == "flow_in_progress"
    assert orch.has_active_flow() is True, "the sign-in survived"
    orch.cancel_background()


@pytest.mark.asyncio
async def test_a_sign_in_may_still_supersede_a_stale_reconcile() -> None:
    """The user asked for the sign-in; it wins."""
    bus = _RecordingBus()
    orch = _orch(bus, _Capture(success=True))

    await orch.run_flow(
        get_url=_url,
        allowed_uris=["https://callback/"],
        exchange_code=_exchange(True),
        background=True,
        events=RECONCILE_FLOW_EVENTS,
    )

    result = await orch.run_flow(
        get_url=_url,
        allowed_uris=["https://callback/"],
        exchange_code=_exchange(True),
        background=True,
    )

    assert result.success is True
    orch.cancel_background()
