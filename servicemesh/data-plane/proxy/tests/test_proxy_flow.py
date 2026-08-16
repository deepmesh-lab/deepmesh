# -*- coding: utf-8 -*-
"""집행 경로 — Algorithm 1 line 9~26을 실제 소켓 위에서 검증한다.

이상 판정은 ScriptedDetector 대신 VerdictStore에 직접 넣는다. 여기서 확인하려는 것은
'이상으로 판정됐을 때 Relay/Drop/Forward가 규칙대로 갈리는가'이지 탐지 자체가 아니다.
"""

import asyncio
import json

from traffic_handler import http_message
from traffic_handler.peers import PeerRegistry
from traffic_handler.ports import Detection, SessionKey
from traffic_handler.proxy import HandlerConfig, TrafficHandler
from traffic_handler.relay import RelayClient
from traffic_handler.verdicts import VerdictStore

POD_IP = "10.244.1.15"
MAX_SESSIONS = 1024
PROXY_PORT = 9011  # 관리 엔드포인트 판별 기준. 실제 리스닝 포트는 테스트마다 임의로 잡는다.


class AlwaysMaliciousVerdicts(VerdictStore):
    """모든 세션을 이상으로 판정한다.

    프록시가 upstream 소켓을 열기 전에는 그 쪽 5-tuple을 알 수 없어 판정을 미리 넣어둘 수
    없다. outbound 응답 경로는 그 세션의 판정을 보므로 대역으로 대신한다.
    """

    def get_any(self, session_ids):
        return Detection(is_malicious=True, score=-0.9)


class FakeControlPlane:
    """Request Verifier 대역. 질의된 시그니처를 기록한다."""

    def __init__(self, allow=True):
        self.allow = allow
        self.signatures = []

    async def verify(self, signature):
        self.signatures.append(signature)
        return self.allow


class FakeBackend:
    """메인 컨테이너 / 형제 Pod 대역."""

    def __init__(self, body=b'{"content":"normal"}', status=200):
        self.body = body
        self.status = status
        self.requests = []
        self.port = None
        self._server = None

    async def start(self):
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        self._server.close()
        await self._server.wait_closed()

    async def _serve(self, reader, writer):
        buffered = http_message.BufferedReader(reader, 65536)
        try:
            while True:
                request = await http_message.read_request(buffered, 1 << 20)
                if request is None:
                    break
                self.requests.append(request)
                response = http_message.HttpResponse(
                    status=self.status,
                    reason="OK",
                    headers=[("Content-Type", "application/json"),
                             ("Content-Length", str(len(self.body)))],
                    body=self.body,
                )
                writer.write(response.to_bytes())
                await writer.drain()
                if request.wants_close():
                    break
        except Exception:
            pass
        finally:
            writer.close()


