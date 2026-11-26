#!/usr/bin/env bash
# Restricted SSH forced-command receiver for db.icexiv.top.
# Install at /usr/local/bin/deploy-db-site (chmod 0755) and set in /home/deploy/.ssh/authorized_keys:
#   command="/usr/local/bin/deploy-db-site",restrict ssh-ed25519 ...
set -euo pipefail

BASE="/srv/db.icexiv.top"
RELEASES="$BASE/releases"
TS="$(date -u +%Y%m%dT%H%M%SZ)-$$"
STAGE="$RELEASES/$TS"

mkdir -p "$RELEASES"
trap 'rm -rf "$STAGE"' ERR

mkdir -p "$STAGE"
tar -xzf - -C "$STAGE" --no-same-owner --no-same-permissions
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
echo "Deployed $TS to $BASE/www"
