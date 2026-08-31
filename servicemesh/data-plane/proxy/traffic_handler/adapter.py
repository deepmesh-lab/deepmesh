# -*- coding: utf-8 -*-
"""종단 어댑터 — Traffic Handler와 탐지 모듈 사이의 단 하나의 접점.

Traffic Handler는 Traffic Converter도 Anomaly Detector도 직접 알지 않는다. 아래 한
메서드만 안다.

    analyze(session_id, frame) -> Detection | None

        frame       메인 컨테이너가 주고받은 완전한 Ethernet 프레임 1개
        session_id  Traffic Handler가 계산한 세션 식별자
        반환         세션 판정. 아직 윈도우가 안 찼으면 None

즉 나가는 것은 프레임 하나, 돌아오는 것은 판정 하나다. 그 사이에서 세션 버퍼링·이미지
변환·모델 추론이 어떤 순서로 일어나든 Traffic Handler는 관여하지 않는다.

탐지 모듈이 던지는 예외는 여기서 흡수해 None으로 만든다. 탐지가 고장 나도 트래픽 중계는
멈추지 않아야 하기 때문이다 (판정 없음 = Forward).
"""

import inspect
import logging
import time

from .ports import Detection

logger = logging.getLogger("traffic-handler.adapter")

DEFAULT_MAX_SESSIONS = 1024


def _as_detection(result):
    """탐지 모듈의 반환값을 Detection으로 정규화한다.

    Detection, (is_malicious, score), (session_id, is_malicious, score),
    {"is_malicious": ..., "score": ...} 형태를 받아들인다.
    """
    if result is None:
        return None
    if isinstance(result, Detection):
        return result
    if isinstance(result, dict):
        return Detection(
            is_malicious=bool(result.get("is_malicious")),
            score=float(result.get("score", 0.0)),
        )
    if isinstance(result, (tuple, list)):
        if len(result) == 2:
            return Detection(is_malicious=bool(result[0]), score=float(result[1]))
        if len(result) == 3:
            return Detection(is_malicious=bool(result[1]), score=float(result[2]))
    if isinstance(result, bool):
        return Detection(is_malicious=result)
    raise TypeError("판정 형식을 해석할 수 없음: {!r}".format(type(result)))


def _with_latency(detection, latency_ms):
    """판정에 추론 지연을 실어 돌려준다. 이미 실려 있으면(0이 아니면) 유지한다."""
    if detection is None or detection.latency_ms:
        return detection
    from dataclasses import replace
    return replace(detection, latency_ms=latency_ms)


def _accepts_two_args(call):
    """호출부가 (session_id, frame)을 받는지 (frame)만 받는지 판별한다."""
    try:
        params = inspect.signature(call).parameters.values()
    except (TypeError, ValueError):
        return True  # 내장·C 확장 등 시그니처를 못 읽으면 표준 형태로 가정한다
    positional = [
        p for p in params
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    if any(p.kind is p.VAR_POSITIONAL for p in params):
        return True
    return len(positional) >= 2


class DetectionAdapter:
    """분리형 구현을 잇는다 — Converter가 이미지를 만들고 Detector가 판정한다.

    Converter가 None을 돌려주면(윈도우 미충족) Detector를 호출하지 않는다.
    """

    def __init__(self, converter, detector, max_sessions=None):
        self._converter = converter
        self._detector = detector
        self.max_sessions = max_sessions or getattr(
            converter, "max_sessions", DEFAULT_MAX_SESSIONS
        )

    def analyze(self, session_id, frame):
        try:
            image = self._converter.push(session_id, frame)
            if image is None:
                return None
            start = time.perf_counter()
            result = self._detector.classify(session_id, image)
            latency_ms = (time.perf_counter() - start) * 1000.0
            return _with_latency(_as_detection(result), latency_ms)
        except Exception:
            logger.exception("탐지 실패 — 판정 없음으로 처리(Forward)")
            return None


class FusedDetectionAdapter:
    """변환과 판정을 한 호출에서 끝내는 구현을 잇는다.

    엔진은 analyze / process_frame / __call__ 중 아무 이름이나 쓸 수 있다.
    세션 버퍼를 엔진이 직접 들고 있는 구조(C 파서 등)가 여기에 해당한다.
    """

    def __init__(self, engine, max_sessions=None):
        self._engine = engine
        self._call = self._resolve(engine)
        # 세션 id를 스스로 계산하는 구현(인자 1개)도 받아준다. 호출 후 재시도하지 않고
        # 시그니처로 미리 판별한다 — 세션 버퍼를 가진 구현에 프레임이 두 번 들어가면
        # 윈도우가 어긋난다.
        self._takes_session_id = _accepts_two_args(self._call)
        self.max_sessions = max_sessions or getattr(
            engine, "max_sessions", getattr(engine, "MAX_SESSIONS", DEFAULT_MAX_SESSIONS)
        )

    @staticmethod
    def _resolve(engine):
        for name in ("analyze", "process_frame"):
            method = getattr(engine, name, None)
            if callable(method):
                return method
        if callable(engine):
            return engine
        raise TypeError("analyze / process_frame 중 하나가 필요함")

    def analyze(self, session_id, frame):
        try:
            start = time.perf_counter()
            result = (
                self._call(session_id, frame) if self._takes_session_id else self._call(frame)
            )
            latency_ms = (time.perf_counter() - start) * 1000.0
            detection = _as_detection(result)
            return _with_latency(detection, latency_ms) if detection is not None else None
        except Exception:
            logger.exception("탐지 실패 — 판정 없음으로 처리(Forward)")
            return None


class NullDetectionAdapter:
    """탐지 모듈이 없을 때. 항상 판정 없음 → 모든 트래픽 Forward."""

    def __init__(self, max_sessions=DEFAULT_MAX_SESSIONS):
        self.max_sessions = max_sessions

    def analyze(self, session_id, frame):
        return None
