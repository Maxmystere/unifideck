"""auth/flow_events.py — which bus events one OAuth flow reports on.

Split out of ``orchestrator.py`` to keep that file under the 550-LOC
volumetry cap. The seam is natural: the orchestrator owns the *flow*
(get URL → wait for redirect → exchange code), while this module owns
the *vocabulary* it announces itself in.

The same machinery serves two callers whose failure modes must not be
confused with each other:

* A real **sign-in** reports on ``STORE_AUTH_*``. A failure there is
  news the user is actively waiting for.
* A **session reconcile** — re-running the exchange after the user
  closed a store's shop window, so the plugin's tokens follow an
  account switch made in there — must not. ``STORE_AUTH_FAILED``
  flips the store's row to ``error``, and the settings UI renders no
  button at all in that state. A background refresh nobody asked for
  must never be able to strand the user with no way to sign in or out.
"""
from __future__ import annotations

from dataclasses import dataclass

from unifideck.core.types import Events


@dataclass(frozen=True)
class FlowEvents:
    """The events one flow announces its start and outcome on.

    ``started=None`` suppresses the start emission entirely, which is
    what a reconcile wants: it runs behind a window the user has
    already closed, so there is no flow to announce.
    """

    started: Events | None
    complete: Events
    failed: Events


AUTH_FLOW_EVENTS = FlowEvents(
    started=Events.STORE_AUTH_STARTED,
    complete=Events.STORE_AUTH_COMPLETE,
    failed=Events.STORE_AUTH_FAILED,
)

RECONCILE_FLOW_EVENTS = FlowEvents(
    started=None,
    complete=Events.STORE_SESSION_RECONCILED,
    failed=Events.STORE_SESSION_RECONCILE_FAILED,
)

# Deadline for a reconcile flow. It is armed when the user OPENS a shop
# window and only redeemed when they close it, so it has to outlast a
# whole browsing session: the storefront ceiling
# (``launcher/flows/storefront._MAX_STOREFRONT_SECONDS``, 1800s) plus
# slack for the OAuth round trip that follows. The orchestrator's
# default 300s would expire while the user was still shopping.
RECONCILE_TIMEOUT_SECONDS = 2100.0
