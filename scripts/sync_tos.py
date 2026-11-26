"""Sync game-assets/models/ (in-memory gzip) and game-assets/orchestrion/ (raw) to Volcengine TOS.

Uses standard S3 Signature V4 over HTTPS with zero third-party dependencies:
- ``models/objects/sha256/*``: pre-gzipped in memory (``mtime=0``), ``Content-Encoding: gzip``,
  ``Cache-Control: public, max-age=31536000, immutable``; skipped immediately if key exists.
- ``models/manifests/*.json`` & ``models/actions/*.json``: pre-gzipped in memory (``mtime=0``),
  ``Content-Encoding: gzip``, ``Cache-Control: public, max-age=86400``; skipped if ETag matches.
- ``orchestrion/*.mp3``: uploaded raw (no gzip so ``<audio>`` HTTP Range seeking works),
  ``Cache-Control: public, max-age=31536000, immutable``; skipped if ETag matches.

Required environment variables:
  TOS_BUCKET      Bucket name
  TOS_REGION      Region (e.g. cn-beijing)
  TOS_ACCESS_KEY  Access Key ID (falls back to AWS_ACCESS_KEY_ID)
  TOS_SECRET_KEY  Secret Access Key (falls back to AWS_SECRET_ACCESS_KEY)

Optional environment variables:
  TOS_ENDPOINT    S3-compatible endpoint host (default: ``tos-s3-{TOS_REGION}.volces.com``)
  TOS_PREFIX      Key prefix inside the bucket (default: ``""``)
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import gzip
import hashlib
import hmac
import http.client
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ASSETS_ROOT = ROOT / "game-assets"
SYNC_DIRS = ("icons", "portraits", "orchestrion", "models")
# Prefixes under game-assets/ that are gzip-compressed in memory with `Content-Encoding: gzip`.
# Everything else (e.g. `orchestrion/` MP3s that rely on HTTP Range seeking) is uploaded raw.
DEFAULT_GZIP_PREFIXES = ("models/",)
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
MANIFEST_CACHE = "public, max-age=86400"


def load_dotenv(path):
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _hmac_sha256(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key, date_stamp, region, service="s3"):
    k_date = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")


def _encode_path(key):
    return "/" + quote(key.lstrip("/"), safe="/-_.~")


def _canonical_query(params):
    return "&".join(
        f"{quote(str(k), safe='-_.~')}={quote(str(v), safe='-_.~')}"
        for k, v in sorted(params.items())
    )


def sign_s3_v4(method, host, path, query_params, payload, *, access_key, secret_key, region, extra_headers=None, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()

    headers = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if extra_headers:
        for k, v in extra_headers.items():
            headers[k.lower()] = v

    sorted_keys = sorted(headers.keys())
    canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in sorted_keys)
    signed_headers = ";".join(sorted_keys)
    canonical_request = "\n".join([
        method,
        path,
        _canonical_query(query_params),
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signature = hmac.new(
        _signing_key(secret_key, date_stamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    out = {k: v for k, v in headers.items() if k != "host"}
    out["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return out


class S3Client:
    def __init__(self, *, bucket, region, access_key, secret_key, endpoint=None):
        self.bucket = bucket
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key
        raw_ep = (endpoint or f"tos-s3-{region}.volces.com").strip()
        if "://" in raw_ep:
            parsed = urlsplit(raw_ep)
            self.scheme = parsed.scheme
            ep_host = parsed.netloc
        else:
            self.scheme = "https"
            ep_host = raw_ep.rstrip("/")
        self.host = ep_host if ep_host.startswith(f"{bucket}.") else f"{bucket}.{ep_host}"
        self._local = threading.local()

    def _conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
            conn = cls(self.host, timeout=60)
            self._local.conn = conn
        return conn

    def _reset_conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def request(self, method, key, *, query=None, body=b"", extra_headers=None, retries=3):
        query = query or {}
        path = _encode_path(key) if key else "/"
        qs = _canonical_query(query)
        target = f"{path}?{qs}" if qs else path
        last_err = None
        for attempt in range(retries):
            headers = sign_s3_v4(
                method, self.host, path, query, body,
                access_key=self.access_key, secret_key=self.secret_key,
                region=self.region, extra_headers=extra_headers,
            )
            try:
                conn = self._conn()
                conn.request(method, target, body=body, headers=headers)
                resp = conn.getresponse()
                data = resp.read()
                if 200 <= resp.status < 300:
                    return resp.status, data
                if resp.status in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                    self._reset_conn()
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise RuntimeError(f"S3 {method} {target} failed ({resp.status}): {data[:400].decode('utf-8', 'replace')}")
            except (http.client.HTTPException, OSError) as err:
                last_err = err
                self._reset_conn()
                if attempt + 1 < retries:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise
        raise last_err

    def list_objects(self, prefix="", *, on_page=None):
        """Return ``{key: (etag_unquoted, size)}`` for all objects under ``prefix``."""
        existing = {}
        token = None
        while True:
            query = {"list-type": "2", "max-keys": "1000"}
            if prefix:
                query["prefix"] = prefix
            if token:
                query["continuation-token"] = token
            _, xml_bytes = self.request("GET", "", query=query)
            root = ET.fromstring(xml_bytes)
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}", 1)[0] + "}"
            for item in root.findall(f"{ns}Contents"):
                key = item.findtext(f"{ns}Key", "")
                etag = item.findtext(f"{ns}ETag", "").strip('"')
                size = int(item.findtext(f"{ns}Size", "0"))
                existing[key] = (etag, size)
            if on_page is not None:
                on_page(len(existing))
            truncated = root.findtext(f"{ns}IsTruncated", "false").lower() == "true"
            if not truncated:
                break
            token = root.findtext(f"{ns}NextContinuationToken")
            if not token:
                break
        return existing


def _fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.2f}{unit}"
        n /= 1024


def _fmt_duration(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


class ProgressBar:
    def __init__(self, total):
        self.total = max(total, 1)
        self.start = time.monotonic()
        self.last_draw = 0.0
        self.is_tty = sys.stdout.isatty()
        self.last_len = 0

    def render(self, uploaded, skipped, raw_bytes, wire_bytes, *, force=False):
        now = time.monotonic()
        done = uploaded + skipped
        if not force and (now - self.last_draw) < 0.1 and done < self.total:
            return
        self.last_draw = now
        elapsed = max(now - self.start, 1e-6)
        frac = min(done / self.total, 1.0)
        width = 24
        filled = int(width * frac)
        bar = "█" * filled + "░" * (width - filled)
        speed = wire_bytes / elapsed
        rate = done / elapsed
        eta = (self.total - done) / rate if rate > 0 else 0
        ratio = (wire_bytes / raw_bytes * 100) if raw_bytes else 0.0
        line = (
            f"[{bar}] {frac * 100:5.1f}%  {done:,}/{self.total:,}  "
            f"↑{uploaded:,} ↷{skipped:,}  "
            f"{_fmt_bytes(wire_bytes)} ({ratio:.0f}%)  "
            f"{_fmt_bytes(speed)}/s  ETA {_fmt_duration(eta)}"
        )
        if self.is_tty:
            pad = " " * max(0, self.last_len - len(line))
            sys.stdout.write(f"\r{line}{pad}")
            sys.stdout.flush()
            self.last_len = len(line)
            if force and done >= self.total:
                sys.stdout.write("\n")
                sys.stdout.flush()
        elif force or done % 1000 == 0 or done >= self.total:
            print(line, flush=True)


def classify_asset(rel_key, gzip_prefixes=DEFAULT_GZIP_PREFIXES):
    """Return ``(gzip_enabled, content_type, cache_control, immutable_key)`` for a game-assets relative key."""
    use_gzip = any(rel_key.startswith(prefix) for prefix in gzip_prefixes)
    if rel_key.startswith("models/objects/sha256/"):
        return use_gzip, "application/octet-stream", IMMUTABLE_CACHE, True
    if rel_key.endswith(".json"):
        return use_gzip, "application/json; charset=utf-8", MANIFEST_CACHE, False
    if rel_key.endswith(".webp"):
        return use_gzip, "image/webp", IMMUTABLE_CACHE, False
    if rel_key.endswith(".mp3"):
        return use_gzip, "audio/mpeg", IMMUTABLE_CACHE, False
    return use_gzip, "application/octet-stream", MANIFEST_CACHE, False


def prepare_payload(path, use_gzip):
    raw = path.read_bytes()
    if use_gzip:
        # mtime=0 makes gzip output and its MD5/ETag deterministic across runs.
        return gzip.compress(raw, compresslevel=6, mtime=0), len(raw)
    return raw, len(raw)


def collect_local_files(assets_root, kinds):
    files = []
    for kind in kinds:
        base = assets_root / kind
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                rel = path.relative_to(assets_root).as_posix()
                files.append((rel, path))
    return files


def sync(assets_root, *, client, prefix="", kinds=SYNC_DIRS, gzip_prefixes=DEFAULT_GZIP_PREFIXES,
         only=None, limit=None, jobs=16, dry_run=False):
    prefix_clean = prefix.strip("/")
    remote_prefix = f"{prefix_clean}/" if prefix_clean else ""
    if only:
        files = []
        for rel in only:
            rel_clean = rel.lstrip("/")
            path = assets_root / rel_clean
            if not path.is_file():
                raise FileNotFoundError(f"Asset file not found: {path}")
            files.append((rel_clean, path))
    else:
        files = collect_local_files(assets_root, kinds)
        if limit is not None:
            files = files[:limit]
    print(f"Found {len(files)} local files (gzip prefixes: {', '.join(gzip_prefixes) or 'none'})")

    existing = {}
    if client is not None and not only:
        is_tty = sys.stdout.isatty()
        total_listed = 0
        for kind in kinds:
            base_count = len(existing)
            def on_page(count, _base=base_count, _kind=kind):
                nonlocal total_listed
                total_listed = _base + count
                if is_tty:
                    sys.stdout.write(f"\rListing s3://{client.bucket}/{remote_prefix}{_kind}/ ... {total_listed:,} objects")
                    sys.stdout.flush()
            existing.update(client.list_objects(f"{remote_prefix}{kind}/", on_page=on_page))
        if is_tty:
            sys.stdout.write(f"\rFound {len(existing):,} remote objects in s3://{client.bucket}/{remote_prefix}              \n")
            sys.stdout.flush()
        else:
            print(f"Found {len(existing):,} remote objects in s3://{client.bucket}/{remote_prefix}")

    stats = {"uploaded": 0, "skipped": 0, "raw_bytes": 0, "wire_bytes": 0}
    lock = threading.Lock()
    progress = ProgressBar(len(files))

    def process(rel, path):
        key = f"{remote_prefix}{rel}"
        use_gzip, content_type, cache_control, immutable_key = classify_asset(rel, gzip_prefixes)
        remote_meta = existing.get(key)
        if immutable_key and remote_meta is not None:
            with lock:
                stats["skipped"] += 1
                progress.render(stats["uploaded"], stats["skipped"], stats["raw_bytes"], stats["wire_bytes"])
            return

        payload, raw_len = prepare_payload(path, use_gzip)
        md5_hex = hashlib.md5(payload).hexdigest()
        if remote_meta is not None and remote_meta[0] == md5_hex and remote_meta[1] == len(payload):
            with lock:
                stats["skipped"] += 1
                progress.render(stats["uploaded"], stats["skipped"], stats["raw_bytes"], stats["wire_bytes"])
            return

        if not dry_run:
            extra = {
                "Content-Type": content_type,
                "Cache-Control": cache_control,
            }
            if use_gzip:
                extra["Content-Encoding"] = "gzip"
            client.request("PUT", key, body=payload, extra_headers=extra)

        with lock:
            stats["uploaded"] += 1
            stats["raw_bytes"] += raw_len
            stats["wire_bytes"] += len(payload)
            progress.render(stats["uploaded"], stats["skipped"], stats["raw_bytes"], stats["wire_bytes"])

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(process, rel, path) for rel, path in files]
        for fut in as_completed(futures):
            fut.result()

    progress.render(stats["uploaded"], stats["skipped"], stats["raw_bytes"], stats["wire_bytes"], force=True)
    mode = "DRY RUN" if dry_run else "DONE"
    ratio = (stats["wire_bytes"] / stats["raw_bytes"] * 100) if stats["raw_bytes"] else 0.0
    elapsed = _fmt_duration(time.monotonic() - progress.start)
    print(
        f"{mode} in {elapsed}: uploaded={stats['uploaded']:,} skipped={stats['skipped']:,} "
        f"raw={_fmt_bytes(stats['raw_bytes'])} wire={_fmt_bytes(stats['wire_bytes'])} ({ratio:.1f}%)"
    )
    return stats


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Sync game-assets/{models,orchestrion} to Volcengine TOS")
    parser.add_argument("--assets-dir", type=Path, default=ASSETS_ROOT)
    parser.add_argument("--kinds", nargs="+", default=list(SYNC_DIRS), choices=list(SYNC_DIRS))
    parser.add_argument("--gzip-prefix", action="append", dest="gzip_prefixes",
                        help="Override prefixes to gzip in memory (repeatable; default: models/)")
    parser.add_argument("--no-gzip", action="store_true", help="Disable gzip compression for all files")
    parser.add_argument("--only", nargs="+", help="Upload specific relative paths under game-assets/ (e.g. models/manifests/1.json)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of files processed")
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--dry-run", action="store_true", help="Compute uploads without writing to TOS")
    parser.add_argument("--offline-dry-run", action="store_true", help="Dry run without connecting to TOS")
    args = parser.parse_args()

    if args.no_gzip:
        gzip_prefixes = ()
    elif args.gzip_prefixes is not None:
        gzip_prefixes = tuple(args.gzip_prefixes)
    else:
        gzip_prefixes = DEFAULT_GZIP_PREFIXES

    client = None
    prefix = os.getenv("TOS_PREFIX", "")
    if not args.offline_dry_run:
        bucket = os.getenv("TOS_BUCKET", "").strip()
        region = os.getenv("TOS_REGION", "").strip()
        access_key = (os.getenv("TOS_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID") or "").strip()
        secret_key = (os.getenv("TOS_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or "").strip()
        endpoint = os.getenv("TOS_ENDPOINT", "").strip() or None
        missing = [name for name, val in [
            ("TOS_BUCKET", bucket),
            ("TOS_REGION", region),
            ("TOS_ACCESS_KEY", access_key),
            ("TOS_SECRET_KEY", secret_key),
        ] if not val]
        if missing:
            sys.exit(f"Missing required environment variables: {', '.join(missing)}")
        client = S3Client(
            bucket=bucket,
            region=region,
            access_key=access_key,
            secret_key=secret_key,
            endpoint=endpoint,
        )

    sync(
        args.assets_dir,
        client=client,
        prefix=prefix,
        kinds=tuple(args.kinds),
        gzip_prefixes=gzip_prefixes,
        only=args.only,
        limit=args.limit,
        jobs=args.jobs,
        dry_run=args.dry_run or args.offline_dry_run,
    )


if __name__ == "__main__":
    main()
