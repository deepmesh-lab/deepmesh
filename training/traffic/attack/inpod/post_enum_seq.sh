# userId를 증가시키며 내부 토큰 검증 API를 조회
. "$(dirname "$0")/common.sh"

# AUTH_URL이 없으면 auth pod 주소를 조회
if [ -z "$AUTH_URL" ]; then
  if command -v kubectl >/dev/null 2>&1; then
    AUTH_IP="$(kubectl -n "${NS:-board}" get pod -l app=auth-service -o jsonpath='{.items[0].status.podIP}' 2>/dev/null)"
    [ -n "$AUTH_IP" ] && AUTH_URL="http://$AUTH_IP:8080"
  fi
fi
if [ -z "$AUTH_URL" ]; then
  echo "[post_enum_seq] AUTH_URL required" >&2
  exit 3
fi

START_ID="${START_ID:-1}"
i=0; id="$START_ID"
while [ "$i" -lt "$N" ]; do
  urls=""; j=0
  while [ "$j" -lt "$BATCH" ] && [ "$i" -lt "$N" ]; do
    urls="$urls $AUTH_URL/internal/auth/validate?userId=$id"
    id=$((id+1)); i=$((i+1)); j=$((j+1))
  done
  curl_browser $urls >/dev/null 2>&1
  pace
done
echo "[post_enum_seq] done N=$N BATCH=$BATCH start=$START_ID"
