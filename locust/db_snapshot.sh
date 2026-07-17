#!/usr/bin/env bash
# db_snapshot.sh — 수집 전/후 DB 스냅샷·복원으로 net-zero (기존 데이터 보존 방식).
#
# 왜 스냅샷·복원인가: truncate 는 수집 전에 존재하던 데이터까지 지운다. 스냅샷·복원은
#   '수집 시작 시점의 DB 상태'를 그대로 저장했다가 수집 후 되돌리므로, 사전 데이터를 보존하면서
#   수집 중 추가된 것(사용자/게시물/댓글)만 정확히 제거한다.
#
# 사용:
#   # (1) 전체 수집 시작 '전에' — 현재 DB 상태를 스냅샷으로 저장
#   bash locust/db_snapshot.sh snapshot
#   # (2) 전체 수집(benign+attack) 종료 후 — 스냅샷 시점으로 복원
#   bash locust/db_snapshot.sh restore
#
# 스냅샷 파일 위치: 기본 $(스크립트 폴더)/db_snapshot.sql, 환경변수 SNAPSHOT_FILE 로 변경 가능.
# 전제: mysql-0(StatefulSet)에 kubectl 로 접근 가능. 앱이 기동돼 테이블이 이미 생성된 상태에서 스냅샷을 뜬다.

set -uo pipefail
NS="${NS:-deepmesh}"
SNAP="${SNAPSHOT_FILE:-$(cd "$(dirname "$0")" && pwd)/db_snapshot.sql}"

case "${1:-}" in
  snapshot)
    echo "[snapshot] auth_db posts_db comments_db → $SNAP"
    # --add-drop-table(기본): 복원 시 각 테이블 DROP 후 재생성 → 수집 중 변경분 정확히 폐기됨
    kubectl -n "$NS" exec mysql-0 -- sh -c \
      'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --databases auth_db posts_db comments_db --single-transaction --routines --triggers --add-drop-table' \
      > "$SNAP"
    if [ -s "$SNAP" ]; then
      echo "[snapshot] 완료: $(wc -c < "$SNAP") bytes 저장"
    else
      echo "[snapshot] 실패: 스냅샷이 비어 있음(자격증명/DB 확인)"; rm -f "$SNAP"; exit 1
    fi
    ;;
  restore)
    [ -s "$SNAP" ] || { echo "[restore] 스냅샷 파일 없음/빈 파일: $SNAP — 먼저 'snapshot' 을 실행해야 함"; exit 1; }
    echo "[restore] $SNAP → DB 복원(수집 전 상태로)"
    # mysql 클라이언트는 mysql-0 내부에서 기본 localhost 소켓으로 접속 → pod eth0 에 트래픽이 없어
    # (설령 캡처가 남아 있어도) 복원 트래픽은 pcap 에 잡히지 않는다.
    kubectl -n "$NS" exec -i mysql-0 -- sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' < "$SNAP"
    echo "[restore] 검증(수집 전 카운트와 일치해야 함):"
    kubectl -n "$NS" exec -i mysql-0 -- sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SELECT (SELECT COUNT(*) FROM auth_db.users) users, (SELECT COUNT(*) FROM auth_db.refresh_tokens) refresh_tokens, (SELECT COUNT(*) FROM posts_db.posts) posts, (SELECT COUNT(*) FROM comments_db.comments) comments;"'
    echo "[restore] 완료 — 서비스 상태를 스냅샷 시점으로 복원"
    ;;
  *)
    echo "usage: db_snapshot.sh [snapshot|restore]"; exit 2 ;;
esac
