# 계정 열거와 로그인 시도를 반복
. "$(dirname "$0")/common.sh"
USERS="admin user1 user2 user3 test guest manager operator root service"
preflight_browser POST "$AUTH_URL/api/auth/login" "content-type"
rndpw() { echo "guess$(od -An -N2 -tu2 /dev/urandom|tr -d ' ')"; }
i=0
while [ "$i" -lt "$N" ]; do
  set --
  j=0
  for u in $USERS; do
    [ "$j" -ge "$BATCH" ] && break
    [ "$i" -ge "$N" ] && break
    body="{\"username\":\"$u\",\"password\":\"$(rndpw)\"}"
    set -- "$@" --next -A "$BROWSER_UA" -H "Accept: $BROWSER_ACCEPT" -H "Origin: $ORIGIN" \
           -H "Content-Type: application/json" -d "$body" "$AUTH_URL/api/auth/login"
    i=$((i+1)); j=$((j+1))
  done
  if [ "$#" -gt 0 ]; then shift; curl -s "$@" >/dev/null 2>&1; fi
  pace
done
echo "[auth_cred_enum] done N=$N BATCH=$BATCH"
