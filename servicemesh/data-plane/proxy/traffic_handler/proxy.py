# -*- coding: utf-8 -*-
"""집행 경로 — Algorithm 1의 line 9~26 (Relay / Drop / Forward).

iptables가 ingress·egress를 모두 이 포트로 REDIRECT한다. 하나의 리스너가 세 종류의
연결을 받는다.

    1. 원목적지 포트 == PROXY_PORT   → Control Plane의 주소록 push (관리 엔드포인트)
    2. 출발지가 Pod 내부            → 메인 컨테이너의 outbound 요청  → Drop 판정 대상
    3. 그 외(외부 클라이언트)        → inbound 요청. 그 응답이 outbound → Relay 판정 대상

inbound 요청 자체는 탐지 대상이 아니다. 위협 모델이 lateral movement이므로 침해된
Pod에서 나가는 트래픽만 검사한다.
"""

import asyncio
import json
import logging
import socket
import struct
from dataclasses import dataclass, field, replace

from . import http_message, signature as sig
from .ports import SessionKey, SessionObservation
from .relay import RELAY_MARKER
from .telemetry import build_event

logger = logging.getLogger("traffic-handler.proxy")

SO_ORIGINAL_DST = 80  # linux/netfilter_ipv4.h
LOCALHOST = "127.0.0.1"

FORWARD = "forward"
DROP = "drop"
RELAY = "relay"

# 백엔드로 보낼 verdict / category / 검증 단계 라벨 (TELEMETRY_API.md)
VERDICT_FORWARD = "FORWARD"
VERDICT_DROP = "DROP"
VERDICT_RELAY = "RELAY"
CAT_CLEARED = "cleared"
CAT_DROP = "drop"
CAT_RELAY = "relay"
STAGE_REQUEST = "REQUEST_VERIFIER"
STAGE_RESPONSE = "RESPONSE_CONSISTENCY"


@dataclass
class HandlerConfig:
    pod_ip: str
    service_name: str = "unknown"
    target_port: int = 8080
    proxy_port: int = 9011
    max_sessions: int = 1024
    max_header_bytes: int = 64 * 1024
    max_body_bytes: int = 8 * 1024 * 1024
    relay_safe_methods: frozenset = field(
        default_factory=lambda: frozenset({"GET", "HEAD", "OPTIONS"})
    )
    # 이 주소에서 온 연결은 메인 컨테이너가 낸 것으로 본다(= outbound 요청).
    # 그 외는 외부 클라이언트의 inbound로 본다.
    local_sources: frozenset = None

    def __post_init__(self):
        if self.local_sources is None:
            self.local_sources = frozenset({self.pod_ip, LOCALHOST})


def original_dst(sock):
    """iptables REDIRECT된 연결의 원 목적지.

    conntrack이 REDIRECT 이전의 목적지를 돌려준다. NAT을 거치지 않은 연결(Control Plane이
    프록시 포트로 직접 붙는 경우)이면 소켓 자신의 주소가 그대로 나오므로, 그 차이로
    관리 엔드포인트를 구분할 수 있다.

    SO_ORIGINAL_DST가 없는 환경(개발 PC)에서는 소켓의 로컬 주소로 대체한다. iptables가
    없어 리다이렉트도 없으니 원목적지와 로컬 주소가 같다.
    """
    try:
        data = sock.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
        port, raw_ip = struct.unpack("!2xH4s8x", data)
        return socket.inet_ntoa(raw_ip), port
    except (OSError, AttributeError, struct.error):
        sockname = sock.getsockname()
        return (sockname[0], sockname[1]) if sockname else None


def _with_endpoint(observation, pod_ip, endpoint, src_port):
    """관측에 실제 상대 주소를 입힌다.

    집행 경로는 SessionObservation 대신 Detection만 받을 수도 있다(ports.py) — 탐지가
    5-tuple을 동반하기 전에 만들어진 판정이 그렇다. 그 경우에도 상대 주소만은 실어 보낸다.
    """
    if isinstance(observation, SessionObservation):
        return replace(observation, src_ip=pod_ip,
                       src_port=observation.src_port or src_port,
                       dst_ip=endpoint[0], dst_port=endpoint[1])
    return SessionObservation(detection=observation, src_ip=pod_ip, src_port=src_port,
                              dst_ip=endpoint[0], dst_port=endpoint[1])


