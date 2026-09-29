"""
auth_converter.py — auth 서비스 전용 Traffic Converter (이중 라우팅 버전).

네이티브 표현: flow (SVC_KIND["auth"] == "flow")

라우팅:
  payload 내용과 무관하게 **항상 flow 메타 벡터**. 목적지 포트 분기가 없다.
  즉 원본 converter.py 가 backend/frontend 에서만 하던 '이중 라우팅'은 이 서비스에 해당되지 않는다.
  (포트는 라우팅 조건이 아니라 flow_features 의 f0-f4/f17 특징값으로만 쓰인다.)

extract() 는 None 을 반환하지 않는다 → 모든 egress 패킷이 이미지화 대상이다.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from converter_common import (
    BaseConverter, Packet,
    flow_features,
)


class AuthConverter(BaseConverter):

    SERVICE = "auth"
    KIND = "flow"

    def extract(self, pkt: Packet) -> Optional[Tuple[np.ndarray, bool]]:
        # (a) 항상 flow 메타. 분기 없음.
        base = flow_features(pkt.dst_port, pkt.tcp_flags, pkt.payload, pkt.iplen)
        isreq = self._is_request(pkt, "flow")

        # (b) 공통 시간특징(f18/f19) 부여
        return self._finish(pkt, base, isreq)


Converter = AuthConverter          # 서비스 파일 안에서의 관용 별칭
