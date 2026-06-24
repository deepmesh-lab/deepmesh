#!/usr/bin/env bash
# ============================================================
# capture.sh — K8s Pod tcpdump 패킷 캡처 스크립트
# ============================================================
# 사용법: ./capture.sh <service-name> <duration-seconds> [output-dir]
#
# 예시:
#   ./capture.sh auth-service 300
#   ./capture.sh post-service 300 ./pcap/post
#   ./capture.sh comment-service 120 ./pcap/comment
# ============================================================

set -euo pipefail

# ── 인자 검증 ─────────────────────────────────────────────
if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <service-name> <duration-seconds> [output-dir]"
  echo ""
  echo "Examples:"
  echo "  $0 auth-service 300"
  echo "  $0 post-service 300 ./pcap/post"
  echo "  $0 comment-service 120 ./pcap/comment"
  exit 1
fi

SERVICE="$1"
DURATION="$2"
OUTPUT_DIR="${3:-./pcap/${SERVICE}}"

# ── duration이 숫자인지 확인 ───────────────────────────────
if ! [[ "$DURATION" =~ ^[0-9]+$ ]]; then
  echo "Error: duration-seconds must be a positive integer (got: '$DURATION')"
  exit 1
fi

# ── K8s에서 실행 중인 Pod 가져오기 ────────────────────────
echo "[INFO] Namespace 'deepmesh'에서 app=${SERVICE} Pod를 검색합니다..."

POD=$(kubectl get pods \
  -n deepmesh \
  -l "app=${SERVICE}" \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

if [[ -z "$POD" ]]; then
  echo "Error: namespace 'deepmesh'에서 app=${SERVICE}로 실행 중인 Pod를 찾을 수 없습니다."
  echo "  kubectl get pods -n deepmesh -l app=${SERVICE}  로 상태를 확인하세요."
  exit 1
fi

echo "[INFO] 대상 Pod: $POD"

# ── output 디렉토리 준비 ───────────────────────────────────
mkdir -p "$OUTPUT_DIR"

# ── 타임스탬프 기반 파일명 ─────────────────────────────────
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTFILE="${OUTPUT_DIR}/${SERVICE}_${TIMESTAMP}.pcap"

echo "[INFO] 출력 파일: $OUTFILE"
echo "[INFO] 캡처 시간: ${DURATION}초"

# ── tcpdump 설치 여부 확인 ─────────────────────────────────
if ! kubectl exec -n deepmesh "$POD" -- which tcpdump >/dev/null 2>&1; then
  echo "Error: Pod '$POD'에 tcpdump가 설치되어 있지 않습니다."
  echo ""
  echo "  Debian/Ubuntu 계열 이미지라면 Dockerfile에 아래를 추가하세요:"
  echo "    RUN apt-get update && apt-get install -y tcpdump"
  echo ""
  echo "  또는 실행 중인 Pod에 임시 설치:"
  echo "    kubectl exec -n deepmesh $POD -- apt-get install -y tcpdump"
  exit 1
fi

# ── tcpdump 실행 (백그라운드) ──────────────────────────────
echo "[INFO] tcpdump 캡처 시작..."

kubectl exec -n deepmesh "$POD" -- \
  tcpdump -i any -w /tmp/capture.pcap -G "$DURATION" -W 1 2>/dev/null &
TCPDUMP_PID=$!

# ── 캡처 완료 대기 ─────────────────────────────────────────
sleep "$DURATION"
wait "$TCPDUMP_PID" || true

echo "[INFO] 캡처 완료. Pod에서 로컬로 파일을 복사합니다..."

# ── Pod → 로컬 복사 ────────────────────────────────────────
kubectl cp "deepmesh/${POD}:/tmp/capture.pcap" "$OUTFILE"

# ── 결과 출력 ──────────────────────────────────────────────
if [[ -f "$OUTFILE" ]]; then
  FILE_SIZE=$(du -sh "$OUTFILE" | cut -f1)
  echo "[SUCCESS] 캡처 완료!"
  echo "  파일: $OUTFILE"
  echo "  크기: $FILE_SIZE"
else
  echo "Error: 파일 복사에 실패했습니다. ($OUTFILE)"
  exit 1
fi

# ============================================================
# 사용 예시
# ============================================================
#
# 1. 단일 서비스 캡처 (기본 출력 경로: ./pcap/<service-name>/)
#    ./capture.sh auth-service 300
#
# 2. 출력 디렉토리 지정
#    ./capture.sh post-service 300 ./pcap/post
#
# 3. 여러 서비스 동시 캡처 (별도 터미널에서 실행)
#    Terminal 1: ./capture.sh auth-service 300
#    Terminal 2: ./capture.sh post-service 300
#    Terminal 3: ./capture.sh comment-service 300
#
# 4. Locust와 병행 실행 예시
#    locust -f locust/auth_locustfile.py \
#      --host http://<NODE_IP>:30080 \
#      --users 20 --spawn-rate 4 --run-time 300s --headless &
#    ./capture.sh auth-service 300
# ============================================================
