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

iptables -t nat -F PREROUTING
iptables -t nat -F OUTPUT

# ── ingress ────────────────────────────────────────────────────────────────
iptables -t nat -A PREROUTING -p tcp --dport "$TARGET_PORT" -j REDIRECT --to-port "$PROXY_PORT"

# ── egress ─────────────────────────────────────────────────────────────────
# 프록시가 전달하는 트래픽이 다시 프록시로 돌아오지 않게 uid를 먼저 제외한다
iptables -t nat -A OUTPUT -m owner --uid-owner "$PROXY_UID" -j RETURN
# 프록시 ↔ 메인 컨테이너 구간(loopback)은 리다이렉트 대상이 아니다
iptables -t nat -A OUTPUT -o lo -j RETURN
iptables -t nat -A OUTPUT -p tcp -j REDIRECT --to-port "$PROXY_PORT"

echo "iptables 설정 완료 (proxy=$PROXY_PORT, target=$TARGET_PORT, uid=$PROXY_UID)"
