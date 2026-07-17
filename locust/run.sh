#!/usr/bin/env bash
# run.sh — 전체 트래픽 수집 오케스트레이션: DB 스냅샷 → benign 수집 → attack 수집 → 스냅샷 복원(net-zero).
#
# 흐름(all):
#   1) snapshot : db_snapshot.sh snapshot     — 수집 전 DB 상태 저장(net-zero 기준점)
#   2) benign   : auth/post/comment/frontend locust 실행
#                 (mysql 은 db_locust 없이 백엔드 부하의 '부산물'로 캡처됨 — 별도 수집기 불필요)
#   3) attack   : attacker pod 안에서 enum/manipulate/bruteforce locust 실행(kubectl exec)
#   4) restore  : db_snapshot.sh restore       — 스냅샷 시점으로 복원 → 서비스 상태 원복
#
# ★ tcpdump 캡처는 이 스크립트가 하지 않는다(노드별 netns 캡처 = §5). 이 스크립트는 '수집기(locust)'와 DB 브래킷만 담당.
#   → 각 대상 pod 노드에서 tcpdump 를 켜 둔 상태로 실행하고, 단계 전환은 [benign]/[attack] echo 마커로 확인해 pcap 파일을 교체.
#   → mysql pcap 은 [benign] 단계 내내 mysql-0 netns 캡처를 함께 켜 두면 얻어진다.
#
# 사전:
#   - kubectl 접근 가능(snapshot/restore/attack). attacker pod·configmap 은 미리 배포(§5-2).
#   - benign 은 pod IP(10.244.x)에 도달 가능한 호스트(노드)에서 실행.
#   - 아래 CONFIG 를 `kubectl get pods -n deepmesh -o wide` 값으로 채운다(재스케줄되면 갱신).
#
# 사용:
#   bash locust/run.sh all       # 스냅샷 → benign → attack → 복원 (전체)
#   bash locust/run.sh snapshot | benign | attack | restore   # 개별 단계

set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
NS="${NS:-deepmesh}"
POD="${ATTACKER_POD:-attacker}"

# ── CONFIG (수집 직전 실제 pod IP 로 채울 것) ─────────────────────────
AUTH_POD="${AUTH_POD:-10.244.194.87}"          # auth-service pod IP
POST_POD="${POST_POD:-10.244.194.89}"          # post-service pod IP
COMMENT_POD="${COMMENT_POD:-10.244.194.90}"    # comment-service pod IP
FRONTEND_POD="${FRONTEND_POD:-10.244.100.215}" # frontend pod IP
BENIGN_OPTS="${BENIGN_OPTS:--u 20 -r 4 -t 600s}"

AUTH_URL="http://$AUTH_POD:8080"
POST_URL="http://$POST_POD:8080"
COMMENT_URL="http://$COMMENT_POD:8080"
FRONTEND_URL="http://$FRONTEND_POD:80"

snapshot () { bash "$DIR/db_snapshot.sh" snapshot; }
restore  () {
  # ★ 복원 트래픽은 pcap 에 남지 않는다:
  #   (1) 복원은 이 단계(모든 수집 종료 후)에만 실행 — 각 캡처는 phase 별 `timeout` 으로 이미 종료됨.
  #   (2) 복원은 mysql-0 내부에서 localhost 소켓으로 실행(db_snapshot.sh) → pod eth0 에 트래픽이 없음.
  #       (attacker/benign pod 는 복원과 무관해 애초에 캡처 대상이 아님.)
  echo "[restore] (모든 tcpdump 캡처 종료 확인 후) 스냅샷 시점으로 DB 복원 — 이 트래픽은 캡처되지 않음"
  bash "$DIR/db_snapshot.sh" restore
}

benign () {
  echo "[benign] auth  → $AUTH_URL"
  locust -f "$DIR/benign/auth_locustfile.py"     --host "$AUTH_URL"     --headless $BENIGN_OPTS
  echo "[benign] post  → $POST_URL  (AUTH_HOST=$AUTH_URL)"
  AUTH_HOST="$AUTH_URL" \
    locust -f "$DIR/benign/post_locustfile.py"    --host "$POST_URL"    --headless $BENIGN_OPTS
  echo "[benign] comment → $COMMENT_URL  (AUTH_HOST=$AUTH_URL POST_HOST=$POST_URL)"
  AUTH_HOST="$AUTH_URL" POST_HOST="$POST_URL" \
    locust -f "$DIR/benign/comment_locustfile.py" --host "$COMMENT_URL" --headless $BENIGN_OPTS
  echo "[benign] frontend → $FRONTEND_URL"
  locust -f "$DIR/benign/frontend_locustfile.py" --host "$FRONTEND_URL" --headless $BENIGN_OPTS
  echo "[benign] 완료 (생성된 게시물/댓글은 각 유저 on_stop 에서 삭제됨)"
}

# 공격 규모(ATTACK_*_OPTS): benign 만큼은 아니지만 '시각화(분포 분리 확인)에 충분한' 양을 확보하도록
# 논문 최소치(enum~84·manipulate~108·brute~6.5K)보다 넉넉히 설정. tcpdump 패킷 카운트를 보며 -t 로 가감.
ATTACK_ENUM_OPTS="${ATTACK_ENUM_OPTS:--u 10 -r 2 -t 300s}"
ATTACK_MANIP_OPTS="${ATTACK_MANIP_OPTS:--u 10 -r 2 -t 300s}"
ATTACK_BRUTE_OPTS="${ATTACK_BRUTE_OPTS:--u 20 -r 5 -t 300s}"

attack_enum  () { echo "[attack] enum (T1613)        opts=$ATTACK_ENUM_OPTS";  kubectl -n "$NS" exec "$POD" -- locust -f /mnt/k8s_enum_locustfile.py       --headless $ATTACK_ENUM_OPTS; }
attack_manip () { echo "[attack] manipulate (T1609)  opts=$ATTACK_MANIP_OPTS"; kubectl -n "$NS" exec "$POD" -- locust -f /mnt/k8s_manipulate_locustfile.py --headless $ATTACK_MANIP_OPTS; }
attack_brute () { echo "[attack] bruteforce (T1110)  opts=$ATTACK_BRUTE_OPTS"; kubectl -n "$NS" exec "$POD" -- locust -f /mnt/k8s_bruteforce_locustfile.py --headless $ATTACK_BRUTE_OPTS; }

# attack: 3종 순차. 시각화용 시나리오별 pcap 분리를 원하면 enum|manipulate|brute 를 개별 실행하며 캡처 파일을 교체.
attack () { attack_enum; attack_manip; attack_brute; echo "[attack] 완료"; }

case "${1:-all}" in
  snapshot)    snapshot ;;
  benign)      benign ;;
  attack)      attack ;;
  enum)        attack_enum ;;      # 시나리오 개별 실행(시각화용 pcap 분리)
  manipulate)  attack_manip ;;
  brute)       attack_brute ;;
  restore)     restore ;;
  all)         snapshot; benign; attack; restore ;;
  *) echo "usage: run.sh [all|snapshot|benign|attack|enum|manipulate|brute|restore]"; exit 2 ;;
esac
