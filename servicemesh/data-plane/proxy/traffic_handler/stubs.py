# -*- coding: utf-8 -*-
"""Traffic Converter / Anomaly Detector 대역.

두 모듈이 완성되기 전까지 Traffic Handler의 분기를 테스트하기 위한 것이다.
탐지 모듈 없이 실행할 때는 이것들이 아니라 adapter.NullDetectionAdapter를 쓴다.
"""

from .ports import Detection


class WindowConverter:
    """세션별로 프레임 w개를 모아 리스트로 내놓는다 (논문의 슬라이딩 윈도우 흉내).

    이미지 형식은 Traffic Converter의 몫이므로 여기서는 만들지 않는다. Traffic Handler가
    윈도우 경계와 세션 분리를 제대로 다루는지 확인하는 용도다.
    """

    def __init__(self, window=5, max_sessions=1024):
        self.window = window
        self.max_sessions = max_sessions
        self._buffers = {}

    def push(self, session_id, frame):
        buffer = self._buffers.setdefault(session_id, [])
        buffer.append(frame)
        if len(buffer) < self.window:
            return None
        image = list(buffer)
        buffer.pop(0)  # Algorithm 1 line 24: RemoveOldest
        return image


class AlwaysNormalDetector:
    def classify(self, session_id, image):
        return Detection(is_malicious=False, score=1.0)


class ScriptedDetector:
    """지정한 세션만 이상으로 판정한다. Drop/Relay 분기 테스트용."""

    def __init__(self, malicious_sessions=()):
        self.malicious_sessions = set(malicious_sessions)

    def classify(self, session_id, image):
        malicious = session_id in self.malicious_sessions
        return Detection(is_malicious=malicious, score=-1.0 if malicious else 1.0)
