# -*- coding: utf-8 -*-
"""탐지 모듈 결합 — vendoring한 Converter/Detector가 어댑터 규약에 맞는지.

세 층으로 나뉜다. 아래로 갈수록 필요한 것이 늘어난다.

    1. 래퍼 자체의 계약      의존성 없음 (대역으로 검증)
    2. 실제 컨버터와의 결합   numpy 필요
    3. 실제 모델 추론        numpy·torch·scikit-learn과 MODEL_ROOT 가중치 필요

가중치는 이미지에 굽지 않고 PVC로 주입하므로(detection/README.md), 3층은 MODEL_ROOT를
실제 가중치 디렉터리로 지정했을 때만 돈다.
"""

import os

import pytest

from conftest import make_frame
from traffic_handler import config
from traffic_handler.detection_binding import (
    ModelConverter, ModelDetector, _resolve_code_root,
)

WIN_SIZE = 5
MAX_SESSIONS = 65536


# ── 1층: 래퍼 자체의 계약 ────────────────────────────────────────────────────

class FakePacket:
    def __init__(self, *fields):
        self.fields = fields


class FakeCommon:
    """converter_common의 최소 대역. 파싱 결과를 시험이 직접 지정한다."""

    WIN_SIZE = WIN_SIZE
    MAX_SESSIONS = MAX_SESSIONS
    Packet = FakePacket

    def __init__(self, parsed=(1, 2, 3, 8080, 0x18, b"", 60)):
        self.parsed = parsed

    def frame_info(self, frame):
        return self.parsed


class FakeConverter:
    """extract가 항상 같은 벡터를 내놓고, to_image는 받은 벡터를 그대로 돌려준다."""

    def __init__(self, vector="v", extract_result=...):
        self.vector = vector
        self.extract_result = extract_result
        self.images = []

    def extract(self, packet):
        if self.extract_result is not ...:
            return self.extract_result
        return (self.vector, True)

    def to_image(self, vectors):
        self.images.append(list(vectors))
        return list(vectors)


class FakeVerdict:
    def __init__(self, is_benign, score):
        self.is_benign = is_benign
        self.score = score


class FakeDetector:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = []

    def detect(self, session_id, image):
        self.calls.append((session_id, image))
        return self.verdict


def build(common=None, converter=None, window_cap=4096):
    return ModelConverter(converter or FakeConverter(), common or FakeCommon(), window_cap)


class TestModelConverter:
    def test_윈도우가_찰_때까지_None을_돌려준다(self):
        converter = build()
        for _ in range(WIN_SIZE - 1):
            assert converter.push(7, b"frame") is None

    def test_윈도우가_차면_이미지를_돌려준다(self):
        converter = build()
        for _ in range(WIN_SIZE - 1):
            converter.push(7, b"frame")
        image = converter.push(7, b"frame")
        assert image == ["v"] * WIN_SIZE

    def test_윈도우가_찬_뒤에는_매_프레임마다_이미지가_나온다(self):
        converter = build()
        for _ in range(WIN_SIZE):
            converter.push(7, b"frame")
        assert converter.push(7, b"frame") is not None

    def test_가장_오래된_벡터가_밀려난다(self):
        """Algorithm 1 line 24 RemoveOldest — 이미지는 항상 최근 5개다."""
        inner = FakeConverter()
        converter = build(converter=inner)
        for i in range(WIN_SIZE + 2):
            inner.vector = "v{}".format(i)
            converter.push(7, b"frame")
        assert inner.images[-1] == ["v2", "v3", "v4", "v5", "v6"]

    def test_파싱되지_않는_프레임은_None이다(self):
        common = FakeCommon()
        common.parsed = None
        assert build(common=common).push(7, b"\x00") is None

    def test_탐지_대상이_아닌_패킷은_윈도우에_쌓이지_않는다(self):
        """extract가 None이면 그 패킷은 없던 것으로 친다 — 그대로 Forward된다."""
        inner = FakeConverter(extract_result=None)
        converter = build(converter=inner)
        for _ in range(WIN_SIZE * 2):
            assert converter.push(7, b"frame") is None
        assert inner.images == []

    def test_세션마다_윈도우가_따로_찬다(self):
        converter = build()
        for _ in range(WIN_SIZE - 1):
            converter.push(7, b"frame")
        assert converter.push(99, b"frame") is None

    def test_수신_시각이_Packet에_들어간다(self):
        """f18(Δt)·f19(윈도우 볼륨)가 이 값을 쓴다. 빠지면 두 축이 죽는다."""
        seen = []
        inner = FakeConverter()
        inner.extract = lambda packet: seen.append(packet) or ("v", True)
        build(converter=inner).push(7, b"frame")
        assert seen[0].fields[-1] > 0


