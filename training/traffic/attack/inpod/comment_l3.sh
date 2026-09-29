# postId를 증가시키며 존재 확인과 댓글 삭제를 반복
. "$(dirname "$0")/common.sh"
START_ID="${START_ID:-1}"; pid="$START_ID"; i=0
while [ "$i" -lt "$N" ]; do
  eurls=""; durls=""; j=0
  while [ "$j" -lt "$BATCH" ] && [ "$i" -lt "$N" ]; do
    eurls="$eurls $POST_URL/internal/posts/$pid/exists"
    durls="$durls $COMMENT_URL/internal/posts/$pid/comments"
    pid=$((pid+1)); i=$((i+1)); j=$((j+1))
  done
  curl_ew $eurls >/dev/null 2>&1
  curl_ew -X DELETE $durls >/dev/null 2>&1
  pace
done
echo "[comment_l3] done N=$N BATCH=$BATCH start=$START_ID"
