"""Game-assets logical-path resolver and renderer SDK installation.

Configure asset resolution with ``GAME_ASSETS_SOURCE`` (or legacy ``GAME_ASSET_CDN_ROOT``):

* ``disabled`` / ``none`` / ``off`` — disable all game assets (placeholders only).
* ``local`` — point to an external local asset server at ``http://127.0.0.1:8015`` (e.g. ``just serve-assets``, or override via ``GAME_ASSETS_LOCAL_URL``).
* ``https://...`` — remote base URL; all assets are requested by logical path under ``game-assets/``.

When unset, defaults to ``disabled`` in CI, ``local`` if ``game-assets/`` exists, else ``disabled``.
"""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PORT = 8015
ASSET_KINDS = ("icons", "portraits", "orchestrion", "models")

CDN_ORIGIN = "https://cdn.icexiv.top"

# Named asset profiles selectable via `GAME_ASSETS_SOURCE=<name>` (or pass an `https://...` URL directly).
# Any individual kind can also be overridden via `GAME_ASSETS_{ICONS,PORTRAITS,ORCHESTRION,MODELS}_BASE`.
PROFILES = {
    "disabled": {
        "icons": "",
        "portraits": "",
        "orchestrion": "",
        "models": "",
    },
    "local": {
        "icons": f"http://127.0.0.1:{PORT}/icons",
        "portraits": f"http://127.0.0.1:{PORT}/portraits",
        "orchestrion": f"http://127.0.0.1:{PORT}/orchestrion",
        "models": f"http://127.0.0.1:{PORT}/models",
    },
    "prod": {
        "icons": f"{CDN_ORIGIN}/icons",
        "portraits": f"{CDN_ORIGIN}/portraits",
        "orchestrion": f"{CDN_ORIGIN}/orchestrion",
        "models": f"{CDN_ORIGIN}/models",
    },
}

SDK_FILES = ("component.js", "icexiv_renderer.js", "icexiv_renderer_bg.wasm")
EFFECT_SDK = ("effects/icexiv_effects.js", "effects/icexiv_effects_bg.wasm", "effects/effect-worker.js")
DISABLED_VALUES = {"disabled", "none", "off", "false", "0"}
KEY_PATTERN = re.compile(r"(icons|portraits|orchestrion|models)/[A-Za-z0-9_./-]+")


def file_hash(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def install_file(source, dest):
    """Replace atomically; never mutate a hardlinked source or another build."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        staged = Path(tmp) / "file"
        try:
            os.link(source, staged)
        except OSError:
            shutil.copyfile(source, staged)
        staged.replace(dest)


def install_sdk(archive, sdk_hash, dest=None):
    """Verify and unpack the pinned same-origin renderer Web SDK runtime files."""
    dest = dest or (ROOT / "static/model-sdk")
    if not re.fullmatch("[a-f0-9]{64}", sdk_hash) or file_hash(archive) != sdk_hash:
        raise ValueError("renderer SDK SHA-256 mismatch")
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        for name in SDK_FILES + EFFECT_SDK:
            member = tar.getmember("package/pkg/" + name)
            if not member.isfile():
                raise ValueError(f"expected regular SDK file {name}")
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(member).read())


def _validate_remote_url(raw):
    url = raw.rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise ValueError(f"Remote game-assets root must be a clean HTTPS URL: {raw}")
    return url


def _validate_base_url(raw):
    url = raw.rstrip("/")
    if url.startswith("/") and not url.startswith("//"):
        if ".." in url.split("/") or "?" in url or "#" in url or "\\" in url:
            raise ValueError(f"Invalid site-relative game-assets base: {raw}")
        return url
    parsed = urlsplit(url)
    is_local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (parsed.scheme != "https" and not is_local_http) or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise ValueError(f"Game-assets base must be a clean HTTPS, localhost HTTP, or site-relative `/` URL: {raw}")
    return url


class Media:
    def __init__(self, root, source=None, *, overrides=None):
        self.root = Path(root)
        self.files = self.root / "game-assets"

        raw_source = source if source is not None else os.getenv("GAME_ASSETS_SOURCE")
        if raw_source is None or raw_source == "":
            raw_source = os.getenv("GAME_ASSET_CDN_ROOT", "")
        raw_source = raw_source.strip()

        if not raw_source:
            if not os.getenv("CI") and self.files.is_dir():
                raw_source = "local"
            else:
                raw_source = "disabled"

        lowered = raw_source.lower()
        if lowered in DISABLED_VALUES:
            self.mode = "disabled"
            self.base = ""
            defaults = dict(PROFILES["disabled"])
        elif lowered == "local":
            self.mode = "local"
            local_url = os.getenv("GAME_ASSETS_LOCAL_URL", "").strip().rstrip("/")
            if local_url:
                self.base = _validate_base_url(local_url)
                defaults = {kind: f"{self.base}/{kind}" for kind in ASSET_KINDS}
            else:
                self.base = f"http://127.0.0.1:{PORT}"
                defaults = dict(PROFILES["local"])
        elif lowered in PROFILES:
            self.mode = lowered
            self.base = ""
            defaults = {
                kind: (_validate_base_url(val) if val else "")
                for kind, val in PROFILES[lowered].items()
            }
        else:
            self.mode = "remote"
            self.base = _validate_remote_url(raw_source)
            defaults = {kind: f"{self.base}/{kind}" for kind in ASSET_KINDS}

        self.bases = {}
        for kind in ASSET_KINDS:
            if overrides is not None and kind in overrides:
                raw_override = overrides[kind]
            else:
                raw_override = os.getenv(f"GAME_ASSETS_{kind.upper()}_BASE")
            if raw_override is not None and raw_override.strip() != "":
                val = raw_override.strip()
                self.bases[kind] = "" if val.lower() in DISABLED_VALUES else _validate_base_url(val)
            else:
                self.bases[kind] = defaults.get(kind, "")

    @property
    def enabled(self):
        return any(self.bases.values())

    def resolve(self, key):
        if not KEY_PATTERN.fullmatch(key) or ".." in key:
            raise ValueError(f"Invalid media key: {key}")
        kind, rest = key.split("/", 1)
        base = self.bases.get(kind, "")
        if not base:
            return ""
        return f"{base}/{rest}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(required=True, dest="command")
    sdk = commands.add_parser("install-sdk", help="Verify and install pinned renderer SDK into static/model-sdk/")
    sdk.add_argument("archive", type=Path)
    sdk.add_argument("--sha256", required=True)
    sdk.add_argument("--dest", type=Path, default=ROOT / "static/model-sdk")
    args = parser.parse_args()
    install_sdk(args.archive, args.sha256, args.dest)


if __name__ == "__main__":
    main()
