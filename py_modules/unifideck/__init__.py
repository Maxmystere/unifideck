"""Unifideck — unified game library for Steam Deck.

Top-level package. Defines the public API of the plugin's backend,
accessible from any Decky-loaded code via simple
`from unifideck.X import Y` imports.

The layered architecture is documented in ``docs/architecture.md``; the
layer diagram there is authoritative (do not restate a layer count here).
Imports flow downward only.

Adjacent packages (`auth/`, `cdp/`, `compatibility/`, `metadata/`,
`steam/`, `utils/`) provide support modules.
"""
from __future__ import annotations

__version__ = "0.7.1"
