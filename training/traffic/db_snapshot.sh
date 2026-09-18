# DB 상태를 저장하거나 복원
# 인자: snapshot 또는 restore

set -uo pipefail
NS="${NS:-deepmesh}"
SNAP="${SNAPSHOT_FILE:-$(cd "$(dirname "$0")" && pwd)/db_snapshot.sql}"

case "${1:-}" in
  snapshot)
    echo "[snapshot] save $SNAP"
    kubectl -n "$NS" exec mysql-0 -- sh -c \
      'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --databases auth_db posts_db comments_db --single-transaction --routines --triggers --add-drop-table' \
      > "$SNAP"
    if [ -s "$SNAP" ]; then
      echo "[snapshot] done bytes=$(wc -c < "$SNAP")"
    else
      echo "[snapshot] failed"; rm -f "$SNAP"; exit 1
    fi
    ;;
  restore)
    [ -s "$SNAP" ] || { echo "[restore] snapshot missing: $SNAP"; exit 1; }
    echo "[restore] load $SNAP"
    kubectl -n "$NS" exec -i mysql-0 -- sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' < "$SNAP"
    echo "[restore] verify"
    kubectl -n "$NS" exec -i mysql-0 -- sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SELECT (SELECT COUNT(*) FROM auth_db.users) users, (SELECT COUNT(*) FROM auth_db.refresh_tokens) refresh_tokens, (SELECT COUNT(*) FROM posts_db.posts) posts, (SELECT COUNT(*) FROM comments_db.comments) comments;"'
    echo "[restore] done"
    ;;
  *)
    echo "usage: snapshot|restore"; exit 2 ;;
esac
