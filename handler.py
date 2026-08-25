"""
handler.py — 런타임 Traffic Handler (서비스별, 세션 하나만 고려).

핸들러-컨버터-디텍터 관계(사용자 확정 [참고 내용]):
  1) 핸들러가 세션의 5패킷 슬라이딩 윈도우를 채운다(이 데모는 서비스당 세션 1개 = 단일 버퍼).
     · 각 패킷을 converter.extract 로 (벡터, is_request) 로 만든다. None 이면 탐지 대상 아님 -> 그대로 forward.
     · 윈도우가 5개로 차면(stride=1 이므로 이후 매 패킷마다) 그 5벡터를 converter 로 넘긴다.
     · 이때 핸들러는 '가장 최근 패킷의 is_request' 를 세션 id 와 엮어 내부 저장한다.
       is_request==False(응답)이면 정합하는 inbound 요청을 함께 합성·저장한다(relay 참조용).
  2) converter 가 이미지화 후 detector 로 직접 전달하고, 판정(session_id, is_benign)이 핸들러로 돌아온다.
  3) 핸들러가 <session_id + 결과> 와 내부 <session_id + is_request> 를 매치해 분기한다:
       분기 1  benign            -> forward
       분기 2  anomaly + 요청     -> "Request Verifier 에 해당 요청 기록"
       분기 2  anomaly + 응답     -> "Pod Info Provider 의 relay 로직 트리거"

emit 주기(stride): converter.stride 를 따른다. 런타임=1 -> 윈도우가 찬 뒤 매 패킷마다 새 이미지.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional, List, Dict

import numpy as np

from converter import Converter, Packet, WIN_SIZE

# 분기 결과(액션 문자열)
ACT_FORWARD = "forward"
ACT_RECORD_REQUEST = "record_request_in_request_verifier"   # 분기 2-1
ACT_TRIGGER_RELAY = "trigger_pod_info_provider_relay"       # 분기 2-2


@dataclass
class InboundRequest:
    """응답 패킷에 대해 핸들러가 합성한 '정합 inbound 요청'(relay 재실행 참조용, 데모 플레이스홀더)."""
    session_id: int
    method: str
    path: str
    note: str = "synthesized to match the stacked response window"


@dataclass
class HandlerEvent:
    session_id: int
    image_built: bool                 # 이번 패킷으로 (20,5) 이미지가 만들어졌는지
    action: str                       # ACT_* 중 하나
    is_benign: Optional[bool] = None  # image_built 일 때만 유효
    score: Optional[float] = None
    threshold: Optional[float] = None
    is_request: Optional[bool] = None # 윈도우 최신 패킷의 방향
    image: Optional[np.ndarray] = None
    inbound_request: Optional[InboundRequest] = None
    dst_port: Optional[int] = None


class Handler:
    def __init__(self, service: str, converter: Converter, win_size: int = WIN_SIZE):
        self.service = service
        self.converter = converter
        self.win = win_size
        self.session_label = f"{service}-sess0"     # 서비스당 세션 하나
        self._buf: deque = deque(maxlen=win_size)   # (vec, is_request, pkt)
        self._n_kept = 0                            # extract 로 유지된 패킷 수(윈도우 채운 수)
        # 내부 저장: 세션 -> 최신 is_request / 합성 inbound 요청
        self.session_is_request: Dict[str, bool] = {}
        self.inbound_requests: Dict[str, InboundRequest] = {}

    def reset(self) -> None:
        """새 시퀀스 시작 전 버퍼/카운터 초기화(노트북에서 (a)/(b) 구간 분리용)."""
        self._buf.clear()
        self._n_kept = 0

    # 응답일 때 정합 inbound 요청 합성(데모: 이 응답을 유발했을 요청의 플레이스홀더)
    def _synthesize_inbound_request(self, pkt: Packet) -> InboundRequest:
        return InboundRequest(session_id=hash(self.session_label) & 0xffffffff,
                              method="GET", path="/")

    def on_packet(self, pkt: Packet) -> Optional[HandlerEvent]:
        """패킷 하나 투입. 이미지가 만들어지면 판정+분기까지 수행한 HandlerEvent 를,
        아직 윈도우가 안 찼거나 stride 로 skip 이면 None(단, 탐지 제외 패킷은 forward 이벤트) 반환."""
        res = self.converter.extract(pkt)
        if res is None:
            # 탐지 대상 아님(backend :8080 응답/ACK 등) -> 그대로 forward
            return HandlerEvent(session_id=self.session_label, image_built=False,
                                action=ACT_FORWARD, dst_port=pkt.dst_port)

        vec, is_request = res
        self._buf.append((vec, is_request, pkt))
        self._n_kept += 1

        # stride 기반 emit: 윈도우가 처음 찬 뒤(=n_kept>=win) stride 마다 이미지 생성
        stride = max(1, getattr(self.converter, "stride", 1))
        if self._n_kept < self.win or ((self._n_kept - self.win) % stride != 0):
            return None  # 아직 이미지 아님

        # ── 윈도우 완성 → 이미지화/판정 ──
        window_vecs = [v for (v, _r, _p) in self._buf]
        newest_is_request = is_request     # 최신 패킷 = 방금 추가한 pkt

        # 내부 저장: 세션-방향, 응답이면 inbound 요청 합성
        self.session_is_request[self.session_label] = newest_is_request
        inbound = None
        if not newest_is_request:
            inbound = self._synthesize_inbound_request(pkt)
            self.inbound_requests[self.session_label] = inbound

        # converter -> detector (핸들러 경유 X). 판정만 되돌려받음.
        result = self.converter.process(self.session_label_id(), window_vecs)

        # ── 분기 ──
        if result.is_benign:
            action = ACT_FORWARD
        else:
            action = ACT_RECORD_REQUEST if newest_is_request else ACT_TRIGGER_RELAY

        return HandlerEvent(
            session_id=self.session_label, image_built=True, action=action,
            is_benign=result.is_benign, score=result.score, threshold=result.threshold,
            is_request=newest_is_request, image=result.image,
            inbound_request=inbound, dst_port=pkt.dst_port,
        )

    def session_label_id(self) -> int:
        return hash(self.session_label) & 0xffffffff

    # 분기 액션 -> 사람이 읽는 출력 문자열
    @staticmethod
    def action_text(ev: HandlerEvent) -> str:
        if ev.action == ACT_FORWARD:
            if not ev.image_built:
                return "forward (탐지 대상 아님: 버퍼에 쌓지 않고 통과)"
            return "forward (benign 판정)"
        if ev.action == ACT_RECORD_REQUEST:
            return "anomaly(요청) → Request Verifier 에 해당 요청 기록"
        if ev.action == ACT_TRIGGER_RELAY:
            return "anomaly(응답) → Pod Info Provider 의 relay 로직 트리거"
        return ev.action