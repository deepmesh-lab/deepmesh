#!/usr/bin/env bash
# ============================================================
# capture_docker.sh — Docker Compose 환경용 tcpdump 캡처
# (K8s용 capture.sh 의 Docker 버전)
# ============================================================
# 대상 서비스 컨테이너의 network namespace 에 tcpdump 를 붙여
# eth0(Ethernet 프레임) 을 pcap 으로 저장한다.
#
# ★ 반드시 eth0 에서 캡처한다. `-i any` 는 Linux cooked(SLL) 헤더가 붙어
#   논문 C 파서(Ethernet offset 가정)와 어긋나므로 사용 금지.
#
# 사용법: ./capture_docker.sh <container-name> <duration-sec> [out-dir]
#   예:  ./capture_docker.sh auth-service 60
#        ./capture_docker.sh post-service 60 ./pcap/post
# ============================================================
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <container-name> <duration-sec> [out-dir]"; exit 1
fi

SVC="$1"; DURATION="$2"; OUT_DIR="${3:-./pcap/${SVC}}"
SNIFFER_IMAGE="${SNIFFER_IMAGE:-nicolaka/netshoot}"

if ! docker ps --format '{{.Names}}' | grep -qx "$SVC"; then
  echo "Error: 실행 중인 컨테이너 '$SVC' 를 찾을 수 없음 (docker ps 로 확인)"; exit 1
fi

mkdir -p "$OUT_DIR"
OUT_DIR_ABS="$(cd "$OUT_DIR" && pwd)"
TS="$(date +%Y%m%d_%H%M%S)"
FILE="${SVC}_${TS}.pcap"

echo "[INFO] 대상 컨테이너: $SVC (netns 공유)"
echo "[INFO] 인터페이스: eth0 (Ethernet)"
echo "[INFO] 캡처 시간: ${DURATION}s → ${OUT_DIR_ABS}/${FILE}"

# --net container:<svc> 로 대상 netns 공유, -v 로 결과 pcap 을 호스트에 저장.
# ★ tcpdump -G/-W 는 마감 후 패킷이 와야 종료돼(idle 인터페이스에서 무한 대기).
#   timeout 으로 트래픽 유무와 무관하게 정확히 DURATION 초 후 SIGTERM → tcpdump flush & 종료.
docker run --rm \
  --net "container:${SVC}" \
  -v "${OUT_DIR_ABS}:/cap" \
  "$SNIFFER_IMAGE" \
  timeout "$DURATION" tcpdump -i eth0 -w "/cap/${FILE}" tcp || true

if [[ -f "${OUT_DIR_ABS}/${FILE}" ]]; then
  echo "[SUCCESS] ${OUT_DIR_ABS}/${FILE} ($(du -h "${OUT_DIR_ABS}/${FILE}" | cut -f1))"
else
  echo "Error: pcap 생성 실패"; exit 1
fi
