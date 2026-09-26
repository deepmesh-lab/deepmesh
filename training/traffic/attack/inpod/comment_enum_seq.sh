# postId를 증가시키며 댓글 목록을 조회
. "$(dirname "$0")/common.sh"

START_ID="${START_ID:-1}"
i=0; id="$START_ID"
while [ "$i" -lt "$N" ]; do
  curl_browser -o /dev/null "$COMMENT_URL/api/comments/$id/comments?size=10"
  pace; id=$((id+1)); i=$((i+1))
done
echo "[comment_enum_seq] done N=$N start=$START_ID"