class Harness:
    """핸들러 + 백엔드 + 형제 Pod를 loopback에 띄운다."""

    def __init__(self, *, backend_body=b'{"content":"normal"}',
                 sibling_body=b'{"content":"normal"}', allow=True,
                 treat_client_as_local=False, always_malicious=False):
        self.backend = FakeBackend(backend_body)
        self.sibling = FakeBackend(sibling_body)
        self.control_plane = FakeControlPlane(allow=allow)
        self.peers = PeerRegistry()
        self.verdicts = (AlwaysMaliciousVerdicts if always_malicious else VerdictStore)(ttl=60.0)
        self._treat_client_as_local = treat_client_as_local
        self.dst = None
        self.port = None
        self._server = None

    async def start(self):
        await self.backend.start()
        await self.sibling.start()
        # 원목적지: inbound는 자기 Pod의 서비스 포트, outbound는 실제 목적지
        self.dst = self.dst or ("127.0.0.1", self.backend.port)

        config = HandlerConfig(
            pod_ip=POD_IP,
            target_port=self.backend.port,
            proxy_port=PROXY_PORT,
            max_sessions=MAX_SESSIONS,
            local_sources=frozenset({"127.0.0.1"}) if self._treat_client_as_local
            else frozenset({POD_IP}),
        )
        relay = RelayClient(self.peers, self.sibling.port, timeout=3.0, max_body_bytes=1 << 20)
        self.handler = TrafficHandler(
            config, self.verdicts, self.peers, self.control_plane, relay,
            resolve_dst=lambda sock: self.dst,
        )
        self._server = await asyncio.start_server(self.handler.handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        self._server.close()
        await self._server.wait_closed()
        await self.backend.stop()
        await self.sibling.stop()

    async def request(self, raw):
        """핸들러에 원바이트를 보내고 돌아온 것을 전부 읽는다."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        local_port = writer.get_extra_info("sockname")[1]
        writer.write(raw)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1 << 20), timeout=5.0)
        writer.close()
        return data, local_port

    def mark_malicious_client_session(self, local_port):
        key = SessionKey("127.0.0.1", self.dst[0], local_port, self.dst[1])
        self.verdicts.put(key.session_id(MAX_SESSIONS), Detection(is_malicious=True, score=-0.9))


GET_POST = b"GET /api/posts/5 HTTP/1.1\r\nHost: post-service:8080\r\nConnection: close\r\n\r\n"
POST_POST = (b"POST /api/posts HTTP/1.1\r\nHost: post-service:8080\r\n"
             b"Content-Type: application/json\r\nContent-Length: 14\r\n"
             b"Connection: close\r\n\r\n{\"title\":\"hi\"}")


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=15.0))


# --- inbound 연결 = outbound 응답 (Relay 경로) -------------------------------

def test_판정이_없으면_메인_컨테이너의_응답을_그대로_전달한다():
    async def scenario():
        harness = Harness(backend_body=b'{"content":"normal"}')
        await harness.start()
        try:
            data, _ = await harness.request(GET_POST)
        finally:
            await harness.stop()
        return data

    assert b'{"content":"normal"}' in run(scenario())


def test_이상_응답은_형제_Pod의_응답으로_교체된다():
    async def scenario():
        harness = Harness(
            backend_body=b'{"content":"<script>evil</script>"}',
            sibling_body=b'{"content":"normal"}',
            always_malicious=True,
        )
        await harness.start()
        harness.peers.update([{"name": "post-b", "ip": "127.0.0.1"}])
        try:
            data, _ = await harness.request(GET_POST)
        finally:
            await harness.stop()
            relayed = harness.sibling.requests
        return data, relayed

    data, relayed = run(scenario())
    assert b'{"content":"normal"}' in data
    assert b"evil" not in data
    assert len(relayed) == 1  # 형제 Pod에 같은 요청이 재전송됐다
    assert relayed[0].target == "/api/posts/5"


def test_형제_응답이_같으면_교체하지_않는다():
    async def scenario():
        harness = Harness(backend_body=b'{"content":"same"}', sibling_body=b'{"content":"same"}',
                          always_malicious=True)
        await harness.start()
        harness.peers.update([{"name": "post-b", "ip": "127.0.0.1"}])
        try:
            data, _ = await harness.request(GET_POST)
        finally:
            await harness.stop()
        return data

    assert b'{"content":"same"}' in run(scenario())


def test_비멱등_요청의_응답은_Relay하지_않는다():
    async def scenario():
        harness = Harness(
            backend_body=b'{"content":"tampered"}', sibling_body=b'{"content":"normal"}',
            always_malicious=True,
        )
        await harness.start()
        harness.peers.update([{"name": "post-b", "ip": "127.0.0.1"}])
        try:
            data, _ = await harness.request(POST_POST)
        finally:
            await harness.stop()
            relayed = len(harness.sibling.requests)
        return data, relayed

    data, relayed = run(scenario())
    assert b'{"content":"tampered"}' in data  # POST 재실행은 리소스를 중복 생성한다
    assert relayed == 0


def test_주소록_미수신이면_Relay를_건너뛴다():
    async def scenario():
        harness = Harness(
            backend_body=b'{"content":"tampered"}', sibling_body=b'{"content":"normal"}',
            always_malicious=True,
        )
        await harness.start()
        try:
            data, _ = await harness.request(GET_POST)
        finally:
            await harness.stop()
            relayed = len(harness.sibling.requests)
        return data, relayed

    data, relayed = run(scenario())
    assert b'{"content":"tampered"}' in data
    assert relayed == 0


def test_형제_Pod가_보낸_참조_요청은_다시_Relay하지_않는다():
    async def scenario():
        harness = Harness(
            backend_body=b'{"content":"tampered"}', sibling_body=b'{"content":"normal"}',
            always_malicious=True,
        )
        await harness.start()
        harness.peers.update([{"name": "post-b", "ip": "127.0.0.1"}])
        raw = (b"GET /api/posts/5 HTTP/1.1\r\nHost: post-service:8080\r\n"
               b"X-Deepmesh-Relay: 1\r\nConnection: close\r\n\r\n")
        try:
            data, _ = await harness.request(raw)
        finally:
            await harness.stop()
            relayed = len(harness.sibling.requests)
        return data, relayed

    data, relayed = run(scenario())
    assert b'{"content":"tampered"}' in data
    assert relayed == 0


# --- outbound 요청 (Drop 경로) ----------------------------------------------

def test_이상_요청이_미관측이면_Drop한다():
    async def scenario():
        harness = Harness(allow=False, treat_client_as_local=True)
        await harness.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", harness.port)
        local_port = writer.get_extra_info("sockname")[1]
        harness.mark_malicious_client_session(local_port)

        writer.write(b"GET /api/v1/secrets HTTP/1.1\r\nHost: 10.96.0.1:443\r\n\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1 << 20), timeout=5.0)
        writer.close()
        try:
            return data, list(harness.control_plane.signatures), len(harness.backend.requests)
        finally:
            await harness.stop()

    data, signatures, forwarded = run(scenario())
    assert data == b""  # 응답 없이 연결이 닫힌다
    assert signatures == ["GET|10.96.0.1:443|/api/v1/secrets|q:|b:"]
    assert forwarded == 0  # 목적지로 나가지 않았다


def test_이상_요청이라도_다른_replica에서_관측됐으면_전달한다():
    async def scenario():
        harness = Harness(allow=True, treat_client_as_local=True)
        await harness.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", harness.port)
        local_port = writer.get_extra_info("sockname")[1]
        harness.mark_malicious_client_session(local_port)

        writer.write(b"GET /api/posts/5 HTTP/1.1\r\nHost: post-service:8080\r\n"
                     b"Connection: close\r\n\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1 << 20), timeout=5.0)
        writer.close()
        try:
            return data, list(harness.control_plane.signatures), len(harness.backend.requests)
        finally:
            await harness.stop()

    data, signatures, forwarded = run(scenario())
    assert b'{"content":"normal"}' in data
    assert signatures == ["GET|post-service:8080|/api/posts/{id}|q:|b:"]
    assert forwarded == 1


def test_판정이_없는_outbound_요청은_검증하지_않는다():
    async def scenario():
        harness = Harness(treat_client_as_local=True)
        await harness.start()
        try:
            data, _ = await harness.request(GET_POST)
            return data, list(harness.control_plane.signatures)
        finally:
            await harness.stop()

    data, signatures = run(scenario())
    assert b'{"content":"normal"}' in data
    assert signatures == []  # 1차 탐지가 이상이라고 한 것만 Control Plane에 묻는다


# --- 관리 엔드포인트 ---------------------------------------------------------

def test_주소록_push를_수신한다():
    async def scenario():
        harness = Harness()
        await harness.start()
        # Control Plane은 NAT을 거치지 않고 프록시 포트로 직접 붙는다
        harness.dst = ("10.244.1.15", PROXY_PORT)

        body = json.dumps({
            "name": "post-a", "ip": POD_IP,
            "pods_ip": [{"name": "post-b", "ip": "10.244.2.20"}],
        }).encode()
        raw = (b"POST /receive/pods_ip HTTP/1.1\r\nContent-Type: application/json\r\n"
               b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        try:
            data, _ = await harness.request(raw)
            return data, harness.peers.list()
        finally:
            await harness.stop()

    data, peers = run(scenario())
    assert b"200 OK" in data
    assert peers == [{"name": "post-b", "ip": "10.244.2.20"}]


def test_알_수_없는_관리_경로는_404():
    async def scenario():
        harness = Harness()
        await harness.start()
        harness.dst = ("10.244.1.15", PROXY_PORT)
        try:
            data, _ = await harness.request(b"POST /nope HTTP/1.1\r\nContent-Length: 0\r\n\r\n")
            return data
        finally:
            await harness.stop()

    assert b"404" in run(scenario())
