#!/usr/bin/env bash
# Restricted SSH forced-command receiver for db.icexiv.top.
# Reads `<filename> <sha256>` from stdin, fetches the zstd tarball from TOS,
# verifies SHA-256, extracts locally, and atomically swaps /srv/db.icexiv.top/www.
set -euo pipefail

BASE="/srv/db.icexiv.top"
RELEASES="$BASE/releases"
TOS_BASE="https://cdn.icexiv.top/_deploy"

read -r FILENAME EXPECTED_SHA256 || { echo "Expected '<filename> <sha256>' on stdin" >&2; exit 1; }

if [[ ! "$FILENAME" =~ ^db-site-[A-Za-z0-9._-]+\.tar\.zst$ ]]; then
  echo "Invalid bundle filename: $FILENAME" >&2
  exit 1
fi
if [[ ! "$EXPECTED_SHA256" =~ ^[a-f0-9]{64}$ ]]; then
  echo "Invalid sha256: $EXPECTED_SHA256" >&2
  exit 1
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)-$$"
STAGE="$RELEASES/$TS"
TMP_ARCHIVE="$(mktemp "$BASE/.deploy-${TS}.XXXXXX.tar.zst")"

cleanup() {
  rm -f "$TMP_ARCHIVE"
}
cleanup_err() {
  rm -rf "$STAGE"
  rm -f "$TMP_ARCHIVE"
}
trap cleanup EXIT
trap cleanup_err ERR

mkdir -p "$RELEASES" "$STAGE"
curl -fsSL --retry 3 --retry-delay 2 "$TOS_BASE/$FILENAME" -o "$TMP_ARCHIVE"

ACTUAL_SHA256="$(sha256sum "$TMP_ARCHIVE" | awk '{print $1}')"
if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
  echo "SHA-256 mismatch: expected $EXPECTED_SHA256, got $ACTUAL_SHA256" >&2
  exit 1
fi

zstd -d --long=27 --stdout "$TMP_ARCHIVE" | tar -xf - -C "$STAGE" --no-same-owner --no-same-permissions
chmod -R u+rwX,go+rX,go-w "$STAGE"

test -f "$STAGE/index.html"
test -f "$STAGE/items/1.html"

if [ -d "$BASE/www" ] && [ ! -L "$BASE/www" ]; then
  mv "$BASE/www" "$BASE/www.legacy-$TS"
fi

ln -sfn "releases/$TS" "$BASE/www.next"
mv -Tf "$BASE/www.next" "$BASE/www"

# Keep only the 2 most recent releases.
ls -1dt "$RELEASES"/* 2>/dev/null | tail -n +3 | xargs -r rm -rf
echo "Deployed $TS ($FILENAME) to $BASE/www"
