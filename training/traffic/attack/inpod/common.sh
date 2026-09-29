# 공격 스크립트의 주소, pacing, 요청 헤더를 공유

# 서비스 주소
AUTH_URL="${AUTH_URL:-http://auth-service:8080}"
POST_URL="${POST_URL:-http://post-service:8080}"
COMMENT_URL="${COMMENT_URL:-http://comment-service:8080}"
FRONTEND_URL="${FRONTEND_URL:-http://frontend:80}"
MYSQL_HOST="${MYSQL_HOST:-mysql-service}"
MYSQL_PORT="${MYSQL_PORT:-3306}"

# pacing
PACE_MS="${PACE_MS:-200}"
PACE_JITTER="${PACE_JITTER:-150}"
pace() {
    j=$(( $(od -An -N2 -tu2 /dev/urandom) % (PACE_JITTER + 1) ))
    ms=$(( PACE_MS + j ))
    sleep "$(awk "BEGIN{printf \"%.3f\", $ms/1000}")"
}
pace_slow() { sleep "$(awk "BEGIN{printf \"%.3f\", (800 + $(od -An -N2 -tu2 /dev/urandom)%400)/1000}")"; }
is_slow() { [ "${SLOW:-0}" = "1" ]; }
N="${N:-40}"
# 한 연결에서 보낼 요청 수
BATCH="${BATCH:-20}"

# 요청 헤더
ORIGIN="${ORIGIN:-http://dev-server:31403}"
BROWSER_UA="${BROWSER_UA:-Mozilla/5.0 (X11; Linux x86_64) DeepMeshClient/1.0}"
BROWSER_ACCEPT="${BROWSER_ACCEPT:-application/json, text/html;q=0.9, */*;q=0.8}"
EW_UA="${EW_UA:-Apache-HttpClient/5.3.1 (Java/17.0.9)}"
EW_ACCEPT="${EW_ACCEPT:-application/json, application/*+json}"

# 공개 API 요청
curl_browser() {
    curl -s -A "$BROWSER_UA" -H "Accept: $BROWSER_ACCEPT" -H "Accept-Language: en-US,en;q=0.9" \
         -H "Origin: $ORIGIN" "$@"
}
# 내부 API 요청
curl_ew() {
    curl -s -A "$EW_UA" -H "Accept: $EW_ACCEPT" "$@"
}
# CORS preflight 요청
preflight_browser() {
    if [ -n "$3" ]; then
        curl -s -o /dev/null -X OPTIONS -A "$BROWSER_UA" -H "Accept: */*" -H "Origin: $ORIGIN" \
             -H "Access-Control-Request-Method: $1" -H "Access-Control-Request-Headers: $3" "$2"
    else
        curl -s -o /dev/null -X OPTIONS -A "$BROWSER_UA" -H "Accept: */*" -H "Origin: $ORIGIN" \
             -H "Access-Control-Request-Method: $1" "$2"
    fi
}

# Kubernetes API 설정
SA_DIR="${SA_DIR:-/var/run/secrets/kubernetes.io/serviceaccount}"
get_sa_token() { cat "$SA_DIR/token" 2>/dev/null; }
CACERT="${CACERT:-$SA_DIR/ca.crt}"
APISERVER="${APISERVER:-https://${KUBERNETES_SERVICE_HOST:-kubernetes.default.svc}:${KUBERNETES_SERVICE_PORT_HTTPS:-443}}"
