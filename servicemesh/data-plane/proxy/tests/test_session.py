# -*- coding: utf-8 -*-
from conftest import make_frame

from traffic_handler.ports import REQUEST, RESPONSE, SessionKey
from traffic_handler.session import (
    is_from_main_container, last_packet_direction, parse_session,
)

TARGET_PORT = 8080
PROXY_PORT = 9011


class TestParseSession:
    def test_ipv4_tcp_프레임에서_5tuple을_뽑는다(self):
        frame = make_frame("10.244.1.15", "10.96.0.1", 52344, 443)
        key = parse_session(frame)
        assert key == SessionKey("10.244.1.15", "10.96.0.1", 52344, 443)

    def test_tcp가_아니면_None(self):
        frame = make_frame("10.244.1.15", "10.96.0.1", 52344, 443, proto=17)
        assert parse_session(frame) is None

    def test_너무_짧은_프레임은_None(self):
        assert parse_session(b"\x00" * 20) is None

    def test_ipv4가_아니면_None(self):
        frame = bytearray(make_frame("10.0.0.1", "10.0.0.2", 1, 2))
        frame[12:14] = b"\x86\xdd"  # IPv6
        assert parse_session(bytes(frame)) is None


class TestSessionId:
    def test_방향이_뒤집혀도_같은_세션으로_묶인다(self):
        forward = SessionKey("10.244.1.15", "10.96.0.1", 52344, 443)
        backward = SessionKey("10.96.0.1", "10.244.1.15", 443, 52344)
        assert forward.session_id(1024) == backward.session_id(1024)

    def test_다른_세션은_다른_id를_가진다(self):
        a = SessionKey("10.244.1.15", "10.96.0.1", 52344, 443)
        b = SessionKey("10.244.1.15", "10.96.0.2", 52344, 443)
        assert a.session_id(1024) != b.session_id(1024)


class TestIsFromMainContainer:
    def test_메인의_outbound_요청은_프록시_포트로_리다이렉트되어_온다(self):
        key = SessionKey("127.0.0.1", "127.0.0.1", 41234, PROXY_PORT)
        assert is_from_main_container(key, TARGET_PORT, PROXY_PORT)

    def test_메인의_outbound_응답은_출발_포트가_타깃_포트다(self):
        key = SessionKey("127.0.0.1", "127.0.0.1", TARGET_PORT, 41235)
        assert is_from_main_container(key, TARGET_PORT, PROXY_PORT)

    def test_프록시가_메인에_전달하는_요청은_탐지_대상이_아니다(self):
        key = SessionKey("127.0.0.1", "127.0.0.1", 41235, TARGET_PORT)
        assert not is_from_main_container(key, TARGET_PORT, PROXY_PORT)

    def test_프록시가_메인에_돌려주는_응답은_탐지_대상이_아니다(self):
        key = SessionKey("127.0.0.1", "127.0.0.1", PROXY_PORT, 41234)
        assert not is_from_main_container(key, TARGET_PORT, PROXY_PORT)


class TestLastPacketDirection:
    def test_프록시_포트로_오는_것은_요청이다(self):
        key = SessionKey("127.0.0.1", "127.0.0.1", 41234, PROXY_PORT)
        assert last_packet_direction(key, TARGET_PORT, PROXY_PORT) == REQUEST

    def test_타깃_포트에서_나가는_것은_응답이다(self):
        key = SessionKey("127.0.0.1", "127.0.0.1", TARGET_PORT, 41235)
        assert last_packet_direction(key, TARGET_PORT, PROXY_PORT) == RESPONSE

    def test_탐지_대상이_아니면_None(self):
        key = SessionKey("127.0.0.1", "127.0.0.1", 41235, TARGET_PORT)
        assert last_packet_direction(key, TARGET_PORT, PROXY_PORT) is None
