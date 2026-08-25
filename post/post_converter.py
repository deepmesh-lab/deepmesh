"""
post_converter.py — post 서비스 전용 Traffic Converter (이중 라우팅 버전).

네이티브 표현: backend (SVC_KIND["post"] == "backend")

라우팅 — ★ 여기가 '이중 라우팅'이 실제로 일어나는 지점:
  1) 목적지가 NEVER_BENIGN_FLOW_PORTS({443, 6443, 22, 9000}) 이면
     payload 를 보지 않고 flow 메타로 이미지화한다.
     · 정상 트래픽이 절대 쓰지 않는 포트이므로, benign 학습 분포에 flow 벡터가 사실상 없다.
       따라서 이 경로로 만들어진 이미지는 내용과 무관하게 OOD 로 잡힌다(k1/k2/c2/e1 탐지).
     · 동시에 이 검사는 '게이트' 역할을 한다. 아래 3)에서 대부분의 패킷을 파이프라인 밖으로
       밀어내기 때문에, 분기 비용(셋 조회 1회)보다 절약되는 추론 비용(윈도우당 CNN+OCSVM)이
       4~5자릿수 크다. 이 분기를 없애면 느려지는 이유가 이것이다.
  2) 그 외 HTTP 요청줄(:8080 등) → http_features.
  3) 나머지(HTTP 응답·ACK·비-HTTP) → None = 탐지 대상 아님 → 핸들러가 그대로 forward.

주의: :3306(mysql), :53(DNS) 은 NEVER_BENIGN_FLOW_PORTS 에 없다.
      정상 east-west 이므로 3)으로 떨어져 forward 된다. 의도된 동작이다.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from converter_common import (
    BaseConverter, Packet,
    NEVER_BENIGN_FLOW_PORTS, _REQ_LINE,
    flow_features, http_features,
)


class PostConverter(BaseConverter):

    SERVICE = "post"
    KIND = "backend"

    def extract(self, pkt: Packet) -> Optional[Tuple[np.ndarray, bool]]:
        payload = pkt.payload

        # (a) 이중 라우팅
        if pkt.dst_port in NEVER_BENIGN_FLOW_PORTS:          # 정상이 안 쓰는 공격 포트 → flow
            base = flow_features(pkt.dst_port, pkt.tcp_flags, payload, pkt.iplen)
            isreq = self._is_request(pkt, "flow")
        elif _REQ_LINE.match(payload):                       # HTTP 요청 → semantic
            base, isreq = http_features(payload), True
        else:
            return None                                      # 응답·ACK → forward

        # (b) 공통 시간특징(f18/f19) 부여
        return self._finish(pkt, base, isreq)


Converter = PostConverter          # 서비스 파일 안에서의 관용 별칭
