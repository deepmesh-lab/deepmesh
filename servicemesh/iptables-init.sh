#!/bin/sh
# iptables 규칙 (논문 §5.1: ingress/egress 모두 프록시로 리다이렉트)
#
# 위협모델(lateral movement)은 main container 에서 나가는 outbound 내부요청을 잡아야 하므로
# ingress(8080→9011) 뿐 아니라 egress 도 프록시로 리다이렉트한다.
# 프록시 자신(uid 1337)과 루프백은 제외해 리다이렉트 루프를 막는다.
set -e

PROXY_PORT="${PROXY_PORT:-9011}"
TARGET_PORT="${TARGET_PORT:-8080}"

iptables -t nat -F PREROUTING
iptables -t nat -F OUTPUT

# ── ingress: 서비스(8080)로 오는 트래픽을 프록시로 ─────────────────────────
iptables -t nat -A PREROUTING -p tcp --dport "$TARGET_PORT" -j REDIRECT --to-port "$PROXY_PORT"

# ── egress: 프록시 자신/루프백은 제외, 나머지 outbound 를 프록시로 ─────────
iptables -t nat -I OUTPUT -m owner --uid-owner 1337 -j RETURN
iptables -t nat -I OUTPUT -o lo -j RETURN
iptables -t nat -A OUTPUT -p tcp --dport "$TARGET_PORT" -j REDIRECT --to-port "$PROXY_PORT"