class TestModelConverter윈도우메타:
    """판정 화면이 보여줄 패킷 메타. 모델이 본 그 윈도우와 정확히 같아야 한다."""

    def test_윈도우가_차기_전에도_쌓인_만큼_돌려준다(self):
        converter = build()
        converter.push(7, b"frame")
        converter.push(7, b"frame")
        assert len(converter.window_meta(7)) == 2

    def test_판정_시점의_메타는_윈도우_크기와_같다(self):
        converter = build()
        for _ in range(WIN_SIZE):
            converter.push(7, b"frame")
        meta = converter.window_meta(7)
        assert len(meta) == WIN_SIZE
        assert [m["seq"] for m in meta] == list(range(1, WIN_SIZE + 1))

    def test_extract가_거른_프레임은_메타에도_없다(self):
        """벡터와 메타를 따로 쌓으면 여기서 길이가 어긋난다."""
        converter = build(converter=FakeConverter(extract_result=None))
        for _ in range(WIN_SIZE):
            converter.push(7, b"frame")
        assert converter.window_meta(7) == ()

    def test_파싱한_필드가_메타에_그대로_담긴다(self):
        # frame_info: (sid, src_ip, dst_ip, dst_port, tcp_flags, payload, iplen)
        common = FakeCommon(parsed=(1, 2, 0x0AF40225, 8080, 0x18, b"hello", 60))
        converter = build(common=common)
        converter.push(7, b"frame")
        meta = converter.window_meta(7)[0]
        assert meta["dstIp"] == "10.244.2.37"
        assert meta["dstPort"] == 8080
        assert meta["flags"] == "PSH,ACK"
        assert meta["length"] == 60
        assert meta["payloadLength"] == 5
        assert "hello" not in str(meta)   # 본문은 담지 않는다

    def test_모르는_세션은_빈_튜플(self):
        assert build().window_meta(999) == ()


class TestModelConverter세션상한:
    def test_상한을_넘으면_오래된_세션부터_버린다(self):
        converter = build(window_cap=2)
        for session_id in (1, 2, 3):
            converter.push(session_id, b"frame")
        assert set(converter._windows) == {2, 3}

    def test_최근에_쓴_세션은_남는다(self):
        converter = build(window_cap=2)
        converter.push(1, b"frame")
        converter.push(2, b"frame")
        converter.push(1, b"frame")  # 1을 다시 씀 -> 2가 더 오래된 쪽이 된다
        converter.push(3, b"frame")
        assert set(converter._windows) == {1, 3}

    def test_max_sessions는_버퍼_상한과_무관하다(self):
        """세션 id 모듈로 값이다. 버퍼 용량으로 대신 쓰면 프록시와 id가 어긋난다."""
        assert build(window_cap=2).max_sessions == MAX_SESSIONS


class TestModelDetector:
    def test_benign은_is_malicious가_False다(self):
        detector = ModelDetector(FakeDetector(FakeVerdict(is_benign=True, score=1.5)))
        detection = detector.classify(7, "image")
        assert detection.is_malicious is False
        assert detection.score == 1.5

    def test_anomaly는_is_malicious가_True다(self):
        detector = ModelDetector(FakeDetector(FakeVerdict(is_benign=False, score=-2.0)))
        detection = detector.classify(7, "image")
        assert detection.is_malicious is True
        assert detection.score == -2.0

    def test_세션_id와_이미지를_그대로_넘긴다(self):
        inner = FakeDetector(FakeVerdict(is_benign=True, score=0.0))
        ModelDetector(inner).classify(42, "image")
        assert inner.calls == [(42, "image")]


