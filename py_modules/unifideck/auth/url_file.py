"""auth/url_file.py — the OAuth-URL handoff file.

The plugin process resolves a store's OAuth URL, but the browser that
opens it is spawned by the launcher subprocess (Steam has to launch it,
or in Gaming Mode the window has no gamescope session and never
renders). A small file on disk is the handoff between the two.

Split out of ``orchestrator.py`` to keep that file under the 550-LOC
volumetry cap. The seam is clean: the orchestrator owns the *flow*, this
owns the *handoff*. ``launcher/flows/auth.read_auth_url`` is the reading
half, and it lives on the launcher side because only that side runs
under the system Python.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def write_url_atomically(path: str, url: str) -> bool:
    """Write the OAuth URL to disk atomically.

    Creates the parent directory if needed, writes to a `.tmp` sibling
    first, then renames into place. This guarantees the shell launcher
    never reads a half-written URL file.
    """
    def _write_sync() -> str:
        expanded = Path(path).expanduser()
        parent = expanded.parent
        parent.mkdir(parents=True, exist_ok=True)
        tmp = expanded.with_name(expanded.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.write(url)
        tmp.replace(expanded)
        return str(expanded)

    # `expanded` was bound only on the success path (the result of
    # asyncio.to_thread). When _write_sync raised OSError, the `except`
    # handler referenced an unbound `expanded`, producing an
    # UnboundLocalError that masked the real OSError and propagated to
    # the caller instead of returning False. Bind a fallback up front so
    # the error path can always log a meaningful target path.
    #
    # The fallback is the raw `path` (no expanduser): the real expanded
    # path is computed inside _write_sync and overwrites this on
    # success. Calling Path(...).expanduser() here would be a blocking
    # pathlib call in an async function (ASYNC240) for no benefit — the
    # value is only ever used in the error log, where the un-expanded
    # path (e.g. "~/.config/...") is just as diagnostic.
    expanded = path
    try:
        expanded = await asyncio.to_thread(_write_sync)
        logger.debug("[auth.url_file] wrote auth URL to %s", expanded)
        return True
    except OSError:
        logger.exception("[auth.url_file] failed to write %s", expanded)
        return False
