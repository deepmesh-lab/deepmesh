# pod의 outbound TCP 트래픽을 캡처
# 인자: pod, 초, 출력 pcap

set -euo pipefail

POD="$1"; SEC="$2"; OUT="$3"
NS="${NS:-deepmesh}"
CTR="sudo ctr -n k8s.io"

IP="$(kubectl get pod "$POD" -n "$NS" -o jsonpath='{.status.podIP}')"
[ -z "$IP" ] && { echo "pod IP missing: $POD"; exit 1; }

# 컨테이너 PID 조회
CID="$($CTR containers ls | grep "$POD" | awk '{print $1}' | head -n1)"
PID="$($CTR task ls | grep "$CID" | awk '{print $2}' | head -n1)"
[ -z "$PID" ] && { echo "PID missing: $POD/$CID"; exit 1; }

echo "[capture] pod=$POD sec=$SEC out=$OUT"
# offload 비활성화
sudo nsenter -t "$PID" -n ethtool -K eth0 gro off tso off gso off lro off 2>/dev/null || true

sudo timeout "$SEC" nsenter -t "$PID" -n \
    tcpdump -i eth0 -s 0 "tcp and src host $IP" -w "$OUT"
echo "[capture] done out=$OUT"
