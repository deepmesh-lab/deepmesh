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


# --- 원래 목적지 복원 (iptables REDIRECT 보정) ------------------------------
#
# 탐지 경로는 lo에서 DNAT된 프레임(dst=127.0.0.1:9011)을 본다. 집행 경로가 등록한 원래
# 목적지로 되돌려야 컨버터의 포트 라우팅·세션 id·관측 dst가 원본을 기준으로 선다.

from traffic_handler.original_dst import OriginalDstRegistry


def _clock():
    _clock.t += 1
    return _clock.t
_clock.t = 0


def test_outbound_목적지가_원본으로_복원된다():
    # 탐지가 보는 프레임: 메인(10.244.1.5:5555) → 프록시(127.0.0.1:9011). DNAT된 것.
    frame = make_frame("10.244.1.5", "127.0.0.1", 5555, PROXY_PORT, b"\x16\x03\x01hello")
    registry = OriginalDstRegistry(ttl=100, clock=_clock)
    # 집행 경로가 원래 목적지(K8s API 10.96.0.1:443)를 등록했다고 하자.
    registry.register("10.244.1.5", 5555, "10.96.0.1", 443)

    seen = []
    class SpyConverter:
        max_sessions = 65536
        def push(self, session_id, frame):
            # 컨버터가 받는 프레임의 목적지가 원본(443)이어야 flow 라우팅을 탄다.
            import struct
            ip = frame[14:]
            ihl = (ip[0] & 0x0F) * 4
            dst_ip = ".".join(str(b) for b in ip[16:20])
            dst_port = struct.unpack("!H", ip[ihl + 2:ihl + 4])[0]
            seen.append((dst_ip, dst_port))
            return None

    adapter = DetectionAdapter(SpyConverter(), AlwaysNormalDetector())
    verdicts = VerdictStore(ttl=10.0)
    pipeline = DetectionPipeline(
        ListPacketSource([frame]), adapter, verdicts, TARGET_PORT, PROXY_PORT,
        original_dst=registry,
    )
    pipeline.run()

    assert seen, "컨버터가 프레임을 받아야 한다"
    assert seen[0] == ("10.96.0.1", 443), "컨버터가 DNAT된 9011이 아니라 원본 443을 봐야 한다"


def test_레지스트리에_없으면_DNAT된_값을_그대로_쓴다():
    # 매핑 전에 온 프레임 — 복원할 수 없으면 있는 그대로 처리(판정은 다음 프레임에 맡긴다).
    frame = make_frame("10.244.1.5", "127.0.0.1", 5555, PROXY_PORT, b"\x16\x03\x01hi")
    registry = OriginalDstRegistry(ttl=100, clock=_clock)

    captured = {}
    class SpyConverter:
        max_sessions = 65536
        def push(self, session_id, frame):
            import struct
            ip = frame[14:]; ihl = (ip[0] & 0x0F) * 4
            captured["dport"] = struct.unpack("!H", ip[ihl + 2:ihl + 4])[0]
            return None
    adapter = DetectionAdapter(SpyConverter(), AlwaysNormalDetector())
    pipeline = DetectionPipeline(
        ListPacketSource([frame]), adapter, VerdictStore(ttl=10.0),
        TARGET_PORT, PROXY_PORT, original_dst=registry,
    )
    pipeline.run()
    assert captured["dport"] == PROXY_PORT   # 복원 안 됨 → 9011 그대로


def test_목적지를_복원해도_방향은_요청으로_남는다():
    # 복원하면 dst_port가 PROXY_PORT가 아니라 원래 목적지 포트(8080)가 된다. 방향을
    # 복원 뒤에 읽으면 복원에 성공한 요청이 전부 방향 없음이 되어, 대시보드 이벤트의
    # direction이 빈다.
    frame = make_frame("10.244.1.5", "127.0.0.1", 5555, PROXY_PORT)
    registry = OriginalDstRegistry(ttl=100, clock=_clock)
    registry.register("10.244.1.5", 5555, "10.100.234.122", 8080)
    session_id = SessionKey("10.244.1.5", "10.100.234.122", 5555, 8080).session_id(1024)

    adapter = DetectionAdapter(WindowConverter(window=WINDOW), ScriptedDetector({session_id}))
    verdicts = VerdictStore(ttl=10.0)
    pipeline = DetectionPipeline(
        ListPacketSource([frame for _ in range(WINDOW)]), adapter, verdicts,
        TARGET_PORT, PROXY_PORT, original_dst=registry,
    )
    pipeline.run()

    obs = verdicts.get(session_id)
    assert obs.direction == "REQUEST"
    assert (obs.dst_ip, obs.dst_port) == ("10.100.234.122", 8080)
