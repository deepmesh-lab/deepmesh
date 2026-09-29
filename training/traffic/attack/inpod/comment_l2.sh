# 위조 토큰으로 내부 검증 API를 반복 호출
. "$(dirname "$0")/common.sh"
forged() {
  case "$(( $(od -An -N1 -tu1 /dev/urandom) % 3 ))" in
    0) echo "Bearer eyJhbGciOiJub25lIn0.$(od -An -N16 -tx1 /dev/urandom|tr -d ' \n').";;
    1) echo "Bearer eyJhbGciOiJIUzI1NiJ9.$(od -An -N40 -tx1 /dev/urandom|tr -d ' \n').X";;
    *) echo "Bearer replayed_$(od -An -N8 -tx1 /dev/urandom|tr -d ' \n')";;
  esac
}
i=0
while [ "$i" -lt "$N" ]; do
  urls=""; j=0
  while [ "$j" -lt "$BATCH" ] && [ "$i" -lt "$N" ]; do
    urls="$urls $AUTH_URL/internal/auth/validate"; i=$((i+1)); j=$((j+1))
  done
  curl_ew -H "Authorization: $(forged)" $urls >/dev/null 2>&1
  pace
done
echo "[comment_l2] done N=$N BATCH=$BATCH"
