"""scripts/fetch_bundled_binaries.py — put the right store CLIs in bin/.

``build-plugin.sh`` does this for a local build. CI does not run that
script — it drives the Decky CLI directly — and the Decky CLI's own
``remote_binary`` download knows nothing about architectures: it reads
one array from package.json and fetches it, whatever machine the plugin
is being built for. On an ARM build that produces a zip that installs
cleanly and then fails at every store call.

So this script does the fetch instead, for the architecture named by
``UNIFIDECK_TARGET_ARCH`` (default: this machine's), verifying every
download against the ``sha256hash`` the manifest publishes for that
architecture — the same value Decky verifies at install time. It then
strips the manifests from package.json so the CLI finds nothing left to
download and simply zips what is already in ``bin/``.

Stdlib only, and deliberately not importing anything from ``py_modules``:
it runs before the plugin tree is assembled, in a CI step whose Python is
a bare ``actions/setup-python``.

Usage::

    UNIFIDECK_TARGET_ARCH=aarch64 python3 scripts/fetch_bundled_binaries.py
    python3 scripts/fetch_bundled_binaries.py --arch x86_64 --keep-manifest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import stat
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Canonical architecture → the package.json key holding its manifest.
#: x86_64 keeps the bare ``remote_binary`` name because that is the key
#: Decky itself reads.
MANIFEST_KEYS = {
    "x86_64": "remote_binary",
    "aarch64": "remote_binary_aarch64",
}

#: Every spelling we may be handed, mapped to the canonical one. Mirrors
#: ``py_modules/unifideck/utils/arch.py``; duplicated rather than imported
#: because this script runs before the plugin tree is importable.
ALIASES = {
    "x86_64": "x86_64", "amd64": "x86_64", "x64": "x86_64",
    "aarch64": "aarch64", "arm64": "aarch64", "armv8l": "aarch64",
}

_CHUNK = 1 << 20


def normalize_arch(machine: str | None) -> str | None:
    """Canonical architecture name, or ``None`` if we ship no build for it."""
    if not machine:
        return None
    return ALIASES.get(machine.strip().lower())


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    """Fetch ``url`` to ``dest`` via a temporary file, then make it +x.

    The temporary file matters: a partial download left at the final path
    is indistinguishable from a good one to every later step, and the
    checksum that would have caught it is computed after the move.
    """
    staging = dest.with_suffix(dest.suffix + ".new")
    with urllib.request.urlopen(url, timeout=120) as response:
        staging.write_bytes(response.read())
    staging.replace(dest)
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def fetch_all(arch: str, bin_dir: Path, manifest: list[dict[str, str]]) -> None:
    """Download every manifest entry into ``bin_dir``, verifying checksums."""
    for entry in manifest:
        name = entry["name"]
        url = entry["url"]
        expected = (entry.get("sha256hash") or "").lower()
        if not expected:
            raise SystemExit(f"{name}: no sha256hash in the {arch} manifest")
        dest = bin_dir / name
        if dest.is_file() and sha256_of(dest) == expected:
            print(f"  {name}: already present and verified")
            continue
        print(f"  {name}: downloading {url}")
        download(url, dest)
        actual = sha256_of(dest)
        if actual != expected:
            raise SystemExit(
                f"{name}: checksum mismatch\n"
                f"  expected {expected}\n  got      {actual}",
            )
        print(f"  {name}: verified ({dest.stat().st_size} bytes)")


def strip_manifests(package_json: Path) -> None:
    """Remove every ``remote_binary*`` key from package.json.

    Only ever run on a throwaway checkout. The binaries are already in
    ``bin/`` and verified; leaving the manifests in place would have the
    Decky CLI re-download them — the wrong architecture's, on an ARM
    build — over the top.
    """
    data = json.loads(package_json.read_text(encoding="utf-8"))
    removed = [key for key in data if key.startswith("remote_binary")]
    for key in removed:
        data.pop(key)
    package_json.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    print(f"Stripped {removed} from package.json (build-local copy)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arch",
        default=os.environ.get("UNIFIDECK_TARGET_ARCH") or platform.machine(),
        help="architecture to fetch binaries for (default: this machine's)",
    )
    parser.add_argument(
        "--keep-manifest",
        action="store_true",
        help="leave package.json's remote_binary arrays alone",
    )
    args = parser.parse_args()

    arch = normalize_arch(args.arch)
    if arch is None:
        print(
            f"error: no bundled binaries are published for {args.arch!r} "
            f"(supported: {', '.join(sorted(MANIFEST_KEYS))})",
            file=sys.stderr,
        )
        return 1

    package_json = REPO_ROOT / "package.json"
    manifest = json.loads(package_json.read_text(encoding="utf-8")).get(
        MANIFEST_KEYS[arch],
    )
    if not manifest:
        print(
            f"error: package.json has no {MANIFEST_KEYS[arch]} array",
            file=sys.stderr,
        )
        return 1

    bin_dir = REPO_ROOT / "bin"
    bin_dir.mkdir(exist_ok=True)
    print(f"Fetching {len(manifest)} bundled binaries for {arch}")
    fetch_all(arch, bin_dir, manifest)

    # The stamp the installed plugin reads to answer "what was this built
    # for?" — see core/binaries/bundled.py and the support bundle.
    (bin_dir / "ARCH").write_text(arch + "\n", encoding="utf-8")
    print(f"Stamped bin/ARCH = {arch}")

    if not args.keep_manifest:
        strip_manifests(package_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
