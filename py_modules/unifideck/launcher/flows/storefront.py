"""launcher/flows/storefront.py — open a store's shop, signed in.

Third sibling of ``flows/auth.py`` (sign-in) and ``flows/xcloud.py``
(game streaming). Runs in the launcher subprocess, under the SYSTEM
python3, launched by Steam via a temporary shortcut — because in
Gaming Mode a window from a process Steam did not launch has no
gamescope session and never renders.

Only the four **browser-OAuth** stores reach this module. Ubisoft and
Battle.net authenticate inside a Wine prefix, so they have no browser
session and their shop is the vendor client's own Store/Shop tab;
``LauncherService._handle_auth_path`` routes them to
``_launch_wrapper_client`` *before* this module is consulted. A
wrapper store arriving here is a routing bug, and
:func:`_resolve_storefront_url` raises rather than opening a
signed-out web page.

Two properties are load-bearing and easy to break:

1. **Cookies are never cleared on this path.** The shared Edge
   profile's live web session IS the signed-in shop. The four
   ``clear_store_cookies`` call sites exist to force a fresh login
   form before a real sign-in; running one here would guarantee the
   signed-out page this flow exists to avoid.
2. **No ``STORE_AUTH_*`` event is ever emitted.** A ``STORE_AUTH_FAILED``
   would flip the store's row to ``error``, where the settings UI
   renders no button at all — stranding the user with no way to sign
   in or out. A shop that failed to open must leave auth state alone.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from unifideck.core.store_urls import storefront_url
from unifideck.core.types import Result
from unifideck.launcher.types.errors import (
    DependencyMissingError,
    GameNotFoundError,
)

from .auth import read_auth_url, wait_for_browser_exit

if TYPE_CHECKING:
    from unifideck.auth.edge_browser import EdgeBrowser
    from unifideck.launcher.types.context import LaunchContext

logger = logging.getLogger(__name__)

# Ceiling on one shop session. Browsing a store is not signing in —
# 600s (the auth ceiling) would kill the window mid-purchase.
#
# COUPLED to TEMP_SHORTCUT_SAFETY_CLEANUP_MS in
# ``src/lib/steam-bridge/temp-shortcut.ts``: that timer removes the
# temporary shortcut, which ends the gamescope session and destroys
# this window. It must stay strictly LARGER than this ceiling. Change
# one, change the other.
_MAX_STOREFRONT_SECONDS = 1800

# Ceiling on the reconcile window that follows. With the web session
# live the provider redirects through in a second or two and the
# window closes itself; this only bounds the case where the session
# was gone and the user is looking at a login form they never asked
# for. Short on purpose — they came to shop, not to sign in.
_MAX_RECONCILE_SECONDS = 90


def _read_config_int(key: str, default: int) -> int:
    """Read an int from the merged config, cold-start safe."""
    from unifideck.utils.config_helpers import read_config_int_cold_start
    return read_config_int_cold_start(key, default)


def _reconcile_armed() -> bool:
    """Whether the frontend armed a token reconcile for this shop run.

    Steam passes launch options as argv, and the dispatcher promotes any
    ``UNIFIDECK_*`` token into the environment, so this reads what the
    frontend set only after ``reconcile_store_session`` succeeded.
    """
    return os.environ.get(
        "UNIFIDECK_STOREFRONT_RECONCILE", "",
    ).strip() in ("1", "true", "yes")


def _resolve_storefront_url(store: str | None) -> str:
    """The shop URL for ``store``, raising if it has none.

    ``storefront_url`` answers ``""`` for the wrapper stores and for
    unknown ids. Both mean the request was mis-routed, so this fails
    loudly instead of handing an empty URL to the browser.
    """
    url = storefront_url(store or "")
    if not url:
        raise GameNotFoundError(
            f"no storefront URL for store {store!r}",
            context={"store": store or ""},
        )
    return url


def _busy_flavour(edge_browser: EdgeBrowser) -> str | None:
    """Which other Edge window is holding the shared profile, if any.

    Chromium refuses a second process on one ``--user-data-dir``: the
    new invocation hands its URL to the running instance over
    ``SingletonSocket`` and exits at once, its own flags ignored. That
    would leave us exiting immediately (so Steam tears down the
    shortcut) while a window opened inside *another* app's gamescope
    session — invisible behind an xCloud kiosk, or hijacking a live
    sign-in.

    So probe the per-flavour CDP ports first and refuse rather than
    spawn something doomed. A *leaked* auth instance self-heals:
    ``EdgeBrowser.prepare_auth_launch`` closes lingering auth targets
    before every real sign-in.
    """
    if edge_browser.cdp_alive(edge_browser.cdp_port):
        return "auth"
    if edge_browser.cdp_alive(edge_browser.xcloud_cdp_port()):
        return "xcloud"
    return None


async def _reuse_open_storefront(
    edge_browser: EdgeBrowser, url: str,
) -> bool:
    """Steer an already-open shop window at ``url``.

    Pressing the cart for Epic and then for GOG must not try to spawn
    a second Chromium. Navigating the live window is both correct and
    what the user expects. Returns False when there is nothing to
    reuse, or when the navigation failed and the stale targets have
    been closed so the caller can spawn fresh.
    """
    port = edge_browser.storefront_cdp_port()
    if not edge_browser.cdp_alive(port):
        return False
    logger.info(
        "[launcher.storefront] reusing open store window on port %d", port,
    )
    if await edge_browser.navigate_on_port(port, url):
        return True
    logger.warning(
        "[launcher.storefront] navigate failed on port %d — "
        "closing stale targets and respawning", port,
    )
    await edge_browser.close_targets_on_port(port, log_prefix="storefront")
    return False


async def _redeem_reconcile(
    edge_browser: EdgeBrowser, store: str,
) -> None:
    """Re-run the OAuth exchange so stored tokens match the shop's account.

    The user may have signed into a *different* account inside the shop.
    That changes the web session but leaves our CLI tokens on the old
    account, so the library would keep syncing the wrong one, and no
    amount of reading Chromium's encrypted cookie DB can tell us the
    new identity. Re-running the exchange can.

    ``reconcile_store_session`` armed this before the shop opened: the
    plugin process wrote the store's auth-URL file and started the
    redirect monitor. All that is left is to *visit* the URL. Because
    this path never clears the store's cookies, the provider redirects
    straight through with no login form — a second or two — and the
    monitor (which polls this same CDP port) captures the code.

    Gated on ``UNIFIDECK_STOREFRONT_RECONCILE``, which the frontend sets
    only when the arming RPC actually succeeded. The gate is not
    belt-and-braces: the auth-URL file persists from the last REAL
    sign-in, so without it an un-armed shop close would open a stale
    OAuth URL and pop a login window the user never asked for. Nothing
    would be waiting to capture the code, either.

    Entirely best-effort beyond that. Every failure is swallowed: the
    shop window has already served its purpose, and the frontend
    re-checks auth state regardless.
    """
    if not _reconcile_armed():
        logger.info(
            "[launcher.storefront] no reconcile armed for %s", store,
        )
        return
    try:
        auth_url = read_auth_url(store)
    except Exception as e:
        logger.info(
            "[launcher.storefront] no reconcile armed for %s (%s)",
            store, e,
        )
        return
    logger.info("[launcher.storefront] reconciling %s session", store)
    if not edge_browser.launch_auth(auth_url):
        logger.warning(
            "[launcher.storefront] reconcile browser failed to start",
        )
        return
    await wait_for_browser_exit(
        edge_browser,
        _read_config_int(
            "launcher.storefront_reconcile_max_seconds",
            _MAX_RECONCILE_SECONDS,
        ),
        log_tag="launcher.storefront.reconcile",
    )


async def _spawn_and_wait(
    edge_browser: EdgeBrowser, url: str, store: str,
) -> Result:
    """Spawn the shop window, outlive it, then reconcile the session.

    The wait is the point: Steam ends the shortcut's gamescope session
    the moment this process exits, and that destroys the window. Only
    reached when we actually own the browser process — the reuse path
    must NOT wait, because the window it steered belongs to another
    launcher process's session and this one has nothing to guard.
    """
    if not edge_browser.launch_storefront(url):
        return Result(
            success=False,
            store=store,
            error="edge_storefront_launch_failed",
        )
    await wait_for_browser_exit(
        edge_browser,
        _read_config_int(
            "launcher.storefront_max_seconds", _MAX_STOREFRONT_SECONDS,
        ),
        log_tag="launcher.storefront",
    )
    logger.info("[launcher.storefront] %s store window closed", store)
    await _redeem_reconcile(edge_browser, store)
    return Result(success=True, store=store)


async def handle_store_storefront(
    ctx: LaunchContext,
    edge_browser: EdgeBrowser,
) -> Result:
    """Open ``ctx``'s store shop in the shared Edge profile."""
    store = ctx.auth_store or ctx.store or ""
    url = _resolve_storefront_url(store)
    if not edge_browser.is_installed:
        raise DependencyMissingError(
            "Microsoft Edge flatpak required for the store browser",
            context={"store": store or ""},
        )
    busy = _busy_flavour(edge_browser)
    if busy is not None:
        logger.warning(
            "[launcher.storefront] refusing: an Edge %s window already "
            "holds the shared profile", busy,
        )
        return Result(
            success=False, store=store, error=f"edge_busy_{busy}",
        )
    logger.info("[launcher.storefront] opening %s store", store)
    if await _reuse_open_storefront(edge_browser, url):
        # Someone else's launcher owns that window and is already
        # waiting on it. Exiting now is correct — and necessary, or
        # this shortcut would sit "running" for the full ceiling.
        return Result(success=True, store=store)
    return await _spawn_and_wait(edge_browser, url, store)