class Test코드루트:
    def test_리포지토리에서_탐지_모듈을_찾는다(self):
        root = _resolve_code_root()
        assert os.path.isfile(os.path.join(root, "converter_common.py"))
        assert os.path.isfile(os.path.join(root, "detector.py"))


# ── 2층: 실제 컨버터와의 결합 (numpy 필요) ──────────────────────────────────

@pytest.fixture(scope="module")
def real_common():
    pytest.importorskip("numpy", reason="탐지 모듈은 numpy를 요구한다")
    from traffic_handler.detection_binding import _load_module_code
    return _load_module_code()[1]


@pytest.mark.parametrize("service", ["auth", "post", "comment", "frontend"])
class Test실제컨버터:
    @staticmethod
    def _converter(service, common, window_cap=4096):
        import importlib
        module = importlib.import_module("{0}.{0}_converter".format(service))
        return ModelConverter(module.Converter(), common, window_cap)

    def test_윈도우가_차면_20x5_이미지가_나온다(self, service, real_common):
        converter = self._converter(service, real_common)
        frame = make_frame("10.0.0.5", "10.0.0.9", 40000, 8080,
                           b"GET /api/posts/1 HTTP/1.1\r\nHost: x\r\n\r\n")
        images = [converter.push(1234, frame) for _ in range(WIN_SIZE)]
        assert images[:-1] == [None] * (WIN_SIZE - 1)
        assert images[-1].shape == (real_common.FEAT_LEN, real_common.WIN_SIZE)

    def test_세션_id가_프록시_계산과_일치한다(self, service, real_common):
        """양쪽이 같은 5-tuple XOR 식을 쓴다. 어긋나면 판정이 엉뚱한 세션에 붙는다."""
        from traffic_handler.ports import SessionKey
        converter = self._converter(service, real_common)
        key = SessionKey("10.0.0.5", "10.0.0.9", 40000, 8080)
        frame = make_frame(key.src_ip, key.dst_ip, key.src_port, key.dst_port, b"GET / HTTP/1.1\r\n\r\n")
        assert real_common.frame_info(frame)[0] == key.session_id(converter.max_sessions)

    def test_짧은_프레임은_None이다(self, service, real_common):
        assert self._converter(service, real_common).push(1, b"\x00" * 20) is None


# ── 3층: 실제 모델 추론 (가중치 필요) ────────────────────────────────────────

def _weights_ready(service):
    return os.path.isdir(os.path.join(config.MODEL_ROOT, service, "{}_model".format(service)))


@pytest.mark.parametrize("service", ["auth", "post", "comment", "frontend"])
class Test실제모델:
    def test_로드해서_판정까지_간다(self, service, real_common):
        pytest.importorskip("torch")
        pytest.importorskip("sklearn")
        if not _weights_ready(service):
            pytest.skip("MODEL_ROOT={}에 {} 가중치가 없다".format(config.MODEL_ROOT, service))

        import importlib
        module = importlib.import_module("{0}.{0}_converter".format(service))
        converter = ModelConverter(module.Converter(), real_common, 4096)
        detector = ModelDetector(
            importlib.import_module("detector").Detector(service, models_root=config.MODEL_ROOT)
        )
        frame = make_frame("10.0.0.5", "10.0.0.9", 40000, 8080,
                           b"GET /api/posts/1 HTTP/1.1\r\nHost: x\r\n\r\n")
        image = None
        for _ in range(WIN_SIZE):
            image = converter.push(1234, frame)
        detection = detector.classify(1234, image)
        assert isinstance(detection.is_malicious, bool)
        assert isinstance(detection.score, float)
