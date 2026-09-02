# -*- coding: utf-8 -*-
"""탐지 모듈 결합 — vendoring한 Converter/Detector를 어댑터 규약에 맞춘다.

adapter.py가 요구하는 것은 두 메서드다.

    converter.push(session_id, frame) -> image | None
    detector.classify(session_id, image) -> Detection

detection/ 쪽이 내놓는 것은 모양이 다르다.

    converter.extract(Packet)     -> (벡터, is_request) | None
    detector.detect(sid, image)   -> Verdict(is_benign=...)

원본은 고치지 않는다. converter_common.py 머리말이 특징 추출 블록을 수정 금지로 못박고
있고(모델이 정확히 그 특징으로 학습됐다), 재학습 산출물을 반입할 때마다 수정을 되살려야
하는 구조가 되기 때문이다. 그래서 간극은 전부 여기서 메운다.

    1. 프레임 -> Packet   frame_info로 5-tuple을 파싱하고 수신 시각을 붙인다. 시각은
                          f18(Δt)·f19(윈도우 볼륨)이 쓰는 값이라 빠지면 두 축이 죽는다.
    2. 윈도우            w=5가 찰 때까지 모으고, 찬 뒤에는 매 패킷마다 이미지를 낸다.
    3. 부호 반전         Verdict.is_benign -> Detection.is_malicious.

세션 id는 양쪽이 이미 같은 식을 쓴다 — (src ^ dst ^ sport ^ dport ^ 6) % max_sessions.
어댑터가 max_sessions를 컨버터에게서 받아 쓰므로(adapter.py), 여기서 컨버터 쪽
MAX_SESSIONS를 그대로 노출하면 프록시가 계산한 id와 converter_common이 계산한 id가
같은 값이 된다.
"""

import importlib
import logging
import os
import sys
import time
from collections import OrderedDict, deque

from . import config
from . import packets
from .ports import Detection

logger = logging.getLogger("traffic-handler.detection-binding")

# 탐지 모듈 코드 루트 후보. 리포지토리와 이미지의 깊이가 다르다 — 리포지토리는
# data-plane/{detection,proxy}/ 인데, Dockerfile이 proxy/ 내용을 /app에 펼치므로
# 이미지 안에서는 /app/{detection,traffic_handler}/ 가 된다.
_CODE_ROOT_CANDIDATES = ("../../detection", "../detection")


def _resolve_code_root():
    """vendoring한 탐지 모듈 코드의 디렉터리를 찾는다."""
    if config.DETECTION_CODE_ROOT:
        return config.DETECTION_CODE_ROOT
    here = os.path.dirname(os.path.abspath(__file__))
    for relative in _CODE_ROOT_CANDIDATES:
        candidate = os.path.normpath(os.path.join(here, relative))
        if os.path.isfile(os.path.join(candidate, "converter_common.py")):
            return candidate
    raise FileNotFoundError(
        "탐지 모듈 코드를 찾지 못함. 후보={} — DETECTION_CODE_ROOT로 직접 지정하세요".format(
            [os.path.normpath(os.path.join(here, r)) for r in _CODE_ROOT_CANDIDATES]
        )
    )


def _load_module_code():
    """코드 루트를 sys.path에 올리고 converter_common을 돌려준다.

    <svc>_converter.py가 `from converter_common import ...` 처럼 최상위 절대 import를
    쓰기 때문에 이 디렉터리를 패키지로 감쌀 수 없다. 경로에 올려두고 <svc>는 네임스페이스
    패키지로 불러온다.
    """
    root = _resolve_code_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    return root, importlib.import_module("converter_common")


