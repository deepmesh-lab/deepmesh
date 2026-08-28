# -*- coding: utf-8 -*-
"""집행 경로 — Algorithm 1 line 9~26을 실제 소켓 위에서 검증한다.

이상 판정은 ScriptedDetector 대신 VerdictStore에 직접 넣는다. 여기서 확인하려는 것은
'이상으로 판정됐을 때 Relay/Drop/Forward가 규칙대로 갈리는가'이지 탐지 자체가 아니다.
"""

import asyncio
import json
import time

from traffic_handler import http_message
from traffic_handler.original_dst import OriginalDstRegistry
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


class RecordingTelemetry:
    """발신된 이벤트를 모아두는 대역. 실제 전송은 하지 않는다."""

    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def incr(self, category, peer=None):
        pass


class Harness:
    """핸들러 + 백엔드 + 형제 Pod를 loopback에 띄운다."""

    def __init__(self, *, backend_body=b'{"content":"normal"}',
                 sibling_body=b'{"content":"normal"}', allow=True,
                 treat_client_as_local=False, always_malicious=False,
                 verdict_wait=0.0, original_dst_registry=None):
        self._verdict_wait = verdict_wait
        self.original_dst_registry = original_dst_registry
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
            verdict_wait=self._verdict_wait,
            verdict_poll=0.01,
        )
        relay = RelayClient(self.peers, self.sibling.port, timeout=3.0, max_body_bytes=1 << 20)
        self.telemetry = RecordingTelemetry()
        self.handler = TrafficHandler(
            config, self.verdicts, self.peers, self.control_plane, relay,
            resolve_dst=lambda sock: self.dst, telemetry=self.telemetry,
            original_dst_registry=self.original_dst_registry,
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

    async def request_with_late_verdict(self, raw):
        """요청을 보내되, 프록시가 판정을 기다리는 동안 늦게 판정을 주입한다."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self._pending_port = writer.get_extra_info("sockname")[1]
        writer.write(raw)
        await writer.drain()
        asyncio.create_task(self._late())
        data = await asyncio.wait_for(reader.read(1 << 20), timeout=5.0)
        writer.close()
        return data

    def mark_malicious_client_session(self, local_port):
        key = SessionKey("127.0.0.1", self.dst[0], local_port, self.dst[1])
        self.verdicts.put(key.session_id(MAX_SESSIONS), Detection(is_malicious=True, score=-0.9))


GET_POST = b"GET /api/posts/5 HTTP/1.1\r\nHost: post-service:8080\r\nConnection: close\r\n\r\n"
# 연결을 닫지 않는 요청. east-west 호출(Apache HttpClient 풀)이 실제로 이 모양이다.
KEEPALIVE_GET = b"GET /api/posts/5 HTTP/1.1\r\nHost: post-service:8080\r\n\r\n"
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


# --- 텔레메트리의 5-tuple 귀속 ----------------------------------------------
#
# 탐지는 lo에서 프레임을 잡아 관측 주소가 메인 컨테이너↔프록시 루프백 구간이다. 그대로
# 내보내면 백엔드가 목적지를 서비스로 역매핑하지 못해 토폴로지 엣지가 전부 external로
# 뭉치고, 이벤트의 peerServiceName이 비어 화면에 "알 수 없음"으로 뜬다. 집행 경로가 아는
# 실제 상대로 바로잡는지 본다 (TELEMETRY_API.md).

def test_outbound_이벤트의_상대는_원_목적지다():
    async def scenario():
        # SO_ORIGINAL_DST가 돌려줄 원 목적지를 클러스터 IP로 둔다. 실제로 연결되지는
        # 않지만 이벤트는 연결 시도 전에 발신되므로 검증에 지장이 없다.
        h = Harness(allow=True, treat_client_as_local=True, always_malicious=True)
        await h.start()
        h.dst = ("10.244.2.77", 8080)
        try:
            await h.request(GET_POST)
        finally:
            await h.stop()
        return h.telemetry.events

    events = run(scenario())
    assert events, "이상 판정 outbound 요청은 이벤트를 남겨야 한다"
    event = events[-1]
    assert event["srcIp"] == POD_IP           # 관측 주체는 내 Pod
    assert event["dstIp"] == "10.244.2.77"    # 127.0.0.1이 아니라 실제 목적지
    assert event["dstPort"] == 8080
    assert event["direction"] is None or event["direction"] in ("REQUEST", "RESPONSE")


def test_응답_이벤트의_상대는_요청을_보낸_클라이언트다():
    async def scenario():
        # 응답 경로(Relay). 상대는 목적지가 아니라 요청을 보내온 외부 클라이언트다.
        h = Harness(backend_body=b'{"content":"tampered"}',
                    sibling_body=b'{"content":"normal"}', always_malicious=True)
        await h.start()
        h.peers.update([{"name": "post-b", "ip": "127.0.0.1"}])
        try:
            await h.request(GET_POST)
        finally:
            await h.stop()
        return h.telemetry.events

    events = run(scenario())
    assert events, "Relay는 이벤트를 남겨야 한다"
    event = events[-1]
    assert event["srcIp"] == POD_IP
    assert event["dstIp"] == "127.0.0.1"      # 테스트에서 클라이언트는 loopback이다
    assert event["verdict"] == "RELAY"


# --- 판정 대기 (Request Verifier 경로) --------------------------------------
#
# 판정은 세션당 프레임 5개가 스니퍼에 잡혀야 나온다. 요청이 도착한 직후엔 아직 안 찼으므로
# 즉시 조회하면 판정이 없어 이상 트래픽도 verify 없이 전달된다. 짧게 기다려야 Drop 경로가
# 산다 — 시나리오 1(K8s API 정찰 → Drop)이 여기에 달려 있다.

def test_요청_직후_판정이_없으면_기다렸다_Drop한다():
    async def scenario():
        h = Harness(allow=False, treat_client_as_local=True, verdict_wait=1.0)
        await h.start()
        # 판정을 늦게 넣는다 — 요청이 도착하고 나서야 스니퍼가 윈도우를 채운 상황.
        async def late_verdict():
            await asyncio.sleep(0.1)
            key = SessionKey("127.0.0.1", h.dst[0], h._pending_port, h.dst[1])
            h.verdicts.put(key.session_id(MAX_SESSIONS),
                           Detection(is_malicious=True, score=-0.9))
        h._late = late_verdict
        try:
            data = await h.request_with_late_verdict(GET_POST)
        finally:
            await h.stop()
        return data, h.control_plane.signatures

    data, signatures = run(scenario())
    # 검증이 거부(allow=False)했으므로 Drop → 목적지 응답이 클라이언트에 가지 않는다.
    assert signatures, "판정이 늦게 와도 Request Verifier를 거쳐야 한다"
    assert b"normal" not in data


def test_판정_대기가_0이면_즉시_전달한다():
    # verdict_wait=0이면 예전 동작 — 판정이 아직 없으니 그대로 전달(fail-open).
    async def scenario():
        h = Harness(allow=False, treat_client_as_local=True, verdict_wait=0.0)
        await h.start()
        try:
            return await h.request(GET_POST)
        finally:
            await h.stop()

    data, _ = run(scenario())
    assert b"normal" in data   # 판정 없음 → Forward


# --- 비HTTP 원바이트 중계 (TLS·MySQL) ---------------------------------------
#
# 프록시는 HTTP만 파싱하고 비HTTP는 그대로 흘려보낸다. peek로 앞부분을 본 뒤 그 버퍼를
# 중복해서 밀어넣으면 TLS ClientHello가 두 번 나가 핸드셰이크가 깨진다 — :443 K8s API와
# :3306 MySQL 연결이 그래서 실패했다. 받은 그대로, 중복 없이 목적지에 닿아야 한다.

class RawEchoServer:
    """받은 바이트를 그대로 돌려보낸다. 비HTTP 스트림 무결성 확인용."""

    def __init__(self):
        self._server = None
        self.port = None
        self.received = bytearray()

    async def start(self):
        async def handle(reader, writer):
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                self.received.extend(chunk)
                writer.write(chunk)
                await writer.drain()
            writer.close()
        self._server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        self._server.close()
        await self._server.wait_closed()


def test_비HTTP_바이트는_중복없이_그대로_중계된다():
    async def scenario():
        echo = RawEchoServer()
        await echo.start()
        h = Harness(treat_client_as_local=True)
        h.dst = ("127.0.0.1", echo.port)      # 원목적지 = raw echo 서버
        await h.start()
        h.dst = ("127.0.0.1", echo.port)
        try:
            # TLS ClientHello를 흉내낸 비HTTP 바이트. 0x16 0x03 = handshake, TLS 1.x
            payload = b"\x16\x03\x01\x00\x2f" + b"CLIENTHELLO-" + b"A" * 40
            reader, writer = await asyncio.open_connection("127.0.0.1", h.port)
            writer.write(payload)
            await writer.drain()
            echoed = await asyncio.wait_for(reader.read(len(payload)), timeout=5.0)
            writer.close()
            await asyncio.sleep(0.05)
            return payload, echoed, bytes(echo.received)
        finally:
            await echo.stop()
            await h.stop()

    payload, echoed, received = run(scenario())
    # 목적지가 받은 바이트가 보낸 것과 정확히 같아야 한다(중복이면 길이가 2배가 된다).
    assert received == payload, "비HTTP 바이트가 원본과 달라졌다(중복 전송 의심)"
    assert echoed == payload    # 왕복도 무결


# --- 응답 판정 대기 (Relay 경로) --------------------------------------------
#
# 응답이 나가는 순간엔 탐지가 아직 윈도우를 못 채워 판정이 없다. 즉시 조회하면 이상
# 응답도 그냥 나가 Relay가 죽는다. 요청 경로처럼 짧게 기다려야 한다 — 시나리오 2가
# 여기 달려 있다.

def test_응답_판정이_늦게_와도_Relay한다():
    async def scenario():
        # 변조 응답(tampered) vs 형제 정상 응답(normal). 판정을 늦게 주입한다.
        h = Harness(backend_body=b'{"content":"tampered"}',
                    sibling_body=b'{"content":"normal"}', verdict_wait=1.0)
        await h.start()
        h.peers.update([{"name": "fe-b", "ip": "127.0.0.1"}])

        reader, writer = await asyncio.open_connection("127.0.0.1", h.port)
        local_port = writer.get_extra_info("sockname")[1]

        async def late():
            await asyncio.sleep(0.1)   # 응답이 프록시에 도착한 뒤에야 판정이 생기는 상황
            key = SessionKey("127.0.0.1", h.dst[0], local_port, h.dst[1])
            h.verdicts.put(key.session_id(MAX_SESSIONS),
                           Detection(is_malicious=True, score=-0.9))
        asyncio.create_task(late())

        writer.write(GET_POST)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1 << 20), timeout=5.0)
        writer.close()
        await h.stop()
        return data

    data = run(scenario())
    # 판정이 늦게 왔어도 형제의 정상 응답으로 교체(Relay)돼야 한다.
    assert b"normal" in data
    assert b"tampered" not in data


def test_응답_판정_대기가_0이면_변조_응답이_그대로_나간다():
    # verdict_wait=0이면 예전 동작 — 판정 전에 응답이 나가 Relay 못 함.
    async def scenario():
        h = Harness(backend_body=b'{"content":"tampered"}',
                    sibling_body=b'{"content":"normal"}', verdict_wait=0.0)
        await h.start()
        h.peers.update([{"name": "fe-b", "ip": "127.0.0.1"}])
        try:
            data, _ = await h.request(GET_POST)
            return data
        finally:
            await h.stop()

    data = run(scenario())
    assert b"tampered" in data   # 판정 없음 → 원본 그대로


# --- keep-alive 연결 (커넥션 풀) ---------------------------------------------
#
# east-west 호출은 Apache HttpClient 풀을 타서 한 연결이 몇 분을 살고 그 위로 요청이
# 계속 흐른다. 연결 하나 = 요청 하나인 공격 스크립트에서는 드러나지 않는 경로다.


async def _wait_until(predicate, timeout=5.0):
    """조건이 참이 될 때까지 이벤트 루프를 돌린다. 연결 종료 정리는 비동기로 끝난다."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


def test_원목적지_등록이_연결이_사는_동안_유지된다():
    # 등록이 연결보다 먼저 사라지면 두 번째 요청부터 탐지가 DNAT된 127.0.0.1:9011을
    # 그대로 보고, 평시 엣지가 목적지 서비스 대신 external로 뭉친다.
    async def scenario():
        registry = OriginalDstRegistry(ttl=600.0, clock=time.monotonic)
        h = Harness(treat_client_as_local=True, original_dst_registry=registry)
        await h.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", h.port)
            local_port = writer.get_extra_info("sockname")[1]
            buffered = http_message.BufferedReader(reader, 65536)

            resolved = []
            for _ in range(3):
                writer.write(KEEPALIVE_GET)
                await writer.drain()
                await http_message.read_response(buffered, "GET", 1 << 20)
                resolved.append(registry.resolve("127.0.0.1", local_port))

            writer.close()
            gone = await _wait_until(
                lambda: registry.resolve("127.0.0.1", local_port) is None
            )
            return resolved, gone, h.dst
        finally:
            await h.stop()

    resolved, gone, dst = run(scenario())
    assert resolved == [dst, dst, dst]  # 요청마다 원목적지를 되찾을 수 있다
    assert gone                          # 연결이 끝나면 지워진다(포트 재사용 오해 방지)


def test_keepalive_두번째_요청도_이상이면_Drop한다():
    # 같은 연결의 2번째 요청부터는 전달 루프가 집행한다. Drop 이벤트에 실을 클라이언트
    # 포트를 그 루프가 들고 있지 않으면 집행이 통째로 예외로 죽는다.
    async def scenario():
        h = Harness(allow=False, treat_client_as_local=True)
        await h.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", h.port)
            local_port = writer.get_extra_info("sockname")[1]
            buffered = http_message.BufferedReader(reader, 65536)

            writer.write(KEEPALIVE_GET)          # 1번째 — 판정 없음 → 전달
            await writer.drain()
            first = await http_message.read_response(buffered, "GET", 1 << 20)

            h.mark_malicious_client_session(local_port)
            writer.write(KEEPALIVE_GET)          # 2번째 — 이상 판정 + 검증 거부
            await writer.drain()
            second = await asyncio.wait_for(reader.read(1 << 20), timeout=5.0)
            writer.close()
            return (first.body, second, list(h.telemetry.events),
                    len(h.backend.requests), local_port)
        finally:
            await h.stop()

    first_body, second, events, forwarded, local_port = run(scenario())
    assert b'{"content":"normal"}' == first_body
    assert second == b""            # 2번째 응답 없이 연결이 닫힌다
    assert forwarded == 1           # 2번째 요청은 목적지로 나가지 않았다
    drops = [e for e in events if e["verdict"] == "DROP"]
    assert len(drops) == 1
    assert drops[0]["srcPort"] == local_port
