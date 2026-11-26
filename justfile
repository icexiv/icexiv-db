# Serve local game-assets/ for `GAME_ASSETS_SOURCE=local notist serve`
serve-assets port="8015":
    miniserve game-assets \
      -i 127.0.0.1 \
      -p {{port}} \
      --header "Access-Control-Allow-Origin: *" \
      --header "Access-Control-Expose-Headers: Content-Length, Content-Range, Accept-Ranges"

# Sync game-assets/{models,orchestrion} to Volcengine TOS (models gzipped in memory, orchestrion raw)
sync-tos *args:
    python3 scripts/sync_tos.py {{args}}