class TrafficHandler:
    def __init__(self, config, verdicts, peers, control_plane, relay_client,
                 resolve_dst=None, telemetry=None):
        self.config = config
        self.verdicts = verdicts
        self.peers = peers
        self.control_plane = control_plane
        self.relay = relay_client
        self.telemetry = telemetry
        # 원목적지 해석기. 테스트에서는 NAT이 없으므로 대역을 주입한다.
        self.resolve_dst = resolve_dst or original_dst

    def _emit(self, observation, verdict, category, stage, passed, signature,
              endpoint=None, src_port=None):
        """집행 결과를 텔레메트리로 보낸다. telemetry가 없으면 무시.

        관측의 5-tuple을 집행 경로가 아는 값으로 바로잡는다. 탐지는 lo에서 프레임을 잡기
        때문에 관측된 주소가 메인 컨테이너↔프록시 루프백 구간(127.0.0.1 양쪽)이다. 그대로
        보내면 백엔드가 목적지를 서비스로 역매핑하지 못해, 토폴로지 엣지가 전부 external로
        뭉치고 이벤트의 peerServiceName이 비어 화면에 "알 수 없음"으로 뜬다.

        TELEMETRY_API.md가 규정하는 값은 이것이다 — srcIp는 관측 주체(내 Pod), dstIp는
        상대. 상대가 누구인지는 집행 경로만 안다: outbound는 SO_ORIGINAL_DST로 얻은 원
        목적지이고, 응답은 요청을 보내온 외부 클라이언트다.
        """
        if self.telemetry is None:
            return
        if endpoint is not None:
            observation = _with_endpoint(observation, self.config.pod_ip, endpoint, src_port)
        self.telemetry.emit(
            build_event(observation, verdict, category, stage, passed, signature)
        )

    # -- 진입점 --------------------------------------------------------------

    async def handle(self, client_reader, client_writer):
        try:
            sock = client_writer.get_extra_info("socket")
            peer = client_writer.get_extra_info("peername") or (LOCALHOST, 0)
            dst = self.resolve_dst(sock) or (LOCALHOST, self.config.target_port)

            if dst[1] == self.config.proxy_port:
                await self._serve_admin(client_reader, client_writer)
                return

            reader = http_message.BufferedReader(client_reader, self.config.max_header_bytes)
            if peer[0] in self.config.local_sources:
                await self._handle_outbound_request(reader, client_writer, peer, dst)
            else:
                await self._handle_inbound(reader, client_writer, peer, dst)
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        except Exception:
            logger.exception("연결 처리 실패")
        finally:
            _close(client_writer)

    # -- 2번: outbound 요청 (Drop 경로) --------------------------------------

    async def _handle_outbound_request(self, reader, client_writer, peer, dst):
        # 판정과 검증을 먼저 끝낸다. Drop할 트래픽 때문에 목적지 연결을 열지 않는다.
        # 스니퍼는 메인 컨테이너 → 프록시 구간(= 클라이언트 쪽 5-tuple)에서 요청을 보므로
        # 이 시점에 조회할 세션 id는 클라이언트 쪽 하나로 충분하다.
        sessions = {SessionKey(peer[0], dst[0], peer[1], dst[1]).session_id(
            self.config.max_sessions)}

        head = await reader.peek(8)
        is_http = http_message.looks_like_http_request(head)
        first_request = None

        if is_http:
            try:
                first_request = await http_message.read_request(
                    reader, self.config.max_body_bytes
                )
            except ValueError as exc:
                logger.debug("HTTP 파싱 실패 — 연결 종료: %s", exc)
                return
            if first_request is None:
                return
            signature = self._signature(first_request, dst)
        else:
            signature = sig.tcp_signature(dst[0], dst[1])

        detection = self.verdicts.get_any(sessions)
        if detection is not None and detection.is_malicious:
            kind = "outbound request" if is_http else "outbound tcp"
            method = first_request.method if is_http else "TCP"
            target = first_request.target if is_http else "{}:{}".format(*dst)
            if not await self.control_plane.verify(signature):
                self._log(DROP, kind, method, target, detection)
                self._emit(detection, VERDICT_DROP, CAT_DROP, STAGE_REQUEST, False, signature,
                           endpoint=dst, src_port=peer[1])
                return  # Algorithm 1 line 19-20: Drop 후 종료
            self._log(FORWARD, kind + "(검증 통과)", method, target, detection)
            self._emit(detection, VERDICT_FORWARD, CAT_CLEARED, STAGE_REQUEST, True, signature,
                       endpoint=dst, src_port=peer[1])

        upstream_ip = LOCALHOST if dst[0] == self.config.pod_ip else dst[0]
        try:
            stream, up_writer = await asyncio.open_connection(upstream_ip, dst[1])
        except OSError as exc:
            logger.warning("upstream 연결 실패 %s:%d — %s", upstream_ip, dst[1], exc)
            return
        up_reader = http_message.BufferedReader(stream, self.config.max_header_bytes)

        try:
            sessions |= self._session_ids(peer, dst, up_writer)
            if not is_http:
                await self._pipe_raw(reader, client_writer, up_reader, up_writer)
                return
            await self._forward_requests(reader, client_writer, up_reader, up_writer,
                                         dst, sessions, first_request)
        except ValueError as exc:
            logger.debug("HTTP 파싱 실패 — 연결 종료: %s", exc)
        finally:
            _close(up_writer)

    async def _pipe_raw(self, reader, client_writer, up_reader, up_writer):
        """비HTTP TCP(MySQL 등)는 파싱하지 않고 그대로 중계한다."""
        pending = reader.buffered
        if pending:
            up_writer.write(pending)
            await up_writer.drain()
        await asyncio.gather(
            _pipe(reader, up_writer),
            _pipe(up_reader, client_writer),
        )

    async def _forward_requests(self, reader, client_writer, up_reader, up_writer,
                                dst, sessions, request):
        """검증을 통과한 outbound 요청과 그 응답을 계속 중계한다."""
        while request is not None:
            up_writer.write(request.to_bytes())
            await up_writer.drain()

            response = await http_message.read_response(
                up_reader, request.method, self.config.max_body_bytes
            )
            if response is None:
                break
            client_writer.write(response.to_bytes())
            await client_writer.drain()
            if request.wants_close() or response.wants_close():
                break

            request = await http_message.read_request(reader, self.config.max_body_bytes)
            if request is None:
                break
            detection = self.verdicts.get_any(sessions)
            if detection is not None and detection.is_malicious:
                signature = self._signature(request, dst)
                if not await self.control_plane.verify(signature):
                    self._log(DROP, "outbound request", request.method, request.target,
                              detection)
                    self._emit(detection, VERDICT_DROP, CAT_DROP, STAGE_REQUEST, False,
                               signature, endpoint=dst, src_port=peer[1])
                    return
                self._emit(detection, VERDICT_FORWARD, CAT_CLEARED, STAGE_REQUEST, True,
                           signature, endpoint=dst, src_port=peer[1])

    # -- 3번: inbound 연결의 응답 (Relay 경로) -------------------------------

    async def _handle_inbound(self, reader, client_writer, peer, dst):
        try:
            stream, up_writer = await asyncio.open_connection(
                LOCALHOST, self.config.target_port
            )
        except OSError as exc:
            logger.warning("메인 컨테이너 연결 실패 — %s", exc)
            return
        up_reader = http_message.BufferedReader(stream, self.config.max_header_bytes)

        try:
            sessions = self._session_ids(peer, dst, up_writer,
                                         upstream_port=self.config.target_port)
            head = await reader.peek(8)
            if not http_message.looks_like_http_request(head):
                pending = reader.buffered
                if pending:
                    up_writer.write(pending)
                    await up_writer.drain()
                await asyncio.gather(
                    _pipe(reader, up_writer),
                    _pipe(up_reader, client_writer),
                )
                return

            while True:
                request = await http_message.read_request(reader, self.config.max_body_bytes)
                if request is None:
                    break

                # inbound 요청은 탐지 대상이 아니다 — 그대로 메인 컨테이너로 전달
                up_writer.write(request.to_bytes())
                await up_writer.drain()

                response = await http_message.read_response(
                    up_reader, request.method, self.config.max_body_bytes
                )
                if response is None:
                    break

                response, action = await self._apply_response_policy(
                    request, response, sessions, dst, peer)
                client_writer.write(response.to_bytes())
                await client_writer.drain()

                if action == RELAY or request.wants_close() or response.wants_close():
                    break
        except ValueError as exc:
            logger.debug("HTTP 파싱 실패 — 연결 종료: %s", exc)
        finally:
            _close(up_writer)

    async def _apply_response_policy(self, request, response, sessions, dst, peer):
        """Algorithm 1 line 10~15. 이상 응답을 형제 Pod의 참조 응답으로 교체한다."""
        detection = self.verdicts.get_any(sessions)
        if detection is None or not detection.is_malicious:
            return response, FORWARD

        if request.header(RELAY_MARKER):
            # 형제 Pod가 보낸 참조 요청이다. 여기서 또 Relay하면 연쇄된다.
            self._log(FORWARD, "outbound response(참조 요청)", request.method,
                      request.target, detection)
            return response, FORWARD

        if request.method.upper() not in self.config.relay_safe_methods:
            # 멱등하지 않은 요청을 형제 Pod에 다시 보내면 리소스가 중복 생성된다
            self._log(FORWARD, "outbound response(비멱등 — Relay 생략)", request.method,
                      request.target, detection)
            return response, FORWARD

        if not self.peers.has_peers():
            # 기동 직후 주소록 미수신 상태 — 비교 기준이 없으므로 그대로 내보낸다
            self._log(FORWARD, "outbound response(주소록 없음)", request.method,
                      request.target, detection)
            return response, FORWARD

        reference = await self.relay.fetch_reference(request)
        if reference is None:
            self._log(FORWARD, "outbound response(참조 응답 획득 실패)", request.method,
                      request.target, detection)
            return response, FORWARD

        signature = self._signature(request, dst)
        if reference.body == response.body:
            # IsContentEqual → 교체하지 않는다 (오탐으로 본다)
            self._log(FORWARD, "outbound response(내용 일치)", request.method,
                      request.target, detection)
            self._emit(detection, VERDICT_FORWARD, CAT_CLEARED, STAGE_RESPONSE, True,
                       signature, endpoint=peer, src_port=self.config.target_port)
            return response, FORWARD

        self._log(RELAY, "outbound response", request.method, request.target, detection)
        self._emit(detection, VERDICT_RELAY, CAT_RELAY, STAGE_RESPONSE, False, signature,
                   endpoint=peer, src_port=self.config.target_port)
        return reference, RELAY

    # -- 1번: 관리 엔드포인트 ------------------------------------------------

    async def _serve_admin(self, client_reader, client_writer):
        """Control Plane의 주소록 push 수신.

        Control Plane은 Pod IP의 PROXY_PORT로 직접 붙는다. iptables는 TARGET_PORT만
        리다이렉트하므로 이 연결은 NAT을 거치지 않아 원목적지가 PROXY_PORT 그대로다.
        그 차이로 프록시 트래픽과 구분한다.
        """
        reader = http_message.BufferedReader(client_reader, self.config.max_header_bytes)
        try:
            request = await http_message.read_request(reader, self.config.max_body_bytes)
        except ValueError:
            request = None
        if request is None:
            return

        if request.method.upper() != "POST" or request.target.split("?")[0] != "/receive/pods_ip":
            _write_simple(client_writer, 404, b'{"error":"not found"}')
            await client_writer.drain()
            return

        try:
            payload = json.loads(request.body or b"{}")
            changed = self.peers.update(payload.get("pods_ip", []))
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning("주소록 파싱 실패: %s", exc)
            _write_simple(client_writer, 400, b'{"error":"bad request"}')
            await client_writer.drain()
            return

        if changed:
            logger.info("주소록 갱신: %s", [p["ip"] for p in self.peers.list()])
        _write_simple(client_writer, 200, b"")
        await client_writer.drain()

    # -- 보조 ----------------------------------------------------------------

    def _session_ids(self, peer, dst, up_writer, upstream_port=None):
        """이 연결에 대응하는 세션 id 후보들.

        프록시가 중간에서 소켓을 새로 열기 때문에 클라이언트 쪽과 upstream 쪽의
        5-tuple이 다르다. 스니퍼가 어느 쪽을 봤든 판정을 찾을 수 있도록 둘 다 만든다.
        """
        ids = set()
        client_side = SessionKey(peer[0], dst[0], peer[1], dst[1])
        ids.add(client_side.session_id(self.config.max_sessions))

        sockname = up_writer.get_extra_info("sockname")
        peername = up_writer.get_extra_info("peername")
        if sockname and peername:
            upstream_side = SessionKey(
                sockname[0], peername[0], sockname[1],
                upstream_port if upstream_port is not None else peername[1],
            )
            ids.add(upstream_side.session_id(self.config.max_sessions))
        return ids

    def _signature(self, request, dst):
        host = request.header("Host") or "{}:{}".format(dst[0], dst[1])
        return sig.http_signature(
            request.method, host, request.target, request.body, request.header("Content-Type")
        )

    def _log(self, action, kind, method, target, detection):
        level = logging.WARNING if action != FORWARD else logging.INFO
        logger.log(
            level, "[%s] %s %s %s (service=%s, score=%.4f)",
            action.upper(), kind, method, target, self.config.service_name, detection.score,
        )


def _write_simple(writer, status, body):
    reason = {200: "OK", 400: "Bad Request", 404: "Not Found"}.get(status, "OK")
    head = "HTTP/1.1 {} {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n".format(
        status, reason, len(body)
    )
    writer.write(head.encode("latin1") + body)


async def _pipe(buffered_reader, writer):
    try:
        while True:
            data = await buffered_reader.read_some()
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        _close(writer)


def _close(writer):
    if writer is None:
        return
    try:
        writer.close()
    except Exception:
        pass
