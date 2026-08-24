"""Permission hardening for third-party store-CLI credential files.

py_modules/unifideck/stores/shared/cli_credentials.py

GOG and Microsoft keep their tokens in a ``SecureTokenStore`` blob that we
write ourselves at mode 0600. Epic and Amazon do not: legendary and nile own
their own ``user.json`` and write it world-readable (0644), holding a live
access token and refresh token in plaintext. On a Steam Deck that file is
readable by every other local account *and* by every game the user launches,
because Proton maps ``$HOME`` into the prefix.

This module closes the mode half of that gap. It is deliberately **not**
encryption at rest — anything running as the user can still read these files.
Doing better means wrapping every legendary/nile invocation so the plaintext
exists only for the duration of one call; that was the job of
``security/ephemeral_creds.py``, which was written, documented, never wired up
by anything, and deleted (audit §1.4 f).

Why it hooks the *authentication check* rather than each subprocess spawn:
Epic and Amazon between them make around a dozen ``create_subprocess_exec``
calls with no shared choke point (``StoreBase._run_cli`` is dead code, audit
§3.2), and both CLIs rewrite ``user.json`` at 0644 whenever they refresh a
token. A one-shot chmod at sign-in would therefore drift back to 0644 on the
next token rotation. ``_check_*_authenticated`` already stats and opens the
file, runs on every store-status refresh and sync, and so re-tightens it
shortly after any rotation.
"""

from __future__ import annotations

import logging
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from unifideck.security import emit_permissions_check

if TYPE_CHECKING:
    from unifideck.event_bus.event_bus import EventBus

logger = logging.getLogger(__name__)

#: Owner read/write only — the mode GOG's and Microsoft's token writers
#: already create their files with.
_TARGET_MODE = 0o600

#: Group/other bits. Any of these set means the file is readable by more
#: than its owner and must be tightened.
_TOO_OPEN = stat.S_IRWXG | stat.S_IRWXO

#: ``nile_lock.quarantine_corrupt_user_file`` renames an unparseable
#: ``user.json`` to ``user.json.corrupt-<epoch>`` and keeps it for
#: diagnosis. The rename preserves the original mode, so those copies are
#: world-readable too — and they still contain the credentials.
_QUARANTINE_GLOB = "{name}.corrupt-*"


def harden_cli_credential_file(
    path: str | Path,
    store: str,
    bus: EventBus | None = None,
) -> int:
    """Tighten *path* (and its quarantine copies) to 0600. Returns the count.

    Only touches files whose mode actually grants group or other access, so
    the common case is a single ``stat`` and no write. Never raises: a
    credential file we cannot chmod is strictly no worse than before, and
    this runs on the store-status path where an exception would surface as a
    spurious "signed out".

    Emits ``SECURITY_PERMISSIONS_CHECK`` for each file it changed, the same
    audit event GOG and Microsoft already emit after a token save, so all
    four stores report credential permissions through one channel into the
    support bundle's ``security`` block.
    """
    target = Path(path).expanduser()
    changed = 0
    for candidate in _candidates(target):
        if _tighten(candidate, store, bus):
            changed += 1
    return changed


def _candidates(target: Path) -> list[Path]:
    """The credential file plus any quarantined copies beside it."""
    found = [target]
    try:
        found.extend(
            sorted(target.parent.glob(
                _QUARANTINE_GLOB.format(name=target.name),
            )),
        )
    except OSError as e:
        logger.debug(
            "[cli_credentials] could not scan for quarantine copies "
            "beside %s: %s", target, e,
        )
    return found


def _tighten(path: Path, store: str, bus: EventBus | None) -> bool:
    """Chmod one file to 0600 if it is too open. True if it was changed."""
    try:
        mode = path.stat().st_mode & 0o7777
    except OSError:
        # Missing is the normal case for a signed-out store, and for the
        # quarantine glob whenever nothing has ever been corrupted.
        return False
    if not mode & _TOO_OPEN:
        return False
    try:
        path.chmod(_TARGET_MODE)
    except OSError as e:
        logger.warning(
            "[cli_credentials] %s credential file %s is mode %o and could "
            "not be tightened: %s", store, path, mode, e,
        )
        return False
    logger.info(
        "[cli_credentials] tightened %s credential file %s from %o to %o",
        store, path, mode, _TARGET_MODE,
    )
    if bus is not None:
        emit_permissions_check(bus, store, str(path), _TARGET_MODE)
    return True
