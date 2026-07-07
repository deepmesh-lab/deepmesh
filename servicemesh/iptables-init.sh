#!/bin/sh
# iptables 규칙: 인바운드 8080 → 9011로 리다이렉션 (proxy 컨테이너 제외)
iptables -t nat -A PREROUTING -p tcp --dport 8080 -j REDIRECT --to-port 9011
# 루프백은 제외 (proxy 자신이 서비스로 보내는 요청)
iptables -t nat -A OUTPUT -p tcp --dport 8080 -m owner --uid-owner 1337 -j RETURN
