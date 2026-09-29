"""
frontend_converter.py — frontend 서비스 전용 Traffic Converter (이중 라우팅 버전).

네이티브 표현: frontend (SVC_KIND["frontend"] == "frontend")

라우팅 — ★ '이중 라우팅' 지점:
  1) 목적지가 NEVER_BENIGN_FLOW_PORTS({443, 6443, 22, 9000}) 이면 payload 무시하고 flow 메타.
     (backend 와 동일한 이유: benign 분포에 없는 표현 → OOD 확정 + 추론 게이트 역할)
  2) HTTP 요청줄 → fe_features, is_request=True
  3) HTTP 상태줄 → fe_features, is_request=False
     ★ backend 와 달리 **응답도 이미지화한다**. r1(응답 위조) 시나리오와, 핸들러의
       분기 2-2(Pod Info Provider relay 트리거)가 이 경로에 의존한다.
  4) 나머지(ACK 등) → None = forward
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from converter_common import (
    BaseConverter, Packet,
    NEVER_BENIGN_FLOW_PORTS, _REQ_LINE, _STATUS_LINE,
    flow_features, fe_features,
)


class FrontendConverter(BaseConverter):

    SERVICE = "frontend"
    KIND = "frontend"

    def extract(self, pkt: Packet) -> Optional[Tuple[np.ndarray, bool]]:
        payload = pkt.payload

        # (a) 이중 라우팅
        if pkt.dst_port in NEVER_BENIGN_FLOW_PORTS:          # 정상이 안 쓰는 공격 포트 → flow
            base = flow_features(pkt.dst_port, pkt.tcp_flags, payload, pkt.iplen)
            isreq = self._is_request(pkt, "flow")
        elif _REQ_LINE.match(payload):                       # 요청
            base, isreq = fe_features(payload), True
        elif _STATUS_LINE.match(payload):                    # 응답(frontend 만 이미지화)
            base, isreq = fe_features(payload), False
        else:
            return None                                      # ACK 등 → forward

        # (b) 공통 시간특징(f18/f19) 부여
        return self._finish(pkt, base, isreq)


Converter = FrontendConverter       # 서비스 파일 안에서의 관용 별칭
