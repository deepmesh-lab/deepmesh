# Kubernetes 리소스 변경을 dry-run으로 반복 요청
. "$(dirname "$0")/common.sh"

TOKEN="$(get_sa_token)"
NS="${NS:-default}"
N="${N:-60}"
DRYRUN="${DRYRUN:-All}"
[ -z "$TOKEN" ] && echo "[k8s_manipulate] token missing" >&2

# dry-run pod 명세
POD_JSON='{"apiVersion":"v1","kind":"Pod","metadata":{"name":"atk-probe","namespace":"'"$NS"'"},
"spec":{"containers":[{"name":"c","image":"busybox","command":["sleep","3600"]}]}}'

q() { [ -n "$DRYRUN" ] && echo "?dryRun=$DRYRUN" || echo ""; }

i=0
while [ "$i" -lt "$N" ]; do
  curl -sk -o /dev/null -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    "$APISERVER/api/v1/namespaces/$NS/pods$(q)" -d "$POD_JSON"
  curl -sk -o /dev/null -X DELETE -H "Authorization: Bearer $TOKEN" \
    "$APISERVER/api/v1/namespaces/$NS/pods/atk-probe$(q)"
  curl -sk -o /dev/null -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    "$APISERVER/api/v1/namespaces/$NS/configmaps$(q)" \
    -d '{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"atk-cm"},"data":{"x":"y"}}'
  if is_slow; then pace_slow; else pace; fi
  i=$((i+1))
done
echo "[k8s_manipulate] done N=$N dryRun=$DRYRUN"
