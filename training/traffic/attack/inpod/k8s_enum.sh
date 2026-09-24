# Kubernetes 리소스와 권한을 반복 조회
. "$(dirname "$0")/common.sh"

TOKEN="$(get_sa_token)"
NS="${NS:-default}"
N="${N:-100}"
[ -z "$TOKEN" ] && echo "[k8s_enum] token missing" >&2

i=0
while [ "$i" -lt "$N" ]; do
  curl -sk -o /dev/null -H "Authorization: Bearer $TOKEN" "$APISERVER/api/v1/namespaces/$NS/pods"
  curl -sk -o /dev/null -H "Authorization: Bearer $TOKEN" "$APISERVER/api/v1/namespaces/$NS/secrets"
  curl -sk -o /dev/null -H "Authorization: Bearer $TOKEN" -X POST \
     -H "Content-Type: application/json" \
     "$APISERVER/apis/authorization.k8s.io/v1/selfsubjectrulesreviews" \
     -d '{"kind":"SelfSubjectRulesReview","apiVersion":"authorization.k8s.io/v1","spec":{"namespace":"'"$NS"'"}}'
  if is_slow; then pace_slow; else pace; fi
  i=$((i+1))
done
echo "[k8s_enum] done N=$N"
