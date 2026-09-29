# 트래픽 수집을 실행(캡처는 별도로 실행)
# 인자: snapshot, restore, benign, attack
set -uo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
NS="${NS:-deepmesh}"

# 대상 주소
AUTH_POD="${AUTH_POD:-10.244.0.0}";     AUTH_URL="http://$AUTH_POD:8080"
POST_POD="${POST_POD:-10.244.0.0}";     POST_URL="http://$POST_POD:8080"
COMMENT_POD="${COMMENT_POD:-10.244.0.0}"; COMMENT_URL="http://$COMMENT_POD:8080"
FRONTEND_POD="${FRONTEND_POD:-10.244.0.0}"; FRONTEND_URL="http://$FRONTEND_POD:80"

# 서비스별 사용자 수 - 조정 가능
AUTH_USERS="${AUTH_USERS:-30}"
POST_USERS="${POST_USERS:-40}"
COMMENT_USERS="${COMMENT_USERS:-40}"
FRONTEND_USERS="${FRONTEND_USERS:-30}"
BENIGN_OPTS="${BENIGN_OPTS:--r 4 -t 2700s}"

snapshot () { bash "$DIR/db_snapshot.sh" snapshot; }
restore  () { echo "[restore] start"; bash "$DIR/db_snapshot.sh" restore; }

# 정상 트래픽 병렬 실행
benign () {
  echo "[benign] start auth=$AUTH_USERS post=$POST_USERS comment=$COMMENT_USERS frontend=$FRONTEND_USERS"
  locust -f "$DIR/benign/auth_locustfile.py"     --host "$AUTH_URL"     --headless -u "$AUTH_USERS" $BENIGN_OPTS \
    >"$DIR/benign_auth.log" 2>&1 &
  local p_auth=$!
  AUTH_HOST="$AUTH_URL" \
    locust -f "$DIR/benign/post_locustfile.py"    --host "$POST_URL"    --headless -u "$POST_USERS" $BENIGN_OPTS \
    >"$DIR/benign_post.log" 2>&1 &
  local p_post=$!
  AUTH_HOST="$AUTH_URL" POST_HOST="$POST_URL" \
    locust -f "$DIR/benign/comment_locustfile.py" --host "$COMMENT_URL" --headless -u "$COMMENT_USERS" $BENIGN_OPTS \
    >"$DIR/benign_comment.log" 2>&1 &
  local p_comment=$!
  locust -f "$DIR/benign/frontend_locustfile.py" --host "$FRONTEND_URL" --headless -u "$FRONTEND_USERS" $BENIGN_OPTS \
    >"$DIR/benign_frontend.log" 2>&1 &
  local p_frontend=$!
  echo "[benign] running auth=$p_auth post=$p_post comment=$p_comment frontend=$p_frontend"
  wait "$p_auth" "$p_post" "$p_comment" "$p_frontend"
  echo "[benign] done"
}

# 공격 시나리오 실행
attack () {
  local pod="$1" scen="$2"
  local script
  case "$scen" in
    k1)   script="k8s_enum.sh" ;;
    k2)   script="k8s_manipulate.sh" ;;
    l2)   script="lateral_token_abuse.sh" ;;
    l3)   script="lateral_chain.sh" ;;
    d1)   script="cross_db.sh" ;;
    e1)   script="exfil.sh" ;;
    r1)   script="response_tamper/run_tamper.sh" ;;
    *) echo "unknown scenario: $scen"; return 2 ;;
  esac
  echo "[attack] pod=$pod scenario=$scen ($script)"
  echo "[attack] copy scripts"
  kubectl -n "$NS" cp "$DIR/attack/inpod" "$pod:/tmp/atk" -c main-container
  echo "[attack] start capture, then press Enter"
  read -r _
  echo "[attack] run"
  kubectl -n "$NS" exec "$pod" -c main-container -- sh "/tmp/atk/$script"
  echo "[attack] cleanup"
  kubectl -n "$NS" exec "$pod" -c main-container -- rm -rf /tmp/atk
}

case "${1:-}" in
  snapshot) snapshot ;;
  restore)  restore ;;
  benign)   benign ;;
  attack)   attack "${2:?pod}" "${3:?scenario}" ;;
  *) echo "usage: snapshot|restore|benign|attack"; exit 2 ;;
esac
