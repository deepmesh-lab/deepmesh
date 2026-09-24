# backend 경로를 반복 탐색
. "$(dirname "$0")/common.sh"
TARGET="${SCAN_TARGET:-$POST_URL}"
PATHS="/ /.env /.git/config /actuator/health /actuator/env /admin /api/posts /api/posts/1 \
/api/comments/1/comments /internal/posts/1/exists /internal/auth/validate /.aws/credentials \
/wp-login.php /config.json /swagger-ui/index.html"
i=0
while [ "$i" -lt "$N" ]; do
  urls=""
  for p in $PATHS; do
    [ "$i" -ge "$N" ] && break
    urls="$urls $TARGET$p"; i=$((i+1))
  done
  curl_browser $urls >/dev/null 2>&1
  pace
done
echo "[frontend_scan_seq] done N=$N target=$TARGET"
