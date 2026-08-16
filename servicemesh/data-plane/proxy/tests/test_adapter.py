# -*- coding: utf-8 -*-
"""종단 어댑터 — 프레임 하나가 나가고 판정 하나가 돌아오는 계약."""

import pytest

from traffic_handler.adapter import (
    DetectionAdapter, FusedDetectionAdapter, NullDetectionAdapter,
)
from traffic_handler.ports import Detection

FRAME = b"\x00" * 60


class RecordingConverter:
    max_sessions = 4096

    def __init__(self, images):
        self.images = list(images)
        self.calls = []

    def push(self, session_id, frame):
        self.calls.append((session_id, frame))
        return self.images.pop(0) if self.images else None


class RecordingDetector:
    def __init__(self, result=Detection(is_malicious=True, score=-0.7)):
        self.result = result
        self.calls = []

    def classify(self, session_id, image):
        self.calls.append((session_id, image))
        return self.result


class TestDetectionAdapter:
    def test_윈도우가_안_차면_판정기를_부르지_않는다(self):
        detector = RecordingDetector()
        adapter = DetectionAdapter(RecordingConverter([None]), detector)

        assert adapter.analyze(7, FRAME) is None
        assert detector.calls == []

    def test_이미지가_나오면_판정을_돌려준다(self):
        adapter = DetectionAdapter(RecordingConverter(["img"]), RecordingDetector())
        detection = adapter.analyze(7, FRAME)

        assert detection.is_malicious
        assert detection.score == -0.7

    def test_핸들러가_준_세션_id를_그대로_전달한다(self):
        converter = RecordingConverter(["img"])
        detector = RecordingDetector()
        DetectionAdapter(converter, detector).analyze(1234, FRAME)

        assert converter.calls[0][0] == 1234
        assert detector.calls[0] == (1234, "img")

    def test_max_sessions를_변환기에서_가져온다(self):
        assert DetectionAdapter(RecordingConverter([]), RecordingDetector()).max_sessions == 4096

    def test_탐지가_터져도_판정_없음으로_흡수한다(self):
        class Broken:
            max_sessions = 1024

            def push(self, session_id, frame):
                raise RuntimeError("boom")

        # 탐지 고장이 트래픽 중계를 끊으면 안 된다 (판정 없음 = Forward)
        assert DetectionAdapter(Broken(), RecordingDetector()).analyze(1, FRAME) is None


class TestFusedDetectionAdapter:
    def test_한_호출로_끝나는_구현을_받는다(self):
        class Engine:
            max_sessions = 65536

            def analyze(self, session_id, frame):
                return Detection(is_malicious=True, score=-1.0)

        adapter = FusedDetectionAdapter(Engine())
        assert adapter.max_sessions == 65536
        assert adapter.analyze(1, FRAME).is_malicious

    def test_process_frame_이름도_받는다(self):
        class Engine:
            MAX_SESSIONS = 65536

            def process_frame(self, frame):
                return (7, True, -0.5)  # (session_id, is_malicious, score)

        adapter = FusedDetectionAdapter(Engine())
        assert adapter.max_sessions == 65536
        detection = adapter.analyze(7, FRAME)
        assert detection.is_malicious
        assert detection.score == -0.5

    def test_윈도우_미충족은_None으로_돌아온다(self):
        class Engine:
            def analyze(self, session_id, frame):
                return None

        assert FusedDetectionAdapter(Engine()).analyze(1, FRAME) is None

    def test_analyze도_process_frame도_없으면_거부한다(self):
        with pytest.raises(TypeError):
            FusedDetectionAdapter(object())


class TestResultShapes:
    """판정 반환 형식을 여러 개 허용한다 — 규격 협의 전에도 붙일 수 있게."""

    @pytest.mark.parametrize("result, expected_malicious, expected_score", [
        (Detection(is_malicious=True, score=-0.2), True, -0.2),
        ((True, -0.2), True, -0.2),
        ((7, True, -0.2), True, -0.2),
        ({"is_malicious": True, "score": -0.2}, True, -0.2),
        (True, True, 0.0),
        (False, False, 0.0),
    ])
    def test_해석한다(self, result, expected_malicious, expected_score):
        class Engine:
            def analyze(self, session_id, frame):
                return result

        detection = FusedDetectionAdapter(Engine()).analyze(1, FRAME)
        assert detection.is_malicious is expected_malicious
        assert detection.score == expected_score

    def test_해석할_수_없는_형식은_판정_없음으로_떨어진다(self):
        class Engine:
            def analyze(self, session_id, frame):
                return "이상함"

        assert FusedDetectionAdapter(Engine()).analyze(1, FRAME) is None


def test_탐지_모듈이_없으면_항상_판정_없음():
    adapter = NullDetectionAdapter()
    assert adapter.analyze(1, FRAME) is None
    assert adapter.max_sessions == 1024
