# -*- coding: utf-8 -*-
import asyncio

from traffic_handler import telemetry
from traffic_handler.ports import Detection, SessionObservation
from traffic_handler.telemetry import (
    TelemetryClient, build_event, session_label,
)

PROXY_META = {"serviceName": "post", "podName": "post-a", "podIp": "10.244.1.5",
              "nodeName": "worker-1", "namespace": "default"}


def obs(direction="REQUEST"):
    return SessionObservation(
        detection=Detection(is_malicious=True, score=-0.41),
        direction=direction,
        src_ip="10.244.1.5", src_port=48812, dst_ip="10.96.0.1", dst_port=443,
    )


def test_url이_없으면_비활성():
    c = TelemetryClient("", PROXY_META)
    assert not c.enabled
    c.emit(build_event(obs(), "DROP", "drop", "REQUEST_VERIFIER", False, "sig"))
    c.incr("benign")
    # 비활성이면 아무것도 쌓이지 않는다
    assert not c._events and not any(c._counts.values())


def test_세션_라벨은_방향에_무관하다():
    fwd = session_label("10.0.0.1", 1000, "10.0.0.2", 2000)
    bwd = session_label("10.0.0.2", 2000, "10.0.0.1", 1000)
    assert fwd == bwd


def test_build_event가_명세_필드를_채운다():
    e = build_event(obs(), "DROP", "drop", "REQUEST_VERIFIER", False, "GET|k:443|/x|q:|b:")
    assert e["direction"] == "REQUEST"
    assert e["verdict"] == "DROP" and e["category"] == "drop"
    assert e["verificationStage"] == "REQUEST_VERIFIER"
    assert e["verificationPassed"] is False
    assert e["modelVerdict"] == "ATTACK"
    assert e["ocsvmScore"] == -0.41
    assert e["srcIp"] == "10.244.1.5" and e["dstPort"] == 443
    # 백엔드가 채우는 필드는 넣지 않는다
    assert "peerServiceName" not in e and "eventId" not in e and "summary" not in e


def test_emit은_이벤트와_집계를_함께_쌓는다():
    c = TelemetryClient("http://backend", PROXY_META)
    c.emit(build_event(obs(), "DROP", "drop", "REQUEST_VERIFIER", False, "sig"))
    c.incr("benign")
    c.incr("benign")
    assert len(c._events) == 1
    assert c._counts["drop"] == 1
    assert c._counts["benign"] == 2


def test_flush가_페이로드를_구성하고_큐를_비운다():
    sent = {}

    class FakeResp:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class FakeSession:
        def post(self, url, json, timeout):
            sent["url"] = url
            sent["payload"] = json
            return FakeResp()

    c = TelemetryClient("http://backend", PROXY_META)
    c._session = FakeSession()
    c.emit(build_event(obs("RESPONSE"), "RELAY", "relay", "RESPONSE_CONSISTENCY", False, "sig"))
    c.incr("benign")

    asyncio.run(c._flush())

    assert sent["url"] == "http://backend/ingest/events"
    p = sent["payload"]
    assert p["proxy"]["serviceName"] == "post"
    assert p["windowStats"]["relay"] == 1
    assert p["windowStats"]["benign"] == 1
    assert len(p["events"]) == 1
    assert p["events"][0]["category"] == "relay"
    # flush 후 비워진다
    assert not c._events and not any(c._counts.values())


def test_전송_실패해도_예외가_전파되지_않는다():
    class BoomSession:
        def post(self, *a, **k):
            raise RuntimeError("backend down")

    c = TelemetryClient("http://backend", PROXY_META)
    c._session = BoomSession()
    c.emit(build_event(obs(), "DROP", "drop", "REQUEST_VERIFIER", False, "sig"))
    # 예외 없이 반환 — 트래픽 중계를 막지 않는다
    asyncio.run(c._flush())


def test_큐가_상한을_넘으면_오래된_것부터_버린다():
    c = TelemetryClient("http://backend", PROXY_META, queue_max=3)
    for i in range(5):
        c.emit(build_event(obs(), "DROP", "drop", "REQUEST_VERIFIER", False, "sig-%d" % i))
    assert len(c._events) == 3
    # 가장 오래된 sig-0, sig-1이 밀려나고 최신 3개가 남는다
    assert c._events[0]["signature"] == "sig-2"


# ── 목적지별 benign 집계 (peerStats) ────────────────────────────────────────

def _flush_payload(client):
    """_flush를 한 번 돌리고 전송된 페이로드를 돌려준다."""
    sent = {}

    class FakeResp:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class FakeSession:
        def post(self, url, json, timeout):
            sent["payload"] = json
            return FakeResp()

    client._session = FakeSession()
    asyncio.run(client._flush())
    return sent["payload"]


def _client():
    return TelemetryClient("http://backend", {"serviceName": "post"})


def test_benign은_목적지별로_나뉜다():
    """평시 엣지를 그릴 근거. cleared/drop/relay는 events가 dstIp를 나르지만
    benign은 개별 이벤트가 없어 여기서만 목적지를 알 수 있다."""
    client = _client()
    for _ in range(3):
        client.incr("benign", peer="10.0.0.9")
    client.incr("benign", peer="10.0.0.7")

    payload = _flush_payload(client)
    assert payload["peerStats"] == [
        {"dstIp": "10.0.0.7", "benign": 1},
        {"dstIp": "10.0.0.9", "benign": 3},
    ]
    assert payload["windowStats"]["benign"] == 4   # 합이 windowStats와 같다


def test_benign이_아닌_분류는_목적지를_세지_않는다():
    """events가 이미 dstIp와 함께 나른다. 두 번 세면 같은 사실이 두 경로로 갈라진다."""
    client = _client()
    client.incr("drop", peer="10.0.0.9")
    assert _flush_payload(client)["peerStats"] == []


def test_peer가_없으면_목적지_집계를_건너뛴다():
    client = _client()
    client.incr("benign")
    payload = _flush_payload(client)
    assert payload["peerStats"] == []
    assert payload["windowStats"]["benign"] == 1


def test_목적지가_상한을_넘으면_other로_접힌다():
    """모델이 스캔을 놓쳐 benign으로 흘릴 때의 안전망."""
    client = _client()
    for i in range(telemetry.MAX_PEERS + 10):
        client.incr("benign", peer="10.0.{}.{}".format(i // 256, i % 256))

    payload = _flush_payload(client)
    peers = {p["dstIp"]: p["benign"] for p in payload["peerStats"]}
    assert len(peers) == telemetry.MAX_PEERS + 1        # 상한 + other 한 칸
    assert peers[telemetry.OTHER_PEER] == 10
    # 접혀도 유실되지 않는다 — 합은 windowStats와 같다
    assert sum(peers.values()) == payload["windowStats"]["benign"]


def test_peerCount는_접힌_목적지까지_센다():
    """상한에 걸려 other로 합쳐져도 '목적지가 몇 개였나'는 남아야 한다.
    평시 10에서 갑자기 커지는 것 자체가 스캔 신호다."""
    client = _client()
    for i in range(telemetry.MAX_PEERS + 10):
        client.incr("benign", peer="10.0.{}.{}".format(i // 256, i % 256))
    assert _flush_payload(client)["peerCount"] == telemetry.MAX_PEERS + 10


def test_창이_끝나면_목적지_집계가_비워진다():
    client = _client()
    client.incr("benign", peer="10.0.0.9")
    _flush_payload(client)
    client.incr("benign", peer="10.0.0.7")
    payload = _flush_payload(client)
    assert payload["peerStats"] == [{"dstIp": "10.0.0.7", "benign": 1}]
    assert payload["peerCount"] == 1
