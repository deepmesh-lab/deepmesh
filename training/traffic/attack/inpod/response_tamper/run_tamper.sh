# frontend 응답 변조 프록시를 실행
HERE="$(dirname "$0")"
APP_UPSTREAM="${APP_UPSTREAM:-http://localhost:8081}"
LISTEN_PORT="${LISTEN_PORT:-80}"

if ! command -v mitmdump >/dev/null 2>&1; then
  echo "[run_tamper] mitmdump missing" >&2
  exit 3
fi

if ! curl -s -o /dev/null --max-time 5 "$APP_UPSTREAM/"; then
  echo "[run_tamper] upstream unavailable: $APP_UPSTREAM" >&2
  exit 4
fi

echo "[run_tamper] listen=$LISTEN_PORT upstream=$APP_UPSTREAM"
mitmdump -s "$HERE/inject.py" --mode reverse:"$APP_UPSTREAM" -p "$LISTEN_PORT"
