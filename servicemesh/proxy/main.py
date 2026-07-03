"""
Sidecar Proxy 엔트리포인트 (경로 A: 투명 TCP 프록시 + AF_PACKET 스니퍼)

논문 Algorithm 1 (Traffic Processing and Intrusion Detection) 이식:
  - SessionSniffer(별도 스레드): 프레임 캡처 → KD-CNN+OCSVM → verdict_map[session_id] 갱신
  - 투명 프록시(asyncio): iptables 로 리다이렉트된 연결을 받아 원 목적지로 중계.
    연결의 session_id 로 verdict_map 을 조회해:
      · 정상/판정없음        → Forward (그대로 중계)
      · 이상 & request       → Control Plane VerifyRequest → invalid 면 Drop, valid 면 Forward
      · 이상 & response      → (시연 우선순위 낮음) 현재는 Forward + 로깅 (relay 는 TODO)
  - /receive/pods_ip: Control Plane 이 push 하는 동료 pod 목록 수신

환경변수:
  TARGET_PORT=8080        메인 컨테이너(백엔드) 포트
  PROXY_PORT=9011         프록시 리스닝 포트
  POD_IP                  현재 pod IP (fieldRef 주입)
  SERVICE_NAME
  CONTROL_PLANE_URL       http://control-plane-service.deepmesh:8080
  MODEL_DIR=/app/model
  PARSER_SO=/app/packet_parser_stack.so
  SNIFF_IFACE             캡처 인터페이스(미지정 시 모든 인터페이스)
"""

import asyncio
import hashlib
import json
import logging
import os
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import aiohttp

from proxy_detection import AnomalyDetector, SessionSniffer, compute_session_id, IPPROTO_TCP

try:
    import uvloop  # Linux/컨테이너
except ImportError:
    uvloop = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("proxy")

TARGET_PORT = int(os.environ.get("TARGET_PORT", 8080))
PROXY_PORT = int(os.environ.get("PROXY_PORT", 9011))
POD_IP = os.environ.get("POD_IP", "127.0.0.1")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "unknown")
CONTROL_PLANE_URL = os.environ.get(
    "CONTROL_PLANE_URL", "http://control-plane-service.deepmesh:8080"
).rstrip("/")
MODEL_DIR = os.environ.get("MODEL_DIR", "/app/model")
PARSER_SO = os.environ.get("PARSER_SO", "/app/packet_parser_stack.so")
SNIFF_IFACE = os.environ.get("SNIFF_IFACE") or None

SO_ORIGINAL_DST = 80  # linux/netfilter_ipv4.h

# 동료 pod 목록 (Control Plane 이 push). relay 대상.
_peer_pods: list[dict] = []
_peer_lock = threading.Lock()

# 탐지기 + 스니퍼 (전역: 스니퍼 스레드와 프록시 코루틴이 공유)
detector = AnomalyDetector(MODEL_DIR, PARSER_SO)
sniffer = SessionSniffer(detector, iface=SNIFF_IFACE)


# ---------------------------------------------------------------------------
# 투명 프록시
# ---------------------------------------------------------------------------

def _get_original_dst(sock: socket.socket) -> tuple[str, int]:
    """iptables REDIRECT 된 연결의 원 목적지(SO_ORIGINAL_DST)."""
    data = sock.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
    dst_port, raw_ip = struct.unpack("!2xH4s8x", data)
    return socket.inet_ntoa(raw_ip), dst_port


def _signature_data(first_chunk: bytes) -> str:
    """
    cross-replica 검증 키. 평문 HTTP 요청의 첫 청크에서
    "METHOD PATH sha256(body)" 형태의 정규화 시그니처를 만든다.
    토큰/타임스탬프 등 가변 헤더는 제외(요청라인+바디해시만 사용).
    """
    try:
        head, _, body = first_chunk.partition(b"\r\n\r\n")
        request_line = head.split(b"\r\n", 1)[0].decode("latin1", "replace")
        parts = request_line.split(" ")
        method = parts[0] if parts else ""
        path = parts[1] if len(parts) > 1 else ""
        body_hash = hashlib.sha256(body).hexdigest()[:16]
        return f"{method} {path} {body_hash}"
    except Exception:
        return hashlib.sha256(first_chunk).hexdigest()[:32]


