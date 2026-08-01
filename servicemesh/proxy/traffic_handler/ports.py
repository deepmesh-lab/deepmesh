# -*- coding: utf-8 -*-
"""Traffic Handler가 외부 모듈과 만나는 경계(port) 정의.

Traffic Handler는 Traffic Converter / Anomaly Detector의 내부 구현을 알지 않는다.
아래 Protocol만 만족하면 무엇이든 주입할 수 있고, 테스트에서는 stubs.py의 대역을 쓴다.

회의록에 정리된 역할 분담을 그대로 옮긴 것이다:
    Traffic Handler가 세션 단위 트래픽을 받아 세션 정보를 구성하고 패킷 벡터를
    Traffic Converter로 전달 → Converter가 만든 세션 이미지를 Anomaly Detector로
    → Detector가 세션 단위 판정을 반환
"""

from dataclasses import dataclass
from typing import Any, Iterator, Optional, Protocol, runtime_checkable

IPPROTO_TCP = 6


@dataclass(frozen=True)
class SessionKey:
    """세션 식별 5-tuple."""

    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    proto: int = IPPROTO_TCP

    def session_id(self, max_sessions):
        """5-tuple XOR 해시.

        XOR이라 방향(정/역)에 무관하다 — 요청 패킷과 응답 패킷이 같은 id로 묶인다.
        Traffic Converter가 세션을 나누는 기준과 반드시 같아야 하므로 max_sessions를
        Converter에게서 받아 쓴다.
        """
        return (
            _ip_to_int(self.src_ip)
            ^ _ip_to_int(self.dst_ip)
            ^ self.src_port
            ^ self.dst_port
            ^ self.proto
        ) % max_sessions


def _ip_to_int(ip):
    a, b, c, d = (int(x) for x in ip.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


@dataclass(frozen=True)
class Detection:
    """Anomaly Detector의 세션 단위 판정 결과."""

    is_malicious: bool
    score: float = 0.0


@runtime_checkable
class TrafficConverter(Protocol):
    """패킷 벡터를 세션별로 버퍼링하다 윈도우 w가 차면 이미지를 낸다."""

    max_sessions: int

    def push(self, session_id: int, frame: bytes) -> Optional[Any]:
        """프레임 1개를 세션 버퍼에 넣는다.

        윈도우가 차서 이미지가 완성되면 이미지를, 아직이면 None을 반환한다.
        """


@runtime_checkable
class AnomalyDetector(Protocol):
    """세션 이미지를 이상/정상으로 분류한다."""

    def classify(self, session_id: int, image: Any) -> Detection: ...


@runtime_checkable
class PacketSource(Protocol):
    """탐지 경로에 프레임을 공급한다 (운영: AF_PACKET, 테스트: 리스트)."""

    def frames(self) -> Iterator[bytes]: ...

    def close(self) -> None: ...
