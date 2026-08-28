# -*- coding: utf-8 -*-
"""텔레메트리 발신 — 판정 결과를 대시보드 백엔드로 보낸다.

계약은 TELEMETRY_API.md 참고. 핵심 성질:
  - 데이터 경로와 분리된다. 판정은 즉시 큐에 넣고 별도 태스크가 배치 전송한다.
    백엔드가 죽거나 느려도 트래픽 중계는 멈추지 않는다.
  - DASHBOARD_URL이 없으면 통째로 비활성이다. emit/incr은 조용히 무시된다.
  - 큐가 가득 차면 오래된 것부터 버린다(최신 관측 우선).
  - benign은 목적지별로도 센다(peerStats). 대시보드가 평시 엣지를 그리는 유일한 근거다 —
    cleared/drop/relay는 events가 dstIp와 함께 나르지만 benign은 개별 이벤트가 없다.

카운터와 큐는 탐지 스레드(benign 집계)와 프록시 코루틴(이벤트 emit) 양쪽에서 접근하므로
thread-safe여야 한다. 전송 루프만 asyncio다.
"""

import asyncio
import logging
import threading
from collections import deque
from datetime import datetime

import aiohttp

logger = logging.getLogger("traffic-handler.telemetry")

CATEGORIES = ("benign", "cleared", "drop", "relay")

# peerStats 슬롯 상한. 평시 목적지는 형제 서비스·mysql·DNS 정도라 10개 안쪽이고, 스캔은
# benign이 아니라 attack 판정을 만들어 여기로 오지 않는다. 그래도 모델이 스캔을 놓쳐
# benign으로 흘리면 키가 퍼질 수 있어 안전망을 둔다. 차면 새 목적지는 OTHER_PEER로 접고,
# 접힌 개수는 peerCount가 드러낸다.
MAX_PEERS = 64
OTHER_PEER = "other"


def _ip_to_int(ip):
    a, b, c, d = (int(x) for x in ip.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def session_label(src_ip, src_port, dst_ip, dst_port):
    """방향에 무관한 세션 라벨. 같은 세션의 요청·응답이 같은 값이 되도록 XOR로 만든다."""
    key = _ip_to_int(src_ip) ^ _ip_to_int(dst_ip) ^ src_port ^ dst_port
    return "s-{:08x}".format(key & 0xFFFFFFFF)


def _now_iso():
    return datetime.now().astimezone().isoformat()


class TelemetryClient:
    def __init__(self, url, proxy_meta, interval=1.0, queue_max=10000, timeout=2.0):
        self._enabled = bool(url)
        self._url = "{}/ingest/events".format(url.rstrip("/")) if url else None
        self._proxy = proxy_meta
        self._interval = interval
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._lock = threading.Lock()
        self._events = deque(maxlen=queue_max)
        self._counts = {c: 0 for c in CATEGORIES}
        # 목적지 -> benign 수. 키는 dstIp 문자열(또는 OTHER_PEER).
        self._peer_benign = {}
        # 이번 창에서 관측한 서로 다른 목적지 수. 상한에 걸려 접힌 것도 센다 —
        # 이 값이 갑자기 커지는 것 자체가 스캔 신호다.
        self._peer_seen = set()
        self._window_start = _now_iso()
        self._session = None

    @property
    def enabled(self):
        return self._enabled

    # -- 생산자 (아무 스레드에서나 호출) -------------------------------------

    def incr(self, category, peer=None):
        """집계 카운터만 올린다. benign처럼 개별 이벤트가 없는 분류에 쓴다.

        peer(목적지 IP)를 주면 목적지별 집계도 함께 올린다. benign에만 의미가 있다 —
        나머지 분류는 events가 dstIp를 들고 오므로 여기서 또 세면 같은 사실이 두 경로로
        갈라진다.
        """
        if not self._enabled:
            return
        with self._lock:
            self._counts[category] = self._counts.get(category, 0) + 1
            if peer is not None and category == "benign":
                self._count_peer(peer)

    def _count_peer(self, peer):
        """호출부는 _lock을 잡고 있어야 한다."""
        self._peer_seen.add(peer)
        if peer not in self._peer_benign and len(self._peer_benign) >= MAX_PEERS:
            peer = OTHER_PEER   # 슬롯이 찼다. 창이 끝날 때까지 나머지는 여기로 모은다
        self._peer_benign[peer] = self._peer_benign.get(peer, 0) + 1

    def emit(self, event):
        """개별 이벤트를 큐에 넣고 해당 분류를 집계한다 (cleared/drop/relay)."""
        if not self._enabled:
            return
        with self._lock:
            self._counts[event["category"]] = self._counts.get(event["category"], 0) + 1
            self._events.append(event)

    # -- 소비자 (asyncio 전송 루프) ------------------------------------------

    async def run(self):
        if not self._enabled:
            return
        self._session = aiohttp.ClientSession()
        try:
            while True:
                await asyncio.sleep(self._interval)
                await self._flush()
        finally:
            if self._session is not None:
                await self._session.close()

    async def _flush(self):
        with self._lock:
            has_stats = any(self._counts.values())
            if not self._events and not has_stats:
                return
            events = list(self._events)
            self._events.clear()
            counts = dict(self._counts)
            for c in self._counts:
                self._counts[c] = 0
            peer_benign = dict(self._peer_benign)
            peer_count = len(self._peer_seen)
            self._peer_benign.clear()
            self._peer_seen.clear()
            window_start, self._window_start = self._window_start, _now_iso()

        payload = {
            "proxy": self._proxy,
            "windowStats": {
                "from": window_start,
                "to": self._window_start,
                **{c: counts.get(c, 0) for c in CATEGORIES},
            },
            # 목적지별 benign. windowStats.benign의 내역이며 합이 같다(상한에 걸려도
            # other로 접힐 뿐 유실되지 않는다).
            "peerStats": [
                {"dstIp": ip, "benign": n} for ip, n in sorted(peer_benign.items())
            ],
            "peerCount": peer_count,
            "events": events,
        }
        try:
            async with self._session.post(self._url, json=payload, timeout=self._timeout) as resp:
                if resp.status >= 300:
                    logger.warning("텔레메트리 전송 실패 status=%d (배치 폐기)", resp.status)
        except Exception as exc:
            # 재전송하지 않는다 — 신선도 우선, 순서 꼬임 방지
            logger.warning("텔레메트리 전송 실패(%s) — 배치 폐기", exc)


def build_event(observation, verdict, category, stage, passed, signature, protocol="TCP"):
    """SessionObservation과 집행 결과로 이벤트 dict를 만든다.

    peerServiceName·eventId·summary는 넣지 않는다 — 백엔드가 채운다(TELEMETRY_API.md).
    """
    return {
        "occurredAt": _now_iso(),
        "direction": observation.direction,
        "sessionId": session_label(
            observation.src_ip, observation.src_port,
            observation.dst_ip, observation.dst_port,
        ),
        "srcIp": observation.src_ip, "srcPort": observation.src_port,
        "dstIp": observation.dst_ip, "dstPort": observation.dst_port,
        "protocol": protocol,
        "modelVerdict": "ATTACK",
        "ocsvmScore": observation.score,
        "verdict": verdict,
        "category": category,
        "verificationStage": stage,
        "verificationPassed": passed,
        # 모델 추론 시간(ms). 어댑터가 classify 호출 전후로 잰다(adapter.py).
        "detectionLatencyMs": round(getattr(observation, "latency_ms", 0.0), 4),
        "signature": signature,
    }