async def _verify_with_control_plane(signature_data: str) -> bool:
    """
    Control Plane cross-replica 검증. 다른 replica 에서도 관측된 요청이면 valid(=허용).
    타임아웃/오류 시 보수적으로 False(=drop). 반환 True=forward, False=drop.
    """
    url = f"{CONTROL_PLANE_URL}/send/internal_request_body"
    payload = {"pod_ip": POD_IP, "signature_data": signature_data}
    try:
        timeout = aiohttp.ClientTimeout(total=2.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                return data.get("result") == "valid"
    except Exception as exc:
        logger.error("Control Plane 검증 실패(%s) → drop 처리", exc)
        return False


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        while not reader.at_eof():
            data = await reader.read(65535)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle_client(client_reader: asyncio.StreamReader,
                        client_writer: asyncio.StreamWriter):
    peer = client_writer.get_extra_info("peername")
    sock = client_writer.get_extra_info("socket")
    remote_writer = None
    try:
        # 원 목적지 확인 (없으면 로컬 백엔드로 간주)
        try:
            dst_ip, dst_port = _get_original_dst(sock)
        except Exception:
            dst_ip, dst_port = "127.0.0.1", TARGET_PORT

        src_ip_i = int.from_bytes(socket.inet_aton(peer[0]), "big")
        dst_ip_i = int.from_bytes(socket.inet_aton(dst_ip), "big")
        session_id = compute_session_id(src_ip_i, dst_ip_i, peer[1], dst_port,
                                        IPPROTO_TCP, detector.MAX_SESSIONS)

        # 방향 판별: 출발지가 이 pod 이면 main container 발(=request), 아니면 인바운드
        is_outbound_request = (peer[0] == POD_IP)

        # 첫 청크 확보(시그니처 생성 + 목적지로 전달)
        first_chunk = await client_reader.read(65535)
        verdict = sniffer.get_verdict(session_id)

        action = "forward"
        if verdict is not None and verdict.is_malicious:
            if is_outbound_request:
                sig = _signature_data(first_chunk)
                allowed = await _verify_with_control_plane(sig)
                action = "forward" if allowed else "drop"
                logger.warning("이상 request: sid=%d score=%.4f sig=%r → %s",
                               session_id, verdict.score, sig, action)
            else:
                # response 이상: relay(다른 replica 응답으로 교체)는 TODO. 현재는 통과+로깅.
                action = "forward"
                logger.warning("이상 response(통과): sid=%d score=%.4f",
                               session_id, verdict.score)

        if action == "drop":
            client_writer.close()
            return

        # Forward: 목적지 연결 후 양방향 파이프
        target_ip = "127.0.0.1" if dst_ip == POD_IP else dst_ip
        remote_reader, remote_writer = await asyncio.open_connection(target_ip, dst_port)
        if first_chunk:
            remote_writer.write(first_chunk)
            await remote_writer.drain()

        await asyncio.gather(
            _pipe(client_reader, remote_writer),
            _pipe(remote_reader, client_writer),
        )
    except Exception as exc:
        logger.debug("연결 처리 오류: %s", exc)
    finally:
        for w in (remote_writer, client_writer):
            if w is not None:
                try:
                    w.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# /receive/pods_ip 수신 (Control Plane push)
# ---------------------------------------------------------------------------

class PodsIPHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path != "/receive/pods_ip":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
            with _peer_lock:
                global _peer_pods
                _peer_pods = data.get("pods_ip", [])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        except Exception:
            self.send_response(400)
            self.end_headers()


def _start_pods_ip_listener():
    # 프록시 포트 + 1 에서 동료 pod 목록 수신 (iptables 는 PROXY_PORT 만 리다이렉트)
    port = PROXY_PORT + 1
    srv = HTTPServer(("0.0.0.0", port), PodsIPHandler)
    threading.Thread(target=srv.serve_forever, name="pods-ip-listener", daemon=True).start()
    logger.info("pods_ip 리스너 시작 :%d", port)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def _serve():
    server = await asyncio.start_server(handle_client, host="0.0.0.0", port=PROXY_PORT)
    logger.info("투명 프록시 리스닝 :%d (service=%s, pod=%s)", PROXY_PORT, SERVICE_NAME, POD_IP)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    sniffer.start()
    _start_pods_ip_listener()
    if uvloop is not None:
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        sniffer.stop()
