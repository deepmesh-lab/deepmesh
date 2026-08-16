# -*- coding: utf-8 -*-
"""탐지 경로 — Algorithm 1 line 1~8."""

from conftest import make_frame

from traffic_handler.adapter import DetectionAdapter
from traffic_handler.detection import DetectionPipeline
from traffic_handler.packet_source import ListPacketSource
from traffic_handler.ports import SessionKey
from traffic_handler.stubs import AlwaysNormalDetector, ScriptedDetector, WindowConverter
from traffic_handler.verdicts import VerdictStore

TARGET_PORT = 8080
PROXY_PORT = 9011
WINDOW = 5


def build(detector, converter=None, frames=()):
    adapter = DetectionAdapter(converter or WindowConverter(window=WINDOW), detector)
    verdicts = VerdictStore(ttl=10.0)
    pipeline = DetectionPipeline(
        ListPacketSource(frames), adapter, verdicts, TARGET_PORT, PROXY_PORT
    )
    return pipeline, verdicts


def outbound_response_frame(payload=b"x"):
    """메인 컨테이너가 프록시로 돌려주는 응답 (탐지 대상)."""
    return make_frame("127.0.0.1", "127.0.0.1", TARGET_PORT, 41234, payload)


def inbound_frame(payload=b"x"):
    """프록시가 메인 컨테이너로 전달하는 요청 (탐지 대상 아님)."""
    return make_frame("127.0.0.1", "127.0.0.1", 41235, TARGET_PORT, payload)


def test_윈도우가_차기_전에는_판정이_나오지_않는다():
    pipeline, verdicts = build(AlwaysNormalDetector())
    for _ in range(WINDOW - 1):
        assert pipeline.process_frame(outbound_response_frame()) is None


def test_윈도우가_차면_판정이_기록된다():
    session = SessionKey("127.0.0.1", "127.0.0.1", TARGET_PORT, 41234)
    session_id = session.session_id(1024)

    pipeline, verdicts = build(ScriptedDetector({session_id}))
    for _ in range(WINDOW):
        detection = pipeline.process_frame(outbound_response_frame())

    assert detection.is_malicious
    assert verdicts.get(session_id).is_malicious


def test_판정에_방향과_5tuple이_함께_기록된다():
    session_id = SessionKey("127.0.0.1", "127.0.0.1", TARGET_PORT, 41234).session_id(1024)
    pipeline, verdicts = build(ScriptedDetector({session_id}))
    for _ in range(WINDOW):
        pipeline.process_frame(outbound_response_frame())

    obs = verdicts.get(session_id)
    assert obs.direction == "RESPONSE"        # src_port == TARGET_PORT
    assert obs.src_ip == "127.0.0.1" and obs.src_port == TARGET_PORT
    assert obs.dst_port == 41234


def test_요청_방향도_기록된다():
    # dst_port == PROXY_PORT 인 프레임 = outbound 요청
    frame = make_frame("127.0.0.1", "127.0.0.1", 41500, PROXY_PORT)
    session_id = SessionKey("127.0.0.1", "127.0.0.1", 41500, PROXY_PORT).session_id(1024)
    pipeline, verdicts = build(ScriptedDetector({session_id}),
                               frames=[frame for _ in range(WINDOW)])
    pipeline.run()

    obs = verdicts.get(session_id)
    assert obs.direction == "REQUEST"


def test_메인_컨테이너로_들어가는_트래픽은_탐지하지_않는다():
    pipeline, verdicts = build(AlwaysNormalDetector())
    for _ in range(WINDOW * 2):
        assert pipeline.process_frame(inbound_frame()) is None


def test_tcp가_아닌_프레임은_무시한다():
    pipeline, _ = build(AlwaysNormalDetector())
    frame = make_frame("127.0.0.1", "127.0.0.1", TARGET_PORT, 41234, proto=17)
    assert pipeline.process_frame(frame) is None


def test_세션이_다르면_윈도우가_따로_찬다():
    converter = WindowConverter(window=WINDOW)
    pipeline, _ = build(AlwaysNormalDetector(), converter=converter)

    for _ in range(WINDOW - 1):
        pipeline.process_frame(make_frame("127.0.0.1", "127.0.0.1", TARGET_PORT, 41234))
    # 다른 세션의 프레임 1개로는 첫 세션의 윈도우가 차지 않는다
    assert pipeline.process_frame(
        make_frame("127.0.0.1", "127.0.0.1", TARGET_PORT, 55555)
    ) is None


def test_소스의_프레임을_끝까지_처리한다():
    session_id = SessionKey("127.0.0.1", "127.0.0.1", TARGET_PORT, 41234).session_id(1024)
    frames = [outbound_response_frame() for _ in range(WINDOW)]
    pipeline, verdicts = build(ScriptedDetector({session_id}), frames=frames)

    pipeline.run()
    assert verdicts.get(session_id).is_malicious
