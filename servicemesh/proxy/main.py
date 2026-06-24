"""
Sidecar Proxy 서버 — port 9011

환경변수:
  TARGET_PORT=8080       실제 서비스 포트
  PROXY_PORT=9011        Proxy 리스닝 포트
  POD_IP                 현재 Pod IP (K8s fieldRef로 주입)
  SERVICE_NAME           서비스 이름
  CONTROL_PLANE_URL      http://control-plane-service.deepmesh:8080
  MODEL_DIR=/app/model   Student + OCSVM 모델 위치
"""

import json
import logging
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from proxy_detection import ProxyHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 환경변수
TARGET_PORT = int(os.environ.get("TARGET_PORT", 8080))
PROXY_PORT = int(os.environ.get("PROXY_PORT", 9011))
POD_IP = os.environ.get("POD_IP", "127.0.0.1")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "unknown")
CONTROL_PLANE_URL = os.environ.get(
    "CONTROL_PLANE_URL", "http://control-plane-service.deepmesh:8080"
)
MODEL_DIR = os.environ.get("MODEL_DIR", "/app/model")

TARGET_HOST = f"http://localhost:{TARGET_PORT}"

# ProxyHandler 초기화 (모델 로드)
proxy_handler = ProxyHandler(
    target_host=TARGET_HOST,
    control_plane_url=CONTROL_PLANE_URL,
    model_dir=MODEL_DIR,
)


class ProxyHTTPHandler(BaseHTTPRequestHandler):
    """인바운드 요청을 처리해 forward / relay / drop 결정."""

    def log_message(self, format, *args):
        # BaseHTTPRequestHandler 기본 로그는 억제하고 커스텀 로거 사용
        pass

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def _handle(self):
        """요청을 처리하고 ProxyHandler 결정에 따라 응답."""
        # 1. 요청 바디 읽기
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""

        # 헤더를 dict로 변환
        headers_dict = dict(self.headers)

        # 2. ProxyHandler로 action 결정
        result = proxy_handler.handle(body_bytes, headers_dict)
        action = result["action"]
        reason = result["reason"]

        logger.info(
            "service=%s pod=%s method=%s path=%s action=%s reason=%s",
            SERVICE_NAME,
            POD_IP,
            self.command,
            self.path,
            action,
            reason,
        )

        # 3. action에 따른 처리
        if action == "relay":
            peer_ips = result.get("peer_ips", [])
            if peer_ips:
                target = f"http://{peer_ips[0]}:{TARGET_PORT}"
            else:
                target = TARGET_HOST
            self._proxy_to_target(body_bytes, headers_dict, target)
        elif action == "forward":
            self._proxy_to_target(body_bytes, headers_dict, TARGET_HOST)
        else:
            # action == "drop"
            self._send_blocked_response()

    def _proxy_to_target(self, body_bytes: bytes, headers_dict: dict, target: str = None):
        """실제 서비스로 요청을 프록싱. target 미지정 시 TARGET_HOST 사용."""
        if target is None:
            target = TARGET_HOST
        target_url = f"{target}{self.path}"

        # 프록싱 시 hop-by-hop 헤더 제거
        _HOP_BY_HOP = {
            "connection", "keep-alive", "proxy-authenticate",
            "proxy-authorization", "te", "trailers",
            "transfer-encoding", "upgrade",
        }
        forward_headers = {
            k: v
            for k, v in headers_dict.items()
            if k.lower() not in _HOP_BY_HOP
        }

        req = urllib.request.Request(
            url=target_url,
            data=body_bytes if body_bytes else None,
            headers=forward_headers,
            method=self.command,
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for header, value in resp.getheaders():
                    if header.lower() not in _HOP_BY_HOP:
                        self.send_header(header, value)
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            resp_body = e.read()
            self.send_response(e.code)
            for header, value in e.headers.items():
                if header.lower() not in _HOP_BY_HOP:
                    self.send_header(header, value)
            self.end_headers()
            self.wfile.write(resp_body)
        except Exception as exc:
            logger.error("업스트림 요청 오류: %s", exc)
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": "bad gateway"}).encode("utf-8")
            )

    def _send_blocked_response(self):
        """침입 탐지 차단 시 403 응답."""
        body = json.dumps(
            {"error": "request blocked by intrusion detection"}
        ).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.environ.get("PROXY_PORT", 9011))
    server = HTTPServer(("0.0.0.0", port), ProxyHTTPHandler)
    logger.info("Proxy listening on :%d (service=%s)", port, SERVICE_NAME)
    server.serve_forever()
