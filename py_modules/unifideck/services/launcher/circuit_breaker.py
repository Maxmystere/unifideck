"""services/launcher/circuit_breaker.py — Pre-launch failure protection.

2 functions protecting a launch from being attempted when the
game has repeatedly failed recently. Circuit breaker state
lives in ``LaunchHistoryService``; this module consults it and
surfaces the refusal to the user.

A third, ``get_launch_id_or_none``, was deleted in 2026-08: its only
purpose was to build a "Show logs" toast action pointing at
``unifideck://show-logs/<launch_id>``, and no frontend renders a toast
action button — both toast renderers special-case the cloud-save
``retry-sync`` modal and drop everything else, and the ``LaunchLogsModal``
that verb targets was never built. See the audit register.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from unifideck.core.types import Result

if TYPE_CHECKING:
    from unifideck.launcher.types.context import LaunchContext

    from .service import LauncherService

logger = logging.getLogger(__name__)


async def emit_circuit_open_toast(
    svc: LauncherService,
    ctx: LaunchContext,
    failure_count: int,
) -> None:
    """Emit an error toast when the circuit breaker refuses launch.

    Goes out on ``LAUNCHER_STAGE``, the only channel that reaches the UI
    from here. This runs in the launcher *subprocess* (``LauncherService``
    is built solely by ``launcher.bootstrap``), whose bus dies with the
    process — ``frontend_bridge.install_bus_forwarder`` mirrors
    LAUNCHER_STAGE, and nothing else, into the file the plugin drains.
    Until 2026-08 this emitted ``TOAST_NOTIFICATION`` instead, which had
    no forwarder and no subscriber in either process: a circuit-breaker
    refusal was completely silent, so a game that had failed three times
    simply stopped responding to Play with no message at all.
    """
    from unifideck.launcher.game_title import resolve_title
    from unifideck.launcher.rpc import emit_stage

    title = resolve_title(ctx.game_key)

    try:
        await emit_stage(
            svc._bus,
            i18n_key="toasts.launcher.errorCircuitBreakerOpen",
            game_title=title,
            severity="error",
            duration_ms=10000,
            # The string interpolates ``{{game_key}}``; feeding the
            # resolved display title into it turns "battlenet:D1 failed to
            # launch" into "Diablo IV failed to launch" without touching
            # 16 locale files. ``resolve_title`` falls back to the raw key.
            i18n_params={"game_key": title, "count": failure_count},
        )
    except Exception as e:
        logger.warning("[CircuitBreaker] Failed to emit toast: %s", e)


async def check_circuit_breaker(
    svc: LauncherService,
    ctx: LaunchContext,
) -> Result | None:
    """Return a refusal Result if the breaker is open."""
    if not svc._launch_history:
        return None

    store = ctx.store
    game_id = ctx.game_id
    game_key = f"{store}:{game_id}"

    try:
        # Assuming LaunchHistoryService has a method to check if circuit is open
        is_open, failure_count = svc._launch_history.is_circuit_open(game_key)

        if is_open:
            logger.warning("[CircuitBreaker] Circuit open for %s (failures: %d)", game_key, failure_count)
            await emit_circuit_open_toast(svc, ctx, failure_count)
            # ``Result`` has no ``message`` field — its public surface
            # is ``success``, ``error``, ``error_code``, ``store``,
            # ``metadata``. Same fix as ``error_toasts.py``: route
            # the human-readable text through ``metadata`` so the
            # toast helper can pick it up while the canonical
            # ``error`` slot holds the machine code. The earlier
            # ``message=`` form raised
            # ``TypeError: Result.__init__() got an unexpected
            # keyword argument 'message'`` every time the circuit
            # breaker engaged, swallowing the actual "circuit open"
            # signal under a TypeError noise.
            return Result(
                success=False,
                error="circuit_open",
                metadata={
                    "message": (
                        f"Launch refused. Game failed "
                        f"{failure_count} times recently."
                    ),
                },
            )

    except Exception as e:
        logger.debug("[CircuitBreaker] Failed to check circuit state: %s", e)

    return None
