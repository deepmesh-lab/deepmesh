#!/bin/sh
# Pod 네트워크를 프록시로 우회시킨다 (initContainer에서 NET_ADMIN 권한으로 실행).
#
#   ingress: 메인 컨테이너 포트로 들어오는 트래픽을 프록시로
#   egress : 메인 컨테이너가 내보내는 모든 TCP를 프록시로
#
# 위협 모델이 lateral movement이므로 egress를 특정 포트로 좁히면 안 된다. K8s API(443)나
# DB(3306) 같은 목적지가 빠지면 데모 시나리오 1(K8s API 무단 호출)이 잡히지 않는다.
#
# 프록시 자신(uid 1337)과 loopback은 제외해 리다이렉트 루프를 막는다.
set -e

PROXY_PORT="${PROXY_PORT:-9011}"
TARGET_PORT="${TARGET_PORT:-8080}"
PROXY_UID="${PROXY_UID:-1337}"
# 프록시를 거치지 않고 그대로 내보낼 목적지 포트. 아래 EXEMPT_PORTS 주석 참고.
EXEMPT_PORTS="${EXEMPT_PORTS:-3306}"

iptables -t nat -F PREROUTING
iptables -t nat -F OUTPUT

# ── ingress ────────────────────────────────────────────────────────────────
iptables -t nat -A PREROUTING -p tcp --dport "$TARGET_PORT" -j REDIRECT --to-port "$PROXY_PORT"

# ── egress ─────────────────────────────────────────────────────────────────
# 프록시가 전달하는 트래픽이 다시 프록시로 돌아오지 않게 uid를 먼저 제외한다
iptables -t nat -A OUTPUT -m owner --uid-owner "$PROXY_UID" -j RETURN
# 프록시 ↔ 메인 컨테이너 구간(loopback)은 리다이렉트 대상이 아니다
iptables -t nat -A OUTPUT -o lo -j RETURN

# 비HTTP 프로토콜은 프록시를 거치지 않는다.
#
# Traffic Handler는 HTTP/1.1 파서다. MySQL 같은 바이너리 프로토콜이 들어오면 핸드셰이크가
# 응답을 못 받아 메인 컨테이너가 기동에 실패한다(mysql-connector의 readMessage에서 멈춘다).
#
# 대가로 이 포트의 트래픽은 탐지에서도 빠진다 — 탐지 경로가 lo만 캡처하는데(SNIFF_IFACE),
# 리다이렉트되지 않으면 lo를 거치지 않기 때문이다. 다만 post·comment 컨버터는 :3306을
# 원래 탐지 대상에서 제외하고 있어(NEVER_BENIGN_FLOW_PORTS 밖) 실질 손실이 없다. auth는
# 모든 egress를 이미지화하므로 d1(mysql) 시나리오를 잃는데, 그 시나리오를 쓰지 않기로
# 했다.
#
# 되살리려면 프록시가 첫 바이트로 HTTP 여부를 판별해 비HTTP는 raw TCP로 릴레이하도록
# 고치면 된다. 그러면 이 예외가 필요 없어지고 탐지도 그대로 남는다.
for port in $EXEMPT_PORTS; do
  iptables -t nat -A OUTPUT -p tcp --dport "$port" -j RETURN
done

iptables -t nat -A OUTPUT -p tcp -j REDIRECT --to-port "$PROXY_PORT"

echo "iptables 설정 완료 (proxy=$PROXY_PORT, target=$TARGET_PORT, uid=$PROXY_UID, exempt=$EXEMPT_PORTS)"