class ModelConverter:
    """프레임을 세션별로 모아 (FEAT_LEN, WIN_SIZE) 이미지를 낸다."""

    def __init__(self, converter, common, window_cap):
        self._converter = converter
        self._common = common
        self._window_cap = window_cap
        self._windows = OrderedDict()
        # 프록시가 세션 id를 계산할 때 쓰는 모듈로. 컨버터 쪽과 같은 값이어야 두 id가
        # 일치한다. 아래 _window_cap(버퍼 용량)과 혼동하면 안 된다 — 다른 수다.
        self.max_sessions = common.MAX_SESSIONS

    def push(self, session_id, frame):
        parsed = self._common.frame_info(frame)
        if parsed is None:
            return None  # IPv4/TCP가 아니거나 헤더가 잘렸다
        sid, src_ip, dst_ip, dst_port, tcp_flags, payload, iplen = parsed

        # ts는 frame_info가 주지 않는 값이다. 학습 때는 pcap 타임스탬프였고 런타임에는
        # 프레임을 잡은 시각이 그 자리를 대신한다.
        # 캡처 시각은 지역 변수로 잡아 둔다. Packet에서 다시 꺼내 쓰면 Packet의 필드
        # 이름에 의존하게 되는데, 그건 컨버터 쪽 자료구조지 우리 것이 아니다.
        captured_at = time.time()
        packet = self._common.Packet(
            sid, src_ip, dst_ip, dst_port, tcp_flags, payload, iplen, captured_at
        )
        extracted = self._converter.extract(packet)
        if extracted is None:
            return None  # 탐지 대상 아님 -> 판정 없이 Forward

        window = self._window(session_id)
        # 벡터와 메타를 **같은 deque에 짝으로** 넣는다. 따로 두면 extract()가 걸러낸
        # 프레임 때문에 둘의 길이가 어긋나, 화면이 판정과 무관한 패킷을 보여주게 된다.
        window.append((extracted[0], packets.packet_meta(
            dst_ip, dst_port, tcp_flags, len(payload), iplen, captured_at,
        )))
        if len(window) < self._common.WIN_SIZE:
            return None
        # deque(maxlen=WIN_SIZE)라 가장 오래된 벡터는 append가 알아서 밀어낸다
        # (Algorithm 1 line 24, RemoveOldest).
        return self._converter.to_image([vector for vector, _ in window])

    def window_meta(self, session_id):
        """방금 판정에 쓰인 윈도우의 패킷 메타. 윈도우가 없으면 빈 튜플.

        push()가 이미지를 돌려준 직후에만 의미가 있다 — 그때의 deque 내용이 곧 모델에
        들어간 그 윈도우다.
        """
        window = self._windows.get(session_id)
        if not window:
            return ()
        return tuple(packets.numbered(meta for _, meta in window))

    def _window(self, session_id):
        window = self._windows.get(session_id)
        if window is not None:
            self._windows.move_to_end(session_id)
            return window
        window = deque(maxlen=self._common.WIN_SIZE)
        self._windows[session_id] = window
        # 세션 id가 % MAX_SESSIONS라 종류는 65,536개로 묶이지만, 사이드카가 그만큼 들고
        # 있을 이유는 없다. 오래 안 쓴 세션부터 버린다.
        while len(self._windows) > self._window_cap:
            self._windows.popitem(last=False)
        return window


class ModelDetector:
    """Verdict(is_benign)를 Detection(is_malicious)으로 바꾼다.

    두 값은 뜻이 반대다. 그대로 넘기면 판정이 통째로 뒤집힌다.
    """

    def __init__(self, detector):
        self._detector = detector

    def classify(self, session_id, image):
        verdict = self._detector.detect(session_id, image)
        return Detection(is_malicious=not verdict.is_benign, score=float(verdict.score))


def build_converter():
    """CONVERTER_FACTORY가 부르는 진입점."""
    root, common = _load_module_code()
    service = config.DETECTION_SERVICE
    module = importlib.import_module("{0}.{0}_converter".format(service))
    logger.info("Traffic Converter 적재 — service=%s, code=%s", service, root)
    return ModelConverter(module.Converter(), common, config.DETECTION_WINDOW_CAP)


def build_detector():
    """DETECTOR_FACTORY가 부르는 진입점."""
    _load_module_code()
    service = config.DETECTION_SERVICE
    detector = importlib.import_module("detector").Detector(
        service, models_root=config.MODEL_ROOT
    )
    logger.info(
        "Anomaly Detector 적재 — service=%s, weights=%s, encoder=%s, threshold=%.4f",
        service, detector.model_dir, detector.encoder_source, detector.threshold,
    )
    return ModelDetector(detector)
